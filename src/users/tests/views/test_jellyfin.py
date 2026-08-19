from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse


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

        self.assertRedirects(response, reverse("integrations"))
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
