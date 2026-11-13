from datetime import timedelta

from django.test import SimpleTestCase
from django.utils import timezone

from integrations import stremio_playback


class PollObservationTests(SimpleTestCase):
    """The poller's producer: the seam that surfaces resume position."""

    def _entry(self, **state):
        defaults = {
            "timeOffset": 600000,
            "duration": 2700000,
            "timeWatched": 600000,
            "flaggedWatched": 0,
        }
        defaults.update(state)
        return {"state": defaults}

    def test_position_is_converted_from_milliseconds(self):
        observation = stremio_playback.poll_observation_from_state(
            "movie",
            self._entry(),
        )

        self.assertEqual(observation.position_seconds, 600)
        self.assertEqual(observation.duration_seconds, 2700)

    def test_resume_position_is_surfaced_not_dropped(self):
        """`timeOffset` used to be discarded by normalize_state entirely."""
        observation = stremio_playback.poll_observation_from_state(
            "movie",
            self._entry(timeOffset=120000, duration=3600000),
        )

        self.assertEqual(observation.position_seconds, 120)

    def test_observed_at_is_our_clock_not_stremios(self):
        """Ordering is about when WE observed, not when the user watched."""
        before = timezone.now()
        observation = stremio_playback.poll_observation_from_state(
            "movie",
            self._entry(
                lastWatched=(timezone.now() - timedelta(hours=2)).isoformat(),
            ),
        )
        after = timezone.now()

        self.assertGreaterEqual(observation.observed_at, before)
        self.assertLessEqual(observation.observed_at, after)

    def test_flagged_watched_becomes_watched_state(self):
        observation = stremio_playback.poll_observation_from_state(
            "movie",
            self._entry(flaggedWatched=1),
        )

        self.assertTrue(observation.watched)

    def test_unflagged_is_explicitly_false_not_none(self):
        """An explicit zero is Stremio asserting the media is not watched."""
        observation = stremio_playback.poll_observation_from_state(
            "movie",
            self._entry(flaggedWatched=0),
        )

        self.assertFalse(observation.watched)

    def test_absent_flag_is_none_not_false(self):
        """A missing key asserts nothing; False would clear a completed session."""
        observation = stremio_playback.poll_observation_from_state(
            "movie",
            {"state": {"timeOffset": 600000, "duration": 2700000}},
        )

        self.assertIsNone(observation.watched)

    def test_times_watched_alone_reads_as_watched(self):
        """A naturally-completed item carries timesWatched and no manual flag.

        Reading flaggedWatched alone would assert False here and clear the
        completed session.
        """
        observation = stremio_playback.poll_observation_from_state(
            "movie",
            {"state": {"duration": 600000, "timeWatched": 600000, "timesWatched": 1}},
        )

        self.assertTrue(observation.watched)

    def test_zero_manual_flag_does_not_override_a_completed_count(self):
        observation = stremio_playback.poll_observation_from_state(
            "movie",
            {"state": {"duration": 600000, "timesWatched": 1, "flaggedWatched": 0}},
        )

        self.assertTrue(observation.watched)

    def test_both_fields_zero_asserts_not_watched(self):
        observation = stremio_playback.poll_observation_from_state(
            "movie",
            {"state": {"duration": 600000, "timesWatched": 0, "flaggedWatched": 0}},
        )

        self.assertFalse(observation.watched)

    def test_an_unparseable_flag_asserts_nothing(self):
        """An unusable value is absent, never False — False clears state."""
        observation = stremio_playback.poll_observation_from_state(
            "movie",
            {"state": {"duration": 600000, "flaggedWatched": "junk"}},
        )

        self.assertIsNone(observation.watched)

    def test_series_entry_carries_the_video_id(self):
        observation = stremio_playback.poll_observation_from_state(
            "series",
            self._entry(video_id="tt2:1:2"),
        )

        self.assertEqual(observation.video_id, "tt2:1:2")

    def test_movie_entry_carries_no_video_id(self):
        observation = stremio_playback.poll_observation_from_state(
            "movie",
            self._entry(video_id="tt1:1:1"),
        )

        self.assertIsNone(observation.video_id)

    def test_action_marks_it_as_a_poll_observation(self):
        observation = stremio_playback.poll_observation_from_state(
            "movie",
            self._entry(),
        )

        self.assertEqual(observation.action, "observed")

    def test_zero_duration_does_not_discard_the_observation(self):
        """29 live entries carry a resume offset with no duration.

        Discarding them lost the position entirely; `persist_merge_result`
        preserves a stored duration when the observation carries none, so the
        observation is still worth emitting.
        """
        observation = stremio_playback.poll_observation_from_state(
            "movie",
            self._entry(timeOffset=2550872, duration=0),
        )

        self.assertIsNone(observation.duration_seconds)
        self.assertEqual(observation.position_seconds, 2550)

    def test_zero_offset_is_absent_not_a_resume_at_zero(self):
        """Storing 0 would overwrite a real position with the start of the film."""
        observation = stremio_playback.poll_observation_from_state(
            "movie",
            self._entry(timeOffset=0),
        )

        self.assertIsNone(observation.position_seconds)

    def test_missing_state_is_none(self):
        self.assertIsNone(
            stremio_playback.poll_observation_from_state("movie", {}),
        )

    def test_malformed_entry_is_none(self):
        self.assertIsNone(
            stremio_playback.poll_observation_from_state("movie", "not-an-entry"),
        )
