"""Tests for negative caching of TMDB episode lookup failures."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch

import requests
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings, tag

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


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class TmdbSeasonAmplificationTests(SimpleTestCase):
    """Characterize current season caching, without changing provider behavior."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        credentials = patch.object(tmdb.credentials, "get", return_value="diagnostic-only")
        credentials.start()
        self.addCleanup(credentials.stop)
        self.tv_data = {"title": "Diagnostic show", "tvdb_id": "123", "related": {}}

    def _repeated_season_lookups(self, entries, *, missing):
        calls = 0

        def stub_request(provider, method, url, **kwargs):
            nonlocal calls
            calls += 1
            self.assertEqual(url, f"{tmdb.base_url}/tv/123")
            self.assertIn("season/21", kwargs["params"]["append_to_response"])
            return {} if missing else {"season/21": {}}

        cache.set(tmdb._tv_cache_key("123"), self.tv_data)
        with (
            patch.object(services, "api_request", side_effect=stub_request),
            patch.object(tmdb, "process_tv", return_value=self.tv_data),
            patch.object(tmdb, "process_season", return_value={"title": "Season"}),
            patch.object(tmdb, "enrich_season_with_tv_data", side_effect=lambda data, *_: data),
            patch.object(tmdb.logger, "warning"),
            patch.object(services.logger, "error"),
            patch.object(services.logger, "warning"),
        ):
            failures = 0
            for _ in range(entries):
                try:
                    services.get_media_metadata("season", "123", "tmdb", [21])
                except services.ProviderAPIError as error:
                    self.assertEqual(error.status_code, 404)
                    failures += 1
        return {"entries": entries, "http_calls": calls, "not_found": failures}

    def test_repeated_missing_season_is_not_negative_cached(self):
        self.assertEqual(
            self._repeated_season_lookups(20, missing=True),
            {"entries": 20, "http_calls": 20, "not_found": 20},
        )

    def test_repeated_successful_season_uses_one_fetch(self):
        self.assertEqual(
            self._repeated_season_lookups(20, missing=False),
            {"entries": 20, "http_calls": 1, "not_found": 0},
        )

    def test_simultaneous_missing_season_fetches_are_not_coalesced(self):
        """Two callers can fetch the same absent season at the same time."""
        rendezvous = Barrier(2)
        cache.set(tmdb._tv_cache_key("123"), self.tv_data)

        def fetch(*_args, **_kwargs):
            rendezvous.wait(timeout=5)
            return {}

        def resolve():
            try:
                services.get_media_metadata("season", "123", "tmdb", [21])
            except services.ProviderAPIError as error:
                return error.status_code
            return None

        with (
            patch.object(services, "api_request", side_effect=fetch) as api,
            patch.object(tmdb, "process_tv", return_value=self.tv_data),
            patch.object(tmdb.logger, "warning"),
            patch.object(services.logger, "error"),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            first = executor.submit(resolve)
            second = executor.submit(resolve)
            self.assertEqual([first.result(), second.result()], [404, 404])
        self.assertEqual(api.call_count, 2)

    @tag("slow", "benchmark")
    def test_80849_missing_season_lookups_amplify_per_entry(self):
        """An offline provider boundary count, not a NAS latency measurement."""
        self.assertEqual(
            self._repeated_season_lookups(80849, missing=True),
            {"entries": 80849, "http_calls": 80849, "not_found": 80849},
        )

    def test_year_coordinate_is_sent_as_season_and_404_is_generated_locally(self):
        cache.set(tmdb._tv_cache_key("123"), self.tv_data)
        with (
            patch.object(services, "api_request", return_value={}) as api,
            patch.object(tmdb, "process_tv", return_value=self.tv_data),
            patch.object(tmdb.logger, "warning"),
            patch.object(services.logger, "error") as log,
            self.assertRaises(services.ProviderAPIError) as caught,
        ):
            services.get_media_metadata("season", "123", "tmdb", [1986])
        self.assertIn("season/1986", api.call_args.kwargs["params"]["append_to_response"])
        self.assertEqual(caught.exception.status_code, 404)
        log.assert_called_once_with("%s %s lookup failed with 404", "tmdb", "season 1986")
