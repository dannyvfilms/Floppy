# FORK: tests for the user-settings API endpoints.
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch

from app.models import MediaTypes

from .base import FloppyApiTestCase


class PreferencesTests(FloppyApiTestCase):
    """GET/PATCH user/preferences."""

    def test_get_preferences_with_choices(self):
        """Current values and valid choices are returned."""
        response = self.call_api(
            "get",
            "api_user_preferences",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        payload = response.json()
        self.assertIn("rating_scale", payload["preferences"])
        self.assertIn("rating_scale", payload["choices"])

    def test_patch_choice_field(self):
        """A valid choice value is persisted."""
        choices = self.call_api(
            "get",
            "api_user_preferences",
            headers=self.auth_headers,
        ).json()["choices"]["rating_scale"]
        target = next(value for value in choices if value != self.user1.rating_scale)
        response = self.call_api(
            "patch",
            "api_user_preferences",
            payload={"rating_scale": target},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.user1.refresh_from_db()
        self.assertEqual(self.user1.rating_scale, target)
        self.assertIn("rating_scale", response.json()["updated_fields"])

    def test_patch_invalid_choice_rejected(self):
        """Values outside the model choices return 400."""
        response = self.call_api(
            "patch",
            "api_user_preferences",
            payload={"rating_scale": "0-1000"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_patch_boolean_field(self):
        """Boolean preferences are persisted with type checking."""
        response = self.call_api(
            "patch",
            "api_user_preferences",
            payload={"hide_zero_rating": True},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.user1.refresh_from_db()
        self.assertTrue(self.user1.hide_zero_rating)

        rejected = self.call_api(
            "patch",
            "api_user_preferences",
            payload={"hide_zero_rating": "yes"},
            headers=self.auth_headers,
        )
        self.assertEqual(rejected.status_code, HTTP.BAD_REQUEST)


class SidebarTests(FloppyApiTestCase):
    """GET/PUT user/sidebar."""

    def test_toggle_media_type(self):
        """A media type can be disabled and re-enabled."""
        response = self.call_api(
            "put",
            "api_user_sidebar",
            payload={"media_types": {MediaTypes.MOVIE.value: False}},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.user1.refresh_from_db()
        self.assertFalse(self.user1.movie_enabled)

        listed = self.call_api("get", "api_user_sidebar", headers=self.auth_headers)
        self.assertFalse(listed.json()["media_types"][MediaTypes.MOVIE.value])

    def test_unknown_media_type_rejected(self):
        """Unknown media types return 400."""
        response = self.call_api(
            "put",
            "api_user_sidebar",
            payload={"media_types": {"vinyl": True}},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)


class NotificationsTests(FloppyApiTestCase):
    """Notification settings, exclusions, and test send."""

    def test_patch_notification_settings(self):
        """Settings persist through the web form's validation."""
        response = self.call_api(
            "patch",
            "api_user_notifications",
            payload={"daily_digest_enabled": True},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.user1.refresh_from_db()
        self.assertTrue(self.user1.daily_digest_enabled)

    def test_exclusions_lifecycle(self):
        """Items can be excluded and re-included."""
        item = self.items_by_type[MediaTypes.MOVIE.value][0]
        excluded = self.call_api(
            "post",
            "api_user_notification_exclusions",
            payload={"item_id": item.id},
            headers=self.auth_headers,
        )
        self.assertEqual(excluded.status_code, HTTP.OK)

        listed = self.call_api(
            "get",
            "api_user_notification_exclusions",
            headers=self.auth_headers,
        )
        self.assertEqual(len(listed.json()["results"]), 1)

        removed = self.call_api(
            "delete",
            "api_user_notification_exclusions",
            payload={"item_id": item.id},
            headers=self.auth_headers,
        )
        self.assertEqual(removed.status_code, HTTP.OK)
        self.assertEqual(
            self.user1.notification_excluded_items.count(),
            0,
        )

    def test_notification_test_requires_urls(self):
        """Without configured URLs the test endpoint returns 400."""
        response = self.call_api(
            "post",
            "api_user_notification_test",
            payload={},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    @patch("api.fork_views_users.apprise.Apprise")
    def test_notification_test_sends(self, mock_apprise):
        """With URLs configured the apprise notify path runs."""
        self.user1.notification_urls = "json://localhost/webhook"
        self.user1.save(update_fields=["notification_urls"])
        mock_apprise.return_value.notify.return_value = True
        response = self.call_api(
            "post",
            "api_user_notification_test",
            payload={},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertTrue(response.json()["sent"])


class TokenRegenerateTests(FloppyApiTestCase):
    """POST user/token/regenerate."""

    def test_regenerate_rotates_token(self):
        """The new token is returned and the old credential stops working."""
        old_token = self.user1.token
        response = self.call_api(
            "post",
            "api_user_token_regenerate",
            payload={},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        new_token = response.json()["token"]
        self.assertNotEqual(new_token, old_token)

        stale = self.call_api(
            "get",
            "api_user_preferences",
            headers={"HTTP_X_API_KEY": old_token},
        )
        self.assertEqual(stale.status_code, HTTP.FORBIDDEN)

        fresh = self.call_api(
            "get",
            "api_user_preferences",
            headers={"HTTP_X_API_KEY": new_token},
        )
        self.assertEqual(fresh.status_code, HTTP.OK)
