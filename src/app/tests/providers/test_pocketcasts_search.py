from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from app.providers import pocketcasts


@override_settings(PER_PAGE=2)
class PocketCastsSearchPaginationTests(TestCase):
    """iTunes ignores `offset` for podcasts, so pages are sliced locally (#1817)."""

    def setUp(self):
        cache.clear()

    @patch("app.providers.pocketcasts.requests.get")
    def test_pages_return_different_results(self, mock_get):
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
