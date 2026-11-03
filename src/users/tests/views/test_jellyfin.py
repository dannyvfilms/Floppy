from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from integrations.webhooks.jellyfin import (
    JELLYFIN_TEMPLATE_OUTDATED_KEY,
    JellyfinWebhookProcessor,
)


class JellyfinWebhookEventsUpdateTests(TestCase):
    """Tests for Jellyfin webhook event opt-in settings."""

    def setUp(self):
        """Create user for the tests."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    def test_update_jellyfin_webhook_events_enable_both(self):
        """Test enabling both MarkPlayed and MarkUnplayed processing."""
        response = self.client.post(
            reverse("update_jellyfin_webhook_events"),
            {
                "jellyfin_mark_played_enabled": "on",
                "jellyfin_mark_unplayed_enabled": "on",
            },
        )

        self.assertRedirects(response, reverse("provider_detail", args=["jellyfin"]) + "?tab=tracking")
        self.user.refresh_from_db()
        self.assertTrue(self.user.jellyfin_mark_played_enabled)
        self.assertTrue(self.user.jellyfin_mark_unplayed_enabled)

        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertIn("updated successfully", str(messages[0]))

    def test_update_jellyfin_webhook_events_disable_both(self):
        """Test omitted checkboxes disable both settings."""
        self.user.jellyfin_mark_played_enabled = True
        self.user.jellyfin_mark_unplayed_enabled = True
        self.user.save()

        self.client.post(reverse("update_jellyfin_webhook_events"), {})

        self.user.refresh_from_db()
        self.assertFalse(self.user.jellyfin_mark_played_enabled)
        self.assertFalse(self.user.jellyfin_mark_unplayed_enabled)

    def test_update_jellyfin_webhook_events_only_mark_played(self):
        """Test only MarkPlayed can be enabled independently."""
        self.client.post(
            reverse("update_jellyfin_webhook_events"),
            {"jellyfin_mark_played_enabled": "on"},
        )

        self.user.refresh_from_db()
        self.assertTrue(self.user.jellyfin_mark_played_enabled)
        self.assertFalse(self.user.jellyfin_mark_unplayed_enabled)


class JellyfinTemplateOutdatedNoticeTests(TestCase):
    """The Integrations page tells old-template users to re-copy it (#1250)."""

    def setUp(self):
        """Create and log in a user."""
        self.credentials = {"username": "notice", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)
        self.key = JELLYFIN_TEMPLATE_OUTDATED_KEY.format(user_id=self.user.id)
        cache.delete(self.key)

    def tearDown(self):
        """Drop the flag so it cannot leak into other tests."""
        cache.delete(self.key)

    def test_notice_hidden_by_default(self):
        """No old-template traffic means no notice."""
        response = self.client.get(
            reverse("provider_detail", args=["jellyfin"]) + "?tab=connection"
        )
        self.assertNotContains(response, 'data-testid="jellyfin-template-outdated"')
        tracking = self.client.get(
            reverse("provider_detail", args=["jellyfin"]) + "?tab=tracking"
        )
        self.assertContains(tracking, "Manual Watched Changes")

    def test_notice_shown_after_old_template_event(self):
        """An old-template UserDataSaved shows the re-copy notice."""
        JellyfinWebhookProcessor().process_payload(
            {
                "Event": "UserDataSaved",
                "Item": {"Type": "Movie", "UserData": {"Played": True}},
            },
            self.user,
        )
        response = self.client.get(
            reverse("provider_detail", args=["jellyfin"]) + "?tab=connection"
        )
        self.assertContains(response, 'data-testid="jellyfin-template-outdated"')

    def test_current_template_event_clears_notice(self):
        """A UserDataSaved with SaveReason clears the notice."""
        cache.set(self.key, True)
        JellyfinWebhookProcessor().process_payload(
            {
                "Event": "UserDataSaved",
                "SaveReason": "PlaybackProgress",
                "Item": {"Type": "Movie", "UserData": {"Played": False}},
            },
            self.user,
        )
        response = self.client.get(
            reverse("provider_detail", args=["jellyfin"]) + "?tab=connection"
        )
        self.assertNotContains(response, 'data-testid="jellyfin-template-outdated"')
