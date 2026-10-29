import calendar as cal
import logging
from collections import defaultdict
from datetime import UTC, date, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import formats, timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from app.models import Item, MediaTypes, PodcastEpisode, Status
from events import tasks
from events.history_feed import (
    DEFAULT_MEDIA_TYPES,
    HISTORY_MEDIA_TYPES,
    get_history_plays,
    selected_history_media_types,
)
from events.models import INACTIVE_TRACKING_STATUSES, Event, ReleaseTypes
from users.models import User, WeekStartDayChoices

logger = logging.getLogger(__name__)

CALENDAR_FEED_CACHE_SECONDS = 15 * 60
ICS_DATETIME_FORMAT = "%Y%m%dT%H%M%SZ"
ICS_LINE_OCTETS = 75


def _escape_ics_text(value):
    """Escape a TEXT value (RFC 5545 section 3.3.11)."""
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _fold_ics_line(line):
    """Fold a content line at 75 octets without splitting a UTF-8 character."""
    if len(line) * 4 <= ICS_LINE_OCTETS:
        return line
    folded = []
    current = ""
    limit = ICS_LINE_OCTETS
    for char in line:
        if len((current + char).encode()) > limit:
            folded.append(current)
            current = char
            limit = ICS_LINE_OCTETS - 1  # continuation lines start with a space
        else:
            current += char
    folded.append(current)
    return "\r\n ".join(folded)


def _user_for_token(token):
    """Return the user a calendar link belongs to, or None for an unknown one."""
    try:
        return User.objects.get(token=token)
    except ObjectDoesNotExist:
        logger.warning(
            "Could not process Calendar request: Invalid token: %s",
            token,
        )
        return None


@require_GET
def calendar(request):
    """Display the calendar page."""
    # Handle view type
    view_type = request.user.update_preference(
        "calendar_layout",
        request.GET.get("view"),
    )

    month = request.GET.get("month")
    year = request.GET.get("year")

    try:
        current_date = (
            date(int(year), int(month), 1) if month and year else timezone.localdate()
        )
        month, year = current_date.month, current_date.year
    except (ValueError, TypeError):
        logger.warning("Invalid month or year provided: %s, %s", month, year)
        current_date = timezone.localdate()
        month, year = current_date.month, current_date.year

    # Calculate navigation dates
    is_december = month == 12  # noqa: PLR2004
    is_january = month == 1

    prev_month = 12 if is_january else month - 1
    prev_year = year - 1 if is_january else year

    next_month = 1 if is_december else month + 1
    next_year = year + 1 if is_december else year

    # Calculate date range for events
    first_day = date(year, month, 1)
    last_day = date(
        year + 1 if is_december else year,
        1 if is_december else month + 1,
        1,
    ) - timedelta(days=1)

    # Get calendar data
    week_start_sunday = request.user.week_start_day == WeekStartDayChoices.SUNDAY
    first_weekday = 6 if week_start_sunday else 0
    calendar_format = cal.Calendar(firstweekday=first_weekday).monthdayscalendar(
        year, month
    )
    month_name = formats.date_format(current_date, "F")
    base_weekdays = [
        formats.date_format(date(2024, 1, day), "D") for day in range(1, 8)
    ]
    weekday_headers = (
        [base_weekdays[6], *base_weekdays[:6]] if week_start_sunday else base_weekdays
    )

    # Get events and organize by day
    releases = Event.objects.get_user_events(request.user, first_day, last_day)

    podcast_media_ids = [
        release.item.media_id
        for release in releases
        if release.item.media_type == MediaTypes.PODCAST.value
    ]
    podcast_art_by_episode_uuid = {}
    if podcast_media_ids:
        podcast_art_by_episode_uuid = {
            episode.episode_uuid: episode.show.image
            for episode in PodcastEpisode.objects.filter(
                episode_uuid__in=podcast_media_ids,
            ).select_related("show")
            if episode.show and episode.show.image
        }

    event_status_values = [
        status.value
        for status in Status
        if status.value not in INACTIVE_TRACKING_STATUSES
    ]

    filter_media_types = set(request.user.get_enabled_media_types())
    if MediaTypes.TV.value in filter_media_types:
        filter_media_types.add(MediaTypes.SEASON.value)
    filter_media_types = sorted(
        filter_media_types,
        key=lambda media_type: MediaTypes(media_type).label,
    )

    release_media_types = {
        release.item.media_type
        for release in releases
        if release.item and release.item.media_type
    }
    available_media_types = sorted(
        release_media_types,
        key=lambda media_type: MediaTypes(media_type).label,
    )

    available_release_types = sorted(
        {release.release_type for release in releases if release.release_type},
    )

    item_ids_by_type = defaultdict(list)
    for release in releases:
        item_ids_by_type[release.item.media_type].append(release.item_id)

    status_by_item_id = {}
    for media_type, item_ids in item_ids_by_type.items():
        status_by_item_id.update(
            Item.objects.filter(
                id__in=item_ids,
                **{f"{media_type}__user": request.user},
            ).values_list("id", f"{media_type}__status"),
        )

    available_statuses_by_type = {}
    for media_type, item_ids in item_ids_by_type.items():
        statuses = {
            status_by_item_id[item_id]
            for item_id in item_ids
            if status_by_item_id.get(item_id)
        }
        if statuses:
            available_statuses_by_type[media_type] = sorted(
                statuses,
                key=lambda status: Status(status).label,
            )

    filter_statuses_by_type = {
        media_type: event_status_values
        for media_type in filter_media_types
        if media_type not in {MediaTypes.TV.value, MediaTypes.EPISODE.value}
    }

    release_dict = {}
    for release in releases:
        release.status = status_by_item_id.get(release.item_id)

        if (
            release.item.media_type == MediaTypes.PODCAST.value
            and release.item.image in {"", settings.IMG_NONE}
        ):
            release.item.image = podcast_art_by_episode_uuid.get(
                release.item.media_id,
                settings.IMG_NONE,
            )

        # Convert UTC datetime to user's timezone and extract day
        local_datetime = timezone.localtime(release.datetime)
        day = local_datetime.day
        if day not in release_dict:
            release_dict[day] = []
        release_dict[day].append(release)

    # Get today's date for highlighting
    today = timezone.localdate()
    days_in_month = range(1, last_day.day + 1)
    selected_day = (
        today.day
        if month == today.month and year == today.year
        else next(iter(sorted(release_dict.keys())), 1)
    )

    context = {
        "user": request.user,
        "media_types": [
            media_type.value
            for media_type in MediaTypes
            if media_type != MediaTypes.EPISODE
        ],
        "event_statuses": event_status_values,
        "history_media_types": HISTORY_MEDIA_TYPES,
        "history_default_media_types": DEFAULT_MEDIA_TYPES,
        "calendar": calendar_format,
        "month": month,
        "month_name": month_name,
        "year": year,
        "prev_month": prev_month,
        "prev_year": prev_year,
        "next_month": next_month,
        "next_year": next_year,
        "release_dict": release_dict,
        "today": today,
        "view_type": view_type,
        "available_media_types": available_media_types,
        "release_type_choices": ReleaseTypes.choices,
        "available_release_types": available_release_types,
        "region_unset": request.user.watch_provider_region == "UNSET",
        "available_statuses_by_type": available_statuses_by_type,
        "filter_media_types": filter_media_types,
        "filter_statuses_by_type": filter_statuses_by_type,
        "days_in_month": days_in_month,
        "selected_day": selected_day,
        "weekday_headers": weekday_headers,
    }
    return render(request, "events/calendar.html", context)


@require_POST
def reload_calendar(request):
    """Refresh the calendar with the latest dates."""
    tasks.reload_calendar.delay(user_id=request.user.id)
    messages.info(request, "The task to refresh upcoming releases has been queued.")
    return redirect("calendar")


@login_not_required
@csrf_exempt
@require_http_methods(["GET", "HEAD", "PROPFIND"])
def download_calendar(request, token: str):
    """Download the calendar as a iCalendar file."""
    user = _user_for_token(token)
    if user is None:
        return HttpResponse(status=401)

    now = timezone.now()

    # Calendar apps poll this feed on their own schedule, and each build walks
    # the whole event window, so a rendered feed is reused briefly per filter.
    feed_cache_key = (
        f"calendar_feed:{user.id}:{now.date().isoformat()}:{request.GET.urlencode()}"
    )
    cached_feed = cache.get(feed_cache_key)
    if cached_feed is not None:
        return _calendar_feed_response(cached_feed)

    # Define default start and end date (from past 30 days to incoming 90 days)
    start_date = now.date() - timedelta(days=30)
    end_date = now.date() + timedelta(days=90)

    # Retrieve release events
    releases = Event.objects.get_user_events(user, start_date, end_date)

    selected_media_types = request.GET.getlist("media_types")
    if selected_media_types:
        valid_media_types = {
            media_type
            for media_type in selected_media_types
            if media_type in {choice.value for choice in MediaTypes}
        }

        # TV release events are stored at the season level.
        if MediaTypes.TV.value in valid_media_types:
            valid_media_types.add(MediaTypes.SEASON.value)

        if valid_media_types:
            releases = releases.filter(item__media_type__in=valid_media_types)

    # No parameter means every release date; "none" leaves only main releases.
    if "release_types" in request.GET:
        allowed_release_types = set(request.GET.getlist("release_types")) & set(
            ReleaseTypes.values,
        )
        releases = releases.filter(
            Q(release_type="") | Q(release_type__in=allowed_release_types),
        )

    selected_statuses = request.GET.getlist("status")
    if selected_statuses:
        valid_statuses = {
            status
            for status in selected_statuses
            if status in {c.value for c in Status}
        }

        if valid_statuses:
            status_query = Q()
            for media_type in MediaTypes:
                if media_type in (MediaTypes.TV, MediaTypes.EPISODE):
                    continue
                status_query |= Q(
                    item__media_type=media_type.value,
                    **{f"item__{media_type.value}__status__in": valid_statuses},
                )
            releases = releases.filter(status_query)

    # An entry only needs its time and its title, and reading every Item
    # column (a dozen of them JSON) for each row was most of the query time.
    releases = releases.only(
        "datetime",
        "content_number",
        "release_type",
        "item__title",
        "item__media_type",
        "item__season_number",
        "item__episode_number",
    )

    # Written out directly: building an icalendar.Event per release spent most
    # of the request's time (about 0.3 ms each, on feeds of thousands).
    dtstamp = now.astimezone(UTC).strftime(ICS_DATETIME_FORMAT)
    lines = ["BEGIN:VCALENDAR", "PRODID:-//Floppy//EN", "VERSION:2.0"]
    for release in releases:
        if release.is_sentinel_time:
            start_date = release.datetime.date()
            dtstart = f"DTSTART;VALUE=DATE:{start_date:%Y%m%d}"
            dtend = f"DTEND;VALUE=DATE:{start_date + timedelta(days=1):%Y%m%d}"
        else:
            dt_tz_aware = release.datetime.replace(tzinfo=UTC)
            dtstart = f"DTSTART:{dt_tz_aware.strftime(ICS_DATETIME_FORMAT)}"
            dtend = f"DTEND:{dt_tz_aware.strftime(ICS_DATETIME_FORMAT)}"
        lines += [
            "BEGIN:VEVENT",
            f"UID:{release.id}",
            _fold_ics_line(f"SUMMARY:{_escape_ics_text(str(release))}"),
            dtstart,
            dtend,
            f"DTSTAMP:{dtstamp}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")

    feed = ("\r\n".join(lines) + "\r\n").encode()
    cache.set(feed_cache_key, feed, CALENDAR_FEED_CACHE_SECONDS)
    return _calendar_feed_response(feed)


@login_not_required
@csrf_exempt
@require_http_methods(["GET", "HEAD", "PROPFIND"])
def download_history_calendar(request, token: str):
    """Download finished plays (what the user watched, read, played) as iCal."""
    user = _user_for_token(token)
    if user is None:
        return HttpResponse(status=401)

    now = timezone.now()
    media_types = selected_history_media_types(request.GET.getlist("media_types"))

    # Calendar apps poll this link on their own schedule, so a built feed is
    # reused briefly. The key holds the resolved types, so a link with no
    # selection shares an entry with one that lists the defaults.
    feed_cache_key = (
        f"calendar_history_feed:{user.id}:{now.date().isoformat()}:"
        f"{','.join(sorted(media_types))}"
    )
    cached_feed = cache.get(feed_cache_key)
    if cached_feed is not None:
        return _calendar_feed_response(cached_feed, "history.ics")

    dtstamp = now.astimezone(UTC).strftime(ICS_DATETIME_FORMAT)
    lines = [
        "BEGIN:VCALENDAR",
        "PRODID:-//Floppy//EN",
        "VERSION:2.0",
        "X-WR-CALNAME:Floppy history",
    ]
    for play in get_history_plays(user, media_types, now):
        if play.is_date_only:
            dtstart = f"DTSTART;VALUE=DATE:{play.local_date:%Y%m%d}"
            dtend = (
                f"DTEND;VALUE=DATE:{play.local_date + timedelta(days=1):%Y%m%d}"
            )
        else:
            played_at = play.played_at.astimezone(UTC).strftime(ICS_DATETIME_FORMAT)
            dtstart = f"DTSTART:{played_at}"
            dtend = f"DTEND:{played_at}"
        lines += [
            "BEGIN:VEVENT",
            f"UID:{play.uid}@floppy-history",
            _fold_ics_line(f"SUMMARY:{_escape_ics_text(play.summary)}"),
            dtstart,
            dtend,
            f"DTSTAMP:{dtstamp}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")

    feed = ("\r\n".join(lines) + "\r\n").encode()
    cache.set(feed_cache_key, feed, CALENDAR_FEED_CACHE_SECONDS)
    return _calendar_feed_response(feed, "history.ics")


def _calendar_feed_response(feed, filename="calendar.ics"):
    """Return the iCal file."""
    response = HttpResponse(feed, content_type="text/calendar")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
