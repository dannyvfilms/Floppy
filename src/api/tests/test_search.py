from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse

from api.helpers import check_source_type
from app.models import Item, MediaTypes, Sources

from .base import FloppyApiTestCase
from .helpers import check_pagination_structure


class SearchTests(FloppyApiTestCase):
    """Validate search endpoint contracts."""

    def test_book_googlebooks_source_is_valid(self):
        """Google Books is an accepted source for book API routes."""
        self.assertTrue(check_source_type("book", "googlebooks"))

    def test_search_rejects_invalid_media_type(self):
        """Search endpoint should reject unknown media types."""
        response = self.call_api(
            "get",
            "api_search_provider",
            args=("invalid",),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            "unsupported media type", response.json().get("detail", "").lower()
        )

    def test_search_rejects_children_media_types(self):
        """Search endpoint should reject season and episode media types."""
        season_response = self.call_api(
            "get",
            "api_search_provider",
            args=("season",),
            headers=self.auth_headers,
        )
        self.assertEqual(season_response.status_code, 400)

        episode_response = self.call_api(
            "get",
            "api_search_provider",
            args=("episode",),
            headers=self.auth_headers,
        )
        self.assertEqual(episode_response.status_code, 400)

    @patch("api.views.services.search")
    def test_search_returns_paginated_payload(self, mock_search):
        """Search endpoint should return paginated response with provider data."""
        mock_search.return_value = {
            "results": [
                {
                    "media_id": 1,
                    "source": "tmdb",
                    "media_type": "movie",
                    "title": "Integer ID",
                    "image": None,
                    "provider_extension": "preserved",
                },
                {
                    "media_id": "tt0133093",
                    "source": "imdb",
                    "media_type": "movie",
                    "title": "String ID",
                    "image": "https://example.test/poster.jpg",
                },
            ],
            "total_results": 2,
            "total_pages": 1,
        }

        response = self.call_api(
            "get",
            "api_search_provider",
            args=("movie",),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("pagination", payload)
        self.assertIn("results", payload)
        check_pagination_structure(self, payload["pagination"])
        self.assertIsInstance(payload["results"][0]["media_id"], int)
        self.assertIsInstance(payload["results"][1]["media_id"], str)
        self.assertEqual(payload["results"][0]["source"], "tmdb")
        self.assertEqual(payload["results"][0]["provider_extension"], "preserved")

    @patch("api.views.services.search")
    def test_search_passes_query_params_to_provider(self, mock_search):
        """Search endpoint should forward search/source/limit/offset and user."""
        mock_search.return_value = {
            "results": [{"id": 1, "title": "Example"}],
            "total_results": 1,
            "total_pages": 1,
        }

        response = self.client.get(
            reverse("api_search_provider", args=("movie",))
            + "?search=matrix&source=tmdb&limit=5&offset=2",
            **self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        mock_search.assert_called_once_with(
            "movie",
            "matrix",
            1,
            "tmdb",
            limit=5,
            offset=2,
            user=self.user1,
            language="en",
        )

        payload = response.json()
        self.assertEqual(payload["pagination"]["limit"], 5)
        self.assertEqual(payload["pagination"]["offset"], 2)

    @patch("api.views.services.search")
    def test_search_defaults_to_the_users_preferred_source(self, mock_search):
        """An omitted source follows the user's Settings > Metadata choice."""
        self.user1.book_metadata_source_default = Sources.OPENLIBRARY.value
        self.user1.save(update_fields=["book_metadata_source_default"])
        mock_search.return_value = {
            "results": [],
            "total_results": 0,
            "total_pages": 1,
        }

        response = self.call_api(
            "get",
            "api_search_provider",
            args=("book",),
            params={"search": "scientific ontology"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_search.call_args.args[3], Sources.OPENLIBRARY.value)

    @override_settings(HARDCOVER_API="")
    @patch("api.views.services.search")
    def test_search_skips_an_unconfigured_default_book_source(self, mock_search):
        """No Hardcover token means books search a provider that can answer."""
        mock_search.return_value = {
            "results": [],
            "total_results": 0,
            "total_pages": 1,
        }

        response = self.call_api(
            "get",
            "api_search_provider",
            args=("book",),
            params={"search": "scientific ontology"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(
            mock_search.call_args.args[3],
            Sources.HARDCOVER.value,
        )

    @patch("api.views.services.search")
    def test_search_forwards_an_explicit_source(self, mock_search):
        """An explicit source still wins over the user's preference."""
        self.user1.book_metadata_source_default = Sources.OPENLIBRARY.value
        self.user1.save(update_fields=["book_metadata_source_default"])
        mock_search.return_value = {
            "results": [],
            "total_results": 0,
            "total_pages": 1,
        }

        self.call_api(
            "get",
            "api_search_provider",
            args=("book",),
            params={"search": "scientific ontology", "source": "googlebooks"},
            headers=self.auth_headers,
        )

        self.assertEqual(mock_search.call_args.args[3], Sources.GOOGLEBOOKS.value)

    @patch("api.views.services.search")
    def test_search_enforces_max_limit(self, mock_search):
        """Search endpoint should clamp limit to the API maximum."""
        mock_search.return_value = {
            "results": [{"id": i, "title": f"Item {i}"} for i in range(1, 6)],
            "total_results": 5,
            "total_pages": 1,
        }

        response = self.client.get(
            reverse("api_search_provider", args=("movie",)) + "?limit=999",
            **self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_search.call_args.kwargs["limit"], 200)
        self.assertEqual(response.json()["pagination"]["limit"], 200)

    def test_search_rejects_invalid_limit(self):
        """Search endpoint should reject non-integer limit values."""
        response = self.client.get(
            reverse("api_search_provider", args=("movie",)) + "?limit=abc",
            **self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("invalid limit", response.json().get("detail", "").lower())

    def test_search_rejects_invalid_offset(self):
        """Search endpoint should reject non-integer offset values."""
        response = self.client.get(
            reverse("api_search_provider", args=("movie",)) + "?offset=abc",
            **self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("invalid offset", response.json().get("detail", "").lower())

    def test_search_rejects_non_positive_limit(self):
        """Search endpoint should reject limit <= 0."""
        response = self.client.get(
            reverse("api_search_provider", args=("movie",)) + "?limit=0",
            **self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("limit must be >0", response.json().get("detail", "").lower())

    @patch("api.views.services.search")
    def test_search_accumulates_pages_before_paginating(self, mock_search):
        """Search endpoint should keep fetching pages until offset+limit is covered."""
        mock_search.side_effect = [
            {
                "results": [
                    {"id": 1, "title": "A"},
                    {"id": 2, "title": "B"},
                ],
                "total_results": 4,
                "total_pages": 2,
            },
            {
                "results": [
                    {"id": 3, "title": "C"},
                    {"id": 4, "title": "D"},
                ],
                "total_results": 4,
                "total_pages": 2,
            },
        ]

        response = self.client.get(
            reverse("api_search_provider", args=("movie",)) + "?limit=2&offset=2",
            **self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_search.call_count, 2)

        payload = response.json()
        self.assertEqual(payload["pagination"]["total"], 4)
        self.assertEqual(payload["pagination"]["limit"], 2)
        self.assertEqual(payload["pagination"]["offset"], 2)
        self.assertEqual([item["id"] for item in payload["results"]], [3, 4])
        self.assertIsNone(payload["pagination"]["next"])
        self.assertIsNotNone(payload["pagination"]["previous"])

    @patch("api.views.services.search")
    def test_search_handles_malformed_provider_payload(self, mock_search):
        """Search endpoint should return empty paginated payload on bad response."""
        mock_search.return_value = {"unexpected": "payload"}

        response = self.call_api(
            "get",
            "api_search_provider",
            args=("movie",),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["results"], [])
        self.assertEqual(payload["pagination"]["total"], 0)

    @patch("api.views.services.search")
    def test_search_provider_exception_returns_internal_error(self, mock_search):
        """Search endpoint should map provider failures to HTTP 500."""
        mock_search.side_effect = RuntimeError("provider failure")

        response = self.call_api(
            "get",
            "api_search_provider",
            args=("movie",),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 500)

    @patch("api.views.services.search")
    def test_search_game_results_include_cached_lengths_summary(self, mock_search):
        """Game search results should carry a lengths summary when cached, #989."""
        Item.objects.create(
            media_id="9101",
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            title="Cached Game",
            provider_game_lengths={
                "active_source": "hltb",
                "hltb": {
                    "summary": {
                        "main_minutes": 600,
                        "main_plus_minutes": 900,
                        "completionist_minutes": 1500,
                        "all_styles_minutes": 900,
                    },
                    "raw": {"should": "not leak"},
                },
            },
        )
        mock_search.return_value = {
            "results": [
                {
                    "media_id": "9101",
                    "source": Sources.IGDB.value,
                    "media_type": MediaTypes.GAME.value,
                    "title": "Cached Game",
                    "image": None,
                },
                {
                    "media_id": "9102",
                    "source": Sources.IGDB.value,
                    "media_type": MediaTypes.GAME.value,
                    "title": "Uncached Game",
                    "image": None,
                },
            ],
            "total_results": 2,
            "total_pages": 1,
        }

        response = self.call_api(
            "get",
            "api_search_provider",
            args=(MediaTypes.GAME.value,),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        cached, uncached = results[0], results[1]

        summary = cached["provider_game_lengths_summary"]
        self.assertEqual(summary["active_source"], "hltb")
        self.assertEqual(summary["hltb_summary"]["main_minutes"], 600)
        self.assertNotIn("raw", summary["hltb_summary"])
        self.assertNotIn("single_player_table", summary)

        self.assertNotIn("provider_game_lengths_summary", uncached)
