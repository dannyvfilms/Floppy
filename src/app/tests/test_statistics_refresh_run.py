"""Coverage for the resumable, bounded Statistics refresh run.

The old refresh was one Celery task body that owned the single-slot
interactive worker for a whole rebuild. These tests pin the two things that
replacement has to get right: the published result must be exactly what the
single-shot rebuild produced, and the run must stay correct when it is
interrupted, superseded, duplicated, forced, or left for dead halfway.
"""

from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from app import statistics_cache, statistics_refresh, statistics_refresh_run
from app.models import Item, MediaTypes, Movie, Sources, Status
from app.statistics_aggregator import _aggregate_statistics_from_days
from app.statistics_day_builder import _build_prefetch_for_range, build_stats_for_day
from app.statistics_day_cache import (
    STATISTICS_DAY_CACHE_TIMEOUT,
    _day_cache_key,
    _get_history_version,
    _set_history_version,
)

EQUIVALENCE_RANGES = (
    "Today",
    "Last 7 Days",
    "This Month",
    "Last 90 Days",
    "All Time",
)


def _single_shot_reference(user, range_name):
    """Rebuild a range the way the pre-run implementation did.

    One range-wide prefetch, every day built back to back in one pass, one
    aggregate over the whole day list. Nothing here is chunked, resumable or
    version-checked -- that is the point: it is the reference the chunked run
    has to reproduce exactly.
    """
    start_date, end_date = statistics_refresh._get_predefined_range_dates(range_name)
    day_list = statistics_refresh._resolve_day_list(user, start_date, end_date)
    sorted_days = [day for day in sorted(set(day_list)) if day]

    prefetch = _build_prefetch_for_range(user, sorted_days)
    history_version = _get_history_version(user.id)
    credit_backfill_hints = 0
    pending = {}
    for day in sorted_days:
        day_stats = build_stats_for_day(
            user.id,
            day,
            user=user,
            prefetch=prefetch,
            history_version=history_version,
            defer_cache_write=True,
        )
        if day_stats:
            pending[_day_cache_key(user.id, day)] = day_stats
            credit_backfill_hints += int(
                day_stats.get("backfill", {}).get("missing_credits") or 0
            )
    if pending:
        cache.set_many(pending, timeout=STATISTICS_DAY_CACHE_TIMEOUT)

    return _aggregate_statistics_from_days(
        user,
        day_list,
        start_date,
        end_date,
        build_missing=True,
        credit_backfill_hints=credit_backfill_hints,
    )


_HIGHLIGHT_CARD_FIELDS = {"entry", "item", "media_type", "title", "image", "played_at"}


def _strip_highlight_blobs(value):
    """Remove the raw History payload embedded in each highlight card.

    A highlight card carries the History day entry it was chosen from, and that
    entry's *shape* depends on whether the History day cache happened to be warm
    when the aggregate ran: a cached day deserializes with ``album``/``show``
    keys that a freshly built day does not carry. That is pre-existing History
    behaviour -- two back-to-back single-shot rebuilds disagree about it too --
    and it says nothing about which day the card selected. Compare the fields
    the Statistics page actually renders instead.
    """
    if isinstance(value, list):
        return [_strip_highlight_blobs(item) for item in value]
    if not isinstance(value, dict):
        return value
    if _HIGHLIGHT_CARD_FIELDS.issubset(value.keys()):
        return {
            key: _strip_highlight_blobs(item)
            for key, item in value.items()
            if key not in {"entry", "item"}
        }
    return {key: _strip_highlight_blobs(item) for key, item in value.items()}


def _comparable(data):
    """Drop the fields that legitimately differ between two rebuilds."""
    if not isinstance(data, dict):
        return data
    stripped = dict(data)
    stripped.pop("computed_at", None)
    stripped.pop("built_at", None)
    stripped["history_highlights"] = _strip_highlight_blobs(
        stripped.get("history_highlights")
    )
    stripped["history_highlights_by_type"] = _strip_highlight_blobs(
        stripped.get("history_highlights_by_type")
    )
    return stripped


class StatisticsRunTestCase(TestCase):
    """A small multi-day, multi-media library to rebuild."""

    day_offsets = (0, 1, 2, 5, 9, 20, 45, 200)

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username=f"stats-run-{self.id()}",
            password="secret123",
        )
        self.days = []
        for index, offset in enumerate(self.day_offsets):
            item = Item.objects.create(
                media_id=f"stats-run-{self.id()}-{offset}",
                source=Sources.MANUAL.value,
                media_type=MediaTypes.MOVIE.value,
                title=f"Statistics run movie {offset}",
                runtime_minutes=90 + index,
            )
            watched_at = timezone.now() - timedelta(days=offset)
            Movie.objects.create(
                user=self.user,
                item=item,
                status=Status.COMPLETED.value,
                end_date=watched_at,
                score=6 + (index % 4),
            )
            self.days.append(timezone.localtime(watched_at).date())

    def tearDown(self):
        cache.clear()

    def _clear_day_caches(self):
        cache.delete_many([_day_cache_key(self.user.id, day) for day in self.days])


class StatisticsRefreshEquivalenceTests(StatisticsRunTestCase):
    def test_chunked_run_matches_the_single_shot_rebuild(self):
        for range_name in EQUIVALENCE_RANGES:
            with self.subTest(range_name=range_name):
                cache.clear()
                expected = _single_shot_reference(self.user, range_name)

                cache.clear()
                actual = statistics_refresh.refresh_statistics_cache(
                    self.user.id, range_name, chunk_size=2
                )

                self.assertIsNotNone(actual)
                self.assertEqual(_comparable(actual), _comparable(expected))

    def test_chunk_size_cannot_change_the_result(self):
        for range_name in EQUIVALENCE_RANGES:
            results = []
            for chunk_size in (1, 3, 10_000):
                cache.clear()
                results.append(
                    _comparable(
                        statistics_refresh.refresh_statistics_cache(
                            self.user.id, range_name, chunk_size=chunk_size
                        )
                    )
                )
            with self.subTest(range_name=range_name):
                self.assertEqual(results[0], results[1])
                self.assertEqual(results[0], results[2])

    def test_finished_run_publishes_the_range_cache(self):
        statistics_refresh.refresh_statistics_cache(
            self.user.id, "All Time", chunk_size=2
        )

        entry = cache.get(statistics_cache._cache_key(self.user.id, "All Time"))
        self.assertIsNotNone(entry)
        self.assertEqual(
            entry.get("history_version"), _get_history_version(self.user.id)
        )
        self.assertFalse(
            statistics_cache.is_statistics_cache_stale(entry, self.user.id)
        )

    def test_run_releases_its_lock_and_scratch_state(self):
        statistics_refresh.refresh_statistics_cache(
            self.user.id, "All Time", chunk_size=2
        )

        self.assertIsNone(
            cache.get(statistics_cache._refresh_lock_key(self.user.id, "All Time"))
        )
        self.assertIsNone(statistics_refresh_run.load_run(self.user.id, "All Time"))


class StatisticsRefreshChunkYieldingTests(StatisticsRunTestCase):
    def test_start_plans_the_run_and_queues_exactly_one_continuation(self):
        with patch(
            "app.tasks_interactive.continue_statistics_refresh_task.apply_async"
        ) as apply_async:
            started = statistics_refresh_run.start_chunked_run(self.user.id, "All Time")

        self.assertTrue(started)
        apply_async.assert_called_once()
        run = statistics_refresh_run.load_run(self.user.id, "All Time")
        self.assertIsNotNone(run)
        self.assertEqual(run["cursor"], 0)
        self.assertEqual(run["state"], statistics_refresh_run.RUN_STATE_BUILDING)
        self.assertEqual(
            apply_async.call_args.kwargs["args"],
            [self.user.id, "All Time", run["run_id"]],
        )

    @override_settings(STATISTICS_REFRESH_CHUNK_DAYS=2)
    def test_each_chunk_queues_one_continuation_instead_of_looping(self):
        with patch(
            "app.tasks_interactive.continue_statistics_refresh_task.apply_async"
        ) as apply_async:
            # No explicit chunk_size: the run must take its bound from the
            # setting, which is what a Docker session will tune.
            statistics_refresh_run.begin_run(self.user.id, "All Time")
            run = statistics_refresh_run.load_run(self.user.id, "All Time")
            self.assertEqual(run["chunk_size"], 2)
            total_days = run["total_days"]
            self.assertGreater(total_days, 2)

            statistics_refresh_run.advance_chunked_run(
                self.user.id, "All Time", run["run_id"]
            )

            self.assertEqual(apply_async.call_count, 1)
            advanced = statistics_refresh_run.load_run(self.user.id, "All Time")
            self.assertEqual(advanced["cursor"], 2)
            self.assertEqual(advanced["chunk_index"], 1)
            # The range cache must not exist yet: a half-built run may not
            # masquerade as a finished one.
            self.assertIsNone(
                cache.get(statistics_cache._cache_key(self.user.id, "All Time"))
            )

    def test_continuations_are_outranked_by_interactive_work(self):
        continuation_priority = settings.CELERY_TASK_PRIORITY_STATISTICS_CONTINUATION
        # Redis priorities are inverted: lower number drains first. A webhook at
        # CELERY_TASK_PRIORITY_INTERACTIVE must beat a queued continuation.
        self.assertGreater(
            continuation_priority, settings.CELERY_TASK_PRIORITY_INTERACTIVE
        )

        route = settings.CELERY_TASK_ROUTES[
            "app.tasks.continue_statistics_refresh_task"
        ]
        self.assertEqual(route["queue"], "interactive")
        self.assertEqual(route["priority"], continuation_priority)

        with patch(
            "app.tasks_interactive.continue_statistics_refresh_task.apply_async"
        ) as apply_async:
            statistics_refresh_run.start_chunked_run(self.user.id, "All Time")

        self.assertEqual(
            apply_async.call_args.kwargs["priority"], continuation_priority
        )
        # No countdown by default: an ETA message is held in the worker's only
        # prefetch slot, which would defeat the yielding this exists for.
        self.assertEqual(apply_async.call_args.kwargs["countdown"], 0)

    @override_settings(STATISTICS_REFRESH_CHUNK_DAYS=3)
    def test_a_run_walks_to_completion_one_chunk_per_message(self):
        statistics_refresh_run.begin_run(self.user.id, "All Time")
        run = statistics_refresh_run.load_run(self.user.id, "All Time")
        run_id = run["run_id"]

        steps = 0
        with patch(
            "app.tasks_interactive.continue_statistics_refresh_task.apply_async"
        ):
            while statistics_refresh_run.load_run(self.user.id, "All Time"):
                statistics_refresh_run.advance_chunked_run(
                    self.user.id, "All Time", run_id
                )
                steps += 1
                self.assertLess(steps, 50, "run did not terminate")

        expected_chunks = -(-run["total_days"] // 3)
        self.assertEqual(steps, expected_chunks + 1)  # chunks, then FINISH
        self.assertIsNotNone(
            cache.get(statistics_cache._cache_key(self.user.id, "All Time"))
        )


class StatisticsRefreshHistoryVersionTests(StatisticsRunTestCase):
    def test_finish_for_an_old_version_cannot_publish_or_clear(self):
        statistics_cache.invalidate_statistics_days(
            self.user.id, [self.days[0]], reason="test-setup"
        )
        dirty_before = statistics_cache._load_dirty_days(self.user.id)
        self.assertTrue(dirty_before)

        statistics_refresh_run.begin_run(self.user.id, "All Time", chunk_size=2)
        run = statistics_refresh_run.load_run(self.user.id, "All Time")
        run_id = run["run_id"]

        with patch(
            "app.tasks_interactive.continue_statistics_refresh_task.apply_async"
        ):
            statistics_refresh_run.advance_chunked_run(self.user.id, "All Time", run_id)

        # History moves to version B while the run is mid-flight.
        _set_history_version(self.user.id)

        with patch(
            "app.tasks_interactive.refresh_statistics_cache_task.apply_async"
        ) as restart:
            statistics_refresh_run.advance_chunked_run(self.user.id, "All Time", run_id)

        self.assertIsNone(
            cache.get(statistics_cache._cache_key(self.user.id, "All Time"))
        )
        self.assertEqual(statistics_cache._load_dirty_days(self.user.id), dirty_before)
        self.assertIsNone(statistics_refresh_run.load_run(self.user.id, "All Time"))
        restart.assert_called_once()

    def test_version_a_finish_cannot_overwrite_a_version_b_result(self):
        statistics_refresh_run.begin_run(self.user.id, "All Time", chunk_size=100)
        stale_run = statistics_refresh_run.load_run(self.user.id, "All Time")

        _set_history_version(self.user.id)
        newer = statistics_refresh.refresh_statistics_cache(self.user.id, "All Time")
        published = cache.get(statistics_cache._cache_key(self.user.id, "All Time"))
        self.assertIsNotNone(newer)

        # The obsolete run tries to finish after the newer result landed.
        stale_run["state"] = statistics_refresh_run.RUN_STATE_FINISHING
        result = statistics_refresh_run.finish_run(self.user.id, "All Time", stale_run)

        self.assertIsNone(result)
        self.assertEqual(
            cache.get(statistics_cache._cache_key(self.user.id, "All Time")),
            published,
        )


class StatisticsRefreshDuplicateAndForceTests(StatisticsRunTestCase):
    def test_two_normal_requests_do_not_create_two_runs(self):
        statistics_cache.invalidate_statistics_cache(self.user.id, "All Time")
        with patch(
            "app.tasks_interactive.continue_statistics_refresh_task.apply_async"
        ):
            first = statistics_refresh_run.start_chunked_run(self.user.id, "All Time")
            second = statistics_refresh_run.start_chunked_run(self.user.id, "All Time")

        self.assertTrue(first)
        self.assertFalse(second)

    def test_scheduling_is_refused_while_a_run_is_active(self):
        statistics_cache.invalidate_statistics_cache(self.user.id, "All Time")
        with patch(
            "app.tasks_interactive.continue_statistics_refresh_task.apply_async"
        ):
            statistics_refresh_run.start_chunked_run(self.user.id, "All Time")

        with patch(
            "app.tasks_interactive.refresh_statistics_cache_task.apply_async"
        ) as apply_async:
            scheduled = statistics_refresh.schedule_statistics_refresh(
                self.user.id, "All Time", allow_inline=False
            )

        self.assertFalse(scheduled)
        apply_async.assert_not_called()

    def test_forced_request_during_a_run_is_recorded_not_dropped(self):
        with patch(
            "app.tasks_interactive.continue_statistics_refresh_task.apply_async"
        ):
            statistics_refresh_run.start_chunked_run(self.user.id, "All Time")

        with patch("app.tasks_interactive.refresh_statistics_cache_task.apply_async"):
            statistics_refresh.schedule_statistics_refresh(
                self.user.id,
                "All Time",
                debounce_seconds=0,
                countdown=0,
                allow_inline=False,
            )

        self.assertIsNotNone(
            cache.get(statistics_refresh_run._rerun_key(self.user.id, "All Time"))
        )

    def test_a_forced_follow_up_starts_a_fresh_run_after_finish(self):
        run = statistics_refresh_run.begin_run(
            self.user.id, "All Time", chunk_size=10_000
        )
        statistics_refresh_run.request_rerun(self.user.id, "All Time", reason="forced")

        with (
            patch("app.tasks_interactive.continue_statistics_refresh_task.apply_async"),
            patch(
                "app.tasks_interactive.refresh_statistics_cache_task.apply_async"
            ) as restart,
        ):
            statistics_refresh_run.advance_chunked_run(
                self.user.id, "All Time", run["run_id"]
            )
            statistics_refresh_run.advance_chunked_run(
                self.user.id, "All Time", run["run_id"]
            )

        restart.assert_called_once()
        self.assertIsNone(
            cache.get(statistics_refresh_run._rerun_key(self.user.id, "All Time"))
        )

    def test_forced_request_also_bypasses_the_freshness_check(self):
        statistics_refresh.refresh_statistics_cache(self.user.id, "All Time")
        entry = cache.get(statistics_cache._cache_key(self.user.id, "All Time"))
        self.assertFalse(
            statistics_cache.is_statistics_cache_stale(entry, self.user.id)
        )

        with patch(
            "app.tasks_interactive.refresh_statistics_cache_task.apply_async"
        ) as apply_async:
            scheduled = statistics_refresh.schedule_statistics_refresh(
                self.user.id,
                "All Time",
                debounce_seconds=0,
                countdown=0,
                allow_inline=False,
            )

        self.assertTrue(scheduled)
        self.assertEqual(
            apply_async.call_args.kwargs["args"], [self.user.id, "All Time", True]
        )


class StatisticsRefreshFailureAndRecoveryTests(StatisticsRunTestCase):
    def _dirty_every_day(self):
        statistics_cache.invalidate_statistics_days(
            self.user.id, self.days, reason="test-setup"
        )
        return statistics_cache._load_dirty_days(self.user.id)

    def _failing_chunk(self, fail_on_index):
        real_run_chunk = statistics_refresh_run.run_chunk
        calls = {"count": 0}

        def flaky(user_id, range_name, run, user=None):
            if calls["count"] == fail_on_index:
                calls["count"] += 1
                msg = "chunk exploded"
                raise RuntimeError(msg)
            calls["count"] += 1
            return real_run_chunk(user_id, range_name, run, user=user)

        return flaky, calls

    def test_a_failed_chunk_keeps_the_cursor_and_the_dirty_days(self):
        for fail_on_index in (0, 1):
            with self.subTest(fail_on_index=fail_on_index):
                cache.clear()
                dirty_before = self._dirty_every_day()
                statistics_refresh_run.begin_run(self.user.id, "All Time", chunk_size=2)
                run = statistics_refresh_run.load_run(self.user.id, "All Time")
                run_id = run["run_id"]
                flaky, _calls = self._failing_chunk(fail_on_index)

                with (
                    patch(
                        "app.tasks_interactive.continue_statistics_refresh_task.apply_async"
                    ),
                    patch.object(statistics_refresh_run, "run_chunk", flaky),
                    self.assertRaises(RuntimeError),
                ):
                    for _ in range(fail_on_index + 1):
                        statistics_refresh_run.advance_chunked_run(
                            self.user.id, "All Time", run_id
                        )

                stalled = statistics_refresh_run.load_run(self.user.id, "All Time")
                self.assertIsNotNone(stalled, "the run must stay resumable")
                self.assertEqual(stalled["cursor"], fail_on_index * 2)
                self.assertIsNone(
                    cache.get(statistics_cache._cache_key(self.user.id, "All Time"))
                )
                self.assertEqual(
                    statistics_cache._load_dirty_days(self.user.id), dirty_before
                )

    def test_a_retried_chunk_resumes_and_finishes_correctly(self):
        dirty_before = self._dirty_every_day()
        self.assertTrue(dirty_before)
        expected = _comparable(_single_shot_reference(self.user, "All Time"))
        cache.clear()
        self._dirty_every_day()

        statistics_refresh_run.begin_run(self.user.id, "All Time", chunk_size=2)
        run_id = statistics_refresh_run.load_run(self.user.id, "All Time")["run_id"]
        flaky, calls = self._failing_chunk(1)

        with (
            patch("app.tasks_interactive.continue_statistics_refresh_task.apply_async"),
            patch.object(statistics_refresh_run, "run_chunk", flaky),
        ):
            statistics_refresh_run.advance_chunked_run(self.user.id, "All Time", run_id)
            with self.assertRaises(RuntimeError):
                statistics_refresh_run.advance_chunked_run(
                    self.user.id, "All Time", run_id
                )

        self.assertEqual(calls["count"], 2)

        with patch(
            "app.tasks_interactive.continue_statistics_refresh_task.apply_async"
        ):
            steps = 0
            while statistics_refresh_run.load_run(self.user.id, "All Time"):
                statistics_refresh_run.advance_chunked_run(
                    self.user.id, "All Time", run_id
                )
                steps += 1
                self.assertLess(steps, 50)

        entry = cache.get(statistics_cache._cache_key(self.user.id, "All Time"))
        self.assertIsNotNone(entry)
        self.assertEqual(_comparable(entry["data"]), expected)
        self.assertFalse(statistics_cache._load_dirty_days(self.user.id))

    def test_a_dead_run_is_recovered_rather_than_locking_forever(self):
        statistics_cache.invalidate_statistics_cache(self.user.id, "All Time")
        with patch(
            "app.tasks_interactive.continue_statistics_refresh_task.apply_async"
        ):
            statistics_refresh_run.start_chunked_run(self.user.id, "All Time")

        # The worker disappears: the lease stops being heartbeated and ages out.
        lock_key = statistics_cache._refresh_lock_key(self.user.id, "All Time")
        dead = cache.get(lock_key)
        dead["started_at"] = (
            timezone.now()
            - statistics_cache.STATISTICS_REFRESH_LOCK_MAX_AGE
            - timedelta(seconds=60)
        ).isoformat()
        cache.set(lock_key, dead, timeout=300)

        self.assertIsNone(statistics_refresh_run.load_run(self.user.id, "All Time"))

        with patch(
            "app.tasks_interactive.continue_statistics_refresh_task.apply_async"
        ) as apply_async:
            restarted = statistics_refresh_run.start_chunked_run(
                self.user.id, "All Time"
            )

        self.assertTrue(restarted)
        apply_async.assert_called_once()
        fresh = statistics_refresh_run.load_run(self.user.id, "All Time")
        self.assertNotEqual(fresh["run_id"], dead["run_id"])

    def test_a_continuation_for_an_obsolete_run_does_nothing(self):
        statistics_refresh_run.begin_run(self.user.id, "All Time", chunk_size=2)
        obsolete_run_id = "0" * 32

        with patch(
            "app.tasks_interactive.continue_statistics_refresh_task.apply_async"
        ) as apply_async:
            advanced = statistics_refresh_run.advance_chunked_run(
                self.user.id, "All Time", obsolete_run_id
            )

        self.assertFalse(advanced)
        apply_async.assert_not_called()
        self.assertEqual(
            statistics_refresh_run.load_run(self.user.id, "All Time")["cursor"], 0
        )


class StatisticsRefreshCacheWriteFailureTests(StatisticsRunTestCase):
    def test_days_whose_cache_write_failed_are_rebuilt_for_the_aggregate(self):
        expected = _comparable(_single_shot_reference(self.user, "All Time"))
        cache.clear()

        failed_day = self.days[0]
        failed_key = _day_cache_key(self.user.id, failed_day)
        original_set_many = cache.set_many

        def set_many_reporting_one_failure(values, timeout=None, version=None):
            original_set_many(
                {key: value for key, value in values.items() if key != failed_key},
                timeout=timeout,
                version=version,
            )
            return [failed_key] if failed_key in values else []

        with patch.object(
            statistics_refresh_run.cache,
            "set_many",
            side_effect=set_many_reporting_one_failure,
        ):
            result = statistics_refresh.refresh_statistics_cache(
                self.user.id, "All Time", chunk_size=2
            )

        self.assertIsNotNone(result)
        self.assertEqual(_comparable(result), expected)

    def test_a_reported_write_failure_is_retried_before_being_recorded(self):
        failed_key = _day_cache_key(self.user.id, self.days[0])
        original_set_many = cache.set_many
        attempts = {"count": 0}

        def flaky_set_many(values, timeout=None, version=None):
            original_set_many(values, timeout=timeout, version=version)
            if failed_key in values and attempts["count"] == 0:
                attempts["count"] += 1
                return [failed_key]
            return []

        run = {
            "run_id": "test",
            "failed_write_days": [],
            "failed_write_count": 0,
        }
        with patch.object(
            statistics_refresh_run.cache, "set_many", side_effect=flaky_set_many
        ):
            failures = statistics_refresh_run._flush_day_writes(
                self.user.id, "All Time", run, {failed_key: {"day": "x"}}
            )

        self.assertEqual(attempts["count"], 1)
        self.assertEqual(failures, 0)
        self.assertEqual(run["failed_write_count"], 0)

    def test_persistent_write_failures_are_recorded_as_identifiers_only(self):
        failed_key = _day_cache_key(self.user.id, self.days[0])
        run = {"run_id": "test", "failed_write_days": [], "failed_write_count": 0}

        with patch.object(
            statistics_refresh_run.cache, "set_many", return_value=[failed_key]
        ):
            failures = statistics_refresh_run._flush_day_writes(
                self.user.id,
                "All Time",
                run,
                {failed_key: {"day": "x", "items": {"movie": {"1": {}}}}},
            )

        self.assertEqual(failures, 1)
        self.assertEqual(run["failed_write_count"], 1)
        self.assertEqual(run["failed_write_days"], [self.days[0].isoformat()])


class StatisticsRefreshDirtyDayTests(StatisticsRunTestCase):
    def test_a_completed_run_clears_only_the_days_it_covered(self):
        covered_day = self.days[0]
        statistics_cache.invalidate_statistics_days(
            self.user.id, [covered_day], reason="test-setup"
        )

        run = statistics_refresh_run.begin_run(
            self.user.id, "All Time", chunk_size=10_000
        )
        self.assertIn(
            covered_day.isoformat(),
            set(
                cache.get(
                    statistics_refresh_run._run_dirty_key(
                        self.user.id, "All Time", run["run_id"]
                    )
                )
                or ()
            ),
        )

        # A day outside this run's range goes dirty after the plan was made.
        outside_day = (timezone.localdate() - timedelta(days=4000)).isoformat()
        remaining = statistics_cache._load_dirty_days(self.user.id)
        remaining.add(outside_day)
        statistics_cache._store_dirty_days(self.user.id, remaining)

        with patch(
            "app.tasks_interactive.continue_statistics_refresh_task.apply_async"
        ):
            statistics_refresh_run.advance_chunked_run(
                self.user.id, "All Time", run["run_id"]
            )
            statistics_refresh_run.advance_chunked_run(
                self.user.id, "All Time", run["run_id"]
            )

        left = statistics_cache._load_dirty_days(self.user.id)
        self.assertEqual(left, {outside_day})

    def test_an_aborted_run_leaves_every_dirty_day_discoverable(self):
        statistics_cache.invalidate_statistics_days(
            self.user.id, self.days, reason="test-setup"
        )
        dirty_before = statistics_cache._load_dirty_days(self.user.id)

        run = statistics_refresh_run.begin_run(self.user.id, "All Time", chunk_size=2)
        statistics_refresh_run._abort_run(self.user.id, "All Time", run, "test-abort")

        self.assertEqual(statistics_cache._load_dirty_days(self.user.id), dirty_before)
        self.assertIsNone(statistics_refresh_run.load_run(self.user.id, "All Time"))


class StatisticsRefreshEmptyRangeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="stats-run-empty",
            password="secret123",
        )

    def tearDown(self):
        cache.clear()

    def test_a_user_with_no_history_still_publishes_an_empty_result(self):
        result = statistics_refresh.refresh_statistics_cache(self.user.id, "All Time")

        self.assertIsNotNone(result)
        self.assertEqual(
            _comparable(result),
            _comparable(_single_shot_reference(self.user, "All Time")),
        )
        entry = cache.get(statistics_cache._cache_key(self.user.id, "All Time"))
        self.assertIsNotNone(entry)
        self.assertIsNone(statistics_refresh_run.load_run(self.user.id, "All Time"))

    def test_an_unknown_user_does_not_leave_a_lock_behind(self):
        self.assertIsNone(statistics_refresh.refresh_statistics_cache(-1, "All Time"))
        self.assertIsNone(cache.get(statistics_cache._refresh_lock_key(-1, "All Time")))

    def test_an_unsupported_range_is_refused(self):
        self.assertIsNone(
            statistics_refresh.refresh_statistics_cache(self.user.id, "Nonsense Range")
        )


class StatisticsRefreshChunkPrefetchTests(StatisticsRunTestCase):
    def test_prefetch_is_built_per_chunk_not_once_for_the_range(self):
        """The range-wide prefetch was the largest single allocation in a run.

        Trading it for one prefetch per chunk is the deliberate throughput cost
        of a bounded, resumable rebuild; this pins that the trade actually
        happened.
        """
        with patch.object(
            statistics_refresh_run,
            "_build_prefetch_for_range",
            wraps=statistics_refresh_run._build_prefetch_for_range,
        ) as prefetch:
            statistics_refresh.refresh_statistics_cache(
                self.user.id, "All Time", chunk_size=2
            )

        self.assertGreater(prefetch.call_count, 1)
        for call_args in prefetch.call_args_list:
            self.assertLessEqual(len(call_args.args[1]), 2)
