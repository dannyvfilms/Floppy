from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from integrations.models import PlexAccount, PlexWebhookShare
from integrations.plex import PlexAuthError


class PlexUsernamesUpdateTests(TestCase):
    """Tests for Plex integration functionality."""

    def setUp(self):
        """Create user for the tests."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    def test_update_plex_usernames_success(self):
        """Test successful update of Plex usernames."""
        response = self.client.post(
            reverse("update_plex_usernames"),
            {"plex_usernames": "user1, user2, user3"},
        )

        self.assertRedirects(response, reverse("provider_detail", args=["plex"]) + "?tab=tracking")
        self.user.refresh_from_db()

        self.assertEqual(self.user.plex_usernames, "user1, user2, user3")

        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertIn("updated successfully", str(messages[0]))

    def test_update_plex_usernames_deduplication(self):
        """Test duplicate usernames are removed."""
        self.client.post(
            reverse("update_plex_usernames"),
            {"plex_usernames": "user1, user2, user1, user3, user2"},
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.plex_usernames, "user1, user2, user3")

    def test_update_plex_usernames_whitespace_handling(self):
        """Test whitespace in usernames is handled correctly."""
        self.client.post(
            reverse("update_plex_usernames"),
            {"plex_usernames": "  user1  , user2  ,  user3  "},
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.plex_usernames, "user1, user2, user3")

    def test_update_plex_usernames_empty(self):
        """Test empty username list."""
        self.user.plex_usernames = "user1, user2"
        self.user.save()

        response = self.client.post(
            reverse("update_plex_usernames"),
            {"plex_usernames": ""},
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.plex_usernames, "")

        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertIn("updated successfully", str(messages[0]))

    def test_update_plex_usernames_no_change(self):
        """Test no update when usernames haven't changed."""
        self.user.plex_usernames = "user1, user2"
        self.user.save()

        response = self.client.post(
            reverse("update_plex_usernames"),
            {"plex_usernames": "user1, user2"},
        )

        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 0)


class PlexWebhookLibrariesUpdateTests(TestCase):
    """Tests for Plex webhook library selection settings."""

    def setUp(self):
        self.credentials = {"username": "testlibs", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)
        PlexAccount.objects.create(
            user=self.user,
            plex_token="token",
            plex_username="testlibs",
            sections=[
                {
                    "id": "1",
                    "title": "Movies",
                    "machine_identifier": "machine-a",
                    "server_name": "Home Server",
                },
                {
                    "id": "2",
                    "title": "Shows",
                    "machine_identifier": "machine-a",
                    "server_name": "Home Server",
                },
            ],
            sections_refreshed_at=timezone.now(),
        )

    def test_update_plex_webhook_libraries_success(self):
        response = self.client.post(
            reverse("update_plex_webhook_libraries"),
            {"plex_webhook_libraries": ["machine-a::1"]},
        )

        self.assertRedirects(response, reverse("provider_detail", args=["plex"]) + "?tab=tracking")
        self.user.refresh_from_db()
        self.assertEqual(self.user.plex_webhook_libraries, ["machine-a::1"])

    def test_update_plex_webhook_libraries_filters_invalid_values(self):
        self.client.post(
            reverse("update_plex_webhook_libraries"),
            {"plex_webhook_libraries": ["machine-a::1", "machine-z::9"]},
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.plex_webhook_libraries, ["machine-a::1"])


class PlexWebhookShareTests(TestCase):
    """Tests for owner-managed and recipient-controlled Plex webhook shares."""

    def setUp(self):
        self.credentials = {"username": "share-owner", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.recipient = get_user_model().objects.create_user(
            username="share-recipient",
            plex_usernames="plex-friend",
        )
        self.client.login(**self.credentials)
        PlexAccount.objects.create(
            user=self.user,
            plex_token="token",
            plex_username="share-owner",
            sections=[
                {
                    "id": "1",
                    "title": "Movies",
                    "machine_identifier": "machine-a",
                },
                {
                    "id": "2",
                    "title": "Shows",
                    "machine_identifier": "machine-a",
                },
            ],
            sections_refreshed_at=timezone.now(),
        )

    def test_owner_creates_opt_in_share_with_selected_libraries(self):
        response = self.client.post(
            reverse("update_plex_webhook_share"),
            {
                "plex_webhook_share_recipient": self.recipient.id,
                "plex_webhook_share_username": "Plex Friend, Another Friend, plex friend",
                "plex_webhook_share_libraries": ["machine-a::2"],
            },
        )

        self.assertRedirects(response, reverse("provider_detail", args=["plex"]) + "?tab=tracking")
        share = PlexWebhookShare.objects.get()
        self.assertEqual(share.owner, self.user)
        self.assertEqual(share.recipient, self.recipient)
        self.assertEqual(share.plex_username, "Plex Friend, Another Friend")
        self.assertEqual(share.allowed_libraries, ["machine-a::2"])
        self.assertFalse(share.recipient_enabled)

    def test_recipient_can_enable_and_disable_share(self):
        share = PlexWebhookShare.objects.create(
            owner=self.user,
            recipient=self.recipient,
            plex_username="Plex Friend",
        )
        self.client.force_login(self.recipient)

        response = self.client.post(
            reverse("toggle_plex_webhook_share"),
            {"plex_webhook_share_id": share.id, "enabled": "1"},
        )

        self.assertRedirects(response, reverse("provider_detail", args=["plex"]) + "?tab=tracking")
        share.refresh_from_db()
        self.assertTrue(share.recipient_enabled)

        self.client.post(
            reverse("toggle_plex_webhook_share"),
            {"plex_webhook_share_id": share.id, "enabled": "0"},
        )
        share.refresh_from_db()
        self.assertFalse(share.recipient_enabled)

    def test_owner_cannot_duplicate_recipient_username_case_insensitively(self):
        first_recipient = get_user_model().objects.create_user(username="other-recipient")
        PlexWebhookShare.objects.create(
            owner=self.user,
            recipient=first_recipient,
            plex_username="Plex Friend",
        )

        response = self.client.post(
            reverse("update_plex_webhook_share"),
            {
                "plex_webhook_share_recipient": self.recipient.id,
                "plex_webhook_share_username": "plex friend",
            },
        )

        self.assertRedirects(response, reverse("provider_detail", args=["plex"]) + "?tab=tracking")
        self.assertEqual(PlexWebhookShare.objects.count(), 1)

    def test_owner_can_revoke_share(self):
        share = PlexWebhookShare.objects.create(
            owner=self.user,
            recipient=self.recipient,
            plex_username="Plex Friend",
        )

        response = self.client.post(
            reverse("delete_plex_webhook_share"),
            {"plex_webhook_share_id": share.id},
        )

        self.assertRedirects(response, reverse("provider_detail", args=["plex"]) + "?tab=tracking")
        self.assertFalse(PlexWebhookShare.objects.exists())

    def test_integrations_page_shows_owner_and_received_share_controls(self):
        share = PlexWebhookShare.objects.create(
            owner=self.user,
            recipient=self.recipient,
            plex_username="Plex Friend",
            allowed_libraries=["machine-a::2"],
        )

        owner_response = self.client.get(
            reverse("provider_detail", args=["plex"]) + "?tab=tracking"
        )

        self.assertContains(owner_response, "Share Plex Webhook")
        self.assertContains(owner_response, "Plex Friend")
        self.assertContains(owner_response, "Waiting for recipient opt-in")

        self.client.force_login(self.recipient)
        recipient_response = self.client.get(
            reverse("provider_detail", args=["plex"]) + "?tab=tracking"
        )

        self.assertContains(recipient_response, "Shared Plex Webhooks")
        self.assertContains(recipient_response, self.user.username)
        self.assertContains(recipient_response, "Turn On")
        self.assertContains(recipient_response, str(share.id))

    def test_integrations_page_limits_share_recipient_options(self):
        demo_user = get_user_model().objects.create_user(
            username="demo-recipient",
            is_demo=True,
        )
        unconfigured_user = get_user_model().objects.create_user(
            username="unconfigured-recipient",
        )
        debug_user = get_user_model().objects.create_user(
            username="debug-6bbc767e",
            is_test_account=True,
        )
        codex_user = get_user_model().objects.create_user(
            username="codex-smoke-hardcover",
            is_test_account=True,
        )

        response = self.client.get(
            reverse("provider_detail", args=["plex"]) + "?tab=tracking"
        )

        recipient_options = response.context["plex_share_recipients"]
        self.assertIn(self.recipient, recipient_options)
        self.assertNotIn(demo_user, recipient_options)
        self.assertIn(unconfigured_user, recipient_options)
        self.assertNotIn(debug_user, recipient_options)
        self.assertNotIn(codex_user, recipient_options)
        self.assertContains(response, 'placeholder="username1, username2, username3"')
        self.assertNotContains(response, "Select a Plex username")

    def test_owner_cannot_create_share_for_demo_user(self):
        demo_user = get_user_model().objects.create_user(
            username="demo-recipient",
            is_demo=True,
        )

        response = self.client.post(
            reverse("update_plex_webhook_share"),
            {
                "plex_webhook_share_recipient": demo_user.id,
                "plex_webhook_share_username": "plex-friend",
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(PlexWebhookShare.objects.exists())

    def test_owner_cannot_create_share_for_qa_user(self):
        debug_user = get_user_model().objects.create_test_user(username="debug_user_2")

        response = self.client.post(
            reverse("update_plex_webhook_share"),
            {
                "plex_webhook_share_recipient": debug_user.id,
                "plex_webhook_share_username": "debug_user_2",
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(PlexWebhookShare.objects.exists())

    def test_create_test_user_marks_explicit_flag(self):
        test_user = get_user_model().objects.create_test_user(
            username="future-qa-user",
        )

        self.assertTrue(test_user.is_test_account)

    def test_disconnect_removes_owned_shares(self):
        PlexWebhookShare.objects.create(
            owner=self.user,
            recipient=self.recipient,
            plex_username="Plex Friend",
        )

        response = self.client.post(reverse("plex_disconnect"))

        self.assertRedirects(
            response,
            reverse("provider_detail", args=["plex"]) + "?tab=connection",
        )
        self.assertFalse(PlexWebhookShare.objects.exists())


class PlexSectionsRefreshTests(TestCase):
    """Integrations settings page must not block on live Plex connection probing."""

    def setUp(self):
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)
        self.account = PlexAccount.objects.create(user=self.user, plex_token="token")

    @patch("users.views.tasks.refresh_plex_sections.delay")
    @patch("integrations.plex.list_sections")
    def test_stale_sections_dispatch_background_refresh_without_blocking(
        self,
        mock_list_sections,
        mock_delay,
    ):
        """The view must dispatch the refresh task, never call list_sections() itself."""
        response = self.client.get(
            reverse("provider_detail", args=["plex"]) + "?tab=tracking"
        )

        self.assertEqual(response.status_code, 200)
        mock_delay.assert_called_once_with(self.user.id)
        mock_list_sections.assert_not_called()

    @patch("integrations.plex.list_sections")
    def test_refresh_task_persists_sections_on_success(self, mock_list_sections):
        from integrations.tasks import refresh_plex_sections

        mock_list_sections.return_value = [{"id": "1", "title": "Movies"}]

        refresh_plex_sections(self.user.id)

        self.account.refresh_from_db()
        self.assertEqual(self.account.sections, [{"id": "1", "title": "Movies"}])
        self.assertIsNotNone(self.account.sections_refreshed_at)

    @patch("integrations.plex.list_sections")
    def test_refresh_task_leaves_cache_untouched_on_auth_error(
        self,
        mock_list_sections,
    ):
        from integrations.tasks import refresh_plex_sections

        self.account.sections = [{"id": "stale", "title": "Old"}]
        self.account.save(update_fields=["sections"])
        mock_list_sections.side_effect = PlexAuthError("token revoked")

        refresh_plex_sections(self.user.id)

        self.account.refresh_from_db()
        self.assertEqual(self.account.sections, [{"id": "stale", "title": "Old"}])
        self.assertIsNone(self.account.sections_refreshed_at)
