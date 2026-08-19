# FORK: durable playback progress (resume positions) for third-party clients
# doing bidirectional sync (e.g. CrossWatch). Kept separate from
# fork_views_tracking.py for the same reason as fork_views_scrobble.py: this is
# a public integration surface, not a web-UI parity mirror. See issue #429.
#
# Movies/episodes are stored in app.models.PlaybackProgress; podcasts keep
# using Podcast.played_up_to_seconds, which the podcast UI already reads.
import logging
from datetime import UTC, datetime
from http import HTTPStatus as HTTP  # noqa: N814

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import views as drf_views
from rest_framework.response import Response

import app.providers.tmdb
from app.models import (
    Item,
    MediaTypes,
    PlaybackProgress,
    Podcast,
    Sources,
    Status,
)
from app.services.tracking_hydration import ensure_item_metadata

from .helpers import paginate_data, parse_limit_offset, try_parse_datetime_input

logger = logging.getLogger(__name__)

MEDIA_TYPES = (
    MediaTypes.MOVIE.value,
    MediaTypes.EPISODE.value,
    MediaTypes.PODCAST.value,
)
_VIDEO_MEDIA_TYPES = (MediaTypes.MOVIE.value, MediaTypes.EPISODE.value)
_EXTERNAL_ID_KEYS = {"tmdb": "tmdb_id", "imdb": "imdb_id", "tvdb": "tvdb_id"}
_PODCAST_COMPLETED_STATUS = 3  # playingStatus from the podcast provider APIs
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _coerce_position(value):
    """Return a non-negative int, or raise ValueError."""
    position = int(value)
    if position < 0:
        msg = "must be >= 0"
        raise ValueError(msg)
    return position


def _external_ids(item):
    """Map an Item's resolved external ids back to the API's `ids` vocabulary."""
    stored = item.provider_external_ids or {}
    return {
        key: str(stored[field])
        for key, field in _EXTERNAL_ID_KEYS.items()
        if stored.get(field)
    }


def resolve_show_tmdb_id(media_type, ids):
    """Resolve an `ids` object to a TMDB movie/show id, or None.

    Tries the ids we've already persisted before falling back to a single
    network `find()` — unlike the live-playback card this feeds a durable
    write, so it must not guess.
    """
    if ids.get("tmdb"):
        return str(ids["tmdb"])

    for key in ("imdb", "tvdb"):
        if not ids.get(key):
            continue
        known = (
            Item.objects.filter(
                source=Sources.TMDB.value,
                **{f"provider_external_ids__{_EXTERNAL_ID_KEYS[key]}": str(ids[key])},
            )
            .order_by("id")
            .first()
        )
        if known:
            return known.media_id

    ext_id = ids.get("imdb") or ids.get("tvdb")
    if not ext_id:
        return None
    ext_type = "imdb_id" if ids.get("imdb") else "tvdb_id"
    find_response = app.providers.tmdb.find(ext_id, ext_type)

    if media_type == MediaTypes.MOVIE.value:
        results = find_response.get("movie_results") or []
        return str(results[0]["id"]) if results else None

    episode_results = find_response.get("tv_episode_results") or []
    if episode_results:
        return str(episode_results[0]["show_id"])
    tv_results = find_response.get("tv_results") or []
    return str(tv_results[0]["id"]) if tv_results else None


def _find_existing_item(media_type, tmdb_id, season_number, episode_number):
    """Cheap DB lookup for an already-known movie/episode Item.

    The same show can have Item rows in more than one library bucket
    (e.g. grouped anime on TV rows), so this can match either bucket;
    ordering by id keeps the choice deterministic. A resume position is
    bucket-agnostic, so picking the oldest row is safe here.
    """
    filters = {
        "source": Sources.TMDB.value,
        "media_id": str(tmdb_id),
        "media_type": media_type,
    }
    if media_type == MediaTypes.EPISODE.value:
        filters["season_number"] = season_number
        filters["episode_number"] = episode_number
    return Item.objects.filter(**filters).order_by("id").first()


def resolve_video_item(user, media_type, ids, season_number, episode_number, *, create):
    """Resolve a movie/episode `ids` object to an Item, optionally creating it.

    When created, only the metadata Item is written — never a Movie/Episode
    tracking row — so pushing a resume position never fabricates watch history.
    """
    tmdb_id = resolve_show_tmdb_id(media_type, ids)
    if not tmdb_id:
        return None

    item = _find_existing_item(media_type, tmdb_id, season_number, episode_number)
    if item or not create:
        return item

    return ensure_item_metadata(
        user,
        media_type,
        str(tmdb_id),
        Sources.TMDB.value,
        season_number=season_number if media_type == MediaTypes.EPISODE.value else None,
        episode_number=episode_number
        if media_type == MediaTypes.EPISODE.value
        else None,
    ).item


def _resolve_podcast(user, ids):
    """Resolve a podcast `ids` object to the user's existing Podcast row."""
    episode_uuid = ids.get("episode_uuid")
    if not episode_uuid:
        return None
    return (
        Podcast.objects.filter(user=user, episode__episode_uuid=str(episode_uuid))
        .select_related("item", "episode", "show")
        .order_by("-id")
        .first()
    )


def upsert_playback_progress(
    user,
    item,
    position_seconds,
    duration_seconds=None,
    *,
    completed=False,
):
    """Store an absolute resume position for a movie/episode Item."""
    progress, _ = PlaybackProgress.objects.update_or_create(
        user=user,
        item=item,
        defaults={
            "position_seconds": position_seconds,
            "duration_seconds": duration_seconds,
            "completed": completed,
        },
    )
    return progress


def _show_item_map(items):
    """Return {(source, media_id): Item} of the shows backing episode items."""
    episode_media_ids = {
        (item.source, item.media_id)
        for item in items
        if item.media_type == MediaTypes.EPISODE.value
    }
    if not episode_media_ids:
        return {}

    shows = Item.objects.filter(
        media_type__in=(MediaTypes.TV.value, MediaTypes.ANIME.value),
        media_id__in=[media_id for _, media_id in episode_media_ids],
    ).order_by("id")
    return {(show.source, show.media_id): show for show in shows}


def _serialize_progress(progress, show_map):
    """Serialize a PlaybackProgress row into the API entry shape."""
    item = progress.item
    show = (
        show_map.get((item.source, item.media_id))
        if item.media_type == MediaTypes.EPISODE.value
        else None
    )
    # Episode Items are created without provider links, so their show-level
    # ids (which is what clients match on) come from the show row.
    ids = _external_ids(item) or (_external_ids(show) if show else {})

    return {
        "media_type": item.media_type,
        "source": item.source,
        "media_id": item.media_id,
        "season_number": item.season_number,
        "episode_number": item.episode_number,
        "ids": ids,
        "title": item.title,
        "series_title": show.title if show else None,
        "position_seconds": progress.position_seconds,
        "duration_seconds": progress.duration_seconds,
        "completed": progress.completed,
        "updated_at": progress.updated_at,
    }


def _podcast_updated_at(podcast):
    """Best-effort mutation time for a podcast position.

    Rows last written before position_updated_at existed fall back to
    progressed_at.
    """
    return podcast.position_updated_at or podcast.progressed_at


def _serialize_podcast(podcast):
    """Serialize a Podcast row into the API entry shape."""
    item = podcast.item
    episode = podcast.episode

    duration_seconds = None
    if episode and episode.duration:
        duration_seconds = episode.duration
    elif item and item.runtime_minutes:
        duration_seconds = item.runtime_minutes * 60

    return {
        "media_type": MediaTypes.PODCAST.value,
        "source": item.source if item else None,
        "media_id": item.media_id if item else None,
        "season_number": episode.season_number if episode else None,
        "episode_number": episode.episode_number if episode else None,
        "ids": {"episode_uuid": episode.episode_uuid} if episode else {},
        "title": item.title if item else None,
        "series_title": podcast.show.title if podcast.show else None,
        "position_seconds": podcast.played_up_to_seconds,
        "duration_seconds": duration_seconds,
        "completed": (
            podcast.last_seen_status == _PODCAST_COMPLETED_STATUS
            or podcast.status == Status.COMPLETED.value
        ),
        "updated_at": _podcast_updated_at(podcast),
    }


def _parse_list_filters(request):
    """Return (filters, error_response) for the GET query params."""
    raw_media_types = request.GET.get("media_type") or ""
    media_types = [part for part in raw_media_types.split(",") if part]
    invalid = [part for part in media_types if part not in MEDIA_TYPES]
    if invalid:
        return None, Response(
            {"detail": f"'media_type' must be one of {MEDIA_TYPES}."},
            status=HTTP.BAD_REQUEST,
        )

    updated_since = None
    raw_updated_since = request.GET.get("updated_since")
    if raw_updated_since:
        try:
            updated_since = try_parse_datetime_input(raw_updated_since)
        except (TypeError, ValueError):
            return None, Response(
                {"detail": "Invalid updated_since format."},
                status=HTTP.BAD_REQUEST,
            )

    completed = None
    raw_completed = request.GET.get("completed")
    if raw_completed is not None and raw_completed != "":
        if raw_completed.lower() not in ("true", "false"):
            return None, Response(
                {"detail": "'completed' must be 'true' or 'false'."},
                status=HTTP.BAD_REQUEST,
            )
        completed = raw_completed.lower() == "true"

    return {
        "media_types": media_types or list(MEDIA_TYPES),
        "updated_since": updated_since,
        "completed": completed,
    }, None


def _identifier_error(data, media_type):
    """Return a 400 Response if the media identifiers are unusable, else None."""
    ids = data.get("ids") or {}
    if media_type == MediaTypes.PODCAST.value:
        if not ids.get("episode_uuid"):
            return Response(
                {"detail": "'ids' must include 'episode_uuid' for podcasts."},
                status=HTTP.BAD_REQUEST,
            )
        return None

    if not any(ids.get(key) for key in _EXTERNAL_ID_KEYS):
        return Response(
            {"detail": "'ids' must include at least one of tmdb/imdb/tvdb."},
            status=HTTP.BAD_REQUEST,
        )

    if media_type == MediaTypes.EPISODE.value and (
        data.get("season_number") is None or data.get("episode_number") is None
    ):
        return Response(
            {
                "detail": (
                    "'season_number' and 'episode_number' are required "
                    "for media_type 'episode'."
                ),
            },
            status=HTTP.BAD_REQUEST,
        )

    return None


def _seconds_error(data, *, require_position):
    """Return a 400 Response if the seconds fields are unusable, else None."""
    raw_position = data.get("position_seconds")
    if raw_position is None and require_position and "position_seconds" not in data:
        return Response(
            {
                "detail": (
                    "'position_seconds' is required (send null to clear "
                    "the saved position)."
                ),
            },
            status=HTTP.BAD_REQUEST,
        )

    for field in ("position_seconds", "duration_seconds"):
        value = data.get(field)
        if value is None:
            continue
        try:
            _coerce_position(value)
        except (TypeError, ValueError):
            return Response(
                {"detail": f"'{field}' must be an integer >= 0."},
                status=HTTP.BAD_REQUEST,
            )

    return None


def _write_request_error(data, *, require_position):
    """Return a 400 Response if the write payload is malformed, else None."""
    media_type = data.get("media_type")
    if media_type not in MEDIA_TYPES:
        return Response(
            {"detail": f"'media_type' must be one of {MEDIA_TYPES}."},
            status=HTTP.BAD_REQUEST,
        )

    return _identifier_error(data, media_type) or _seconds_error(
        data,
        require_position=require_position,
    )

    return None


_ENTRY_SCHEMA = {
    "type": "object",
    "properties": {
        "media_type": {"type": "string", "enum": list(MEDIA_TYPES)},
        "source": {"type": "string", "nullable": True},
        "media_id": {"type": "string", "nullable": True},
        "season_number": {"type": "integer", "nullable": True},
        "episode_number": {"type": "integer", "nullable": True},
        "ids": {"type": "object"},
        "title": {"type": "string", "nullable": True},
        "series_title": {"type": "string", "nullable": True},
        "position_seconds": {"type": "integer", "nullable": True},
        "duration_seconds": {"type": "integer", "nullable": True},
        "completed": {"type": "boolean"},
        "updated_at": {"type": "string", "format": "date-time", "nullable": True},
    },
}

_WRITE_SCHEMA = {
    "type": "object",
    "required": ["media_type", "ids"],
    "properties": {
        "media_type": {"type": "string", "enum": list(MEDIA_TYPES)},
        "ids": {
            "type": "object",
            "description": (
                "Movies/episodes: at least one of tmdb/imdb/tvdb. "
                "Podcasts: episode_uuid (Pocket Casts UUID or RSS GUID)."
            ),
            "properties": {
                "tmdb": {"type": "string", "nullable": True},
                "imdb": {"type": "string", "nullable": True},
                "tvdb": {"type": "string", "nullable": True},
                "episode_uuid": {"type": "string", "nullable": True},
            },
        },
        "season_number": {
            "type": "integer",
            "nullable": True,
            "description": "Required for media_type 'episode'.",
        },
        "episode_number": {
            "type": "integer",
            "nullable": True,
            "description": "Required for media_type 'episode'.",
        },
        "position_seconds": {
            "type": "integer",
            "nullable": True,
            "description": "Absolute resume position. null clears it.",
        },
        "duration_seconds": {"type": "integer", "nullable": True},
        "completed": {"type": "boolean", "nullable": True},
    },
}

_DETAIL_SCHEMA = {"type": "object", "properties": {"detail": {"type": "string"}}}


# /api/v1/playback/progress/
class PlaybackProgressView(drf_views.APIView):
    """Durable resume positions for movies, episodes and podcasts.

    Complements /api/v1/scrobble/, which can push playback progress in but
    can't read saved positions back out. Positions here are written by API
    clients and by scrobble 'stop'; Plex/Jellyfin/Emby webhook playback is
    not mirrored into this store.
    """

    @extend_schema(
        description=(
            "List saved resume positions, newest first. Supports "
            "?updated_since= for delta sync, ?media_type= (comma separated) "
            "and ?completed=true|false, plus the standard limit/offset."
        ),
        responses={
            200: {
                "type": "object",
                "properties": {
                    "pagination": {"type": "object"},
                    "results": {"type": "array", "items": _ENTRY_SCHEMA},
                },
            },
            400: _DETAIL_SCHEMA,
        },
    )
    def get(self, request):
        """Return the user's saved resume positions."""
        limit, offset, error = parse_limit_offset(request)
        if error:
            return error

        filters, error = _parse_list_filters(request)
        if error:
            return error

        entries = []
        video_types = [
            media_type
            for media_type in filters["media_types"]
            if media_type in _VIDEO_MEDIA_TYPES
        ]
        if video_types:
            entries.extend(self._video_entries(request.user, video_types, filters))
        if MediaTypes.PODCAST.value in filters["media_types"]:
            entries.extend(self._podcast_entries(request.user, filters))

        entries.sort(key=lambda entry: entry["updated_at"] or _EPOCH, reverse=True)
        return Response(paginate_data(request, entries, limit, offset), status=HTTP.OK)

    def _video_entries(self, user, media_types, filters):
        """Serialize PlaybackProgress rows matching the request filters."""
        queryset = PlaybackProgress.objects.filter(
            user=user,
            item__media_type__in=media_types,
        ).select_related("item")
        if filters["updated_since"]:
            queryset = queryset.filter(updated_at__gte=filters["updated_since"])
        if filters["completed"] is not None:
            queryset = queryset.filter(completed=filters["completed"])

        rows = list(queryset)
        show_map = _show_item_map([row.item for row in rows])
        return [_serialize_progress(row, show_map) for row in rows]

    def _podcast_entries(self, user, filters):
        """Serialize Podcast rows that carry a resume position."""
        queryset = Podcast.objects.filter(
            user=user,
            played_up_to_seconds__gt=0,
        ).select_related("item", "episode", "show")

        entries = [_serialize_podcast(podcast) for podcast in queryset]
        since = filters["updated_since"]
        if since:
            entries = [
                entry
                for entry in entries
                if entry["updated_at"] and entry["updated_at"] >= since
            ]
        if filters["completed"] is not None:
            entries = [
                entry for entry in entries if entry["completed"] == filters["completed"]
            ]
        return entries

    @extend_schema(
        description=(
            "Set an absolute resume position. Sending "
            '"position_seconds": null clears it, for clients that cannot '
            "send a DELETE body. Movies/episodes create the metadata item "
            "if it isn't known yet, without creating a watch record; "
            "podcasts require an already-tracked episode."
        ),
        request={"application/json": _WRITE_SCHEMA},
        responses={200: _ENTRY_SCHEMA, 400: _DETAIL_SCHEMA, 404: _DETAIL_SCHEMA},
    )
    def put(self, request):
        """Set or clear a resume position."""
        error = _write_request_error(request.data, require_position=True)
        if error:
            return error

        if request.data.get("position_seconds") is None:
            return self._clear(request)

        media_type = request.data.get("media_type")
        if media_type == MediaTypes.PODCAST.value:
            return self._put_podcast(request)
        return self._put_video(request, media_type)

    def _put_video(self, request, media_type):
        """Upsert a movie/episode position, creating the Item if needed."""
        data = request.data
        try:
            item = resolve_video_item(
                request.user,
                media_type,
                data.get("ids") or {},
                data.get("season_number"),
                data.get("episode_number"),
                create=True,
            )
        except Exception as e:
            return Response(
                {"detail": "Could not resolve media.", "errors": str(e)},
                status=HTTP.NOT_FOUND,
            )
        if item is None:
            return Response(
                {"detail": "Could not resolve media."},
                status=HTTP.NOT_FOUND,
            )

        duration = data.get("duration_seconds")
        progress = upsert_playback_progress(
            request.user,
            item,
            _coerce_position(data.get("position_seconds")),
            _coerce_position(duration) if duration is not None else None,
            completed=bool(data.get("completed")),
        )
        progress.item = item
        show_map = _show_item_map([item])
        return Response(_serialize_progress(progress, show_map), status=HTTP.OK)

    def _put_podcast(self, request):
        """Write a podcast position onto the existing Podcast row."""
        podcast = _resolve_podcast(request.user, request.data.get("ids") or {})
        if podcast is None:
            return Response(
                {"detail": "No tracked podcast episode matches that episode_uuid."},
                status=HTTP.NOT_FOUND,
            )

        podcast.played_up_to_seconds = _coerce_position(
            request.data.get("position_seconds"),
        )
        podcast.position_updated_at = timezone.now()
        update_fields = ["played_up_to_seconds", "position_updated_at"]
        if request.data.get("completed"):
            podcast.status = Status.COMPLETED.value
            podcast.last_seen_status = _PODCAST_COMPLETED_STATUS
            update_fields += ["status", "last_seen_status"]
        podcast.save(update_fields=update_fields)

        return Response(_serialize_podcast(podcast), status=HTTP.OK)

    @extend_schema(
        description="Clear a saved resume position.",
        request={"application/json": _WRITE_SCHEMA},
        responses={204: None, 400: _DETAIL_SCHEMA, 404: _DETAIL_SCHEMA},
    )
    def delete(self, request):
        """Clear a saved resume position."""
        error = _write_request_error(request.data, require_position=False)
        if error:
            return error
        return self._clear(request)

    def _clear(self, request):
        """Delete the stored position for the identified media."""
        data = request.data
        media_type = data.get("media_type")

        if media_type == MediaTypes.PODCAST.value:
            podcast = _resolve_podcast(request.user, data.get("ids") or {})
            if podcast is None:
                return Response(
                    {"detail": "No tracked podcast episode matches that episode_uuid."},
                    status=HTTP.NOT_FOUND,
                )
            podcast.played_up_to_seconds = None
            podcast.position_updated_at = timezone.now()
            podcast.save(
                update_fields=["played_up_to_seconds", "position_updated_at"],
            )
            return Response(status=HTTP.NO_CONTENT)

        try:
            item = resolve_video_item(
                request.user,
                media_type,
                data.get("ids") or {},
                data.get("season_number"),
                data.get("episode_number"),
                create=False,
            )
        except Exception as e:
            return Response(
                {"detail": "Could not resolve media.", "errors": str(e)},
                status=HTTP.NOT_FOUND,
            )
        if item is None:
            return Response(
                {"detail": "Could not resolve media."},
                status=HTTP.NOT_FOUND,
            )

        PlaybackProgress.objects.filter(user=request.user, item=item).delete()
        return Response(status=HTTP.NO_CONTENT)
