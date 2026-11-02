from datetime import UTC, datetime

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from app.activity_builders import _build_detail_activity_state
from app.models import (
    TV,
    BasicMedia,
    Book,
    Episode,
    Item,
    Manga,
    MediaTypes,
    Podcast,
    Season,
    Sources,
    Status,
)


class PodcastActivityBuilderTests(TestCase):
    """Test podcast activity totals."""

    def test_progress_is_aggregated_as_minutes(self):
        """Podcast progress values are already stored in minutes."""
        user = get_user_model().objects.create_user(username="podcast-activity")
        first_item = Item.objects.create(
            media_id="podcast-episode-1",
            source=Sources.POCKETCASTS.value,
            media_type=MediaTypes.PODCAST.value,
            title="Episode One",
            runtime_minutes=30,
        )
        second_item = Item.objects.create(
            media_id="podcast-episode-2",
            source=Sources.POCKETCASTS.value,
            media_type=MediaTypes.PODCAST.value,
            title="Episode Two",
            runtime_minutes=45,
        )
        first = Podcast.objects.create(
            item=first_item,
            user=user,
            status=Status.COMPLETED.value,
            progress=30,
            end_date=datetime(2026, 3, 1, tzinfo=UTC),
        )
        second = Podcast.objects.create(
            item=second_item,
            user=user,
            status=Status.COMPLETED.value,
            progress=45,
            end_date=datetime(2026, 3, 2, tzinfo=UTC),
        )

        play_stats, subtitle = _build_detail_activity_state(
            MediaTypes.PODCAST.value,
            {"max_progress": 2},
            current_instance=first,
            user_medias=[first, second],
        )

        self.assertEqual(play_stats["total_minutes"], 75)
        self.assertEqual(play_stats["total_hours"], 1)
        self.assertEqual(play_stats["total_minutes_remainder"], 15)
        self.assertEqual(subtitle["duration_text"], "1h 15min listened")


class ReadingTimeActivityTests(TestCase):
    """The detail subtitle shows the time read, added up over every read."""

    def setUp(self):
        """Create a user."""
        self.user = get_user_model().objects.create_user(username="reading-activity")

    def state(self, media_type, model, item, *minutes):
        entries = [
            model.objects.create(
                item=item,
                user=self.user,
                status=Status.COMPLETED.value,
                progress=10,
                reading_time=value,
            )
            for value in minutes
        ]
        return _build_detail_activity_state(
            media_type,
            {},
            current_instance=entries[0],
            user_medias=entries,
        )

    def test_book_reads_add_up(self):
        item = Item.objects.create(
            media_id="b1",
            source=Sources.OPENLIBRARY.value,
            media_type=MediaTypes.BOOK.value,
            title="Dune",
        )

        _, subtitle = self.state(MediaTypes.BOOK.value, Book, item, 125, 60)

        self.assertEqual(subtitle["duration_text"], "3h 5min read")

    def test_manga_shows_its_time(self):
        item = Item.objects.create(
            media_id="m1",
            source=Sources.MAL.value,
            media_type=MediaTypes.MANGA.value,
            title="Berserk",
        )

        _, subtitle = self.state(MediaTypes.MANGA.value, Manga, item, 45)

        self.assertEqual(subtitle["duration_text"], "45min read")

    def test_no_time_means_no_duration(self):
        item = Item.objects.create(
            media_id="b2",
            source=Sources.OPENLIBRARY.value,
            media_type=MediaTypes.BOOK.value,
            title="Emma",
        )

        _, subtitle = self.state(MediaTypes.BOOK.value, Book, item, 0)

        self.assertIsNone(subtitle["duration_text"])


class TvActivityQueryTests(TestCase):
    """The TV subtitle reads the prefetched seasons and episodes, not the database."""

    def build_show(self, seasons, episodes):
        user = get_user_model().objects.create_user(username="tv-activity")
        tv_item = Item.objects.create(
            media_id="900",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Long Show",
        )
        tv = TV.objects.create(item=tv_item, user=user, status=Status.IN_PROGRESS.value)
        for season_number in range(1, seasons + 1):
            season_item = Item.objects.create(
                media_id="900",
                source=Sources.TMDB.value,
                media_type=MediaTypes.SEASON.value,
                title="Long Show",
                season_number=season_number,
            )
            season = Season.objects.create(
                item=season_item,
                user=user,
                related_tv=tv,
                status=Status.COMPLETED.value,
            )
            for episode_number in range(1, episodes + 1):
                episode_item = Item.objects.create(
                    media_id="900",
                    source=Sources.TMDB.value,
                    media_type=MediaTypes.EPISODE.value,
                    title="Long Show",
                    season_number=season_number,
                    episode_number=episode_number,
                    runtime_minutes=30,
                )
                Episode.objects.create(
                    item=episode_item,
                    related_season=season,
                    end_date=datetime(2026, 3, episode_number, tzinfo=UTC),
                )
        return user

    def stats_for(self, user):
        user_medias = list(
            BasicMedia.objects.filter_media_prefetch(
                user,
                "900",
                MediaTypes.TV.value,
                Sources.TMDB.value,
            ),
        )
        with CaptureQueriesContext(connection) as queries:
            play_stats, _ = _build_detail_activity_state(
                MediaTypes.TV.value,
                {},
                current_instance=user_medias[0],
                user_medias=user_medias,
            )
        return play_stats, len(queries)

    def test_activity_stats_issue_no_queries_per_season(self):
        stats_small, queries_small = self.stats_for(self.build_show(2, 3))
        self.assertEqual(stats_small["episode_count"], 6)
        self.assertEqual(stats_small["total_minutes"], 180)
        self.assertEqual(queries_small, 0)

    def test_query_count_does_not_grow_with_seasons(self):
        play_stats, queries = self.stats_for(self.build_show(6, 4))
        self.assertEqual(play_stats["episode_count"], 24)
        self.assertEqual(queries, 0)
