from unittest.mock import patch
from urllib.parse import parse_qs, unquote, urlencode, urlparse

from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.cached_db import SessionStore
from django.test import Client, TestCase
from django.urls import reverse

from integrations.models import PlexAccount


class OAuthStateViewTests(TestCase):
    """Exercise provider OAuth state storage, consumption, and replay guards."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="oauth-user",
            password="oauth-password",
        )
        self.client.force_login(self.user)

    def _start_oauth(self, view_name):
        response = self.client.post(
            reverse(view_name),
            data={
                "mode": "new",
                "frequency": "once",
                "time": "00:00",
            },
        )

        self.assertEqual(response.status_code, 302)
        parsed_location = urlparse(response["Location"])
        query = parse_qs(parsed_location.query)
        if view_name == "plex_connect":
            fragment_query = parse_qs(parsed_location.fragment.lstrip("?"))
            forward_url = unquote(fragment_query["forwardUrl"][0])
            state_token = parse_qs(urlparse(forward_url).query)["state"][0]
        else:
            state_token = query["state"][0]
        self.assertIn(state_token, self.client.session)
        return state_token

    def _callback_url(self, view_name, state_token):
        return f"{reverse(view_name)}?{urlencode({'state': state_token, 'code': 'oauth-code'})}"

    def _assert_invalid_state(self, view_name, message, callback_path):
        response = self.client.get(reverse(view_name), follow=True)

        self.assertContains(response, message)
        self.assertEqual(response.redirect_chain[-1][0], callback_path)
        self.assertEqual(
            self.client.session.get("_auth_user_id"),
            str(self.user.pk),
        )

    def test_simkl_state_is_consumed_and_replay_is_rejected(self):
        state_token = self._start_oauth("simkl_oauth")
        callback_url = self._callback_url("import_simkl_private", state_token)

        with (
            patch(
                "integrations.views.simkl.get_token",
                return_value={"access_token": "simkl-access", "username": "simkl-user"},
            ) as get_token,
            patch("integrations.views.helpers.encrypt", return_value="encrypted-token"),
            patch("integrations.views.tasks.import_simkl.delay") as import_task,
        ):
            response = self.client.get(callback_url)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, reverse("import_data"))
            self.assertNotIn(state_token, self.client.session)

            with self.assertLogs("integrations.views", level="WARNING") as logs:
                replay = self.client.get(callback_url, follow=True)

            get_token.assert_called_once()
            import_task.assert_called_once()

        self.assertContains(replay, "Invalid or expired SIMKL authorization request.")
        self.assertNotIn(state_token, "\n".join(logs.output))

    def test_trakt_state_is_consumed_and_replay_is_rejected(self):
        state_token = self._start_oauth("trakt_oauth")
        callback_url = self._callback_url("import_trakt_private", state_token)

        with (
            patch(
                "integrations.views.trakt.handle_oauth_callback",
                return_value={"refresh_token": "trakt-refresh", "username": "trakt-user"},
            ) as handle_callback,
            patch("integrations.views.helpers.encrypt", return_value="encrypted-token"),
            patch("integrations.views.tasks.import_trakt.delay") as import_task,
        ):
            response = self.client.get(callback_url)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, reverse("import_data"))
            self.assertNotIn(state_token, self.client.session)

            with self.assertLogs("integrations.views", level="WARNING") as logs:
                replay = self.client.get(callback_url, follow=True)

            handle_callback.assert_called_once()
            import_task.assert_called_once()

        self.assertContains(replay, "Invalid or expired Trakt authorization request.")
        self.assertNotIn(state_token, "\n".join(logs.output))

    def test_anilist_state_is_consumed_and_replay_is_rejected(self):
        state_token = self._start_oauth("import_anilist_oauth")
        callback_url = self._callback_url("import_anilist_private", state_token)

        with (
            patch(
                "integrations.views.anilist.get_token",
                return_value={"access_token": "anilist-access", "username": "anilist-user"},
            ) as get_token,
            patch("integrations.views.helpers.encrypt", return_value="encrypted-token"),
            patch("integrations.views.tasks.import_anilist.delay") as import_task,
        ):
            response = self.client.get(callback_url)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, reverse("import_data"))
            self.assertNotIn(state_token, self.client.session)

            with self.assertLogs("integrations.views", level="WARNING") as logs:
                replay = self.client.get(callback_url, follow=True)

            get_token.assert_called_once()
            import_task.assert_called_once()

        self.assertContains(replay, "Invalid or expired AniList authorization request.")
        self.assertNotIn(state_token, "\n".join(logs.output))

    def test_plex_state_is_consumed_and_replay_is_rejected(self):
        with patch(
            "integrations.views.plex_api.create_pin",
            return_value={"id": "plex-pin-id", "code": "plex-pin-code"},
        ):
            state_token = self._start_oauth("plex_connect")

        callback_url = self._callback_url("plex_callback", state_token)
        with (
            patch("integrations.views.plex_api.poll_pin", return_value="plex-access"),
            patch(
                "integrations.views.plex_api.fetch_account",
                return_value={"id": "plex-account-id", "username": "plex-user"},
            ),
            patch("integrations.views.plex_api.list_sections", return_value=[]),
        ):
            response = self.client.get(callback_url)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("import_data"))
        self.assertNotIn(state_token, self.client.session)
        self.assertTrue(PlexAccount.objects.filter(user=self.user).exists())

        with patch("integrations.views.plex_api.poll_pin") as poll_pin:
            replay = self.client.get(callback_url, follow=True)

        poll_pin.assert_not_called()
        self.assertContains(replay, "Invalid or expired Plex authorization request.")

    def test_missing_state_is_rejected_without_provider_calls(self):
        cases = (
            (
                "import_simkl_private",
                "SIMKL",
                "integrations.views.simkl.get_token",
            ),
            (
                "import_trakt_private",
                "Trakt",
                "integrations.views.trakt.handle_oauth_callback",
            ),
            (
                "import_anilist_private",
                "AniList",
                "integrations.views.anilist.get_token",
            ),
            ("plex_callback", "Plex", "integrations.views.plex_api.poll_pin"),
        )

        for view_name, provider, provider_call in cases:
            with self.subTest(provider=provider), patch(provider_call) as callback:
                self._assert_invalid_state(
                    view_name,
                    f"Invalid or expired {provider} authorization request.",
                    reverse("import_data"),
                )
                callback.assert_not_called()

    def test_stale_callback_after_relogin_is_safe(self):
        state_token = self._start_oauth("simkl_oauth")
        callback_url = self._callback_url("import_simkl_private", state_token)
        stale_session_key = self.client.session.session_key

        current_client = Client()
        current_client.force_login(self.user)
        SessionStore(stale_session_key).delete()

        with patch("integrations.views.simkl.get_token") as get_token:
            response = self.client.get(callback_url)

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("account_login"), response["Location"])
        get_token.assert_not_called()
        self.assertEqual(
            current_client.session.get("_auth_user_id"),
            str(self.user.pk),
        )

    def test_oauth_start_still_requires_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)

        response = csrf_client.post(
            reverse("simkl_oauth"),
            data={
                "mode": "new",
                "frequency": "once",
                "time": "00:00",
            },
            HTTP_REFERER="/",
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/")
