"""Tests for deferring smart-list membership sync off GET requests.

Smart-list pages render membership dynamically (rules are evaluated per
request), so the write-heavy sync_smart_items() persistence step runs as a
debounced background task instead of inside page loads.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from app.models import Item, MediaTypes, Movie, Sources, Status
from lists import tasks as list_tasks
from lists.models import CustomList
from users.home_screen import _custom_list_row_window
from users.models import HomeScreenRowTypeChoices


def _make_smart_list(owner, **kwargs):
    return CustomList.objects.create(
        name=kwargs.pop("name", "Smart"),
        owner=owner,
        is_smart=True,
        smart_media_types=[MediaTypes.MOVIE.value],
        smart_filters={"status": "all", "rating": "all", "collection": "all"},
        **kwargs,
    )


def _clear_debounce(custom_list):
    cache.delete(f"smart_list_sync_scheduled:{custom_list.id}")


class SyncSmartListTaskTests(TestCase):
    """The background task persists smart-list membership."""

    def setUp(self):
        """Create a user with a matching movie."""
        self.user = get_user_model().objects.create_user(
            username="smartuser",
            password="12345",
        )
        self.item = Item.objects.create(
            title="Smart Movie",
            media_id="456",
            media_type=MediaTypes.MOVIE.value,
            source=Sources.TMDB.value,
            image="https://example.com/movie.jpg",
        )
        Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.COMPLETED.value,
        )

    def test_task_syncs_membership(self):
        """Running the task persists matching items to the list."""
        smart_list = _make_smart_list(self.user)
        list_tasks.sync_smart_list_task(smart_list.id)
        self.assertTrue(smart_list.items.filter(id=self.item.id).exists())

    def test_task_skips_missing_list(self):
        """A deleted list is skipped without raising."""
        smart_list = _make_smart_list(self.user)
        missing_id = smart_list.id
        smart_list.delete()
        list_tasks.sync_smart_list_task(missing_id)

    def test_task_skips_regular_list(self):
        """A non-smart list is left untouched."""
        regular = CustomList.objects.create(name="Plain", owner=self.user)
        list_tasks.sync_smart_list_task(regular.id)
        self.assertFalse(regular.items.exists())


class ScheduleSmartListSyncTests(TestCase):
    """Scheduling is debounced and only applies to smart lists."""

    def setUp(self):
        """Create a user and a smart list with a clean debounce key."""
        self.user = get_user_model().objects.create_user(
            username="debounceuser",
            password="12345",
        )
        self.smart_list = _make_smart_list(self.user)
        _clear_debounce(self.smart_list)

    def tearDown(self):
        """Leave no debounce key behind for other tests."""
        _clear_debounce(self.smart_list)

    @patch("lists.tasks.sync_smart_list_task.delay")
    def test_schedule_enqueues_once_within_debounce_window(self, mock_delay):
        """The second schedule inside the window is a no-op."""
        self.assertTrue(list_tasks.schedule_smart_list_sync(self.smart_list))
        self.assertFalse(list_tasks.schedule_smart_list_sync(self.smart_list))
        mock_delay.assert_called_once_with(self.smart_list.id)

    @patch("lists.tasks.sync_smart_list_task.delay")
    def test_schedule_noop_for_regular_list(self, mock_delay):
        """Regular lists never schedule a smart sync."""
        regular = CustomList.objects.create(name="Plain", owner=self.user)
        self.assertFalse(list_tasks.schedule_smart_list_sync(regular))
        mock_delay.assert_not_called()


class GetRequestsDoNotSyncInlineTests(TestCase):
    """GET pages schedule the sync instead of writing membership inline."""

    def setUp(self):
        """Create a logged-in client and a smart list."""
        self.credentials = {"username": "getuser", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client = Client()
        self.client.login(**self.credentials)
        self.smart_list = _make_smart_list(self.user)
        _clear_debounce(self.smart_list)

    def tearDown(self):
        """Leave no debounce key behind for other tests."""
        _clear_debounce(self.smart_list)

    @patch("lists.models.CustomList.sync_smart_items")
    @patch("lists.tasks.sync_smart_list_task.delay")
    def test_list_detail_schedules_background_sync(self, mock_delay, mock_sync):
        """list_detail renders without inline membership writes."""
        response = self.client.get(
            reverse("list_detail", args=[self.smart_list.id]),
        )
        self.assertEqual(response.status_code, 200)
        mock_sync.assert_not_called()
        mock_delay.assert_called_once_with(self.smart_list.id)

    @patch("lists.models.CustomList.sync_smart_items")
    @patch("lists.tasks.sync_smart_list_task.delay")
    def test_home_custom_list_row_schedules_background_sync(
        self,
        mock_delay,
        mock_sync,
    ):
        """Home smart-list rows render saved membership and sync in the background."""
        row = self.user.home_screen_rows.create(
            media_type=MediaTypes.MOVIE.value,
            row_type=HomeScreenRowTypeChoices.CUSTOM_LIST,
            custom_list=self.smart_list,
        )
        _custom_list_row_window(self.user, row, 0, 100, seed=0)
        mock_sync.assert_not_called()
        mock_delay.assert_called_once_with(self.smart_list.id)


class MediaSaveDefersSmartListSyncTests(TestCase):
    """A media write queues the rule evaluation instead of running it inline."""

    def setUp(self):
        """Create a user, a smart list and an untracked item."""
        self.user = get_user_model().objects.create_user(
            username="smartwriter",
            password="12345",
        )
        self.item = Item.objects.create(
            title="Written Movie",
            media_id="789",
            media_type=MediaTypes.MOVIE.value,
            source=Sources.TMDB.value,
            image="https://example.com/movie.jpg",
        )
        self.smart_list = _make_smart_list(self.user)

    def test_save_queues_task_and_membership_follows(self):
        """The save queues one task; running it adds the item to the list."""
        with (
            self.settings(CELERY_TASK_ALWAYS_EAGER=False),
            patch("lists.tasks.sync_smart_lists_for_items_task.delay") as mock_delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            Movie.objects.create(
                item=self.item,
                user=self.user,
                status=Status.COMPLETED.value,
            )
        self.assertFalse(self.smart_list.items.filter(id=self.item.id).exists())
        mock_delay.assert_called_with(self.user.id, [self.item.id])

        list_tasks.sync_smart_lists_for_items_task(self.user.id, [self.item.id])
        self.assertTrue(self.smart_list.items.filter(id=self.item.id).exists())

    def test_save_without_smart_lists_queues_nothing(self):
        """An owner with no smart lists pays no enqueue."""
        self.smart_list.delete()
        with (
            self.settings(CELERY_TASK_ALWAYS_EAGER=False),
            patch("lists.tasks.sync_smart_lists_for_items_task.delay") as mock_delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            Movie.objects.create(
                item=self.item,
                user=self.user,
                status=Status.COMPLETED.value,
            )
        mock_delay.assert_not_called()
