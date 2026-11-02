"""Tests for CooperativeRun and its adoption in backfill tasks."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase, override_settings

from app.interactive_requests import INTERACTIVE_REQUEST_TTL_SECONDS
from app.models import Item, MediaTypes, Sources
from app.task_cooperation import CooperativeRun, higher_priority_task_waiting


def _fake_items(count):
    return [SimpleNamespace(id=index + 1) for index in range(count)]


class CooperativeRunTests(TestCase):
    """Unit tests for the CooperativeRun iterator."""

    @patch("app.task_cooperation.interactive_request_active", return_value=False)
    def test_processes_all_items_when_idle(self, _mock_active):
        """Without interactive activity, every item is yielded."""
        run = CooperativeRun("test_idle")
        items = _fake_items(3)
        self.assertEqual(list(run.iter(items)), items)
        self.assertFalse(run.deferred)
        self.assertEqual(run.remaining, [])

    @patch("app.task_cooperation.interactive_request_active", return_value=True)
    def test_defers_after_min_progress(self, _mock_active):
        """With the flag set, the first item still processes; the rest defer."""
        run = CooperativeRun("test_defer")
        items = _fake_items(4)
        with self.assertLogs("app.task_cooperation", level="INFO") as logs:
            processed = list(run.iter(items))
        self.assertEqual(processed, items[:1])
        self.assertTrue(run.deferred)
        self.assertEqual(run.remaining, items[1:])
        self.assertEqual(run.remaining_ids, [2, 3, 4])
        self.assertIn("test_defer_deferred", logs.output[0])
        self.assertIn("processed=1 remaining=3", logs.output[0])

    @patch("app.task_cooperation.interactive_request_active")
    def test_defers_when_flag_flips_mid_run(self, mock_active):
        """A flag raised mid-iteration stops the run at that point."""
        mock_active.side_effect = [False, False, True]
        run = CooperativeRun("test_mid")
        items = _fake_items(5)
        processed = list(run.iter(items))
        self.assertEqual(processed, items[:3])
        self.assertTrue(run.deferred)
        self.assertEqual(run.remaining_ids, [4, 5])

    @patch("app.task_cooperation.interactive_request_active", return_value=True)
    def test_check_every_skips_checks(self, mock_active):
        """check_every batches the flag checks."""
        run = CooperativeRun("test_batch", check_every=3, min_progress=3)
        items = _fake_items(7)
        processed = list(run.iter(items))
        # Checks happen at indexes 3 and 6; deferral hits at index 3.
        self.assertEqual(processed, items[:3])
        self.assertEqual(mock_active.call_count, 1)

    @patch("app.task_cooperation.interactive_request_active", return_value=False)
    def test_empty_iterable(self, _mock_active):
        """An empty input yields nothing and does not defer."""
        run = CooperativeRun("test_empty")
        self.assertEqual(list(run.iter([])), [])
        self.assertFalse(run.deferred)


class GenreBackfillDeferralTests(TestCase):
    """The genre backfill loop re-enqueues the remainder when deferred."""

    def _create_items(self, count):
        return [
            Item.objects.create(
                media_id=f"coop_{index}",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title=f"Coop Movie {index}",
                image="https://example.com/movie.jpg",
            )
            for index in range(count)
        ]

    @patch("app.tasks_genre.enqueue_genre_backfill_items")
    @patch("app.tasks_genre.services.get_media_metadata", return_value=None)
    @patch("app.task_cooperation.interactive_request_active", return_value=True)
    def test_deferred_items_are_reenqueued(
        self,
        _mock_active,
        mock_metadata,
        mock_enqueue,
    ):
        """Only the first item is processed; the rest go back on the queue.

        The retry waits out the interactive flag's TTL: a sooner one finds the
        flag still set and processes a single item again (#1158).
        """
        from app.tasks_genre import _populate_genres_for_items

        items = self._create_items(3)
        _populate_genres_for_items(items, delay_seconds=0)

        self.assertEqual(mock_metadata.call_count, 1)
        mock_enqueue.assert_called_once_with(
            [items[1].id, items[2].id],
            countdown=INTERACTIVE_REQUEST_TTL_SECONDS,
        )

    @patch("app.tasks_genre.enqueue_genre_backfill_items")
    @patch("app.tasks_genre.services.get_media_metadata", return_value=None)
    @patch("app.task_cooperation.interactive_request_active", return_value=False)
    def test_idle_run_processes_all_without_reenqueue(
        self,
        _mock_active,
        mock_metadata,
        mock_enqueue,
    ):
        """Without interactive activity the whole batch is processed."""
        from app.tasks_genre import _populate_genres_for_items

        items = self._create_items(3)
        _populate_genres_for_items(items, delay_seconds=0)

        self.assertEqual(mock_metadata.call_count, 3)
        mock_enqueue.assert_not_called()


class TraktPopularityDeferralTests(TestCase):
    """The Trakt loop forwards the retry countdown through its force wrapper."""

    @patch("app.tasks_trakt.enqueue_trakt_popularity_backfill_items")
    @patch("app.tasks_trakt.trakt_popularity_service")
    @patch("app.task_cooperation.interactive_request_active", return_value=True)
    def test_deferred_items_are_reenqueued_with_force_and_countdown(
        self,
        _mock_active,
        mock_service,
        mock_enqueue,
    ):
        from app.tasks_trakt import populate_trakt_popularity_data_for_items

        items = [
            Item.objects.create(
                media_id=f"trakt_coop_{index}",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title=f"Trakt Coop {index}",
                image="https://example.com/movie.jpg",
            )
            for index in range(3)
        ]
        mock_service.trakt_provider.is_configured.return_value = True
        mock_service.tracked_items_queryset.return_value = Item.objects.all()

        populate_trakt_popularity_data_for_items(
            [item.id for item in items], force=True
        )

        mock_enqueue.assert_called_once()
        args, kwargs = mock_enqueue.call_args
        self.assertEqual(len(args[0]), 2)
        self.assertEqual(
            kwargs,
            {"countdown": INTERACTIVE_REQUEST_TTL_SECONDS, "force": True},
        )


@override_settings(CELERY_TASK_ALWAYS_EAGER=False)
@patch("app.task_cooperation._BROKER_LOOK_FAILED_AT", 0.0)
class HigherPriorityTaskWaitingTests(SimpleTestCase):
    """A long task can see a webhook queued behind it without owning a broker."""

    def channel(self, queued):
        client = SimpleNamespace(llen=lambda key: queued if key == "interactive" else 0)
        channel = SimpleNamespace(client=client, _q_for_pri=lambda queue, pri: queue)
        connection = MagicMock()
        connection.default_channel = channel
        pool = MagicMock()
        pool.acquire.return_value.__enter__.return_value = connection
        return SimpleNamespace(pool=pool)

    def test_reports_a_queued_task(self):
        with patch("config.celery.app", self.channel(queued=2)):
            self.assertTrue(higher_priority_task_waiting("interactive"))

    def test_reports_an_empty_queue(self):
        with patch("config.celery.app", self.channel(queued=0)):
            self.assertFalse(higher_priority_task_waiting("interactive"))

    def test_a_broker_error_never_stops_the_caller_and_is_not_retried_at_once(self):
        broken = SimpleNamespace(pool=MagicMock())
        broken.pool.acquire.side_effect = ConnectionError("down")
        with patch("config.celery.app", broken):
            self.assertFalse(higher_priority_task_waiting("interactive"))
            self.assertFalse(higher_priority_task_waiting("interactive"))
        self.assertEqual(broken.pool.acquire.call_count, 1)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_eager_runs_never_touch_a_broker(self):
        with patch("config.celery.app") as app:
            self.assertFalse(higher_priority_task_waiting("interactive"))
        app.pool.acquire.assert_not_called()
