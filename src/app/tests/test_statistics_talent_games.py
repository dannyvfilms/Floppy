from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from app.models import (
    CreditRoleType,
    Game,
    Item,
    ItemPersonCredit,
    ItemStudioCredit,
    MediaTypes,
    Movie,
    Person,
    PersonGender,
    Sources,
    Status,
    Studio,
)
from app.statistics_talent import _aggregate_top_talent, get_person_talent_totals


class GamesInTopTalentAggregationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="talent-tester",
            password="password123",
        )
        self.game_item = Item.objects.create(
            media_id="igdb-100",
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
        self.game_person = Person.objects.create(
            source=Sources.IMDB.value,
            source_person_id="nm0000001",
            name="Alice Actor",
            gender=PersonGender.FEMALE.value,
        )
        ItemPersonCredit.objects.create(
            item=self.game_item,
            person=self.game_person,
            role_type=CreditRoleType.CAST.value,
            role="Sam",
        )
        self.game_studio = Studio.objects.create(
            source=Sources.IGDB.value,
            source_studio_id="studio-100",
            name="Dispatch Studio",
        )
        ItemStudioCredit.objects.create(item=self.game_item, studio=self.game_studio)

        self.movie_item = Item.objects.create(
            media_id="tmdb-200",
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
        self.movie_person = Person.objects.create(
            source=Sources.TMDB.value,
            source_person_id="1",
            name="Bob Movie Star",
            gender=PersonGender.MALE.value,
        )
        ItemPersonCredit.objects.create(
            item=self.movie_item,
            person=self.movie_person,
            role_type=CreditRoleType.CAST.value,
            role="Hero",
        )

    def test_game_cast_appears_in_top_actors(self):
        result = _aggregate_top_talent(
            self.user,
            start_date=None,
            end_date=None,
            schedule_missing_backfill=False,
        )

        actress_names = {row["name"] for row in result["top_actresses"]}
        self.assertIn("Alice Actor", actress_names)

        entry = next(
            row for row in result["top_actresses"] if row["name"] == "Alice Actor"
        )
        self.assertEqual(entry["unique_titles"], 1)
        self.assertEqual(entry["unique_games"], 1)
        self.assertEqual(entry["unique_movies"], 0)

    def test_game_studios_appear_in_top_studios(self):
        result = _aggregate_top_talent(
            self.user,
            start_date=None,
            end_date=None,
            schedule_missing_backfill=False,
        )

        studio_entry = next(
            row for row in result["top_studios"] if row["name"] == "Dispatch Studio"
        )
        self.assertEqual(studio_entry["plays"], 1)
        self.assertEqual(studio_entry["unique_titles"], 1)
        self.assertEqual(studio_entry["unique_games"], 1)
        self.assertEqual(studio_entry["unique_movies"], 0)
        self.assertEqual(studio_entry["unique_shows"], 0)

    def test_movie_filter_excludes_game_cast(self):
        result = _aggregate_top_talent(
            self.user,
            start_date=None,
            end_date=None,
            schedule_missing_backfill=False,
            media_type=MediaTypes.MOVIE.value,
        )

        actress_names = {row["name"] for row in result["top_actresses"]}
        actor_names = {row["name"] for row in result["top_actors"]}
        self.assertNotIn("Alice Actor", actress_names)
        self.assertIn("Bob Movie Star", actor_names)

    def test_game_filter_excludes_movie_cast(self):
        result = _aggregate_top_talent(
            self.user,
            start_date=None,
            end_date=None,
            schedule_missing_backfill=False,
            media_type=MediaTypes.GAME.value,
        )

        actor_names = {row["name"] for row in result["top_actors"]}
        actress_names = {row["name"] for row in result["top_actresses"]}
        self.assertNotIn("Bob Movie Star", actor_names)
        self.assertIn("Alice Actor", actress_names)

    def test_imdb_game_cast_with_unknown_gender_falls_back_to_actor_and_uses_game_minutes(
        self,
    ):
        unknown_item = Item.objects.create(
            media_id="igdb-101",
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            title="Unknown Gender Game",
            image="http://example.com/game-unknown.jpg",
        )
        Game.objects.create(
            item=unknown_item,
            user=self.user,
            status=Status.COMPLETED.value,
            progress=135,
            end_date=timezone.now(),
        )
        unknown_person = Person.objects.create(
            source=Sources.IMDB.value,
            source_person_id="nm0000009",
            name="Unknown Gender Performer",
            gender=PersonGender.UNKNOWN.value,
        )
        ItemPersonCredit.objects.create(
            item=unknown_item,
            person=unknown_person,
            role_type=CreditRoleType.CAST.value,
            role="Lead",
        )

        result = _aggregate_top_talent(
            self.user,
            start_date=None,
            end_date=None,
            schedule_missing_backfill=False,
        )

        actor_entry = next(
            row
            for row in result["top_actors"]
            if row["name"] == "Unknown Gender Performer"
        )
        self.assertEqual(actor_entry["watched_minutes"], 135)
        self.assertEqual(actor_entry["watched_time"], "2h 15min")

    def test_person_talent_totals_include_unknown_gender_imdb_game_cast(self):
        unknown_item = Item.objects.create(
            media_id="igdb-102",
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            title="Dispatch Two",
            image="http://example.com/game-two.jpg",
        )
        Game.objects.create(
            item=unknown_item,
            user=self.user,
            status=Status.COMPLETED.value,
            progress=90,
            end_date=timezone.now(),
        )
        unknown_person = Person.objects.create(
            source=Sources.IMDB.value,
            source_person_id="nm0000010",
            name="Dispatch Performer",
            gender=PersonGender.UNKNOWN.value,
        )
        ItemPersonCredit.objects.create(
            item=unknown_item,
            person=unknown_person,
            role_type=CreditRoleType.CAST.value,
            role="Lead",
        )

        totals = get_person_talent_totals(
            self.user,
            unknown_person.source,
            unknown_person.source_person_id,
        )

        self.assertEqual(totals["bucket"], "actor")
        self.assertEqual(totals["watched_minutes"], 90)
        self.assertEqual(totals["unique_titles"], 1)
        self.assertEqual(totals["unique_games"], 1)
        self.assertEqual(totals["unique_movies"], 0)
