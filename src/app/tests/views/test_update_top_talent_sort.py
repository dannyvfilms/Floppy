from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from app.models import (
    CreditRoleType,
    Game,
    Item,
    ItemPersonCredit,
    MediaTypes,
    Movie,
    Person,
    PersonGender,
    Sources,
    Status,
)


class UpdateTopTalentSortMediaTypeFilterTests(TestCase):
    def setUp(self):
        self.credentials = {"username": "top-talent-tester", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        self.game_item = Item.objects.create(
            media_id="igdb-300",
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            title="Dispatch",
            image="http://example.com/game.jpg",
        )
        Game.objects.create(
            item=self.game_item,
            user=self.user,
            status=Status.COMPLETED.value,
            progress=1,
            end_date=timezone.now(),
        )
        game_person = Person.objects.create(
            source=Sources.IMDB.value,
            source_person_id="nm0000009",
            name="Game Actor",
            gender=PersonGender.FEMALE.value,
        )
        ItemPersonCredit.objects.create(
            item=self.game_item,
            person=game_person,
            role_type=CreditRoleType.CAST.value,
            role="Sam",
        )

        self.movie_item = Item.objects.create(
            media_id="tmdb-300",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="A Movie",
            image="http://example.com/movie.jpg",
        )
        Movie.objects.create(
            item=self.movie_item,
            user=self.user,
            status=Status.COMPLETED.value,
            end_date=timezone.now(),
        )
        movie_person = Person.objects.create(
            source=Sources.TMDB.value,
            source_person_id="9",
            name="Movie Actor",
            gender=PersonGender.MALE.value,
        )
        ItemPersonCredit.objects.create(
            item=self.movie_item,
            person=movie_person,
            role_type=CreditRoleType.CAST.value,
            role="Hero",
        )

    def test_media_type_game_scopes_response_to_game_cast(self):
        response = self.client.post(
            reverse("update_top_talent_sort"),
            {"sort_by": "plays", "media_type": "game"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertIn("studio_footprint_html", data)
        self.assertIn("Game Actor", data["role_leaders_html"])
        self.assertNotIn("Movie Actor", data["role_leaders_html"])

    def test_media_type_movie_scopes_response_to_movie_cast(self):
        response = self.client.post(
            reverse("update_top_talent_sort"),
            {"sort_by": "plays", "media_type": "movie"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("Movie Actor", data["role_leaders_html"])
        self.assertNotIn("Game Actor", data["role_leaders_html"])

    def test_no_media_type_includes_both(self):
        response = self.client.post(
            reverse("update_top_talent_sort"),
            {"sort_by": "plays"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("Movie Actor", data["role_leaders_html"])
        self.assertIn("Game Actor", data["role_leaders_html"])

    def test_invalid_media_type_is_ignored(self):
        response = self.client.post(
            reverse("update_top_talent_sort"),
            {"sort_by": "plays", "media_type": "boardgame"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("Movie Actor", data["role_leaders_html"])
        self.assertIn("Game Actor", data["role_leaders_html"])
