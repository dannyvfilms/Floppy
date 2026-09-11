"""Declarative remote add-ons: manifest validation and registration."""

import json
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from requests import RequestException

from integrations import addons
from integrations.addon_manifest import InvalidManifestError, parse_manifest
from integrations.models import RemoteAddon
from integrations.safe_fetch import UnsafeUrlError

VALID = {
    "id": "org.example.addon",
    "version": "1.0.0",
    "name": "Example",
    "description": "An example add-on.",
    "resources": ["catalog", "meta"],
    "types": ["movie", "series"],
    "catalogs": [{"type": "movie", "id": "top", "name": "Top"}],
}


class ManifestValidationTests(TestCase):
    """A manifest is data, and only known fields survive."""

    def assert_refused(self, document, reason_code):
        """Assert a manifest is refused with a stable reason code."""
        with self.assertRaises(InvalidManifestError) as caught:
            parse_manifest(json.dumps(document))
        self.assertEqual(caught.exception.reason_code, reason_code)

    def test_a_valid_manifest_parses(self):
        """The ordinary case works."""
        parsed = parse_manifest(json.dumps(VALID))

        self.assertEqual(parsed["id"], "org.example.addon")
        self.assertEqual(parsed["resources"], ["catalog", "meta"])
        self.assertEqual(parsed["catalogs"][0]["id"], "top")

    def test_unknown_fields_are_dropped(self):
        """A manifest cannot smuggle a field a later version might honour."""
        parsed = parse_manifest(
            json.dumps({**VALID, "behaviorHints": {"p2p": True}, "script": "evil()"}),
        )

        self.assertNotIn("script", parsed)
        self.assertNotIn("behaviorHints", parsed)

    def test_non_json_is_refused(self):
        """A host that returns HTML is not an add-on."""
        with self.assertRaises(InvalidManifestError) as caught:
            parse_manifest("<html>nope</html>")
        self.assertEqual(caught.exception.reason_code, "manifest_not_json")

    def test_a_json_array_is_refused(self):
        """A manifest must be an object."""
        self.assert_refused([1, 2, 3], "manifest_not_object")

    def test_missing_required_fields_are_refused(self):
        """id, version and name are the minimum identity."""
        for field in ("id", "version", "name"):
            with self.subTest(field=field):
                document = {k: v for k, v in VALID.items() if k != field}
                self.assert_refused(document, "manifest_missing_field")

    def test_an_addon_with_no_usable_resource_is_refused(self):
        """Registering something Floppy can never call helps nobody."""
        self.assert_refused({**VALID, "resources": ["nonsense"]}, "manifest_no_usable_resource")

    def test_unsupported_resources_are_dropped_not_fatal(self):
        """An add-on that also offers streams is still usable for catalogs."""
        parsed = parse_manifest(
            json.dumps({**VALID, "resources": ["catalog", "wormhole"]}),
        )

        self.assertEqual(parsed["resources"], ["catalog"])

    def test_an_oversize_manifest_is_refused(self):
        """A huge document must not be parsed at all."""
        payload = json.dumps({**VALID, "description": "x" * 300000})
        with self.assertRaises(InvalidManifestError) as caught:
            parse_manifest(payload.encode("utf-8"))
        self.assertEqual(caught.exception.reason_code, "manifest_too_large")

    def test_strings_are_bounded(self):
        """A long name cannot blow past the column it is stored in."""
        parsed = parse_manifest(json.dumps({**VALID, "name": "n" * 5000}))

        self.assertLessEqual(len(parsed["name"]), 512)

    def test_one_malformed_catalog_does_not_condemn_the_addon(self):
        """A partly broken catalog list still yields the usable entries."""
        parsed = parse_manifest(
            json.dumps({**VALID, "catalogs": [{"type": "movie"}, VALID["catalogs"][0]]}),
        )

        self.assertEqual(len(parsed["catalogs"]), 1)

    def test_invalid_utf8_is_refused(self):
        """Bytes that are not text are not a manifest."""
        with self.assertRaises(InvalidManifestError) as caught:
            parse_manifest(b"\xff\xfe not utf8")
        self.assertEqual(caught.exception.reason_code, "manifest_not_json")


class RegistrationTests(TestCase):
    """Registration fetches through the boundary and stores only what validated."""

    def setUp(self):
        """Create a user."""
        self.user = get_user_model().objects.create_user(username="addons")

    def fetch_returning(self, body, status=200):
        """Patch safe_fetch to return a canned response."""
        response = Mock(status_code=status)
        return patch.object(
            addons,
            "safe_fetch",
            return_value=(response, json.dumps(body).encode("utf-8")),
        )

    def test_registering_stores_the_validated_manifest(self):
        """The stored manifest is the projection, not the raw document."""
        with self.fetch_returning({**VALID, "script": "evil()"}):
            addon = addons.register_addon(self.user, "https://example.com/manifest.json")

        self.assertEqual(addon.addon_id, "org.example.addon")
        self.assertNotIn("script", addon.manifest)

    def test_an_unsafe_url_is_not_stored(self):
        """A registry full of unreachable entries helps nobody."""
        with patch.object(
            addons,
            "safe_fetch",
            side_effect=UnsafeUrlError("forbidden_address", "no"),
        ), self.assertRaises(UnsafeUrlError):
            addons.register_addon(self.user, "https://evil.example/manifest.json")

        self.assertFalse(RemoteAddon.objects.exists())

    def test_an_invalid_manifest_is_not_stored(self):
        """Validation happens before anything is written."""
        with self.fetch_returning({"nope": True}), self.assertRaises(
            InvalidManifestError,
        ):
            addons.register_addon(self.user, "https://example.com/manifest.json")

        self.assertFalse(RemoteAddon.objects.exists())

    def test_registering_twice_updates_rather_than_duplicates(self):
        """Re-adding the same URL is a refresh, not a second row."""
        with self.fetch_returning(VALID):
            addons.register_addon(self.user, "https://example.com/manifest.json")
        with self.fetch_returning({**VALID, "version": "2.0.0"}):
            addons.register_addon(self.user, "https://example.com/manifest.json")

        self.assertEqual(RemoteAddon.objects.count(), 1)
        self.assertEqual(RemoteAddon.objects.get().version, "2.0.0")


class RefreshTests(TestCase):
    """A refresh never raises, and never discards a working manifest."""

    def setUp(self):
        """Register one add-on."""
        self.user = get_user_model().objects.create_user(username="refresh")
        self.addon = RemoteAddon.objects.create(
            user=self.user,
            manifest_url="https://example.com/manifest.json",
            addon_id="org.example.addon",
            name="Example",
            version="1.0.0",
            manifest=dict(VALID),
        )

    def test_a_transport_failure_keeps_the_last_good_manifest(self):
        """One unreachable host must not empty a working install."""
        with patch.object(addons, "safe_fetch", side_effect=RequestException("down")):
            addons.refresh_addon(self.addon)

        self.addon.refresh_from_db()
        self.assertEqual(self.addon.last_status, "error")
        self.assertEqual(self.addon.last_error_code, "transport_error")
        self.assertEqual(self.addon.manifest["id"], "org.example.addon")

    def test_an_unsafe_redirect_is_recorded_as_a_reason_code(self):
        """The failure is stored as a code, never as a URL or response body."""
        with patch.object(
            addons,
            "safe_fetch",
            side_effect=UnsafeUrlError("forbidden_address", "no"),
        ):
            addons.refresh_addon(self.addon)

        self.addon.refresh_from_db()
        self.assertEqual(self.addon.last_error_code, "forbidden_address")
        self.assertNotIn("example.com", self.addon.last_error_code)

    def test_a_successful_refresh_updates_the_manifest(self):
        """The happy path moves the version forward."""
        response = Mock(status_code=200)
        with patch.object(
            addons,
            "safe_fetch",
            return_value=(response, json.dumps({**VALID, "version": "3.0.0"}).encode()),
        ):
            addons.refresh_addon(self.addon)

        self.addon.refresh_from_db()
        self.assertEqual(self.addon.version, "3.0.0")
        self.assertEqual(self.addon.last_status, "ok")
        self.assertEqual(self.addon.last_error_code, "")

    def test_a_bad_status_is_recorded(self):
        """A 500 from the host is a visible failure, not a silent one."""
        response = Mock(status_code=500)
        with patch.object(addons, "safe_fetch", return_value=(response, b"{}")):
            addons.refresh_addon(self.addon)

        self.addon.refresh_from_db()
        self.assertEqual(self.addon.last_error_code, "bad_status")


class MaskingTests(TestCase):
    """A configured URL can carry a secret in its path."""

    def test_the_path_is_masked(self):
        """The credential in the path must not be shown back."""
        user = get_user_model().objects.create_user(username="mask")
        addon = RemoteAddon(
            user=user,
            manifest_url="https://example.com/secret-token/manifest.json",
        )

        masked = addon.masked_url()

        self.assertNotIn("secret-token", masked)
        self.assertIn("example.com", masked)
