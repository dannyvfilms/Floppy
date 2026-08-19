from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, tag

from app.models import (
    TV,
    Episode,
    Item,
    MediaTypes,
    Season,
    Sources,
    Status,
)

mock_path = Path(__file__).resolve().parent.parent / "mock_data"


class TVModel(TestCase):
    """Test the @properties and custom save of the TV model."""

    def setUp(self):
        """Create a user and a season with episodes."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

        item_season1 = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=1,
        )

        season1 = Season.objects.create(
            item=item_season1,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

        self.tv = TV.objects.get(user=self.user)

        item_ep1 = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=1,
            episode_number=1,
        )
        Episode.objects.create(
            item=item_ep1,
            related_season=season1,
            end_date=datetime(2023, 6, 1, 0, 0, tzinfo=UTC),
        )

        item_ep2 = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=1,
            episode_number=2,
        )
        Episode.objects.create(
            item=item_ep2,
            related_season=season1,
            end_date=datetime(2023, 6, 2, 0, 0, tzinfo=UTC),
        )

        item_season2 = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=2,
        )

        season2 = Season.objects.create(
            item=item_season2,
            related_tv=self.tv,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

        item_ep3 = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=2,
            episode_number=1,
        )
        Episode.objects.create(
            item=item_ep3,
            related_season=season2,
            end_date=datetime(2023, 6, 4, 0, 0, tzinfo=UTC),
        )

        item_ep4 = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=2,
            episode_number=2,
        )
        Episode.objects.create(
            item=item_ep4,
            related_season=season2,
            end_date=datetime(2023, 6, 5, 0, 0, tzinfo=UTC),
        )

    def test_tv_progress(self):
        """Test the progress property of the Season model."""
        self.assertEqual(self.tv.progress, 4)

    def test_tv_start_date(self):
        """Test the start_date property of the Season model."""
        self.assertEqual(
            self.tv.start_date,
            datetime(2023, 6, 1, 0, 0, tzinfo=UTC),
        )

    def test_tv_end_date(self):
        """Test the end_date property of the Season model."""
        self.assertEqual(
            self.tv.end_date,
            datetime(2023, 6, 5, 0, 0, tzinfo=UTC),
        )

    @tag("network")
    def test_tv_save(self):
        """Test the custom save method of the TV model."""
        self.tv.status = Status.COMPLETED.value
        self.tv.save(update_fields=["status"])

        self.assertEqual(
            self.tv.seasons.filter(status=Status.COMPLETED.value).count(),
            10,
        )


class TVSkipAheadProgressTests(TestCase):
    """Regression for #527: show-level count vs. furthest-position semantics."""

    def setUp(self):
        """Create a show with one normally-watched season and one skip-ahead season."""
        self.credentials = {"username": "skip-ahead-test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

        tv_item = Item.objects.create(
            media_id="5555",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Skip Ahead Show",
            image="http://example.com/show.jpg",
        )
        self.tv = TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

        item_season1 = Item.objects.create(
            media_id="5555",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Skip Ahead Show",
            image="http://example.com/image.jpg",
            season_number=1,
        )
        self.season1 = Season.objects.create(
            item=item_season1,
            user=self.user,
            related_tv=self.tv,
            status=Status.IN_PROGRESS.value,
        )
        for ep_num in (1, 2):
            item = Item.objects.create(
                media_id="5555",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title="Skip Ahead Show",
                image="http://example.com/image.jpg",
                season_number=1,
                episode_number=ep_num,
            )
            Episode.objects.create(
                item=item,
                related_season=self.season1,
                end_date=datetime(2023, 6, ep_num, 0, 0, tzinfo=UTC),
            )

        item_season2 = Item.objects.create(
            media_id="5555",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Skip Ahead Show",
            image="http://example.com/image.jpg",
            season_number=2,
        )
        self.season2 = Season.objects.create(
            item=item_season2,
            user=self.user,
            related_tv=self.tv,
            status=Status.IN_PROGRESS.value,
        )
        item_ep9 = Item.objects.create(
            media_id="5555",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Skip Ahead Show",
            image="http://example.com/image.jpg",
            season_number=2,
            episode_number=9,
        )
        Episode.objects.create(
            item=item_ep9,
            related_season=self.season2,
            end_date=datetime(2023, 6, 9, 0, 0, tzinfo=UTC),
        )

        item_season3 = Item.objects.create(
            media_id="5555",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Skip Ahead Show",
            image="http://example.com/image.jpg",
            season_number=3,
        )
        self.dropped_season = Season.objects.create(
            item=item_season3,
            user=self.user,
            related_tv=self.tv,
            status=Status.DROPPED.value,
        )
        item_dropped_ep = Item.objects.create(
            media_id="5555",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Skip Ahead Show",
            image="http://example.com/image.jpg",
            season_number=3,
            episode_number=1,
        )
        Episode.objects.create(
            item=item_dropped_ep,
            related_season=self.dropped_season,
            end_date=datetime(2023, 7, 1, 0, 0, tzinfo=UTC),
        )

    def test_tv_completed_episode_count_excludes_dropped_seasons(self):
        """Completed episode count should sum non-dropped seasons only."""
        self.assertEqual(self.tv.progress, 11)  # 2 + 9, position-based (unchanged)
        self.assertEqual(self.tv.completed_episode_count, 3)  # 2 + 1, count-based

    def test_tv_plays_sort_value_uses_completed_count(self):
        """Regression for #527: plays should reflect episodes watched, not position."""
        self.assertEqual(self.tv._plays_sort_value(), 3)

    def test_tv_progress_percentage_uses_completed_count(self):
        """Regression for #527: percentage should reflect episodes watched, not position."""
        self.tv.max_progress = 20
        self.assertEqual(self.tv.progress_percentage, 15)  # 3 / 20 * 100

    def test_tv_progress_percentage_none_without_max_progress(self):
        """No max_progress attribute means percentage can't be computed."""
        self.assertIsNone(self.tv.progress_percentage)


class TVGroupedAnimeSkipAheadTests(TestCase):
    """Regression for #527: grouped anime reuses the Season/TV models and fix."""

    def setUp(self):
        """Create a grouped-anime season with only a later episode watched."""
        self.credentials = {"username": "anime-skip-test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

        item_season = Item.objects.create(
            media_id="7777",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            library_media_type=MediaTypes.ANIME.value,
            title="Grouped Anime Show",
            image="http://example.com/image.jpg",
            season_number=1,
        )
        self.season = Season.objects.create(
            item=item_season,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        item_ep9 = Item.objects.create(
            media_id="7777",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            library_media_type=MediaTypes.ANIME.value,
            title="Grouped Anime Show",
            image="http://example.com/image.jpg",
            season_number=1,
            episode_number=9,
        )
        Episode.objects.create(
            item=item_ep9,
            related_season=self.season,
            end_date=datetime(2023, 6, 9, 0, 0, tzinfo=UTC),
        )

    def test_grouped_anime_plays_and_percentage_use_completed_count(self):
        """Grouped anime should get the same count-based fix as regular TV seasons."""
        self.season.max_progress = 10

        self.assertEqual(self.season.progress, 9)
        self.assertEqual(self.season._plays_sort_value(), 1)
        self.assertEqual(self.season.progress_percentage, 10)


class TVStatusTests(TestCase):
    """Test TV model status change behaviors."""

    def setUp(self):
        """Create test data."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

        self.tv_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Test Show",
            image="http://example.com/image.jpg",
        )

        self.tv = TV.objects.create(
            item=self.tv_item,
            user=self.user,
            status=Status.PLANNING.value,
        )

        self.season1_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Test Show",
            image="http://example.com/image.jpg",
            season_number=1,
        )

        self.season1 = Season.objects.create(
            item=self.season1_item,
            user=self.user,
            related_tv=self.tv,
            status=Status.IN_PROGRESS.value,
        )

        self.season2_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Test Show",
            image="http://example.com/image.jpg",
            season_number=2,
        )

        self.season2 = Season.objects.create(
            item=self.season2_item,
            user=self.user,
            related_tv=self.tv,
            status=Status.PLANNING.value,
        )

    @patch("app.models.providers.services.get_media_metadata")
    def test_completed_status_creates_all_seasons(self, mock_get_metadata):
        """Test setting status to COMPLETED creates all seasons."""
        mock_metadata = {
            "max_progress": 10,
            "related": {
                "seasons": [
                    {"season_number": 1, "image": "img1.jpg"},
                    {"season_number": 2, "image": "img2.jpg"},
                    {"season_number": 3, "image": "img3.jpg"},
                ],
            },
            "season/1": {
                "image": "http://example.com/image.jpg",
                "season_number": 1,
                "episodes": [{"episode_number": 1}] * 10,
            },
            "season/2": {
                "image": "http://example.com/image.jpg",
                "season_number": 2,
                "episodes": [{"episode_number": 1}] * 10,
            },
            "season/3": {
                "image": "http://example.com/image.jpg",
                "season_number": 3,
                "episodes": [{"episode_number": 1}] * 10,
            },
        }
        mock_get_metadata.return_value = mock_metadata

        self.tv.status = Status.COMPLETED.value
        self.tv.save()

        self.assertEqual(self.tv.seasons.count(), 3)
        self.assertEqual(
            self.tv.seasons.filter(status=Status.COMPLETED.value).count(),
            3,
        )

        for season in self.tv.seasons.all():
            self.assertTrue(season.episodes.exists())

    def test_dropped_status_marks_in_progress_seasons_dropped(self):
        """Test setting status to DROPPED marks in-progress seasons as dropped."""
        season3_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Test Show",
            image="http://example.com/image.jpg",
            season_number=3,
        )

        Season.objects.create(
            item=season3_item,
            user=self.user,
            related_tv=self.tv,
            status=Status.IN_PROGRESS.value,
        )

        self.tv.status = Status.DROPPED.value
        self.tv.save()

        self.assertEqual(
            self.tv.seasons.filter(status=Status.DROPPED.value).count(),
            2,  # season1 and season3
        )
        self.assertEqual(
            self.tv.seasons.filter(status=Status.PLANNING.value).count(),
            1,
        )

    @patch("app.models.providers.services.get_media_metadata")
    def test_in_progress_status_activates_next_season(self, _):
        """Test setting status to IN_PROGRESS activates next available season."""
        self.season1.status = Status.COMPLETED.value
        self.season1.save()

        self.tv.status = Status.IN_PROGRESS.value
        self.tv.save()

        season2 = Season.objects.get(pk=self.season2.pk)
        self.assertEqual(season2.status, Status.IN_PROGRESS.value)

    @patch("app.models.providers.services.get_media_metadata")
    def test_in_progress_status_creates_new_season_if_needed(self, mock_get_metadata):
        """Test setting status to IN_PROGRESS creates new season if needed."""
        self.season1.status = Status.COMPLETED.value
        self.season1.save()
        self.season2.status = Status.COMPLETED.value
        self.season2.save()

        mock_metadata = {
            "related": {
                "seasons": [
                    {"season_number": 1, "image": "img1.jpg"},
                    {"season_number": 2, "image": "img2.jpg"},
                    {"season_number": 3, "image": "img3.jpg"},
                ],
            },
        }
        mock_get_metadata.return_value = mock_metadata

        self.tv.status = Status.IN_PROGRESS.value
        self.tv.save()

        season3 = self.tv.seasons.get(item__season_number=3)
        self.assertEqual(season3.status, Status.IN_PROGRESS.value)

    def test_in_progress_status_noop_if_already_has_in_progress_season(self):
        """Test IN_PROGRESS status change does nothing if season already in progress."""
        original_season1_status = self.season1.status

        self.tv.status = Status.IN_PROGRESS.value
        self.tv.save()

        season1 = Season.objects.get(pk=self.season1.pk)
        self.assertEqual(season1.status, original_season1_status)


class TVSpecialActivityTests(TestCase):
    """Test show-level activity dates when specials are watched."""

    def setUp(self):
        """Create a TV entry with a regular season and a watched special."""
        self.credentials = {"username": "specials-test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.regular_watch = datetime(2023, 8, 28, 0, 0, tzinfo=UTC)
        self.special_watch = datetime(2026, 3, 12, 0, 0, tzinfo=UTC)

        tv_item = Item.objects.create(
            media_id="114410",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Chainsaw Man",
            image="http://example.com/show.jpg",
        )
        self.tv = TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

        season_one_item = Item.objects.create(
            media_id="114410",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Chainsaw Man",
            image="http://example.com/season1.jpg",
            season_number=1,
        )
        # Create as PLANNING then flip via update() so the fixture does not
        # trigger the completed-on-create fan-out (which fetches metadata).
        season_one = Season.objects.create(
            item=season_one_item,
            user=self.user,
            related_tv=self.tv,
            status=Status.PLANNING.value,
        )
        Season.objects.filter(pk=season_one.pk).update(
            status=Status.COMPLETED.value,
        )
        season_one.refresh_from_db()
        regular_episode = Episode(
            item=Item.objects.create(
                media_id="114410",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title="Chainsaw Man",
                image="http://example.com/episode1.jpg",
                season_number=1,
                episode_number=12,
            ),
            related_season=season_one,
            end_date=self.regular_watch,
        )

        special_item = Item.objects.create(
            media_id="114410",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Chainsaw Man",
            image="http://example.com/specials.jpg",
            season_number=0,
        )
        specials = Season.objects.create(
            item=special_item,
            user=self.user,
            related_tv=self.tv,
            status=Status.PLANNING.value,
        )
        Season.objects.filter(pk=specials.pk).update(
            status=Status.COMPLETED.value,
        )
        specials.refresh_from_db()
        special_episode = Episode(
            item=Item.objects.create(
                media_id="114410",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title="Chainsaw Man",
                image="http://example.com/special-episode.jpg",
                season_number=0,
                episode_number=1,
            ),
            related_season=specials,
            end_date=self.special_watch,
        )
        Episode.objects.bulk_create([regular_episode, special_episode])

    def test_specials_do_not_change_show_progress_or_started_date(self):
        """Specials should not change main-series progress semantics."""
        self.assertEqual(self.tv.progress, 12)
        self.assertEqual(self.tv.start_date, self.regular_watch)

    def test_specials_advance_show_end_date_and_recent_activity(self):
        """A watched special should update the show's latest activity date."""
        self.assertEqual(self.tv.end_date, self.special_watch)
        self.assertEqual(self.tv.progressed_at, self.special_watch)
