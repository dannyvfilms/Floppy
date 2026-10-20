"""Regressions for pointless metadata backfill retries and their log noise.

Production evidence (2026-10-14, one install, about 46 hours): 4,240
``metadata_backfill_retry_later`` lines for episode runtimes, all from
providers that had answered with no runtime, and 163 season release lookups
that ran every day at ``fail_count=31`` and learned nothing.
"""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from app import tasks_episode, tasks_runtime
from app.models import (
    Item,
    MediaTypes,
    MetadataBackfillField,
    MetadataBackfillState,
    Sources,
)
from app.tasks_backfill_state import (
    METADATA_BACKFILL_EMPTY_ANSWER_DELAY_SECONDS,
    METADATA_BACKFILL_PENDING_MAX_DELAY_SECONDS,
    _record_backfill_failure,
    _record_backfill_pending,
)

DAY = 60 * 60 * 24
LOGGER = "app.tasks_backfill_state"


def _season():
    return Item.objects.create(
        media_id="1668",
        source=Sources.TMDB.value,
        media_type=MediaTypes.SEASON.value,
        title="Season",
        season_number=7,
    )


def _episode(number=1):
    return Item.objects.create(
        media_id="1668",
        source=Sources.TMDB.value,
        media_type=MediaTypes.EPISODE.value,
        title=f"Episode {number}",
        season_number=7,
        episode_number=number,
    )


def _delay_seconds(item, field):
    state = MetadataBackfillState.objects.get(item=item, field=field)
    return (state.next_retry_at - state.last_attempt_at).total_seconds()


class PendingBackoffTests(TestCase):
    def test_pending_backoff_grows_past_one_day_and_stops_at_two_weeks(self):
        """A season with no air date is not asked about every day forever."""
        item = _season()
        field = MetadataBackfillField.RELEASE.value
        delays = []
        for _ in range(40):
            _record_backfill_pending(item, field, "provider has no release date")
            delays.append(_delay_seconds(item, field))

        self.assertEqual(delays[0], 60 * 60)
        self.assertEqual(delays[4], 16 * 60 * 60)
        self.assertGreater(delays[5], DAY)
        self.assertEqual(max(delays), METADATA_BACKFILL_PENDING_MAX_DELAY_SECONDS)
        self.assertEqual(delays[-1], 14 * DAY)
        self.assertEqual(delays, sorted(delays))

    def test_pending_never_gives_up(self):
        item = _season()
        field = MetadataBackfillField.RELEASE.value
        for _ in range(40):
            _record_backfill_pending(item, field, "provider has no release date")

        state = MetadataBackfillState.objects.get(item=item, field=field)
        self.assertFalse(state.give_up)
        self.assertEqual(state.fail_count, 40)

    def test_a_larger_floor_still_wins(self):
        item = _season()
        field = MetadataBackfillField.TVDB_MIGRATION.value
        _record_backfill_pending(item, field, "x", min_delay_seconds=30 * DAY)

        self.assertEqual(_delay_seconds(item, field), 30 * DAY)

    def test_an_absurd_fail_count_does_not_build_a_huge_integer(self):
        item = _season()
        field = MetadataBackfillField.RELEASE.value
        MetadataBackfillState.objects.create(item=item, field=field, fail_count=9998)

        _record_backfill_pending(item, field, "provider has no release date")

        self.assertEqual(
            _delay_seconds(item, field),
            METADATA_BACKFILL_PENDING_MAX_DELAY_SECONDS,
        )


class FailureFloorTests(TestCase):
    def test_failure_ladder_is_unchanged_without_a_floor(self):
        item = _episode()
        field = MetadataBackfillField.RUNTIME
        _record_backfill_failure(item, field, "exception: boom")

        self.assertEqual(_delay_seconds(item, field), 60 * 60)

    def test_floor_defers_the_first_retry(self):
        item = _episode()
        field = MetadataBackfillField.RUNTIME
        _record_backfill_failure(
            item,
            field,
            "no runtime",
            min_delay_seconds=METADATA_BACKFILL_EMPTY_ANSWER_DELAY_SECONDS,
        )

        self.assertEqual(_delay_seconds(item, field), DAY)

    def test_floor_still_ends_in_give_up(self):
        item = _episode()
        field = MetadataBackfillField.RUNTIME
        gave_up = [
            _record_backfill_failure(item, field, "no runtime", min_delay_seconds=DAY)
            for _ in range(6)
        ]

        self.assertEqual(gave_up, [False] * 5 + [True])


class LogNoiseTests(TestCase):
    def test_retry_later_and_pending_are_not_info_lines(self):
        item = _episode()
        with self.assertNoLogs(LOGGER, "INFO"):
            _record_backfill_failure(item, MetadataBackfillField.RUNTIME, "no runtime")
            _record_backfill_pending(item, MetadataBackfillField.RELEASE.value, "x")

    def test_retry_later_is_still_available_at_debug(self):
        item = _episode()
        with self.assertLogs(LOGGER, "DEBUG") as logs:
            _record_backfill_failure(item, MetadataBackfillField.RUNTIME, "no runtime")

        self.assertIn("metadata_backfill_retry_later", logs.output[0])

    def test_giving_up_is_still_a_warning(self):
        item = _episode()
        with self.assertLogs(LOGGER, "WARNING") as logs:
            _record_backfill_failure(
                item, MetadataBackfillField.RUNTIME, "x", terminal=True
            )

        self.assertIn("metadata_backfill_give_up", logs.output[0])


class EmptyAnswerCallSiteTests(TestCase):
    def _assert_deferred_a_day(self, item):
        state = MetadataBackfillState.objects.get(
            item=item, field=MetadataBackfillField.RUNTIME
        )
        self.assertGreaterEqual(
            state.next_retry_at - state.last_attempt_at, timedelta(days=1)
        )

    def test_movie_style_runtime_with_none_from_provider_waits_a_day(self):
        item = Item.objects.create(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Movie",
        )
        with patch.object(
            tasks_runtime.services,
            "get_media_metadata",
            return_value={"details": {"runtime": None}},
        ):
            tasks_runtime._populate_runtime_for_items([item], 0)

        self._assert_deferred_a_day(item)

    def test_runtime_exception_still_uses_the_short_ladder(self):
        item = Item.objects.create(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Movie",
        )
        with patch.object(
            tasks_runtime.services,
            "get_media_metadata",
            side_effect=RuntimeError("provider down"),
        ):
            tasks_runtime._populate_runtime_for_items([item], 0)

        state = MetadataBackfillState.objects.get(
            item=item, field=MetadataBackfillField.RUNTIME
        )
        self.assertLess(state.next_retry_at - state.last_attempt_at, timedelta(hours=2))

    def test_episode_with_no_runtime_in_season_payload_waits_a_day(self):
        episode = _episode(1)
        season_payload = {"season/7": {"episodes": []}}
        with (
            patch(
                "app.providers.services.get_media_metadata",
                return_value=season_payload,
            ),
            patch(
                "app.providers.tmdb.process_episodes",
                return_value=[{"episode_number": 1, "runtime": None}],
            ),
            patch("time.sleep"),
        ):
            tasks_episode.populate_episode_runtime_data(["1668|tmdb|7"])

        self._assert_deferred_a_day(episode)
