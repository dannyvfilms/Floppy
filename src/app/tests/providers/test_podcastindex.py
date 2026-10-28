import hashlib
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from app.models import MediaTypes, Sources
from app.providers import credentials, podcastindex


@override_settings(PER_PAGE=24, PODCASTINDEX_API_KEY="key", PODCASTINDEX_API_SECRET="s3")
class PodcastIndexSearchTests(TestCase):
    """Tests for the Podcast Index podcast search provider."""

    def setUp(self):
        cache.clear()
        credentials.invalidate_cache()

    @patch("app.providers.podcastindex.services.api_request")
    def test_search_maps_results_to_feed_keyed_shows(self, mock_request):
        mock_request.return_value = {
            "feeds": [
                {
                    "url": "https://example.com/babylon.xml",
                    "title": "Babylon Berlin",
                    "artwork": "https://example.com/babylon.jpg",
                },
                {"url": "https://example.com/babylon.xml", "title": "Duplicate"},
                {"title": "No feed"},
            ],
        }

        response = podcastindex.search("babylon", 1)

        self.assertEqual(response["total_results"], 1)
        self.assertEqual(
            response["results"][0],
            {
                "media_id": "https://example.com/babylon.xml",
                "source": Sources.GPODDER.value,
                "media_type": MediaTypes.PODCAST.value,
                "title": "Babylon Berlin",
                "image": "https://example.com/babylon.jpg",
            },
        )

    @patch("app.providers.podcastindex.time.time", return_value=1700000000)
    @patch("app.providers.podcastindex.services.api_request")
    def test_search_signs_the_request(self, mock_request, _time):
        mock_request.return_value = {"feeds": []}

        podcastindex.search("x", 1)

        headers = mock_request.call_args.kwargs["headers"]
        self.assertEqual(headers["X-Auth-Key"], "key")
        self.assertEqual(headers["X-Auth-Date"], "1700000000")
        self.assertEqual(
            headers["Authorization"],
            hashlib.sha1(b"keys31700000000").hexdigest(),  # noqa: S324
        )

    @patch("app.providers.podcastindex.services.api_request")
    def test_empty_query_does_not_call_the_provider(self, mock_request):
        self.assertEqual(podcastindex.search("  ", 1)["results"], [])
        mock_request.assert_not_called()

    def test_enabled_needs_key_and_secret(self):
        self.assertTrue(podcastindex.enabled())
        with override_settings(PODCASTINDEX_API_SECRET=""):
            credentials.invalidate_cache()
            self.assertFalse(podcastindex.enabled())
