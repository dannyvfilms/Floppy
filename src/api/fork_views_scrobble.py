# FORK: generic scrobble endpoint for third-party playback clients (e.g.
# streaming apps that aren't Plex/Jellyfin/Emby). Kept separate from
# fork_views_tracking.py since it's a public integration surface rather
# than a web-UI parity mirror. URL wiring lives in fork_urls.py.
import logging
from http import HTTPStatus as HTTP  # noqa: N814

from drf_spectacular.utils import extend_schema
from rest_framework import views as drf_views
from rest_framework.response import Response

import app.providers.tmdb
from app import live_playback
from app.models import MediaTypes
from integrations.webhooks.generic_scrobble import GenericScrobbleProcessor, is_played

from . import fork_views_playback
from .helpers import try_parse_datetime_input

logger = logging.getLogger(__name__)

_ACTIONS = ("start", "pause", "stop")
_MEDIA_TYPES = (MediaTypes.MOVIE.value, MediaTypes.EPISODE.value)
_EVENT_TYPE_MAP = {
    "start": "media.play",
    "pause": "media.pause",
    "stop": "media.stop",
}


def _scrobble_request_error(data):
    """Return a 400 Response if the scrobble payload is malformed, else None."""
    action = data.get("action")
    if action not in _ACTIONS:
        return Response(
            {"detail": f"'action' must be one of {_ACTIONS}."},
            status=HTTP.BAD_REQUEST,
        )

    media_type = data.get("media_type")
    if media_type not in _MEDIA_TYPES:
        return Response(
            {"detail": f"'media_type' must be one of {_MEDIA_TYPES}."},
            status=HTTP.BAD_REQUEST,
        )

    ids = data.get("ids") or {}
    if not any(ids.get(key) for key in ("tmdb", "imdb", "tvdb")):
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

    raw_played_at = data.get("played_at")
    if raw_played_at:
        try:
            try_parse_datetime_input(raw_played_at)
        except (TypeError, ValueError):
            return Response(
                {"detail": "Invalid played_at format."},
                status=HTTP.BAD_REQUEST,
            )

    return None


def _resolve_live_playback_media_id(media_type, ids):
    """Best-effort tmdb id resolution for the Now Playing card.

    Falls back to a single TMDB find() lookup when only imdb/tvdb ids are
    given. Failures are swallowed — the live card is best-effort and must
    never block a client's playback loop.
    """
    if ids.get("tmdb"):
        return str(ids["tmdb"])

    ext_id = ids.get("imdb") or ids.get("tvdb")
    ext_type = "imdb_id" if ids.get("imdb") else "tvdb_id"
    if not ext_id:
        return None

    try:
        find_response = app.providers.tmdb.find(ext_id, ext_type)
    except Exception:
        logger.warning("Scrobble live-playback id resolution failed", exc_info=True)
        return None

    if media_type == MediaTypes.MOVIE.value:
        results = find_response.get("movie_results") or []
        return str(results[0]["id"]) if results else None

    episode_results = find_response.get("tv_episode_results") or []
    if episode_results:
        return str(episode_results[0]["show_id"])
    tv_results = find_response.get("tv_results") or []
    return str(tv_results[0]["id"]) if tv_results else None


# /api/v1/scrobble/
class ScrobbleView(drf_views.APIView):
    """Generic start/pause/stop scrobble events for third-party clients.

    Authenticated the same way as the rest of the API (Bearer/API-Key
    token). "start"/"pause" only update the home page's Now Playing card;
    "stop" additionally persists a durable progress/status update via the
    same shared logic the Plex/Jellyfin/Emby webhooks use internally.
    """

    @extend_schema(
        description=(
            "Record a playback start/pause/stop event from a third-party "
            "client. Movies are identified by tmdb/imdb id; episodes "
            "additionally require season_number/episode_number. "
            "'start'/'pause' only update the live Now Playing card; "
            "'stop' persists a durable watch/progress update."
        ),
        request={
            "application/json": {
                "type": "object",
                "required": ["action", "media_type", "ids"],
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": list(_ACTIONS),
                    },
                    "media_type": {
                        "type": "string",
                        "enum": list(_MEDIA_TYPES),
                    },
                    "ids": {
                        "type": "object",
                        "description": "At least one of tmdb/imdb/tvdb is required.",
                        "properties": {
                            "tmdb": {"type": "string", "nullable": True},
                            "imdb": {"type": "string", "nullable": True},
                            "tvdb": {"type": "string", "nullable": True},
                        },
                    },
                    "title": {"type": "string", "nullable": True},
                    "series_title": {
                        "type": "string",
                        "nullable": True,
                        "description": "Required (in effect) for media_type "
                        "'episode' to power live-card display and title "
                        "search fallback.",
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
                    "position_seconds": {"type": "integer", "nullable": True},
                    "duration_seconds": {"type": "integer", "nullable": True},
                    "completed": {
                        "type": "boolean",
                        "nullable": True,
                        "description": "Only used by 'stop'. Overrides the "
                        "position/duration completion heuristic when given.",
                    },
                    "played_at": {
                        "type": "string",
                        "format": "date-time",
                        "nullable": True,
                        "description": "Only used by 'stop'. Defaults to now.",
                    },
                },
            },
        },
        responses={
            200: {
                "type": "object",
                "properties": {"detail": {"type": "string"}},
            },
            400: {
                "type": "object",
                "properties": {"detail": {"type": "string"}},
            },
            404: {
                "type": "object",
                "properties": {
                    "detail": {"type": "string"},
                    "errors": {"type": "string"},
                },
            },
        },
    )
    def post(self, request):
        """Validate and apply a scrobble event."""
        error = _scrobble_request_error(request.data)
        if error:
            return error

        action = request.data.get("action")
        media_type = request.data.get("media_type")
        ids = request.data.get("ids") or {}

        self._update_live_playback(request.user, action, media_type, ids, request.data)

        if action != "stop":
            return Response({"detail": "accepted"}, status=HTTP.OK)

        raw_played_at = request.data.get("played_at")
        payload = {
            "media_type": media_type,
            "ids": ids,
            "title": request.data.get("title"),
            "series_title": request.data.get("series_title"),
            "season_number": request.data.get("season_number"),
            "episode_number": request.data.get("episode_number"),
            "position_seconds": request.data.get("position_seconds"),
            "duration_seconds": request.data.get("duration_seconds"),
            "completed": request.data.get("completed"),
            "played_at": try_parse_datetime_input(raw_played_at)
            if raw_played_at
            else None,
        }
        try:
            GenericScrobbleProcessor().process_payload(payload, request.user)
        except Exception as e:
            return Response(
                {"detail": "Could not resolve media.", "errors": str(e)},
                status=HTTP.NOT_FOUND,
            )

        self._store_playback_progress(
            request.user,
            payload,
            completed=is_played(payload),
        )

        return Response({"detail": "accepted"}, status=HTTP.OK)

    def _store_playback_progress(self, user, payload, *, completed):
        """Persist the durable resume position; failures are never raised.

        The processor has just resolved/created the Item, so this is a cheap
        lookup. Exposed to clients via /api/v1/playback/progress/.
        """
        position = payload.get("position_seconds")
        if position is None:
            return
        try:
            item = fork_views_playback.resolve_video_item(
                user,
                payload["media_type"],
                payload["ids"],
                payload.get("season_number"),
                payload.get("episode_number"),
                create=False,
            )
            if item is None:
                return
            duration = payload.get("duration_seconds")
            fork_views_playback.upsert_playback_progress(
                user,
                item,
                max(0, int(position)),
                max(0, int(duration)) if duration is not None else None,
                completed=completed,
            )
        except Exception:
            logger.warning("Scrobble playback-progress update failed", exc_info=True)

    def _update_live_playback(self, user, action, media_type, ids, data):
        """Update the Now Playing card; failures are logged, never raised."""
        try:
            media_id = _resolve_live_playback_media_id(media_type, ids)
            live_playback.apply_playback_event(
                user_id=user.id,
                event_type=_EVENT_TYPE_MAP[action],
                playback_media_type=media_type,
                media_id=media_id,
                title=data.get("title"),
                series_title=data.get("series_title"),
                episode_title=data.get("title")
                if media_type == MediaTypes.EPISODE.value
                else None,
                season_number=data.get("season_number"),
                episode_number=data.get("episode_number"),
                view_offset_seconds=data.get("position_seconds"),
                duration_seconds=data.get("duration_seconds"),
            )
        except Exception:
            logger.warning("Scrobble live-playback update failed", exc_info=True)
