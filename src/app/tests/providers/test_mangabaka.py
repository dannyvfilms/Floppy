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

RELATED_SERIES = {
    "id": 5469,
    "title": "Overlord New World",
    "type": "manga",
    "year": 2024,
    "cover": {
        "raw": {"url": "https://images.mangabaka.dev/related/5469"},
        "x350": {"x1": "https://cdn.mangabaka.dev/imgproxy/plain/x350@1/rel"},
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
            "to_series_id": 5469,
            "relation_type": "sequel",
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
        mock_api_request.side_effect = [
            {"status": 200, "data": SERIES_DETAIL},
            {"status": 200, "data": RELATED_SERIES},
        ]

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
        self.assertEqual(data["genres"], ["Action", "Adventure", "Fantasy"])
        self.assertNotEqual(data["image"], settings.IMG_NONE)
        self.assertIsNone(data["score_count"])
        related = data["related"]["related_manga"]
        self.assertEqual(len(related), 1)
        self.assertEqual(related[0]["title"], "Overlord New World")
        self.assertEqual(related[0]["media_id"], "5469")
        self.assertEqual(related[0]["relation_type"], "sequel")

    @patch("app.providers.mangabaka.services.api_request")
    def test_manga_404(self, mock_api_request):
        mock_api_request.side_effect = _http_error(404)

        with self.assertRaises(services.ProviderAPIError) as cm:
            mangabaka.manga("999999999")

        self.assertEqual(cm.exception.provider, Sources.MANGABAKA.value)

    @patch("app.providers.mangabaka.services.api_request")
    def test_metadata_caches(self, mock_api_request):
        mock_api_request.side_effect = [
            {"status": 200, "data": SERIES_DETAIL},
            {"status": 200, "data": RELATED_SERIES},
        ]

        mangabaka.manga("20703")
        mangabaka.manga("20703")

        self.assertEqual(mock_api_request.call_count, 2)

    @patch("app.providers.mangabaka.services.api_request")
    def test_related_skips_failed_fetch(self, mock_api_request):
        mock_api_request.side_effect = [
            {"status": 200, "data": SERIES_DETAIL},
            _http_error(404),
        ]

        data = mangabaka.manga("20703")

        self.assertEqual(data["related"]["related_manga"], [])

    def test_related_keeps_only_official_types(self):
        relationships = [
            {"to_series_id": 1, "relation_type": "main"},
            {"to_series_id": 2, "relation_type": "side_story"},
            {"to_series_id": 3, "relation_type": "sequel"},
            {"to_series_id": 4, "relation_type": "prequel"},
            {"to_series_id": 5, "relation_type": "source"},
            {"to_series_id": 6, "relation_type": "spin_off"},
            {"to_series_id": 7, "relation_type": "parody"},
            {"to_series_id": 8, "relation_type": "other"},
            {"to_series_id": 9, "relation_type": None},
        ]

        with patch(
            "app.providers.mangabaka.services.api_request",
        ) as mock_api_request:
            mock_api_request.side_effect = lambda *a, **k: {
                "status": 200,
                "data": {
                    "id": 1,
                    "title": "Related",
                    "cover": {},
                    "year": 2020,
                },
            }

            related = mangabaka.get_related(relationships)

        self.assertEqual(len(related), 6)
        self.assertEqual(mock_api_request.call_count, 6)


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
        series = {
            "cover": {
                "raw": {"url": "https://x/raw"},
                "x350": {"x1": "https://x/350"},
            },
        }
        self.assertEqual(mangabaka.get_image_url(series), "https://x/raw")
        self.assertEqual(
            mangabaka.get_image_url(series, thumbnail=True),
            "https://x/350",
        )

    def test_get_genres_normalizes_display(self):
        self.assertEqual(
            mangabaka.get_genres(["action", "slice_of_life", "school_life"]),
            ["Action", "Slice Of Life", "School Life"],
        )
        self.assertIsNone(mangabaka.get_genres([]))
        self.assertIsNone(mangabaka.get_genres(None))
