from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from app.providers import tmdb


class TmdbAdvancedDiscoverTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        base_params = patch(
            "app.providers.tmdb.base_params",
            return_value={"api_key": "unit-test", "language": "en-US"},
        )
        base_params.start()
        self.addCleanup(base_params.stop)

    @patch("app.providers.tmdb.services.api_request")
    def test_discover_passes_filters_and_normalizes_movie_results(self, api_request):
        api_request.return_value = {
            "page": 1,
            "total_results": 1,
            "results": [{
                "id": 42,
                "adult": True,
                "title": "Example",
                "release_date": "2020-02-03",
                "poster_path": "/example.jpg",
            }],
        }

        response = tmdb.discover("movie", {"with_people": "1,2", "include_video": "false"})

        self.assertEqual(response["results"][0]["media_id"], "42")
        self.assertEqual(response["results"][0]["title"], "Example")
        self.assertEqual(response["results"][0]["year"], 2020)
        self.assertEqual(response["results"][0]["media_type"], "movie")
        self.assertIs(response["results"][0]["adult"], True)
        self.assertIn("/discover/movie", api_request.call_args.args[2])
        self.assertEqual(api_request.call_args.kwargs["params"]["with_people"], "1,2")

    @patch("app.providers.tmdb.services.api_request")
    def test_certifications_are_cached_and_country_grouped(self, api_request):
        api_request.return_value = {
            "certifications": {
                "US": [{"certification": "PG-13", "meaning": "Parents strongly cautioned"}],
                "GB": [{"certification": "12A"}],
            },
        }

        result = tmdb.discovery_certifications("movie")
        cached_result = tmdb.discovery_certifications("movie")

        self.assertEqual(result["US"][0]["certification"], "PG-13")
        self.assertEqual(result["GB"][0]["meaning"], "")
        self.assertEqual(cached_result, result)
        api_request.assert_called_once()

    def test_discover_rejects_unsupported_media_type(self):
        with self.assertRaises(ValueError):
            tmdb.discover("person", {})
