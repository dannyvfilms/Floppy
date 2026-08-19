import base64
import datetime
import hashlib
import json
import logging
import time
from collections import defaultdict

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
from app.models import Episode, MediaTypes, Status
from app.services.completion import normalize_completed_entry
from integrations import import_progress

logger = logging.getLogger(__name__)


class MediaImportError(Exception):
    """Custom exception for import errors."""


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


def find_item_across_buckets(preferred_bucket=None, **identity):
    """Return an existing Item for an identity, preferring one library bucket.

    Every Item uniqueness constraint includes ``library_media_type``, and the
    same media identity can legitimately live in more than one bucket (grouped
    anime is stored on TV rows, and episodes auto-created for a tracked season
    inherit the show's bucket rather than the default 'episode' one). A
    ``get``/``get_or_create`` keyed only on the identity fields therefore raises
    ``MultipleObjectsReturned`` as soon as two buckets exist. Reuse an existing
    row instead of failing or creating a third, divergent one - preferring the
    caller's bucket, then the oldest row so repeat runs stay stable.
    """
    candidates = list(app.models.Item.objects.filter(**identity).order_by("id"))
    if not candidates:
        return None
    if preferred_bucket:
        for item in candidates:
            if item.library_media_type == preferred_bucket:
                return item
    return candidates[0]


def get_existing_media(user):
    """Get all existing media for the user to check against during import."""
    excluded_types = [MediaTypes.SEASON.value, MediaTypes.EPISODE.value]
    valid_types = [value for value in MediaTypes.values if value not in excluded_types]
    existing = defaultdict(lambda: defaultdict(dict))

    for media_type in valid_types:
        media_model = apps.get_model(app_label="app", model_name=media_type)

        for media in media_model.objects.filter(user=user).select_related("item"):
            existing[media_type][media.item.source][media.item.media_id] = media

    counts = [
        f"{media_type}: {sum(len(source_dict) for source_dict in media_dict.values())}"
        for media_type, media_dict in existing.items()
    ]
    logger.debug("Existing media for user %s: %s", user.username, ", ".join(counts))
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


def _backfill_completed_season_episodes(seasons):
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
        return []

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
            episodes_to_create.extend(season.get_remaining_eps(season_metadata))
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

    if episodes_to_create:
        created_episodes = bulk_create_with_history(
            episodes_to_create,
            Episode,
            batch_size=500,
        )
        for episode in created_episodes:
            normalize_completed_entry(episode)

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


def bulk_create_media(bulk_media_list, user):
    """Bulk create all media objects.

    Returns warning messages for any seasons whose Completed-status
    episode backfill failed, for callers that want to surface them.
    """
    for media_type in _ordered_media_types(bulk_media_list):
        bulk_media = bulk_media_list[media_type]
        if not bulk_media:
            continue

        model = apps.get_model(app_label="app", model_name=media_type)
        bulk_media = _deduplicate_unique_user_item_rows(model, bulk_media)

        import_run_id = import_progress.get_current_import_run_id()
        if import_run_id:
            for media_obj in bulk_media:
                media_obj.import_run_id = import_run_id

        logger.info("Bulk importing %s", media_type)

        # Update references for seasons and episodes
        if media_type == MediaTypes.SEASON.value:
            logger.info("Updating references for season to existing TV shows")
            update_season_references(bulk_media, user)
        elif media_type == MediaTypes.EPISODE.value:
            logger.info(
                "Updating references for episodes to existing TV seasons",
            )
            update_episode_references(bulk_media, user)

        def create_media(bulk_media=bulk_media, model=model):
            return bulk_create_with_history(
                bulk_media,
                model,
                batch_size=500,
                default_user=user,
                default_date=timezone.now(),
            )

        created_media = retry_on_lock(create_media)
        for media in created_media:
            normalize_completed_entry(media)

    # Run after every media type (including any episodes the importer supplied
    # directly) has been persisted, so the "does this season already have
    # episodes" check below sees the importer's own episodes too.
    bulk_seasons = bulk_media_list.get(MediaTypes.SEASON.value)
    if bulk_seasons:
        return retry_on_lock(
            lambda: _backfill_completed_season_episodes(bulk_seasons),
        )
    return []


def create_import_schedule(
    username,
    request,
    mode,
    frequency,
    import_time,
    source,
    token=None,
    extra_kwargs=None,
):
    """Create an import schedule.

    extra_kwargs: Optional dictionary of additional task kwargs to persist.
    """
    try:
        import_time = (
            datetime.datetime.strptime(import_time, "%H:%M")
            .astimezone(
                timezone.get_default_timezone(),
            )
            .time()
        )
    except ValueError:
        messages.error(request, "Invalid import time.")
        return

    task_name = f"Import from {source} for {username} at {import_time} {frequency}"
    if PeriodicTask.objects.filter(name=task_name).exists():
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


def decrypt_or_raise(token):
    """Decrypt a stored credential, raising a friendly MediaImportError on failure."""
    try:
        return decrypt(token)
    except InvalidToken as error:
        logger.exception("Failed to decrypt stored credential")
        msg = (
            "Stored credentials could not be decrypted. This usually happens "
            "after the app's encryption key changes. Please reconnect this "
            "integration."
        )
        raise MediaImportError(msg) from error
