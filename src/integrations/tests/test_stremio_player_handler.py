from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from app.mixins import disable_fetch_releases
from app.models import Item, Movie, MoviePlay, PlaybackProgress
from app.models.choices import MediaTypes, Sources
from integrations import stremio_tracker as tracker

User = get_user_model()


class RecordPlayerEventTests(TestCase):
    def setUp(self):
        # The session lives in the cache and is keyed on the user id, which
        # restarts at 1 in every test; without a clear, one test's session
        # leaks into the next and the monotonic-position rule pins it.
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user(username="player", password="x")
        with disable_fetch_releases():
            # The shape the Stremio importer creates: a numeric TMDB media_id
            # with the IMDB id (what Stremio sends) in provider_external_ids.
            self.item = Item.objects.create(
                media_id="700",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                provider_external_ids={"imdb_id": "tt700"},
                title="Played",
                image="",
            )
            Movie.objects.create(item=self.item, user=self.user)

    def _progress(self):
        return PlaybackProgress.objects.get(user=self.user, item=self.item)

    def _plays(self):
        return Movie.objects.get(item=self.item, user=self.user).plays.count()

    def test_start_records_a_position(self):
        status = tracker.record_player_event(
            self.user,
            "movie",
            "tt700",
            "action=start&currentTime=60000&duration=600000",
        )

        self.assertEqual(status, "recorded")
        self.assertEqual(self._progress().position_seconds, 60)

    def test_pause_records_the_position(self):
        tracker.record_player_event(
            self.user,
            "movie",
            "tt700",
            "action=pause&currentTime=120000&duration=600000",
        )

        self.assertEqual(self._progress().position_seconds, 120)

    def test_malformed_extra_is_ignored_not_crashed(self):
        status = tracker.record_player_event(
            self.user,
            "movie",
            "tt700",
            "action=&currentTime=abc",
        )

        self.assertEqual(status, "invalid_extra")
        self.assertFalse(
            PlaybackProgress.objects.filter(user=self.user, item=self.item).exists(),
        )

    def test_missing_extra_is_ignored(self):
        status = tracker.record_player_event(self.user, "movie", "tt700", "")

        self.assertEqual(status, "invalid_extra")

    def test_unknown_media_is_skipped(self):
        status = tracker.record_player_event(
            self.user,
            "movie",
            "tt999",
            "action=start&currentTime=1000&duration=2000",
        )

        self.assertEqual(status, "unresolved_media")

    def test_stop_at_seventy_five_percent_appends_a_play(self):
        """The flag drives completion; is_played() would not fire here."""
        status = tracker.record_player_event(
            self.user,
            "movie",
            "tt700",
            "action=stop&currentTime=450000&duration=600000",
        )

        self.assertEqual(status, "recorded")
        self.assertEqual(self._plays(), 1)

    def test_stop_below_the_threshold_does_not_append_a_play(self):
        """A stop at 40% is not a completion: the provisional needs 70%.

        The library flag is what confirms watched-ness; a position-based
        provisional must not guess below Stremio's own threshold.
        """
        status = tracker.record_player_event(
            self.user,
            "movie",
            "tt700",
            "action=stop&currentTime=240000&duration=600000",
        )

        self.assertEqual(status, "recorded")
        self.assertEqual(self._plays(), 0)
        self.assertFalse(self._progress().completed)

    def test_pause_after_completion_keeps_the_progress_row_completed(self):
        """A pause must not clear a completed session.

        `watched=False` asserts the media is NOT watched and clears the
        completed session, so passing it for a pause would flip a finished
        item back to unwatched and resurrect its continue-watching row. The
        handler must pass `None` — "no assertion" — for anything but a
        threshold-meeting stop.
        """
        tracker.record_player_event(
            self.user,
            "movie",
            "tt700",
            "action=stop&currentTime=450000&duration=600000",
        )
        self.assertTrue(self._progress().completed)

        tracker.record_player_event(
            self.user,
            "movie",
            "tt700",
            "action=pause&currentTime=460000&duration=600000",
        )

        self.assertTrue(self._progress().completed)
        self.assertEqual(self._plays(), 1)

    def test_a_rewatch_appends_a_second_play(self):
        """A second viewing counts as a second play.

        The later `start` must cross a session boundary; if the handler folds
        it into the settled session, `play_recorded` stays true and the second
        completion is deduped away.
        """
        first = timezone.now()
        tracker.record_player_event(
            self.user,
            "movie",
            "tt700",
            "action=stop&currentTime=450000&duration=600000",
            now=first,
        )
        self.assertEqual(self._plays(), 1)

        # Beyond the shared dedupe window (3h when the item's runtime is
        # unknown), so this is genuinely a second viewing rather than the same
        # one re-reported.
        later = first + timedelta(hours=4)
        tracker.record_player_event(
            self.user,
            "movie",
            "tt700",
            "action=start&currentTime=0&duration=600000",
            now=later,
        )
        tracker.record_player_event(
            self.user,
            "movie",
            "tt700",
            "action=stop&currentTime=450000&duration=600000",
            now=later + timedelta(seconds=1),
        )

        self.assertEqual(self._plays(), 2)

    def test_a_legacy_movie_play_suppresses_the_tracker_append(self):
        """The 90%-completion verifier and the client's `stop` are one play.

        The legacy path stores its play as a `MoviePlay` row (what `Movie.watch`
        creates); the tracker must measure its own append against it, or one
        finished movie lands as two history rows.
        """
        ended = timezone.now()
        movie = Movie.objects.get(item=self.item, user=self.user)
        MoviePlay.objects.create(movie=movie, end_date=ended)

        tracker.record_player_event(
            self.user,
            "movie",
            "tt700",
            "action=stop&currentTime=450000&duration=600000",
            now=ended + timedelta(minutes=1),
        )

        self.assertEqual(self._plays(), 1)

    def test_a_legacy_importer_movie_row_suppresses_the_tracker_append(self):
        """The importer shape: an extra completed `Movie` row is one play.

        `existing_movie_play_times` reads both storage shapes, so a completed
        `Movie` row with an `end_date` must suppress the tracker's append just
        as a `MoviePlay` does.
        """
        ended = timezone.now()
        Movie.objects.create(item=self.item, user=self.user, end_date=ended)

        tracker.record_player_event(
            self.user,
            "movie",
            "tt700",
            "action=stop&currentTime=450000&duration=600000",
            now=ended + timedelta(minutes=1),
        )

        # A second Movie row means `Movie.objects.get` is ambiguous, so count
        # the plays directly: the tracker appended none.
        self.assertEqual(
            MoviePlay.objects.filter(
                movie__item=self.item, movie__user=self.user
            ).count(),
            0,
        )
