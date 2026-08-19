import calendar as _calendar
import logging
import re
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta
from django.db.utils import OperationalError
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.timezone import datetime
from django.views.decorators.http import require_GET, require_POST

from app import config, statistics_cache, stats_cast_crew
from app import statistics as stats
from app.models import MediaTypes
from app.providers import tvdb
from app.statistics_talent import _aggregate_top_talent
from app.templatetags import app_tags
from users.models import (
    ActivityHistoryViewChoices,
    DateFormatChoices,
    DurationFormatChoices,
    GenreSortChoices,
    RatingScaleChoices,
    StatisticsCompareChoices,
    TopTalentSortChoices,
    WeekStartDayChoices,
)

DATE_FORMAT_DJANGO_MAP = {
    DateFormatChoices.SYSTEM_DEFAULT: "",
    DateFormatChoices.ISO_8601: "Y-m-d",
    DateFormatChoices.MONTH_D_YYYY: "M d, Y",
    DateFormatChoices.D_MON_YYYY: "d M Y",
    DateFormatChoices.M_D_YYYY: "n/j/Y",
    DateFormatChoices.D_M_YYYY: "j/n/Y",
    DateFormatChoices.DD_MM_YYYY: "d.m.Y",
    DateFormatChoices.YYYY_MM_DD: "Y/m/d",
    DateFormatChoices.LONG_EU: "j M, Y",
}

logger = logging.getLogger(__name__)

NO_CHANGE_DELTA_PERCENT_THRESHOLD = 0.05


def _extend_heatmap_with_future(
    activity_data, start_date, end_date, week_start_sunday=False
):
    """Extend calendar_weeks beyond today with empty future cells to fill the period.

    Runs at render time so it's never affected by the Celery-managed cache.
    """
    if not isinstance(activity_data, dict):
        return activity_data
    today = timezone.localdate()
    weeks = activity_data.get("calendar_weeks", [])
    if not weeks:
        return activity_data

    # Find the first and last dates currently in the grid.
    first_day = None
    for day in weeks[0]:
        if day:
            first_day = date.fromisoformat(day["date"])
            break
    last_day = None
    for day in reversed(weeks[-1]):
        if day:
            last_day = date.fromisoformat(day["date"])
            break
    if not first_day or not last_day:
        return activity_data

    # Determine how far to extend.
    start_local = (
        start_date.date() if start_date and hasattr(start_date, "date") else start_date
    )
    end_local = end_date.date() if end_date and hasattr(end_date, "date") else today

    if (
        start_local
        and start_local.month == 1
        and start_local.day == 1
        and end_local >= today - timedelta(days=1)
    ):
        display_end = date(today.year, 12, 31)
    elif (
        start_local and start_local.day == 1 and end_local >= today - timedelta(days=1)
    ):
        display_end = date(
            today.year, today.month, _calendar.monthrange(today.year, today.month)[1]
        )
    else:
        days_to_end = (
            (6 - today.weekday())
            if not week_start_sunday
            else ((5 - today.weekday()) % 7)
        )
        display_end = today + timedelta(days=days_to_end)

    if display_end <= last_day:
        return activity_data

    # Build a lookup of existing cells, then extend through display_end.
    existing = {date.fromisoformat(d["date"]): d for w in weeks for d in w if d}
    all_days = [
        first_day + timedelta(days=i) for i in range((display_end - first_day).days + 1)
    ]
    all_cells = [
        existing.get(
            d, {"date": d.strftime("%Y-%m-%d"), "count": 0, "level": 0, "future": True}
        )
        for d in all_days
    ]

    new_weeks = [all_cells[i : i + 7] for i in range(0, len(all_cells), 7)]

    # Rebuild month header labels from the full date range.
    week_start_weekday = 6 if week_start_sunday else 0
    months, current_month, monday_count = [], first_day.strftime("%b"), 0
    for d in all_days:
        if d.weekday() == week_start_weekday:
            month = d.strftime("%b")
            if current_month != month:
                months.append((current_month if monday_count > 1 else "", monday_count))
                current_month, monday_count = month, 0
            monday_count += 1
    if monday_count > 1:
        months.append((current_month, monday_count))

    return {**activity_data, "calendar_weeks": new_weeks, "months": months}


STATISTICS_COMPARE_PREVIOUS_PERIOD = "previous_period"
STATISTICS_COMPARE_LAST_YEAR = "last_year"
STATISTICS_COMPARE_NONE = "none"
STATISTICS_COMPARE_LABELS = {
    STATISTICS_COMPARE_PREVIOUS_PERIOD: "Previous period",
    STATISTICS_COMPARE_LAST_YEAR: "Last year",
    STATISTICS_COMPARE_NONE: "No comparison",
}
STATISTICS_CARD_LAST_YEAR_LABELS = {
    "This Year": "last year",
    "This Month": "last year",
}
_STATISTICS_HOURS_DISPLAY_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)h\s+(\d+(?:\.\d+)?)min\s*$"
)


def _statistics_day_boundary(day_value: date | None, *, end_of_day: bool = False):
    if day_value is None:
        return None
    boundary_time = datetime.max.time() if end_of_day else datetime.min.time()
    return timezone.make_aware(
        datetime.combine(day_value, boundary_time),
        timezone.get_current_timezone(),
    )


def _format_statistics_range_label(user, start_date, end_date):
    if not start_date or not end_date:
        return "All Time"

    local_start = timezone.localdate(start_date)
    local_end = timezone.localdate(end_date)
    start_label = app_tags.date_format(_statistics_day_boundary(local_start), user)
    end_label = app_tags.date_format(_statistics_day_boundary(local_end), user)
    if local_start == local_end:
        return start_label
    return f"{start_label} - {end_label}"


def _get_statistics_card_range_label(user, selected_range_name, start_date, end_date):
    if selected_range_name:
        return selected_range_name
    return _format_statistics_range_label(user, start_date, end_date)


def _get_statistics_card_comparison_suffix(
    user,
    selected_range_name,
    compare_mode,
    comparison_start_date,
    comparison_end_date,
):
    if not comparison_start_date or not comparison_end_date:
        return ""

    if compare_mode == STATISTICS_COMPARE_LAST_YEAR:
        card_label = STATISTICS_CARD_LAST_YEAR_LABELS.get(selected_range_name)
        if card_label:
            return card_label

    return f"in {_format_statistics_range_label(user, comparison_start_date, comparison_end_date)}"


def _get_statistics_card_tooltip_labels(selected_range_name, compare_mode):
    current_label = (selected_range_name or "Current period").title()

    if compare_mode == STATISTICS_COMPARE_LAST_YEAR:
        comparison_label = STATISTICS_CARD_LAST_YEAR_LABELS.get(
            selected_range_name,
            STATISTICS_COMPARE_LABELS[compare_mode],
        )
    else:
        comparison_label = STATISTICS_COMPARE_LABELS.get(compare_mode, "")

    return current_label, comparison_label.title()


def _normalize_statistics_compare_mode(compare_mode, *, finite_range: bool):
    if not finite_range:
        return STATISTICS_COMPARE_NONE
    if compare_mode in STATISTICS_COMPARE_LABELS:
        return compare_mode
    return STATISTICS_COMPARE_PREVIOUS_PERIOD


def _resolve_statistics_comparison_range(start_date, end_date, compare_mode):
    if compare_mode == STATISTICS_COMPARE_NONE or not start_date or not end_date:
        return None, None

    local_start = timezone.localdate(start_date)
    local_end = timezone.localdate(end_date)
    if local_start > local_end:
        local_start, local_end = local_end, local_start

    if compare_mode == STATISTICS_COMPARE_PREVIOUS_PERIOD:
        duration_days = (local_end - local_start).days + 1
        compare_end = local_start - timedelta(days=1)
        compare_start = compare_end - timedelta(days=duration_days - 1)
    elif compare_mode == STATISTICS_COMPARE_LAST_YEAR:
        compare_start = local_start - relativedelta(years=1)
        compare_end = local_end - relativedelta(years=1)
    else:
        return None, None

    return (
        _statistics_day_boundary(compare_start),
        _statistics_day_boundary(compare_end, end_of_day=True),
    )


def _resolve_statistics_range_inputs(range_name, start_date_str, end_date_str):
    """Resolve statistics UI date inputs into aware datetimes."""
    if range_name in statistics_cache.PREDEFINED_RANGES:
        return statistics_cache._get_predefined_range_dates(range_name)

    if start_date_str == "all" and end_date_str == "all":
        return None, None

    start_date = None
    end_date = None
    if start_date_str and start_date_str != "all":
        start_date = _statistics_day_boundary(parse_date(start_date_str))
    if end_date_str and end_date_str != "all":
        end_date = _statistics_day_boundary(parse_date(end_date_str), end_of_day=True)

    return start_date, end_date


def _parse_statistics_total_display_to_minutes(value):
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return 0.0

    cleaned = value.strip()
    if "play" in cleaned:
        try:
            return float(cleaned.split()[0])
        except (IndexError, ValueError):
            return 0.0

    match = _STATISTICS_HOURS_DISPLAY_RE.match(cleaned)
    if not match:
        return 0.0

    try:
        hours = float(match.group(1))
        minutes = float(match.group(2))
    except ValueError:
        return 0.0

    return (hours * 60) + minutes


def _get_statistics_minutes_by_type(statistics_data):
    if not isinstance(statistics_data, dict):
        return {}

    raw_minutes = statistics_data.get("minutes_per_media_type")
    if isinstance(raw_minutes, dict):
        return {
            media_type: float(total or 0) for media_type, total in raw_minutes.items()
        }

    return {
        media_type: _parse_statistics_total_display_to_minutes(total)
        for media_type, total in (
            statistics_data.get("hours_per_media_type") or {}
        ).items()
    }


def _format_statistics_total_for_media_type(
    media_type, total, duration_format="hours_minutes"
):
    if media_type == MediaTypes.BOARDGAME.value:
        rounded_total = round(total or 0)
        return f"{rounded_total} play{'s' if rounded_total != 1 else ''}"
    return stats._format_hours_minutes(total or 0, duration_format)


def _format_statistics_percent_change(delta_percent):
    formatted = f"{round(abs(float(delta_percent)), 1):.1f}"
    return formatted.rstrip("0").rstrip(".")


def _build_hours_per_media_type_comparison(
    current_minutes_by_type,
    comparison_minutes_by_type,
    compare_mode,
    comparison_suffix,
    current_period_label,
    comparison_period_label,
    duration_format="hours_minutes",
):
    if compare_mode == STATISTICS_COMPARE_NONE:
        return {
            media_type: {
                "badge": "",
                "badge_state": "none",
                "badge_short": "",
                "badge_classes": "",
                "details": "No comparison selected",
                "details_classes": "text-gray-500",
                "tooltip": None,
            }
            for media_type in current_minutes_by_type
        }

    media_types = list(
        dict.fromkeys([*stats.MEDIA_TYPE_HOURS_ORDER, *current_minutes_by_type.keys()])
    )
    comparisons = {}

    for media_type in media_types:
        current_total = float(current_minutes_by_type.get(media_type, 0) or 0)
        if current_total <= 0:
            continue

        current_display = _format_statistics_total_for_media_type(
            media_type, current_total, duration_format
        )
        previous_total = float(comparison_minutes_by_type.get(media_type, 0) or 0)
        previous_display = _format_statistics_total_for_media_type(
            media_type, previous_total, duration_format
        )
        tooltip = {
            "current_label": current_period_label,
            "current_total": current_display,
            "comparison_label": comparison_period_label,
            "comparison_total": previous_display,
        }

        if previous_total <= 0:
            comparisons[media_type] = {
                "badge": "New",
                "badge_state": "new",
                "badge_short": "New",
                "badge_classes": "stats-metric-delta-badge stats-metric-delta-badge-positive",
                "details": f"No activity {comparison_suffix}".strip(),
                "details_classes": "text-gray-400",
                "tooltip": tooltip,
            }
            continue

        delta_percent = ((current_total - previous_total) / previous_total) * 100

        if abs(delta_percent) < NO_CHANGE_DELTA_PERCENT_THRESHOLD:
            comparisons[media_type] = {
                "badge": "No change",
                "badge_state": "neutral",
                "badge_short": "No change",
                "badge_classes": "stats-metric-delta-badge stats-metric-delta-badge-neutral",
                "details": f"vs {previous_display} {comparison_suffix}".strip(),
                "details_classes": "text-gray-400",
                "tooltip": tooltip,
            }
            continue

        is_positive = delta_percent > 0
        direction = "Up" if is_positive else "Down"
        tone_class = (
            "stats-metric-delta-badge stats-metric-delta-badge-positive"
            if is_positive
            else "stats-metric-delta-badge stats-metric-delta-badge-negative"
        )
        comparisons[media_type] = {
            "badge": f"{direction} {_format_statistics_percent_change(delta_percent)}%",
            "badge_state": direction.lower(),
            "badge_short": f"{_format_statistics_percent_change(delta_percent)}%",
            "badge_classes": tone_class,
            "details": f"vs {previous_display} {comparison_suffix}".strip(),
            "details_classes": "text-gray-400",
            "tooltip": tooltip,
        }

    return comparisons


@require_GET
def statistics(request):
    """Return the statistics page."""
    try:
        timeformat = "%Y-%m-%d"
        today = timezone.localdate()
        one_year_ago = today.replace(year=today.year - 1)

        start_date_param = request.GET.get("start-date")
        end_date_param = request.GET.get("end-date")

        if not start_date_param and not end_date_param:
            preferred_range = getattr(request.user, "statistics_default_range", None)
            if preferred_range not in statistics_cache.PREDEFINED_RANGES:
                preferred_range = "Last 12 Months"
            preferred_start, preferred_end = _get_predefined_range_date_strings(
                preferred_range,
                today,
                timeformat,
            )
            if preferred_start and preferred_end:
                start_date_str = preferred_start
                end_date_str = preferred_end
            else:
                start_date_str = one_year_ago.strftime(timeformat)
                end_date_str = today.strftime(timeformat)
        else:
            start_date_str = start_date_param or one_year_ago.strftime(timeformat)
            end_date_str = end_date_param or today.strftime(timeformat)

        if start_date_str == "all" and end_date_str == "all":
            start_date = None
            end_date = None
        else:
            start_date = parse_date(start_date_str)
            end_date = parse_date(end_date_str)

            if start_date and end_date:
                start_date = timezone.make_aware(
                    datetime.combine(start_date, datetime.min.time()),
                    timezone.get_current_timezone(),
                )
                end_date = timezone.make_aware(
                    datetime.combine(end_date, datetime.max.time()),
                    timezone.get_current_timezone(),
                )

        selected_range_name = _identify_predefined_range(start_date, end_date)

        if selected_range_name in statistics_cache.PREDEFINED_RANGES:
            request.user.update_preference(
                "statistics_default_range", selected_range_name
            )

        statistics_data = statistics_cache.get_statistics_data(
            request.user,
            start_date,
            end_date,
            range_name=selected_range_name,
        )

        show_year_charts = selected_range_name in (None, "All Time")
        has_finite_range = start_date is not None and end_date is not None
        compare_mode_param = request.GET.get("compare")
        compare_mode_source = (
            compare_mode_param
            if compare_mode_param is not None
            else getattr(
                request.user,
                "statistics_compare_mode",
                StatisticsCompareChoices.PREVIOUS_PERIOD,
            )
        )
        selected_compare_mode = _normalize_statistics_compare_mode(
            compare_mode_source,
            finite_range=has_finite_range,
        )
        comparison_start_date, comparison_end_date = (
            _resolve_statistics_comparison_range(
                start_date,
                end_date,
                selected_compare_mode,
            )
        )
        comparison_range_name = _identify_predefined_range(
            comparison_start_date,
            comparison_end_date,
        )
        comparison_minutes_by_type = {}
        if comparison_start_date and comparison_end_date:
            comparison_minutes_by_type = (
                statistics_cache.get_statistics_minutes_by_type(
                    request.user,
                    comparison_start_date,
                    comparison_end_date,
                    range_name=comparison_range_name,
                )
            )

        selected_range_dates_label = _get_statistics_card_range_label(
            request.user,
            selected_range_name,
            start_date,
            end_date,
        )
        comparison_range_dates_label = _format_statistics_range_label(
            request.user,
            comparison_start_date,
            comparison_end_date,
        )
        comparison_card_suffix = _get_statistics_card_comparison_suffix(
            request.user,
            selected_range_name,
            selected_compare_mode,
            comparison_start_date,
            comparison_end_date,
        )
        current_tooltip_label, comparison_tooltip_label = (
            _get_statistics_card_tooltip_labels(
                selected_range_name,
                selected_compare_mode,
            )
        )
        _duration_fmt = getattr(request.user, "duration_format", "hours_minutes")
        _current_minutes_map = _get_statistics_minutes_by_type(statistics_data)
        hours_per_media_type_comparison = _build_hours_per_media_type_comparison(
            _current_minutes_map,
            comparison_minutes_by_type,
            selected_compare_mode,
            comparison_card_suffix,
            current_tooltip_label,
            comparison_tooltip_label,
            duration_format=_duration_fmt,
        )
        _current_total_minutes = sum(_current_minutes_map.values())
        _comparison_total_minutes = sum(
            float(v or 0) for v in comparison_minutes_by_type.values()
        )
        total_activity_comparison = (
            _build_hours_per_media_type_comparison(
                {"all": _current_total_minutes},
                {"all": _comparison_total_minutes},
                selected_compare_mode,
                comparison_card_suffix,
                current_tooltip_label,
                comparison_tooltip_label,
                duration_format=_duration_fmt,
            ).get("all")
            or {}
        )

        # The talent/studio/taste section is rendered asynchronously by
        # statistics_talent_fragment so its featured-player scan and
        # comparison-window aggregation never block the page shell.

        top_rated_by_type = statistics_data.get("top_rated_by_type", {})
        top_rated_movie = top_rated_by_type.get("movie", [])
        top_rated_tv = top_rated_by_type.get("tv", [])
        top_rated_anime = top_rated_by_type.get("anime", [])
        top_rated_book = top_rated_by_type.get("book", [])
        top_rated_comic = top_rated_by_type.get("comic", [])
        top_rated_manga = top_rated_by_type.get("manga", [])

        start_date_str_for_url = start_date_str or ""
        end_date_str_for_url = end_date_str or ""

        _compare_label = STATISTICS_COMPARE_LABELS[selected_compare_mode]
        _range_to_comparison_label = {
            "Today": "yesterday",
            "Yesterday": "previous day",
            "This Week": "last week",
            "This Month": "last month",
            "This Year": "last year",
        }
        if selected_range_name and selected_range_name.lower().startswith("last"):
            activity_comparison_period_label = selected_range_name.lower()
        elif selected_range_name in _range_to_comparison_label:
            activity_comparison_period_label = _range_to_comparison_label[
                selected_range_name
            ]
        else:
            activity_comparison_period_label = _compare_label.lower()

        context = {
            "user": request.user,
            "tvdb_enabled": tvdb.enabled(),
            "start_date": start_date,
            "end_date": end_date,
            "start_date_str": start_date_str_for_url,
            "end_date_str": end_date_str_for_url,
            "selected_range_name": selected_range_name,
            "selected_range_dates_label": selected_range_dates_label,
            "selected_compare_mode": selected_compare_mode,
            "selected_compare_label": _compare_label,
            "activity_comparison_period_label": activity_comparison_period_label,
            "comparison_range_dates_label": comparison_range_dates_label,
            "hours_per_media_type_comparison": hours_per_media_type_comparison,
            "total_activity_comparison": total_activity_comparison,
            "weekday_hour_chart_data": statistics_data.get(
                "weekday_hour_chart_data", {}
            ),
            "combined_plays_charts": statistics_data.get("combined_plays_charts", {}),
            "media_count": statistics_data["media_count"],
            "activity_data": _extend_heatmap_with_future(
                statistics_data["activity_data"],
                start_date,
                end_date,
                week_start_sunday=request.user.week_start_day
                == WeekStartDayChoices.SUNDAY,
            ),
            "media_type_distribution": statistics_data["media_type_distribution"],
            "score_distribution": statistics_data["score_distribution"],
            "top_rated": statistics_data["top_rated"],
            "top_rated_movie": top_rated_movie,
            "top_rated_tv": top_rated_tv,
            "top_rated_anime": top_rated_anime,
            "top_rated_book": top_rated_book,
            "top_rated_comic": top_rated_comic,
            "top_rated_manga": top_rated_manga,
            "top_played": statistics_data["top_played"],
            "status_distribution": statistics_data["status_distribution"],
            "status_pie_chart_data": statistics_data["status_pie_chart_data"],
            "hours_per_media_type": statistics_data["hours_per_media_type"],
            "tv_consumption": statistics_data["tv_consumption"],
            "movie_consumption": statistics_data["movie_consumption"],
            "anime_consumption": statistics_data.get("anime_consumption", {}),
            "music_consumption": statistics_data["music_consumption"],
            "podcast_consumption": statistics_data["podcast_consumption"],
            "game_consumption": statistics_data["game_consumption"],
            "book_consumption": statistics_data.get("book_consumption", {}),
            "comic_consumption": statistics_data.get("comic_consumption", {}),
            "manga_consumption": statistics_data.get("manga_consumption", {}),
            "daily_hours_by_media_type": statistics_data["daily_hours_by_media_type"],
            "history_highlights": statistics_data.get("history_highlights", {}),
            "history_highlights_by_type": statistics_data.get(
                "history_highlights_by_type", {}
            ),
            "summary_stats_by_type": statistics_data.get("summary_stats_by_type", {}),
            "consumption_stats_by_type": statistics_data.get(
                "consumption_stats_by_type", {}
            ),
            "show_year_charts": show_year_charts,
            "user_django_date_format": DATE_FORMAT_DJANGO_MAP.get(
                request.user.date_format, ""
            ),
            "date_format_values": [
                fmt for fmt in DATE_FORMAT_DJANGO_MAP.values() if fmt
            ],
            "media_type_colors": {
                "tv": config.get_stats_color(MediaTypes.TV.value),
                "movie": config.get_stats_color(MediaTypes.MOVIE.value),
                "game": config.get_stats_color(MediaTypes.GAME.value),
                "music": config.get_stats_color(MediaTypes.MUSIC.value),
                "podcast": config.get_stats_color(MediaTypes.PODCAST.value),
                "book": config.get_stats_color(MediaTypes.BOOK.value),
                "comic": config.get_stats_color(MediaTypes.COMIC.value),
                "manga": config.get_stats_color(MediaTypes.MANGA.value),
            },
        }

        return render(request, "app/statistics.html", context)
    except OperationalError:
        logger.exception("Database error in statistics view")
        timeformat = "%Y-%m-%d"
        today = timezone.localdate()
        one_year_ago = today.replace(year=today.year - 1)
        start_date_str = request.GET.get("start-date") or one_year_ago.strftime(
            timeformat
        )
        end_date_str = request.GET.get("end-date") or today.strftime(timeformat)

        empty_statistics_data = {
            "media_count": {},
            "activity_data": [],
            "media_type_distribution": {},
            "minutes_per_media_type": {},
            "hours_per_media_type": {},
            "media_type_colors": {
                "tv": config.get_stats_color(MediaTypes.TV.value),
                "movie": config.get_stats_color(MediaTypes.MOVIE.value),
                "game": config.get_stats_color(MediaTypes.GAME.value),
                "music": config.get_stats_color(MediaTypes.MUSIC.value),
                "podcast": config.get_stats_color(MediaTypes.PODCAST.value),
                "book": config.get_stats_color(MediaTypes.BOOK.value),
                "comic": config.get_stats_color(MediaTypes.COMIC.value),
                "manga": config.get_stats_color(MediaTypes.MANGA.value),
            },
            "score_distribution": {},
            "top_rated": [],
            "top_played": [],
            "top_talent": {},
            "status_distribution": {},
            "status_pie_chart_data": {},
            "tv_consumption": {},
            "movie_consumption": {},
            "music_consumption": {},
            "podcast_consumption": {},
            "game_consumption": {},
            "book_consumption": {},
            "comic_consumption": {},
            "manga_consumption": {},
            "daily_hours_by_media_type": {},
            "history_highlights": {},
        }

        error_start_date = (
            _statistics_day_boundary(parse_date(start_date_str))
            if start_date_str != "all"
            else None
        )
        error_end_date = (
            _statistics_day_boundary(parse_date(end_date_str), end_of_day=True)
            if end_date_str != "all"
            else None
        )
        has_finite_range = error_start_date is not None and error_end_date is not None
        compare_mode_param = request.GET.get("compare")
        compare_mode_source = (
            compare_mode_param
            if compare_mode_param is not None
            else getattr(
                request.user,
                "statistics_compare_mode",
                StatisticsCompareChoices.PREVIOUS_PERIOD,
            )
        )
        selected_compare_mode = _normalize_statistics_compare_mode(
            compare_mode_source,
            finite_range=has_finite_range,
        )
        selected_range_name = _identify_predefined_range(
            error_start_date, error_end_date
        )

        context = {
            "user": request.user,
            "tvdb_enabled": tvdb.enabled(),
            "start_date": parse_date(start_date_str)
            if start_date_str != "all"
            else None,
            "end_date": parse_date(end_date_str) if end_date_str != "all" else None,
            "start_date_str": start_date_str,
            "end_date_str": end_date_str,
            "selected_range_name": selected_range_name,
            "selected_range_dates_label": _get_statistics_card_range_label(
                request.user,
                selected_range_name,
                error_start_date,
                error_end_date,
            ),
            "selected_compare_mode": selected_compare_mode,
            "selected_compare_label": STATISTICS_COMPARE_LABELS[selected_compare_mode],
            "comparison_range_dates_label": "",
            "hours_per_media_type_comparison": {},
            "media_count": empty_statistics_data["media_count"],
            "activity_data": empty_statistics_data["activity_data"],
            "media_type_distribution": empty_statistics_data["media_type_distribution"],
            "score_distribution": empty_statistics_data["score_distribution"],
            "top_rated": empty_statistics_data["top_rated"],
            "top_rated_movie": [],
            "top_rated_tv": [],
            "top_rated_anime": [],
            "top_rated_book": [],
            "top_rated_comic": [],
            "top_rated_manga": [],
            "top_played": empty_statistics_data["top_played"],
            "top_talent": empty_statistics_data["top_talent"],
            "featured_person": None,
            "person_media_strip": [],
            "person_media_strip_row": stats_cast_crew.build_media_strip_row([]),
            "role_leaders": {"columns": []},
            "studio_footprint": {"studios": [], "delta": None},
            "studio_sort_by": getattr(request.user, "studio_sort_by", "plays"),
            "era_spotlight": [],
            "top_genres_combined": [],
            "genre_sort_by": getattr(request.user, "genre_sort_by", "time"),
            "status_distribution": empty_statistics_data["status_distribution"],
            "status_pie_chart_data": empty_statistics_data["status_pie_chart_data"],
            "hours_per_media_type": empty_statistics_data["hours_per_media_type"],
            "tv_consumption": empty_statistics_data["tv_consumption"],
            "movie_consumption": empty_statistics_data["movie_consumption"],
            "anime_consumption": empty_statistics_data.get("anime_consumption", {}),
            "music_consumption": empty_statistics_data["music_consumption"],
            "podcast_consumption": empty_statistics_data["podcast_consumption"],
            "game_consumption": empty_statistics_data["game_consumption"],
            "book_consumption": empty_statistics_data["book_consumption"],
            "comic_consumption": empty_statistics_data["comic_consumption"],
            "manga_consumption": empty_statistics_data["manga_consumption"],
            "daily_hours_by_media_type": empty_statistics_data[
                "daily_hours_by_media_type"
            ],
            "history_highlights": empty_statistics_data["history_highlights"],
            "media_type_colors": empty_statistics_data["media_type_colors"],
            "show_year_charts": False,
            "database_error": True,
        }
        return render(request, "app/statistics.html", context)


TALENT_FRAGMENT_CACHE_TTL = 300


def _talent_fragment_cache_key(user, range_token, compare_mode):
    history_version = statistics_cache.get_history_version(user.id)
    top_talent_sort = getattr(user, "top_talent_sort_by", "plays")
    genre_sort = getattr(user, "genre_sort_by", "time")
    studio_sort = getattr(user, "studio_sort_by", "plays")
    return (
        f"stats_talent_frag_v1_{user.id}_{history_version}_{range_token}_"
        f"{top_talent_sort}_{studio_sort}_{genre_sort}_{compare_mode}"
    )


def _build_talent_fragment_context(
    user,
    range_name,
    start_date,
    end_date,
    start_date_str,
    end_date_str,
    comparison_start_date,
    comparison_end_date,
):
    statistics_data = statistics_cache.get_statistics_data(
        user,
        start_date,
        end_date,
        range_name=range_name,
    )
    top_talent = statistics_data.get("top_talent", {})
    active_top_talent_sort = getattr(user, "top_talent_sort_by", "plays")
    active_genre_sort = getattr(user, "genre_sort_by", "time")
    active_studio_sort = getattr(user, "studio_sort_by", "plays")

    featured_person, person_media_strip = (
        stats_cast_crew.get_featured_repeat_player_with_strip(
            user,
            start_date,
            end_date,
            top_talent,
            total_library_titles=statistics_data.get("media_count", {}).get("total", 0),
            sort_by=active_top_talent_sort,
        )
    )
    person_media_strip_row = stats_cast_crew.build_media_strip_row(
        person_media_strip,
        person_name=featured_person.get("name") if featured_person else None,
        total_titles=featured_person.get("unique_titles") if featured_person else None,
        sort_by=active_top_talent_sort,
    )
    role_leaders = stats_cast_crew.get_role_leaders(
        top_talent,
        sort_by=active_top_talent_sort,
    )
    studio_footprint = stats_cast_crew.get_studio_footprint(
        user,
        start_date,
        end_date,
        top_talent,
        comparison_start_date=comparison_start_date,
        comparison_end_date=comparison_end_date,
        sort_by=active_studio_sort,
    )
    era_spotlight = stats_cast_crew.get_era_spotlight(
        statistics_data.get("movie_consumption", {}),
        statistics_data.get("tv_consumption", {}),
        statistics_data.get("anime_consumption", {}),
        statistics_data.get("game_consumption", {}),
        statistics_data.get("music_consumption", {}),
        sort_by=active_genre_sort,
    )
    top_genres_combined = stats_cast_crew.get_top_genres_combined(
        statistics_data.get("movie_consumption", {}),
        statistics_data.get("tv_consumption", {}),
        statistics_data.get("anime_consumption", {}),
        statistics_data.get("game_consumption", {}),
        statistics_data.get("music_consumption", {}),
        sort_by=active_genre_sort,
    )

    return {
        "top_talent": top_talent,
        "featured_person": featured_person,
        "person_media_strip": person_media_strip,
        "person_media_strip_row": person_media_strip_row,
        "role_leaders": role_leaders,
        "studio_footprint": studio_footprint,
        "studio_sort_by": active_studio_sort,
        "era_spotlight": era_spotlight,
        "top_genres_combined": top_genres_combined,
        "genre_sort_by": active_genre_sort,
        "selected_range_name": range_name,
        "start_date_str": start_date_str or "",
        "end_date_str": end_date_str or "",
        "media_count": statistics_data.get("media_count", {}),
    }


@require_GET
def statistics_talent_fragment(request):
    """Render the talent/studio/taste statistics section as an HTMX fragment.

    Loaded asynchronously from the statistics shell so the featured-player
    scan and the comparison-window talent re-aggregation never block the
    page's first paint. The built context is cached; the key embeds the
    user's history version so any tracked-media change (or the refresh
    button) invalidates it automatically.
    """
    from django.core.cache import cache

    range_name = request.GET.get("range_name") or None
    start_date_str = request.GET.get("start-date") or None
    end_date_str = request.GET.get("end-date") or None
    compare_mode_param = request.GET.get("compare") or None

    start_date, end_date = _resolve_statistics_range_inputs(
        range_name,
        start_date_str,
        end_date_str,
    )

    has_finite_range = start_date is not None and end_date is not None
    compare_source = (
        compare_mode_param
        if compare_mode_param is not None
        else getattr(
            request.user,
            "statistics_compare_mode",
            StatisticsCompareChoices.PREVIOUS_PERIOD,
        )
    )
    selected_compare_mode = _normalize_statistics_compare_mode(
        compare_source,
        finite_range=has_finite_range,
    )
    comparison_start_date, comparison_end_date = _resolve_statistics_comparison_range(
        start_date,
        end_date,
        selected_compare_mode,
    )

    range_token = range_name or f"{start_date_str or 'all'}:{end_date_str or 'all'}"
    cache_key = _talent_fragment_cache_key(
        request.user,
        range_token,
        selected_compare_mode,
    )
    context = cache.get(cache_key)
    if context is None:
        context = _build_talent_fragment_context(
            request.user,
            range_name,
            start_date,
            end_date,
            start_date_str,
            end_date_str,
            comparison_start_date,
            comparison_end_date,
        )
        cache.set(cache_key, context, TALENT_FRAGMENT_CACHE_TTL)

    return render(
        request,
        "app/components/statistics/talent_section.html",
        context,
    )


@require_POST
def refresh_statistics(request):
    """Force refresh statistics cache for the current range."""
    range_name = request.POST.get("range_name")
    if not range_name:
        return JsonResponse({"error": "range_name is required"}, status=400)

    if range_name not in statistics_cache.PREDEFINED_RANGES:
        return JsonResponse({"error": "Invalid range_name"}, status=400)

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

    return JsonResponse({"success": True, "message": "Statistics refresh scheduled"})


@require_POST
def select_featured_person(request):
    """Swap the Featured Repeat Player card + media strip for a clicked person."""
    person_source = request.POST.get("person_source")
    person_id = request.POST.get("person_id")
    range_name = request.POST.get("range_name")
    start_date_str = request.POST.get("start_date")
    end_date_str = request.POST.get("end_date")
    total_library_titles = request.POST.get("total_library_titles")
    sort_by = request.POST.get("sort_by") or getattr(
        request.user, "top_talent_sort_by", "plays"
    )

    if not person_source or not person_id:
        return JsonResponse(
            {"error": "person_source and person_id are required"},
            status=400,
        )

    start_date, end_date = _resolve_statistics_range_inputs(
        range_name,
        start_date_str,
        end_date_str,
    )

    try:
        total_library_titles = int(total_library_titles)
    except (TypeError, ValueError):
        total_library_titles = None

    if total_library_titles is None or total_library_titles < 0:
        media_count = statistics_cache.get_statistics_media_count(
            request.user,
            start_date,
            end_date,
            range_name=range_name,
        )
        total_library_titles = media_count.get("total", 0)

    featured_person, person_media_strip = (
        stats_cast_crew.get_featured_person_with_strip(
            request.user,
            person_source,
            person_id,
            start_date,
            end_date,
            total_library_titles=total_library_titles,
            sort_by=sort_by,
        )
    )
    if not featured_person:
        return JsonResponse({"error": "Person not found"}, status=404)

    featured_html = render_to_string(
        "app/components/featured_repeat_player_content.html",
        {
            "featured_person": featured_person,
            "csrf_token": request.META.get("CSRF_COOKIE"),
        },
        request=request,
    )
    footer_html = render_to_string(
        "app/components/featured_repeat_player_footer.html",
        {
            "featured_person": featured_person,
        },
        request=request,
    )
    strip_html = render_to_string(
        "app/components/person_media_strip_row.html",
        {
            "person_media_strip_row": stats_cast_crew.build_media_strip_row(
                person_media_strip,
                person_name=featured_person.get("name"),
                total_titles=featured_person.get("unique_titles"),
                sort_by=sort_by,
            ),
        },
        request=request,
    )

    return JsonResponse(
        {
            "success": True,
            "featured_html": featured_html,
            "footer_html": footer_html,
            "strip_html": strip_html,
            "pct_of_library": featured_person.get("pct_of_library", 0),
        },
    )


@require_POST
def update_top_talent_sort(request):
    """Autosave top talent sort preference and refresh role leaders + featured person."""
    sort_by = request.POST.get("sort_by")
    range_name = request.POST.get("range_name")
    start_date_str = request.POST.get("start_date")
    end_date_str = request.POST.get("end_date")
    total_library_titles = request.POST.get("total_library_titles")
    media_type = request.POST.get("media_type")
    if media_type not in {
        MediaTypes.MOVIE.value,
        MediaTypes.TV.value,
        MediaTypes.ANIME.value,
        MediaTypes.GAME.value,
    }:
        media_type = None

    valid_sort_values = list(TopTalentSortChoices.values)
    if sort_by not in valid_sort_values:
        return JsonResponse(
            {
                "error": "Invalid sort_by",
                "valid_values": valid_sort_values,
            },
            status=400,
        )

    previous_sort = request.user.top_talent_sort_by
    updated_sort = request.user.update_preference("top_talent_sort_by", sort_by)
    changed = previous_sort != updated_sort
    requires_reload = False

    if range_name in statistics_cache.PREDEFINED_RANGES:
        try:
            if statistics_cache.range_needs_top_talent_upgrade(
                request.user.id, range_name
            ):
                statistics_cache.invalidate_statistics_cache(
                    request.user.id, range_name
                )
                statistics_cache.refresh_statistics_cache(request.user.id, range_name)
                requires_reload = True
        except Exception as exc:  # pragma: no cover - best effort compatibility upgrade
            logger.debug(
                "top_talent_sort_upgrade_failed user_id=%s range=%s error=%s",
                request.user.id,
                range_name,
                exc,
            )

    if requires_reload:
        return JsonResponse(
            {
                "success": True,
                "sort_by": updated_sort,
                "changed": changed,
                "requires_reload": True,
            },
        )

    start_date, end_date = _resolve_statistics_range_inputs(
        range_name,
        start_date_str,
        end_date_str,
    )

    try:
        total_library_titles = int(total_library_titles)
    except (TypeError, ValueError):
        total_library_titles = None

    if total_library_titles is None or total_library_titles < 0:
        media_count = statistics_cache.get_statistics_media_count(
            request.user,
            start_date,
            end_date,
            range_name=range_name,
        )
        total_library_titles = media_count.get("total", 0)

    if media_type:
        # Filtered variants aren't cached — only the unfiltered per-range payload is.
        top_talent = _aggregate_top_talent(
            request.user, start_date, end_date, media_type=media_type
        )
    else:
        top_talent = statistics_cache.get_top_talent_data(
            request.user,
            start_date,
            end_date,
            range_name=range_name,
        )
    role_leaders = stats_cast_crew.get_role_leaders(top_talent, sort_by=sort_by)
    featured_person, person_media_strip = (
        stats_cast_crew.get_featured_repeat_player_with_strip(
            request.user,
            start_date,
            end_date,
            top_talent,
            total_library_titles=total_library_titles,
            sort_by=sort_by,
        )
    )
    studio_footprint = stats_cast_crew.get_studio_footprint(
        request.user,
        start_date,
        end_date,
        top_talent,
        media_type=media_type,
    )

    role_leaders_html = render_to_string(
        "app/components/role_leaders_grid.html",
        {
            "role_leaders": role_leaders,
        },
        request=request,
    )
    studio_footprint_html = render_to_string(
        "app/components/studio_footprint_grid.html",
        {
            "studio_footprint": studio_footprint,
        },
        request=request,
    )

    featured_html = ""
    footer_html = ""
    strip_html = ""
    selected_person_key = ""
    pct_of_library = 0

    if featured_person:
        selected_person_key = f"{featured_person.get('source', '')}:{featured_person.get('person_id', '')}"
        pct_of_library = featured_person.get("pct_of_library", 0)
        featured_html = render_to_string(
            "app/components/featured_repeat_player_content.html",
            {
                "featured_person": featured_person,
            },
            request=request,
        )
        footer_html = render_to_string(
            "app/components/featured_repeat_player_footer.html",
            {
                "featured_person": featured_person,
            },
            request=request,
        )
        strip_html = render_to_string(
            "app/components/person_media_strip_row.html",
            {
                "person_media_strip_row": stats_cast_crew.build_media_strip_row(
                    person_media_strip,
                    person_name=featured_person.get("name"),
                    total_titles=featured_person.get("unique_titles"),
                    sort_by=sort_by,
                ),
            },
            request=request,
        )

    return JsonResponse(
        {
            "success": True,
            "sort_by": updated_sort,
            "changed": changed,
            "requires_reload": False,
            "role_leaders_html": role_leaders_html,
            "studio_footprint_html": studio_footprint_html,
            "featured_html": featured_html,
            "footer_html": footer_html,
            "strip_html": strip_html,
            "selected_person_key": selected_person_key,
            "pct_of_library": pct_of_library,
        },
    )


@require_POST
def update_genre_sort(request):
    """Autosave the Taste Signals sort preference and refresh Top Genres + Era Spotlight."""
    sort_by = request.POST.get("sort_by")
    range_name = request.POST.get("range_name")
    start_date_str = request.POST.get("start_date")
    end_date_str = request.POST.get("end_date")
    media_type = request.POST.get("media_type")
    if media_type not in {
        MediaTypes.MOVIE.value,
        MediaTypes.TV.value,
        MediaTypes.ANIME.value,
        MediaTypes.GAME.value,
    }:
        media_type = None

    valid_sort_values = list(GenreSortChoices.values)
    if sort_by not in valid_sort_values:
        return JsonResponse(
            {
                "error": "Invalid sort_by",
                "valid_values": valid_sort_values,
            },
            status=400,
        )

    request.user.update_preference("genre_sort_by", sort_by)

    start_date, end_date = _resolve_statistics_range_inputs(
        range_name,
        start_date_str,
        end_date_str,
    )
    statistics_data = statistics_cache.get_statistics_data(
        request.user,
        start_date,
        end_date,
        range_name=range_name,
    )
    empty_consumption = {}
    consumption_by_type = {
        MediaTypes.MOVIE.value: statistics_data.get("movie_consumption", {}),
        MediaTypes.TV.value: statistics_data.get("tv_consumption", {}),
        MediaTypes.ANIME.value: statistics_data.get("anime_consumption", {}),
        MediaTypes.GAME.value: statistics_data.get("game_consumption", {}),
        MediaTypes.MUSIC.value: statistics_data.get("music_consumption", {}),
    }
    if media_type:
        # Filtered view: only the selected media type contributes rows.
        for key in consumption_by_type:
            if key != media_type:
                consumption_by_type[key] = empty_consumption

    top_genres_combined = stats_cast_crew.get_top_genres_combined(
        consumption_by_type[MediaTypes.MOVIE.value],
        consumption_by_type[MediaTypes.TV.value],
        consumption_by_type[MediaTypes.ANIME.value],
        consumption_by_type[MediaTypes.GAME.value],
        consumption_by_type[MediaTypes.MUSIC.value],
        sort_by=sort_by,
    )
    era_spotlight = stats_cast_crew.get_era_spotlight(
        consumption_by_type[MediaTypes.MOVIE.value],
        consumption_by_type[MediaTypes.TV.value],
        consumption_by_type[MediaTypes.ANIME.value],
        consumption_by_type[MediaTypes.GAME.value],
        consumption_by_type[MediaTypes.MUSIC.value],
        sort_by=sort_by,
    )
    genres_html = render_to_string(
        "app/components/taste_signals_genres.html",
        {
            "top_genres_combined": top_genres_combined,
            "genre_sort_by": sort_by,
        },
        request=request,
    )
    decades_html = render_to_string(
        "app/components/taste_signals_decades.html",
        {
            "era_spotlight": era_spotlight,
            "genre_sort_by": sort_by,
        },
        request=request,
    )

    return JsonResponse(
        {
            "success": True,
            "sort_by": sort_by,
            "genres_html": genres_html,
            "decades_html": decades_html,
        },
    )


@require_POST
def update_studio_sort(request):
    """Autosave the Studio Footprint sort preference and refresh its list."""
    sort_by = request.POST.get("sort_by")
    range_name = request.POST.get("range_name")
    start_date_str = request.POST.get("start_date")
    end_date_str = request.POST.get("end_date")
    media_type = request.POST.get("media_type")
    if media_type not in {
        MediaTypes.MOVIE.value,
        MediaTypes.TV.value,
        MediaTypes.ANIME.value,
        MediaTypes.GAME.value,
    }:
        media_type = None

    valid_sort_values = list(GenreSortChoices.values)
    if sort_by not in valid_sort_values:
        return JsonResponse(
            {
                "error": "Invalid sort_by",
                "valid_values": valid_sort_values,
            },
            status=400,
        )

    request.user.update_preference("studio_sort_by", sort_by)

    start_date, end_date = _resolve_statistics_range_inputs(
        range_name,
        start_date_str,
        end_date_str,
    )

    if media_type:
        # Filtered variants aren't cached — only the unfiltered per-range payload is.
        top_talent = _aggregate_top_talent(
            request.user, start_date, end_date, media_type=media_type
        )
    else:
        top_talent = statistics_cache.get_top_talent_data(
            request.user,
            start_date,
            end_date,
            range_name=range_name,
        )
    studio_footprint = stats_cast_crew.get_studio_footprint(
        request.user,
        start_date,
        end_date,
        top_talent,
        media_type=media_type,
        sort_by=sort_by,
    )
    studio_html = render_to_string(
        "app/components/studio_footprint_grid.html",
        {
            "studio_footprint": studio_footprint,
            "studio_sort_by": sort_by,
        },
        request=request,
    )

    return JsonResponse(
        {
            "success": True,
            "sort_by": sort_by,
            "studio_html": studio_html,
        },
    )


@require_POST
def update_statistics_preferences(request):
    """Save statistics-specific display preferences from the stats page modal."""
    fields_to_update = []
    invalidate_cache = False

    activity_history_view = request.POST.get("activity_history_view")
    if (
        activity_history_view
        and activity_history_view in ActivityHistoryViewChoices.values
    ) and request.user.activity_history_view != activity_history_view:
        request.user.activity_history_view = activity_history_view
        fields_to_update.append("activity_history_view")

    duration_format = request.POST.get("duration_format")
    if (
        duration_format and duration_format in DurationFormatChoices.values
    ) and request.user.duration_format != duration_format:
        request.user.duration_format = duration_format
        fields_to_update.append("duration_format")
        invalidate_cache = True

    week_start_day = request.POST.get("week_start_day")
    if (
        week_start_day and week_start_day in WeekStartDayChoices.values
    ) and request.user.week_start_day != week_start_day:
        request.user.week_start_day = week_start_day
        fields_to_update.append("week_start_day")
        invalidate_cache = True

    rating_scale = request.POST.get("rating_scale")
    if (
        rating_scale and rating_scale in RatingScaleChoices.values
    ) and request.user.rating_scale != rating_scale:
        request.user.rating_scale = rating_scale
        fields_to_update.append("rating_scale")
        invalidate_cache = True

    stats_split_tv_anime = request.POST.get("stats_split_tv_anime")
    if stats_split_tv_anime in ("true", "false"):
        new_val = stats_split_tv_anime == "true"
        if request.user.stats_split_tv_anime != new_val:
            request.user.stats_split_tv_anime = new_val
            fields_to_update.append("stats_split_tv_anime")
            invalidate_cache = True

    if fields_to_update:
        request.user.save(update_fields=fields_to_update)
        if invalidate_cache:
            statistics_cache.invalidate_all_statistics_days(
                request.user.id,
                reason="statistics_preferences_changed",
            )
            statistics_cache.invalidate_statistics_cache(request.user.id)
            statistics_cache.schedule_all_ranges_refresh(
                request.user.id,
                debounce_seconds=0,
            )

    return JsonResponse({"status": "ok"})


@require_POST
def update_statistics_compare_mode(request):
    """Autosave statistics comparison mode preference from page controls."""
    compare_mode = request.POST.get("compare_mode")

    valid_compare_values = list(StatisticsCompareChoices.values)
    if compare_mode not in valid_compare_values:
        return JsonResponse(
            {
                "error": "Invalid compare_mode",
                "valid_values": valid_compare_values,
            },
            status=400,
        )

    previous_mode = request.user.statistics_compare_mode
    updated_mode = request.user.update_preference(
        "statistics_compare_mode", compare_mode
    )

    return JsonResponse(
        {
            "success": True,
            "changed": previous_mode != updated_mode,
            "compare_mode": updated_mode,
        },
    )


def _identify_predefined_range(start_date, end_date):
    if start_date is None and end_date is None:
        return "All Time"

    if not start_date or not end_date:
        return None

    local_start = timezone.localdate(start_date)
    local_end = timezone.localdate(end_date)
    today = timezone.localdate()

    if local_start == today and local_end == today:
        return "Today"

    yesterday = today - timedelta(days=1)
    if local_start == yesterday and local_end == yesterday:
        return "Yesterday"

    month_start = today.replace(day=1)
    if local_start == month_start and local_end == today:
        return "This Month"
    if local_start == month_start and local_end == today - timedelta(days=1):
        return "This Month"

    monday = today - timedelta(days=today.weekday())
    if local_start == monday and local_end == today:
        return "This Week"
    if local_start == monday and local_end == today - timedelta(days=1):
        return "This Week"

    if local_start == today - timedelta(days=6) and local_end == today:
        return "Last 7 Days"

    if local_start == today - timedelta(days=29) and local_end == today:
        return "Last 30 Days"

    if local_start == today - timedelta(days=89) and local_end == today:
        return "Last 90 Days"

    year_start = today.replace(month=1, day=1)
    if local_start == year_start and local_end == today:
        return "This Year"
    if local_start == year_start and local_end == today - timedelta(days=1):
        return "This Year"

    six_months_start = _adjust_month_delta(today, months=6)
    if _dates_close(local_start, six_months_start) and local_end == today:
        return "Last 6 Months"

    twelve_months_start = _adjust_month_delta(today, months=12)
    if _dates_close(local_start, twelve_months_start) and local_end == today:
        return "Last 12 Months"

    return None


def _get_predefined_range_date_strings(range_name, today, timeformat):
    if range_name == "All Time":
        return "all", "all"

    start_date = None
    end_date = today

    if range_name == "Today":
        start_date = today
    elif range_name == "Yesterday":
        start_date = today - timedelta(days=1)
        end_date = start_date
    elif range_name == "This Week":
        start_date = today - timedelta(days=today.weekday())
    elif range_name == "Last 7 Days":
        start_date = today - timedelta(days=6)
    elif range_name == "This Month":
        start_date = today.replace(day=1)
    elif range_name == "Last 30 Days":
        start_date = today - timedelta(days=29)
    elif range_name == "Last 90 Days":
        start_date = today - timedelta(days=89)
    elif range_name == "This Year":
        start_date = today.replace(month=1, day=1)
    elif range_name == "Last 6 Months":
        start_date = _adjust_month_delta(today, months=6)
    elif range_name == "Last 12 Months":
        start_date = _adjust_month_delta(today, months=12)

    if start_date is None:
        return None, None

    return start_date.strftime(timeformat), end_date.strftime(timeformat)


def _adjust_month_delta(reference_date, months):
    candidate = reference_date - relativedelta(months=months)
    if candidate.day != reference_date.day:
        candidate = (candidate.replace(day=1) + relativedelta(months=1)) - timedelta(
            days=1
        )
    return candidate


def _dates_close(date_one, date_two, tolerance_days=1):
    return abs((date_one - date_two).days) <= tolerance_days
