from datetime import UTC, datetime

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.activity_builders import _build_detail_activity_state
from app.models import Book, Item, Manga, MediaTypes, Podcast, Sources, Status


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
