# FORK: device-code and redirect connect endpoints for the native app.
from datetime import timedelta
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from integrations import pending_auth
from integrations.imports.helpers import MediaImportError

from .base import FloppyApiTestCase

APP_LINK = "floppy-native-proof://connect/trakt"


@override_settings(URLS=["http://192.168.1.50:8000"])
class TraktDeviceConnectTests(FloppyApiTestCase):
    """Trakt on a plain-HTTP instance links through a device code."""

    device = {
        "device_code": "device-code",
        "user_code": "5055CC52",
        "verification_url": "https://trakt.tv/activate",
        "expires_in": 600,
        "interval": 5,
    }

    def _start(self):
        with patch("integrations.views.trakt.request_device_code", return_value=self.device):
            return self.call_api(
                "post", "api_provider_connect_start", args=("trakt",), headers=self.auth_headers,
                payload={"mode": "new", "frequency": "once", "time": "00:00"},
            )

    def _poll(self):
        return self.call_api("get", "api_provider_connect_poll", args=("trakt",), headers=self.auth_headers)

    def test_start_returns_the_code_and_the_web_page_reads_the_same_state(self):
        response = self._start()
        self.assertEqual(response.status_code, HTTP.OK, response.content)
        data = response.json()
        self.assertEqual(data["kind"], "device")
        self.assertEqual(data["userCode"], "5055CC52")
        self.assertEqual(data["openUrl"], "https://trakt.tv/activate/5055CC52")
        self.assertEqual(data["interval"], 5)
        self.client.force_login(self.user1)
        page = self.client.get(reverse("trakt_device_verify"))
        self.assertContains(page, "5055CC52")

    def test_poll_pending_connected_denied_and_expired(self):
        self._start()
        with patch("integrations.views.trakt.poll_device_token", return_value=None):
            self.assertEqual(self._poll().json()["status"], "pending")
        done = {
            "access_token": "a", "refresh_token": "r",
            "redirect_uri": "urn:ietf:wg:oauth:2.0:oob", "username": "tr",
        }
        with (
            patch("integrations.views.trakt.poll_device_token", return_value=done),
            patch("integrations.views.tasks.import_trakt.delay") as queued,
        ):
            self.assertEqual(self._poll().json()["status"], "connected")
        queued.assert_called_once()
        self.assertIsNone(pending_auth.get("trakt_device_auth", self.user1.pk))

        self._start()
        with patch(
            "integrations.views.trakt.poll_device_token",
            side_effect=MediaImportError("Trakt authorization was denied."),
        ):
            data = self._poll().json()
        self.assertEqual(data["status"], "denied")

        self._start()
        state = pending_auth.get("trakt_device_auth", self.user1.pk)
        state["expires_at"] = (timezone.now() - timedelta(seconds=1)).isoformat()
        pending_auth.put("trakt_device_auth", self.user1.pk, state)
        with patch("integrations.views.trakt.poll_device_token") as poll:
            self.assertEqual(self._poll().json()["status"], "expired")
        poll.assert_not_called()

    def test_cancel_clears_the_pending_login(self):
        self._start()
        response = self.call_api(
            "post", "api_provider_connect_cancel", args=("trakt",), headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertIsNone(pending_auth.get("trakt_device_auth", self.user1.pk))

    def test_start_failure_is_reported(self):
        with patch(
            "integrations.views.trakt.request_device_code",
            side_effect=MediaImportError("Could not start Trakt authorization."),
        ):
            response = self.call_api(
                "post", "api_provider_connect_start", args=("trakt",), headers=self.auth_headers,
                payload={},
            )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_pending_state_is_per_user(self):
        self._start()
        other = self.call_api(
            "get", "api_provider_connect_poll", args=("trakt",), headers=self.auth_headers2,
        )
        self.assertEqual(other.json()["status"], "expired")
        self.assertIsNotNone(pending_auth.get("trakt_device_auth", self.user1.pk))


class StorytellerConnectTests(FloppyApiTestCase):
    """Storyteller's device login, driven through JSON."""

    def _start(self):
        data = {
            "device_code": "dev", "user_code": "ABCD", "expires_in": 600, "interval": 5,
            "verification_uri": "https://story.example/device",
            "verification_uri_complete": "https://story.example/device?code=ABCD",
        }
        with patch("integrations.views.StorytellerClient") as client:
            client.return_value.start_device_auth.return_value = data
            return self.call_api(
                "post", "api_provider_connect_start", args=("storyteller",),
                headers=self.auth_headers, payload={"serverUrl": "https://story.example/"},
            )

    def _poll(self, token=None, error=None, status=400):
        with patch("integrations.views.StorytellerClient") as client:
            client.return_value.poll_device_token.return_value = (
                {"access_token": token} if token else {"error": error},
                200 if token else status,
            )
            with patch("integrations.views.tasks.import_storyteller.delay"):
                return self.call_api(
                    "get", "api_provider_connect_poll", args=("storyteller",), headers=self.auth_headers,
                )

    def test_start_pending_connected_denied(self):
        data = self._start().json()
        self.assertEqual(data["kind"], "device")
        self.assertEqual(data["userCode"], "ABCD")
        self.assertEqual(data["openUrl"], "https://story.example/device?code=ABCD")
        self.assertEqual(self._poll(error="authorization_pending").json()["status"], "pending")
        denied = self._poll(error="access_denied", status=403).json()
        self.assertEqual(denied["status"], "denied")
        self.assertIsNone(pending_auth.get("storyteller_pending_auth", self.user1.pk))

        self._start()
        self.assertEqual(self._poll(token="tok").json()["status"], "connected")
        self.user1.refresh_from_db()
        self.assertTrue(hasattr(self.user1, "storyteller_account"))

    def test_expired_and_idle(self):
        self.assertEqual(self._poll(error="x").json()["status"], "idle")
        self._start()
        state = pending_auth.get("storyteller_pending_auth", self.user1.pk)
        state["expires_at"] = (timezone.now() - timedelta(seconds=1)).isoformat()
        pending_auth.put("storyteller_pending_auth", self.user1.pk, state)
        self.assertEqual(self._poll(error="x").json()["status"], "expired")

    def test_missing_server_url_is_an_error(self):
        response = self.call_api(
            "post", "api_provider_connect_start", args=("storyteller",),
            headers=self.auth_headers, payload={},
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)


class WeTrakrConnectTests(FloppyApiTestCase):
    """WeTrakr keeps its pending code on the account row."""

    def test_start_poll_pending_approved_and_failed(self):
        flow = {
            "device_code": "dc", "user_code": "WT-1", "verification_url": "https://wetrakr.com/link",
            "interval": 5, "expires_in": 600,
        }
        with (
            patch("integrations.wetrakr_views.wetrakr_api.client_id_for", return_value="cid"),
            patch("integrations.wetrakr_views.wetrakr_api.start_device_flow", return_value=flow),
        ):
            data = self.call_api(
                "post", "api_provider_connect_start", args=("wetrakr",), headers=self.auth_headers, payload={},
            ).json()
        self.assertEqual(data["kind"], "device")
        self.assertEqual(data["userCode"], "WT-1")

        poll = lambda: self.call_api(  # noqa: E731
            "get", "api_provider_connect_poll", args=("wetrakr",), headers=self.auth_headers,
        ).json()
        with patch("integrations.wetrakr_views.wetrakr_api.poll_device_flow", return_value=("pending", None)):
            self.assertEqual(poll()["status"], "pending")
        from django.core.cache import cache

        cache.delete(f"wetrakr_poll:{self.user1.pk}")
        with patch(
            "integrations.wetrakr_views.wetrakr_api.poll_device_flow",
            return_value=("failed", "The login was denied."),
        ):
            self.assertEqual(poll()["status"], "denied")

    def test_start_without_app_key_is_an_error(self):
        with patch("integrations.wetrakr_views.wetrakr_api.client_id_for", return_value=""):
            response = self.call_api(
                "post", "api_provider_connect_start", args=("wetrakr",), headers=self.auth_headers, payload={},
            )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)


class RedirectConnectTests(FloppyApiTestCase):
    """Redirect providers return an authorize URL and finish on the web callback."""

    def _start(self, slug, payload=None):
        return self.call_api(
            "post", "api_provider_connect_start", args=(slug,), headers=self.auth_headers,
            payload={"mode": "new", "frequency": "once", "time": "00:00", **(payload or {})},
        )

    def test_return_address_is_restricted(self):
        for bad in ("https://evil.example/x", "//evil.example", "javascript:alert(1)",
                    "other-app://connect", "floppy-native-proof-x://a"):
            response = self._start("anilist", {"returnTo": bad})
            self.assertEqual(response.status_code, HTTP.BAD_REQUEST, bad)

    def test_unknown_and_unsupported_providers(self):
        self.assertEqual(self._start("nope").status_code, HTTP.NOT_FOUND)
        self.assertEqual(self._start("jellyfin").status_code, HTTP.NOT_FOUND)
        bad_mode = self._start("anilist", {"mode": "wipe"})
        self.assertEqual(bad_mode.status_code, HTTP.BAD_REQUEST)

    def test_anilist_state_is_user_bound_and_returns_to_the_app(self):
        data = self._start("anilist", {"returnTo": APP_LINK}).json()
        self.assertEqual(data["kind"], "redirect")
        token = parse_qs(urlsplit(data["authorizeUrl"]).query)["state"][0]
        # A native start never writes a browser session.
        self.assertNotIn(token, self.client.session)
        callback = reverse("import_anilist_private")
        # Another user's browser cannot consume the state.
        self.client.force_login(self.user2)
        with patch("integrations.views.anilist.get_token") as exchange:
            refused = self.client.get(callback, {"state": token, "code": "c"})
        exchange.assert_not_called()
        self.assertEqual(refused.status_code, HTTP.FOUND)
        self.assertNotEqual(refused["Location"], APP_LINK)
        # The state was single use even for the wrong user, so start again.
        data = self._start("anilist", {"returnTo": APP_LINK}).json()
        token = parse_qs(urlsplit(data["authorizeUrl"]).query)["state"][0]
        self.client.force_login(self.user1)
        with (
            patch(
                "integrations.views.anilist.get_token",
                return_value={"access_token": "t", "username": "ani"},
            ),
            patch("integrations.views.tasks.import_anilist.delay"),
        ):
            done = self.client.get(callback, {"state": token, "code": "c"})
        self.assertEqual(done.status_code, HTTP.FOUND)
        self.assertEqual(done["Location"], APP_LINK)
        # Replay is rejected.
        with patch("integrations.views.anilist.get_token") as exchange:
            self.client.get(callback, {"state": token, "code": "c"})
        exchange.assert_not_called()

    def test_plex_start_returns_the_auth_url(self):
        pin = {"id": 7, "code": "pincode"}
        with patch("integrations.views.plex_api.create_pin", return_value=pin):
            data = self._start("plex", {"returnTo": "/settings/providers/plex"}).json()
        self.assertEqual(data["kind"], "redirect")
        self.assertIn("pincode", data["authorizeUrl"])

    def test_tmdb_start_and_return(self):
        expires = (timezone.now() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S UTC")
        client = MagicMock()
        client.return_value.request.return_value = {"request_token": "tok", "expires_at": expires}
        with patch("integrations.tmdb_views.TMDbClient", client):
            data = self._start("tmdb", {"returnTo": APP_LINK}).json()
        self.assertEqual(data["kind"], "redirect")
        self.assertIn("themoviedb.org/authenticate/tok", data["authorizeUrl"])
        self.client.force_login(self.user1)
        denied = self.client.get(reverse("tmdb_callback"), {"request_token": "tok", "approved": "false"})
        self.assertEqual(denied["Location"], APP_LINK)

    def test_scoped_tokens_cannot_reach_connect(self):
        from integrations.models import IntegrationToken

        _token, raw = IntegrationToken.generate(user=self.user1, name="s", scopes=["user:write"])
        response = self.call_api(
            "post", "api_provider_connect_start", args=("anilist",),
            headers={"HTTP_X_API_KEY": raw}, payload={},
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)
