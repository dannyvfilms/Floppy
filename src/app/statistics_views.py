import calendar as _calendar
import logging
import re
from datetime import date, timedelta
from urllib.parse import quote

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db.utils import OperationalError
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.timesince import timesince
from django.utils.timezone import datetime
from django.utils.translation import gettext, gettext_noop, ngettext
from django.views.decorators.http import require_GET, require_POST

from app import config, statistics_cache, stats_cast_crew
from app import statistics as stats
from app.log_safety import exception_summary
from app.models import MediaTypes, Status
from app.providers import tvdb
from app.statistics_talent import (
    TALENT_MEDIA_TYPES,
    _aggregate_top_talent,
    _normalize_talent_media_types,
)
from app.stats_utils import MEDIA_TYPE_HOURS_ORDER
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
    "This Year": gettext_noop("last year"),
    "This Month": gettext_noop("last year"),
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


def _normalize_statistics_media_types(raw, allowed=None):
    """Return the stats media types in ``raw`` in the chart order."""
    tokens = {token.strip() for token in str(raw or "").split(",") if token.strip()}
    if allowed is not None:
        tokens.intersection_update(allowed)
    return [media_type for media_type in MEDIA_TYPE_HOURS_ORDER if media_type in tokens]


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
                "details_classes": "text-[var(--color-text-muted)]",
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


STATISTICS_TYPE_LABELS = {
    "all": "titles",
    MediaTypes.MOVIE.value: "films",
    MediaTypes.TV.value: "shows",
    MediaTypes.GAME.value: "games",
    MediaTypes.BOOK.value: "books",
    MediaTypes.ANIME.value: "titles",
    MediaTypes.MUSIC.value: "albums",
    MediaTypes.PODCAST.value: "podcasts",
    MediaTypes.COMIC.value: "comics",
    MediaTypes.MANGA.value: "manga",
    MediaTypes.BOARDGAME.value: "board games",
    MediaTypes.VIDEO.value: "videos",
}

STATISTICS_TYPE_FLAVORS = {
    "all": "stories, ideas, and worlds",
    MediaTypes.MOVIE.value: "film and storytelling",
    MediaTypes.TV.value: "episodes and seasons",
    MediaTypes.GAME.value: "play and adventure",
    MediaTypes.BOOK.value: "reading and discovery",
    MediaTypes.ANIME.value: "anime and storytelling",
    MediaTypes.MUSIC.value: "music and discovery",
    MediaTypes.PODCAST.value: "listening and learning",
    MediaTypes.COMIC.value: "comics and art",
    MediaTypes.MANGA.value: "manga and art",
    MediaTypes.BOARDGAME.value: "tabletop and strategy",
    MediaTypes.VIDEO.value: "video and motion",
}


def _statistics_level(count):
    """Match stats_activity.get_level for the shared heatmap."""
    for index, threshold in enumerate((0, 3, 6, 9)):
        if count <= threshold:
            return index
    return 4


def _statistics_comparison(badge_data, period_label):
    if not badge_data:
        return {}
    state = badge_data.get("badge_state") or "none"
    return {
        "label": badge_data.get("badge_short") or badge_data.get("badge") or "",
        "state": state,
        "periodLabel": period_label or "",
        "details": badge_data.get("details") or "",
    }


def _statistics_summary_model(media_type, row, comparison, period_label):
    total_minutes = float(row.get("total_minutes") or 0)
    start = row.get("longest_streak_start")
    end = row.get("longest_streak_end")
    streak_dates = ""
    if start and end:
        streak_dates = start if start == end else f"{start} - {end}"
    return {
        "total": row.get("total", 0),
        "completed": row.get("completed", 0),
        "totalMinutes": total_minutes,
        "totalHours": round(total_minutes / 60),
        "totalDays": int(total_minutes / 60 / 24),
        "scoreCount": row.get("score_count", 0),
        "scoreSum": row.get("score_sum", 0),
        "weekdayMinutes": row.get("weekday_minutes") or [],
        "activeRuns": row.get("active_runs") or [],
        "streakEndDay": row.get("streak_end_day"),
        "averageScore": (
            round(float(row["average_score"]), 1)
            if row.get("average_score") is not None
            else None
        ),
        "hasScore": bool(row.get("has_score")),
        "mostActiveDay": row.get("most_active_day") or "",
        "mostActiveDayLabel": row.get("most_active_day") or "",
        "mostActiveDayPercentage": round(
            float(row.get("most_active_day_percentage") or 0)
        ),
        "currentStreak": row.get("current_streak", 0),
        "longestStreak": row.get("longest_streak", 0),
        "longestStreakStart": start or "",
        "longestStreakDates": streak_dates,
        "typeLabel": STATISTICS_TYPE_LABELS.get(media_type, "titles"),
        "typeFlavor": STATISTICS_TYPE_FLAVORS.get(media_type, "stories, ideas, and worlds"),
        "comparison": _statistics_comparison(comparison, period_label),
    }


def _statistics_highlight_card(entry, key, label, prefix, user):
    if not entry:
        return None
    played_at = entry.get("played_at")
    date_label = prefix
    if played_at is not None:
        date_label = f"{prefix} {app_tags.date_format(played_at, user)}".strip()
    media_type = entry.get("media_type") or ""
    return {
        "key": key,
        "label": label,
        "title": entry.get("title") or "",
        "meta": app_tags.media_type_readable(media_type) if media_type else "",
        "date": date_label,
        "image": entry.get("image") or "",
        "href": app_tags.media_url(entry.get("item")) if entry.get("item") else "",
    }


def _statistics_highlights_model(history_highlights, user):
    if not isinstance(history_highlights, dict):
        return []
    cards = [
        _statistics_highlight_card(
            history_highlights.get("first_play"), "first", "First Play", "Played", user
        ),
        _statistics_highlight_card(
            history_highlights.get("last_play"), "last", "Last Play", "Played", user
        ),
    ]
    today_card = history_highlights.get("today_card") or {}
    today_entry = today_card.get("entry")
    if today_entry:
        card = _statistics_highlight_card(
            today_entry,
            "today",
            today_card.get("label") or "Today",
            today_card.get("date_prefix") or "Played in",
            user,
        )
        if card:
            card["date"] = f"{today_card.get('date_prefix') or 'Played in'} {today_card.get('year') or ''}".strip()
            month = history_highlights.get("today_month")
            day = history_highlights.get("today_day")
            params = []
            if today_card.get("use_release_url"):
                params.append("history_mode=release")
            if month and day:
                params.extend([f"month={month}", f"day={day}"])
            card["href"] = reverse("history") + (f"?{'&'.join(params)}" if params else "")
        cards.append(card)
    return [card for card in cards if card]


def _statistics_series_model(chart, default_color):
    if not isinstance(chart, dict):
        return {"labels": [], "data": [], "color": default_color}
    datasets = chart.get("datasets") or []
    dataset = datasets[0] if datasets else {}
    return {
        "labels": chart.get("labels") or [],
        "data": dataset.get("data") or [],
        "color": dataset.get("background_color") or default_color,
    }


def _statistics_heatmap_model(activity_data, media_type):
    weeks = []
    for week in activity_data.get("calendar_weeks", []):
        days = []
        for day in week:
            future = bool(day.get("future"))
            if future:
                count = 0
            elif media_type is None:
                count = int(day.get("count") or 0)
            else:
                count = int((day.get("by_type") or {}).get(media_type) or 0)
            days.append({
                "key": day.get("date"),
                "count": count,
                "level": 0 if future else _statistics_level(count),
                "future": future,
            })
        weeks.append({"days": days})
    months = [
        {"label": label, "span": span}
        for label, span in activity_data.get("months", [])
        if label
    ]
    return {
        "weeks": weeks,
        "monthLabels": months,
        "weekdayLabels": activity_data.get("weekday_labels") or [
            "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"
        ],
    }


def _statistics_status_composition(status_distribution, media_type=None):
    labels = []
    data = []
    colors = []
    if not isinstance(status_distribution, dict):
        return {"labels": labels, "data": data, "colors": colors}
    type_labels = status_distribution.get("labels") or []
    try:
        index = type_labels.index(app_tags.media_type_readable(media_type)) if media_type else None
    except ValueError:
        index = None
    for dataset in status_distribution.get("datasets") or []:
        values = dataset.get("data") or []
        value = values[index] if index is not None and index < len(values) else sum(values)
        if value > 0:
            labels.append(dataset.get("label") or "")
            data.append(value)
            colors.append(dataset.get("background_color") or "")
    return {"labels": labels, "data": data, "colors": colors}


def _statistics_rating_distribution(score_distribution, media_type=None):
    labels = list(score_distribution.get("labels") or [])
    data = [0 for _ in labels]
    if isinstance(score_distribution, dict):
        for dataset in score_distribution.get("datasets") or []:
            if media_type and dataset.get("label") != app_tags.media_type_readable(media_type):
                continue
            for index, value in enumerate(dataset.get("data") or []):
                if index < len(data):
                    data[index] += float(value or 0)
    return {
        "labels": labels,
        "data": [round(value) for value in data],
        "scaleMax": score_distribution.get("scale_max") or 10,
    }


def _statistics_status_breakdown(
    status_distribution, media_count, media_type_colors, media_types
):
    type_labels = status_distribution.get("labels") or []
    rows = []
    for media_type in media_types:
        label = app_tags.media_type_readable(media_type)
        if label not in type_labels:
            continue
        index = type_labels.index(label)
        statuses = {}
        for dataset in status_distribution.get("datasets") or []:
            values = dataset.get("data") or []
            statuses[dataset.get("label") or ""] = (
                values[index] if index < len(values) else 0
            )
        rows.append({
            "label": label,
            "color": media_type_colors.get(media_type) or "",
            "total": media_count.get(media_type, 0),
            "statuses": statuses,
        })
    columns = [
        {
            "label": dataset.get("label") or "",
            "color": dataset.get("background_color") or "",
            "completed": dataset.get("label") == Status.COMPLETED.value,
        }
        for dataset in status_distribution.get("datasets") or []
    ]
    return {"rows": rows, "columns": columns}


def _statistics_completion(summary_stats_by_type, media_type_colors, media_types):
    rows = []
    for media_type in media_types:
        row = summary_stats_by_type.get(media_type) or {}
        rows.append({
            "label": app_tags.media_type_readable(media_type),
            "color": media_type_colors.get(media_type) or "",
            "completed": row.get("completed", 0),
            "total": row.get("total", 0),
        })
    return {"rows": rows}


def _build_statistics_react_props(user, context, statistics_data):
    """Build the shared Statistics models from the server's own values."""
    summary_stats_by_type = context.get("summary_stats_by_type") or {}
    media_count = context.get("media_count") or {}
    status_distribution = context.get("status_distribution") or {}
    score_distribution = context.get("score_distribution") or {}
    media_type_distribution = context.get("media_type_distribution") or {}
    activity_data = context.get("activity_data") or {}
    weekday_hour_chart_data = context.get("weekday_hour_chart_data") or {}
    combined_plays_charts = context.get("combined_plays_charts") or {}
    media_type_colors = context.get("media_type_colors") or {}
    minutes_per_media_type = statistics_data.get("minutes_per_media_type") or {}
    history_highlights = context.get("history_highlights") or {}
    history_highlights_by_type = context.get("history_highlights_by_type") or {}
    comparisons = context.get("hours_per_media_type_comparison") or {}
    total_comparison = context.get("total_activity_comparison") or {}
    comparison_period = context.get("activity_comparison_period_label") or ""

    types = [
        media_type
        for media_type in summary_stats_by_type
        if media_type != "all"
    ]
    # Use the chart-ready type list from the distribution when labels are readable.
    readable_to_type = {
        app_tags.media_type_readable(media_type): media_type for media_type in media_type_colors
    }
    chart_types = [
        readable_to_type[label]
        for label in media_type_distribution.get("labels", [])
        if label in readable_to_type
    ] or types

    def summary_for(media_type, comparison):
        row = summary_stats_by_type.get(media_type) or {}
        return _statistics_summary_model(
            media_type, row, comparison, comparison_period
        )

    summary_all = summary_for("all", total_comparison)
    summary_types = {
        media_type: summary_for(media_type, comparisons.get(media_type))
        for media_type in types
    }

    def hours(dataset_key, media_type=None):
        source = (combined_plays_charts.get(dataset_key) or {})
        key = media_type or "all"
        return _statistics_series_model(
            source.get(key),
            media_type_colors.get(media_type) or "#6366f1",
        )

    def media_type_hours(media_type=None):
        if media_type:
            minutes = float(minutes_per_media_type.get(media_type) or 0)
            if minutes <= 0:
                return {"labels": [], "data": [], "colors": []}
            return {
                "labels": [app_tags.media_type_readable(media_type)],
                "data": [round(minutes / 60, 2)],
                "colors": [media_type_colors.get(media_type) or "#6366f1"],
            }
        return {
            "labels": media_type_distribution.get("labels") or [],
            "data": (media_type_distribution.get("datasets") or [{}])[0].get("data") or [],
            "colors": (media_type_distribution.get("datasets") or [{}])[0].get("backgroundColor") or [],
        }

    def rhythm(media_type=None):
        key = media_type or "all"
        matrix = weekday_hour_chart_data.get(key)
        if not matrix:
            matrix = [[0 for _ in range(24)] for _ in range(7)]
        return {
            "matrix": matrix,
            "weekdayLabels": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        }

    def chart_model(media_type=None):
        return {
            "rhythm": rhythm(media_type),
            "mediaTypeHours": media_type_hours(media_type),
            "heatmap": _statistics_heatmap_model(activity_data, media_type),
            "hoursByMonth": hours("by_month", media_type),
            "hoursByWeekday": hours("by_weekday", media_type),
            "hoursByTimeOfDay": hours("by_time_of_day", media_type),
            "statusComposition": _statistics_status_composition(
                status_distribution, media_type
            ),
            "ratingDistribution": _statistics_rating_distribution(
                score_distribution, media_type
            ),
            "statusBreakdown": _statistics_status_breakdown(
                status_distribution,
                media_count,
                media_type_colors,
                [media_type] if media_type else chart_types,
            ),
            "completion": _statistics_completion(
                summary_stats_by_type,
                media_type_colors,
                [media_type] if media_type else chart_types,
            ),
        }

    def group(keys, media_type):
        model = chart_model(media_type)
        return {key: model[key] for key in keys}

    groups = {
        "overview": ("rhythm", "mediaTypeHours"),
        "heatmap": ("heatmap",),
        "hours": ("hoursByMonth", "hoursByWeekday", "hoursByTimeOfDay"),
        "status": ("statusComposition", "ratingDistribution"),
        "breakdown": ("statusBreakdown", "completion"),
    }
    charts = {
        name: {
            "group": name,
            "all": group(keys, None),
            "types": {media_type: group(keys, media_type) for media_type in types},
        }
        for name, keys in groups.items()
    }

    built_at = context.get("statistics_built_at")
    return {
        "summary": {
            "all": summary_all,
            "types": summary_types,
            "highlights": {
                "all": _statistics_highlights_model(history_highlights, user),
                "types": {
                    media_type: _statistics_highlights_model(highlights, user)
                    for media_type, highlights in history_highlights_by_type.items()
                },
            },
            "updatedLabel": f"{timesince(built_at)} ago" if built_at else "",
            "scaleMax": user.rating_scale_max,
        },
        "charts": charts,
        "sections": {
            "comparison": _statistics_comparison_section(
                user, context, statistics_data,
            ),
            "overviews": _statistics_media_overview_models(
                context,
                statistics_data,
                user,
                context.get("selected_range_dates_label") or "",
            ),
        },
    }


STATISTICS_OVERVIEW_TYPE_LABELS = {
    "tv": gettext_noop("TV Shows"),
    "movie": gettext_noop("Movies"),
    "anime": gettext_noop("Anime"),
    "game": gettext_noop("Video Games"),
    "music": gettext_noop("Music"),
    "podcast": gettext_noop("Podcast"),
    "book": gettext_noop("Books"),
    "comic": gettext_noop("Comics"),
    "manga": gettext_noop("Manga"),
    "video": gettext_noop("Video"),
}


def _statistics_media_color(context, media_type):
    colors = context.get("media_type_colors") or {}
    return colors.get(media_type) or "#6366f1"


def _statistics_image(value):
    if not value or value == getattr(settings, "IMG_NONE", None):
        return ""
    return app_tags.image_url(value)


def _statistics_media_href(item):
    return app_tags.media_url(item) if item else ""


def _statistics_media_score(media, user):
    if not media:
        return ""
    score = getattr(media, "aggregated_score", None)
    if score is None:
        score = getattr(media, "score", None)
    display = app_tags.score_display(score, user)
    return "" if display is None else str(display)


def _statistics_plural(count, one, many):
    return ngettext(one, many, int(count or 0)) % {"count": int(count or 0)}


def _statistics_overview_chart(key, title, chart, color):
    chart = chart if isinstance(chart, dict) else {}
    datasets = chart.get("datasets") or []
    dataset = datasets[0] if datasets else {}
    return {
        "key": key,
        "title": title,
        "labels": chart.get("labels") or [],
        "data": dataset.get("data") or [],
        "color": dataset.get("background_color") or color,
    }


def _statistics_overview_item(title, subtitle="", value="", image="", href="", key=""):
    return {
        "key": key or title,
        "title": title or "",
        "subtitle": subtitle,
        "value": str(value) if value not in (None, "") else "",
        "image": _statistics_image(image),
        "href": href,
    }


def _statistics_overview_panel(key, title, items, round_images=False):
    return {
        "key": key,
        "title": title,
        "roundImages": round_images,
        "items": items,
    }


def _statistics_top_played_panel(media_type, context, user):
    entries = (context.get("top_played") or {}).get(media_type) or []
    if not entries:
        return None
    items = []
    for entry in entries:
        media_entry = entry.get("media")
        item = getattr(media_entry, "item", None)
        if item is None:
            continue
        duration = entry.get("formatted_duration") or ""
        if media_type in (MediaTypes.TV.value, MediaTypes.ANIME.value):
            count = entry.get("episode_count") or 0
            subtitle = f"{duration} · {_statistics_plural(count, '%(count)s episode', '%(count)s episodes')}"
        elif media_type == MediaTypes.MOVIE.value:
            count = entry.get("play_count") or 0
            subtitle = f"{duration} · {_statistics_plural(count, '%(count)s play', '%(count)s plays')}"
        else:
            subtitle = duration
        items.append(_statistics_overview_item(
            item.title,
            subtitle=subtitle,
            image=getattr(item, "image", ""),
            href=_statistics_media_href(item),
            key=f"{item.source}:{item.media_id}",
        ))
    return _statistics_overview_panel(
        f"{media_type}-most-played", gettext("Most Played"), items,
    )


def _statistics_top_rated_panel(media_type, context, user):
    entries = context.get(f"top_rated_{media_type}") or []
    if not entries:
        return None
    items = []
    for media in entries:
        item = getattr(media, "item", None)
        if item is None:
            continue
        items.append(_statistics_overview_item(
            item.title,
            subtitle="",
            value=_statistics_media_score(media, user),
            image=getattr(item, "image", ""),
            href=_statistics_media_href(item),
            key=f"{item.source}:{item.media_id}",
        ))
    return _statistics_overview_panel(f"{media_type}-top-rated", gettext("Top Rated"), items)


def _statistics_music_overview(consumption, context, user):
    color = _statistics_media_color(context, MediaTypes.MUSIC.value)
    charts = []
    if context.get("show_year_charts"):
        charts.append(_statistics_overview_chart(
            "music-year",
            gettext("Music Plays by Year"),
            (consumption.get("charts") or {}).get("by_year"),
            color,
        ))
    panels = []

    def panel(key, title, rows, *, image_key, href_builder, round_images=False):
        items = []
        for row in rows or []:
            count = row.get("plays") or 0
            subtitle = row.get("formatted_duration") or ""
            if subtitle and count:
                subtitle = f"{subtitle} · {_statistics_plural(count, '%(count)s play', '%(count)s plays')}"
            elif count:
                subtitle = _statistics_plural(count, "%(count)s play", "%(count)s plays")
            items.append(_statistics_overview_item(
                row.get("name") or row.get("title") or row.get("label")
                or row.get("code") or "",
                subtitle=subtitle,
                image=row.get(image_key) or "",
                href=href_builder(row),
                key=f"{key}:{row.get('id') or row.get('name') or row.get('title') or row.get('label') or row.get('code')}",
            ))
        if items:
            panels.append(_statistics_overview_panel(key, title, items, round_images))

    panel(
        "music-artists", gettext("Top Artists"), consumption.get("top_artists"),
        image_key="image", href_builder=app_tags.music_artist_url, round_images=True,
    )
    panel(
        "music-albums", gettext("Top Albums"), consumption.get("top_albums"),
        image_key="image", href_builder=app_tags.music_album_url,
    )
    panel(
        "music-tracks", gettext("Top Tracks"), consumption.get("top_tracks"),
        image_key="album_image",
        href_builder=lambda row: (
            app_tags.music_album_url({
                "id": row.get("album_id"),
                "title": row.get("album") or "",
                "artist_id": row.get("album_artist_id"),
                "artist_name": row.get("album_artist_name") or "",
            })
            if row.get("album_id") else ""
        ),
    )
    panel(
        "music-decades", gettext("Top Decades"), consumption.get("top_decades"),
        image_key="", href_builder=lambda row: "",
    )
    panel(
        "music-countries", gettext("Top Countries"), consumption.get("top_countries"),
        image_key="", href_builder=lambda row: "",
    )
    return {
        "id": "music",
        "typeValue": "music",
        "typeLabel": gettext(STATISTICS_OVERVIEW_TYPE_LABELS["music"]),
        "title": gettext("Activity Overview"),
        "charts": charts,
        "panels": panels,
    }


def _statistics_podcast_href(entry):
    from django.utils.text import slugify

    show_id = entry.get("show_id")
    podcast_uuid = entry.get("podcast_uuid")
    if show_id and podcast_uuid:
        title = entry.get("slug") or entry.get("title") or entry.get("show") or "podcast"
        return reverse(
            "media_details",
            kwargs={
                "source": "pocketcasts",
                "media_type": "podcast",
                "media_id": podcast_uuid,
                "title": slugify(title) or "podcast",
            },
        )
    if show_id:
        return reverse("podcast_show_detail", args=[show_id])
    return ""


def _statistics_podcast_overview(consumption, context):
    color = _statistics_media_color(context, MediaTypes.PODCAST.value)
    charts = []
    if context.get("show_year_charts"):
        charts.append(_statistics_overview_chart(
            "podcast-year",
            gettext("Podcast Plays by Year"),
            (consumption.get("charts") or {}).get("by_year"),
            color,
        ))
    panels = []

    def panel(key, title, rows):
        items = []
        for row in rows or []:
            count = row.get("plays") or 0
            duration = row.get("formatted_duration") or ""
            if key == "podcast-longest":
                subtitle = duration
            elif duration and count:
                subtitle = f"{duration} · {_statistics_plural(count, '%(count)s play', '%(count)s plays')}"
            else:
                subtitle = _statistics_plural(count, "%(count)s play", "%(count)s plays")
            items.append(_statistics_overview_item(
                row.get("title") or row.get("show") or "",
                subtitle=subtitle,
                image=row.get("image") or "",
                href=_statistics_podcast_href(row),
                key=f"{key}:{row.get('show_id') or row.get('episode_id') or row.get('title')}",
            ))
        if items:
            panels.append(_statistics_overview_panel(key, title, items))

    panel("podcast-most-played", gettext("Most Played"), consumption.get("most_played"))
    panel("podcast-most-listened", gettext("Most Listened"), consumption.get("most_listened"))
    panel("podcast-longest", gettext("Longest Episodes"), consumption.get("longest_episodes"))
    return {
        "id": "podcast",
        "typeValue": "podcast",
        "typeLabel": gettext(STATISTICS_OVERVIEW_TYPE_LABELS["podcast"]),
        "title": gettext("Activity Overview"),
        "charts": charts,
        "panels": panels,
    }


def _statistics_game_overview(consumption, context, user):
    color = _statistics_media_color(context, MediaTypes.GAME.value)
    charts_obj = consumption.get("charts") or {}
    charts = []
    if context.get("show_year_charts"):
        charts.append(_statistics_overview_chart(
            "game-year", gettext("Game Hours by Year"), charts_obj.get("by_year"), color,
        ))
    charts.append(_statistics_overview_chart(
        "game-month", gettext("Game Hours by Month"), charts_obj.get("by_month"), color,
    ))
    charts.append(_statistics_overview_chart(
        "game-daily-average",
        gettext("Average Daily Playtime"),
        charts_obj.get("by_daily_average"),
        color,
    ))
    panels = []
    most_played = _statistics_top_played_panel(MediaTypes.GAME.value, context, user)
    if most_played:
        panels.append(most_played)
    platform_items = []
    for platform in consumption.get("platform_breakdown") or []:
        count = platform.get("games") or 0
        platform_items.append(_statistics_overview_item(
            platform.get("name") or "",
            subtitle=(
                f"{platform.get('formatted_hours') or ''} · "
                f"{_statistics_plural(count, '%(count)s game', '%(count)s games')}"
            ),
            value="",
            key=f"platform:{platform.get('name')}",
        ))
    if platform_items:
        panels.append(_statistics_overview_panel(
            "game-platforms", gettext("Top Platforms"), platform_items,
        ))
    return {
        "id": "game",
        "typeValue": "game",
        "typeLabel": gettext(STATISTICS_OVERVIEW_TYPE_LABELS["game"]),
        "title": gettext("Activity Overview"),
        "charts": [chart for chart in charts if chart["labels"]],
        "panels": panels,
    }


def _statistics_reading_overview(media_type, consumption, context, user):
    color = _statistics_media_color(context, media_type)
    label = gettext(STATISTICS_OVERVIEW_TYPE_LABELS.get(media_type, media_type))
    unit_name = consumption.get("unit_name") or gettext("Page")
    facts = []
    listening = consumption.get("listening")
    if listening:
        facts.append({
            "key": f"{media_type}-listening",
            "label": gettext("Listening Time"),
            "value": listening.get("formatted") or "",
            "copy": gettext("Audiobook sessions in this range"),
        })
    charts = []
    completion_charts = consumption.get("completion_charts") or {}
    if context.get("show_year_charts"):
        charts.append(_statistics_overview_chart(
            f"{media_type}-year",
            gettext("%(label)s by Year") % {
                "label": consumption.get("completion_label") or gettext("Completed"),
            },
            completion_charts.get("by_year"),
            color,
        ))
    charts.append(_statistics_overview_chart(
        f"{media_type}-released",
        gettext("%(label)s Released by Year") % {"label": label},
        consumption.get("release_chart"),
        color,
    ))
    charts.append(_statistics_overview_chart(
        f"{media_type}-completed-length",
        gettext("Completed %(unit)ss") % {"unit": unit_name},
        consumption.get("completed_length_chart"),
        color,
    ))
    panels = []
    items = []
    for row in consumption.get("top_items") or []:
        entry = row.get("media")
        item = getattr(entry, "item", None)
        if item is None:
            continue
        items.append(_statistics_overview_item(
            item.title,
            subtitle=row.get("formatted_units") or "",
            image=getattr(item, "image", ""),
            href=_statistics_media_href(item),
            key=f"{item.source}:{item.media_id}",
        ))
    if items:
        panels.append(_statistics_overview_panel(
            f"{media_type}-most-read", gettext("Most Read"), items,
        ))
    if media_type == MediaTypes.BOOK.value:
        author_items = []
        for author in consumption.get("top_authors") or []:
            count = author.get("titles") or 0
            author_items.append(_statistics_overview_item(
                author.get("name") or "",
                subtitle=(
                    f"{author.get('formatted_units') or ''} · "
                    f"{_statistics_plural(count, '%(count)s book', '%(count)s books')}"
                ),
                image=author.get("image") or "",
                href=(
                    reverse(
                        "person_detail",
                        kwargs={
                            "source": author.get("source"),
                            "person_id": author.get("person_id"),
                            "name": app_tags.slug(author.get("name") or ""),
                        },
                    )
                    if author.get("source") and author.get("person_id")
                    else ""
                ),
                key=f"author:{author.get('name')}",
            ))
        if author_items:
            panels.append(_statistics_overview_panel(
                f"{media_type}-authors", gettext("Top Authors"), author_items,
                round_images=True,
            ))
    genre_items = []
    genre_noun = {
        MediaTypes.BOOK.value: ("%(count)s book", "%(count)s books"),
        MediaTypes.COMIC.value: ("%(count)s comic", "%(count)s comics"),
        MediaTypes.MANGA.value: ("%(count)s manga", "%(count)s manga"),
    }.get(media_type, ("%(count)s title", "%(count)s titles"))
    for genre in consumption.get("top_genres") or []:
        count = genre.get("titles") or 0
        genre_items.append(_statistics_overview_item(
            genre.get("name") or "",
            subtitle=(
                f"{genre.get('formatted_units') or ''} · "
                f"{_statistics_plural(count, *genre_noun)}"
            ),
            href=(
                reverse("history")
                + "?genre=" + quote(str(genre.get("name") or ""), safe="")
                + f"&media_type={media_type}"
                + (
                    f"&start-date={context.get('start_date_str')}"
                    if context.get("start_date_str")
                    and context.get("start_date_str") != "all"
                    else ""
                )
                + (
                    f"&end-date={context.get('end_date_str')}"
                    if context.get("end_date_str")
                    and context.get("end_date_str") != "all"
                    else ""
                )
            ),
            key=f"genre:{genre.get('name')}",
        ))
    if genre_items:
        panels.append(_statistics_overview_panel(
            f"{media_type}-genres", gettext("Top Genres"), genre_items,
        ))
    top_rated = _statistics_top_rated_panel(media_type, context, user)
    if top_rated:
        panels.append(top_rated)
    return {
        "id": media_type,
        "typeValue": media_type,
        "typeLabel": label,
        "title": gettext("Activity Overview"),
        "facts": facts,
        "charts": [chart for chart in charts if chart["labels"]],
        "panels": panels,
    }


def _statistics_media_overview_models(context, statistics_data, user, range_label):
    models = {}

    def add(media_type, model):
        model["rangeLabel"] = range_label
        models[media_type] = model

    for media_type in (MediaTypes.TV.value, MediaTypes.ANIME.value,
                       MediaTypes.MOVIE.value, MediaTypes.VIDEO.value):
        consumption = context.get(f"{media_type}_consumption") or {}
        if not consumption.get("has_data"):
            continue
        color = _statistics_media_color(context, media_type)
        charts = []
        if context.get("show_year_charts"):
            chart_title = {
                MediaTypes.TV.value: gettext("Episode Plays by Year"),
                MediaTypes.ANIME.value: gettext("Episode Plays by Year"),
                MediaTypes.MOVIE.value: gettext("Movie Plays by Year"),
                MediaTypes.VIDEO.value: gettext("Video Plays by Year"),
            }[media_type]
            charts.append(_statistics_overview_chart(
                f"{media_type}-year",
                chart_title,
                (consumption.get("charts") or {}).get("by_year"),
                color,
            ))
        panels = []
        if media_type != MediaTypes.VIDEO.value:
            most_played = _statistics_top_played_panel(media_type, context, user)
            if most_played:
                panels.append(most_played)
            top_rated = _statistics_top_rated_panel(media_type, context, user)
            if top_rated:
                panels.append(top_rated)
        add(media_type, {
            "id": media_type,
            "typeValue": media_type,
            "typeLabel": gettext(STATISTICS_OVERVIEW_TYPE_LABELS[media_type]),
            "title": gettext("Activity Overview"),
            "charts": [chart for chart in charts if chart["labels"]],
            "panels": panels,
        })

    game = context.get("game_consumption") or {}
    if game.get("has_data"):
        add(MediaTypes.GAME.value, _statistics_game_overview(game, context, user))

    if context.get("music_consumption", {}).get("has_data"):
        add(MediaTypes.MUSIC.value, _statistics_music_overview(
            context["music_consumption"], context, user,
        ))

    if context.get("podcast_consumption", {}).get("has_data"):
        add(MediaTypes.PODCAST.value, _statistics_podcast_overview(
            context["podcast_consumption"], context,
        ))

    for media_type in (MediaTypes.BOOK.value, MediaTypes.COMIC.value,
                       MediaTypes.MANGA.value):
        consumption = context.get(f"{media_type}_consumption") or {}
        if consumption.get("has_data"):
            add(media_type, _statistics_reading_overview(
                media_type, consumption, context, user,
            ))

    return models


def _statistics_comparison_section(user, context, statistics_data):
    current = _get_statistics_minutes_by_type(statistics_data)
    comparisons = context.get("hours_per_media_type_comparison") or {}
    selected = context.get("selected_compare_mode") or STATISTICS_COMPARE_PREVIOUS_PERIOD
    duration_format = getattr(user, "duration_format", "hours_minutes")
    rows = []
    for media_type in MEDIA_TYPE_HOURS_ORDER:
        current_total = float(current.get(media_type) or 0)
        if current_total <= 0 and media_type not in comparisons:
            continue
        entry = comparisons.get(media_type) or {}
        tooltip = entry.get("tooltip") or {}
        state = entry.get("badge_state") or "none"
        if state not in ("up", "down"):
            state = "neutral"
        rows.append({
            "key": media_type,
            "type": media_type,
            "label": app_tags.media_type_readable(media_type),
            "color": _statistics_media_color(context, media_type),
            "currentLabel": _format_statistics_total_for_media_type(
                media_type, current_total, duration_format,
            ),
            "comparisonLabel": (
                tooltip.get("comparison_total") if selected != STATISTICS_COMPARE_NONE else ""
            ) or "",
            "deltaLabel": (
                entry.get("badge_short") or entry.get("badge") or ""
                if selected != STATISTICS_COMPARE_NONE else ""
            ),
            "state": state,
        })
    comparison_label = STATISTICS_COMPARE_LABELS.get(selected, "")
    if selected == STATISTICS_COMPARE_NONE:
        copy = gettext("Hours in this range. Choose a period to compare.")
    else:
        copy = gettext("Hours in this range compared with %(period)s.") % {
            "period": comparison_label.lower(),
        }
    return {
        "title": gettext("Comparison"),
        "copy": copy,
        "selected": selected,
        "options": [
            {"value": value, "label": gettext(label)}
            for value, label in STATISTICS_COMPARE_LABELS.items()
        ],
        "rows": rows,
    }


def _statistics_talent_react_props(context, user):
    role_leaders = context.get("role_leaders") or {}
    role_sort = role_leaders.get("sort_by") or getattr(
        user, "top_talent_sort_by", "plays",
    )
    columns = []
    for column in role_leaders.get("columns") or []:
        entries = []
        for index, entry in enumerate(column.get("entries") or []):
            entries.append({
                "name": entry.get("name") or "",
                "source": entry.get("source") or "",
                "personId": str(entry.get("person_id") or ""),
                "rank": index + 1,
                "plays": entry.get("plays") or 0,
                "titles": entry.get("unique_titles") or 0,
                "time": entry.get("watched_time") or "",
                "displayMetric": str(entry.get("display_metric") or ""),
                "selected": bool(entry.get("selected")),
            })
        if entries:
            columns.append({
                "bucket": column.get("bucket") or "",
                "label": column.get("label") or "",
                "entries": entries,
            })
    role_model = {
        "title": gettext("Role Leaders"),
        "copy": gettext("The actors, directors and writers you return to most."),
        "selected": role_sort,
        "sortOptions": [
            {"value": "plays", "label": gettext("Plays")},
            {"value": "time", "label": gettext("Time")},
            {"value": "titles", "label": gettext("Titles")},
        ],
        "columns": columns,
    }

    studio_footprint = context.get("studio_footprint") or {}
    studio_sort = context.get("studio_sort_by") or getattr(
        user, "studio_sort_by", "plays",
    )
    studios = []
    for index, studio in enumerate(studio_footprint.get("studios") or []):
        studios.append({
            "name": studio.get("name") or "",
            "pct": studio.get("pct") or 0,
            "plays": studio.get("plays") or 0,
            "time": studio.get("watched_time") or "",
            "metricLabel": (
                studio.get("watched_time") or ""
                if studio_sort == "time"
                else _statistics_plural(
                    studio.get("plays") or 0, "%(count)s play", "%(count)s plays",
                )
            ),
            "color": "#6366f1",
            "rank": index + 1,
        })
    delta = studio_footprint.get("delta")
    studio_model = {
        "title": gettext("Studio Footprint"),
        "copy": gettext("Studios that appear most often."),
        "selected": studio_sort,
        "sortOptions": [
            {"value": "plays", "label": gettext("Plays")},
            {"value": "time", "label": gettext("Time")},
        ],
        "delta": (
            {
                "label": f"{'+' if delta.get('is_positive') else ''}{delta.get('pct', 0)}%",
                "state": "up" if delta.get("is_positive") else "down",
                "copy": gettext("studio appearances vs previous period"),
            }
            if isinstance(delta, dict) else None
        ),
        "studios": studios,
    }

    genre_sort = context.get("genre_sort_by") or getattr(user, "genre_sort_by", "time")
    genres = [
        {
            "name": genre.get("name") or "",
            "pct": genre.get("pct") or 0,
            "plays": genre.get("plays") or 0,
            "formattedDuration": genre.get("formatted_duration") or "",
            "color": genre.get("color") or "",
        }
        for genre in context.get("top_genres_combined") or []
    ]
    eras = [
        {
            "label": era.get("label") or "",
            "pct": era.get("pct") or 0,
            "plays": era.get("plays") or 0,
            "formattedDuration": era.get("formatted_duration") or "",
        }
        for era in context.get("era_spotlight") or []
    ]
    taste_model = {
        "title": gettext("Taste Signals"),
        "copy": gettext("What your library says about your taste."),
        "selected": genre_sort,
        "sortOptions": [
            {"value": "time", "label": gettext("Time")},
            {"value": "plays", "label": gettext("Plays")},
        ],
        "genresTitle": gettext("Top Genres"),
        "erasTitle": gettext("Era Spotlight"),
        "genres": genres,
        "eras": eras,
        "genresEmpty": gettext("No genre data available for this range."),
        "erasEmpty": gettext("No release-year data available for this range."),
    }

    return {
        "roleLeaders": role_model,
        "studioFootprint": studio_model,
        "tasteSignals": taste_model,
    }


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

        selected_media_types = ",".join(
            _normalize_statistics_media_types(
                getattr(request.user, "statistics_default_media_types", ""),
                allowed=set(request.user.get_enabled_media_types())
                | {
                    MediaTypes.TV.value,
                    MediaTypes.MOVIE.value,
                    MediaTypes.ANIME.value,
                    MediaTypes.GAME.value,
                },
            )
        )

        statistics_data = statistics_cache.get_statistics_data(
            request.user,
            start_date,
            end_date,
            range_name=selected_range_name,
        )
        statistics_building = bool(statistics_data.pop("statistics_building", False))
        statistics_built_at = None
        if selected_range_name in statistics_cache.PREDEFINED_RANGES:
            from app import statistics_sync

            snapshot = statistics_sync.load_snapshot_meta(
                request.user.id, selected_range_name
            )
            statistics_built_at = snapshot.get("built_at") if snapshot else None

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
            "Today": gettext_noop("yesterday"),
            "Yesterday": gettext_noop("previous day"),
            "This Week": gettext_noop("last week"),
            "This Month": gettext_noop("last month"),
            "This Year": gettext_noop("last year"),
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
            "selected_media_types": selected_media_types,
            "statistics_building": statistics_building,
            "statistics_built_at": statistics_built_at,
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
            "minutes_per_media_type": statistics_data.get("minutes_per_media_type", {}),
            "tv_consumption": statistics_data["tv_consumption"],
            "movie_consumption": statistics_data["movie_consumption"],
            "anime_consumption": statistics_data.get("anime_consumption", {}),
            "music_consumption": statistics_data["music_consumption"],
            "podcast_consumption": statistics_data["podcast_consumption"],
            "video_consumption": statistics_data.get("video_consumption", {}),
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
                "anime": config.get_stats_color(MediaTypes.ANIME.value),
                "boardgame": config.get_stats_color(MediaTypes.BOARDGAME.value),
                "game": config.get_stats_color(MediaTypes.GAME.value),
                "music": config.get_stats_color(MediaTypes.MUSIC.value),
                "podcast": config.get_stats_color(MediaTypes.PODCAST.value),
                "video": config.get_stats_color(MediaTypes.VIDEO.value),
                "book": config.get_stats_color(MediaTypes.BOOK.value),
                "comic": config.get_stats_color(MediaTypes.COMIC.value),
                "manga": config.get_stats_color(MediaTypes.MANGA.value),
            },
        }

        context["statistics_react_props"] = _build_statistics_react_props(
            request.user, context, statistics_data
        )
        if request.GET.get("format") == "json":
            return JsonResponse({"model": context["statistics_react_props"]})
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
                "video": config.get_stats_color(MediaTypes.VIDEO.value),
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
            "video_consumption": {},
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
            "selected_media_types": ",".join(
                _normalize_statistics_media_types(
                    getattr(request.user, "statistics_default_media_types", ""),
                    allowed=set(request.user.get_enabled_media_types())
                    | {
                        MediaTypes.TV.value,
                        MediaTypes.MOVIE.value,
                        MediaTypes.ANIME.value,
                        MediaTypes.GAME.value,
                    },
                )
            ),
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
            "video_consumption": empty_statistics_data["video_consumption"],
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
        context["statistics_react_props"] = _build_statistics_react_props(
            request.user, context, empty_statistics_data
        )
        if request.GET.get("format") == "json":
            return JsonResponse({"model": context["statistics_react_props"]})
        return render(request, "app/statistics.html", context)


TALENT_FRAGMENT_CACHE_TTL = 300
# The last rendered section per range and sort, kept across data changes so a
# view after a play can show it at once while a rebuild runs in the background.
TALENT_FRAGMENT_LAST_GOOD_TTL = 7 * 24 * 60 * 60
TALENT_FRAGMENT_REFRESH_LOCK_TTL = 5 * 60


def _talent_fragment_key_suffix(user, range_token, compare_mode):
    top_talent_sort = getattr(user, "top_talent_sort_by", "plays")
    genre_sort = getattr(user, "genre_sort_by", "time")
    studio_sort = getattr(user, "studio_sort_by", "plays")
    return f"{range_token}_{top_talent_sort}_{studio_sort}_{genre_sort}_{compare_mode}"


def _talent_fragment_cache_key(user, range_token, compare_mode):
    # The fragment renders from the published range, so it must turn over when
    # a new snapshot is published, not only when data changes: keying on the
    # change token alone cached the stale snapshot's output for the full TTL.
    history_version = statistics_cache.get_history_version(user.id)
    if range_token in statistics_cache.PREDEFINED_RANGES:
        from app import statistics_sync

        meta = statistics_sync.load_snapshot_meta(user.id, range_token)
        if meta and meta.get("built_at"):
            history_version = f"{history_version}:{meta['built_at'].isoformat()}"
    suffix = _talent_fragment_key_suffix(user, range_token, compare_mode)
    return f"stats_talent_frag_v1_{user.id}_{history_version}_{suffix}"


def _talent_fragment_last_good_key(user, range_token, compare_mode):
    suffix = _talent_fragment_key_suffix(user, range_token, compare_mode)
    return f"stats_talent_frag_last_v1_{user.id}_{suffix}"


def _talent_fragment_request(
    user, range_name, start_date_str, end_date_str, compare_mode_param
):
    """Resolve a talent fragment request to its dates and cache keys."""
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
            user,
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
    return {
        "start_date": start_date,
        "end_date": end_date,
        "comparison_start_date": comparison_start_date,
        "comparison_end_date": comparison_end_date,
        "cache_key": _talent_fragment_cache_key(
            user, range_token, selected_compare_mode
        ),
        "last_good_key": _talent_fragment_last_good_key(
            user, range_token, selected_compare_mode
        ),
    }


def build_talent_fragment(
    user, range_name, start_date_str, end_date_str, compare_mode_param
):
    """Build the talent section context and store it under both keys."""
    from django.core.cache import cache

    fragment = _talent_fragment_request(
        user, range_name, start_date_str, end_date_str, compare_mode_param
    )
    context = _build_talent_fragment_context(
        user,
        range_name,
        fragment["start_date"],
        fragment["end_date"],
        start_date_str,
        end_date_str,
        fragment["comparison_start_date"],
        fragment["comparison_end_date"],
    )
    cache.set(fragment["cache_key"], context, TALENT_FRAGMENT_CACHE_TTL)
    cache.set(fragment["last_good_key"], context, TALENT_FRAGMENT_LAST_GOOD_TTL)
    # The section now reflects every change so far; a later change may queue
    # the next rebuild.
    cache.delete(_talent_fragment_refresh_lock_key(fragment["last_good_key"]))
    return context


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
        "statistics_talent_props": _statistics_talent_react_props(
            {
                "role_leaders": role_leaders,
                "studio_footprint": studio_footprint,
                "studio_sort_by": active_studio_sort,
                "top_genres_combined": top_genres_combined,
                "era_spotlight": era_spotlight,
                "genre_sort_by": active_genre_sort,
            },
            user,
        ),
    }


@require_GET
def statistics_talent_fragment(request):
    """Render the talent/studio/taste statistics section as an HTMX fragment.

    Loaded asynchronously from the statistics shell so the featured-player
    scan and the comparison-window talent re-aggregation never block the
    page's first paint. The built context is cached; the key embeds the
    user's history version so any tracked-media change (or the refresh
    button) invalidates it automatically.

    Every play changes that version, and a rebuild can take many seconds on a
    large library, so after a change the last rendered section is shown at
    once and the rebuild runs on the interactive worker. Only a section never
    built for this range and sort is built while the viewer waits.
    """
    from django.core.cache import cache

    range_name = request.GET.get("range_name") or None
    start_date_str = request.GET.get("start-date") or None
    end_date_str = request.GET.get("end-date") or None
    compare_mode_param = request.GET.get("compare") or None

    fragment = _talent_fragment_request(
        request.user, range_name, start_date_str, end_date_str, compare_mode_param
    )
    context = cache.get(fragment["cache_key"])
    if context is None:
        last_good = cache.get(fragment["last_good_key"])
        if last_good is not None:
            _queue_talent_fragment_refresh(
                request.user,
                fragment["last_good_key"],
                range_name,
                start_date_str,
                end_date_str,
                compare_mode_param,
            )
            # A worker that finished first (or an eager test run) left the
            # fresh section; otherwise the last one is shown meanwhile.
            context = cache.get(fragment["cache_key"]) or last_good
    if context is None:
        context = build_talent_fragment(
            request.user,
            range_name,
            start_date_str,
            end_date_str,
            compare_mode_param,
        )

    if request.GET.get("format") == "json":
        return JsonResponse({
            "talent": context.get("statistics_talent_props") or {},
            "featuredPerson": context.get("featured_person"),
            "selectedPersonKey": (
                f"{context['featured_person'].get('source', '')}:"
                f"{context['featured_person'].get('person_id', '')}"
                if context.get("featured_person") else ""
            ),
        })

    return render(
        request,
        "app/components/statistics/talent_section.html",
        context,
    )


def _talent_fragment_refresh_lock_key(last_good_key):
    # Keyed like the last-good copy, not the per-change key: plays arriving
    # while a rebuild is queued must not queue more rebuilds of the same
    # section on the single-concurrency interactive worker.
    return f"{last_good_key}_refreshing"


def _queue_talent_fragment_refresh(
    user, last_good_key, range_name, start_date_str, end_date_str, compare_mode_param
):
    from django.core.cache import cache

    if not cache.add(
        _talent_fragment_refresh_lock_key(last_good_key),
        True,
        TALENT_FRAGMENT_REFRESH_LOCK_TTL,
    ):
        return
    from app.tasks_interactive import refresh_statistics_talent_fragment_task

    try:
        refresh_statistics_talent_fragment_task.delay(
            user.id, range_name, start_date_str, end_date_str, compare_mode_param
        )
    except Exception as error:  # the last good section is already on screen
        logger.warning(
            "talent_fragment_refresh_enqueue_failed user_id=%s error=%s",
            user.id,
            exception_summary(error),
        )


@require_POST
def refresh_statistics(request):
    """Force refresh statistics cache for the current range."""
    range_name = request.POST.get("range_name")
    if not range_name:
        return JsonResponse({"error": "range_name is required"}, status=400)

    if range_name not in statistics_cache.PREDEFINED_RANGES:
        return JsonResponse({"error": "Invalid range_name"}, status=400)

    from app import statistics_sync

    statistics_sync.request_manual_refresh(request.user, range_name)

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
    media_type = _normalize_talent_media_types(request.POST.get("media_type")) or None

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
                refreshed = statistics_cache.refresh_statistics_cache(
                    request.user.id, range_name
                )
                requires_reload = refreshed is not None
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

    if media_type is not None:
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
            "role_leaders": _statistics_talent_react_props(
                {
                    "role_leaders": role_leaders,
                    "studio_footprint": studio_footprint,
                    "studio_sort_by": getattr(
                        request.user, "studio_sort_by", "plays",
                    ),
                },
                request.user,
            )["roleLeaders"],
        },
    )


@require_POST
def update_genre_sort(request):
    """Autosave the Taste Signals sort preference and refresh Top Genres + Era Spotlight."""
    sort_by = request.POST.get("sort_by")
    range_name = request.POST.get("range_name")
    start_date_str = request.POST.get("start_date")
    end_date_str = request.POST.get("end_date")
    media_type = (
        _normalize_talent_media_types(
            request.POST.get("media_type"),
            allowed=TALENT_MEDIA_TYPES | {MediaTypes.MUSIC.value},
        )
        or None
    )

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
    if media_type is not None:
        # Filtered view: only the selected media types contribute rows.
        for key in consumption_by_type:
            if key not in media_type:
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
            "taste_signals": _statistics_talent_react_props(
                {
                    "top_genres_combined": top_genres_combined,
                    "era_spotlight": era_spotlight,
                    "genre_sort_by": sort_by,
                },
                request.user,
            )["tasteSignals"],
        },
    )


@require_POST
def update_studio_sort(request):
    """Autosave the Studio Footprint sort preference and refresh its list."""
    sort_by = request.POST.get("sort_by")
    range_name = request.POST.get("range_name")
    start_date_str = request.POST.get("start_date")
    end_date_str = request.POST.get("end_date")
    media_type = _normalize_talent_media_types(request.POST.get("media_type")) or None

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

    if media_type is not None:
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
            "studio_footprint": _statistics_talent_react_props(
                {
                    "studio_footprint": studio_footprint,
                    "studio_sort_by": sort_by,
                },
                request.user,
            )["studioFootprint"],
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
            # These preferences shape the day payloads, so every day rebuilds.
            statistics_cache.invalidate_all_statistics_days(
                request.user.id,
                reason="statistics_preferences_changed",
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


@require_POST
def update_statistics_media_types(request):
    """Autosave the media types ticked in the statistics filter."""
    raw = request.POST.get("media_types", "")
    tokens = [token.strip() for token in raw.split(",") if token.strip()]
    if any(token not in MEDIA_TYPE_HOURS_ORDER for token in tokens):
        return JsonResponse(
            {
                "error": "Invalid media_types",
                "valid_values": list(MEDIA_TYPE_HOURS_ORDER),
            },
            status=400,
        )

    normalized = ",".join(_normalize_statistics_media_types(raw))
    previous = request.user.statistics_default_media_types
    updated = request.user.update_preference(
        "statistics_default_media_types", normalized
    )

    return JsonResponse(
        {
            "success": True,
            "changed": previous != updated,
            "media_types": updated,
        }
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
