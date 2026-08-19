"""Floppy must keep working when Redis does not (issue #521).

The reported failure was a Redis read timeout inside cache.get propagating all
the way out of webhook processing. These tests pin the behaviour that replaced
it: a cache failure degrades to a miss, and the paths that use the cache for
control flow rather than caching resolve it deliberately.
"""

from unittest import mock

import redis
from django.test import SimpleTestCase, TestCase

from app import backfill_queue, interactive_requests, tasks_providers
from app.interactive_requests import interactive_request_active
from app.models import Item, MediaTypes, Sources


class InteractiveMarkerTests(SimpleTestCase):
    """The marker that background tasks yield to."""

    def test_unavailable_cache_reports_no_interactive_request(self):
        """True would defer every background task for the whole outage."""
        with mock.patch.object(
            interactive_requests.cache,
            "get",
            side_effect=redis.exceptions.TimeoutError("Timeout reading from redis"),
        ):
            self.assertFalse(interactive_request_active())

    def test_ignored_exception_none_also_reports_no_interactive_request(self):
        """IGNORE_EXCEPTIONS returns None rather than raising."""
        with mock.patch.object(interactive_requests.cache, "get", return_value=None):
            self.assertFalse(interactive_request_active())

    def test_it_never_raises_into_cooperative_run(self):
        """CooperativeRun.iter calls this outside the per-item try/except."""
        from app.task_cooperation import CooperativeRun

        with mock.patch.object(
            interactive_requests.cache,
            "get",
            side_effect=redis.exceptions.ConnectionError("refused"),
        ):
            run = CooperativeRun("test")
            self.assertEqual(list(run.iter([1, 2, 3])), [1, 2, 3])


class BackfillQueueDegradationTests(TestCase):
    """The queue must report unavailability rather than dropping work."""

    def setUp(self):
        """Start each test from an empty queue."""
        backfill_queue.clear(
            tasks_providers.WATCH_PROVIDERS_BACKFILL_ITEMS_QUEUE_KEY,
            tasks_providers.WATCH_PROVIDERS_BACKFILL_ITEMS_SCHEDULED_KEY,
        )

    def test_enqueue_reports_failure_when_redis_is_down(self):
        """A False return is what lets the caller dispatch directly instead."""
        with mock.patch.object(
            backfill_queue,
            "_client",
            return_value=mock.Mock(
                pipeline=mock.Mock(
                    side_effect=redis.exceptions.ConnectionError("refused"),
                ),
            ),
        ):
            queued = backfill_queue.enqueue(
                "q",
                "s",
                [1, 2],
                ttl=60,
                drain_task=mock.Mock(),
            )
        self.assertFalse(queued)

    @mock.patch("app.tasks_providers.populate_provider_data_for_items.apply_async")
    @mock.patch("app.tasks_providers.populate_provider_backfill_queue.apply_async")
    def test_items_are_dispatched_directly_when_the_queue_is_unavailable(
        self,
        mock_drain,
        mock_direct,
    ):
        """The fallback used to be dead code, silently dropping the items."""
        item = Item.objects.create(
            media_id="9001",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Unavailable Queue Movie",
        )

        with mock.patch.object(backfill_queue, "enqueue", return_value=False):
            queued = tasks_providers.enqueue_provider_backfill_items([item.id])

        self.assertEqual(queued, 1)
        mock_direct.assert_called_once()
        self.assertEqual(mock_direct.call_args.kwargs["args"], [[item.id]])
        mock_drain.assert_not_called()

    def test_take_reports_no_work_rather_than_raising(self):
        """A drain task must not crash when Redis goes away mid-run."""
        with mock.patch.object(
            backfill_queue,
            "_client",
            return_value=mock.Mock(
                spop=mock.Mock(side_effect=redis.exceptions.TimeoutError("timeout")),
            ),
        ):
            batch, more = backfill_queue.take("q", "s", 50)
        self.assertEqual(batch, [])
        self.assertFalse(more)


class BackfillQueueBehaviourTests(TestCase):
    """The set-backed queue's own semantics."""

    QUEUE = "test_backfill_queue"
    SCHEDULED = "test_backfill_scheduled"

    def setUp(self):
        """Start each test from an empty queue."""
        backfill_queue.clear(self.QUEUE, self.SCHEDULED)

    def test_enqueue_deduplicates_without_reading_the_whole_queue(self):
        """The set is what removes the O(N) read-modify-write per batch."""
        drain = mock.Mock()
        backfill_queue.enqueue(
            self.QUEUE, self.SCHEDULED, [1, 2, 3], ttl=60, drain_task=drain
        )
        backfill_queue.enqueue(
            self.QUEUE, self.SCHEDULED, [3, 4], ttl=60, drain_task=drain
        )

        self.assertEqual(backfill_queue.members(self.QUEUE), {1, 2, 3, 4})
        self.assertEqual(backfill_queue.depth(self.QUEUE), 4)

    def test_only_the_first_enqueue_schedules_a_drain(self):
        """The marker keeps a burst of enqueues from queueing a drain each."""
        drain = mock.Mock()
        for _ in range(5):
            backfill_queue.enqueue(
                self.QUEUE, self.SCHEDULED, [1], ttl=60, drain_task=drain
            )
        drain.apply_async.assert_called_once()

    def test_take_removes_the_batch_and_reports_whether_more_remain(self):
        """The drain has to know whether to schedule itself again."""
        drain = mock.Mock()
        backfill_queue.enqueue(
            self.QUEUE, self.SCHEDULED, range(10), ttl=60, drain_task=drain
        )

        batch, more = backfill_queue.take(self.QUEUE, self.SCHEDULED, 4)
        self.assertEqual(len(batch), 4)
        self.assertTrue(more)
        self.assertEqual(backfill_queue.depth(self.QUEUE), 6)

        _, more = backfill_queue.take(self.QUEUE, self.SCHEDULED, 100)
        self.assertFalse(more)
        self.assertEqual(backfill_queue.depth(self.QUEUE), 0)

    def test_string_members_survive_the_round_trip(self):
        """Episode season keys are encoded tokens, not integers."""
        drain = mock.Mock()
        backfill_queue.enqueue(
            self.QUEUE,
            self.SCHEDULED,
            ["tmdb:1234:2", "tmdb:5678:1"],
            ttl=60,
            drain_task=drain,
        )
        batch, _ = backfill_queue.take(self.QUEUE, self.SCHEDULED, 10, coerce=str)
        self.assertEqual(set(batch), {"tmdb:1234:2", "tmdb:5678:1"})

    def test_keys_are_namespaced_by_redis_prefix(self):
        """Two instances sharing a Redis must not share backfill queues."""
        with self.settings(REDIS_PREFIX="inst_a"):
            self.assertEqual(backfill_queue.namespaced("q"), "inst_a:q")
        with self.settings(REDIS_PREFIX=None):
            self.assertEqual(backfill_queue.namespaced("q"), "q")
