from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django_celery_beat.models import PeriodicTask

from integrations.jellyfin_client import JellyfinAuthError
from integrations.jellyfin_sync import JELLYFIN_PUSH_TASK_NAME
from integrations.models import JellyfinAccount
from integrations.views import _ensure_jellyfin_push_schedule


class JellyfinViewTests(TestCase):
    """Cover Jellyfin connect/disconnect/settings/push views."""

    def setUp(self):
        """Create an authenticated user for Jellyfin view requests."""
        self.user = get_user_model().objects.create_user(username="jf-view-user")
        self.client.force_login(self.user)

    @patch("integrations.views.JellyfinClient.get_current_user")
    @patch("integrations.views.JellyfinClient.healthcheck")
    def test_connect_persists_account(self, mock_healthcheck, mock_current_user):
        """Connecting Jellyfin should store an encrypted key and resolved user id."""
        mock_current_user.return_value = {"Id": "jf-1", "Name": "danny"}

        response = self.client.post(
            reverse("jellyfin_connect"),
            {
                "base_url": "https://jellyfin.local:8096",
                "api_key": "jf-key",
            },
        )

        self.assertEqual(response.status_code, 302)
        account = JellyfinAccount.objects.get(user=self.user)
        self.assertEqual(account.base_url, "https://jellyfin.local:8096")
        self.assertEqual(account.jellyfin_user_id, "jf-1")
        self.assertEqual(account.jellyfin_username, "danny")
        self.assertNotEqual(account.api_key, "jf-key")
        mock_healthcheck.assert_called_once()

    @patch("integrations.views.JellyfinClient.get_current_user")
    @patch("integrations.views.JellyfinClient.healthcheck")
    def test_connect_surfaces_auth_error(self, mock_healthcheck, mock_current_user):
        """A failed healthcheck should not persist an account."""
        mock_healthcheck.side_effect = JellyfinAuthError("bad key")

        response = self.client.post(
            reverse("jellyfin_connect"),
            {
                "base_url": "https://jellyfin.local:8096",
                "api_key": "bad-key",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(JellyfinAccount.objects.filter(user=self.user).exists())
        mock_current_user.assert_not_called()

    @patch("integrations.views.JellyfinClient.find_user_by_name")
    @patch("integrations.views.JellyfinClient.get_current_user")
    @patch("integrations.views.JellyfinClient.healthcheck")
    def test_connect_falls_back_to_username_for_dashboard_keys(
        self,
        mock_healthcheck,
        mock_current_user,
        mock_find_user,
    ):
        """A Dashboard API key (no Users/Me) should resolve via the username."""
        mock_current_user.return_value = None
        mock_find_user.return_value = {"Id": "jf-9", "Name": "danny"}

        response = self.client.post(
            reverse("jellyfin_connect"),
            {
                "base_url": "https://jellyfin.local:8096",
                "api_key": "dashboard-key",
                "username": "danny",
            },
        )

        self.assertEqual(response.status_code, 302)
        account = JellyfinAccount.objects.get(user=self.user)
        self.assertEqual(account.jellyfin_user_id, "jf-9")
        self.assertEqual(account.jellyfin_username, "danny")
        mock_healthcheck.assert_called_once()
        mock_find_user.assert_called_once_with("danny")

    def test_connect_requires_username_fallback_when_me_unresolved(self):
        """Without Users/Me and no username fallback, connect should fail cleanly."""
        with (
            patch("integrations.views.JellyfinClient.healthcheck"),
            patch(
                "integrations.views.JellyfinClient.get_current_user",
                return_value=None,
            ),
        ):
            response = self.client.post(
                reverse("jellyfin_connect"),
                {
                    "base_url": "https://jellyfin.local:8096",
                    "api_key": "jf-key",
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(JellyfinAccount.objects.filter(user=self.user).exists())

    def test_disconnect_removes_account_and_schedule(self):
        """Disconnecting should delete the account and any push schedule."""
        account = JellyfinAccount.objects.create(
            user=self.user,
            base_url="https://jellyfin.local:8096",
            api_key="encrypted",
            jellyfin_user_id="jf-1",
            scheduled_push_enabled=True,
        )
        _ensure_jellyfin_push_schedule(self.user, account)

        response = self.client.post(reverse("jellyfin_disconnect"))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(JellyfinAccount.objects.filter(user=self.user).exists())
        self.assertFalse(
            PeriodicTask.objects.filter(task=JELLYFIN_PUSH_TASK_NAME).exists()
        )

    def test_settings_toggles_create_and_remove_schedule(self):
        """Toggling scheduled_push_enabled should create/remove the periodic task."""
        JellyfinAccount.objects.create(
            user=self.user,
            base_url="https://jellyfin.local:8096",
            api_key="encrypted",
            jellyfin_user_id="jf-1",
        )

        response = self.client.post(
            reverse("jellyfin_settings"),
            {"scheduled_push_enabled": "on", "push_watched_enabled": "on"},
        )

        self.assertEqual(response.status_code, 302)
        account = JellyfinAccount.objects.get(user=self.user)
        self.assertTrue(account.scheduled_push_enabled)
        self.assertTrue(account.push_watched_enabled)
        self.assertFalse(account.push_unwatched_enabled)
        self.assertTrue(
            PeriodicTask.objects.filter(task=JELLYFIN_PUSH_TASK_NAME).exists()
        )

        response = self.client.post(reverse("jellyfin_settings"), {})

        account.refresh_from_db()
        self.assertFalse(account.scheduled_push_enabled)
        self.assertFalse(
            PeriodicTask.objects.filter(task=JELLYFIN_PUSH_TASK_NAME).exists()
        )

    @patch("integrations.views.tasks.push_jellyfin_watched.delay")
    def test_push_now_requires_connected_account(self, mock_delay):
        """push_now should refuse to queue without a connected account."""
        response = self.client.post(reverse("jellyfin_push_now"))

        self.assertEqual(response.status_code, 302)
        mock_delay.assert_not_called()

    @patch("integrations.views.tasks.push_jellyfin_watched.delay")
    def test_push_now_queues_task(self, mock_delay):
        """push_now should enqueue the push task for a connected account."""
        JellyfinAccount.objects.create(
            user=self.user,
            base_url="https://jellyfin.local:8096",
            api_key="encrypted",
            jellyfin_user_id="jf-1",
        )

        response = self.client.post(reverse("jellyfin_push_now"))

        self.assertEqual(response.status_code, 302)
        mock_delay.assert_called_once_with(user_id=self.user.id)

    @patch("integrations.views.tasks.import_jellyfin_playback_reporting.delay")
    def test_playback_reporting_upload_queues_history_import(self, mock_delay):
        """A connected user can queue a manual Playback Reporting upload."""
        JellyfinAccount.objects.create(
            user=self.user,
            base_url="https://jellyfin.local:8096",
            api_key="encrypted",
            jellyfin_user_id="jf-1",
        )
        payload = b"2024-01-01 00:00:00\tjf-1\titem-1\tMovie\tTitle\tDirectPlay\tWeb\tDevice\t120"

        response = self.client.post(
            reverse("jellyfin_playback_reporting_import"),
            {
                "playback_reporting_file": SimpleUploadedFile(
                    "PlaybackReporting.tsv",
                    payload,
                    content_type="text/tab-separated-values",
                ),
            },
        )

        self.assertEqual(response.status_code, 302)
        mock_delay.assert_called_once_with(payload, self.user.id, "new")
