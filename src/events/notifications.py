import logging
from dataclasses import dataclass
from datetime import UTC
from html import escape

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db.models import Max, Q
from django.utils import timezone

from app.models import TV, MediaTypes, Season
from app.templatetags import app_tags
from events.models import INACTIVE_TRACKING_STATUSES, Event

logger = logging.getLogger(__name__)

BATCH_COLLAPSE_THRESHOLD = 3


@dataclass
class BatchEvent:
    """A run of >= BATCH_COLLAPSE_THRESHOLD episode events for one item."""

    first_event: Event
    min_ep: int
    max_ep: int
    is_finale: bool

    @property
    def range_label(self):
        """Return the human-readable episode range for this batch."""
        prefix = "All Episodes" if self.min_ep == 1 else "Episodes"
        return f"{prefix} {self.min_ep}-{self.max_ep}"


def send_releases():
    """Send notifications for recently released media."""
    now = timezone.now()
    thirty_minutes_ago = now - timezone.timedelta(minutes=30)

    # Get users who should receive notifications
    users = (
        get_user_model()
        .objects.filter(
            ~Q(notification_urls=""),
            release_notifications_enabled=True,
        )
        .prefetch_related("notification_excluded_items")
    )

    if not users.exists():
        return "No users with release notifications enabled"

    # Find events that were released recently and haven't been notified yet
    base_queryset = Event.objects.filter(
        datetime__gte=thirty_minutes_ago,
        datetime__lte=now,
        notification_sent=False,
    ).select_related("item")

    events = Event.objects.sort_with_sentinel_last(base_queryset)

    if not events.exists():
        return "No recent releases found"

    result = send_notifications(
        events=events,
        users=users,
        title="🔔 Floppy: New Releases Available! 🔔",
    )

    # Mark events as notified
    if result["event_ids"]:
        Event.objects.filter(id__in=result["event_ids"]).update(
            notification_sent=True,
        )
        logger.info("Marked %s events as notified", len(result["event_ids"]))

    failed_deliveries = result.get("failed_deliveries", {})
    record_failed_alerts(failed_deliveries)

    return f"{result['event_count']} recent releases processed" + describe_failures(
        failed_deliveries,
    )


def send_daily_digest():
    """Send daily digest of today's releases to users."""
    # Get current date in the timezone defined in settings
    now_in_current_tz = timezone.localtime()

    # Create start and end of today in the current timezone
    today_start = now_in_current_tz.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    today_end = today_start + timezone.timedelta(days=1)

    # Convert back to UTC for database query
    today_start_utc = today_start.astimezone(UTC)
    today_end_utc = today_end.astimezone(UTC)

    # Get users who have enabled daily digest
    users = (
        get_user_model()
        .objects.filter(
            ~Q(notification_urls=""),
            daily_digest_enabled=True,
        )
        .prefetch_related("notification_excluded_items")
    )

    if not users.exists():
        return "No users with daily digest enabled"

    # Get today's events using the converted UTC times
    base_queryset = Event.objects.filter(
        datetime__gte=today_start_utc,
        datetime__lt=today_end_utc,
    ).select_related("item")

    events = Event.objects.sort_with_sentinel_last(base_queryset)

    if not events.exists():
        return "No releases scheduled for today"

    title = "📆 Floppy: Today's Releases 📆"

    result = send_notifications(
        events=events,
        users=users,
        title=title,
        skip_alerted_for_instant_users=True,
    )

    return f"Daily digest sent for {result['event_count']} releases" + (
        describe_failures(result.get("failed_deliveries", {}))
    )


def describe_failures(failed_deliveries):
    """Return a task-result suffix naming how many users could not be reached."""
    if not failed_deliveries:
        return ""
    return f" (delivery failed for {len(failed_deliveries)} user(s))"


def record_failed_alerts(failed_deliveries):
    """Remember which users a real-time alert did not reach, per event."""
    through = Event.alert_failed_users.through
    through.objects.bulk_create(
        [
            through(event_id=event_id, user_id=user_id)
            for user_id, event_ids in failed_deliveries.items()
            for event_id in event_ids
        ],
        ignore_conflicts=True,
    )


def send_premiere_digest():
    """Send weekly digest of new show and season premieres."""
    # Rolling 7-day window starting at local midnight today
    now_in_current_tz = timezone.localtime()
    today_start = now_in_current_tz.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    week_end = today_start + timezone.timedelta(days=7)

    today_start_utc = today_start.astimezone(UTC)
    week_end_utc = week_end.astimezone(UTC)

    users = (
        get_user_model()
        .objects.filter(
            ~Q(notification_urls=""),
            premiere_notifications_enabled=True,
        )
        .prefetch_related("notification_excluded_items")
    )

    if not users.exists():
        return "No users with premiere notifications enabled"

    # A season's first episode (content_number=1) marks its premiere
    base_queryset = Event.objects.filter(
        item__media_type=MediaTypes.SEASON.value,
        content_number=1,
        datetime__gte=today_start_utc,
        datetime__lt=week_end_utc,
    ).select_related("item")

    events = Event.objects.sort_with_sentinel_last(base_queryset)

    if not events.exists():
        return "No premieres scheduled this week"

    result = send_notifications(
        events=events,
        users=users,
        title="🎬 Floppy: Premieres This Week 🎬",
        formatter=format_premiere_notification_html,
    )

    return f"Premiere digest sent for {result['event_count']} premieres"


def send_notifications(
    events,
    users,
    title,
    formatter=None,
    skip_alerted_for_instant_users=False,
):
    """Process events and send notifications to appropriate users.

    Args:
        events: QuerySet of Event objects
        users: QuerySet of User objects
        title: Notification title
        formatter: Callable(releases) -> HTML body. Defaults to
            format_notification_html.
        skip_alerted_for_instant_users: Leave out events already announced by
            send_releases() for users who have release notifications on.

    Returns:
        Dictionary with results information. failed_deliveries maps each user
        id whose notification could not be sent to that user's event ids.
    """
    event_count = events.count()
    logger.info(
        "Found %s users with this type of notifications enabled",
        users.count(),
    )
    logger.info("Found %s events for notification", event_count)

    events = annotate_finale_events(events)

    # Create event lookup for quick access
    events_by_item_and_content = {}
    event_ids = []

    for event in events:
        key = (event.item.id, event.content_number)
        events_by_item_and_content[key] = event
        event_ids.append(event.id)

    user_releases = get_user_releases(
        users=users,
        target_events=events_by_item_and_content,
        skip_alerted_for_instant_users=skip_alerted_for_instant_users,
    )

    failed_user_ids = deliver_notifications(
        user_releases,
        users,
        title,
        formatter=formatter,
    )

    return {
        "event_count": event_count,
        "event_ids": event_ids,
        "failed_deliveries": {
            user_id: [event.id for event in user_releases[user_id]]
            for user_id in failed_user_ids
        },
    }


def get_user_releases(users, target_events, skip_alerted_for_instant_users=False):
    """Get user releases with optimized queries that avoid N+1 problems.

    notification_sent is global, so it only counts as "already alerted" for
    users who receive release notifications, and only when their alert did not
    fail; everyone else still sees the event.
    """
    failed_alerts = set()
    if skip_alerted_for_instant_users:
        failed_alerts = set(
            Event.alert_failed_users.through.objects.filter(
                event_id__in=[event.id for event in target_events.values()],
            ).values_list("user_id", "event_id"),
        )

    user_exclusions = {}
    for user in users:
        user_exclusions[user.id] = set(
            user.notification_excluded_items.values_list("id", flat=True),
        )

    user_enabled_types = {}
    for user in users:
        enabled_types = user.get_active_media_types()
        # Episode events use the season media type, but TV Seasons is only a
        # display setting: enabling TV Series is enough (same rule as the calendar).
        if (
            MediaTypes.TV.value in enabled_types
            and MediaTypes.SEASON.value not in enabled_types
        ):
            enabled_types = [*enabled_types, MediaTypes.SEASON.value]
        user_enabled_types[user.id] = enabled_types

    user_tracking_data = get_all_user_tracking_data(
        users,
        target_events,
        user_exclusions,
    )
    user_releases = {}
    for user in users:
        user_events = []
        enabled_types = user_enabled_types[user.id]
        excluded_items = user_exclusions.get(user.id, set())
        hidden_item_ids = Event.objects.hidden_duplicate_item_ids(
            user,
            enabled_types,
        )

        skip_alerted = (
            skip_alerted_for_instant_users and user.release_notifications_enabled
        )

        for event in target_events.values():
            if (
                skip_alerted
                and event.notification_sent
                and (user.id, event.id) not in failed_alerts
            ):
                continue

            # Digital and physical dates only apply to the user's own region
            if event.release_type and event.region != user.watch_provider_region:
                continue

            # Check if a preferred cross-provider/cross-bucket duplicate exists
            if event.item.id in hidden_item_ids:
                continue

            # Check if user has excluded this item
            if event.item.media_type != Season and event.item.id in excluded_items:
                continue

            # Check if user is tracking this media type
            if event.item.media_type not in enabled_types:
                continue

            # Check if user is tracking this item
            if is_user_tracking_item(
                user,
                event.item,
                user_tracking_data,
            ):
                user_events.append(event)

        if user_events:
            user_releases[user.id] = user_events

    return user_releases


def annotate_finale_events(events):
    """Annotate regular season events whose episode is the highest known one."""
    events = list(events)
    unannotated_events = [
        event for event in events if not hasattr(event, "_is_season_finale")
    ]
    if not unannotated_events:
        return events

    season_item_ids = {
        event.item_id
        for event in unannotated_events
        if event.item.media_type == MediaTypes.SEASON.value
        and event.item.season_number
        and event.item.season_number > 0
        and event.content_number is not None
    }
    final_episode_by_item = dict(
        Event.objects.filter(
            item_id__in=season_item_ids,
            content_number__isnull=False,
        )
        .values("item_id")
        .annotate(final_episode=Max("content_number"))
        .values_list("item_id", "final_episode"),
    )

    for event in unannotated_events:
        event._is_season_finale = (
            event.item_id in final_episode_by_item
            and event.content_number == final_episode_by_item[event.item_id]
        )

    return events


def get_all_user_tracking_data(users, target_events, user_exclusions):
    """Get all user tracking data for the specified users and events."""
    user_ids = [user.id for user in users]

    # Group items by media type
    items_by_type = {}
    season_items = []
    for event in target_events.values():
        media_type = event.item.media_type

        if media_type == MediaTypes.SEASON.value:
            season_items.append(event.item)
            continue

        if media_type not in items_by_type:
            items_by_type[media_type] = []

        items_by_type[media_type].append(event.item.id)

    # Pre-fetch all tracking data for each media type
    tracking_data = {}

    for media_type, item_ids_for_type in items_by_type.items():
        media_model = apps.get_model(
            app_label="app",
            model_name=media_type.capitalize(),
        )

        # Get all user-item combinations for this media type
        media_objects = media_model.objects.filter(
            user_id__in=user_ids,
            item_id__in=item_ids_for_type,
        ).select_related("item")

        # Store in lookup format: (user_id, item_id) -> media_object
        for media_obj in media_objects:
            key = (media_obj.user_id, media_obj.item_id)
            tracking_data[key] = media_obj

    # Handle TV seasons separately
    tv_tracking_data = get_tv_tracking_data(users, season_items, user_exclusions)
    tracking_data.update(tv_tracking_data)

    return tracking_data


def get_tv_tracking_data(users, season_items, user_exclusions):
    """Get tracking data for TV shows and seasons."""
    user_ids = [user.id for user in users]

    if not season_items:
        return {}

    media_ids = list({item.media_id for item in season_items})

    # Pre-fetch all TV shows and seasons
    tv_lookup, season_lookup = build_tv_lookups(
        user_ids,
        media_ids,
        user_exclusions,
    )

    return determine_season_tracking_status(
        season_items,
        user_ids,
        tv_lookup,
        season_lookup,
    )


def build_tv_lookups(user_ids, media_ids, user_exclusions):
    """Build lookup structures for TV shows and seasons."""
    tv_shows = TV.objects.filter(
        user_id__in=user_ids,
        item__media_id__in=media_ids,
    ).select_related("item")

    seasons = Season.objects.filter(
        user_id__in=user_ids,
        item__media_id__in=media_ids,
    ).select_related("item")

    tv_lookup = {}  # (user_id, media_id) -> TV object
    season_lookup = {}  # (user_id, media_id) -> list of Season objects

    # Build TV lookup
    for tv in tv_shows:
        if tv.item.id not in user_exclusions.get(tv.user.id, set()):
            key = (tv.user_id, tv.item.media_id)
            tv_lookup[key] = tv

    # Build season lookup
    for season in seasons:
        if season.item.id not in user_exclusions.get(season.user.id, set()):
            key = (season.user_id, season.item.media_id)
            if key not in season_lookup:
                season_lookup[key] = []
            season_lookup[key].append(season)

    return tv_lookup, season_lookup


def determine_season_tracking_status(season_items, user_ids, tv_lookup, season_lookup):
    """Determine tracking status for each season item."""
    tracking_data = {}

    for season_item in season_items:
        for user_id in user_ids:
            is_tracking = check_user_season_tracking(
                user_id,
                season_item,
                tv_lookup,
                season_lookup,
            )

            if is_tracking is not None:
                item_key = (user_id, season_item.id)
                tracking_data[item_key] = is_tracking

    return tracking_data


def check_user_season_tracking(user_id, season_item, tv_lookup, season_lookup):
    """Check if a user is tracking a specific season.

    Returns:
        bool: True if tracking, False if not tracking, None if no TV show found
    """
    tv_key = (user_id, season_item.media_id)
    season_key = (user_id, season_item.media_id)

    # Check if user has the TV show and it's active
    tv_show = tv_lookup.get(tv_key)
    if not tv_show or tv_show.status in INACTIVE_TRACKING_STATUSES:
        return None

    # Check for dropped seasons
    user_seasons = season_lookup.get(season_key, [])
    dropped_seasons = [
        s
        for s in user_seasons
        if s.status in INACTIVE_TRACKING_STATUSES
        and s.item.season_number <= season_item.season_number
    ]

    if dropped_seasons:
        first_dropped = min(dropped_seasons, key=lambda s: s.item.season_number)
        return season_item.season_number < first_dropped.item.season_number

    return True


def is_user_tracking_item(user, item, user_tracking_data):
    """Check if user is tracking item using pre-fetched data."""
    media_type = item.media_type

    # Handle TV seasons
    if media_type == MediaTypes.SEASON.value:
        key = (user.id, item.id)
        return user_tracking_data.get(key, False)

    key = (user.id, item.id)
    media_obj = user_tracking_data.get(key)

    if not media_obj:
        return False

    return media_obj.status not in INACTIVE_TRACKING_STATUSES


def deliver_notifications(user_releases, users, title, formatter=None):
    """Deliver notifications to users using calendar logic.

    Args:
        user_releases: Dictionary mapping user IDs to lists of events
        users: QuerySet of User objects
        title: Notification title
        formatter: Callable(releases) -> HTML body. Defaults to
            format_notification_html.

    Returns:
        List of user ids whose notification could not be sent.
    """
    # Imported here, not at module scope: apprise loads its whole notification
    # plugin registry on import, and that cost lands in every long-lived
    # process that merely imports this module.
    import apprise

    if formatter is None:
        formatter = format_notification_html

    failed_user_ids = []

    # Create user lookup
    users_by_id = {user.id: user for user in users}

    for user_id, releases in user_releases.items():
        if not releases:
            continue

        user = users_by_id.get(user_id)
        if not user:
            logger.error("User %s not found", user_id)
            continue

        # Get notification URLs for this user
        urls = [
            url.strip() for url in user.notification_urls.splitlines() if url.strip()
        ]
        if not urls:
            continue

        # Format notification as HTML for richer email output
        notification_body = formatter(releases=releases)

        # Send notification
        sent = send_user_notification(
            user,
            urls,
            title,
            notification_body,
            body_format=apprise.NotifyFormat.HTML,
        )
        if not sent:
            failed_user_ids.append(user_id)

    return failed_user_ids


def group_releases_by_type(releases):
    """Group events by media type while preserving release ordering."""
    releases_by_type = {}
    for event in releases:
        media_type = event.item.media_type
        if media_type not in releases_by_type:
            releases_by_type[media_type] = []
        releases_by_type[media_type].append(event)
    return releases_by_type


def collapse_batch_events(media_events):
    """Group events by item, collapsing runs of >= BATCH_COLLAPSE_THRESHOLD.

    Args:
        media_events: List of Event objects for a single media type

    Returns:
        List of Event and BatchEvent objects, in first-seen order
    """
    by_item = {}
    for event in media_events:
        by_item.setdefault(event.item_id, []).append(event)

    units = []
    for group in by_item.values():
        if len(group) < BATCH_COLLAPSE_THRESHOLD:
            units.extend(group)
            continue

        group.sort(key=lambda e: e.content_number or 0)
        episode_numbers = [e.content_number for e in group if e.content_number is not None]
        units.append(
            BatchEvent(
                first_event=group[0],
                min_ep=min(episode_numbers),
                max_ep=max(episode_numbers),
                is_finale=any(getattr(e, "_is_season_finale", False) for e in group),
            ),
        )

    return units


def format_notification(releases):
    """Format notification text for releases.

    Args:
        releases: List of Event objects to include in the notification

    Returns:
        Formatted notification text as a string
    """
    releases = annotate_finale_events(releases)

    # Group releases by media type
    releases_by_type = group_releases_by_type(releases)

    # Format the notification body
    notification_body = []

    notification_body.append("--------------------------------------------")

    # Add releases grouped by media type
    for media_type, media_events in releases_by_type.items():
        icon = app_tags.unicode_icon(media_type)

        # Add a header for each media type with icon
        if media_type == MediaTypes.SEASON.value:
            notification_body.append(f"{icon}  TV Shows")
        else:
            notification_body.append(f"{icon}  {media_type.upper()}")

        for unit in collapse_batch_events(media_events):
            if isinstance(unit, BatchEvent):
                first_event = unit.first_event
                line = f"  • {first_event.item} ({unit.range_label})"
                is_finale = unit.is_finale
            else:
                line = f"  • {unit}"
                first_event = unit
                is_finale = unit._is_season_finale

            if not first_event.is_sentinel_time:
                # Convert to local timezone and format
                local_dt = timezone.localtime(first_event.datetime)
                time_str = local_dt.strftime("%H:%M")
                line += f" ({time_str})"

            if is_finale:
                line += " * Season Finale"
            notification_body.append(line)

        # Add a blank line between media types
        notification_body.append("")

    notification_body.append("Enjoy your media!")

    return "\n".join(notification_body)


def format_notification_html(releases):
    """Format notification HTML for releases."""
    releases = annotate_finale_events(releases)
    releases_by_type = group_releases_by_type(releases)
    notification_html = ["<div>"]

    for media_type, media_events in releases_by_type.items():
        icon = app_tags.unicode_icon(media_type)

        if media_type == MediaTypes.SEASON.value:
            heading = "TV Shows"
        else:
            heading = media_type.upper()

        notification_html.append(
            f"<p><strong>{escape(icon)} {escape(heading)}</strong></p><ul>",
        )

        for unit in collapse_batch_events(media_events):
            if isinstance(unit, BatchEvent):
                first_event = unit.first_event
                label = f"{first_event.item} ({unit.range_label})"
                is_finale = unit.is_finale
            else:
                label = str(unit)
                first_event = unit
                is_finale = unit._is_season_finale

            if first_event.is_sentinel_time:
                line = escape(label)
            else:
                local_dt = timezone.localtime(first_event.datetime)
                time_str = local_dt.strftime("%H:%M")
                line = f"{escape(label)} ({time_str})"
            if is_finale:
                line += ' <span style="color: #dc2626;">* Season Finale</span>'
            notification_html.append(f"<li>{line}</li>")

        notification_html.append("</ul>")

    notification_html.append("<p>Enjoy your media!</p></div>")
    return "".join(notification_html)


def format_premiere_notification_html(releases):
    """Format premiere digest HTML, grouping new shows vs new seasons."""
    new_shows = [event for event in releases if event.item.season_number == 1]
    new_seasons = [event for event in releases if event.item.season_number != 1]

    notification_html = ["<div>"]

    for heading, events in (
        ("🎬 New Shows", new_shows),
        ("🆕 New Seasons", new_seasons),
    ):
        if not events:
            continue

        notification_html.append(f"<p><strong>{escape(heading)}</strong></p><ul>")
        for event in events:
            if event.is_sentinel_time:
                line = escape(str(event.item))
            else:
                local_dt = timezone.localtime(event.datetime)
                date_str = local_dt.strftime("%a, %b %d")
                line = f"{escape(str(event.item))} ({date_str})"
            notification_html.append(f"<li>{line}</li>")
        notification_html.append("</ul>")

    notification_html.append("<p>Enjoy your media!</p></div>")
    return "".join(notification_html)


def send_user_notification(
    user,
    urls,
    title,
    body,
    body_format=None,
):
    """Send a notification to a specific user.

    Args:
        user: User object
        urls: List of notification URLs
        title: Notification title
        body: Notification body
        body_format: Apprise body format. Defaults to plain text.

    Returns:
        True if Apprise reported the notification as sent, False otherwise.
    """
    # Imported here, not at module scope: apprise loads its whole notification
    # plugin registry on import, and that cost lands in every long-lived
    # process that merely imports this module.
    import apprise

    if body_format is None:
        body_format = apprise.NotifyFormat.TEXT

    apobj = apprise.Apprise()
    for url in urls:
        apobj.add(url)

    try:
        result = apobj.notify(
            title=title,
            body=body,
            body_format=body_format,
        )

        if result:
            logger.info(
                "Notification sent to %s",
                user.username,
            )
            return True
        logger.error(
            "Failed to send notification to %s",
            user.username,
        )
    except Exception:
        logger.exception("Error sending notification to %s", user.username)

    return False
