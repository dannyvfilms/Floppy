from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch

from django.urls import reverse

from app.models import Sources
from app.providers import services

from .base import FloppyApiTestCase


class PeopleSearchEndpointTests(FloppyApiTestCase):
    @patch("api.fork_views_people.people_views.advanced_discover")
    def test_advanced_discover_forwards_adult_mode_to_shared_view(self, advanced_discover):
        from django.http import JsonResponse

        advanced_discover.return_value = JsonResponse({"adultMode": "only"})
        response = self.call_api(
            "get",
            "api_advanced_discover",
            params={"search": "1", "adult_mode": "only"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json(), {"adultMode": "only"})
        request = advanced_discover.call_args.args[0]
        self.assertEqual(request.GET["adult_mode"], "only")
        self.assertEqual(request.GET["format"], "json")

    @patch("app.providers.tmdb.search_people")
    def test_search_returns_normalized_people(self, search_people):
        search_people.return_value = [
            {
                "person_id": "123",
                "name": "Jane Star",
                "image": "https://example.com/jane.jpg",
                "known_for_department": "Acting",
                "known_for": ["Example Movie"],
            },
        ]

        response = self.call_api(
            "get",
            "api_people_search",
            params={"query": "Jane Star"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["query"], "Jane Star")
        self.assertEqual(response.json()["people"][0]["person_id"], "123")
        self.assertEqual(
            response.json()["people"][0]["href"],
            reverse(
                "person_detail",
                kwargs={"source": Sources.TMDB.value, "person_id": "123", "name": "jane-star"},
            ),
        )
        search_people.assert_called_once_with("Jane Star")

    @patch("app.providers.tmdb.search_people")
    def test_short_query_returns_empty_without_provider_request(self, search_people):
        response = self.call_api(
            "get",
            "api_people_search",
            params={"query": "J"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["people"], [])
        search_people.assert_not_called()

    @patch("app.providers.tmdb.search_people", return_value=[])
    def test_query_is_limited_before_provider_request(self, search_people):
        query = "Jane " + "x" * 120

        response = self.call_api(
            "get",
            "api_people_search",
            params={"query": query},
            headers=self.auth_headers,
        )

        bounded_query = query[:100]
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["query"], bounded_query)
        search_people.assert_called_once_with(bounded_query)

    @patch("app.providers.tmdb.search_people")
    def test_provider_failure_returns_gateway_error(self, search_people):
        search_people.side_effect = services.ProviderAPIError(
            Sources.TMDB.value,
            RuntimeError("offline"),
        )

        response = self.call_api(
            "get",
            "api_people_search",
            params={"query": "Jane Star"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.BAD_GATEWAY)
        self.assertEqual(response.json(), {"detail": "TMDB is currently unavailable."})
