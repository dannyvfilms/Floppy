import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from app.models import (
    TV,
    CreditRoleType,
    Episode,
    Game,
    Item,
    ItemPersonCredit,
    ItemStudioCredit,
    MediaTypes,
    Movie,
    Person,
    PersonGender,
    Season,
    Sources,
    Status,
    Studio,
)
from app.statistics_cache import get_statistics_data
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


class NoDateEntriesInAllTimeTopTalentTests(TestCase):
    """Regression tests for #1098: entries with no start/end date should still
    count toward "All Time" top talent, but not toward a concrete date range.
    """

    # A past range guaranteed not to overlap any dateless entry.
    RANGE_START = datetime.datetime(2000, 1, 1, tzinfo=datetime.UTC)
    RANGE_END = datetime.datetime(2000, 1, 31, tzinfo=datetime.UTC)

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="no-date-talent-tester",
            password="password123",
        )

    def test_movie_with_no_dates_included_in_all_time_top_actors(self):
        movie_item = Item.objects.create(
            media_id="tmdb-300",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Undated Movie",
        )
        Movie.objects.create(
            item=movie_item,
            user=self.user,
            status=Status.COMPLETED.value,
            start_date=None,
            end_date=None,
        )
        person = Person.objects.create(
            source=Sources.TMDB.value,
            source_person_id="300",
            name="Undated Movie Actor",
            gender=PersonGender.MALE.value,
        )
        ItemPersonCredit.objects.create(
            item=movie_item,
            person=person,
            role_type=CreditRoleType.CAST.value,
            role="Lead",
        )

        all_time_result = _aggregate_top_talent(
            self.user,
            start_date=None,
            end_date=None,
            schedule_missing_backfill=False,
        )
        actor_names = {row["name"] for row in all_time_result["top_actors"]}
        self.assertIn("Undated Movie Actor", actor_names)

        ranged_result = _aggregate_top_talent(
            self.user,
            start_date=self.RANGE_START,
            end_date=self.RANGE_END,
            schedule_missing_backfill=False,
        )
        ranged_actor_names = {row["name"] for row in ranged_result["top_actors"]}
        self.assertNotIn("Undated Movie Actor", ranged_actor_names)

    def test_game_with_no_dates_included_in_all_time_top_actors(self):
        game_item = Item.objects.create(
            media_id="igdb-300",
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            title="Undated Game",
        )
        Game.objects.create(
            item=game_item,
            user=self.user,
            status=Status.COMPLETED.value,
            progress=1,
            start_date=None,
            end_date=None,
        )
        person = Person.objects.create(
            source=Sources.IMDB.value,
            source_person_id="nm0000300",
            name="Undated Game Actor",
            gender=PersonGender.MALE.value,
        )
        ItemPersonCredit.objects.create(
            item=game_item,
            person=person,
            role_type=CreditRoleType.CAST.value,
            role="Lead",
        )

        all_time_result = _aggregate_top_talent(
            self.user,
            start_date=None,
            end_date=None,
            schedule_missing_backfill=False,
        )
        actor_names = {row["name"] for row in all_time_result["top_actors"]}
        self.assertIn("Undated Game Actor", actor_names)

        ranged_result = _aggregate_top_talent(
            self.user,
            start_date=self.RANGE_START,
            end_date=self.RANGE_END,
            schedule_missing_backfill=False,
        )
        ranged_actor_names = {row["name"] for row in ranged_result["top_actors"]}
        self.assertNotIn("Undated Game Actor", ranged_actor_names)

    def test_episode_with_no_end_date_included_in_all_time_top_actors(self):
        show_item = Item.objects.create(
            media_id="tmdb-400",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Undated Show",
        )
        tv = TV.objects.create(
            item=show_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        season_item = Item.objects.create(
            media_id="tmdb-400",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title="Undated Show",
        )
        season = Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=tv,
            status=Status.IN_PROGRESS.value,
        )
        episode_item = Item.objects.create(
            media_id="tmdb-400",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title="Undated Episode",
        )
        Episode.objects.create(
            item=episode_item,
            related_season=season,
            end_date=None,
        )
        person = Person.objects.create(
            source=Sources.TMDB.value,
            source_person_id="400",
            name="Undated Episode Actor",
            gender=PersonGender.MALE.value,
        )
        ItemPersonCredit.objects.create(
            item=episode_item,
            person=person,
            role_type=CreditRoleType.CAST.value,
            role="Lead",
        )

        all_time_result = _aggregate_top_talent(
            self.user,
            start_date=None,
            end_date=None,
            schedule_missing_backfill=False,
        )
        actor_names = {row["name"] for row in all_time_result["top_actors"]}
        self.assertIn("Undated Episode Actor", actor_names)

        ranged_result = _aggregate_top_talent(
            self.user,
            start_date=self.RANGE_START,
            end_date=self.RANGE_END,
            schedule_missing_backfill=False,
        )
        ranged_actor_names = {row["name"] for row in ranged_result["top_actors"]}
        self.assertNotIn("Undated Episode Actor", ranged_actor_names)

    def test_all_time_page_shows_talent_when_only_activity_is_dateless(self):
        """Regression test for the day-cache gap flagged in PR #1126 review.

        When a user's only movie/TV activity has no recorded date at all, the
        day-bucketed play counts that gate top-talent computation never see
        it, so the "All Time" page must fall back to a direct existence
        check (see `_has_dateless_movie_or_episode_activity` in
        statistics_aggregator.py) rather than reporting empty top talent.
        """
        movie_item = Item.objects.create(
            media_id="tmdb-500",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Only Undated Movie",
        )
        Movie.objects.create(
            item=movie_item,
            user=self.user,
            status=Status.COMPLETED.value,
            start_date=None,
            end_date=None,
        )
        person = Person.objects.create(
            source=Sources.TMDB.value,
            source_person_id="500",
            name="Only Undated Movie Actor",
            gender=PersonGender.MALE.value,
        )
        ItemPersonCredit.objects.create(
            item=movie_item,
            person=person,
            role_type=CreditRoleType.CAST.value,
            role="Lead",
        )

        data = get_statistics_data(self.user, start_date=None, end_date=None)

        actor_names = {
            row["name"] for row in data["top_talent"]["by_sort"]["plays"]["top_actors"]
        }
        self.assertIn("Only Undated Movie Actor", actor_names)
