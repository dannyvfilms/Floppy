from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import Item, Sources


class PeopleDiscoveryViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="people-discovery",
            password="test-password",
        )
        self.client.force_login(self.user)

    @patch("app.providers.tmdb.search_people")
    def test_results_link_to_existing_tmdb_person_profile_without_tracking(self, search_people):
        search_people.return_value = [
            {
                "person_id": "123",
                "name": "Jane Star",
                "image": "https://image.tmdb.org/t/p/h632/jane.jpg",
                "known_for_department": "Acting",
                "known_for": ["Example Movie"],
            },
        ]

        response = self.client.get(reverse("discover_people"), {"q": "Jane Star"})

        profile_url = reverse(
            "person_detail",
            kwargs={"source": Sources.TMDB.value, "person_id": "123", "name": "jane-star"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Discover people")
        self.assertContains(response, profile_url)
        self.assertEqual(response.context["search_props"]["people"][0]["person_id"], "123")
        self.assertFalse(Item.objects.exists())
        search_people.assert_called_once_with("Jane Star")

    @patch("app.providers.tmdb.search_people")
    def test_short_query_does_not_search_provider(self, search_people):
        response = self.client.get(reverse("discover_people"), {"q": "J"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["people"], [])
        search_people.assert_not_called()
