"""Tests for durable reconcile gating and backoff (issue #521)."""

from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from app import cache_safety, reconcile_state
from app.models import BackfillReconcileState

KEY = "test_reconcile"


class ReconcileStateTestCase(TestCase):
    """Base case clearing the cache-held lock, which tests don't roll back."""

    def setUp(self):
        """Start from a clean cache and no reconcile rows."""
        cache.clear()
        BackfillReconcileState.objects.all().delete()


class ShouldRunTests(ReconcileStateTestCase):
    """Deciding whether a sweep is due, without querying Item."""

    def test_first_call_creates_state_and_allows_the_sweep(self):
        """A fresh install has work to do."""
        state = reconcile_state.should_run(KEY, 1)

        self.assertIsNotNone(state)
        self.assertEqual(
            BackfillReconcileState.objects.get(key=KEY).strategy_version, 1
        )

    def test_a_completed_reconcile_is_skipped(self):
        """This is the durable fact the cache marker never was."""
        reconcile_state.get_state(KEY, 1)
        reconcile_state.mark_complete(KEY, 1)

        self.assertIsNone(reconcile_state.should_run(KEY, 1))

    def test_completion_survives_a_cache_flush(self):
        """The whole point of moving this out of Redis."""
        reconcile_state.get_state(KEY, 1)
        reconcile_state.mark_complete(KEY, 1)

        cache.clear()

        self.assertIsNone(reconcile_state.should_run(KEY, 1))

    def test_a_new_strategy_version_reopens_the_reconcile(self):
        """A changed strategy means previously-done items may need revisiting."""
        reconcile_state.get_state(KEY, 1)
        reconcile_state.mark_complete(KEY, 1)

        state = reconcile_state.should_run(KEY, 2)

        self.assertIsNotNone(state)
        self.assertIsNone(state.completed_at)
        self.assertEqual(state.last_cursor_item_id, 0)

    def test_a_backing_off_reconcile_is_skipped(self):
        """Between passes, the beat tick must cost nothing."""
        reconcile_state.get_state(KEY, 1)
        BackfillReconcileState.objects.filter(key=KEY).update(
            next_run_after=timezone.now() + timedelta(hours=1),
        )

        self.assertIsNone(reconcile_state.should_run(KEY, 1))

    def test_an_expired_backoff_allows_the_sweep_again(self):
        """Backing off must not become never running."""
        reconcile_state.get_state(KEY, 1)
        BackfillReconcileState.objects.filter(key=KEY).update(
            next_run_after=timezone.now() - timedelta(minutes=1),
        )

        self.assertIsNotNone(reconcile_state.should_run(KEY, 1))


class BackoffTests(ReconcileStateTestCase):
    """Sweeps that keep finding nothing must slow down."""

    def test_repeated_empty_sweeps_back_off_exponentially(self):
        """The old 5-minute cadence never changed no matter what it found."""
        reconcile_state.get_state(KEY, 1)
        delays = []

        for _ in range(5):
            before = timezone.now()
            reconcile_state.mark_progress(KEY, 1, cursor=0, enqueued=0)
            state = BackfillReconcileState.objects.get(key=KEY)
            delays.append((state.next_run_after - before).total_seconds())

        self.assertEqual(delays, sorted(delays))
        self.assertGreater(delays[-1], delays[0])
        self.assertLessEqual(delays[-1], reconcile_state.BACKOFF_MAX_SECONDS + 5)

    def test_backoff_is_capped(self):
        """Exponential growth must not become "effectively never"."""
        reconcile_state.get_state(KEY, 1)
        BackfillReconcileState.objects.filter(key=KEY).update(
            consecutive_no_op_runs=50,
        )

        before = timezone.now()
        reconcile_state.mark_progress(KEY, 1, cursor=0, enqueued=0)
        state = BackfillReconcileState.objects.get(key=KEY)

        self.assertLessEqual(
            (state.next_run_after - before).total_seconds(),
            reconcile_state.BACKOFF_MAX_SECONDS + 5,
        )

    def test_productive_sweeps_reset_the_backoff(self):
        """Finding work means come back soon."""
        reconcile_state.get_state(KEY, 1)
        BackfillReconcileState.objects.filter(key=KEY).update(
            consecutive_no_op_runs=4,
        )

        reconcile_state.mark_progress(KEY, 1, cursor=42, enqueued=10)
        state = BackfillReconcileState.objects.get(key=KEY)

        self.assertEqual(state.consecutive_no_op_runs, 0)
        self.assertEqual(state.last_cursor_item_id, 42)

    def test_the_cursor_is_persisted_so_sweeps_resume(self):
        """Resuming is what makes a bounded pass eventually cover everything."""
        reconcile_state.get_state(KEY, 1)
        reconcile_state.mark_progress(KEY, 1, cursor=1234, enqueued=5)

        self.assertEqual(
            reconcile_state.get_state(KEY, 1).last_cursor_item_id,
            1234,
        )


class LockTests(ReconcileStateTestCase):
    """Only one sweep at a time, even without a working cache."""

    def test_a_second_acquire_is_refused(self):
        """Two concurrent whole-library sweeps are the load we're avoiding."""
        state = reconcile_state.should_run(KEY, 1)
        self.assertTrue(reconcile_state.acquire(KEY, state))

        state = reconcile_state.get_state(KEY, 1)
        self.assertFalse(reconcile_state.acquire(KEY, state))

    def test_release_allows_the_next_sweep(self):
        """A finished sweep must not block the following one for 30 minutes."""
        state = reconcile_state.should_run(KEY, 1)
        reconcile_state.acquire(KEY, state)
        reconcile_state.release(KEY)
        # Clear the claimed window that acquire() wrote, as a real pass would
        # via mark_progress.
        reconcile_state.mark_progress(KEY, 1, cursor=0, enqueued=1)
        BackfillReconcileState.objects.filter(key=KEY).update(
            next_run_after=timezone.now() - timedelta(seconds=1),
        )

        state = reconcile_state.should_run(KEY, 1)
        self.assertIsNotNone(state)
        self.assertTrue(reconcile_state.acquire(KEY, state))

    def test_an_unavailable_cache_fails_closed(self):
        """Skipping a sweep is cheap; running several at once is not."""
        state = reconcile_state.should_run(KEY, 1)

        with mock.patch.object(cache_safety, "cache_add", return_value=None):
            self.assertFalse(reconcile_state.acquire(KEY, state))
