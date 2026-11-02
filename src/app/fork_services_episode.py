# FORK: shared episode-tracking domain logic used by both the web views
# (save_views.episode_save / episode_drop) and the REST API, so the two
# surfaces cannot drift apart.
import logging
from dataclasses import dataclass
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from app import cache_utils
from app.db_retry import run_retryable_db_operation
from app.models import Episode, Item, MediaTypes, Season, Status
from app.providers import services
from app.services import metadata_resolution

logger = logging.getLogger(__name__)
EPISODE_WATCH_CONFLICT_CODE = "EPISODE-WATCH-CONFLICT-001"


class EpisodeWatchConflictError(Exception):
    """A private watch token was already claimed by another identity."""

    code = EPISODE_WATCH_CONFLICT_CODE

    def __init__(self):
        """Expose only the stable public conflict code."""
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class EpisodeWatchResult:
    """Persisted Episode plus whether this request created it."""

    episode: Episode
    created: bool


def normalize_watch_operation_id(value):
    """Return a UUID or reject malformed private form state safely."""
    if value in (None, ""):
        return None
    try:
        return UUID(str(value))
    except (AttributeError, TypeError, ValueError) as error:
        message = "Invalid watch operation."
        raise ValidationError(message, code="invalid") from error


def _resolve_claimed_watch(episode, *, user_id, season_id=None, item_id=None):
    same_identity = episode.related_season.user_id == user_id
    if season_id is not None:
        same_identity = same_identity and episode.related_season_id == season_id
    if item_id is not None:
        same_identity = same_identity and episode.item_id == item_id
    if not same_identity:
        raise EpisodeWatchConflictError
    return EpisodeWatchResult(episode=episode, created=False)


def resolve_episode_watch_replay(episode, *, user_id, season_id=None, item_id=None):
    """Resolve a quick-progress retry against its persisted winning watch."""
    return _resolve_claimed_watch(
        episode,
        user_id=user_id,
        season_id=season_id,
        item_id=item_id,
    )


def _find_external_episode(related_season, item, external_id):
    """Return the episode play claimed by a client-supplied external id."""
    return (
        Episode.objects.filter(
            related_season=related_season,
            item=item,
            external_id=external_id,
        )
        .select_related("related_season", "item")
        .first()
    )


def create_episode_watch(
    related_season,
    item,
    end_date,
    *,
    watch_operation_id=None,
    external_id=None,
    **episode_fields,
):
    """Create one Episode watch, replaying a previously claimed private token.

    ``watch_operation_id`` is the private web-form token; ``external_id`` is
    the public client-supplied play id. Either one makes the call safe to
    retry: a replay returns the winning play with ``created=False`` instead of
    appending a second copy.
    """
    operation_id = normalize_watch_operation_id(watch_operation_id)
    if external_id is not None:
        external_id = str(external_id).strip() or None
    identity = {
        "user_id": related_season.user_id,
        "season_id": related_season.id,
        "item_id": item.id,
    }

    def create_or_replay():
        if operation_id is not None:
            claimed = (
                Episode.objects.filter(watch_operation_id=operation_id)
                .select_related("related_season", "item")
                .first()
            )
            if claimed is not None:
                return _resolve_claimed_watch(claimed, **identity)

        if external_id is not None:
            existing = _find_external_episode(related_season, item, external_id)
            if existing is not None:
                return EpisodeWatchResult(episode=existing, created=False)

        try:
            with transaction.atomic():
                episode = Episode.objects.create(
                    related_season=related_season,
                    item=item,
                    end_date=end_date,
                    watch_operation_id=operation_id,
                    external_id=external_id,
                    **episode_fields,
                )
        except IntegrityError as error:
            if operation_id is None and external_id is None:
                raise
            if operation_id is not None:
                claimed = (
                    Episode.objects.filter(watch_operation_id=operation_id)
                    .select_related("related_season", "item")
                    .first()
                )
                if claimed is not None:
                    return _resolve_claimed_watch(claimed, **identity)
            if external_id is not None:
                existing = _find_external_episode(
                    related_season,
                    item,
                    external_id,
                )
                if existing is not None:
                    return EpisodeWatchResult(episode=existing, created=False)
            raise EpisodeWatchConflictError from error
        return EpisodeWatchResult(episode=episode, created=True)

    return run_retryable_db_operation(
        create_or_replay,
        operation_name="episode watch",
        operation_logger=logger,
    ).value


def resolve_or_create_season(
    user,
    media_id,
    source,
    season_number,
    library_media_type="",
    *,
    prepare_only=False,
    status=Status.IN_PROGRESS.value,
):
    """Return the user's tracked Season row, creating it if it doesn't exist.

    Mirrors the season auto-create behavior of the web episode actions:
    missing seasons are created In Progress (or ``status``) with
    metadata-derived title/image.
    """
    related_season = metadata_resolution.find_tracked_season(
        user,
        media_id,
        source,
        season_number,
        library_media_type=library_media_type or None,
    )
    if related_season is None:
        tv_with_seasons_metadata = services.get_media_metadata(
            "tv_with_seasons",
            media_id,
            source,
            [season_number],
        )
        season_metadata = tv_with_seasons_metadata.get(f"season/{season_number}")
        if not isinstance(season_metadata, dict):
            season_metadata = {}

        # Use season poster if available, otherwise fallback to TV show poster
        season_image = season_metadata.get("image") or tv_with_seasons_metadata.get(
            "image",
        )

        item = metadata_resolution.get_or_create_tracked_season_item(
            media_id,
            source,
            season_number,
            provider=source,
            library_media_type=library_media_type or MediaTypes.SEASON.value,
            metadata=None,
            defaults={
                **Item.title_fields_from_metadata(tv_with_seasons_metadata),
                "image": season_image,
            },
        )
        related_season = Season(
            item=item,
            user=user,
            score=None,
            status=status,
            notes="",
        )
        if prepare_only:
            # Ordered destinations belong to an already tracked show. Resolve
            # its identity without committing a tracking parent before sealing.
            related_season.related_tv = related_season.get_tv()
        else:
            related_season.save()

        if not prepare_only:
            logger.info("%s did not exist, it was created successfully.", related_season)

    _sync_library_media_type(related_season, library_media_type)
    return related_season


def _sync_library_media_type(related_season, library_media_type):
    """Propagate an explicit library bucket to the season and TV items."""
    if not library_media_type:
        return
    if related_season.item.library_media_type != library_media_type:
        related_season.item.library_media_type = library_media_type
        related_season.item.save(update_fields=["library_media_type"])
    if (
        related_season.related_tv
        and related_season.related_tv.item.library_media_type != library_media_type
    ):
        related_season.related_tv.item.library_media_type = library_media_type
        related_season.related_tv.item.save(update_fields=["library_media_type"])


def drop_episode(related_season, episode_number):
    """Mark an episode dropped — advances progress without watch history."""
    item = related_season.get_episode_item(episode_number)
    episode_record = Episode.objects.create(
        related_season=related_season,
        item=item,
        end_date=None,
        dropped=True,
        status=Status.DROPPED.value,
    )
    logger.info("%s dropped successfully.", episode_record)
    cache_utils.clear_time_left_cache_for_user(related_season.user_id)
    cache_utils.clear_media_list_cache_for_user(related_season.user_id)
    return episode_record
