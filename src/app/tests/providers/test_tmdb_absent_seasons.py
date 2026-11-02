"""Only confirmed missing season coordinates may suppress provider retries."""

from unittest.mock import patch

import redis
import requests
from django.core.cache import cache
from django.test import SimpleTestCase, tag

from app.models import MediaTypes, Sources
from app.providers import services, tmdb


class AbsentSeasonTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.tv_data = {"title": "Show", "tvdb_id": "7", "related": {}}
        self.response = {
            "number_of_seasons": 1,
            "seasons": [{"season_number": 1}],
        }
        self.api = self.enterContext(
            patch("app.providers.services.api_request", return_value=self.response)
        )
        self.enterContext(
            patch("app.providers.tmdb.process_tv", return_value=self.tv_data)
        )
        self.enterContext(
            patch("app.providers.tmdb.get_tvdb_id_override", return_value=None)
        )
        self.enterContext(patch("app.providers.tmdb.credentials.get", return_value="test-key"))
        self.enterContext(patch("app.providers.services.logger.warning"))
        self.enterContext(patch("app.providers.services.logger.error"))
        self.enterContext(patch("app.providers.tmdb.logger.warning"))

    def resolve(self, show="100", season=2, language=None):
        return services.get_media_metadata(
            MediaTypes.SEASON.value,
            show,
            Sources.TMDB.value,
            season_numbers=[season],
            language=language,
        )

    @tag("slow", "benchmark")
    def test_ten_thousand_repeated_absent_resolutions_make_one_provider_call(self):
        for _ in range(10000):
            with self.assertRaises(services.ProviderAPIError) as raised:
                self.resolve()
            self.assertTrue(raised.exception.confirmed_absent)
        self.api.assert_called_once()

    def test_cache_keys_separate_show_season_and_language_and_normalize_inputs(self):
        for show, season, language in (
            ("100", 2, None),
            ("100", "02", None),
            ("100", 3, None),
            ("101", 2, None),
            ("100", 2, "fr-FR"),
        ):
            with self.assertRaises(services.ProviderAPIError) as raised:
                self.resolve(show, season, language)
            self.assertTrue(raised.exception.confirmed_absent)
        self.assertEqual(self.api.call_count, 4)

    def test_incomplete_or_malformed_catalogues_do_not_confirm_absence(self):
        for catalogue, count in (
            ([], 1),
            ([{"season_number": 1}], 2),
            ([{"season_number": "1"}], 1),
            ([{"season_number": True}], 1),
            ([{"season_number": 1}, {"season_number": -1}], 1),
            ([{"season_number": 1}, {"season_number": 1}], 1),
            ([{}], 1),
            (None, 1),
            ([{"season_number": 2}], 1),
            ([{"season_number": 1}], "1"),
            ([{"season_number": 1}], True),
        ):
            with self.subTest(catalogue=catalogue, count=count):
                cache.clear()
                self.api.reset_mock()
                self.api.return_value = {
                    "seasons": catalogue,
                    "number_of_seasons": count,
                }
                for _ in range(2):
                    with self.assertRaises(services.ProviderAPIError) as raised:
                        self.resolve()
                    self.assertFalse(raised.exception.confirmed_absent)
                self.assertEqual(self.api.call_count, 2)
                self.assertIsNone(cache.get(tmdb._season_cache_key("100", 2)))

    def test_http_errors_and_network_failures_are_not_negative_cached(self):
        failures = [requests.Timeout("timeout"), requests.ConnectionError("offline")]
        for status in (401, 403, 404, 429, 500, 503):
            response = requests.Response()
            response.status_code = status
            response._content = b"{}"
            failures.append(requests.HTTPError("provider failure", response=response))
        for error in failures:
            with self.subTest(error=error):
                cache.clear()
                self.api.reset_mock()
                self.api.side_effect = error
                for _ in range(2):
                    with self.assertRaises(
                        (services.ProviderAPIError, requests.RequestException)
                    ):
                        self.resolve()
                self.assertEqual(self.api.call_count, 2)
                self.assertIsNone(cache.get(tmdb._season_cache_key("100", 2)))

    def test_invalid_requested_coordinates_are_not_confirmed_absent(self):
        for season in ("bad", -1, True):
            with self.subTest(season=season):
                with self.assertRaises(services.ProviderAPIError) as raised:
                    self.resolve(season=season)
                self.assertFalse(raised.exception.confirmed_absent)
                self.assertIsNone(cache.get(tmdb._season_cache_key("100", season)))

    def test_absent_marker_has_short_ttl_and_expiry_retries(self):
        with patch.object(tmdb.cache, "set", wraps=cache.set) as write:
            with self.assertRaises(services.ProviderAPIError):
                self.resolve()
        write.assert_any_call(
            tmdb._season_cache_key("100", 2),
            tmdb._ABSENT_SEASON,
            tmdb.ABSENT_SEASON_CACHE_TIMEOUT,
        )
        self.assertEqual(tmdb.ABSENT_SEASON_CACHE_TIMEOUT, 300)
        # Expiration is Redis's responsibility; removal models its resulting miss.
        cache.delete(tmdb._season_cache_key("100", 2))
        with self.assertRaises(services.ProviderAPIError):
            self.resolve()
        self.assertEqual(self.api.call_count, 2)

    def test_negative_cache_outage_preserves_confirmed_absence_for_import_memo(self):
        cache.set(tmdb._tv_cache_key("100"), self.tv_data)
        for failure in (redis.ConnectionError("offline"), redis.TimeoutError("timeout")):
            with self.subTest(failure=failure):
                with patch.object(tmdb.cache, "set", side_effect=failure):
                    with self.assertRaises(services.ProviderAPIError) as raised:
                        self.resolve()
                self.assertTrue(raised.exception.confirmed_absent)

    def test_manual_invalidation_and_repaired_positive_payload_share_the_same_key(self):
        with self.assertRaises(services.ProviderAPIError):
            self.resolve()
        keys = tmdb.metadata_cache_keys("100", MediaTypes.SEASON.value, season_number=2)
        cache.delete_many(keys)
        repaired = {"title": "Repaired season", "episodes": []}
        cache.set(keys[0], repaired)
        self.assertEqual(self.resolve()["title"], "Repaired season")
        self.api.assert_called_once()

    def test_specials_keep_tvdb_fallback_and_never_create_absent_marker(self):
        specials = {"title": "Specials", "episodes": [], "season_number": 0}
        with (
            patch(
                "app.providers.tmdb._build_specials_season_from_tvdb",
                return_value=specials,
            ) as fallback,
            patch("app.providers.tmdb._attach_specials_to_tv_data"),
        ):
            self.assertEqual(self.resolve(season="0")["title"], "Specials")
        fallback.assert_called_once()
        self.assertNotEqual(
            cache.get(tmdb._season_cache_key("100", 0)), tmdb._ABSENT_SEASON
        )

    def test_marker_cannot_reach_workers_using_the_previous_cache_protocol(self):
        legacy_key = "tmdb_season_v4_100_2"
        legacy_payload = {"title": "Previous season payload", "episodes": []}
        cache.set(legacy_key, legacy_payload)
        with self.assertRaises(services.ProviderAPIError):
            self.resolve()
        self.assertEqual(cache.get(legacy_key), legacy_payload)
        self.assertEqual(cache.get(tmdb._season_cache_key("100", 2)), tmdb._ABSENT_SEASON)

    def test_missing_append_payload_without_catalogue_remains_unconfirmed(self):
        self.api.return_value = {}
        with self.assertRaises(services.ProviderAPIError) as raised:
            self.resolve()
        self.assertFalse(raised.exception.confirmed_absent)
