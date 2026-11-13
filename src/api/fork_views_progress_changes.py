"""Ordered change feed for resume progress.

Mirrors the watched-state feed deliberately: same cursor semantics, same
checkpoint proof, same cursor-expired contract. A client that implements one
implements the other, and the retention machinery is shared rather than forked.
"""

import logging
from http import HTTPStatus as HTTP  # noqa: N814

from drf_spectacular.utils import extend_schema
from rest_framework import views as drf_views
from rest_framework.response import Response

from app.services.progress_changes import (
    PROGRESS_RESOURCE,
    progress_changes_since,
    retained_progress_range,
)
from integrations.models import SyncBinding
from integrations.state.checkpoints import record_applied_position

from .fork_views_playback import item_reference, show_item_map
from .fork_views_sync import (
    FEED_ERROR_SCHEMA,
    FEED_SCHEMA,
    SYNC_PARAMETERS,
    availability,
    strict_feed,
)

logger = logging.getLogger(__name__)

MAX_CHANGE_PAGE = 500


# /api/v1/sync/progress-changes/
class ProgressChangeFeedView(drf_views.APIView):
    """Serve the ordered resume-progress change feed."""

    @extend_schema(parameters=SYNC_PARAMETERS, responses={200: FEED_SCHEMA, 400: FEED_ERROR_SCHEMA, 409: FEED_ERROR_SCHEMA})
    def get(self, request):
        """Return progress changes after a cursor, in server order."""
        if "contract" in request.query_params:
            return strict_feed(request, "progress")

        raw_cursor = request.query_params.get("cursor", "0")
        try:
            cursor = int(raw_cursor)
        except ValueError:
            return Response(
                {"detail": "cursor must be an integer sequence."},
                status=HTTP.BAD_REQUEST,
            )

        try:
            limit = min(int(request.query_params.get("limit", 100)), MAX_CHANGE_PAGE)
        except ValueError:
            return Response(
                {"detail": "limit must be an integer."},
                status=HTTP.BAD_REQUEST,
            )

        oldest, newest = retained_progress_range(request.user)
        feed_status = availability(request.user, "progress")
        if 0 < cursor < feed_status["minimum_valid_cursor"]:
            return Response(
                {
                    "code": "cursor_expired",
                    "detail": (
                        "This cursor is older than the retained change log. "
                        "Read the current progress snapshot and resume from "
                        "its sequence."
                    ),
                    "oldest_sequence": oldest,
                    "newest_sequence": newest,
                },
                status=HTTP.CONFLICT,
            )

        binding = self._acknowledging_binding(request)
        if binding is not None and cursor > 0:
            record_applied_position(binding, cursor, resource=PROGRESS_RESOURCE)

        changes = progress_changes_since(request.user, cursor, limit=limit)
        show_map = show_item_map([change.item for change in changes if change.item])
        results = [
            {
                "sequence": change.sequence,
                "kind": change.kind,
                "position_seconds": change.position_seconds,
                "duration_seconds": change.duration_seconds,
                "completed": change.completed,
                "media_id": change.item.media_id if change.item else None,
                "source": change.item.source if change.item else None,
                "media_type": change.item.media_type if change.item else None,
                **(item_reference(change.item, show_map) if change.item else {}),
                "origin_key": change.origin_key,
                "correlation_id": str(change.correlation_id),
            }
            for change in changes
        ]

        return Response(
            {
                "results": results,
                "next_cursor": results[-1]["sequence"] if results else cursor,
                "has_more": len(results) == limit,
                "oldest_sequence": oldest,
                "newest_sequence": newest,
                **feed_status,
            },
            status=HTTP.OK,
        )

    @staticmethod
    def _acknowledging_binding(request):
        """Return the binding this pull speaks for, if it names one."""
        origin_key = request.query_params.get("connection")
        if not origin_key:
            return None
        return SyncBinding.objects.filter(
            user=request.user,
            origin_key=origin_key,
        ).first()
