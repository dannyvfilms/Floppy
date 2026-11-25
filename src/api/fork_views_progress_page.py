# FORK: /api/v1/progress/ — the Progress page's list of shows with what is left
# to watch. The read lives in app.progress_page so web and native share it; URL
# wiring is in fork_urls.py.
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import views as drf_views
from rest_framework.response import Response

from app.progress_page import (
    DEFAULT_LIMIT,
    DEFAULT_SORT,
    GROUPS,
    SORTS,
    build_progress_page,
    normalize_groups,
)


def _int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# /api/v1/progress/
class ProgressPageView(drf_views.APIView):
    """Shows with episodes left, their totals and the next episode to watch."""

    @extend_schema(
        operation_id="listProgress",
        parameters=[
            OpenApiParameter("sort", str, enum=list(SORTS), default=DEFAULT_SORT),
            OpenApiParameter(
                "statuses", str, description="Comma list of: " + ", ".join(GROUPS)
            ),
            OpenApiParameter("offset", int, default=0),
            OpenApiParameter("limit", int, default=DEFAULT_LIMIT),
        ],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        """Return the summary line and one page of shows."""
        params = request.query_params
        return Response(
            build_progress_page(
                request.user,
                sort=params.get("sort", DEFAULT_SORT),
                groups=normalize_groups(params.get("statuses")),
                offset=_int(params.get("offset"), 0),
                limit=_int(params.get("limit"), DEFAULT_LIMIT),
            )
        )
