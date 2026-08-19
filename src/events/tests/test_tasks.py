from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from app.models import Item, MediaTypes, Sources
from events.tasks import reload_calendar


class ReloadCalendarTaskTests(TestCase):
    """Tests for the reload_calendar Celery task."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="taskuser",
            password="pass12345",
        )

    @patch("events.tasks.get_items_to_process", return_value=[])
    @patch("events.tasks.auto_pause.auto_pause_stale_items")
    @patch("events.tasks.fetch_releases")
    def test_auto_pause_runs_for_global_refresh(
        self,
        mock_fetch,
        mock_auto_pause,
        mock_select,
    ):
        mock_fetch.return_value = "ok"

        result = reload_calendar()

        self.assertEqual(result, "ok")
        # The global refresh resolves its own work list so the selection (which
        # queries TMDB's change feed) runs once per reload, not once per chunk.
        mock_select.assert_called_once_with(None)
        mock_fetch.assert_called_once_with(user=None, items_to_process=[])
        mock_auto_pause.assert_called_once_with()

    @patch("events.tasks.auto_pause.auto_pause_stale_items")
    @patch("events.tasks.fetch_releases")
    def test_auto_pause_skipped_for_single_user(self, mock_fetch, mock_auto_pause):
        mock_fetch.return_value = "ok"

        result = reload_calendar(user_id=self.user.id)

        self.assertEqual(result, "ok")
        mock_fetch.assert_called_once_with(user=self.user, items_to_process=None)
        mock_auto_pause.assert_not_called()

    @patch("events.tasks.auto_pause.auto_pause_stale_items")
    @patch("events.tasks.fetch_releases")
    def test_item_ids_are_resolved_before_fetch(self, mock_fetch, mock_auto_pause):
        movie = Item.objects.create(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Matrix",
            image="https://example.com/matrix.jpg",
        )
        mock_fetch.return_value = "ok"

        result = reload_calendar(item_ids=[movie.id])

        self.assertEqual(result, "ok")
        mock_fetch.assert_called_once_with(user=None, items_to_process=[movie])
        mock_auto_pause.assert_not_called()

    @patch("events.tasks.get_items_to_process", return_value=[])
    @patch("app.tasks.backfill_item_metadata_task.apply_async")
    @patch("events.tasks.auto_pause.auto_pause_stale_items")
    @patch("events.tasks.fetch_releases")
    def test_release_backfill_is_queued_on_global_refresh_when_release_dates_missing(
        self,
        mock_fetch,
        mock_auto_pause,
        mock_backfill_apply_async,
        mock_select,
    ):
        """The backfill is queued, not run inline (#521).

        It used to run inline at a batch size of up to 5000, so one calendar
        reload held a worker while fetching thousands of items' metadata - and
        each fetch caches a full provider payload, which is also the fastest way
        to fill Redis.
        """
        mock_fetch.return_value = "ok"
        Item.objects.create(
            media_id="262712",
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            title="Ananta",
            image="https://example.com/ananta.jpg",
            metadata_fetched_at=timezone.now(),
            release_datetime=None,
        )

        result = reload_calendar()

        self.assertEqual(result, "ok")
        mock_fetch.assert_called_once_with(user=None, items_to_process=[])
        mock_auto_pause.assert_called_once_with()
        mock_backfill_apply_async.assert_called_once()
        self.assertEqual(
            mock_backfill_apply_async.call_args.kwargs["kwargs"]["batch_size"],
            settings.CALENDAR_RELOAD_BACKFILL_BATCH_SIZE,
        )

    @override_settings(CALENDAR_RELOAD_CHUNK_SIZE=2)
    @patch("app.tasks.backfill_item_metadata_task.apply_async")
    @patch("events.tasks.reload_calendar.delay")
    @patch("events.tasks.auto_pause.auto_pause_stale_items")
    @patch("events.tasks.fetch_releases")
    def test_global_refresh_processes_one_chunk_and_defers_the_rest(
        self,
        mock_fetch,
        mock_auto_pause,
        mock_delay,
        mock_backfill_apply_async,
    ):
        """One task must not hold a worker for the whole library walk."""
        items = [
            Item.objects.create(
                media_id=f"tt{index}",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title=f"Movie {index}",
                image=f"https://example.com/{index}.jpg",
            )
            for index in range(5)
        ]
        mock_fetch.return_value = "ok"

        with patch("events.tasks.get_items_to_process", return_value=items):
            result = reload_calendar()

        self.assertEqual(result, "ok")
        mock_fetch.assert_called_once_with(user=None, items_to_process=items[:2])
        mock_delay.assert_called_once_with(item_ids=[item.id for item in items[2:]])

    @override_settings(CALENDAR_RELOAD_CHUNK_SIZE=0)
    @patch("app.tasks.backfill_item_metadata_task.apply_async")
    @patch("events.tasks.reload_calendar.delay")
    @patch("events.tasks.auto_pause.auto_pause_stale_items")
    @patch("events.tasks.fetch_releases")
    def test_chunking_can_be_disabled(
        self,
        mock_fetch,
        mock_auto_pause,
        mock_delay,
        mock_backfill_apply_async,
    ):
        """0 restores the previous single-pass behaviour."""
        items = [
            Item.objects.create(
                media_id=f"zz{index}",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title=f"Other {index}",
                image=f"https://example.com/o{index}.jpg",
            )
            for index in range(3)
        ]
        mock_fetch.return_value = "ok"

        with patch("events.tasks.get_items_to_process", return_value=items):
            reload_calendar()

        mock_fetch.assert_called_once_with(user=None, items_to_process=items)
        mock_delay.assert_not_called()
