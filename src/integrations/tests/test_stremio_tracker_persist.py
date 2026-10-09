from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from app.mixins import disable_fetch_releases
from app.models import (
    TV,
    Episode,
    Item,
    Movie,
    PlaybackProgress,
    ProgressChange,
    Season,
    WatchStateSequence,
)
from app.models.choices import MediaTypes, Sources, Status
from integrations import stremio_tracker as tracker

User = get_user_model()


class PersistMergeResultTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="persist", password="x")
        self.item = Item.objects.create(
            media_id="tt500",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Persisted",
            image="",
        )
        self.movie = Movie.objects.create(item=self.item, user=self.user)

    def _result(self, **overrides):
        defaults = {
            "completed": False,
            "position_seconds": 120,
            "duration_seconds": 600,
            "record_play": False,
            "clear_progress": False,
        }
        defaults.update(overrides)
        return tracker.MergeResult(**defaults)

    def test_position_is_stored(self):
        tracker.persist_merge_result(
            self.user,
            self.item,
            self._result(),
            media_id="tt500",
            video_id=None,
            session_started_at=None,
            ended_at=None,
        )

        progress = PlaybackProgress.objects.get(user=self.user, item=self.item)
        self.assertEqual(progress.position_seconds, 120)
        self.assertEqual(progress.duration_seconds, 600)
        self.assertFalse(progress.completed)

    def test_position_without_duration_preserves_the_stored_duration(self):
        """A position-only observation must not wipe a known duration.

        Stremio's player events carry a duration, but a library or poll
        observation carries only a position. Writing ``None`` over the stored
        duration loses the runtime the resume bar is drawn from, so the shared
        sink's preserve flag has to be honoured here too.
        """
        tracker.persist_merge_result(
            self.user,
            self.item,
            self._result(position_seconds=120, duration_seconds=600),
            media_id="tt500",
            video_id=None,
            session_started_at=None,
            ended_at=None,
        )

        tracker.persist_merge_result(
            self.user,
            self.item,
            self._result(position_seconds=180, duration_seconds=None),
            media_id="tt500",
            video_id=None,
            session_started_at=None,
            ended_at=None,
        )

        progress = PlaybackProgress.objects.get(user=self.user, item=self.item)
        self.assertEqual(progress.position_seconds, 180)
        self.assertEqual(progress.duration_seconds, 600)

    def test_clear_progress_removes_the_row(self):
        PlaybackProgress.objects.create(
            user=self.user,
            item=self.item,
            position_seconds=300,
        )

        tracker.persist_merge_result(
            self.user,
            self.item,
            self._result(clear_progress=True, position_seconds=None),
            media_id="tt500",
            video_id=None,
            session_started_at=None,
            ended_at=None,
        )

        self.assertFalse(
            PlaybackProgress.objects.filter(user=self.user, item=self.item).exists(),
        )

    def test_completion_appends_one_history_play(self):
        recorded = tracker.persist_merge_result(
            self.user,
            self.item,
            self._result(completed=True, record_play=True, position_seconds=590),
            media_id="tt500",
            video_id=None,
            session_started_at=timezone.now(),
            ended_at=timezone.now(),
        )

        self.assertTrue(recorded)
        self.assertEqual(self.movie.plays.count(), 1)

    def test_completed_without_record_play_appends_nothing(self):
        """The append is gated by record_play, not re-derived from completed.

        Task 3 sets record_play only on the false->true transition, so a
        repeated observation arrives completed=True with record_play=False and
        must append nothing.
        """
        recorded = tracker.persist_merge_result(
            self.user,
            self.item,
            self._result(completed=True, record_play=False, position_seconds=590),
            media_id="tt500",
            video_id=None,
            session_started_at=timezone.now(),
            ended_at=timezone.now(),
        )

        self.assertFalse(recorded)
        self.assertEqual(self.movie.plays.count(), 0)

    def test_none_item_is_a_noop(self):
        self.assertFalse(
            tracker.persist_merge_result(
                self.user,
                None,
                self._result(completed=True, record_play=True),
                media_id="tt500",
                video_id=None,
                session_started_at=timezone.now(),
                ended_at=timezone.now(),
            ),
        )

    def test_replaying_the_same_session_does_not_append_twice(self):
        """The append dedup is the app-level pre-check in the watch call.

        The unique constraint on the play's external id is the backstop; the
        id is the session key, so a replay of one session is not a second play.
        """
        started = timezone.now()
        for _ in range(2):
            tracker.persist_merge_result(
                self.user,
                self.item,
                self._result(completed=True, record_play=True),
                media_id="tt500",
                video_id=None,
                session_started_at=started,
                ended_at=timezone.now(),
            )

        self.assertEqual(self.movie.plays.count(), 1)

    def test_a_second_session_appends_a_second_play(self):
        first = timezone.now()
        # Beyond the shared dedupe window, so this is genuinely a second
        # viewing rather than the same one re-reported.
        second = first + timedelta(hours=4)
        for started in (first, second):
            tracker.persist_merge_result(
                self.user,
                self.item,
                self._result(completed=True, record_play=True),
                media_id="tt500",
                video_id=None,
                session_started_at=started,
                ended_at=started,
            )

        self.assertEqual(self.movie.plays.count(), 2)


class RecordPollObservationTests(TestCase):
    """The poll wiring: a resume position reaches the durable store.

    This is the only path that stores a position for a client that cannot emit
    player events, so without it the row never appears.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="poll-wiring", password="x")
        with disable_fetch_releases():
            self.item = Item.objects.create(
                media_id="603",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                provider_external_ids={"imdb_id": "tt700"},
                title="Polled",
                image="",
            )
            self.movie = Movie.objects.create(
                item=self.item,
                user=self.user,
                status=Status.IN_PROGRESS.value,
            )

    def _observation(self, **overrides):
        defaults = {
            "action": "observed",
            "position_seconds": 300,
            "duration_seconds": 600,
            "watched": False,
            "observed_at": timezone.now(),
            "video_id": None,
            "records_play": False,
        }
        defaults.update(overrides)
        return tracker.Observation(**defaults)

    def test_a_poll_stores_the_resume_position(self):
        recorded = tracker.record_poll_observation(
            self.user,
            "movie",
            "tt700",
            self._observation(),
        )

        self.assertTrue(recorded)
        progress = PlaybackProgress.objects.get(user=self.user, item=self.item)
        self.assertEqual(progress.position_seconds, 300)
        self.assertEqual(progress.duration_seconds, 600)

    def test_a_watched_poll_appends_no_history_play(self):
        """The library flag is item state; the verifier owns the history row."""
        tracker.record_poll_observation(
            self.user,
            "movie",
            "tt700",
            self._observation(watched=True),
        )

        self.assertEqual(self.movie.plays.count(), 0)

    def test_an_unresolved_identity_stores_nothing(self):
        self.assertFalse(
            tracker.record_poll_observation(
                self.user,
                "movie",
                "tt999",
                self._observation(),
            ),
        )
        self.assertFalse(PlaybackProgress.objects.filter(user=self.user).exists())

class ProgressChangeEmissionTests(TestCase):
    """A tracker-driven write must feed the same change log as the API.

    Delta-sync clients learn about resume-position movement from
    ``ProgressChange`` rows, so a Stremio event that moves or clears a position
    without recording one is invisible to them.
    """

    def setUp(self):
        # Sessions live in the cache keyed on the user id, which restarts at 1
        # in every test; without a clear, one test's session leaks into the next.
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user(username="persist-changes", password="x")
        self.item = Item.objects.create(
            media_id="tt600",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            provider_external_ids={"imdb_id": "tt600"},
            title="Change Logged",
            image="",
        )
        Movie.objects.create(item=self.item, user=self.user)
        WatchStateSequence.objects.update_or_create(
            user=self.user,
            defaults={"emit_changes": True},
        )

    def _result(self, **overrides):
        defaults = {
            "completed": False,
            "position_seconds": 120,
            "duration_seconds": 600,
            "record_play": False,
            "clear_progress": False,
        }
        defaults.update(overrides)
        return tracker.MergeResult(**defaults)

    def test_a_position_update_records_a_progress_change(self):
        tracker.persist_merge_result(
            self.user,
            self.item,
            self._result(position_seconds=240),
            media_id="tt600",
            video_id=None,
            session_started_at=None,
            ended_at=None,
        )

        change = ProgressChange.objects.get(user=self.user, item=self.item)
        self.assertEqual(change.kind, "upsert")
        self.assertEqual(change.position_seconds, 240)

    def test_a_clear_records_a_delete_tombstone(self):
        PlaybackProgress.objects.create(
            user=self.user,
            item=self.item,
            position_seconds=300,
        )

        tracker.persist_merge_result(
            self.user,
            self.item,
            self._result(clear_progress=True, position_seconds=None),
            media_id="tt600",
            video_id=None,
            session_started_at=None,
            ended_at=None,
        )

        change = ProgressChange.objects.get(user=self.user, item=self.item)
        self.assertEqual(change.kind, "delete")

    def test_a_repeated_poll_records_no_second_progress_change(self):
        """Stremio repeats the same position between its ~90s pushes.

        The verifier polls every 5-120s and folds every poll into the merge
        point, so without the short-circuit each poll appended a
        `ProgressChange` row for a position that had not moved — and nothing
        prunes that table.
        """
        observation = tracker.Observation(
            action="observed",
            position_seconds=240,
            duration_seconds=600,
            watched=False,
            observed_at=timezone.now(),
            video_id=None,
            records_play=False,
        )

        for _ in range(2):
            self.assertTrue(
                tracker.record_poll_observation(
                    self.user,
                    "movie",
                    "tt600",
                    observation,
                ),
            )

        self.assertEqual(
            ProgressChange.objects.filter(user=self.user, item=self.item).count(),
            1,
        )
        progress = PlaybackProgress.objects.get(user=self.user, item=self.item)
        self.assertEqual(progress.position_seconds, 240)


class PersistMergeResultEpisodeTests(TestCase):
    """The episode branch: `Season.watch` through `episode.related_season`.

    Episodes are the high-volume path for Stremio playback, and their append
    goes through a different API than the movie branch — a `Season.watch`
    returning an `EpisodeWatchResult` instead of `Movie.watch`'s tuple.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="persist-episode", password="x")
        # Watching an episode resolves the episode Item and syncs the season
        # through provider metadata; the test network guard blocks the real
        # call, so stub the season payload the way the model tests do.
        metadata = patch(
            "app.models.providers.services.get_media_metadata",
            return_value={
                "season/1": {
                    "episodes": [{"episode_number": number} for number in (1, 2, 3)],
                },
                "related": {"seasons": [{"season_number": 1}]},
                # The credits backfill runs off Item saves; a real payload
                # carries these, and without them every save logs a warning.
                "cast": [],
                "crew": [],
            },
        )
        metadata.start()
        self.addCleanup(metadata.stop)
        with disable_fetch_releases():
            series_item = Item.objects.create(
                media_id="1399",
                source=Sources.TMDB.value,
                media_type=MediaTypes.TV.value,
                provider_external_ids={"imdb_id": "tt900"},
                title="Episode Series",
                image="",
            )
            self.tv = TV.objects.create(
                item=series_item,
                user=self.user,
                status=Status.PLANNING.value,
            )
            season_item = Item.objects.create(
                media_id="1399",
                source=Sources.TMDB.value,
                media_type=MediaTypes.SEASON.value,
                season_number=1,
                title="Episode Series",
                image="",
            )
            self.season = Season.objects.create(
                item=season_item,
                related_tv=self.tv,
                user=self.user,
                status=Status.PLANNING.value,
            )
            self.episode_item = Item.objects.create(
                media_id="1399",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                season_number=1,
                episode_number=2,
                title="An Episode",
                image="",
            )
            # Seed the row `_append_play` uses to reach the season: without it
            # the episode item has no related season to watch into. It is
            # fixture plumbing, so `_plays` counts it out.
            Episode.objects.bulk_create(
                [
                    Episode(
                        item=self.episode_item,
                        related_season=self.season,
                        end_date=None,
                    ),
                ],
            )
            self.seeded_plays = Episode.objects.filter(
                item=self.episode_item,
            ).count()

    def _plays(self):
        """Count the plays appended for the episode, ignoring the seeded row."""
        return (
            Episode.objects.filter(item=self.episode_item).count() - self.seeded_plays
        )

    def _result(self, **overrides):
        defaults = {
            "completed": True,
            "position_seconds": 590,
            "duration_seconds": 600,
            "record_play": True,
            "clear_progress": False,
        }
        defaults.update(overrides)
        return tracker.MergeResult(**defaults)

    def _persist(self, session_started_at):
        return tracker.persist_merge_result(
            self.user,
            self.episode_item,
            self._result(),
            media_id="1399",
            video_id="tt900:1:2",
            session_started_at=session_started_at,
            ended_at=session_started_at,
        )

    def test_episode_completion_appends_one_history_play(self):
        recorded = self._persist(timezone.now())

        self.assertTrue(recorded)
        self.assertEqual(self._plays(), 1)

    def test_replaying_the_same_episode_session_does_not_append_twice(self):
        """The episode append dedups on the external id, as the movie branch does.

        The app-level pre-check in the watch call is the first line of defence;
        the unique constraint is the backstop.
        """
        started = timezone.now()
        for _ in range(2):
            self._persist(started)

        self.assertEqual(self._plays(), 1)

    def test_a_second_episode_session_appends_a_second_play(self):
        first = timezone.now()
        # Beyond the shared dedupe window, so this is genuinely a second
        # viewing rather than the same one re-reported.
        second = first + timedelta(hours=4)
        for started in (first, second):
            self._persist(started)

        self.assertEqual(self._plays(), 2)
