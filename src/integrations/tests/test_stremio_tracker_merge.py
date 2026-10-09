from datetime import timedelta

from django.test import SimpleTestCase
from django.utils import timezone

from integrations import stremio_tracker as tracker


class MergePolicyTests(SimpleTestCase):
    def setUp(self):
        self.now = timezone.now()
        self.session = tracker.new_session(video_id="tt1:1:2", started_at=self.now)

    def _obs(self, **overrides):
        defaults = {
            "action": "start",
            "position_seconds": None,
            "duration_seconds": None,
            "watched": None,
            "observed_at": self.now,
            "video_id": "tt1:1:2",
        }
        defaults.update(overrides)
        return tracker.Observation(**defaults)

    def test_a_poll_completion_does_not_record_a_play(self):
        """A poll reports the item's state, not evidence of a viewing.

        A replay of an already-watched title still reads `timesWatched=1`, so
        recording a play here would complete the replay the moment it started —
        the stale-snapshot case the verifier's baseline evidence rejects. The
        progress row still reflects the library's flag.
        """
        result = tracker.apply_observation(
            self.session,
            self._obs(watched=True, records_play=False),
        )

        self.assertTrue(result.completed)
        self.assertFalse(result.record_play)

    def test_a_poll_leaves_the_play_for_a_source_that_can_prove_one(self):
        """A poll must not consume the session's one play.

        `records_play=False` has to skip `play_recorded` as well as the append,
        or the player stop that follows a poll would find the play already spent
        and append nothing.
        """
        tracker.apply_observation(
            self.session,
            self._obs(watched=True, records_play=False),
        )

        result = tracker.apply_observation(
            self.session,
            self._obs(action="stop", watched=True),
        )

        self.assertTrue(result.record_play)

    def test_a_poll_does_not_arm_a_play_for_an_unproven_replay(self):
        """The sticky `completed` flag is not itself evidence of a viewing.

        Replaying an already-watched movie: the poll reads `timesWatched=1` and
        marks the session completed. The next event is a `pause` of that replay
        with no completion evidence of its own, so nothing may be appended —
        gating the append on `session["completed"]` filed a history play for a
        replay the user abandoned.
        """
        tracker.apply_observation(
            self.session,
            self._obs(action="observed", watched=True, records_play=False),
        )

        result = tracker.apply_observation(
            self.session,
            self._obs(action="pause", position_seconds=60, duration_seconds=6000),
        )

        self.assertTrue(result.completed)
        self.assertFalse(result.record_play)

    def test_playback_start_does_not_record_a_play(self):
        result = tracker.apply_observation(self.session, self._obs())

        self.assertFalse(result.record_play)
        self.assertFalse(result.completed)

    def test_stop_at_seventy_five_percent_completes(self):
        """Stremio flags watched at 70%; a stop at 75% is a real completion.

        is_played() would require the final 30 seconds, so wiring completion to
        it would drop the common 'skipped the credits' case.
        """
        result = tracker.apply_observation(
            self.session,
            self._obs(
                action="stop",
                position_seconds=4500,
                duration_seconds=6000,
                watched=True,
            ),
        )

        self.assertTrue(result.completed)
        self.assertTrue(result.record_play)

    def test_position_is_monotonic_within_a_session(self):
        """A lagging report must not rewind progress."""
        tracker.apply_observation(
            self.session,
            self._obs(action="pause", position_seconds=3000, duration_seconds=6000),
        )
        result = tracker.apply_observation(
            self.session,
            self._obs(action="pause", position_seconds=1000, duration_seconds=6000),
        )

        self.assertEqual(result.position_seconds, 3000)

    def test_late_poll_does_not_rewind_position(self):
        """The 90s push throttle means a poll can carry a stale position.

        The poll's position is HIGHER than the session's, so this only passes if
        the staleness guard actually rejects it — max() alone would return 5000.
        """
        tracker.apply_observation(
            self.session,
            self._obs(action="pause", position_seconds=3000, duration_seconds=6000),
        )
        result = tracker.apply_observation(
            self.session,
            self._obs(
                action="observed",
                position_seconds=5000,
                duration_seconds=6000,
                observed_at=self.now - timedelta(seconds=300),
            ),
        )

        self.assertEqual(result.position_seconds, 3000)

    def test_stale_stop_does_not_settle(self):
        """A stale stop must not close the session: a rewatch would not start."""
        tracker.apply_observation(
            self.session,
            self._obs(action="pause", position_seconds=1000, duration_seconds=6000),
        )
        tracker.apply_observation(
            self.session,
            self._obs(
                action="stop",
                position_seconds=2000,
                duration_seconds=6000,
                observed_at=self.now - timedelta(seconds=300),
            ),
        )

        self.assertFalse(self.session["settled"])

    def test_stale_poll_may_set_watched_but_not_position(self):
        """Rule 1's asymmetry: the flag owns watched-ness; it does not own position."""
        result = tracker.apply_observation(
            self.session,
            self._obs(
                action="observed",
                position_seconds=5000,
                duration_seconds=6000,
                watched=True,
                observed_at=self.now - timedelta(seconds=300),
            ),
        )

        self.assertTrue(result.completed)
        self.assertIsNone(result.position_seconds)

    def test_observation_inside_the_skew_tolerance_is_not_stale(self):
        """A retry arriving just before last_event_at is skew, not disorder."""
        tracker.apply_observation(
            self.session,
            self._obs(action="pause", position_seconds=1000, duration_seconds=6000),
        )
        result = tracker.apply_observation(
            self.session,
            self._obs(
                action="pause",
                position_seconds=2000,
                duration_seconds=6000,
                observed_at=self.now - timedelta(seconds=60),
            ),
        )

        self.assertEqual(result.position_seconds, 2000)

    def test_stale_pause_after_completion_keeps_it(self):
        """Rule 4 holds against a stale, non-asserting in-progress observation."""
        tracker.apply_observation(
            self.session,
            self._obs(
                action="stop",
                position_seconds=4500,
                duration_seconds=6000,
                watched=True,
            ),
        )
        result = tracker.apply_observation(
            self.session,
            self._obs(
                action="pause",
                position_seconds=100,
                duration_seconds=6000,
                watched=None,
                observed_at=self.now - timedelta(seconds=300),
            ),
        )

        self.assertTrue(result.completed)

    def test_completion_is_sticky_against_in_progress_observations(self):
        tracker.apply_observation(
            self.session,
            self._obs(
                action="stop",
                position_seconds=4500,
                duration_seconds=6000,
                watched=True,
            ),
        )
        result = tracker.apply_observation(
            self.session,
            self._obs(action="pause", position_seconds=100, duration_seconds=6000),
        )

        self.assertTrue(result.completed)

    def test_play_is_recorded_once_per_session(self):
        first = tracker.apply_observation(
            self.session,
            self._obs(
                action="stop",
                position_seconds=4500,
                duration_seconds=6000,
                watched=True,
            ),
        )
        second = tracker.apply_observation(
            self.session,
            self._obs(
                action="stop",
                position_seconds=4500,
                duration_seconds=6000,
                watched=True,
            ),
        )

        self.assertTrue(first.record_play)
        self.assertFalse(second.record_play)

    def test_rewatch_after_settling_starts_a_new_session(self):
        """Without a reset, monotonic position pins a rewatch near the end."""
        tracker.apply_observation(
            self.session,
            self._obs(
                action="stop",
                position_seconds=5900,
                duration_seconds=6000,
                watched=True,
            ),
        )
        fresh = tracker.new_session(
            video_id="tt1:1:2",
            started_at=self.now + timedelta(hours=1),
        )
        result = tracker.apply_observation(
            fresh,
            self._obs(
                action="pause",
                position_seconds=600,
                duration_seconds=6000,
                observed_at=self.now + timedelta(hours=1),
            ),
        )

        self.assertEqual(result.position_seconds, 600)
        self.assertFalse(result.completed)

    def test_unwatch_clears_state_without_recording_a_play(self):
        result = tracker.apply_observation(
            self.session,
            self._obs(action="unwatched", watched=False),
        )

        self.assertFalse(result.completed)
        self.assertFalse(result.record_play)
        self.assertTrue(result.clear_progress)

    def test_library_remove_clears_progress_only(self):
        result = tracker.apply_observation(
            self.session,
            self._obs(action="libraryRemove"),
        )

        self.assertTrue(result.clear_progress)
        self.assertFalse(result.record_play)

    def test_poll_may_set_watched_state_without_position(self):
        """The flag is authoritative for watched-ness even on a stale poll."""
        result = tracker.apply_observation(
            self.session,
            self._obs(action="observed", watched=True),
        )

        self.assertTrue(result.completed)
        self.assertTrue(result.record_play)

    def test_flag_bearing_not_watched_clears_completion(self):
        """The three-state contract: an explicit False assertion clears.

        Stremio's flag is time_watched-based, so it can legitimately disagree
        with a position-based provisional completion. The flag wins.
        """
        tracker.apply_observation(
            self.session,
            self._obs(
                action="stop",
                position_seconds=4500,
                duration_seconds=6000,
                watched=True,
            ),
        )
        result = tracker.apply_observation(
            self.session,
            self._obs(action="observed", watched=False),
        )

        self.assertFalse(result.completed)

    def _settle(self, session=None):
        session = self.session if session is None else session
        tracker.apply_observation(
            session,
            self._obs(
                action="stop",
                position_seconds=4500,
                duration_seconds=6000,
                watched=True,
            ),
        )
        return session

    def test_no_session_starts_one(self):
        session = tracker.session_for_observation(None, self._obs())

        self.assertEqual(session["video_id"], "tt1:1:2")

    def test_start_after_settling_starts_a_new_session(self):
        self._settle()
        session = tracker.session_for_observation(self.session, self._obs())

        self.assertIsNot(session, self.session)
        self.assertFalse(session["completed"])
        self.assertFalse(session["play_recorded"])

    def test_changed_video_id_starts_a_new_session(self):
        session = tracker.session_for_observation(
            self.session,
            self._obs(video_id="tt1:1:3"),
        )

        self.assertIsNot(session, self.session)
        self.assertEqual(session["video_id"], "tt1:1:3")

    def test_reset_from_a_none_video_id_observation_keeps_the_session_video_id(self):
        tracker.apply_observation(
            self.session,
            self._obs(
                action="stop",
                position_seconds=4500,
                duration_seconds=6000,
                watched=True,
            ),
        )
        fresh = tracker.session_for_observation(
            self.session,
            self._obs(action="start", video_id=None),
        )

        self.assertEqual(fresh["video_id"], "tt1:1:2")

    def test_same_video_keeps_the_session(self):
        session = tracker.session_for_observation(self.session, self._obs())

        self.assertIs(session, self.session)

    def test_settled_session_past_the_grace_window_starts_a_new_session(self):
        self._settle()
        session = tracker.session_for_observation(
            self.session,
            self._obs(
                action="pause",
                position_seconds=100,
                duration_seconds=6000,
                observed_at=self.now
                + timedelta(seconds=tracker.SESSION_GRACE_SECONDS + 1),
            ),
        )

        self.assertIsNot(session, self.session)

    def test_settled_session_inside_the_grace_window_keeps_the_session(self):
        self._settle()
        session = tracker.session_for_observation(
            self.session,
            self._obs(
                action="pause",
                position_seconds=100,
                duration_seconds=6000,
                observed_at=self.now
                + timedelta(seconds=tracker.SESSION_GRACE_SECONDS - 1),
            ),
        )

        self.assertIs(session, self.session)

    def test_rewatch_after_settling_appends_a_second_play(self):
        """The user-visible requirement: a rewatch counts as a second play."""
        first = tracker.apply_observation(
            self.session,
            self._obs(
                action="stop",
                position_seconds=4500,
                duration_seconds=6000,
                watched=True,
            ),
        )
        session = tracker.session_for_observation(
            self.session,
            self._obs(action="start", observed_at=self.now + timedelta(hours=1)),
        )
        second = tracker.apply_observation(
            session,
            self._obs(
                action="stop",
                position_seconds=4500,
                duration_seconds=6000,
                watched=True,
                observed_at=self.now + timedelta(hours=1),
            ),
        )

        self.assertTrue(first.record_play)
        self.assertTrue(second.record_play)
