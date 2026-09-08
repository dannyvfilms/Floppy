from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from app.models import Sources
from app.providers import mal


class MalSeasonProviderTests(SimpleTestCase):
    databases = {"default"}

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch("app.providers.mal.services.api_request")
    def test_seasonal_anime_normalizes_and_caches_results(self, mock_request):
        mock_request.side_effect = [
            {
                "data": [
                    {
                        "node": {
                            "id": 52991,
                            "title": "Sousou no Frieren",
                            "alternative_titles": {"en": "Frieren"},
                            "main_picture": {
                                "large": "https://example.com/frieren.jpg",
                            },
                            "media_type": "tv",
                            "start_date": "2026-01-09",
                            "mean": 9.1,
                            "popularity": 12,
                        },
                    },
                ],
                "paging": {"next": "https://example.com/?offset=100"},
            },
            {
                "data": [
                    {
                        "node": {
                            "id": 60000,
                            "title": "Second Page",
                            "media_type": "ona",
                            "popularity": 42,
                        },
                    },
                ],
                "paging": {},
            },
        ]

        expected = mal.seasonal_anime(2026, "winter")
        self.assertEqual(mal.seasonal_anime(2026, "winter"), expected)
        self.assertEqual(
            [entry["media_id"] for entry in expected],
            ["52991", "60000"],
        )
        self.assertEqual(
            expected[0],
            {
                "media_id": "52991",
                "source": "mal",
                "media_type": "anime",
                "title": "Frieren",
                "original_title": "Sousou no Frieren",
                "localized_title": "Frieren",
                "image": "https://example.com/frieren.jpg",
                "release_date": "2026-01-09",
                "format": "tv",
                "score": 9.1,
                "popularity_rank": 12,
            },
        )
        self.assertEqual(mock_request.call_count, 2)
        mock_request.assert_any_call(
            Sources.MAL.value,
            "GET",
            "https://api.myanimelist.net/v2/anime/season/2026/winter",
            params={
                "fields": (
                    "media_type,start_date,alternative_titles,mean,popularity"
                ),
                "limit": 100,
                "offset": 0,
            },
            headers={"X-MAL-CLIENT-ID": settings.MAL_API},
        )
        self.assertEqual(mock_request.call_args.kwargs["params"]["offset"], 100)

    @patch("app.providers.mal.services.api_request", return_value={"data": []})
    def test_seasonal_cache_is_scoped_to_nsfw_setting(self, mock_request):
        with override_settings(MAL_NSFW=False):
            mal.seasonal_anime(2026, "winter")
            mal.seasonal_anime(2026, "winter")

        with override_settings(MAL_NSFW=True):
            mal.seasonal_anime(2026, "winter")
            mal.seasonal_anime(2026, "winter")

        self.assertEqual(mock_request.call_count, 2)
        self.assertNotIn("nsfw", mock_request.call_args_list[0].kwargs["params"])
        self.assertEqual(
            mock_request.call_args_list[1].kwargs["params"]["nsfw"],
            "true",
        )
