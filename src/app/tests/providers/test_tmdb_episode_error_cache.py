"""Tests for negative caching of TMDB episode lookup failures."""

from types import SimpleNamespace
from unittest.mock import patch

import requests
from django.core.cache import cache
from django.test import TestCase

from app.providers import services, tmdb


def _http_error(status_code):
    response = SimpleNamespace(status_code=status_code, headers={}, text="")
    error = requests.exceptions.HTTPError(response=response)
    return error


class TmdbEpisodeErrorCacheTests(TestCase):
    def tearDown(self):
        cache.clear()
        super().tearDown()

    @patch("app.providers.services.api_request")
    def test_404_is_negative_cached(self, mock_api):
        mock_api.side_effect = _http_error(404)

        with self.assertRaises(services.ProviderAPIError):
            tmdb.episode("999999", 1, 1)
        with self.assertRaises(services.ProviderAPIError):
            tmdb.episode("999999", 1, 1)

        mock_api.assert_called_once()

    @patch("app.providers.services.api_request")
    def test_server_error_is_negative_cached(self, mock_api):
        mock_api.side_effect = _http_error(503)

        with self.assertRaises(services.ProviderAPIError):
            tmdb.episode("999998", 1, 1)
        with self.assertRaises(services.ProviderAPIError):
            tmdb.episode("999998", 1, 1)

        mock_api.assert_called_once()

    @patch("app.providers.services.api_request")
    def test_cached_error_preserves_status_code(self, mock_api):
        mock_api.side_effect = _http_error(404)

        with self.assertRaises(services.ProviderAPIError):
            tmdb.episode("999997", 1, 1)
        with self.assertRaises(services.ProviderAPIError) as ctx:
            tmdb.episode("999997", 1, 1)

        self.assertEqual(ctx.exception.status_code, 404)
