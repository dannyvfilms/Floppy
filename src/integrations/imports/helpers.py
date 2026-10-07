import base64
import datetime
import hashlib
import json
import logging
import time
from collections import defaultdict
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
from integrations import import_progress
from integrations.models import ImportRun

logger = logging.getLogger(__name__)


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


# Importers read identity fields off the preloaded items, never these. Loading
# them for a whole library (``watch_providers`` is ~146 KiB a title) ran a large
# Trakt export import out of memory before it wrote anything (#1252).
PRELOAD_DEFERRED_ITEM_FIELDS = history_deferred_item_fields("item")


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
                    end_date=getattr(season, "_pending_end_date", _UNSET_END_DATE),
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
        if normalize:
            normalize_completed_entries(created_media)

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
    return warnings


def backfill_completed_seasons(season_ids):
    """Backfill completed seasons after a multi-batch import has finished."""
    if not season_ids:
        return []
    season_model = apps.get_model(app_label="app", model_name=MediaTypes.SEASON.value)
    seasons = season_model.objects.filter(pk__in=season_ids)
    return retry_on_lock(lambda: _backfill_completed_season_episodes(seasons))


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
