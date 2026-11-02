"""Tests for TMDB carousel handling when a source is no longer available."""

from types import SimpleNamespace
from unittest.mock import patch

import requests
from django.core.cache import cache
from django.test import TestCase

from app import carousel
from app.models import MediaTypes, Sources
from app.providers import services, tmdb


def _http_error(status_code):
    response = SimpleNamespace(status_code=status_code, headers={}, text="")
    return requests.exceptions.HTTPError(response=response)


class TmdbCarouselNotFoundTests(TestCase):
    def tearDown(self):
        cache.clear()
        super().tearDown()

    @patch("app.providers.services.api_request")
    def test_404_returns_empty_payload_and_is_negative_cached(self, mock_api):
        mock_api.side_effect = _http_error(404)

        expected = {
            "video": None,
            "photos": [],
            "logos": [],
            "backdrop_path": None,
        }
        self.assertEqual(tmdb.carousel_media(MediaTypes.SEASON.value, "999999", 10), expected)
        self.assertEqual(tmdb.carousel_media(MediaTypes.SEASON.value, "999999", 10), expected)

        mock_api.assert_called_once()

    @patch("app.providers.services.api_request")
    def test_non_404_error_still_raises(self, mock_api):
        mock_api.side_effect = _http_error(503)

        with self.assertRaises(services.ProviderAPIError):
            tmdb.carousel_media(MediaTypes.SEASON.value, "999998", 10)

        mock_api.assert_called_once()

    @patch("app.providers.services.api_request")
    def test_resolve_carousel_media_returns_none_for_404(self, mock_api):
        mock_api.side_effect = _http_error(404)

        result = carousel.resolve_carousel_media(
            MediaTypes.SEASON.value,
            Sources.TMDB.value,
            "999997",
            season_number=10,
        )

        self.assertIsNone(result)
