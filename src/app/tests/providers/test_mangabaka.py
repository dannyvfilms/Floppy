from unittest.mock import MagicMock, patch

import requests
from django.conf import settings
from django.core.cache import cache
from django.test import TestCase

from app.models import MediaTypes, Sources
from app.providers import mangabaka, services

SEARCH_ITEM = {
    "id": 20703,
    "title": "Overlord",
    "type": "manga",
    "year": 2014,
    "content_rating": "suggestive",
    "cover": {
        "raw": {"url": "https://images.mangabaka.dev/b/3/5/3/3/7/0/5/0e6c"},
        "x250": {"x1": "https://cdn.mangabaka.dev/imgproxy/plain/x250@1/abc"},
    },
}

SERIES_DETAIL = {
    "id": 20703,
    "title": "Overlord",
    "type": "manga",
    "year": 2014,
    "status": "completed",
    "description": "Momonga stays logged in after the servers go dark.",
    "genres": ["action", "adventure", "fantasy"],
    "rating": 79.55,
    "total_chapters": "91",
    "final_volume": "19",
    "authors": ["Kugane Maruyama", "Oshio Satoshi"],
    "artists": ["Fugin Miyama"],
    "canonical_url": "https://mangabaka.org/manga/20703/Overlord",
    "cover": {
        "raw": {"url": "https://images.mangabaka.dev/b/3/5/3/3/7/0/5/0e6c"},
        "x250": {"x1": "https://cdn.mangabaka.dev/imgproxy/plain/x250@1/abc"},
    },
    "content_rating": "suggestive",
    "relationships_v2": [
        {
            "id": "019f3c99-fb6c-7019-9e04-60922eee9359",
            "to_series_id": 589980,
            "relation_type": "parody",
        },
    ],
}


def _http_error(status_code):
    error = requests.exceptions.HTTPError()
    error.response = MagicMock(status_code=status_code)
    return error


class TestMangaBakaSearch(TestCase):
    """Test MangaBaka search normalization and caching."""

    def setUp(self):
        cache.clear()

    @patch("app.providers.mangabaka.services.api_request")
    def test_search_returns_results(self, mock_api_request):
        mock_api_request.return_value = {
            "status": 200,
            "pagination": {"count": 84, "page": 1, "limit": 30},
            "data": [SEARCH_ITEM],
        }

        data = mangabaka.search("Overlord", 1)

        result = data["results"][0]
        self.assertEqual(result["media_id"], "20703")
        self.assertEqual(result["source"], "mangabaka")
        self.assertEqual(result["media_type"], "manga")
        self.assertEqual(result["title"], "Overlord")
        self.assertEqual(data["total_results"], 84)

    @patch("app.providers.mangabaka.services.api_request")
    def test_search_empty(self, mock_api_request):
        mock_api_request.return_value = {
            "status": 200,
            "pagination": {"count": 0, "page": 1, "limit": 30},
            "data": [],
        }

        data = mangabaka.search("zzzz-no-match", 1)

        self.assertEqual(data["results"], [])
        self.assertEqual(data["total_results"], 0)

    @patch("app.providers.mangabaka.services.api_request")
    def test_search_caches(self, mock_api_request):
        mock_api_request.return_value = {
            "status": 200,
            "pagination": {"count": 1, "page": 1, "limit": 30},
            "data": [SEARCH_ITEM],
        }

        mangabaka.search("Overlord", 1)
        mangabaka.search("Overlord", 1)

        self.assertEqual(mock_api_request.call_count, 1)

    @patch("app.providers.mangabaka.services.api_request")
    def test_search_filters_nsfw_by_default(self, mock_api_request):
        mock_api_request.return_value = {
            "status": 200,
            "pagination": {"count": 1, "page": 1, "limit": 30},
            "data": [SEARCH_ITEM],
        }

        mangabaka.search("Overlord", 1)

        _, kwargs = mock_api_request.call_args
        self.assertEqual(kwargs["params"]["content_rating"], "safe")


class TestMangaBakaMetadata(TestCase):
    """Test MangaBaka series metadata normalization and caching."""

    def setUp(self):
        cache.clear()

    @patch("app.providers.mangabaka.services.api_request")
    def test_manga_metadata(self, mock_api_request):
        mock_api_request.return_value = {"status": 200, "data": SERIES_DETAIL}

        data = mangabaka.manga("20703")

        self.assertEqual(data["media_id"], "20703")
        self.assertEqual(data["source"], "mangabaka")
        self.assertEqual(
            data["source_url"],
            "https://mangabaka.org/manga/20703/Overlord",
        )
        self.assertEqual(data["media_type"], MediaTypes.MANGA.value)
        self.assertEqual(data["title"], "Overlord")
        self.assertEqual(data["score"], round(79.55 / 10, 1))
        self.assertEqual(data["max_progress"], 91)
        self.assertEqual(data["details"]["format"], "manga")
        self.assertEqual(
            data["details"]["authors"],
            ["Kugane Maruyama", "Oshio Satoshi", "Fugin Miyama"],
        )
        self.assertEqual(data["genres"], ["action", "adventure", "fantasy"])
        self.assertNotEqual(data["image"], settings.IMG_NONE)
        self.assertIsNone(data["score_count"])

    @patch("app.providers.mangabaka.services.api_request")
    def test_manga_404(self, mock_api_request):
        mock_api_request.side_effect = _http_error(404)

        with self.assertRaises(services.ProviderAPIError) as cm:
            mangabaka.manga("999999999")

        self.assertEqual(cm.exception.provider, Sources.MANGABAKA.value)

    @patch("app.providers.mangabaka.services.api_request")
    def test_metadata_caches(self, mock_api_request):
        mock_api_request.return_value = {"status": 200, "data": SERIES_DETAIL}

        mangabaka.manga("20703")
        mangabaka.manga("20703")

        self.assertEqual(mock_api_request.call_count, 1)


class TestMangaBakaHelpers(TestCase):
    """Unit tests for MangaBaka normalization helpers."""

    def test_get_score_scales_from_100(self):
        self.assertEqual(mangabaka.get_score(79.55), 8.0)
        self.assertIsNone(mangabaka.get_score(0))
        self.assertIsNone(mangabaka.get_score(None))

    def test_parse_int_string(self):
        self.assertEqual(mangabaka._parse_int("91"), 91)
        self.assertIsNone(mangabaka._parse_int(None))
        self.assertIsNone(mangabaka._parse_int(""))

    def test_get_image_url_fallback(self):
        self.assertEqual(mangabaka.get_image_url({}), settings.IMG_NONE)
        self.assertEqual(
            mangabaka.get_image_url({"cover": {"raw": {"url": "https://x/y"}}}),
            "https://x/y",
        )
