# FORK: tracking endpoints that mirror web-only actions — episode watch/
# drop and tag management. Kept out of upstream-owned views.py; URL wiring
# lives in fork_urls.py.
import logging
from http import HTTPStatus as HTTP  # noqa: N814

from django.conf import settings
from django.db.models import Count
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import views as drf_views
from rest_framework.response import Response

from app import fork_services_history, history_cache_reader
from app.fork_services_episode import drop_episode, resolve_or_create_season
from app.fork_services_movie import resolve_or_create_movie
from app.history_cache_utils import normalize_history_media_type_tokens
from app.models import Episode, ItemTag, MediaTypes, Movie, Season, Tag
from app.tasks import bulk_episode_plays_task

from .helpers import (
    MEDIA_TYPE_MODEL_MAP,
    check_source_type,
    check_valid_type,
    paginate_data,
    parse_limit_offset,
    resolve_item_queryset,
    try_parse_datetime_input,
)
from .schema import MEDIA_TYPE_PARAM, MEDIA_TYPE_TV_ONLY_PARAM
from .serializers import HistorySerializer, serialize_data

logger = logging.getLogger(__name__)


def _tv_route_error(media_type, source):
    """Validate the media_type/source pair for episode routes."""
    if media_type != MediaTypes.TV.value:
        return Response(
            {"detail": "Episodes are supported only for 'tv' media type."},
            status=HTTP.BAD_REQUEST,
        )
    if not check_source_type(media_type, source):
        return Response(
            {"detail": f"Cannot query `{source}` for `{media_type}` media type"},
            status=HTTP.BAD_REQUEST,
        )
    return None


def _get_tracked_season(user, media_id, source, season_number):
    """Return the user's tracked Season row or None."""
    return (
        Season.objects.filter(
            item__media_id=media_id,
            item__source=source,
            item__season_number=season_number,
            item__episode_number=None,
            user=user,
        )
        .order_by("id")
        .first()
    )


# /api/v1/media/tv/[source]/[media_id]/[season_number]/episodes/[episode_number]/watch/
class MediaEpisodeWatchView(drf_views.APIView):
    """Add or remove a watch (play) for an episode.

    POST mirrors the web UI's episode_save: the season is auto-created when
    missing and a new Episode play row is added. DELETE mirrors unwatching:
    the most recent play of the episode is removed.
    """

    @extend_schema(parameters=[MEDIA_TYPE_TV_ONLY_PARAM])
    def post(
        self,
        request,
        media_type,
        source,
        media_id,
        season_number,
        episode_number,
    ):
        """Record a watch for the episode."""
        error = _tv_route_error(media_type, source)
        if error:
            return error

        raw_end_date = request.data.get("end_date")
        if raw_end_date in (None, ""):
            end_date = timezone.now()
        else:
            try:
                end_date = try_parse_datetime_input(raw_end_date)
            except (TypeError, ValueError):
                return Response(
                    {"detail": "Invalid end_date format."},
                    status=HTTP.BAD_REQUEST,
                )

        library_media_type = (request.data.get("library_media_type") or "").strip()
        try:
            related_season = resolve_or_create_season(
                request.user,
                media_id,
                source,
                int(season_number),
                library_media_type=library_media_type,
            )
        except Exception as e:
            return Response(
                {"detail": "Could not resolve season.", "errors": str(e)},
                status=HTTP.NOT_FOUND,
            )

        related_season.watch(int(episode_number), end_date)
        episode = (
            Episode.objects.filter(
                related_season=related_season,
                item__episode_number=int(episode_number),
            )
            .select_related("item")
            .order_by("-id")
            .first()
        )
        return Response(serialize_data(episode), status=HTTP.CREATED)

    @extend_schema(parameters=[MEDIA_TYPE_TV_ONLY_PARAM])
    def delete(
        self,
        request,
        media_type,
        source,
        media_id,
        season_number,
        episode_number,
    ):
        """Remove the most recent watch of the episode."""
        error = _tv_route_error(media_type, source)
        if error:
            return error

        related_season = _get_tracked_season(
            request.user,
            media_id,
            source,
            int(season_number),
        )
        if related_season is None:
            return Response(
                {"detail": "Season not found or not tracked."},
                status=HTTP.NOT_FOUND,
            )

        plays = Episode.objects.filter(
            related_season=related_season,
            item__episode_number=int(episode_number),
        )
        if not plays.exists():
            return Response(
                {"detail": "Episode has no watches."},
                status=HTTP.NOT_FOUND,
            )

        related_season.unwatch(int(episode_number))
        return Response(status=HTTP.NO_CONTENT)


# /api/v1/media/movie/[source]/[media_id]/watch/
class MediaMovieWatchView(drf_views.APIView):
    """Add or remove a watch (play) for a movie.

    POST appends a dated play (mirroring episode watch); repeated calls
    leave multiple plays instead of overwriting the tracker's end_date.
    DELETE mirrors unwatching: the most recent play is removed. An optional
    `external_id` makes both calls idempotent/targetable for callers that
    replay the same event.
    """

    @extend_schema(parameters=[MEDIA_TYPE_PARAM])
    def post(self, request, media_type, source, media_id):
        """Record a watch (play) for the movie."""
        if media_type != MediaTypes.MOVIE.value:
            return Response(
                {"detail": "This endpoint is supported only for 'movie' media type."},
                status=HTTP.BAD_REQUEST,
            )
        if not check_source_type(media_type, source):
            return Response(
                {"detail": f"Cannot query `{source}` for `{media_type}` media type"},
                status=HTTP.BAD_REQUEST,
            )

        raw_end_date = request.data.get("end_date")
        if raw_end_date in (None, ""):
            end_date = timezone.now()
        else:
            try:
                end_date = try_parse_datetime_input(raw_end_date)
            except (TypeError, ValueError):
                return Response(
                    {"detail": "Invalid end_date format."},
                    status=HTTP.BAD_REQUEST,
                )

        external_id = (request.data.get("external_id") or "").strip() or None

        try:
            movie = resolve_or_create_movie(request.user, media_id, source)
        except Exception as e:
            return Response(
                {"detail": "Could not resolve movie.", "errors": str(e)},
                status=HTTP.NOT_FOUND,
            )

        play, created = movie.watch(end_date, external_id=external_id)
        status_code = HTTP.CREATED if created else HTTP.OK
        return Response(
            serialize_data(play, serializer_class=HistorySerializer),
            status=status_code,
        )

    @extend_schema(parameters=[MEDIA_TYPE_PARAM])
    def delete(self, request, media_type, source, media_id):
        """Remove a watch (play) of the movie.

        Removes the most recent play by default, or the play matching an
        `external_id` query parameter if provided.
        """
        if media_type != MediaTypes.MOVIE.value:
            return Response(
                {"detail": "This endpoint is supported only for 'movie' media type."},
                status=HTTP.BAD_REQUEST,
            )
        if not check_source_type(media_type, source):
            return Response(
                {"detail": f"Cannot query `{source}` for `{media_type}` media type"},
                status=HTTP.BAD_REQUEST,
            )

        movie = (
            Movie.objects.filter(
                item__media_id=media_id,
                item__source=source,
                item__media_type=MediaTypes.MOVIE.value,
                user=request.user,
            )
            .order_by("id")
            .first()
        )
        if movie is None:
            return Response(
                {"detail": "Movie not found or not tracked."},
                status=HTTP.NOT_FOUND,
            )

        external_id = (request.GET.get("external_id") or "").strip() or None
        play = movie.unwatch(external_id=external_id)
        if play is None:
            return Response(
                {"detail": "Movie has no watches."},
                status=HTTP.NOT_FOUND,
            )

        return Response(status=HTTP.NO_CONTENT)


# /api/v1/media/tv/[source]/[media_id]/[season_number]/episodes/[episode_number]/drop/
class MediaEpisodeDropView(drf_views.APIView):
    """Mark an episode dropped — advances progress without watch history."""

    @extend_schema(parameters=[MEDIA_TYPE_TV_ONLY_PARAM])
    def post(
        self,
        request,
        media_type,
        source,
        media_id,
        season_number,
        episode_number,
    ):
        """Record a drop for the episode (mirrors web episode_drop)."""
        error = _tv_route_error(media_type, source)
        if error:
            return error

        library_media_type = (request.data.get("library_media_type") or "").strip()
        try:
            related_season = resolve_or_create_season(
                request.user,
                media_id,
                source,
                int(season_number),
                library_media_type=library_media_type,
            )
        except Exception as e:
            return Response(
                {"detail": "Could not resolve season.", "errors": str(e)},
                status=HTTP.NOT_FOUND,
            )

        episode = drop_episode(related_season, int(episode_number))
        return Response(serialize_data(episode), status=HTTP.CREATED)


def _serialize_tag(tag, item_count=None):
    """Return a plain payload for a Tag row."""
    payload = {
        "id": tag.id,
        "name": tag.name,
        "created_at": tag.created_at,
    }
    if item_count is not None:
        payload["item_count"] = item_count
    return payload


# /api/v1/tags/
class TagsView(drf_views.APIView):
    """List or create the user's tags."""

    def get(self, request):
        """Return all tags for the user with item counts."""
        tags = Tag.objects.filter(user=request.user).annotate(
            item_count=Count("item_tags"),
        )
        return Response(
            {"results": [_serialize_tag(tag, tag.item_count) for tag in tags]},
            status=HTTP.OK,
        )

    def post(self, request):
        """Create a tag (names are unique per user, case-insensitive)."""
        name = " ".join((request.data.get("name") or "").split())
        if not name:
            return Response(
                {"detail": "Tag name is required."},
                status=HTTP.BAD_REQUEST,
            )
        if Tag.objects.filter(user=request.user, name__iexact=name).exists():
            return Response(
                {"detail": f'Tag "{name}" already exists.'},
                status=HTTP.CONFLICT,
            )
        tag = Tag.objects.create(user=request.user, name=name)
        return Response(_serialize_tag(tag), status=HTTP.CREATED)


# /api/v1/tags/[tag_id]/
class TagDetailView(drf_views.APIView):
    """Rename or delete a tag."""

    def _get_tag(self, request, tag_id):
        return Tag.objects.filter(id=tag_id, user=request.user).first()

    def patch(self, request, tag_id):
        """Rename the tag."""
        tag = self._get_tag(request, tag_id)
        if tag is None:
            return Response({"detail": "Tag not found."}, status=HTTP.NOT_FOUND)
        name = " ".join((request.data.get("name") or "").split())
        if not name:
            return Response(
                {"detail": "Tag name is required."},
                status=HTTP.BAD_REQUEST,
            )
        if (
            Tag.objects.filter(user=request.user, name__iexact=name)
            .exclude(id=tag.id)
            .exists()
        ):
            return Response(
                {"detail": f'Tag "{name}" already exists.'},
                status=HTTP.CONFLICT,
            )
        tag.name = name
        tag.save()
        return Response(_serialize_tag(tag), status=HTTP.OK)

    def delete(self, request, tag_id):
        """Delete the tag and its item associations."""
        tag = self._get_tag(request, tag_id)
        if tag is None:
            return Response({"detail": "Tag not found."}, status=HTTP.NOT_FOUND)
        tag.delete()
        return Response(status=HTTP.NO_CONTENT)


# /api/v1/media/[media_type]/[source]/[media_id]/tags/
class MediaTagsView(drf_views.APIView):
    """Read or replace the caller's tags on a media item."""

    def _get_item(self, media_type, source, media_id):
        return resolve_item_queryset(media_id, source, media_type).first()

    @extend_schema(parameters=[MEDIA_TYPE_PARAM])
    def get(self, request, media_type, source, media_id):
        """Return the user's tags applied to this item."""
        if not check_valid_type(media_type):
            return Response(
                {"detail": "Unsupported media type."},
                status=HTTP.BAD_REQUEST,
            )
        item = self._get_item(media_type, source, media_id)
        if item is None:
            return Response({"detail": "Item not found."}, status=HTTP.NOT_FOUND)
        tags = Tag.objects.filter(user=request.user, item_tags__item=item)
        return Response(
            {"results": [_serialize_tag(tag) for tag in tags]},
            status=HTTP.OK,
        )

    @extend_schema(parameters=[MEDIA_TYPE_PARAM])
    def put(self, request, media_type, source, media_id):
        """Replace the user's tags on this item with the given tag ids."""
        if not check_valid_type(media_type):
            return Response(
                {"detail": "Unsupported media type."},
                status=HTTP.BAD_REQUEST,
            )
        item = self._get_item(media_type, source, media_id)
        if item is None:
            return Response({"detail": "Item not found."}, status=HTTP.NOT_FOUND)

        tag_ids = request.data.get("tag_ids")
        if not isinstance(tag_ids, list):
            return Response(
                {"detail": "'tag_ids' must be a list of tag ids."},
                status=HTTP.BAD_REQUEST,
            )

        tags = list(Tag.objects.filter(user=request.user, id__in=tag_ids))
        if len(tags) != len(set(tag_ids)):
            return Response(
                {"detail": "One or more tags not found."},
                status=HTTP.NOT_FOUND,
            )

        ItemTag.objects.filter(item=item, tag__user=request.user).exclude(
            tag__in=tags,
        ).delete()
        for tag in tags:
            ItemTag.objects.get_or_create(tag=tag, item=item)

        applied = Tag.objects.filter(user=request.user, item_tags__item=item)
        return Response(
            {"results": [_serialize_tag(tag) for tag in applied]},
            status=HTTP.OK,
        )


_HISTORY_INT_FILTERS = (
    "album",
    "artist",
    "tv",
    "season",
    "season_number",
    "podcast_show",
)
_HISTORY_STR_FILTERS = (
    "genre",
    "implied_genre",
    "media_id",
    "source",
    "person_source",
    "person_id",
)


# /api/v1/history/
class HistoryView(drf_views.APIView):
    """Day-by-day consumption timeline (mirrors the web history page).

    Supports the web page's filters (media_type, genre, media_id/source,
    album/artist/tv/season/podcast_show, person) plus start_date/end_date,
    and paginates over days with limit/offset.
    """

    def get(self, request):
        """Return the user's history grouped by day, newest first."""
        limit, offset, err = parse_limit_offset(request)
        if err:
            return err

        filters = {}
        for param in _HISTORY_INT_FILTERS:
            value = request.GET.get(param)
            if value:
                try:
                    filters[param] = int(value)
                except (TypeError, ValueError):
                    return Response(
                        {"detail": f"Invalid {param} parameter"},
                        status=HTTP.BAD_REQUEST,
                    )
        for param in _HISTORY_STR_FILTERS:
            value = request.GET.get(param)
            if value:
                filters[param] = value

        raw_media_types = request.GET.getlist("types")
        raw_media_types.extend(request.GET.getlist("media_type"))
        if raw_media_types:
            try:
                normalized_media_types = normalize_history_media_type_tokens(
                    raw_media_types,
                )
            except ValueError as exc:
                return Response(
                    {"detail": str(exc)},
                    status=HTTP.BAD_REQUEST,
                )
            filters["media_type"] = ",".join(sorted(normalized_media_types))

        logging_style = request.GET.get("logging_style")
        if logging_style not in (None, "", "sessions", "repeats"):
            return Response(
                {"detail": "logging_style must be 'sessions' or 'repeats'"},
                status=HTTP.BAD_REQUEST,
            )

        date_filters = {}
        for param in ("start_date", "end_date"):
            value = request.GET.get(param)
            if value:
                date_filters[param] = value

        type_only_request = not date_filters and set(filters).issubset(
            {"media_type"},
        )
        if type_only_request:
            history_days, total_days = history_cache_reader.get_cached_history_window(
                request.user,
                limit=limit,
                offset=offset,
                filters=filters or None,
                logging_style_override=logging_style or None,
            )
        else:
            history_days = history_cache_reader.get_history_days(
                request.user,
                filters=filters or None,
                date_filters=date_filters or None,
                logging_style_override=logging_style or None,
            )
            total_days = None
        if type_only_request:
            paginated = paginate_data(
                request,
                [],
                limit,
                offset,
                total=total_days,
            )
            paginated["results"] = history_days
        else:
            paginated = paginate_data(request, history_days, limit, offset)
        return Response(paginated, status=HTTP.OK)


# /api/v1/history/[media_type]/[history_id]/
class HistoryRecordView(drf_views.APIView):
    """Delete a consumption-history record (mirrors the web history delete)."""

    @extend_schema(parameters=[MEDIA_TYPE_PARAM])
    def delete(self, request, media_type, history_id):
        """Delete the record; play-per-instance types delete the play itself."""
        if media_type not in MEDIA_TYPE_MODEL_MAP:
            return Response(
                {"detail": "Unsupported media type."},
                status=HTTP.BAD_REQUEST,
            )
        try:
            fork_services_history.delete_history_record_core(
                request.user,
                media_type,
                history_id,
            )
        except fork_services_history.HistoryRecordNotFoundError:
            return Response(
                {"detail": "History record not found."},
                status=HTTP.NOT_FOUND,
            )
        except fork_services_history.HistoryDeletionError as e:
            return Response(
                {"detail": str(e)},
                status=HTTP.INTERNAL_SERVER_ERROR,
            )
        return Response(status=HTTP.NO_CONTENT)


# /api/v1/media/[media_type]/[source]/[media_id]/episodes/bulk/
class MediaEpisodeBulkView(drf_views.APIView):
    """Dispatch a bulk episode play range as a background task.

    Mirrors the web episode_bulk_save: the range spans seasons, and the
    task distributes plays across the start/end dates. Returns 202 with a
    task_id that can be polled at /api/v1/tasks/{task_id}.
    """

    @extend_schema(parameters=[MEDIA_TYPE_TV_ONLY_PARAM])
    def post(self, request, media_type, source, media_id):
        """Queue the bulk play range for the media."""
        if media_type != MediaTypes.TV.value:
            return Response(
                {"detail": "Episodes are supported only for 'tv' media type."},
                status=HTTP.BAD_REQUEST,
            )

        start_date = (str(request.data.get("start_date") or "")).strip()
        end_date = (str(request.data.get("end_date") or "")).strip()
        if not start_date or not end_date:
            return Response(
                {"detail": "start_date and end_date are required."},
                status=HTTP.BAD_REQUEST,
            )

        try:
            first_season_number = int(request.data["first_season_number"])
            first_episode_number = int(request.data["first_episode_number"])
            last_season_number = int(request.data["last_season_number"])
            last_episode_number = int(request.data["last_episode_number"])
        except (KeyError, TypeError, ValueError):
            return Response(
                {"detail": "Invalid episode range."},
                status=HTTP.BAD_REQUEST,
            )

        write_mode = request.data.get("write_mode", "add")
        distribution_mode = request.data.get("distribution_mode", "even")
        if write_mode not in ("add", "replace"):
            return Response(
                {"detail": "write_mode must be 'add' or 'replace'."},
                status=HTTP.BAD_REQUEST,
            )
        if distribution_mode not in ("even", "air_date"):
            return Response(
                {"detail": "distribution_mode must be 'even' or 'air_date'."},
                status=HTTP.BAD_REQUEST,
            )

        task = bulk_episode_plays_task.apply_async(
            kwargs={
                "user_id": request.user.id,
                "media_type": media_type,
                "source": source,
                "media_id": media_id,
                "first_season_number": first_season_number,
                "first_episode_number": first_episode_number,
                "last_season_number": last_season_number,
                "last_episode_number": last_episode_number,
                "write_mode": write_mode,
                "distribution_mode": distribution_mode,
                "start_date_str": start_date,
                "end_date_str": end_date,
                "identity_media_type": request.data.get("identity_media_type"),
                "library_media_type": request.data.get("library_media_type"),
            },
            priority=settings.CELERY_TASK_PRIORITY_INTERACTIVE,
        )
        logger.info(
            "bulk_episode_plays_task_dispatched task_id=%s user_id=%d media_id=%s",
            task.id,
            request.user.id,
            media_id,
        )
        return Response({"task_id": task.id}, status=HTTP.ACCEPTED)
