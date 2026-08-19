# FORK: full statistics endpoints returning the same cached payload the web
# statistics dashboard renders (resolves the upstream "reuse WebUI
# statistics" TODO). URL wiring lives in fork_urls.py.
import decimal
import logging
from datetime import date, datetime
from http import HTTPStatus as HTTP  # noqa: N814

from django.db.models import Model
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import views as drf_views
from rest_framework.response import Response

from app import statistics_cache
from app.statistics_views import (
    _get_predefined_range_date_strings,
    _identify_predefined_range,
)

logger = logging.getLogger(__name__)

_TIME_FORMAT = "%Y-%m-%d"

# Fields to surface for any bare model instance embedded in statistics data
# (top_rated, top_played, and similar lists hold raw Media rows since the
# web template accesses them directly; the API needs a plain projection).
_MODEL_PROJECTION_FIELDS = (
    "id",
    "score",
    "progress",
    "status",
    "start_date",
    "end_date",
    "notes",
)


def _json_safe(value):
    """Recursively convert statistics data into JSON-serializable values.

    Model instances (raw Media rows embedded for template rendering) are
    reduced to a plain dict; everything else passes through DRF's encoder.
    """
    if isinstance(value, Model):
        payload = {
            field: _json_safe(getattr(value, field))
            for field in _MODEL_PROJECTION_FIELDS
            if hasattr(value, field)
        }
        item = getattr(value, "item", None)
        if item is not None:
            payload["item"] = {
                "media_id": getattr(item, "media_id", None),
                "source": getattr(item, "source", None),
                "media_type": getattr(item, "media_type", None),
                "title": getattr(item, "title", None),
                "image": getattr(item, "image", None),
            }
        return payload
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value
    return value


def _resolve_range(request):
    """Resolve start/end datetimes like the web statistics view.

    Returns (start_date, end_date, range_name, error_response). Defaults to
    the user's preferred predefined range; start_date=end_date="all" selects
    All Time.
    """
    today = timezone.localdate()
    one_year_ago = today.replace(year=today.year - 1)
    start_date_param = request.GET.get("start_date")
    end_date_param = request.GET.get("end_date")

    if not start_date_param and not end_date_param:
        preferred_range = getattr(request.user, "statistics_default_range", None)
        if preferred_range not in statistics_cache.PREDEFINED_RANGES:
            preferred_range = "Last 12 Months"
        preferred_start, preferred_end = _get_predefined_range_date_strings(
            preferred_range,
            today,
            _TIME_FORMAT,
        )
        start_date_str = preferred_start or one_year_ago.strftime(_TIME_FORMAT)
        end_date_str = preferred_end or today.strftime(_TIME_FORMAT)
    else:
        start_date_str = start_date_param or one_year_ago.strftime(_TIME_FORMAT)
        end_date_str = end_date_param or today.strftime(_TIME_FORMAT)

    if start_date_str == "all" and end_date_str == "all":
        start_date = None
        end_date = None
    else:
        start = parse_date(start_date_str)
        end = parse_date(end_date_str)
        if start is None or end is None:
            return (
                None,
                None,
                None,
                Response(
                    {"detail": "Invalid date format (expected YYYY-MM-DD or 'all')."},
                    status=HTTP.BAD_REQUEST,
                ),
            )
        tz = timezone.get_current_timezone()
        start_date = timezone.make_aware(
            datetime.combine(start, datetime.min.time()),
            tz,
        )
        end_date = timezone.make_aware(
            datetime.combine(end, datetime.max.time()),
            tz,
        )

    range_name = _identify_predefined_range(start_date, end_date)
    return start_date, end_date, range_name, None


# /api/v1/statistics/overview/
class StatisticsOverviewView(drf_views.APIView):
    """The full statistics payload the web dashboard renders.

    Includes media counts, activity heatmap data, media-type/score
    distributions, top rated/played, talent and studio boards, and the
    per-domain (video/music/podcast/reading/game) breakdowns.
    """

    def get(self, request):
        """Return statistics for the date range (default: user's preference)."""
        start_date, end_date, range_name, error = _resolve_range(request)
        if error:
            return error
        data = statistics_cache.get_statistics_data(
            request.user,
            start_date,
            end_date,
            range_name=range_name,
        )
        return Response(
            {
                "range": {
                    "start_date": start_date,
                    "end_date": end_date,
                    "range_name": range_name,
                },
                "statistics": _json_safe(data),
            },
            status=HTTP.OK,
        )


# /api/v1/statistics/refresh/
class StatisticsRefreshView(drf_views.APIView):
    """Force a statistics-cache refresh (mirrors web refresh_statistics)."""

    def post(self, request):
        """Invalidate and rebuild the given predefined range."""
        range_name = request.data.get("range_name")
        if not range_name:
            return Response(
                {
                    "detail": "range_name is required.",
                    "choices": list(statistics_cache.PREDEFINED_RANGES),
                },
                status=HTTP.BAD_REQUEST,
            )
        if range_name not in statistics_cache.PREDEFINED_RANGES:
            return Response(
                {
                    "detail": "Invalid range_name.",
                    "choices": list(statistics_cache.PREDEFINED_RANGES),
                },
                status=HTTP.BAD_REQUEST,
            )
        statistics_cache.invalidate_all_statistics_days(
            request.user.id,
            reason=f"manual_statistics_refresh:{range_name}",
        )
        statistics_cache.invalidate_statistics_cache(request.user.id, range_name)
        statistics_cache.schedule_statistics_refresh(
            request.user.id,
            range_name,
            debounce_seconds=0,
            countdown=0,
            allow_inline=True,
        )
        return Response({"scheduled": True}, status=HTTP.ACCEPTED)
