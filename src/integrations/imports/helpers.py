import base64
import datetime
import hashlib
import json
import logging
import time
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from copy import copy

from cryptography.fernet import Fernet, InvalidToken
from django.apps import apps
from django.conf import settings
from django.contrib import messages
from django.utils import timezone
from django_celery_beat.models import CrontabSchedule, PeriodicTask
from requests import RequestException
from simple_history.utils import bulk_create_with_history

import app
from app import providers
from app.db_retry import run_retryable_db_operation
from app.history_cache_utils import history_deferred_item_fields
from app.models import Episode, MediaTypes, Status
from app.models.tv import _UNSET_END_DATE
from app.services.completion import normalize_completed_entries
from app.services.watch_state import (
    PROJECTED_MEDIA_TYPES,
    project_watch_states_bulk,
)
from app.signals import importer_replacing_rows
from integrations import import_progress
from integrations.models import ImportRun

logger = logging.getLogger(__name__)


# Rows an import wrote with bulk_create, which sends no post_save signal. Set by
# record_bulk_rows() for importers whose catch-up is scoped to what they wrote.
_bulk_rows: ContextVar[list | None] = ContextVar("import_bulk_rows", default=None)


@contextmanager
def record_bulk_rows():
    """Collect the rows ``bulk_create_media`` writes inside the block."""
    rows = []
    token = _bulk_rows.set(rows)
    try:
        yield rows
    finally:
        _bulk_rows.reset(token)


def note_bulk_rows(rows):
    """Record rows written without a save signal, so the import publishes their days."""
    sink = _bulk_rows.get()
    if sink is not None:
        sink.extend(rows)


# Noted by an importer whose write moved rows between libraries, which no day
# list describes; publishing then falls back to dropping every cached day.
FULL_REFRESH = object()


def note_full_refresh():
    """Ask the import to drop every cached day when it publishes."""
    note_bulk_rows([FULL_REFRESH])


def publish_everything(user_id):
    """Drop every cached History and Statistics day for one user."""
    from app import history_cache, statistics_cache

    # Importers rely on bulk_create_with_history, which bypasses model signals.
    # Force-clear history cache so month view index pages don't keep stale
    # "empty month" payloads after imports.
    history_cache.invalidate_history_cache(user_id, force=True)
    # The same bypass leaves statistics days unmarked: drop every day payload;
    # the background sync rebuilds them in budgeted slices while the last
    # published numbers keep being served.
    statistics_cache.invalidate_all_statistics_days(user_id, reason="media_import")


def publish_bulk_rows(user_id, rows):
    """Refresh History and Statistics for just the days bulk-written rows sit on.

    The blanket alternative drops every cached day, and a library of thousands
    of days then takes hours to rebuild, so a recurring poll that adds one row
    kept the worker busy until the next poll. Every day a row's dates
    touch is a superset of the days any History or Statistics placement uses.
    Undated rows have no day to refresh, but their status and score still feed
    the range totals, so they re-aggregate those.

    Returns whether the refresh stayed scoped; False means it dropped every day
    (see ``note_full_refresh``), so the sweep the import requested must stand.
    """
    from app import history_cache, statistics_sync

    if FULL_REFRESH in rows:
        publish_everything(user_id)
        return False

    day_keys = set()
    has_undated = False
    for row in rows:
        start, end = getattr(row, "start_date", None), getattr(row, "end_date", None)
        row_keys = set(history_cache.history_day_keys_for_range(start, end))
        row_keys.update(
            key for key in map(history_cache.history_day_key, (start, end)) if key
        )
        has_undated = has_undated or not row_keys
        day_keys.update(row_keys)
    if day_keys:
        history_cache.invalidate_history_days(
            user_id, day_keys=sorted(day_keys), force=True, reason="import_rows"
        )
        statistics_sync.mark_days(user_id, day_keys, reason="import_rows")
    if has_undated:
        statistics_sync.mark_aggregate(user_id, reason="import_rows")
    return True


class MediaImportError(Exception):
    """Custom exception for import errors."""


class ConnectionAuthError(MediaImportError):
    """The provider rejected our credentials (401/403).

    The one import failure that marks an account ``connection_broken``; see
    ``integrations.connection_health``.
    """


class MediaImportUnexpectedError(Exception):
    """Custom exception for unexpected import errors."""


def retry_on_lock(func, max_retries=5, base_delay=0.1, backoff=2.0):
    """Retry the callable when SQLite reports a lock or disk I/O error."""
    outcome = run_retryable_db_operation(
        func,
        mode="required",
        operation_name="database operation",
        operation_logger=logger,
        max_retries=max_retries,
        base_delay=base_delay,
        backoff=backoff,
    )
    return outcome.value


def mal_id_from_kitsu_mappings(mappings, media_type):
    """Return the raw MyAnimeList external id from a Kitsu mappings dict.

    ``mappings`` maps Kitsu's externalSite strings (e.g. "myanimelist/anime")
    to their externalId. Returns None when no MAL mapping is present.
    """
    return mappings.get(f"myanimelist/{media_type}")


def periodic_task_user_kwargs(user_id):
    """Return ``filter`` kwargs matching one user's periodic task by exact id.

    A bare ``kwargs__contains='"user_id": 1'`` also matches user 10's task, so
    the match must end at the closing brace or the next key.
    """
    return {"kwargs__regex": rf"[\"']user_id[\"']: {int(user_id)}[,}}]"}


def find_item_across_buckets(preferred_bucket=None, user=None, **identity):
    """Return an existing Item for an identity, preferring one library bucket.

    Every Item uniqueness constraint includes ``library_media_type``, and the
    same media identity can legitimately live in more than one bucket (grouped
    anime is stored on TV rows, and episodes auto-created for a tracked season
    inherit the show's bucket rather than the default 'episode' one). A
    ``get``/``get_or_create`` keyed only on the identity fields therefore raises
    ``MultipleObjectsReturned`` as soon as two buckets exist. Reuse an existing
    row instead of failing or creating a third, divergent one - preferring the
    row ``user`` already tracks (so another user's bucket never pulls them onto
    a second row), then the caller's bucket, then the oldest row so repeat runs
    stay stable.
    """
    candidates = list(app.models.Item.objects.filter(**identity).order_by("id"))
    if not candidates:
        return None
    if user is not None and len(candidates) > 1:
        tracked_ids = _item_ids_tracked_by(user, identity.get("media_type"), candidates)
        for item in candidates:
            if item.id in tracked_ids:
                return item
    if preferred_bucket:
        for item in candidates:
            if item.library_media_type == preferred_bucket:
                return item
    return candidates[0]


def _item_ids_tracked_by(user, media_type, items):
    """Return the ids among ``items`` that ``user`` has a tracking row for."""
    try:
        model = apps.get_model(app_label="app", model_name=media_type)
    except (LookupError, ValueError):
        return set()
    if not any(field.name == "user" for field in model._meta.fields):
        return set()
    return set(
        model.objects.filter(user=user, item__in=items).values_list(
            "item_id",
            flat=True,
        ),
    )


def get_or_create_item_across_buckets(
    preferred_bucket=None,
    user=None,
    defaults=None,
    **identity,
):
    """``get_or_create`` for an Item identity that tolerates several buckets.

    Returns ``(item, created)`` like ``get_or_create``, but reuses a row from
    any library bucket (see ``find_item_across_buckets``) instead of raising
    ``MultipleObjectsReturned`` when the identity exists in more than one.
    """
    item = find_item_across_buckets(preferred_bucket, user, **identity)
    if item is not None:
        return item, False
    return app.models.Item.objects.get_or_create(defaults=defaults, **identity)


# Importers read identity fields off the preloaded items, never these. Loading
# them for a whole library (``watch_providers`` is ~146 KiB a title) ran a large
# Trakt export import out of memory before it wrote anything (#1252).
PRELOAD_DEFERRED_ITEM_FIELDS = history_deferred_item_fields("item")
# Items projected per query after a bulk import.
PROJECTION_BATCH_SIZE = 500


def get_existing_media(user):
    """Get all existing media for the user to check against during import."""
    excluded_types = [MediaTypes.SEASON.value, MediaTypes.EPISODE.value]
    valid_types = [value for value in MediaTypes.values if value not in excluded_types]
    existing = defaultdict(lambda: defaultdict(dict))

    for media_type in valid_types:
        media_model = apps.get_model(app_label="app", model_name=media_type)

        for media in (
            media_model.objects.filter(user=user)
            .select_related("item")
            .defer(*PRELOAD_DEFERRED_ITEM_FIELDS)
        ):
            existing[media_type][media.item.source][media.item.media_id] = media

    counts = [
        f"{media_type}: {sum(len(source_dict) for source_dict in media_dict.values())}"
        for media_type, media_dict in existing.items()
    ]
    logger.debug("Existing media for user %s: %s", user.username, ", ".join(counts))
    return existing


def get_existing_children(user):
    """Get existing Season/Episode identity keys, for "new" mode healing.

    ``get_existing_media`` only tracks top-level shows, so a season/episode
    row's "new" mode existence check normally collapses to "does the parent
    show exist" (see ``should_process_media``). That makes an already-tracked
    show block every season/episode row for it, even ones the show doesn't
    have yet. This tracks season/episode identity directly so callers can
    check a row's own granularity instead.
    """
    existing = {
        MediaTypes.SEASON.value: defaultdict(dict),
        MediaTypes.EPISODE.value: defaultdict(dict),
    }
    for season in (
        app.models.Season.objects.filter(user=user)
        .select_related("item")
        .defer(*PRELOAD_DEFERRED_ITEM_FIELDS)
    ):
        item = season.item
        existing[MediaTypes.SEASON.value][item.source][
            (item.media_id, item.season_number)
        ] = season
    for episode in (
        app.models.Episode.objects.filter(related_season__user=user)
        .select_related("item")
        .defer(*PRELOAD_DEFERRED_ITEM_FIELDS)
    ):
        item = episode.item
        existing[MediaTypes.EPISODE.value][item.source][
            (item.media_id, item.season_number, item.episode_number)
        ] = episode
    return existing


def get_deleted_media(user):
    """Get media the user explicitly deleted, so imports don't recreate it."""
    deleted = defaultdict(lambda: defaultdict(set))
    for tombstone in app.models.DeletedMedia.objects.filter(user=user):
        deleted[tombstone.media_type][tombstone.source].add(tombstone.media_id)
    return deleted


def should_process_media(
    existing_media,
    to_delete,
    media_type,
    source,
    media_id,
    mode,
    deleted_media=None,
    skip_existing=True,
):
    """Determine if a media item should be processed based on mode.

    skip_existing=False lets callers with their own per-event dedupe (e.g.
    Plex TV episode history, where a show already being tracked shouldn't
    block newly watched episodes of it) route an existing item through the
    overwrite/deleted-media handling below without a blanket "new mode" skip.
    """
    if deleted_media and media_id in deleted_media[media_type][source]:
        logger.debug(
            "Skipping deleted %s: %s (user deleted this locally)",
            media_type,
            media_id,
        )
        return False

    exists = media_id in existing_media[media_type][source]

    if mode == "new" and exists and skip_existing:
        # In "new" mode, skip if media already exists
        logger.debug(
            "Skipping existing %s: %s (mode: new)",
            media_type,
            media_id,
        )
        return False

    if mode == "overwrite" and exists:
        # In "overwrite" mode, add to the deletion list
        logger.debug(
            "Adding existing %s to deletion list: %s (mode: overwrite)",
            media_type,
            media_id,
        )
        to_delete[media_type][source].add(media_id)

    return True


def cleanup_existing_media(to_delete, user):
    """Delete existing media if in overwrite mode."""
    for media_type, sources in to_delete.items():
        if not sources:
            continue

        model = apps.get_model(app_label="app", model_name=media_type)
        total_deleted = 0

        for source, media_ids in sources.items():
            if not media_ids:
                continue

            def delete_media(model=model, media_ids=media_ids, source=source):
                return model.objects.filter(
                    item__media_id__in=media_ids,
                    item__source=source,
                    user=user,
                ).delete()

            with importer_replacing_rows():
                deleted_count, _ = retry_on_lock(delete_media)
            total_deleted += deleted_count

        if total_deleted > 0:
            logger.info(
                "Deleted %s %s objects for user %s in overwrite mode",
                total_deleted,
                media_type,
                user,
            )


def update_season_references(seasons, user):
    """Update season references with actual TV instances.

    When bulk_create skips existing TV shows, seasons would still reference
    the unsaved TV instances. This updates those references to point to
    the existing TV shows in the database, preventing the ValueError about
    unsaved related objects during bulk creation of seasons.
    """
    # Get existing TV shows from database
    existing_tv = {
        tv.item.media_id: tv
        for tv in app.models.TV.objects.filter(
            user=user,
            item__media_id__in=[season.item.media_id for season in seasons],
        )
    }

    # Update references
    for season in seasons:
        media_id = season.item.media_id
        if media_id in existing_tv:
            season.related_tv = existing_tv[media_id]
            logger.debug(
                "Updated new season %s with existing TV %s",
                season,
                existing_tv[media_id],
            )


def update_episode_references(episodes, user):
    """Update episode references with actual Season instances.

    When bulk_create skips existing seasons, episodes would still reference
    the unsaved season instances. This updates those references to point to
    the existing seasons in the database, preventing the ValueError about
    unsaved related objects during bulk creation of episodes.
    """
    # Create mapping of season instances
    existing_seasons = {
        (season.item.media_id, season.item.season_number): season
        for season in app.models.Season.objects.filter(
            user=user,
            item__media_id__in={episode.item.media_id for episode in episodes},
        )
    }

    # Update references
    for episode in episodes:
        season_key = (
            episode.item.media_id,
            episode.item.season_number,
        )
        if season_key in existing_seasons:
            episode.related_season = existing_seasons[season_key]
            logger.debug(
                "Updated new episode %s with existing season %s",
                episode,
                existing_seasons[season_key],
            )


def update_podcast_references(podcasts):
    """Link imported Podcast rows to an existing PodcastEpisode/PodcastShow.

    CSV-imported Podcast rows only carry an Item (media_id=episode_uuid,
    source=show.source); if that episode's show is already tracked locally,
    look it up here so the show's episode list can find this play (see
    issue #1048) instead of leaving show/episode unset.
    """
    media_ids = {podcast.item.media_id for podcast in podcasts if podcast.item.media_id}
    if not media_ids:
        return

    existing_episodes = {
        (episode.episode_uuid, episode.show.source): episode
        for episode in app.models.PodcastEpisode.objects.select_related(
            "show",
        ).filter(episode_uuid__in=media_ids)
    }

    for podcast in podcasts:
        key = (podcast.item.media_id, podcast.item.source)
        episode = existing_episodes.get(key)
        if episode:
            podcast.episode = episode
            podcast.show = episode.show


def _ordered_media_types(bulk_media_list):
    """Return media types in creation order with dependency types first."""
    ordered_types = []
    seen = set()

    for media_type in (
        MediaTypes.TV.value,
        MediaTypes.SEASON.value,
        MediaTypes.EPISODE.value,
    ):
        if media_type in bulk_media_list:
            ordered_types.append(media_type)
            seen.add(media_type)

    ordered_types.extend(
        media_type for media_type in bulk_media_list if media_type not in seen
    )

    return ordered_types


def _fetch_season_metadata_with_retry(season, max_retries=3, base_delay=0.5):
    """Fetch season metadata, retrying transient network failures.

    A single dropped connection is common when a bulk import fires off
    metadata requests for many shows back-to-back; without a retry here
    that one blip permanently strands the season at Completed with zero
    episodes (see issue #471). Provider errors that aren't transient (e.g.
    a 404 for a season TMDB doesn't have) are raised immediately since
    retrying them cannot succeed.
    """
    attempt = 0
    while True:
        try:
            return providers.services.get_media_metadata(
                MediaTypes.SEASON.value,
                season.item.media_id,
                season.item.source,
                [season.item.season_number],
            )
        except RequestException:
            attempt += 1
            if attempt >= max_retries:
                raise
            time.sleep(base_delay * attempt)


def _backfill_completed_season_episodes(seasons, *, prepare_only=False):
    """Create the missing Episode rows for seasons bulk-created as Completed.

    Bulk imports persist Season instances via bulk_create, which bypasses
    Season.save() and the episode-completion fan-out it normally performs
    (see Season.save() in app/models/tv.py). A season imported directly as
    Completed with no per-episode history (e.g. a rating-only import) would
    otherwise end up with zero Episode rows, making it invisible to
    exports/statistics that key off episode data.

    Returns warning messages for seasons that could not be backfilled, so
    the importer can surface them to the user instead of only logging.
    """
    completed_seasons = [
        season
        for season in seasons
        if season.pk is not None and season.status == Status.COMPLETED.value
    ]
    if not completed_seasons:
        return ([], []) if prepare_only else []

    existing_season_ids = set(
        Episode.objects.filter(
            related_season__in=completed_seasons,
        )
        .values_list("related_season_id", flat=True)
        .distinct(),
    )

    warnings = []
    episodes_to_create = []
    for season in completed_seasons:
        if season.pk in existing_season_ids:
            continue
        try:
            season_metadata = _fetch_season_metadata_with_retry(season)
            episodes_to_create.extend(
                season.get_remaining_eps(
                    season_metadata,
                    # A season that arrived with a known watched date fans out
                    # to that date. Without this the fabricated episodes take
                    # the user's preference, which defaults to "now" — so an
                    # import of old history stamps every invented episode with
                    # the import time and the show reads as watched today.
                    # A rating-only season carries only its history date.
                    end_date=getattr(
                        season,
                        "_pending_end_date",
                        getattr(season, "_history_date", _UNSET_END_DATE),
                    ),
                ),
            )
        except (
            providers.services.ProviderAPIError,
            RequestException,
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            logger.warning(
                "Skipping episode backfill due to missing metadata for %s S%s: %s",
                season.item.media_id,
                season.item.season_number,
                error,
            )
            warnings.append(
                f"{season.item.title} S{season.item.season_number}: imported as "
                f"Completed but episode data could not be fetched ({error}). "
                "Re-import in overwrite mode once the issue clears to fill in "
                "the missing episodes.",
            )

    if prepare_only:
        return episodes_to_create, warnings
    if episodes_to_create:
        created_episodes = bulk_create_with_history(
            episodes_to_create,
            Episode,
            batch_size=500,
        )
        note_bulk_rows(created_episodes)
        normalize_completed_entries(created_episodes)

    return warnings


def _has_unique_user_item_constraint(model):
    """Return whether model enforces one row per user/item pair."""
    return any(
        tuple(getattr(constraint, "fields", ())) == ("user", "item")
        for constraint in model._meta.constraints
    )


def _merge_duplicate_media_row(existing, duplicate):
    """Fold non-empty imported values from duplicate into the kept row."""
    for field in duplicate._meta.fields:
        if field.primary_key or field.name in {"created_at", "item", "user"}:
            continue
        value = getattr(duplicate, field.name)
        if value not in (None, ""):
            setattr(existing, field.name, value)

    if hasattr(duplicate, "_history_date"):
        existing._history_date = duplicate._history_date


def _deduplicate_unique_user_item_rows(model, bulk_media):
    """Remove duplicate unsaved rows that would violate a user/item import key."""
    if not _has_unique_user_item_constraint(model):
        return bulk_media

    deduplicated = []
    by_user_item = {}
    for media_obj in bulk_media:
        key = (media_obj.user_id, media_obj.item_id)
        existing = by_user_item.get(key)
        if existing is None:
            by_user_item[key] = media_obj
            deduplicated.append(media_obj)
            continue

        _merge_duplicate_media_row(existing, media_obj)

    return deduplicated


def _unique_identity_fields(model):
    """Return the DB columns that identify one of ``model``'s unique rows.

    Only the tracking models imports bulk-create have a uniqueness contract:
    a TV show is one row per user/item, and a season is one row per
    user/related TV/item. Everything else (movies, episodes, plays) may
    legitimately have several rows for the same item.
    """
    constraints = {
        tuple(getattr(constraint, "fields", ()))
        for constraint in model._meta.constraints
    }
    if ("user", "item") in constraints:
        return ("user_id", "item_id")
    if ("related_tv", "item") in constraints:
        return ("user_id", "related_tv_id", "item_id")
    return None


def _reuse_persisted_unique_rows(model, bulk_media):
    """Drop queued rows that another writer already stored during the import.

    Importers decide what is new against a snapshot taken at the start of the
    run. A tracking row written in the meantime - by a webhook, a sync, or a
    second import - is missing from that snapshot, so the queued duplicate
    hits the unique constraint at save time and aborts the import (#1518).
    The database is authoritative: reuse the stored row, keeping its values,
    and skip the queued insert.
    """
    identity_fields = _unique_identity_fields(model)
    if identity_fields is None or not bulk_media:
        return bulk_media

    manager = getattr(model, "all_objects", model._default_manager)
    stored = {}
    for start in range(0, len(bulk_media), PROJECTION_BATCH_SIZE):
        filters = defaultdict(set)
        for row in bulk_media[start : start + PROJECTION_BATCH_SIZE]:
            for field in identity_fields:
                value = getattr(row, field)
                if value is not None:
                    filters[field].add(value)
        if len(filters) != len(identity_fields):
            continue
        for row in manager.filter(
            **{f"{field}__in": values for field, values in filters.items()},
        ):
            stored[tuple(getattr(row, field) for field in identity_fields)] = row
    if not stored:
        return bulk_media

    retained = []
    reused = 0
    for row in bulk_media:
        key = tuple(getattr(row, field) for field in identity_fields)
        existing = stored.get(key)
        if existing is None:
            retained.append(row)
            continue

        # Mirror the stored row so callers (chunk receipts, parent hydration)
        # see an already-persisted instance instead of an unsaved duplicate.
        for field in model._meta.concrete_fields:
            setattr(row, field.attname, getattr(existing, field.attname))
        row._state.adding = False
        reused += 1

    if reused:
        logger.info(
            "Reused %s existing %s rows written during the import",
            reused,
            model._meta.model_name,
        )
    return retained


def _deduplicate_season_related_tv_item_rows(seasons):
    """Remove duplicate unsaved seasons that would violate the related_tv/item key.

    Two importer entries can independently queue a Season for what turns out
    to be the same show/season once update_season_references() repoints both
    at the same persisted TV row - only visible after that reference fix-up.
    """
    deduplicated = []
    by_related_tv_item = {}
    for season in seasons:
        related_tv_pk = season.related_tv.pk if season.related_tv_id else None
        key = (
            related_tv_pk if related_tv_pk is not None else f"unsaved:{id(season.related_tv)}",
            season.item_id,
        )
        existing = by_related_tv_item.get(key)
        if existing is None:
            by_related_tv_item[key] = season
            deduplicated.append(season)
            continue

        _merge_duplicate_media_row(existing, season)

    return deduplicated


def prepare_bulk_media(bulk_media_list, user, *, exclude_tv_ids=(), exclude_season_ids=(), prepare_only=False):
    """Resolve incoming coordinates before the durable persistence boundary."""
    from integrations.episode_orders import resolve_incoming, season_for_target

    # A source season's aggregate status is not a destination season status:
    # alternate orders may split or combine those groups.
    active_shows = set(
        app.models.TV.objects.filter(
            user=user, active_episode_order__isnull=False,
        ).exclude(pk__in=exclude_tv_ids).values_list("item__source", "item__media_id"),
    )

    # Importers build rows using their source provider's numbering. Resolve
    # before persistence so those numbers never become active-order numbers.
    # Resolution is per episode and only ever matches a show with an active
    # order, so a user with none skips it: it cost ~3 queries per episode, two
    # thirds of the time this function spent on a large history import.
    ordered_episodes = []
    planned_seasons = {}
    for episode in bulk_media_list.get(MediaTypes.EPISODE.value, []):
        item = episode.item
        if not active_shows or item.episode_order_id:
            ordered_episodes.append(episode)
            continue
        targets = resolve_incoming(
            user, item.media_id, item.source, item.season_number,
            item.episode_number, integration="import",
        )
        if targets is None:
            ordered_episodes.append(episode)
            continue
        for target in targets:
            mapped = copy(episode)
            mapped.pk = None
            mapped.item = target
            if prepare_only:
                key = (target.episode_order_id, target.season_number)
                if key not in planned_seasons:
                    planned_seasons[key] = season_for_target(user, target, prepare_only=True)
                mapped.related_season = planned_seasons[key]
            else:
                mapped.related_season = season_for_target(user, target)
            ordered_episodes.append(mapped)
    if MediaTypes.EPISODE.value in bulk_media_list:
        bulk_media_list[MediaTypes.EPISODE.value] = ordered_episodes

    if MediaTypes.SEASON.value in bulk_media_list:
        bulk_media_list[MediaTypes.SEASON.value] = [
            season for season in bulk_media_list[MediaTypes.SEASON.value]
            if season.item.episode_order_id
            or (season.item.source, season.item.media_id) not in active_shows
        ]
    if prepare_only:
        new_parents = [season for season in planned_seasons.values() if season.pk is None]
        if new_parents:
            bulk_media_list.setdefault(MediaTypes.SEASON.value, []).extend(new_parents)
        # Preserve the existing reference helpers' media-id/coordinate policy,
        # but decide once against the post-delete/post-parent-create graph.
        # A resumed chunk must not reinterpret these references after a user
        # changes an episode order or provider identity.
        seasons = bulk_media_list.get(MediaTypes.SEASON.value, [])
        now = timezone.now().timestamp()
        existing_tvs = list(app.models.TV.objects.filter(
            user=user, item__media_id__in={row.item.media_id for row in seasons},
        ).exclude(pk__in=exclude_tv_ids).select_related("item").only(
            "id", "item_id", "user_id", "created_at", "item__media_id",
        ))
        tvs = existing_tvs + _deduplicate_unique_user_item_rows(app.models.TV, bulk_media_list.get(MediaTypes.TV.value, []))
        ordered_tvs = sorted(enumerate(tvs), key=lambda pair: (
            pair[1].item_id, -(pair[1].created_at.timestamp() if pair[1].created_at else now),
            -pair[0] if pair[1].pk is None else 0,
        ))
        by_media_id = {row.item.media_id: row for _index, row in ordered_tvs}
        for season in seasons:
            if season.item.media_id in by_media_id:
                season.related_tv = by_media_id[season.item.media_id]
        # Canonicalize before splitting; two unsaved references can collapse
        # onto one persisted TV, including across chunk boundaries.
        retained = []
        canonical = {}
        for season in seasons:
            key = (season.user_id, season.related_tv.item_id, season.item_id)
            if key in canonical:
                _merge_duplicate_media_row(canonical[key], season)
            else:
                canonical[key] = season
                retained.append(season)
        if seasons:
            bulk_media_list[MediaTypes.SEASON.value] = retained
        episodes = bulk_media_list.get(MediaTypes.EPISODE.value, [])
        existing_seasons = list(app.models.Season.objects.filter(
            user=user, item__media_id__in={row.item.media_id for row in episodes},
        ).exclude(pk__in=exclude_season_ids).select_related("item", "related_tv").only(
            "id", "item_id", "user_id", "created_at", "related_tv", "related_tv__item_id",
            "item__media_id", "item__season_number",
        ))
        candidates = existing_seasons + retained
        ordered_seasons = sorted(enumerate(candidates), key=lambda pair: (
            pair[1].item_id, -(pair[1].created_at.timestamp() if pair[1].created_at else now),
            -pair[0] if pair[1].pk is None else 0,
        ))
        by_coordinate = {(row.item.media_id, row.item.season_number): row for _index, row in ordered_seasons}
        for episode in episodes:
            key = (episode.item.media_id, episode.item.season_number)
            if key in by_coordinate:
                episode.related_season = by_coordinate[key]
        return new_parents
    return None



def bulk_create_media(bulk_media_list, user, *, backfill_completed=True, prepared=False, normalize=True):
    """Bulk create all media objects.

    Returns warning messages for any episodes skipped because no matching
    season could be found, and for any seasons whose Completed-status
    episode backfill failed, for callers that want to surface them.
    """
    warnings = []
    projected_item_ids = set()
    if not prepared:
        prepare_bulk_media(bulk_media_list, user)

    for media_type in _ordered_media_types(bulk_media_list):
        bulk_media = bulk_media_list[media_type]
        if not bulk_media:
            continue

        model = apps.get_model(app_label="app", model_name=media_type)
        bulk_media = _deduplicate_unique_user_item_rows(model, bulk_media)

        import_run_id = import_progress.get_current_import_run_id()
        import_source = ""
        if import_run_id:
            import_source = (
                ImportRun.objects.filter(id=import_run_id)
                .values_list("source", flat=True)
                .first()
                or ""
            )
            for media_obj in bulk_media:
                media_obj.import_run_id = import_run_id
                if import_source and not media_obj.entry_source:
                    media_obj.entry_source = import_source

        logger.info("Bulk importing %s", media_type)

        # Update references for seasons and episodes
        if media_type == MediaTypes.SEASON.value and not prepared:
            logger.info("Updating references for season to existing TV shows")
            update_season_references(bulk_media, user)
            bulk_media = _deduplicate_season_related_tv_item_rows(bulk_media)
        elif media_type == MediaTypes.EPISODE.value and not prepared:
            logger.info(
                "Updating references for episodes to existing TV seasons",
            )
            update_episode_references(bulk_media, user)
            resolved_episodes = []
            skipped_season_keys = defaultdict(int)
            for episode in bulk_media:
                if episode.related_season_id is not None:
                    resolved_episodes.append(episode)
                    continue
                # related_season_id can still read empty here for a
                # resolvable episode: bulk_create()'s own
                # _prepare_related_fields_for_save() re-derives the column
                # from a *cached* related_season object's pk right before
                # insert (e.g. an importer that linked an episode directly to
                # a not-yet-created Season instance). hasattr() is the safe
                # way to probe that cache: accessing .related_season on a
                # non-nullable FK with nothing cached and no id raises
                # RelatedObjectDoesNotExist (an AttributeError subclass).
                if (
                    hasattr(episode, "related_season")
                    and episode.related_season.pk is not None
                ):
                    resolved_episodes.append(episode)
                    continue
                skipped_season_keys[
                    (episode.item.media_id, episode.item.season_number)
                ] += 1
            if skipped_season_keys:
                warnings.append(
                    "Skipped {count} episode(s) with no matching season for: "
                    "{keys}. Re-import once those seasons have been "
                    "tracked.".format(
                        count=sum(skipped_season_keys.values()),
                        keys=", ".join(
                            f"{media_id} S{season_number}"
                            for media_id, season_number in sorted(
                                skipped_season_keys,
                            )
                        ),
                    ),
                )
            bulk_media = resolved_episodes
            bulk_media_list[media_type] = bulk_media
        elif media_type == MediaTypes.PODCAST.value:
            logger.info("Updating references for podcasts to existing episodes")
            update_podcast_references(bulk_media)

        bulk_media = _reuse_persisted_unique_rows(model, bulk_media)
        bulk_media_list[media_type] = bulk_media
        if not bulk_media:
            continue

        # Imports are written as the user, so the reason is what tells an
        # imported status apart from one the user set (#1133).
        change_reason = (
            f"{import_source.replace('_', ' ').capitalize()} import"
            if import_source
            else "Import"
        )

        def create_media(
            bulk_media=bulk_media,
            model=model,
            change_reason=change_reason,
        ):
            return bulk_create_with_history(
                bulk_media,
                model,
                batch_size=500,
                default_user=user,
                default_date=timezone.now(),
                default_change_reason=change_reason,
            )

        created_media = retry_on_lock(create_media)
        note_bulk_rows(created_media)
        if normalize:
            normalize_completed_entries(created_media)
        if media_type in PROJECTED_MEDIA_TYPES:
            projected_item_ids.update(
                row.item_id for row in created_media if row.item_id is not None
            )

    # Run after every media type (including any episodes the importer supplied
    # directly) has been persisted, so the "does this season already have
    # episodes" check below sees the importer's own episodes too.
    bulk_seasons = bulk_media_list.get(MediaTypes.SEASON.value)
    if bulk_seasons and backfill_completed:
        warnings.extend(
            retry_on_lock(
                lambda: _backfill_completed_season_episodes(bulk_seasons),
            ),
        )
        _project_season_episodes(bulk_seasons)
    project_imported_watch_state(user, projected_item_ids)
    return warnings


def _item_key(spec):
    return (
        spec["media_id"],
        spec["source"],
        spec["media_type"],
        spec["library_media_type"] or spec["media_type"],
        spec["season_number"],
        spec["episode_number"],
    )


def bulk_resolve_items(specs):
    """Return ``{key: Item}`` for specs, creating the missing Items in bulk.

    Replaces a ``get_or_create`` per row (a SELECT, a SAVEPOINT, an INSERT and
    the Item post_save work) with one read plus one insert per chunk. Each spec
    is a dict with ``media_id``, ``source``, ``media_type``,
    ``library_media_type``, ``season_number``, ``episode_number``, ``title`` and
    ``image``. Existing rows are never changed. The backfills the Item post_save
    handler would queue for a new Item are queued together afterwards.
    """
    item_model = app.models.Item
    by_key = {_item_key(spec): spec for spec in specs}
    if not by_key:
        return {}

    def fetch(keys):
        found = {}
        media_ids = list({key[0] for key in keys})
        for start in range(0, len(media_ids), PROJECTION_BATCH_SIZE):
            for item in item_model.objects.filter(
                media_id__in=media_ids[start : start + PROJECTION_BATCH_SIZE],
            ).defer("watch_providers"):
                key = (
                    item.media_id,
                    item.source,
                    item.media_type,
                    item.library_media_type,
                    item.season_number,
                    item.episode_number,
                )
                if key in keys:
                    found[key] = item
        return found

    found = fetch(by_key.keys())
    missing = [key for key in by_key if key not in found]
    if missing:
        item_model.objects.bulk_create(
            [
                item_model(
                    media_id=key[0],
                    source=key[1],
                    media_type=key[2],
                    library_media_type=key[3],
                    season_number=key[4],
                    episode_number=key[5],
                    title=by_key[key]["title"],
                    image=by_key[key]["image"],
                )
                for key in missing
            ],
            ignore_conflicts=True,
        )
        created = fetch(set(missing))
        found.update(created)
        _enqueue_new_item_backfills(list(created.values()))
    return found


def _enqueue_new_item_backfills(items):
    """Queue what Item's post_save handler queues for a brand-new Item."""
    from app import signals as app_signals
    from app.tasks_credits import enqueue_credits_backfill_items
    from app.tasks_genre import enqueue_genre_backfill_items
    from app.tasks_runtime import enqueue_runtime_backfill_items

    if settings.TESTING or app_signals.media_change_side_effects_suppressed():
        return
    sources = app_signals
    runtime_ids, genre_ids, credit_ids = [], [], []
    for item in items:
        media_type = item.media_type
        if (
            item.source in sources.RUNTIME_BACKFILL_SOURCES
            and media_type
            in (MediaTypes.MOVIE.value, MediaTypes.TV.value, MediaTypes.ANIME.value)
            and item.runtime_minutes in (None, 0)
        ):
            runtime_ids.append(item.id)
        if (
            item.source in sources.GENRE_BACKFILL_SOURCES
            and media_type
            in (
                MediaTypes.MOVIE.value,
                MediaTypes.TV.value,
                MediaTypes.ANIME.value,
                MediaTypes.GAME.value,
                MediaTypes.BOARDGAME.value,
            )
            and not item.genres
        ):
            genre_ids.append(item.id)
        if item.source == "tmdb" and media_type in (
            MediaTypes.MOVIE.value,
            MediaTypes.TV.value,
            MediaTypes.SEASON.value,
        ):
            credit_ids.append(item.id)
    if runtime_ids:
        enqueue_runtime_backfill_items(runtime_ids)
    if genre_ids:
        enqueue_genre_backfill_items(genre_ids)
    if credit_ids:
        enqueue_credits_backfill_items(credit_ids)


def project_imported_watch_state(user, item_ids):
    """Project canonical watched state for items an import bulk-created rows for.

    bulk_create fires no save signals, so the projection that
    app.signals_watch_state keeps for every other write never sees these rows.
    """
    item_ids = sorted(item_ids)
    for start in range(0, len(item_ids), PROJECTION_BATCH_SIZE):
        project_watch_states_bulk(
            user,
            list(
                app.models.Item.objects.filter(
                    id__in=item_ids[start : start + PROJECTION_BATCH_SIZE],
                ),
            ),
        )


def _project_season_episodes(seasons):
    """Project the episodes under seasons whose Completed backfill added rows."""
    seasons = [season for season in seasons if season.pk is not None]
    users = {season.user_id: season.user for season in seasons}
    item_ids = defaultdict(set)
    for user_id, item_id in Episode.objects.filter(
        related_season__in=seasons, item__isnull=False,
    ).values_list("related_season__user_id", "item_id"):
        item_ids[user_id].add(item_id)
    for user_id, ids in item_ids.items():
        project_imported_watch_state(users[user_id], ids)


def backfill_completed_seasons(season_ids):
    """Backfill completed seasons after a multi-batch import has finished."""
    if not season_ids:
        return []
    season_model = apps.get_model(app_label="app", model_name=MediaTypes.SEASON.value)
    seasons = list(season_model.objects.filter(pk__in=season_ids).select_related("user"))
    warnings = retry_on_lock(lambda: _backfill_completed_season_episodes(seasons))
    _project_season_episodes(seasons)
    return warnings


def create_import_schedule(
    username,
    request,
    mode,
    frequency,
    import_time,
    source,
    token=None,
    extra_kwargs=None,
    replace_existing=False,
):
    """Create an import schedule.

    extra_kwargs: Optional dictionary of additional task kwargs to persist.
    replace_existing: When the same schedule already exists, refresh its token
        and extra kwargs instead of refusing. Used when a connection is redone,
        so the schedule does not keep a dead token.
    """
    try:
        # The entered time is already in the app's timezone; no conversion.
        import_time = (
            datetime.datetime.strptime(import_time, "%H:%M")
            .replace(tzinfo=timezone.get_default_timezone())
            .time()
        )
    except ValueError:
        messages.error(request, "Invalid import time.")
        return

    task_name = f"Import from {source} for {username} at {import_time} {frequency}"
    existing = PeriodicTask.objects.filter(name=task_name).first()
    if existing and replace_existing:
        task_kwargs = json.loads(existing.kwargs)
        if token:
            task_kwargs["token"] = token
        if extra_kwargs:
            task_kwargs.update(extra_kwargs)
        existing.kwargs = json.dumps(task_kwargs)
        existing.save()
        messages.success(request, f"{source} import task updated.")
        return
    if existing:
        messages.error(
            request,
            "The same import task is already scheduled.",
        )
        return

    crontab, _ = CrontabSchedule.objects.get_or_create(
        hour=import_time.hour,
        minute=import_time.minute,
        day_of_week="*" if frequency == "daily" else "*/2",
        timezone=timezone.get_default_timezone(),
    )

    kwargs = {
        "username": username,
        "user_id": request.user.id,
        "mode": mode,
    }

    if token:
        kwargs["token"] = token
    if extra_kwargs:
        kwargs.update(extra_kwargs)

    # Create new periodic task
    PeriodicTask.objects.create(
        name=task_name,
        task=f"Import from {source}",
        crontab=crontab,
        kwargs=json.dumps(kwargs),
        start_time=timezone.now(),
    )
    messages.success(request, f"{source} import task scheduled.")


def join_with_commas_and(items):
    """Join a list of items with commas and 'and'."""
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def fernet():
    """Derive a stable 32-byte key from Django's SECRET_KEY.

    Uses SHA-256 then urlsafe_b64encode to satisfy Fernet.
    """
    digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(value):
    """Return url-safe encrypted string."""
    return fernet().encrypt(value.encode()).decode()


def decrypt(token):
    """Decrypt value that was encrypted with `encrypt`."""
    return fernet().decrypt(token.encode()).decode()


def stamp_entry_source(media, label):
    """Record where an entry came from when nothing is recorded yet.

    A value the user typed, or one an earlier sync set, is never replaced.
    """
    if label and not media.entry_source:
        media.entry_source = label
        media.save(update_fields=["entry_source"])
    return media


def decrypt_or_raise(token):
    """Decrypt a stored credential, raising a friendly MediaImportError on failure."""
    try:
        return decrypt(token)
    except InvalidToken as error:
        logger.exception("Failed to decrypt stored credential")
        msg = "Saved credentials can't be read. Reconnect this integration."
        raise MediaImportError(msg) from error


def season_last_episode_number(season_metadata):
    """Return the number of a season's final episode.

    A season's ``max_progress`` is how many episodes it has. Anime seasons
    that continue the numbering (51-100) end on a number larger than that
    count, so completion checks compare against this instead.
    """
    last = season_metadata.get("last_episode_number")
    if last:
        return last
    numbers = [
        episode["episode_number"]
        for episode in season_metadata.get("episodes") or []
        if isinstance(episode, dict) and episode.get("episode_number") is not None
    ]
    if numbers:
        return max(numbers)
    return season_metadata.get("max_progress")


def season_episode_numbers(season_metadata):
    """Return the episode numbers that make up a season's ``max_progress``.

    Episodes past the provider's count (a future episode it lists but does not
    count yet) are left out, as they were when this was ``range(1, count + 1)``.
    """
    count = int(season_metadata.get("max_progress") or 0)
    numbers = sorted(
        {
            int(episode["episode_number"])
            for episode in season_metadata.get("episodes") or []
            if isinstance(episode, dict) and episode.get("episode_number") is not None
        },
    )
    if numbers and count:
        return set(numbers[:count])
    return set(range(1, count + 1))
