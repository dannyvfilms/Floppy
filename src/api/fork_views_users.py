# FORK: user-settings endpoints under /api/v1/user/ mirroring the web
# settings pages. URL wiring lives in fork_urls.py.
import json
import logging
from http import HTTPStatus as HTTP  # noqa: N814

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import views as drf_views
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response

from api.authentication import APIKeyAuthentication, BearerAuthentication
from app import cache_utils, history_cache, statistics_cache
from app.models import Item
from users.forms import NotificationSettingsForm
from users.models import PLAYBACK_WEBHOOK_SECRET_MAX_LENGTH
from users.views import SIDEBAR_MEDIA_TYPES

logger = logging.getLogger(__name__)

# Preference fields whose values are validated against the User model
# field's own choices (same vocabulary the web preferences page uses).
_CHOICE_PREFERENCE_FIELDS = (
    "date_format",
    "time_format",
    "currency",
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
    "theme",
    "logo_style",
    "ui_language",
)

_BOOLEAN_PREFERENCE_FIELDS = (
    "show_recommendations",
    "hide_completed_recommendations",
    "hide_zero_rating",
    "progress_bar",
    "book_comic_manga_progress_percentage",
    "auto_pause_in_progress_enabled",
    "obfuscate_episodes",
    "clickable_media_cards",
    "home_show_media_type_headers",
)

# Free-text preferences a client may write but that are not choices or booleans.
#
# Both belong to the outgoing playback webhook. They are here so a client can
# configure its own delivery — the iOS app enrols with its push relay and then
# writes the URL and secret the relay issued, rather than making the reader copy
# two generated strings into the web UI by hand.
_TEXT_PREFERENCE_FIELDS = (
    "playback_webhook_url",
    "playback_webhook_secret",
)

# Writable but never read back.
#
# A webhook URL can itself contain credentials in userinfo, path, or query.
# Neither it nor the signing secret should be disclosed to user:read clients.
_WRITE_ONLY_PREFERENCE_FIELDS = frozenset(
    {
        "playback_webhook_url",
        "playback_webhook_secret",
    }
)

# Longest value each text preference accepts. `playback_webhook_secret` is
# stored encrypted in an unbounded column, so its cap cannot be read off the
# model field the way the URL's can — the limit belongs to the plaintext the
# client sends, and matches the one the settings form enforces.
_TEXT_PREFERENCE_MAX_LENGTHS = {
    "playback_webhook_secret": PLAYBACK_WEBHOOK_SECRET_MAX_LENGTH,
}

# Only http(s) reaches an outbound webhook, and the value must be a URL at all.
# Without this the API would accept what the settings form rejects: a client
# could store "garbage", and every playback event from then on would queue a
# task that fails in the worker, where the client never sees it.
_validate_webhook_url = URLValidator(schemes=["http", "https"])

# Region and metadata language come from TMDB, not a model choices list, so the
# web preferences view validates them against the provider's own lists.
_TMDB_PREFERENCE_FIELDS = ("watch_provider_region", "metadata_language")


def tmdb_preference_choices():
    """Return the TMDB-backed option lists the web preferences page renders."""
    from django.conf import settings

    from app.providers import tmdb

    try:
        regions = [list(pair) for pair in tmdb.watch_provider_regions()]
    except Exception as exc:
        logger.warning("Could not load watch regions: %s", exc)
        regions = [["", "Disabled"]]
    try:
        languages = [list(pair) for pair in tmdb.metadata_languages()]
    except Exception as exc:
        logger.warning("Could not load languages: %s", exc)
        languages = [["", f"Server Default ({settings.TMDB_LANG})"]]
    return {"watch_provider_region": regions, "metadata_language": languages}


def _active_auto_pause_libraries(user):
    from users.views import AUTO_PAUSE_MEDIA_TYPES

    return [
        library
        for library in user.get_active_media_types()
        if library in AUTO_PAUSE_MEDIA_TYPES
    ]


# Fields whose change requires the web view's statistics-cache refresh.
_STATS_SENSITIVE_FIELDS = {
    "rating_scale",
    "top_talent_sort_by",
    "week_start_day",
    "duration_format",
}


def _field_choices(user, field_name):
    if field_name == "media_card_subtitle_display":
        from users.card_metadata import DISPLAY_CHOICES

        return list(DISPLAY_CHOICES)
    field = user._meta.get_field(field_name)
    return [choice[0] for choice in (field.choices or [])]


def _serialize_preferences(user):
    from users.card_metadata import OMIT, absorbed_preference_value

    payload = {
        "playback_webhook_configured": bool(user.playback_webhook_url.strip()),
        "watch_provider_region": user.watch_provider_region,
        "metadata_language": user.metadata_language,
        "auto_pause_rules": user.auto_pause_rules or [],
        "auto_pause_libraries": _active_auto_pause_libraries(user),
    }
    readable = (
        _CHOICE_PREFERENCE_FIELDS + _BOOLEAN_PREFERENCE_FIELDS + _TEXT_PREFERENCE_FIELDS
    )
    absorbed = {
        "media_card_subtitle_display",
        "progress_bar",
        "hide_zero_rating",
    }
    for field in readable:
        if field in _WRITE_ONLY_PREFERENCE_FIELDS:
            continue
        if field in absorbed:
            value = absorbed_preference_value(user, field)
            if value is OMIT:
                continue
            payload[field] = value
            continue
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
            {
                "preferences": _serialize_preferences(request.user),
                "choices": choices,
                # Superuser-only settings pages are hidden on the client from
                # this field and permission-checked again on the server.
                "is_superuser": bool(request.user.is_superuser),
            },
            status=HTTP.OK,
        )

    def patch(self, request):
        """Update only the preference fields present in the request body.

        Omitted fields keep their stored value. Clients that change one
        preference, such as the header theme toggle, therefore do not need to
        echo the rest of the form back.
        """
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
            if field == "media_card_subtitle_display":
                from users.card_metadata import apply_absorbed_preference

                apply_absorbed_preference(user, field, value)
                if "card_metadata" not in fields_to_update:
                    fields_to_update.append("card_metadata")
                changed.add(field)
                continue
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
            if field in {"progress_bar", "hide_zero_rating"}:
                from users.card_metadata import apply_absorbed_preference

                apply_absorbed_preference(user, field, value)
                if "card_metadata" not in fields_to_update:
                    fields_to_update.append("card_metadata")
                changed.add(field)
                continue
            if getattr(user, field) != value:
                setattr(user, field, value)
                fields_to_update.append(field)
                changed.add(field)

        for field in _TEXT_PREFERENCE_FIELDS:
            if field not in request.data:
                continue
            value = request.data[field]
            # `None` clears it, which is how a client turns the webhook off
            # without having to send an empty string.
            if value is None:
                value = ""
            if not isinstance(value, str):
                return Response(
                    {"detail": f"{field} must be a string."},
                    status=HTTP.BAD_REQUEST,
                )
            value = value.strip()
            max_length = _TEXT_PREFERENCE_MAX_LENGTHS.get(
                field,
                user._meta.get_field(field).max_length,
            )
            if max_length and len(value) > max_length:
                return Response(
                    {"detail": f"{field} is too long."},
                    status=HTTP.BAD_REQUEST,
                )
            if field == "playback_webhook_url" and value:
                try:
                    _validate_webhook_url(value)
                except ValidationError:
                    return Response(
                        {"detail": f"{field} must be an http(s) URL."},
                        status=HTTP.BAD_REQUEST,
                    )
            if field == "playback_webhook_secret":
                # Stored encrypted, so a plaintext comparison against the column
                # would always differ and rewrite the row on every PATCH. Compare
                # against what the column decrypts to instead.
                if user.get_playback_webhook_secret() == value:
                    continue
                user.set_playback_webhook_secret(value)
                fields_to_update.append(field)
                changed.add(field)
                continue
            if getattr(user, field) != value:
                setattr(user, field, value)
                fields_to_update.append(field)
                changed.add(field)

        error = self._patch_provider_fields(request, fields_to_update, changed)
        if error is not None:
            return error

        if fields_to_update:
            user.save(update_fields=fields_to_update)
            user.refresh_from_db()
            if "metadata_language" in changed:
                from app.tasks_metadata_language import (
                    reset_metadata_language_repair,
                )

                reset_metadata_language_repair(user.pk)
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

    @staticmethod
    def _patch_provider_fields(request, fields_to_update, changed):
        """Apply region, metadata language and auto-pause rules, as the web does."""
        user = request.user
        data = request.data
        for field in _TMDB_PREFERENCE_FIELDS:
            if field not in data:
                continue
            value = data[field]
            valid = {code for code, _label in tmdb_preference_choices()[field]}
            if not isinstance(value, str) or (
                value not in valid and field == "watch_provider_region"
            ):
                return Response(
                    {"detail": f"Invalid value for {field}."},
                    status=HTTP.BAD_REQUEST,
                )
            if field == "metadata_language" and value not in valid:
                value = ""
            if getattr(user, field) != value:
                setattr(user, field, value)
                fields_to_update.append(field)
                changed.add(field)
        if "auto_pause_rules" in data:
            from users.views import _normalize_auto_pause_rules

            rules = data["auto_pause_rules"]
            if not isinstance(rules, list):
                return Response(
                    {"detail": "auto_pause_rules must be a list."},
                    status=HTTP.BAD_REQUEST,
                )
            normalized = _normalize_auto_pause_rules(
                json.dumps(rules), _active_auto_pause_libraries(user)
            )
            if user.auto_pause_rules != normalized:
                user.auto_pause_rules = normalized
                fields_to_update.append("auto_pause_rules")
                changed.add("auto_pause_rules")
        return None


# /api/v1/user/navigation/
class UserNavigationView(drf_views.APIView):
    """The signed-in sidebar as data, for the native app.

    Reads the same builder the web sidebar template uses, so labels, order,
    icons and saved views cannot drift between surfaces.
    """

    authentication_classes = (
        BearerAuthentication,
        APIKeyAuthentication,
        SessionAuthentication,
    )

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Return the sidebar model without the CSRF token."""
        from app.sidebar_model import sidebar_model

        model = sidebar_model(request, request.user, None)
        model.pop("csrfToken", None)
        model["lastSearchType"] = (
            getattr(request.user, "last_search_type", None) or "all"
        )
        return Response(model, status=HTTP.OK)


# /api/v1/user/sidebar/
class UserSidebarView(drf_views.APIView):
    """Read or update media-type visibility (mirrors the sidebar page)."""

    def get(self, request):
        """Return the enabled state, order and labels per media type."""
        from app.icon_specs import file_icon, type_icon
        from app.templatetags.app_tags import media_type_readable_plural

        preferred = [
            media_type
            for media_type in (request.user.sidebar_media_type_order or [])
            if media_type in SIDEBAR_MEDIA_TYPES
        ]
        order = preferred + [
            media_type for media_type in SIDEBAR_MEDIA_TYPES if media_type not in preferred
        ]
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
                "order": order,
                "labels": {
                    media_type: str(media_type_readable_plural(media_type))
                    for media_type in SIDEBAR_MEDIA_TYPES
                },
                "icons": {
                    media_type: type_icon(media_type)
                    for media_type in SIDEBAR_MEDIA_TYPES
                },
                "discover_icon": file_icon("four-square"),
                "show_discover": request.user.show_discover,
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
        order = request.data.get("order")
        show_discover = request.data.get("show_discover")
        if order is not None and (
            not isinstance(order, list)
            or any(media_type not in SIDEBAR_MEDIA_TYPES for media_type in order)
        ):
            return Response(
                {"detail": "'order' must be a list of known media types."},
                status=HTTP.BAD_REQUEST,
            )
        if show_discover is not None and not isinstance(show_discover, bool):
            return Response(
                {"detail": "'show_discover' must be a boolean."},
                status=HTTP.BAD_REQUEST,
            )
        fields_to_update = []
        if show_discover is not None and user.show_discover != show_discover:
            user.show_discover = show_discover
            fields_to_update.append("show_discover")
        if order is not None:
            normalized = list(dict.fromkeys(order))
            normalized += [m for m in SIDEBAR_MEDIA_TYPES if m not in normalized]
            if user.sidebar_media_type_order != normalized:
                user.sidebar_media_type_order = normalized
                fields_to_update.append("sidebar_media_type_order")
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
            # Mixed Home rows depend on which media types are enabled.
            cache_utils.clear_home_row_cache_for_user(user.id)
        return Response(
            {"updated_fields": sorted(fields_to_update)},
            status=HTTP.OK,
        )


# /api/v1/user/notifications/
class UserNotificationsView(drf_views.APIView):
    """Read or update settings; credential-bearing notification URLs are write-only."""

    def get(self, request):
        """Return notification settings and excluded items."""
        return Response(
            {
                "notification_urls_configured": bool(
                    request.user.notification_urls.strip()
                ),
                "daily_digest_enabled": request.user.daily_digest_enabled,
                "release_notifications_enabled": (
                    request.user.release_notifications_enabled
                ),
                "premiere_notifications_enabled": (
                    request.user.premiere_notifications_enabled
                ),
                "playback_webhook_configured": bool(
                    request.user.playback_webhook_url.strip()
                ),
            },
            status=HTTP.OK,
        )

    def patch(self, request):
        """Update notification settings via the web form's validation.

        The form declares every notification field, and a ModelForm resets a
        field the data omits. Each omitted field therefore falls back to the
        stored value, so a partial PATCH never clears the premiere toggle or
        the playback webhook.
        """
        user = request.user
        if user.is_demo:
            # The web form is guarded by DemoAccountGuardMiddleware.
            return Response(
                {"detail": "This section is view-only for demo accounts."},
                status=HTTP.FORBIDDEN,
            )
        data = {
            field: request.data.get(field, getattr(user, field))
            for field in (
                "notification_urls",
                "daily_digest_enabled",
                "release_notifications_enabled",
                "premiere_notifications_enabled",
                "playback_webhook_url",
            )
        }
        # Blank keeps the stored secret (see the form's clean method).
        data["playback_webhook_secret"] = request.data.get(
            "playback_webhook_secret", ""
        )
        form = NotificationSettingsForm(data, instance=user)
        if not form.is_valid():
            errors = dict(form.errors)
            if "notification_urls" in errors:
                # The web form quotes the URL, which may be a stored secret.
                errors["notification_urls"] = ["Invalid notification URL."]
            return Response(
                {"detail": "Invalid notification settings.", "errors": errors},
                status=HTTP.BAD_REQUEST,
            )
        form.save()
        return self.get(request)


# /api/v1/user/notifications/exclusions/
class UserNotificationExclusionsView(drf_views.APIView):
    """Manage the notification exclusion list."""

    def get(self, request):
        """Return excluded items."""
        from app.templatetags.app_tags import image_url, media_type_readable

        return Response(
            {
                "results": [
                    {
                        "item_id": item.id,
                        "title": item.title,
                        "media_type": item.media_type,
                        "media_type_label": media_type_readable(item.media_type),
                        "image": image_url(item.image),
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
        # Imported here, not at module scope: apprise loads its whole notification
        # provider tree, which the web process must not pay for at startup.
        import apprise

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
        if request.user.is_demo:
            return Response(
                {"detail": "This section is view-only for demo accounts."},
                status=HTTP.FORBIDDEN,
            )
        request.user.regenerate_token()
        return Response({"token": request.user.token}, status=HTTP.OK)
