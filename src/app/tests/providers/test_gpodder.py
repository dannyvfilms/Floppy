from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from app.models import MediaTypes, Sources
from app.providers import gpodder


@override_settings(PER_PAGE=24)
class GPodderSearchTests(TestCase):
    """Tests for the public gpodder.net podcast search provider."""

    def setUp(self):
        cache.clear()

    @patch("app.providers.gpodder.services.api_request")
    def test_search_maps_results_and_sends_user_agent(self, mock_request):
        mock_request.return_value = [
            {
                "url": "https://example.com/linux.xml",
                "title": "Linux Outlaws",
                "logo_url": "https://example.com/linux.jpg",
            },
            {
                "url": "https://example.com/no-logo.xml",
                "title": "No Logo",
                "scaled_logo_url": "https://example.com/logo64.jpg",
            },
            {"title": "Missing feed"},
        ]

        response = gpodder.search("linux", 1)

        self.assertEqual(response["total_results"], 2)
        self.assertEqual(
            response["results"][0],
            {
                "media_id": "https://example.com/linux.xml",
                "source": Sources.GPODDER.value,
                "media_type": MediaTypes.PODCAST.value,
                "title": "Linux Outlaws",
                "image": "https://example.com/linux.jpg",
            },
        )
        self.assertEqual(
            response["results"][1]["image"],
            "https://example.com/logo64.jpg",
        )
        mock_request.assert_called_once_with(
            Sources.GPODDER.value,
            "GET",
            gpodder.SEARCH_URL,
            params={"q": "linux"},
            headers={"User-Agent": gpodder.USER_AGENT},
        )

    @patch("app.providers.gpodder.services.api_request")
    def test_search_is_cached(self, mock_request):
        mock_request.return_value = [
            {"url": "https://example.com/feed.xml", "title": "Cached"},
        ]

        first = gpodder.search("cached", 1)
        second = gpodder.search("cached", 1)

        self.assertEqual(first, second)
        mock_request.assert_called_once()

    @patch("app.providers.gpodder.services.api_request")
    def test_empty_query_does_not_call_the_provider(self, mock_request):
        response = gpodder.search("", 1)

        self.assertEqual(response["results"], [])
        mock_request.assert_not_called()

    @patch("app.providers.gpodder.services.api_request")
    def test_page_past_the_results_is_empty(self, mock_request):
        mock_request.return_value = [
            {"url": "https://example.com/feed.xml", "title": "One"},
        ]

        response = gpodder.search("one", 2)

        self.assertEqual(response["results"], [])
        self.assertEqual(response["total_results"], 1)
