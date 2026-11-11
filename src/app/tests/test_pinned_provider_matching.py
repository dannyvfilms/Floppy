"""Pinned watch providers must match catalog names regardless of padding (#1873)."""

from types import SimpleNamespace

from django.test import SimpleTestCase

from app.providers import tmdb


def _item(name):
    return SimpleNamespace(
        watch_providers={
            "US": {
                "flatrate": [
                    {"provider_id": 1, "provider_name": name, "logo_path": "/x.png"},
                ],
            },
        },
    )


class PinnedProviderMatchTests(SimpleTestCase):
    """The pin endpoint stores trimmed names; catalog names may carry padding."""

    def test_trimmed_pin_matches_padded_catalog_name(self):
        matches = tmdb.pinned_provider_matches(_item(" Max"), ["Max"])

        self.assertEqual([m["provider_name"] for m in matches], [" Max"])

    def test_padded_stored_pin_still_matches(self):
        matches = tmdb.pinned_provider_matches(_item("Max"), [" Max "])

        self.assertEqual(len(matches), 1)

    def test_other_provider_does_not_match(self):
        self.assertEqual(tmdb.pinned_provider_matches(_item("Hulu"), ["Max"]), [])
