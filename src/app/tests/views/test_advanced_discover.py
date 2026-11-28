from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from app.models import Item, MediaTypes, Movie, Sources, Status


class AdvancedDiscoverViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="advanced-discover",
            password="test-password",
        )
        self.client.force_login(self.user)
        country_names = patch(
            "app.providers.tmdb.discovery_country_names",
            return_value={},
        )
        country_names.start()
        self.addCleanup(country_names.stop)

    @patch("app.people_views._people_credit_contract")
    @patch("app.people_views.attach_card_media")
    @patch("app.providers.tmdb.discover")
    @patch("app.providers.tmdb.discovery_certifications")
    def test_movie_discovery_sends_scoped_people_and_certification_filters(
        self,
        certifications,
        discover,
        attach_cards,
        card_contract,
    ):
        certifications.side_effect = [
            {"US": [
                {"certification": "R", "meaning": "Restricted"},
                {"certification": "NR", "meaning": "No rating information"},
            ]},
            {},
        ]
        discover.return_value = {"results": [], "total_results": 0}
        card_contract.return_value = {"card": {}}

        response = self.client.get(reverse("advanced_discover"), {
            "type": "movie",
            "search": "1",
            "person": ["123", "456"],
            "person_name_123": "A Person",
            "person_name_456": "Another Person",
            "person_role": "cast",
            "person_logic": "or",
            "certification_country": "US",
            "certification": ["R", "NR"],
            "include_video": "true",
            "format": "json",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["kind"], "advanced-discover")
        self.assertEqual(response.json()["selectedCertifications"], ["R", "NR"])
        self.assertEqual(response.json()["adultMode"], "exclude")
        discover.assert_called_once_with("movie", {
            "include_adult": "false",
            "sort_by": "release_date.desc",
            "include_video": "true",
            "certification_country": "US",
            "certification": "R|NR",
            "with_cast": "123|456",
        }, page=1)

    @override_settings(TMDB_NSFW=True)
    @patch("app.people_views._people_credit_contract")
    @patch("app.people_views.attach_card_media")
    @patch("app.providers.tmdb.discover")
    @patch("app.providers.tmdb.discovery_certifications", return_value={})
    def test_tv_discovery_uses_tv_include_flags_and_all_people_logic(
        self,
        certifications,
        discover,
        attach_cards,
        card_contract,
    ):
        discover.return_value = {"results": [], "total_results": 0}
        card_contract.return_value = {"card": {}}

        response = self.client.get(reverse("advanced_discover"), {
            "type": "tv",
            "search": "1",
            "person": ["12", "bad", "12", "34"],
            "person_role": "people",
            "person_logic": "and",
            "include_adult": "true",
            "include_null_first_air_dates": "true",
            "format": "json",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["adultMode"], "include")
        discover.assert_called_once_with("tv", {
            "include_adult": "true",
            "sort_by": "first_air_date.desc",
            "include_null_first_air_dates": "true",
            "with_people": "12,34",
        }, page=1)

    @patch("app.providers.tmdb.search_people", return_value=[{"person_id": "123", "name": "A Person"}])
    def test_people_autocomplete_is_bounded_and_returns_json(self, search_people):
        response = self.client.get(reverse("advanced_discover"), {
            "action": "people",
            "q": "A Person",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["people"][0]["person_id"], "123")
        search_people.assert_called_once_with("A Person")

    @patch("app.providers.tmdb.search_people")
    def test_invalid_type_is_rejected(self, search_people):
        response = self.client.get(reverse("advanced_discover"), {"type": "person"})
        self.assertEqual(response.status_code, 400)
        search_people.assert_not_called()

    @override_settings(TMDB_NSFW=True)
    @patch("app.providers.tmdb.discovery_certifications", return_value={})
    @patch("app.providers.tmdb.discover")
    def test_only_adult_filters_each_provider_page_and_projects_card_chip(self, discover, certifications):
        discover.return_value = {
            "results": [{
                "media_id": "9001",
                "source": "tmdb",
                "media_type": "movie",
                "adult": True,
                "title": "An adult result",
                "image": "https://image.tmdb.org/t/p/w500/poster.jpg",
                "year": 2024,
                "release_date": "2024-01-01",
                "role": "",
            }, {
                "media_id": "9002",
                "source": "tmdb",
                "media_type": "movie",
                "adult": False,
                "title": "A non-adult result",
                "image": "https://image.tmdb.org/t/p/w500/poster-2.jpg",
                "year": 2024,
                "release_date": "2024-01-01",
                "role": "",
            }],
            "total_results": 40,
            "total_pages": 4,
            "page": 1,
        }

        response = self.client.get(reverse("advanced_discover"), {
            "type": "movie",
            "search": "1",
            "adult_mode": "only",
            "format": "json",
        })

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["adultMode"], "only")
        self.assertIsNone(payload["totalPages"])
        self.assertIsNone(payload["totalResults"])
        self.assertTrue(payload["hasNextPage"])
        self.assertEqual(len(payload["results"]), 1)
        entry = payload["results"][0]
        self.assertEqual(entry["title"], "An adult result")
        self.assertIs(entry["isAdult"], True)
        self.assertIn(
            {"kind": "runtime-top", "text": "TMDB Adult", "title": "TMDB marks this title as adult"},
            entry["card"]["cornerChips"],
        )
        certifications.assert_any_call("movie")
        discover.assert_called_once_with("movie", {
            "include_adult": "true",
            "sort_by": "release_date.desc",
            "include_video": "false",
        }, page=1)

    @patch("app.providers.tmdb.discovery_certifications", return_value={})
    @patch("app.providers.services.get_media_metadata", return_value={"max_progress": None})
    @patch("app.models.Item.fetch_releases")
    @patch("app.providers.tmdb.discover")
    def test_existing_user_tracker_is_projected_with_status_and_edit_actions(
        self,
        discover,
        fetch_releases,
        get_media_metadata,
        certifications,
    ):
        item = Item.objects.create(
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            media_id="9001",
            title="Tracked result",
        )
        Movie.objects.create(
            item=item,
            user=self.user,
            status=Status.COMPLETED.value,
            progress=1,
        )
        discover.return_value = {
            "results": [{
                "media_id": "9001",
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.MOVIE.value,
                "title": "Tracked result",
                "image": "https://image.tmdb.org/t/p/w500/poster.jpg",
                "year": 2024,
                "release_date": "2024-01-01",
                "role": "",
            }],
            "total_results": 1,
            "total_pages": 1,
            "page": 1,
        }

        response = self.client.get(reverse("advanced_discover"), {
            "type": MediaTypes.MOVIE.value,
            "search": "1",
            "format": "json",
        })

        self.assertEqual(response.status_code, 200)
        card = response.json()["results"][0]["card"]
        self.assertEqual(card["statusChip"]["status"], Status.COMPLETED.label)
        self.assertIn("instance_id", card["actions"]["items"][0]["vals"])

    @patch("app.providers.tmdb.discovery_certifications", return_value={})
    @patch("app.providers.tmdb.discover")
    def test_sort_choices_map_to_movie_and_tv_discover_fields(
        self,
        discover,
        certifications,
    ):
        choices = {
            "movie": {
                "release_date": "release_date.desc",
                "title": "title.asc",
                "popularity": "popularity.desc",
                "votes": "vote_count.desc",
            },
            "tv": {
                "release_date": "first_air_date.desc",
                "title": "name.asc",
                "popularity": "popularity.desc",
                "votes": "vote_count.desc",
            },
        }
        discover.return_value = {"results": [], "total_results": 0, "total_pages": 1}

        for media_type, sort_choices in choices.items():
            for choice, expected_sort in sort_choices.items():
                with self.subTest(media_type=media_type, sort=choice):
                    discover.reset_mock()
                    response = self.client.get(reverse("advanced_discover"), {
                        "type": media_type,
                        "search": "1",
                        "sort": choice,
                        "format": "json",
                    })
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["sort"], choice)
                    filters = {
                        "include_adult": "false",
                        "sort_by": expected_sort,
                    }
                    filters[
                        "include_video" if media_type == "movie"
                        else "include_null_first_air_dates"
                    ] = "false"
                    discover.assert_called_once_with(media_type, filters, page=1)
