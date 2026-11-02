"""Relocated capability forms preserve settings owned by other tabs."""

from html.parser import HTMLParser
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from django.urls import reverse

from app.models import Status
from integrations.models import JellyfinAccount, PlexAccount
from users.views import NEW_TOKEN_SESSION_KEY, integrations_context


class _SettingsForm(HTMLParser):
    def __init__(self, action):
        super().__init__()
        self.action = action
        self.inside = False
        self.data = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.inside = attrs.get("action") == self.action
        if (
            self.inside
            and tag == "input"
            and attrs.get("name")
            and (attrs.get("type") != "checkbox" or "checked" in attrs)
        ):
            self.data[attrs["name"]] = attrs.get("value", "on")

    def handle_endtag(self, tag):
        if tag == "form":
            self.inside = False


class ProviderIntegrationSectionsTests(TestCase):
    """A tab may change its own flags without resetting the other capability."""

    def setUp(self):
        """Create a connection with deliberately mixed flag values."""
        self.user = get_user_model().objects.create_user(username="provider-tabs")
        self.client.force_login(self.user)
        self.account = JellyfinAccount.objects.create(
            user=self.user,
            base_url="https://jellyfin.example.com",
            api_key="stored-key",
            jellyfin_user_id="jf-user",
            push_watched_enabled=True,
            push_unwatched_enabled=False,
            scheduled_push_enabled=True,
            instant_push_enabled=False,
            pull_history_enabled=True,
        )

    def _rendered_settings(self, tab):
        request = RequestFactory().get("/settings/providers/jellyfin")
        request.user = self.user
        request.session = {}
        context = integrations_context(request, "jellyfin")
        context.update(provider_slug="jellyfin", provider_tab=tab)
        html = render_to_string(
            "users/providers/integration_content.html",
            context,
            request=request,
        )
        form = _SettingsForm(reverse("jellyfin_settings"))
        form.feed(html)
        return form.data

    def test_import_form_preserves_outbound_flags(self):
        """Disabling incoming polling keeps all existing outbound choices."""
        data = self._rendered_settings("import")
        data.pop("pull_history_enabled")
        self.client.post(reverse("jellyfin_settings"), data)
        self.account.refresh_from_db()
        self.assertFalse(self.account.pull_history_enabled)
        self.assertTrue(self.account.push_watched_enabled)
        self.assertFalse(self.account.push_unwatched_enabled)
        self.assertTrue(self.account.scheduled_push_enabled)
        self.assertFalse(self.account.instant_push_enabled)

    def test_sync_form_preserves_incoming_polling(self):
        """Changing an outbound flag keeps historical import enabled."""
        data = self._rendered_settings("sync")
        data.pop("push_watched_enabled")
        self.client.post(reverse("jellyfin_settings"), data)
        self.account.refresh_from_db()
        self.assertFalse(self.account.push_watched_enabled)
        self.assertTrue(self.account.pull_history_enabled)

    def test_provider_context_does_not_consume_one_time_token(self):
        """Only Access & Tokens may consume a newly generated app secret."""
        request = RequestFactory().get("/settings/providers/jellyfin")
        request.user = self.user
        request.session = {NEW_TOKEN_SESSION_KEY: "show-once"}
        context = integrations_context(request, "jellyfin")
        self.assertIsNone(context["new_integration_token"])
        self.assertEqual(request.session[NEW_TOKEN_SESSION_KEY], "show-once")

    @patch("users.views.tasks.refresh_plex_sections.delay")
    @patch("users.views._should_refresh_plex_sections", return_value=True)
    def test_unrelated_provider_does_not_refresh_plex(self, _stale, refresh):
        """Opening Jellyfin does not enqueue work for another provider."""
        PlexAccount.objects.create(user=self.user, plex_token="stored-plex-key")
        request = RequestFactory().get("/settings/providers/jellyfin")
        request.user = self.user
        request.session = {}
        integrations_context(request, "jellyfin")
        refresh.assert_not_called()

    @patch("users.views.tasks.refresh_plex_sections.delay")
    @patch("users.views._should_refresh_plex_sections", return_value=True)
    def test_central_context_can_suppress_plex_refresh(self, _stale, refresh):
        """Activity and token pages need no server-library refresh."""
        PlexAccount.objects.create(user=self.user, plex_token="stored-plex-key")
        request = RequestFactory().get("/settings/activity")
        request.user = self.user
        request.session = {}
        integrations_context(request, refresh_plex=False)
        refresh.assert_not_called()

    def _seerr_settings(self, tab):
        self.user.jellyseerr_enabled = True
        self.user.jellyseerr_trigger_statuses = "PROCESSING"
        self.user.jellyseerr_allowed_usernames = "bob"
        self.user.jellyseerr_default_added_status = Status.IN_PROGRESS.value
        self.user.seerr_url = "https://seerr.example.com"
        self.user.seerr_username = "bob"
        self.user.seerr_user_id = 42
        self.user.seerr_api_key = "never-render-this-secret"
        self.user.save()
        request = RequestFactory().get("/settings/providers/seerr")
        request.user = self.user
        request.session = {}
        html = render_to_string(
            "users/providers/integration_content.html",
            {
                **integrations_context(request, "seerr"),
                "provider_slug": "seerr",
                "provider_tab": tab,
            },
            request=request,
        )
        self.assertNotIn("never-render-this-secret", html)
        form = _SettingsForm(reverse("update_jellyseerr_settings"))
        form.feed(html)
        return form.data

    @patch("users.views.seerr_api.SeerrClient.find_user_id", return_value=43)
    def test_seerr_connection_form_preserves_tracking_rules(self, _lookup):
        """Changing connection identity does not enable or reset intake rules."""
        data = self._seerr_settings("connection")
        data["seerr_username"] = "new-user"
        data["seerr_api_key"] = "replacement-key"
        self.client.post(reverse("update_jellyseerr_settings"), data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.jellyseerr_enabled)
        self.assertEqual(self.user.jellyseerr_trigger_statuses, "PROCESSING")
        self.assertEqual(self.user.jellyseerr_allowed_usernames, "bob")
        self.assertEqual(
            self.user.jellyseerr_default_added_status, Status.IN_PROGRESS.value
        )
        self.assertEqual(self.user.seerr_username, "new-user")

    @patch("users.views.seerr_api.SeerrClient.find_user_id")
    def test_seerr_tracking_form_preserves_connection(self, lookup):
        """Changing webhook filters keeps credentials and needs no server call."""
        data = self._seerr_settings("tracking")
        data.update(
            jellyseerr_enabled="1",
            jellyseerr_trigger_statuses="AVAILABLE",
            jellyseerr_default_added_status=Status.IN_PROGRESS.value,
        )
        self.client.post(reverse("update_jellyseerr_settings"), data)
        self.user.refresh_from_db()
        self.assertEqual(self.user.jellyseerr_trigger_statuses, "AVAILABLE")
        self.assertEqual(self.user.seerr_url, "https://seerr.example.com")
        self.assertEqual(self.user.seerr_username, "bob")
        self.assertEqual(self.user.seerr_api_key, "never-render-this-secret")
        self.assertEqual(self.user.seerr_user_id, 42)
        lookup.assert_not_called()
