from datetime import UTC, datetime

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import Item, MediaTypes, Movie, MoviePlay, Sources, Status


class MovieWatchModel(TestCase):
    """Test Movie.watch()/unwatch() (issue #577)."""

    def setUp(self):
        """Create a user and a tracked movie."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

        item = Item.objects.create(
            media_id="27205",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Inception",
            image="http://example.com/image.jpg",
        )
        self.movie = Movie.objects.create(
            item=item,
            user=self.user,
            status=Status.PLANNING.value,
        )

    def test_watch_creates_play_and_updates_tracker(self):
        """First watch creates a play and syncs end_date/status onto Movie."""
        end_date = datetime(2024, 1, 1, tzinfo=UTC)
        play, created = self.movie.watch(end_date)

        self.assertTrue(created)
        self.assertEqual(play.end_date, end_date)
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.end_date, end_date)
        self.assertEqual(self.movie.status, Status.COMPLETED.value)

    def test_repeated_watch_creates_multiple_plays(self):
        """Three watches leave three plays; tracker end_date is the latest."""
        first = datetime(2023, 5, 14, tzinfo=UTC)
        second = datetime(2026, 2, 3, tzinfo=UTC)
        third = datetime(2026, 7, 19, tzinfo=UTC)

        self.movie.watch(first)
        self.movie.watch(second)
        self.movie.watch(third)

        self.assertEqual(MoviePlay.objects.filter(movie=self.movie).count(), 3)
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.end_date, third)

    def test_watch_lazily_backfills_preexisting_end_date(self):
        """A pre-existing end_date is preserved as a play on first watch()."""
        preexisting = datetime(2020, 1, 1, tzinfo=UTC)
        self.movie.end_date = preexisting
        self.movie.save(update_fields=["end_date"])

        self.movie.watch(datetime(2026, 1, 1, tzinfo=UTC))

        self.assertEqual(MoviePlay.objects.filter(movie=self.movie).count(), 2)
        self.assertTrue(
            MoviePlay.objects.filter(movie=self.movie, end_date=preexisting).exists(),
        )

    def test_watch_idempotent_external_id(self):
        """A duplicate external_id returns the existing play without creating one."""
        first_play, first_created = self.movie.watch(
            datetime(2024, 1, 1, tzinfo=UTC),
            external_id="evt-1",
        )
        second_play, second_created = self.movie.watch(
            datetime(2024, 6, 1, tzinfo=UTC),
            external_id="evt-1",
        )

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first_play.id, second_play.id)
        self.assertEqual(MoviePlay.objects.filter(movie=self.movie).count(), 1)

    def test_unwatch_removes_most_recent_play_by_end_date(self):
        """unwatch() removes the play with the latest end_date, not creation order."""
        self.movie.watch(datetime(2024, 1, 1, tzinfo=UTC))
        self.movie.watch(datetime(2024, 2, 1, tzinfo=UTC))

        removed = self.movie.unwatch()

        self.assertEqual(removed.end_date, datetime(2024, 2, 1, tzinfo=UTC))
        remaining = MoviePlay.objects.filter(movie=self.movie)
        self.assertEqual(remaining.count(), 1)
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.end_date, datetime(2024, 1, 1, tzinfo=UTC))

    def test_unwatch_last_play_clears_end_date(self):
        """Removing the only play clears the tracker's end_date."""
        self.movie.watch(datetime(2024, 1, 1, tzinfo=UTC))

        self.movie.unwatch()

        self.movie.refresh_from_db()
        self.assertIsNone(self.movie.end_date)
        self.assertFalse(MoviePlay.objects.filter(movie=self.movie).exists())

    def test_unwatch_with_no_plays_returns_none(self):
        """unwatch() on a movie with no plays is a no-op."""
        self.assertIsNone(self.movie.unwatch())

    def test_unwatch_by_external_id(self):
        """unwatch(external_id=...) targets a specific play."""
        self.movie.watch(datetime(2024, 1, 1, tzinfo=UTC), external_id="a")
        self.movie.watch(datetime(2024, 2, 1, tzinfo=UTC), external_id="b")

        removed = self.movie.unwatch(external_id="a")

        self.assertEqual(removed.external_id, "a")
        remaining = MoviePlay.objects.filter(movie=self.movie)
        self.assertEqual(remaining.count(), 1)
        self.assertEqual(remaining.first().external_id, "b")
