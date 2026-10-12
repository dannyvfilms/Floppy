import base64
import hashlib
import json
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, unquote, urlencode, urlparse

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.contrib.sessions.backends.cached_db import SessionStore
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django_celery_beat.models import PeriodicTask
from requests import Response

from integrations.imports import helpers
from integrations.imports.helpers import MediaImportError
from integrations.models import PlexAccount
from integrations.views import TRAKT_DEVICE_SESSION_KEY


@override_settings(SIMKL_ID="test-simkl-id", SIMKL_SECRET="test-simkl-secret")
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

    @override_settings(SIMKL_ID="", SIMKL_SECRET="")
    def test_simkl_without_credentials_never_leaves_floppy(self):
        # Floppy used to ship a SIMKL client ID with no secret, so users
        # approved on SIMKL and only then hit a 403 at token exchange (#1318).
        response = self.client.post(
            reverse("simkl_oauth"),
            data={"mode": "new", "frequency": "once", "time": "00:00"},
            follow=True,
        )

        self.assertEqual(response.redirect_chain, [(reverse("import_data"), 302)])
        self.assertContains(response, "SIMKL needs your own Client ID and Client secret.")
        self.assertContains(response, "SIMKL needs your own API app")

    def test_simkl_rejected_token_exchange_shows_message_not_500(self):
        state_token = self._start_oauth("simkl_oauth")
        callback_url = self._callback_url("import_simkl_private", state_token)
        code_verifier = self.client.session[state_token]["code_verifier"]
        rejected = Response()
        rejected.status_code = 403
        rejected.url = "https://api.simkl.com/oauth2/token"

        with patch(
            "app.providers.services.resilient_request",
            return_value=rejected,
        ) as provider_request:
            response = self.client.get(callback_url, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SIMKL rejected the Client ID and Client secret.")
        request_kwargs = provider_request.call_args.kwargs
        self.assertEqual(request_kwargs["url"], "https://api.simkl.com/oauth2/token")
        self.assertEqual(request_kwargs["headers"]["simkl-api-key"], "test-simkl-id")
        self.assertTrue(request_kwargs["headers"]["User-Agent"].startswith("Floppy/"))
        self.assertEqual(request_kwargs["data"]["client_secret"], "test-simkl-secret")
        self.assertEqual(request_kwargs["data"]["code_verifier"], code_verifier)

    def test_simkl_authorize_uses_auth_v2_with_pkce(self):
        response = self.client.post(
            reverse("simkl_oauth"),
            data={"mode": "new", "frequency": "once", "time": "00:00"},
        )
        parsed = urlparse(response["Location"])
        query = parse_qs(parsed.query)
        code_verifier = self.client.session[query["state"][0]]["code_verifier"]
        expected_challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )

        self.assertEqual(f"{parsed.netloc}{parsed.path}", "simkl.com/oauth2/authorize")
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(query["code_challenge"], [expected_challenge])

    def test_simkl_v1_option_keeps_the_original_flow(self):
        # SIMKL apps made before AUTH V2 keep working until V1 retires
        response = self.client.post(
            reverse("simkl_oauth"),
            data={
                "mode": "new",
                "frequency": "daily",
                "time": "03:00",
                "auth_version": "v1",
            },
        )
        parsed = urlparse(response["Location"])
        query = parse_qs(parsed.query)
        state_token = query["state"][0]

        self.assertEqual(f"{parsed.netloc}{parsed.path}", "simkl.com/oauth/authorize")
        self.assertNotIn("code_challenge", query)
        self.assertNotIn("code_verifier", self.client.session[state_token])

        with patch(
            "app.providers.services.api_request",
            side_effect=[
                {"access_token": "v1-access"},
                {"user": {"name": "simkl-user"}},
            ],
        ) as api_request:
            self.client.get(self._callback_url("import_simkl_private", state_token))

        token_call = api_request.call_args_list[0]
        self.assertEqual(token_call.args[2], "https://api.simkl.com/oauth/token")
        self.assertEqual(
            token_call.kwargs["params"]["client_secret"], "test-simkl-secret"
        )
        self.assertNotIn("code_verifier", token_call.kwargs["params"])
        task_kwargs = json.loads(
            PeriodicTask.objects.get(task="Import from SIMKL").kwargs,
        )
        self.assertEqual(helpers.decrypt(task_kwargs["token"]), "v1-access")
        self.assertNotIn("refresh_token", task_kwargs)

    def test_simkl_schedule_keeps_the_refresh_token(self):
        response = self.client.post(
            reverse("simkl_oauth"),
            data={"mode": "new", "frequency": "daily", "time": "03:00"},
        )
        state_token = parse_qs(urlparse(response["Location"]).query)["state"][0]
        callback_url = self._callback_url("import_simkl_private", state_token)

        with patch(
            "integrations.views.simkl.get_token",
            return_value={
                "access_token": "simkl-access",
                "refresh_token": "simkl-refresh",
                "username": "simkl-user",
            },
        ):
            self.client.get(callback_url)

        task_kwargs = json.loads(
            PeriodicTask.objects.get(task="Import from SIMKL").kwargs,
        )
        self.assertEqual(
            helpers.decrypt(task_kwargs["refresh_token"]),
            "simkl-refresh",
        )
        self.assertEqual(helpers.decrypt(task_kwargs["token"]), "simkl-access")

    @override_settings(URLS=["https://floppy.example.com"])
    def test_trakt_state_is_consumed_and_replay_is_rejected(self):
        state_token = self._start_oauth("trakt_oauth")
        callback_url = self._callback_url("import_trakt_private", state_token)

        with (
            patch(
                "integrations.views.trakt.handle_oauth_callback",
                return_value={
                    "refresh_token": "trakt-refresh",
                    "redirect_uri": "https://floppy.example.com/import/trakt/private",
                    "username": "trakt-user",
                },
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
            self.assertEqual(
                import_task.call_args.kwargs["redirect_uri"],
                "https://floppy.example.com/import/trakt/private",
            )

        self.assertContains(replay, "Invalid or expired Trakt authorization request.")
        self.assertNotIn(state_token, "\n".join(logs.output))

    @override_settings(URLS=["https://floppy.example.com"])
    def test_trakt_without_a_secret_authorizes_with_pkce(self):
        """An app with no client secret logs in with a PKCE challenge (#1523)."""
        with (
            patch(
                "integrations.views.credentials.get",
                side_effect=lambda _slug, field: {"client_id": "client"}.get(field, ""),
            ),
            patch("integrations.views.trakt.default_client_secret", return_value=""),
        ):
            response = self.client.post(
                reverse("trakt_oauth"),
                data={"mode": "new", "frequency": "once", "time": "00:00"},
            )

        query = parse_qs(urlparse(response["Location"]).query)
        state_token = query["state"][0]
        verifier = self.client.session[state_token]["code_verifier"]
        digest = hashlib.sha256(verifier.encode()).digest()
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(
            query["code_challenge"],
            [base64.urlsafe_b64encode(digest).decode().rstrip("=")],
        )

        callback_url = self._callback_url("import_trakt_private", state_token)
        with (
            patch(
                "integrations.views.trakt.handle_oauth_callback",
                return_value={
                    "refresh_token": "trakt-refresh",
                    "redirect_uri": "https://floppy.example.com/import/trakt/private",
                    "username": "trakt-user",
                },
            ) as handle_callback,
            patch("integrations.views.tasks.import_trakt.delay"),
        ):
            self.client.get(callback_url)

        self.assertEqual(handle_callback.call_args.kwargs["code_verifier"], verifier)

    @override_settings(URLS=["https://floppy.example.com"])
    def test_trakt_with_a_secret_does_not_use_pkce(self):
        with (
            patch(
                "integrations.views.credentials.get",
                side_effect=lambda _slug, field: {"client_id": "client"}.get(field, ""),
            ),
            patch(
                "integrations.views.trakt.default_client_secret",
                return_value="secret",
            ),
        ):
            response = self.client.post(
                reverse("trakt_oauth"),
                data={"mode": "new", "frequency": "once", "time": "00:00"},
            )

        query = parse_qs(urlparse(response["Location"]).query)
        self.assertNotIn("code_challenge", query)
        self.assertNotIn("code_verifier", self.client.session[query["state"][0]])

    @override_settings(URLS=["https://floppy.example.com"])
    def test_trakt_reconnect_refreshes_the_existing_schedule(self):
        """A reconnect with the same settings must replace the schedule's dead token (#1404)."""
        callback_uri = "https://floppy.example.com/import/trakt/private"
        for token in ("first-token", "second-token"):
            response = self.client.post(
                reverse("trakt_oauth"),
                data={"mode": "new", "frequency": "daily", "time": "04:00"},
            )
            state_token = parse_qs(urlparse(response["Location"]).query)["state"][0]
            with (
                patch(
                    "integrations.views.trakt.handle_oauth_callback",
                    return_value={
                        "refresh_token": token,
                        "redirect_uri": callback_uri,
                        "username": "trakt-user",
                    },
                ),
                patch("integrations.views.helpers.encrypt", side_effect=lambda t: f"enc-{t}"),
            ):
                self.client.get(self._callback_url("import_trakt_private", state_token))

        task = PeriodicTask.objects.get(task="Import from Trakt")
        task_kwargs = json.loads(task.kwargs)
        self.assertEqual(task_kwargs["token"], "enc-second-token")
        self.assertEqual(task_kwargs["redirect_uri"], callback_uri)

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


@override_settings(URLS=["http://192.168.1.50:8000"])
class TraktDeviceFlowViewTests(TestCase):
    """Trakt cannot redirect to a plain-HTTP LAN address, so use device codes (#681)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="device-user",
            password="device-password",
        )
        self.client.force_login(self.user)
        self.device = {
            "device_code": "device-code",
            "user_code": "5055CC52",
            "verification_url": "https://trakt.tv/activate",
            "expires_in": 600,
            "interval": 5,
        }

    def _start(self, next_url=None):
        data = {"mode": "new", "frequency": "once", "time": "00:00"}
        if next_url:
            data["next"] = next_url
        with patch(
            "integrations.views.trakt.request_device_code",
            return_value=self.device,
        ):
            return self.client.post(reverse("trakt_oauth"), data=data)

    def test_start_stores_state_and_redirects_to_the_code_screen(self):
        response = self._start(next_url="/onboarding/")

        self.assertRedirects(
            response,
            reverse("trakt_device_verify"),
            fetch_redirect_response=False,
        )
        state = self.client.session[TRAKT_DEVICE_SESSION_KEY]
        self.assertEqual(state["device_code"], "device-code")
        self.assertEqual(state["mode"], "new")
        self.assertEqual(state["frequency"], "once")
        self.assertEqual(state["time"], "00:00")
        self.assertEqual(state["return_to"], "/onboarding/")

    def test_verify_screen_shows_the_code(self):
        self._start()
        response = self.client.get(reverse("trakt_device_verify"))

        self.assertContains(response, "5055CC52")
        self.assertContains(response, reverse("trakt_device_poll"))

    def test_poll_while_pending_keeps_the_session(self):
        self._start()
        with patch(
            "integrations.views.trakt.poll_device_token",
            return_value=None,
        ) as poll:
            response = self.client.get(reverse("trakt_device_poll"))

        poll.assert_called_once_with("device-code")
        self.assertEqual(response.status_code, 204)
        self.assertNotIn("HX-Redirect", response)
        self.assertIn(TRAKT_DEVICE_SESSION_KEY, self.client.session)

    def test_poll_success_queues_the_import(self):
        self._start()
        with (
            patch(
                "integrations.views.trakt.poll_device_token",
                return_value={
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
                    "username": "trakt-user",
                },
            ),
            patch("integrations.views.helpers.encrypt", return_value="encrypted-token"),
            patch("integrations.views.tasks.import_trakt.delay") as import_task,
        ):
            response = self.client.get(reverse("trakt_device_poll"))

        import_task.assert_called_once()
        self.assertEqual(
            import_task.call_args.kwargs["redirect_uri"],
            "urn:ietf:wg:oauth:2.0:oob",
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Redirect"], reverse("import_data"))
        self.assertNotIn(TRAKT_DEVICE_SESSION_KEY, self.client.session)

    def test_poll_surfaces_a_denied_authorization(self):
        self._start()
        with patch(
            "integrations.views.trakt.poll_device_token",
            side_effect=MediaImportError("Trakt authorization was denied."),
        ):
            response = self.client.get(reverse("trakt_device_poll"))

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Redirect"], reverse("import_data"))
        self.assertNotIn(TRAKT_DEVICE_SESSION_KEY, self.client.session)
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertIn("Trakt authorization was denied.", messages)

    def test_expired_state_never_calls_trakt(self):
        self._start()
        session = self.client.session
        state = session[TRAKT_DEVICE_SESSION_KEY]
        state["expires_at"] = (timezone.now() - timedelta(seconds=1)).isoformat()
        session[TRAKT_DEVICE_SESSION_KEY] = state
        session.save()

        with patch("integrations.views.trakt.poll_device_token") as poll:
            response = self.client.get(reverse("trakt_device_poll"))

        poll.assert_not_called()
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Redirect"], reverse("import_data"))
        self.assertNotIn(TRAKT_DEVICE_SESSION_KEY, self.client.session)
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertIn("The Trakt authorization code expired. Start again.", messages)
