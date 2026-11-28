from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from app.providers import tmdb


class SearchPeopleTests(SimpleTestCase):
    databases = {"default"}

    def setUp(self):
        cache.clear()

    @patch("app.providers.tmdb.services.api_request")
    def test_returns_normalized_people_and_ignores_invalid_provider_rows(self, api_request):
        api_request.return_value = {
            "results": [
                {
                    "id": 123,
                    "name": " Jane Star ",
                    "profile_path": "/jane.jpg",
                    "known_for_department": "Acting",
                    "known_for": [
                        {"title": "Example Movie"},
                        {"name": "Example Series"},
                        {"title": "Example Movie"},
                    ],
                },
                {"id": 0, "name": "Invalid"},
                {"id": 456, "name": ""},
            ],
        }

        people = tmdb.search_people(" Jane Star ")

        self.assertEqual(people, [{
            "person_id": "123",
            "name": "Jane Star",
            "image": "https://image.tmdb.org/t/p/h632/jane.jpg",
            "known_for_department": "Acting",
            "known_for": ["Example Movie", "Example Series"],
        }])
        self.assertEqual(api_request.call_args.args[2], f"{tmdb.base_url}/search/person")
        self.assertEqual(api_request.call_args.kwargs["params"]["query"], "Jane Star")

    @patch("app.providers.tmdb.services.api_request")
    def test_blank_query_skips_provider(self, api_request):
        self.assertEqual(tmdb.search_people("  "), [])
        api_request.assert_not_called()

    @patch("app.providers.tmdb.services.api_request", return_value={"results": []})
    def test_reuses_search_cache(self, api_request):
        tmdb.search_people("Jane Star")
        tmdb.search_people("Jane Star")
        api_request.assert_called_once()

    @patch("app.providers.tmdb.services.api_request", return_value={"results": []})
    def test_adult_setting_uses_a_separate_cache_entry_and_provider_parameter(self, api_request):
        with override_settings(TMDB_NSFW=False):
            tmdb.search_people("Jane Star")
        with override_settings(TMDB_NSFW=True):
            tmdb.search_people("Jane Star")
            tmdb.search_people("Jane Star")

        self.assertEqual(api_request.call_count, 2)
        self.assertNotIn("include_adult", api_request.call_args_list[0].kwargs["params"])
        self.assertEqual(
            api_request.call_args_list[1].kwargs["params"]["include_adult"],
            "true",
        )
