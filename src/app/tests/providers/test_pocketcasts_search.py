from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from app.providers import pocketcasts


@override_settings(PER_PAGE=2)
class PocketCastsSearchPaginationTests(TestCase):
    """iTunes ignores `offset` for podcasts, so pages are sliced locally (#1817)."""

    def setUp(self):
        cache.clear()

    @patch("app.providers.pocketcasts._directory_candidates", return_value=[])
    @patch("app.providers.pocketcasts.requests.get")
    def test_pages_return_different_results(self, mock_get, _candidates):
        response = MagicMock()
        response.json.return_value = {
            "results": [
                {"collectionId": i, "collectionName": f"Show {i}"} for i in range(1, 4)
            ],
        }
        mock_get.return_value = response

        first = pocketcasts.search("show", 1)
        second = pocketcasts.search("show", 2)

        self.assertEqual([r["media_id"] for r in first["results"]], ["1", "2"])
        self.assertEqual([r["media_id"] for r in second["results"]], ["3"])
        self.assertEqual(first["total_pages"], 2)


@override_settings(PER_PAGE=10)
class PocketCastsSearchDiscoveryTests(TestCase):
    """Duplicate listings collapse and directory-only shows are found (#1829)."""

    def setUp(self):
        cache.clear()

    @patch("app.providers.pocketcasts.requests.post")
    @patch("app.providers.pocketcasts.requests.get")
    def test_duplicates_collapse_and_directory_show_is_added(self, mock_get, mock_post):
        listing = [
            {"collectionId": 1, "collectionName": "Babies", "artistName": "A"},
            {"collectionId": 2, "collectionName": "Babies", "artistName": "A"},
        ]
        target = {
            "collectionId": 9,
            "collectionName": "Blackout",
            "artistName": "QCODE",
        }

        def get(url, params=None, **kwargs):
            response = MagicMock()
            is_lookup = params["limit"] == 5
            response.json.return_value = {"results": [target] if is_lookup else listing}
            return response

        mock_get.side_effect = get
        mock_post.return_value.json.return_value = [
            {"title": "Blackout", "author": "QCODE"},
        ]

        data = pocketcasts.search("blackou", 1)

        self.assertEqual([r["media_id"] for r in data["results"]], ["9", "1"])
