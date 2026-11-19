# FORK: full statistics endpoints returning the same cached payload the web
# statistics dashboard renders (resolves the upstream "reuse WebUI
# statistics" TODO). URL wiring lives in fork_urls.py.
import decimal
import json
import logging
from datetime import date, datetime
from http import HTTPStatus as HTTP  # noqa: N814

from django.db.models import Model
from django.utils import timezone
from django.utils.dateparse import parse_date
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import views as drf_views
from rest_framework.response import Response

from app import statistics_cache, stats_cast_crew
from app import statistics_views as web_statistics
from app.models import MediaTypes
from app.statistics_views import (
    _get_predefined_range_date_strings,
    _identify_predefined_range,
)
from app.stats_utils import MEDIA_TYPE_HOURS_ORDER
from users.models import (
    ActivityHistoryViewChoices,
    DurationFormatChoices,
    GenreSortChoices,
    RatingScaleChoices,
    StatisticsCompareChoices,
    TopTalentSortChoices,
    WeekStartDayChoices,
)

from .fork_views_history import django_request

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
    requested_range = request.GET.get("range_name")

    if requested_range in statistics_cache.PREDEFINED_RANGES:
        # A named range resolves on the server so the dates use the account's
        # timezone, not the device's.
        start_date_param, end_date_param = _get_predefined_range_date_strings(
            requested_range,
            today,
            _TIME_FORMAT,
        )

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


def _media_type_gate(user):
    """Return the media types the filter may offer and the selected ones."""
    allowed = set(user.get_enabled_media_types()) | {
        MediaTypes.TV.value,
        MediaTypes.MOVIE.value,
        MediaTypes.ANIME.value,
        MediaTypes.GAME.value,
    }
    return {
        "available": [m for m in MEDIA_TYPE_HOURS_ORDER if m in allowed],
        "selected": web_statistics._normalize_statistics_media_types(
            getattr(user, "statistics_default_media_types", ""),
            allowed=allowed,
        ),
    }


def _activity_period_label(range_name, selected):
    """Name the compared period the way the web activity card does."""
    shorthand = {
        "Today": "yesterday",
        "Yesterday": "previous day",
        "This Week": "last week",
        "This Month": "last month",
        "This Year": "last year",
    }
    if range_name and range_name.lower().startswith("last"):
        return range_name.lower()
    if range_name in shorthand:
        return shorthand[range_name]
    return web_statistics.STATISTICS_COMPARE_LABELS.get(selected, "").lower()


def _comparison_block(request, data, start_date, end_date, range_name):
    """Return the Compare-to section: options plus per-type deltas."""
    web = web_statistics
    requested = request.GET.get("compare")
    if requested is None:
        requested = getattr(
            request.user,
            "statistics_compare_mode",
            StatisticsCompareChoices.PREVIOUS_PERIOD,
        )
    selected = web._normalize_statistics_compare_mode(
        requested,
        finite_range=start_date is not None and end_date is not None,
    )
    compare_start, compare_end = web._resolve_statistics_comparison_range(
        start_date,
        end_date,
        selected,
    )
    comparison_minutes = {}
    if compare_start and compare_end:
        comparison_minutes = statistics_cache.get_statistics_minutes_by_type(
            request.user,
            compare_start,
            compare_end,
            range_name=_identify_predefined_range(compare_start, compare_end),
        )
    current_tooltip, compare_tooltip = web._get_statistics_card_tooltip_labels(
        range_name,
        selected,
    )
    suffix = web._get_statistics_card_comparison_suffix(
        request.user,
        range_name,
        selected,
        compare_start,
        compare_end,
    )
    context = {
        "selected_compare_mode": selected,
        "hours_per_media_type_comparison": web._build_hours_per_media_type_comparison(
            web._get_statistics_minutes_by_type(data),
            comparison_minutes,
            selected,
            suffix,
            current_tooltip,
            compare_tooltip,
            duration_format=getattr(request.user, "duration_format", "hours_minutes"),
        ),
        "media_type_colors": {},
    }
    total_minutes = sum(web._get_statistics_minutes_by_type(data).values())
    total_comparison = web._build_hours_per_media_type_comparison(
        {"all": total_minutes},
        {"all": sum(float(v or 0) for v in comparison_minutes.values())},
        selected,
        suffix,
        current_tooltip,
        compare_tooltip,
        duration_format=getattr(request.user, "duration_format", "hours_minutes"),
    ).get("all")
    section = web._statistics_comparison_section(request.user, context, data)
    period_label = _activity_period_label(range_name, selected)
    section["total"] = {
        "periodLabel": period_label,
        **web._statistics_comparison(total_comparison or {}, period_label),
    }
    section["rangeLabel"] = web._format_statistics_range_label(
        request.user,
        compare_start,
        compare_end,
    )
    # The web page hides its own colour fallback; clients pick theme colours.
    for row in section["rows"]:
        row.pop("color", None)
    return _json_safe(section)


# /api/v1/statistics/overview/
class StatisticsOverviewView(drf_views.APIView):
    """The full statistics payload the web dashboard renders.

    Includes media counts, activity heatmap data, media-type/score
    distributions, top rated/played, talent and studio boards, and the
    per-domain (video/music/podcast/reading/game) breakdowns.
    """

    @extend_schema(
        operation_id="getStatisticsOverview",
        parameters=[
            OpenApiParameter("start_date", str),
            OpenApiParameter("end_date", str),
            OpenApiParameter(
                "compare",
                str,
                description="previous_period, last_year or none (default: preference)",
            ),
        ],
    responses={200: OpenApiTypes.OBJECT},
    )
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
        building = bool(data.pop("statistics_building", False))
        compare = _comparison_block(
            request,
            data,
            start_date,
            end_date,
            range_name,
        )
        return Response(
            {
                "range": {
                    "start_date": start_date,
                    "end_date": end_date,
                    "range_name": range_name,
                    "label": web_statistics._format_statistics_range_label(
                        request.user,
                        start_date,
                        end_date,
                    ),
                },
                "building": building,
                "comparison": compare,
                "media_types": _media_type_gate(request.user),
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
        from app import statistics_sync

        statistics_sync.request_manual_refresh(request.user, range_name)
        return Response({"scheduled": True}, status=HTTP.ACCEPTED)


_PREFERENCE_CHOICES = {
    "compare_mode": ("statistics_compare_mode", StatisticsCompareChoices.values),
    "default_range": (
        "statistics_default_range",
        list(statistics_cache.PREDEFINED_RANGES),
    ),
    "top_talent_sort_by": ("top_talent_sort_by", TopTalentSortChoices.values),
    "genre_sort_by": ("genre_sort_by", GenreSortChoices.values),
    "studio_sort_by": ("studio_sort_by", GenreSortChoices.values),
}


# The statistics modal's display preferences (web update_statistics_preferences).
# Changing the last four reshapes the day payloads, so every day rebuilds.
_DISPLAY_CHOICES = {
    "activity_history_view": ActivityHistoryViewChoices.values,
    "duration_format": DurationFormatChoices.values,
    "week_start_day": WeekStartDayChoices.values,
    "rating_scale": RatingScaleChoices.values,
}


def _preferences_payload(user):
    from app.providers import tvdb

    return {
        "activity_history_view": user.activity_history_view,
        "duration_format": user.duration_format,
        "week_start_day": user.week_start_day,
        "rating_scale": user.rating_scale,
        # The Anime split only exists when TVDB can tag a show as anime.
        "stats_split_tv_anime": user.stats_split_tv_anime,
        "stats_split_available": bool(not user.anime_enabled and tvdb.enabled()),
        "display_choices": {key: list(values) for key, values in _DISPLAY_CHOICES.items()},
        "compare_mode": user.statistics_compare_mode,
        "default_range": user.statistics_default_range,
        "top_talent_sort_by": user.top_talent_sort_by,
        "genre_sort_by": user.genre_sort_by,
        "studio_sort_by": user.studio_sort_by,
        "media_types": _media_type_gate(user),
        "choices": {
            "compare_mode": list(StatisticsCompareChoices.values),
            "default_range": list(statistics_cache.PREDEFINED_RANGES),
            "top_talent_sort_by": list(TopTalentSortChoices.values),
            "genre_sort_by": list(GenreSortChoices.values),
            "studio_sort_by": list(GenreSortChoices.values),
        },
    }


# /api/v1/statistics/preferences/
class StatisticsPreferencesView(drf_views.APIView):
    """The statistics page's autosaved choices (compare, range, sorts, types)."""

    @extend_schema(operation_id="getStatisticsPreferences", responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Return the saved statistics preferences and their valid values."""
        return Response(_preferences_payload(request.user), status=HTTP.OK)

    @extend_schema(operation_id="updateStatisticsPreferences", request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def patch(self, request):
        """Save any of compare_mode, default_range, sorts and media_types."""
        data = request.data
        for key, (_field, valid) in _PREFERENCE_CHOICES.items():
            if key in data and data[key] not in valid:
                return Response(
                    {"detail": f"Invalid {key}", "valid_values": list(valid)},
                    status=HTTP.BAD_REQUEST,
                )
        media_types = None
        if "media_types" in data:
            raw = data["media_types"]
            tokens = (
                [str(t).strip() for t in raw]
                if isinstance(raw, (list, tuple))
                else [t.strip() for t in str(raw or "").split(",")]
            )
            tokens = [t for t in tokens if t]
            if any(t not in MEDIA_TYPE_HOURS_ORDER for t in tokens):
                return Response(
                    {
                        "detail": "Invalid media_types",
                        "valid_values": list(MEDIA_TYPE_HOURS_ORDER),
                    },
                    status=HTTP.BAD_REQUEST,
                )
            media_types = ",".join(
                web_statistics._normalize_statistics_media_types(",".join(tokens)),
            )
        for key, valid in _DISPLAY_CHOICES.items():
            if key in data and data[key] not in valid:
                return Response(
                    {"detail": f"Invalid {key}", "valid_values": list(valid)},
                    status=HTTP.BAD_REQUEST,
                )
        if "stats_split_tv_anime" in data and not isinstance(
            data["stats_split_tv_anime"],
            bool,
        ):
            return Response(
                {"detail": "Invalid stats_split_tv_anime"},
                status=HTTP.BAD_REQUEST,
            )
        for key, (field, _valid) in _PREFERENCE_CHOICES.items():
            if key in data:
                request.user.update_preference(field, data[key])
        changed = []
        for key in _DISPLAY_CHOICES:
            if key in data and getattr(request.user, key) != data[key]:
                setattr(request.user, key, data[key])
                changed.append(key)
        if (
            "stats_split_tv_anime" in data
            and request.user.stats_split_tv_anime != data["stats_split_tv_anime"]
        ):
            request.user.stats_split_tv_anime = data["stats_split_tv_anime"]
            changed.append("stats_split_tv_anime")
        if changed:
            request.user.save(update_fields=changed)
            if set(changed) - {"activity_history_view"}:
                statistics_cache.invalidate_all_statistics_days(
                    request.user.id,
                    reason="statistics_preferences_changed",
                )
        if media_types is not None:
            request.user.update_preference("statistics_default_media_types", media_types)
        return Response(_preferences_payload(request.user), status=HTTP.OK)


# /api/v1/statistics/talent/
class StatisticsTalentView(drf_views.APIView):
    """Top talent, studios, taste signals and the featured repeat player."""

    @extend_schema(
        operation_id="getStatisticsTalent",
        parameters=[
            OpenApiParameter("range_name", str),
            OpenApiParameter("start_date", str),
            OpenApiParameter("end_date", str),
            OpenApiParameter("compare", str),
        ],
    responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        """Return the web talent section as JSON."""
        updates = {"format": "json"}
        for source, target in (("start_date", "start-date"), ("end_date", "end-date")):
            if request.GET.get(source):
                updates[target] = request.GET[source]
        response = web_statistics.statistics_talent_fragment(
            django_request(request, **updates),
        )
        return Response(json.loads(response.content), status=HTTP.OK)


# /api/v1/statistics/featured-person/
class StatisticsFeaturedPersonView(drf_views.APIView):
    """Pick the person the Featured Repeat Player card shows."""

    @extend_schema(operation_id="selectStatisticsFeaturedPerson", request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def post(self, request):
        """Return the person's card data and media strip for the range."""
        data = request.data
        person_source = data.get("person_source")
        person_id = data.get("person_id")
        if not person_source or not person_id:
            return Response(
                {"detail": "person_source and person_id are required."},
                status=HTTP.BAD_REQUEST,
            )
        sort_by = data.get("sort_by") or getattr(request.user, "top_talent_sort_by", "plays")
        if sort_by not in TopTalentSortChoices.values:
            return Response({"detail": "Invalid sort_by"}, status=HTTP.BAD_REQUEST)
        start_date, end_date = web_statistics._resolve_statistics_range_inputs(
            data.get("range_name"),
            data.get("start_date"),
            data.get("end_date"),
        )
        try:
            total = int(data.get("total_library_titles"))
        except (TypeError, ValueError):
            total = None
        if total is None or total < 0:
            total = statistics_cache.get_statistics_media_count(
                request.user,
                start_date,
                end_date,
                range_name=data.get("range_name"),
            ).get("total", 0)
        person, strip = stats_cast_crew.get_featured_person_with_strip(
            request.user,
            person_source,
            person_id,
            start_date,
            end_date,
            total_library_titles=total,
            sort_by=sort_by,
        )
        if not person:
            return Response({"detail": "Person not found."}, status=HTTP.NOT_FOUND)
        return Response(
            {
                "featured_person": _json_safe(person),
                "media_strip": _json_safe(
                    stats_cast_crew.build_media_strip_row(
                        strip,
                        person_name=person.get("name"),
                        total_titles=person.get("unique_titles"),
                        sort_by=sort_by,
                    ),
                ),
            },
            status=HTTP.OK,
        )
