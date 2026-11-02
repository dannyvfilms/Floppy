"""The runtime backfill chain must not re-count the whole candidate set per batch."""

from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from app import tasks_runtime
from app.models import Item, MediaTypes, Sources


def _metadata(*_args, **_kwargs):
    return {"details": {"runtime": "1h 30m"}}


class RuntimeBatchRequeueTests(TestCase):
    def _items(self, count):
        for i in range(count):
            Item.objects.create(
                media_id=str(1000 + i),
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title=f"Movie {i}",
            )

    def _run(self, **kwargs):
        with (
            # An interactive-request marker leaked by an earlier test would make
            # the cooperative run defer after one item.
            patch(
                "app.task_cooperation.interactive_request_active", return_value=False
            ),
            patch.object(tasks_runtime.services, "get_media_metadata", _metadata),
            patch.object(
                tasks_runtime.populate_runtime_data_batch, "apply_async"
            ) as requeue,
            CaptureQueriesContext(connection) as queries,
        ):
            result = tasks_runtime.populate_runtime_data_batch(
                delay_seconds=0, **kwargs
            )
        return result, requeue, queries

    def test_requeues_while_items_remain_without_counting_them(self):
        self._items(5)
        result, requeue, queries = self._run(batch_size=2)

        self.assertEqual(result["updated"], 2)
        self.assertTrue(result["next_batch_scheduled"])
        requeue.assert_called_once()
        counts = [
            q["sql"] for q in queries if q["sql"].lstrip().startswith("SELECT COUNT")
        ]
        self.assertEqual(counts, [])

    def test_stops_when_drained(self):
        self._items(2)
        result, requeue, _queries = self._run(batch_size=2)

        self.assertEqual(result["updated"], 2)
        self.assertFalse(result["next_batch_scheduled"])
        requeue.assert_not_called()

    def test_idle_batch_does_not_requeue(self):
        result, requeue, _queries = self._run(batch_size=2)

        self.assertEqual(result["updated"], 0)
        requeue.assert_not_called()
