import pickle
from unittest.mock import Mock, patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from app import network_policy
from app.providers import services


class ProviderNetworkPolicyTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        network_policy.install_provider_network_guard()

    @staticmethod
    def _response(payload=None):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = payload or {"ok": True}
        return response

    @override_settings(FLOPPY_NETWORK_MODE="offline")
    def test_offline_mode_stops_before_http_session(self):
        with patch.object(services.session, "get") as session_get:
            with self.assertRaises(services.ProviderAPIError) as raised:
                services.api_request(
                    "tvdb",
                    "GET",
                    "https://example.invalid/private?token=secret",
                )

        session_get.assert_not_called()
        self.assertIsInstance(raised.exception, services.ProviderNetworkUnavailable)
        self.assertNotIn("example.invalid", str(raised.exception))
        self.assertNotIn("secret", str(raised.exception))

    @override_settings(
        FLOPPY_NETWORK_MODE="restricted",
        FLOPPY_NETWORK_ALLOWLIST="tmdb, igdb",
    )
    def test_restricted_mode_denies_unlisted_provider(self):
        with patch.object(services.session, "get") as session_get:
            with self.assertRaises(services.ProviderNetworkUnavailable):
                services.api_request("tvdb", "GET", "https://example.invalid")

        session_get.assert_not_called()

    @override_settings(
        FLOPPY_NETWORK_MODE="restricted",
        FLOPPY_NETWORK_ALLOWLIST=" TVDB, igdb ",
    )
    def test_restricted_mode_allows_exact_normalized_provider(self):
        response = self._response({"provider": "tvdb"})
        with patch.object(services.session, "get", return_value=response) as session_get:
            result = services.api_request("tvdb", "GET", "https://example.invalid")

        self.assertEqual(result, {"provider": "tvdb"})
        session_get.assert_called_once()

    @override_settings(
        FLOPPY_NETWORK_MODE="restricted",
        FLOPPY_NETWORK_ALLOWLIST="tv",
    )
    def test_restricted_mode_does_not_use_partial_provider_matches(self):
        with patch.object(services.session, "get") as session_get:
            with self.assertRaises(services.ProviderNetworkUnavailable):
                services.api_request("tvdb", "GET", "https://example.invalid")

        session_get.assert_not_called()

    @override_settings(FLOPPY_NETWORK_MODE="online")
    def test_online_mode_keeps_existing_request_behavior(self):
        response = self._response()
        with patch.object(services.session, "get", return_value=response) as session_get:
            result = services.api_request("tvdb", "GET", "https://example.invalid")

        self.assertEqual(result, {"ok": True})
        session_get.assert_called_once()

    @override_settings(FLOPPY_NETWORK_MODE="unexpected")
    def test_invalid_mode_fails_closed_before_http_session(self):
        with patch.object(services.session, "get") as session_get:
            with self.assertRaises(ImproperlyConfigured):
                services.api_request("tvdb", "GET", "https://example.invalid")

        session_get.assert_not_called()

    def test_explicit_invalid_mode_fails_closed(self):
        with self.assertRaises(ImproperlyConfigured):
            network_policy.provider_access_allowed("tvdb", mode="unexpected")

    @override_settings(
        FLOPPY_NETWORK_MODE="restricted",
        FLOPPY_NETWORK_ALLOWLIST="https://api.example.invalid",
    )
    def test_invalid_allowlist_entry_fails_closed(self):
        with patch.object(services.session, "get") as session_get:
            with self.assertRaises(ImproperlyConfigured):
                services.api_request("tvdb", "GET", "https://example.invalid")

        session_get.assert_not_called()

    def test_blocked_provider_error_serializes_without_request_data(self):
        error = network_policy.ProviderNetworkUnavailable("tvdb", "offline")

        restored = pickle.loads(pickle.dumps(error))

        self.assertIsInstance(restored, network_policy.ProviderNetworkUnavailable)
        self.assertEqual(restored.provider, "tvdb")
        self.assertEqual(restored.mode, "offline")
        self.assertNotIn("http", str(restored))

    def test_guard_installation_is_idempotent(self):
        first = network_policy.install_provider_network_guard()
        second = network_policy.install_provider_network_guard()

        self.assertIs(first, second)
        self.assertIs(first, services.api_request)
