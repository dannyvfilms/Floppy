# FORK: ListenBrainz-compatible ingest endpoints. Mounted at the root under
# /apis/listenbrainz/1/ rather than /api/v1/ so that any client accepting a
# custom ListenBrainz URL (Multi-Scrobbler, Navidrome, Pano Scrobbler, ...) can
# point at Floppy's base URL unmodified. Receive-only: Floppy never submits
# listens outward. URL wiring lives in listenbrainz_urls.py.
import logging
from http import HTTPStatus as HTTP  # noqa: N814

from drf_spectacular.utils import extend_schema
from rest_framework import views as drf_views
from rest_framework.response import Response

from api.authentication import ListenBrainzTokenAuthentication
from integrations.webhooks.listenbrainz import ListenBrainzScrobbleProcessor

logger = logging.getLogger(__name__)

# "single" and "import" are recorded; "playing_now" is accepted but not stored.
_RECORDED_LISTEN_TYPES = ("single", "import")
_LISTEN_TYPES = (*_RECORDED_LISTEN_TYPES, "playing_now")

MAX_LISTENS_PER_SUBMISSION = 1000


def _error(message, status=HTTP.BAD_REQUEST):
    """Return a ListenBrainz-shaped error response."""
    return Response({"code": int(status), "error": message}, status=status)


@extend_schema(
    summary="Submit listens (ListenBrainz-compatible)",
    description=(
        "Accepts scrobbles from any ListenBrainz-compatible client. "
        "Authenticate with `Authorization: Token <your API token>`. "
        "`playing_now` submissions are accepted but not recorded."
    ),
    request={
        "application/json": {
            "type": "object",
            "properties": {
                "listen_type": {"type": "string", "enum": list(_LISTEN_TYPES)},
                "payload": {"type": "array", "items": {"type": "object"}},
            },
        },
    },
    responses={
        200: {"type": "object", "properties": {"status": {"type": "string"}}},
        400: {
            "type": "object",
            "properties": {
                "code": {"type": "integer"},
                "error": {"type": "string"},
            },
        },
    },
)
class SubmitListensView(drf_views.APIView):
    """ListenBrainz `submit-listens` endpoint."""

    authentication_classes = [ListenBrainzTokenAuthentication]

    def post(self, request):
        """Validate a submission and record its listens."""
        data = request.data
        if not isinstance(data, dict):
            return _error("JSON document must be a single object.")

        listen_type = data.get("listen_type")
        if listen_type not in _LISTEN_TYPES:
            return _error(
                f"Invalid listen_type. Must be one of: {', '.join(_LISTEN_TYPES)}.",
            )

        payload = data.get("payload")
        if not isinstance(payload, list):
            return _error("JSON document must contain a 'payload' list.")

        if len(payload) > MAX_LISTENS_PER_SUBMISSION:
            return _error(
                f"Too many listens in one submission "
                f"(maximum {MAX_LISTENS_PER_SUBMISSION}).",
            )

        if listen_type == "single" and len(payload) != 1:
            return _error(
                "Submission of type 'single' must contain exactly one listen."
            )

        # Accept and drop now-playing pings: recording one would mean creating
        # catalog rows for a track the user may never finish.
        if listen_type == "playing_now":
            return Response({"status": "ok"}, status=HTTP.OK)

        if not getattr(request.user, "music_enabled", False):
            return _error(
                "Music tracking is disabled for this account.",
                status=HTTP.FORBIDDEN,
            )

        if not payload:
            return Response({"status": "ok"}, status=HTTP.OK)

        stats = ListenBrainzScrobbleProcessor().process_listens(payload, request.user)
        self._refresh_statistics(request.user, stats["affected_day_keys"])

        logger.info(
            "ListenBrainz submission for %s: processed=%s skipped=%s errors=%s",
            request.user.username,
            stats["processed"],
            stats["skipped"],
            stats["errors"],
        )
        return Response({"status": "ok"}, status=HTTP.OK)

    def _refresh_statistics(self, user, day_keys):
        """Invalidate cached statistics for the affected days."""
        if not day_keys:
            return
        try:
            from app import statistics_cache

            statistics_cache.invalidate_statistics_days(
                user.id,
                day_values=list(day_keys),
                reason="listenbrainz_submission",
            )
            statistics_cache.schedule_all_ranges_refresh(user.id)
        except Exception:
            logger.exception(
                "Failed to refresh statistics after ListenBrainz submission"
            )


@extend_schema(
    summary="Validate token (ListenBrainz-compatible)",
    description=(
        "Reports whether the supplied token is valid. ListenBrainz clients call "
        "this on startup to confirm the connection."
    ),
    responses={
        200: {
            "type": "object",
            "properties": {
                "code": {"type": "integer"},
                "message": {"type": "string"},
                "valid": {"type": "boolean"},
                "user_name": {"type": "string"},
            },
        },
    },
)
class ValidateTokenView(drf_views.APIView):
    """ListenBrainz `validate-token` endpoint."""

    authentication_classes = [ListenBrainzTokenAuthentication]

    def get(self, request):
        """Confirm the presented token is valid."""
        return Response(
            {
                "code": int(HTTP.OK),
                "message": "Token valid.",
                "valid": True,
                "user_name": request.user.username,
            },
            status=HTTP.OK,
        )
