"""The reconcilers must converge and stay converged (issue #521).

Before this, ``ensure_provider_backfill_reconcile`` ran every five minutes,
scanned the whole ``Item`` table, and re-enqueued every outstanding candidate -
forever, because previously-failed items kept re-entering the candidate set and
the completion marker was never consulted. These tests pin the three properties
that make it terminate.
"""

from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from app import backfill_queue, reconcile_state, tasks_providers
from app.models import (
    BackfillReconcileState,
    Item,
    MediaTypes,
    MetadataBackfillField,
    MetadataBackfillState,
    Sources,
)
from app.tasks_providers import (
    RECONCILE_KEY,
    WATCH_PROVIDERS_BACKFILL_VERSION,
    ensure_provider_backfill_reconcile,
    reconcile_provider_backfill,
)


def make_item(media_id):
    """Create a TMDB movie with no watch-provider data yet."""
    return Item.objects.create(
        media_id=str(media_id),
        source=Sources.TMDB.value,
        media_type=MediaTypes.MOVIE.value,
        title=f"Movie {media_id}",
    )


@patch("app.tasks_providers.populate_provider_backfill_queue.apply_async")
class ReconcileConvergenceTests(TestCase):
    """A reconcile eventually finishes and then stops doing work."""

    def setUp(self):
        """Start from a clean queue, cache and reconcile state.

        The reconcile lock lives in the cache, which - unlike the database - is
        not rolled back between tests, so a lock left by another test would make
        these fail depending on run order.
        """
        cache.clear()
        backfill_queue.clear(
            tasks_providers.WATCH_PROVIDERS_BACKFILL_ITEMS_QUEUE_KEY,
            tasks_providers.WATCH_PROVIDERS_BACKFILL_ITEMS_SCHEDULED_KEY,
        )
        BackfillReconcileState.objects.all().delete()

    def test_an_empty_library_is_marked_complete_immediately(self, _mock_drain):
        """Nothing to do must be recorded, not rediscovered every five minutes."""
        result = reconcile_provider_backfill()

        self.assertTrue(result["complete"])
        state = BackfillReconcileState.objects.get(key=RECONCILE_KEY)
        self.assertIsNotNone(state.completed_at)

    def test_a_completed_reconcile_short_circuits_without_touching_items(
        self,
        _mock_drain,
    ):
        """The gate must be answerable from the state row alone."""
        reconcile_provider_backfill()

        with patch(
            "app.tasks_providers._provider_items_queryset",
        ) as mock_queryset:
            result = ensure_provider_backfill_reconcile()

        self.assertEqual(result["reason"], "not_due")
        mock_queryset.assert_not_called()

    def test_a_backing_off_reconcile_short_circuits_without_touching_items(
        self,
        _mock_drain,
    ):
        state = reconcile_state.get_state(
            RECONCILE_KEY,
            WATCH_PROVIDERS_BACKFILL_VERSION,
        )
        BackfillReconcileState.objects.filter(pk=state.pk).update(
            next_run_after=timezone.now() + timedelta(hours=1),
        )

        with patch(
            "app.tasks_providers._provider_items_queryset",
        ) as mock_queryset:
            result = ensure_provider_backfill_reconcile()

        self.assertEqual(result["reason"], "not_due")
        mock_queryset.assert_not_called()

    def test_a_pass_is_bounded_and_resumes_from_its_cursor(self, _mock_drain):
        """One pass must not enqueue the whole library."""
        for media_id in range(1, 11):
            make_item(2000 + media_id)

        first = reconcile_provider_backfill(batch_size=2, max_chunks=2)

        self.assertEqual(first["selected"], 4)
        cursor = BackfillReconcileState.objects.get(key=RECONCILE_KEY)
        self.assertGreater(cursor.last_cursor_item_id, 0)

        second = reconcile_provider_backfill(batch_size=2, max_chunks=2)

        self.assertEqual(second["selected"], 4)
        self.assertGreater(
            BackfillReconcileState.objects.get(key=RECONCILE_KEY).last_cursor_item_id,
            cursor.last_cursor_item_id,
        )

    def test_repeated_passes_converge_once_the_work_lands(self, _mock_drain):
        """Bounded passes must still converge rather than cycle forever.

        The enqueued items are marked backfilled between passes, standing in for
        the drain task. Without that the reconcile correctly keeps finding
        candidates - "complete" means the library has the data, not that a sweep
        has looked at it.
        """
        items = [make_item(3000 + media_id) for media_id in range(1, 8)]

        for _ in range(20):
            reconcile_provider_backfill(batch_size=2, max_chunks=1)
            # Simulate the drain succeeding for everything queued so far.
            for item in items:
                MetadataBackfillState.objects.update_or_create(
                    item=item,
                    field=MetadataBackfillField.WATCH_PROVIDERS,
                    defaults={
                        "fail_count": 0,
                        "give_up": False,
                        "last_success_at": timezone.now(),
                        "strategy_version": WATCH_PROVIDERS_BACKFILL_VERSION,
                    },
                )
            if BackfillReconcileState.objects.get(key=RECONCILE_KEY).completed_at:
                break

        self.assertIsNotNone(
            BackfillReconcileState.objects.get(key=RECONCILE_KEY).completed_at,
        )

    def test_a_sweep_that_never_finishes_the_work_keeps_finding_candidates(
        self,
        _mock_drain,
    ):
        """"Complete" must mean the data is there, not that a sweep ran."""
        for media_id in range(1, 6):
            make_item(3500 + media_id)

        for _ in range(5):
            reconcile_provider_backfill(batch_size=2, max_chunks=1)

        self.assertIsNone(
            BackfillReconcileState.objects.get(key=RECONCILE_KEY).completed_at,
        )

    def test_previously_failed_items_do_not_block_completion(self, _mock_drain):
        """The bug that made the reconcile permanent.

        A failed item's next_retry_at caps at one day, so it re-entered the
        candidate set daily and the sweep could never be marked complete. Retrying
        failures belongs to backfill_item_metadata, not to the reconcile.
        """
        item = make_item(4001)
        MetadataBackfillState.objects.create(
            item=item,
            field=MetadataBackfillField.WATCH_PROVIDERS,
            fail_count=2,
            # Already due for retry, so the old next_retry_at filter wouldn't
            # have excluded it.
            next_retry_at=timezone.now() - timedelta(hours=1),
        )

        result = reconcile_provider_backfill()

        self.assertTrue(result["complete"])
        # The item is still a candidate for the regular retry path.
        self.assertIn(
            item.id,
            set(
                tasks_providers._provider_items_queryset().values_list("id", flat=True),
            ),
        )

    def test_an_interactive_request_defers_the_sweep(self, _mock_drain):
        """Background maintenance yields to someone actually using the app."""
        with patch(
            "app.tasks_providers.interactive_request_active",
            return_value=True,
        ):
            result = ensure_provider_backfill_reconcile()

        self.assertEqual(result["reason"], "interactive_request_active")

    def test_a_concurrent_sweep_is_refused(self, _mock_drain):
        """Two overlapping whole-library sweeps are the load we're avoiding."""
        make_item(5001)
        state = reconcile_state.should_run(
            RECONCILE_KEY, WATCH_PROVIDERS_BACKFILL_VERSION
        )
        reconcile_state.acquire(RECONCILE_KEY, state)

        result = ensure_provider_backfill_reconcile()

        self.assertIn(result["reason"], {"already_running", "not_due"})
