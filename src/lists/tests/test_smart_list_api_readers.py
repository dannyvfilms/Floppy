"""Tools that read a smart list keep it current, not only the app's own pages.

The lists API, CSV export and the public RSS and arr feeds answer from the
stored membership rows. Each of them queues the same debounced background
sync the list page and Home queue, so a download tool polling a smart list
sees the refreshed membership on a later poll instead of waiting for someone
to open the list in the app.
"""

from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from api.tests.base import FloppyApiTestCase
from app.models import Item, MediaTypes, Movie, Sources, Status
from lists import tasks as list_tasks
from lists.models import CustomList

DELAY = "lists.tasks.sync_smart_list_task.delay"


def _debounce_key(custom_list):
    return f"smart_list_sync_scheduled:{custom_list.id}"


class SmartListApiReadersTests(FloppyApiTestCase):
    """Every non-page reader of a smart list's items schedules one sync."""

    def setUp(self):
        """Create a public smart list over the owner's movies."""
        super().setUp()
        self.smart_list = CustomList.objects.create(
            name="Smart Movies",
            owner=self.user1,
            is_smart=True,
            visibility="public",
            smart_media_types=[MediaTypes.MOVIE.value],
        )
        cache.delete(_debounce_key(self.smart_list))
        self.addCleanup(cache.delete, _debounce_key(self.smart_list))

    def _get(self, url_name, *, params=None):
        return self.call_api(
            "get",
            url_name,
            args=(self.smart_list.id,),
            params=params,
            headers=self.auth_headers,
        )

    def test_api_reads_schedule_one_sync_inside_the_window(self):
        """The first read queues a sync; a second read inside 60 s queues none."""
        for url_name in ("api_list_detail", "api_list_add_item"):
            with self.subTest(url_name=url_name), patch(DELAY) as delay:
                cache.delete(_debounce_key(self.smart_list))
                self.assertEqual(self._get(url_name).status_code, 200)
                self.assertEqual(self._get(url_name).status_code, 200)
                delay.assert_called_once_with(self.smart_list.id)

    def test_api_read_never_syncs_inline(self):
        """The answer comes from the stored rows; the request writes nothing."""
        with (
            patch(DELAY),
            patch("lists.models.CustomList.sync_smart_items") as sync,
        ):
            self.assertEqual(self._get("api_list_add_item").status_code, 200)
        sync.assert_not_called()

    def test_export_and_public_feeds_schedule_a_sync(self):
        """CSV export, RSS and the Radarr/Sonarr JSON feed each queue a sync."""
        reads = (
            lambda: self._get("api_list_export_csv"),
            lambda: self.client.get(reverse("list_rss", args=[self.smart_list.id])),
            lambda: self.client.get(
                reverse("list_json", args=[self.smart_list.id]), {"arr": "radarr"}
            ),
        )
        for read in reads:
            with self.subTest(read=read), patch(DELAY) as delay:
                cache.delete(_debounce_key(self.smart_list))
                self.assertEqual(read().status_code, 200)
                delay.assert_called_once_with(self.smart_list.id)

    def test_plain_list_schedules_nothing(self):
        """A list without rules has nothing to refresh."""
        plain = CustomList.objects.create(name="Plain", owner=self.user1)
        with patch(DELAY) as delay:
            response = self.call_api(
                "get",
                "api_list_add_item",
                args=(plain.id,),
                headers=self.auth_headers,
            )
        self.assertEqual(response.status_code, 200)
        delay.assert_not_called()

    def test_unreachable_queue_still_serves_the_stored_rows(self):
        """A queue outage is logged, the read succeeds, and the next read retries."""
        with (
            patch(DELAY, side_effect=ConnectionError("broker down")),
            self.assertLogs("lists.tasks", level="ERROR"),
        ):
            self.assertEqual(self._get("api_list_add_item").status_code, 200)
        with patch(DELAY) as delay:
            self.assertEqual(self._get("api_list_add_item").status_code, 200)
        delay.assert_called_once_with(self.smart_list.id)


class DateRuleSmartListThroughApiTests(FloppyApiTestCase):
    """A rule over dates changes with the clock and no write; a read repairs it."""

    def setUp(self):
        """Create a "completed in the last 7 days" list holding one movie."""
        super().setUp()
        self.item = Item.objects.create(
            title="Recent Watch",
            media_id="date-rule-1",
            media_type=MediaTypes.MOVIE.value,
            source=Sources.MANUAL.value,
            image="https://example.com/recent.jpg",
        )
        Movie.objects.create(
            item=self.item,
            user=self.user1,
            status=Status.COMPLETED.value,
            end_date=timezone.now() - timedelta(days=3),
        )
        self.smart_list = CustomList.objects.create(
            name="Last week",
            owner=self.user1,
            is_smart=True,
            smart_media_types=[MediaTypes.MOVIE.value],
            smart_filters={
                "completed_date_within": "7",
                "completed_date_within_unit": "days",
            },
        )
        self.smart_list.sync_smart_items()
        cache.delete(_debounce_key(self.smart_list))
        self.addCleanup(cache.delete, _debounce_key(self.smart_list))

    def _item_ids(self):
        response = self.call_api(
            "get",
            "api_list_add_item",
            args=(self.smart_list.id,),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        return [entry["id"] for entry in response.json()["results"]]

    def test_read_after_the_window_moves_drops_the_item_once_synced(self):
        """Ten days later the first read queues the sync; the next read is right."""
        self.assertEqual(self._item_ids(), [self.item.id])
        cache.delete(_debounce_key(self.smart_list))

        later = timezone.localdate() + timedelta(days=10)
        with (
            patch("django.utils.timezone.localdate", return_value=later),
            patch(DELAY) as delay,
        ):
            # Served from the stored rows: still the old answer.
            self.assertEqual(self._item_ids(), [self.item.id])
            delay.assert_called_once_with(self.smart_list.id)
            # The queued task runs.
            list_tasks.sync_smart_list_task(self.smart_list.id)
            self.assertEqual(self._item_ids(), [])
