import logging

from celery import current_task, shared_task
from django.contrib.auth import get_user_model
from django.utils import timezone

import events
from app import cache_safety, history_cache
from app.mixins import disable_fetch_releases
from integrations import import_progress
from integrations.imports import (
    anilist,
    audiobookshelf,
    goodreads,
    gpodder,
    grouvee,
    hardcover,
    helpers,
    hltb,
    imdb,
    kitsu,
    mal,
    mdblist,
    plex,
    pocketcasts,
    radarr,
    simkl,
    sonarr,
    steam,
    storygraph,
    storyteller,
    stremio,
    trakt,
    trakt_collection,
    trakt_export,
    xbox,
    yamtrack,
)
from integrations.jellyfin_sync import (
    JELLYFIN_PUSH_TASK_NAME,
    JellyfinPushSyncService,
    format_jellyfin_push_message,
)
from integrations.models import ImportRun
from integrations.plex_watchlist import PlexWatchlistSyncService
from integrations.tasks._import_helpers import (
    GOODREADS_IMPORT_TASK_NAME,
    LEGACY_GOODREADS_IMPORT_TASK_NAMES,
    _coerce_uploaded_file,
    format_import_message,
    format_watchlist_sync_message,
)
from integrations.tasks._plex_collection import update_collection_metadata_from_plex

logger = logging.getLogger(__name__)


def import_media(
    importer_func,
    identifier,
    user_id,
    mode,
    oauth_username=None,
    **extra_kwargs,
):
    """Handle the import process for different media services."""
    user = get_user_model().objects.get(id=user_id)
    task_id = current_task.request.id if current_task and current_task.request else None

    source = getattr(importer_func, "__module__", "").rsplit(".", 1)[-1]
    import_run = ImportRun.objects.create(user=user, source=source, task_id=task_id)

    try:
        with disable_fetch_releases(), import_progress.tracking(task_id, import_run.id):
            if oauth_username is None:
                imported_counts, warnings = importer_func(
                    identifier,
                    user,
                    mode,
                    **extra_kwargs,
                )
            else:
                imported_counts, warnings = importer_func(
                    identifier,
                    user,
                    mode,
                    username=oauth_username,
                    **extra_kwargs,
                )
    except Exception:
        ImportRun.objects.filter(id=import_run.id).update(
            status=ImportRun.Status.FAILED,
            finished_at=timezone.now(),
        )
        raise

    ImportRun.objects.filter(id=import_run.id).update(
        status=ImportRun.Status.COMPLETED,
        created_count=sum(imported_counts.values()),
        finished_at=timezone.now(),
    )

    # Imports run inside disable_fetch_releases(), so per-item calendar triggers are
    # suppressed and a catch-up reload is needed -- but only when something actually
    # landed. Recurring importers poll on a 2-hour schedule and usually import
    # nothing; firing an unscoped global reload each time was re-walking the whole
    # library (and holding the single celery-queue worker) for no reason.
    if any(imported_counts.values()):
        events.tasks.reload_calendar.delay()
    else:
        logger.info(
            "calendar_reload_skipped reason=no_items_imported importer=%s user_id=%s",
            getattr(importer_func, "__name__", importer_func),
            user_id,
        )

    # Importers rely heavily on bulk_create_with_history, which bypasses model signals.
    # Force-clear history cache so month view index pages don't keep stale "empty month"
    # payloads after imports (notably reproducible with SIMKL imports).
    history_cache.invalidate_history_cache(user.id, force=True)

    # bulk_create also bypasses the post_save signals that normally schedule a statistics
    # cache refresh. Trigger it explicitly so the hours card and activity overview reflect
    # the newly imported media without requiring a manual page reload or waiting for the
    # next scheduled Celery beat.
    from app import statistics_cache as _statistics_cache

    _statistics_cache.schedule_all_ranges_refresh(user.id)

    # Queue collection metadata update task for media server imports
    _queue_post_import_collection_update(user_id, importer_func)

    return format_import_message(imported_counts, warnings)


def _run_arr_import(service_name, importer_func, user_id, mode):
    """Run ARR imports without surfacing expected connection failures as task tracebacks."""
    try:
        return import_media(importer_func, None, user_id, mode)
    except helpers.MediaImportError as exc:
        logger.warning("%s import failed for user %s: %s", service_name, user_id, exc)
        return f"{service_name} import failed: {exc}"


def _queue_post_import_collection_update(user_id, importer_func):
    """Queue collection metadata update task after import if applicable.

    Args:
        user_id: User ID
        importer_func: The importer function that was called
    """
    # Check if this is a media server import that supports collection updates
    # Compare by function reference
    import integrations.imports.plex as plex_import_module

    if importer_func == plex_import_module.importer:
        # Queue Plex collection update (run after calendar reload with a delay)
        update_collection_metadata_from_plex.apply_async(
            args=("all", user_id),
            countdown=60,  # Run 60 seconds after import to allow calendar reload to complete
        )
        logger.info(
            "Queued post-import collection metadata update for user %s", user_id
        )
    # TODO: Add Jellyfin and Emby when their importers are available


@shared_task(name="Import from Trakt")
def import_trakt(user_id, mode, token=None, username=None):
    """Celery task for importing media data from Trakt.

    Can import using either OAuth (token provided) or public username.
    """
    return import_media(trakt.importer, token, user_id, mode, username)


@shared_task(name="Import from MDBList")
def import_mdblist(user_id, mode, username=None):
    """Celery task for importing tracking data from MDBList.

    The API key is decrypted from the user's MDBListAccount at run time so
    recurring schedules never persist it in PeriodicTask kwargs.
    """
    user = get_user_model().objects.get(id=user_id)
    account = getattr(user, "mdblist_account", None)
    if account is None:
        msg = "Connect your MDBList account before importing."
        raise helpers.MediaImportError(msg)
    api_key = helpers.decrypt_or_raise(account.api_key)
    return import_media(mdblist.importer, api_key, user_id, mode)


@shared_task(name="Import from SIMKL")
def import_simkl(token, user_id, mode, username=None, anime_destination="anime"):
    """Celery task for importing media data from SIMKL."""
    return import_media(
        simkl.importer,
        token,
        user_id,
        mode,
        anime_destination=anime_destination,
    )


@shared_task(name="Import from MyAnimeList")
def import_mal(username, user_id, mode):
    """Celery task for importing anime and manga data from MyAnimeList."""
    return import_media(mal.importer, username, user_id, mode)


@shared_task(name="Import from AniList")
def import_anilist(user_id, mode, token=None, username=None):
    """Celery task for importing media data from AniList."""
    return import_media(anilist.importer, token, user_id, mode, username)


@shared_task(name="Import from Kitsu")
def import_kitsu(username, user_id, mode):
    """Celery task for importing anime and manga data from Kitsu."""
    return import_media(kitsu.importer, username, user_id, mode)


# Task name stays "Import from Yamtrack": it is persisted in celery result
# and beat rows, and matched by name in users.models.
@shared_task(name="Import from Yamtrack")
def import_yamtrack(file, user_id, mode):
    """Celery task for importing a Floppy backup or Yamtrack CSV."""
    return import_media(yamtrack.importer, _coerce_uploaded_file(file), user_id, mode)


@shared_task(name="Import from HowLongToBeat")
def import_hltb(file, user_id, mode):
    """Celery task for importing media data from HowLongToBeat."""
    return import_media(hltb.importer, _coerce_uploaded_file(file), user_id, mode)


@shared_task(name="Import from Grouvee")
def import_grouvee(file, user_id, mode):
    """Celery task for importing game data from a Grouvee JSON export."""
    return import_media(grouvee.importer, _coerce_uploaded_file(file), user_id, mode)


@shared_task(name="Import Trakt collection CSV")
def import_trakt_collection_csv(file, user_id, mode):
    """Celery task for importing collection ownership from a Trakt CSV export."""
    return import_media(
        trakt_collection.importer,
        _coerce_uploaded_file(file),
        user_id,
        mode,
    )


@shared_task(name="Import Trakt data export")
def import_trakt_export(file, user_id, mode):
    """Celery task for importing a Trakt data export archive."""
    return import_media(
        trakt_export.importer,
        _coerce_uploaded_file(file),
        user_id,
        mode,
    )


@shared_task(name="Import from Steam")
def import_steam(username, user_id, mode):
    """Celery task for importing game data from Steam."""
    return import_media(steam.importer, username, user_id, mode)


@shared_task(name="Import from Xbox")
def import_xbox(user_id, mode="new"):
    """Celery task for importing game data from a connected Xbox account."""
    return import_media(xbox.importer, None, user_id, mode)


@shared_task(name="Import from Xbox (Recurring)")
def import_xbox_recurring(user_id, mode="new"):
    """Recurring import task for Xbox."""
    return import_media(xbox.importer, None, user_id, mode)


@shared_task(name="Import from IMDB")
def import_imdb(file, user_id, mode):
    """Celery task for importing media data from IMDB."""
    return import_media(imdb.importer, _coerce_uploaded_file(file), user_id, mode)


def _run_goodreads_import(file, user_id, mode):
    """Execute the Goodreads CSV import for any registered task alias."""
    return import_media(goodreads.importer, _coerce_uploaded_file(file), user_id, mode)


@shared_task(name=GOODREADS_IMPORT_TASK_NAME)
def import_goodreads(file, user_id, mode):
    """Celery task for importing media data from Goodreads."""
    return _run_goodreads_import(file, user_id, mode)


@shared_task(name=LEGACY_GOODREADS_IMPORT_TASK_NAMES[0])
def import_goodreads_legacy(file, user_id, mode):
    """Compatibility alias for the legacy Goodreads task name."""
    return _run_goodreads_import(file, user_id, mode)


@shared_task(name=LEGACY_GOODREADS_IMPORT_TASK_NAMES[1])
def import_goodreads_dotted(file, user_id, mode):
    """Compatibility alias for dotted Goodreads task references."""
    return _run_goodreads_import(file, user_id, mode)


@shared_task(name="Import from Hardcover")
def import_hardcover(file, user_id, mode):
    """Celery task for importing media data from Hardcover."""
    return import_media(hardcover.importer, _coerce_uploaded_file(file), user_id, mode)


@shared_task(name="Import from StoryGraph")
def import_storygraph(file, user_id, mode):
    """Celery task for importing media data from StoryGraph."""
    return import_media(storygraph.importer, _coerce_uploaded_file(file), user_id, mode)


@shared_task(name="Import from Plex")
def import_plex(library, user_id, mode, username=None):
    """Celery task for importing media data from Plex."""
    return import_media(plex.importer, library, user_id, mode)


@shared_task(name="Import from Radarr")
def import_radarr(user_id, mode="new", username=None):
    """Celery task for importing movie collection data from Radarr."""
    return _run_arr_import("Radarr", radarr.importer, user_id, mode)


@shared_task(name="Import from Radarr (Recurring)")
def import_radarr_recurring(user_id):
    """Recurring import task for Radarr."""
    return _run_arr_import("Radarr", radarr.importer, user_id, "new")


@shared_task(name="Import from Sonarr")
def import_sonarr(user_id, mode="new", username=None):
    """Celery task for importing TV collection data from Sonarr."""
    return _run_arr_import("Sonarr", sonarr.importer, user_id, mode)


@shared_task(name="Import from Sonarr (Recurring)")
def import_sonarr_recurring(user_id):
    """Recurring import task for Sonarr."""
    return _run_arr_import("Sonarr", sonarr.importer, user_id, "new")


@shared_task(name="Sync Plex Watchlist")
def sync_plex_watchlist(user_id, mode="watchlist"):
    """Celery task for syncing Plex Discover watchlist items."""
    from integrations.models import PlexAccount

    user = get_user_model().objects.get(id=user_id)
    account = getattr(user, "plex_account", None)
    if not account:
        msg = "Connect Plex before syncing the watchlist."
        raise helpers.MediaImportError(msg)

    try:
        sync_counts, warnings = PlexWatchlistSyncService(user, account).sync()
    except helpers.MediaImportError as exc:
        PlexAccount.objects.filter(user=user).update(
            watchlist_last_error=str(exc),
            watchlist_last_error_at=timezone.now(),
        )
        raise
    except Exception as exc:  # pragma: no cover - defensive
        PlexAccount.objects.filter(user=user).update(
            watchlist_last_error=str(exc),
            watchlist_last_error_at=timezone.now(),
        )
        raise

    PlexAccount.objects.filter(user=user).update(
        watchlist_last_synced_at=timezone.now(),
        watchlist_last_error="",
        watchlist_last_error_at=None,
    )

    if sync_counts.get("created") or sync_counts.get("removed"):
        events.tasks.reload_calendar.delay()

    return format_watchlist_sync_message(sync_counts, warnings)


@shared_task(name=JELLYFIN_PUSH_TASK_NAME)
def push_jellyfin_watched(user_id):
    """Celery task for pushing Floppy watched state to Jellyfin."""
    from integrations.models import JellyfinAccount

    user = get_user_model().objects.get(id=user_id)
    account = getattr(user, "jellyfin_account", None)
    if not account:
        msg = "Connect Jellyfin before syncing."
        raise helpers.MediaImportError(msg)

    try:
        push_counts, warnings = JellyfinPushSyncService(user, account).sync()
    except helpers.MediaImportError as exc:
        JellyfinAccount.objects.filter(user=user).update(
            connection_broken=True,
            last_error_message=str(exc),
        )
        raise

    JellyfinAccount.objects.filter(user=user).update(
        last_sync_at=timezone.now(),
        connection_broken=False,
        last_error_message="",
    )

    return format_jellyfin_push_message(push_counts, warnings)


@shared_task(name="Import from Audiobookshelf")
def import_audiobookshelf(user_id, mode="new"):
    """Celery task for importing audiobook progress from Audiobookshelf."""
    return import_media(audiobookshelf.importer, None, user_id, mode)


@shared_task(name="Import from Audiobookshelf (Recurring)")
def import_audiobookshelf_recurring(user_id):
    """Recurring import task for Audiobookshelf."""
    return import_media(audiobookshelf.importer, None, user_id, "new")


@shared_task(name="Import from Storyteller")
def import_storyteller(user_id, mode="new"):
    """Celery task for importing book reading progress from Storyteller."""
    return import_media(storyteller.importer, None, user_id, mode)


@shared_task(name="Import from Storyteller (Recurring)")
def import_storyteller_recurring(user_id):
    """Recurring import task for Storyteller."""
    return import_media(storyteller.importer, None, user_id, "new")


@shared_task(name="Import from Stremio")
def import_stremio(user_id, mode="new"):
    """Celery task for importing library watch state from Stremio."""
    return import_media(stremio.importer, None, user_id, mode)


@shared_task(name="Import from Stremio (Recurring)")
def import_stremio_recurring(user_id):
    """Recurring import task for Stremio."""
    return import_media(stremio.importer, None, user_id, "new")


@shared_task(name="Import from Pocket Casts")
def import_pocketcasts(user_id, mode="new"):
    """Celery task for importing podcast history from Pocket Casts."""
    lock_key = f"pocketcasts_import_lock_{user_id}"
    # The user is waiting on this, so an unreachable cache must not be read as
    # "already running" - that would refuse a manual import with no explanation
    # for as long as Redis was unwell (#521).
    if not cache_safety.acquire_lock(
        lock_key,
        timeout=600,
        on_error=cache_safety.ON_ERROR_PROCEED,
        value="1",
    ):
        logger.info(
            "Pocket Casts import already running for user %s, skipping", user_id
        )
        return "Skipped: import already in progress"
    try:
        return import_media(pocketcasts.importer, None, user_id, mode)
    finally:
        cache_safety.release_lock(lock_key)


@shared_task(name="Import from Pocket Casts (Recurring)")
def import_pocketcasts_history(user_id):
    """Recurring import task for Pocket Casts (called every 2 hours via Celery beat)."""
    lock_key = f"pocketcasts_import_lock_{user_id}"
    # Recurring, so skipping a run when the cache is unavailable is cheap - the
    # next one is two hours away and the manual path above stays open.
    if not cache_safety.acquire_lock(
        lock_key,
        timeout=600,
        on_error=cache_safety.ON_ERROR_SKIP,
        value="1",
    ):
        logger.info(
            "Pocket Casts import already running for user %s, skipping", user_id
        )
        return "Skipped: import already in progress"
    try:
        return import_media(pocketcasts.importer, None, user_id, "new")
    finally:
        cache_safety.release_lock(lock_key)


@shared_task(name="Import from GPodder")
def import_gpodder(user_id, mode="new"):
    """Celery task for importing podcast history from GPodder-compatible servers."""
    lock_key = f"gpodder_import_lock_{user_id}"
    # Fails open for the same reason as the Pocket Casts manual import above: a
    # user waiting on this must not be told "already in progress" because the
    # cache was briefly unreachable (#521).
    if not cache_safety.acquire_lock(
        lock_key,
        timeout=600,
        on_error=cache_safety.ON_ERROR_PROCEED,
        value="1",
    ):
        logger.info("GPodder import already running for user %s, skipping", user_id)
        return "Skipped: import already in progress"
    try:
        return import_media(gpodder.importer, None, user_id, mode)
    finally:
        cache_safety.release_lock(lock_key)


@shared_task(name="Import from GPodder (Recurring)")
def import_gpodder_recurring(user_id):
    """Recurring import task for GPodder-compatible servers."""
    lock_key = f"gpodder_import_lock_{user_id}"
    # Recurring, so skipping a run costs little; the manual path above stays open.
    if not cache_safety.acquire_lock(
        lock_key,
        timeout=600,
        on_error=cache_safety.ON_ERROR_SKIP,
        value="1",
    ):
        logger.info("GPodder import already running for user %s, skipping", user_id)
        return "Skipped: import already in progress"
    try:
        return import_media(gpodder.importer, None, user_id, "new")
    finally:
        cache_safety.release_lock(lock_key)
