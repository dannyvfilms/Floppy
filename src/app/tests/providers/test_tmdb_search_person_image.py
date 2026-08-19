from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from app.providers import tmdb


class SearchPersonProfileTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_returns_image_and_gender_for_first_result(self):
        with patch(
            "app.providers.tmdb.services.api_request",
            return_value={"results": [{"profile_path": "/abc.jpg", "gender": 1}]},
        ):
            profile = tmdb.search_person_profile("Alice Actor")

        self.assertEqual(profile["image"], "https://image.tmdb.org/t/p/h632/abc.jpg")
        self.assertEqual(profile["gender"], "female")

    def test_returns_unknown_gender_when_tmdb_has_no_gender_data(self):
        with patch(
            "app.providers.tmdb.services.api_request",
            return_value={"results": [{"profile_path": "/abc.jpg", "gender": 0}]},
        ):
            profile = tmdb.search_person_profile("Ambiguous Person")

        self.assertEqual(profile["gender"], "unknown")

    def test_returns_none_when_no_results(self):
        with patch(
            "app.providers.tmdb.services.api_request",
            return_value={"results": []},
        ):
            profile = tmdb.search_person_profile("Nobody Findable")

        self.assertIsNone(profile)

    def test_returns_none_for_blank_name(self):
        profile = tmdb.search_person_profile("")
        self.assertIsNone(profile)

    def test_second_call_uses_cache_not_a_new_request(self):
        with patch(
            "app.providers.tmdb.services.api_request",
            return_value={"results": [{"profile_path": "/abc.jpg", "gender": 2}]},
        ) as mock_request:
            tmdb.search_person_profile("Alice Actor")
            tmdb.search_person_profile("Alice Actor")

        mock_request.assert_called_once()
