"""Focused tests for the compact cached TMDB person-date lookup."""

from unittest.mock import ANY, patch

from django.core.cache import cache
from django.test import TestCase

from app.models import Sources
from app.providers import tmdb


class TmdbPersonDatesTests(TestCase):
    """The lazy cast-card lookup caches only the profile dates it needs."""

    def setUp(self):
        cache.delete(tmdb._person_dates_cache_key("57700"))
        cache.delete(f"{Sources.TMDB.value}_person_57700")

    @patch(
        "app.providers.services.api_request",
        return_value={"birthday": "1965-02-01", "deathday": "1993-03-31"},
    )
    def test_person_dates_are_cached_without_fetching_combined_credits(self, request):
        first = tmdb.person_dates("57700")
        second = tmdb.person_dates("57700")

        self.assertEqual(first["birth_date"], "1965-02-01")
        self.assertEqual(first["death_date"], "1993-03-31")
        self.assertEqual(second, first)
        request.assert_called_once_with(
            Sources.TMDB.value,
            "GET",
            f"{tmdb.base_url}/person/57700",
            params=ANY,
        )
        self.assertNotIn("append_to_response", request.call_args.kwargs["params"])
