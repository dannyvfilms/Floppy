# FORK: user-settings endpoints under /api/v1/user/ mirroring the web
# settings pages. URL wiring lives in fork_urls.py.
import logging
from http import HTTPStatus as HTTP  # noqa: N814

import apprise
from rest_framework import views as drf_views
from rest_framework.response import Response

from app import history_cache, statistics_cache
from app.models import Item
from users.forms import NotificationSettingsForm
from users.views import SIDEBAR_MEDIA_TYPES

logger = logging.getLogger(__name__)

# Preference fields whose values are validated against the User model
# field's own choices (same vocabulary the web preferences page uses).
_CHOICE_PREFERENCE_FIELDS = (
    "date_format",
    "time_format",
    "week_start_day",
    "activity_history_view",
    "duration_format",
    "game_logging_style",
    "mobile_grid_layout",
    "media_card_subtitle_display",
    "title_display_preference",
    "top_talent_sort_by",
    "rating_scale",
    "show_planned_on_home",
    "anime_library_mode",
    "quick_season_update_mobile",
    "session_duration",
)

_BOOLEAN_PREFERENCE_FIELDS = (
    "hide_completed_recommendations",
    "hide_zero_rating",
    "progress_bar",
    "book_comic_manga_progress_percentage",
    "auto_pause_in_progress_enabled",
    "obfuscate_episodes",
    "clickable_media_cards",
    "home_show_media_type_headers",
)

# Fields whose change requires the web view's statistics-cache refresh.
_STATS_SENSITIVE_FIELDS = {
    "rating_scale",
    "top_talent_sort_by",
    "week_start_day",
    "duration_format",
}


def _field_choices(user, field_name):
    field = user._meta.get_field(field_name)
    return [choice[0] for choice in (field.choices or [])]


def _serialize_preferences(user):
    payload = {}
    for field in _CHOICE_PREFERENCE_FIELDS + _BOOLEAN_PREFERENCE_FIELDS:
        payload[field] = getattr(user, field)
    return payload


# /api/v1/user/preferences/
class UserPreferencesView(drf_views.APIView):
    """Read or update user preferences (mirrors the web preferences page)."""

    def get(self, request):
        """Return the current preference values and valid choices."""
        choices = {
            field: _field_choices(request.user, field)
            for field in _CHOICE_PREFERENCE_FIELDS
        }
        return Response(
            {"preferences": _serialize_preferences(request.user), "choices": choices},
            status=HTTP.OK,
        )

    def patch(self, request):
        """Update the provided preference fields."""
        user = request.user
        if user.is_demo:
            return Response(
                {"detail": "This section is view-only for demo accounts."},
                status=HTTP.FORBIDDEN,
            )

        fields_to_update = []
        changed = set()
        for field in _CHOICE_PREFERENCE_FIELDS:
            if field not in request.data:
                continue
            value = request.data[field]
            valid = _field_choices(user, field)
            if value not in valid:
                return Response(
                    {"detail": f"Invalid value for {field}.", "choices": valid},
                    status=HTTP.BAD_REQUEST,
                )
            if getattr(user, field) != value:
                setattr(user, field, value)
                fields_to_update.append(field)
                changed.add(field)

        for field in _BOOLEAN_PREFERENCE_FIELDS:
            if field not in request.data:
                continue
            value = request.data[field]
            if not isinstance(value, bool):
                return Response(
                    {"detail": f"{field} must be a boolean."},
                    status=HTTP.BAD_REQUEST,
                )
            if getattr(user, field) != value:
                setattr(user, field, value)
                fields_to_update.append(field)
                changed.add(field)

        if fields_to_update:
            user.save(update_fields=fields_to_update)
            user.refresh_from_db()
            # Cache side effects mirrored from the web preferences view.
            if "game_logging_style" in changed:
                history_cache.invalidate_history_cache(user.id)
                history_cache.schedule_history_refresh(
                    user.id,
                    user.game_logging_style,
                    debounce_seconds=0,
                )
            if "rating_scale" in changed:
                history_cache.invalidate_history_cache(
                    user.id,
                    force=True,
                    logging_styles=("sessions", "repeats"),
                )
            if changed & _STATS_SENSITIVE_FIELDS:
                statistics_cache.invalidate_statistics_cache(user.id)
                statistics_cache.schedule_all_ranges_refresh(
                    user.id,
                    debounce_seconds=0,
                )

        return Response(
            {
                "preferences": _serialize_preferences(user),
                "updated_fields": sorted(fields_to_update),
            },
            status=HTTP.OK,
        )


# /api/v1/user/sidebar/
class UserSidebarView(drf_views.APIView):
    """Read or update media-type visibility (mirrors the sidebar page)."""

    def get(self, request):
        """Return the enabled state per media type."""
        return Response(
            {
                "media_types": {
                    media_type: getattr(
                        request.user,
                        f"{media_type}_enabled",
                        False,
                    )
                    for media_type in SIDEBAR_MEDIA_TYPES
                },
            },
            status=HTTP.OK,
        )

    def put(self, request):
        """Set the enabled state for the provided media types."""
        user = request.user
        if user.is_demo:
            return Response(
                {"detail": "This section is view-only for demo accounts."},
                status=HTTP.FORBIDDEN,
            )
        updates = request.data.get("media_types")
        if not isinstance(updates, dict):
            return Response(
                {"detail": "'media_types' must be an object of booleans."},
                status=HTTP.BAD_REQUEST,
            )
        fields_to_update = []
        for media_type, enabled in updates.items():
            if media_type not in SIDEBAR_MEDIA_TYPES:
                return Response(
                    {"detail": f"Unknown media type: {media_type}"},
                    status=HTTP.BAD_REQUEST,
                )
            if not isinstance(enabled, bool):
                return Response(
                    {"detail": f"{media_type} must map to a boolean."},
                    status=HTTP.BAD_REQUEST,
                )
            field = f"{media_type}_enabled"
            if getattr(user, field) != enabled:
                setattr(user, field, enabled)
                fields_to_update.append(field)
        if fields_to_update:
            user.save(update_fields=fields_to_update)
        return Response(
            {"updated_fields": sorted(fields_to_update)},
            status=HTTP.OK,
        )


# /api/v1/user/notifications/
class UserNotificationsView(drf_views.APIView):
    """Read or update notification settings (mirrors the web page)."""

    def get(self, request):
        """Return notification settings and excluded items."""
        return Response(
            {
                "notification_urls": request.user.notification_urls,
                "daily_digest_enabled": request.user.daily_digest_enabled,
                "release_notifications_enabled": (
                    request.user.release_notifications_enabled
                ),
            },
            status=HTTP.OK,
        )

    def patch(self, request):
        """Update notification settings via the web form's validation."""
        data = {
            "notification_urls": request.data.get(
                "notification_urls",
                request.user.notification_urls,
            ),
            "daily_digest_enabled": request.data.get(
                "daily_digest_enabled",
                request.user.daily_digest_enabled,
            ),
            "release_notifications_enabled": request.data.get(
                "release_notifications_enabled",
                request.user.release_notifications_enabled,
            ),
        }
        form = NotificationSettingsForm(data, instance=request.user)
        if not form.is_valid():
            return Response(
                {"detail": "Invalid notification settings.", "errors": form.errors},
                status=HTTP.BAD_REQUEST,
            )
        form.save()
        return Response(data, status=HTTP.OK)


# /api/v1/user/notifications/exclusions/
class UserNotificationExclusionsView(drf_views.APIView):
    """Manage the notification exclusion list."""

    def get(self, request):
        """Return excluded items."""
        return Response(
            {
                "results": [
                    {
                        "item_id": item.id,
                        "title": item.title,
                        "media_type": item.media_type,
                    }
                    for item in request.user.notification_excluded_items.all()
                ],
            },
            status=HTTP.OK,
        )

    def post(self, request):
        """Exclude an item from notifications."""
        item = Item.objects.filter(id=request.data.get("item_id")).first()
        if item is None:
            return Response({"detail": "Item not found."}, status=HTTP.NOT_FOUND)
        request.user.notification_excluded_items.add(item)
        return Response({"item_id": item.id, "excluded": True}, status=HTTP.OK)

    def delete(self, request):
        """Remove an item from the exclusion list."""
        item = Item.objects.filter(id=request.data.get("item_id")).first()
        if item is None:
            return Response({"detail": "Item not found."}, status=HTTP.NOT_FOUND)
        request.user.notification_excluded_items.remove(item)
        return Response({"item_id": item.id, "excluded": False}, status=HTTP.OK)


# /api/v1/user/notifications/test/
class UserNotificationTestView(drf_views.APIView):
    """Send a test notification (mirrors the web test_notification view)."""

    def post(self, request):
        """Send the test message to all configured Apprise URLs."""
        notification_urls = [
            url.strip()
            for url in request.user.notification_urls.splitlines()
            if url.strip()
        ]
        if not notification_urls:
            return Response(
                {"detail": "No notification URLs configured."},
                status=HTTP.BAD_REQUEST,
            )
        apobj = apprise.Apprise()
        for url in notification_urls:
            apobj.add(url)
        try:
            result = apobj.notify(
                title="Floppy Test Notification",
                body=(
                    "<p>This is a test notification from Floppy.</p>"
                    "<p>If you're seeing this, "
                    "your notifications are working correctly!</p>"
                ),
                body_format=apprise.NotifyFormat.HTML,
            )
        except Exception as e:
            return Response(
                {"detail": "Failed to send test notification.", "errors": str(e)},
                status=HTTP.BAD_GATEWAY,
            )
        if not result:
            return Response(
                {"detail": "Failed to send test notification."},
                status=HTTP.BAD_GATEWAY,
            )
        return Response({"sent": True}, status=HTTP.OK)


# /api/v1/user/token/regenerate/
class UserTokenRegenerateView(drf_views.APIView):
    """Rotate the user's API/webhook/calendar token.

    WARNING: the old token — including the credential used for this very
    request — stops working immediately, and webhook/iCal URLs built from
    it must be updated.
    """

    def post(self, request):
        """Regenerate and return the new token once."""
        request.user.regenerate_token()
        return Response({"token": request.user.token}, status=HTTP.OK)
