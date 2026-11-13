"""Discover refreshes: queued copies coalesce and a library pool stays bounded."""

import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from app.discover import service, tab_cache
from app.models import Item, MediaTypes, Movie, Sources, Status
from app.tasks import refresh_discover_rows, refresh_discover_tab_cache


@override_settings(TESTING=False)
class RowRefreshCoalescingTests(TestCase):
    """Several stale rows of one tab cost one tab rebuild, and no duplicates."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username="rows", password="x")

    def queue(self, *row_keys):
        with patch("app.tasks.refresh_discover_rows.delay") as delay:
            for row_key in row_keys:
                service._queue_stale_refresh(self.user.id, "movie", row_key, False)
        return delay

    def run_task(self, row_key):
        with (
            patch("app.discover.service.refresh_rows_for_user", return_value=1),
            patch("app.discover.tab_cache.refresh_tab_cache") as rebuild,
        ):
            refresh_discover_rows(self.user.id, "movie", [row_key])
        return rebuild

    def test_only_the_last_queued_row_refresh_rebuilds_the_tab(self):
        self.queue("comfort_rewatches", "top_picks_for_you", "coming_soon")

        self.assertEqual(self.run_task("comfort_rewatches").call_count, 0)
        self.assertEqual(self.run_task("top_picks_for_you").call_count, 0)
        self.assertEqual(self.run_task("coming_soon").call_count, 1)

    def test_a_lone_row_refresh_still_rebuilds_the_tab(self):
        self.queue("coming_soon")

        self.assertEqual(self.run_task("coming_soon").call_count, 1)

    def test_a_task_queued_outside_the_page_path_still_rebuilds_the_tab(self):
        self.assertEqual(self.run_task("coming_soon").call_count, 1)

    def test_a_row_waiting_in_the_queue_is_not_queued_again(self):
        delay = self.queue("coming_soon", "coming_soon")

        self.assertEqual(delay.call_count, 1)

    def test_the_lock_is_released_when_the_task_finishes(self):
        self.queue("coming_soon")
        self.run_task("coming_soon")

        delay = self.queue("coming_soon")

        self.assertEqual(delay.call_count, 1)

    def test_a_failed_task_releases_its_lock_and_its_place_in_the_count(self):
        self.queue("comfort_rewatches", "coming_soon")
        with (
            patch(
                "app.discover.service.refresh_rows_for_user",
                side_effect=RuntimeError("provider down"),
            ),
            self.assertRaises(RuntimeError),
        ):
            refresh_discover_rows(self.user.id, "movie", ["comfort_rewatches"])

        self.assertEqual(self.run_task("coming_soon").call_count, 1)
        self.assertEqual(self.queue("comfort_rewatches").call_count, 1)

    def test_every_return_path_is_json_serializable(self):
        # Celery stores the return value as JSON; an eager test run never
        # encodes it, so a User object left in the result went unnoticed.
        self.queue("comfort_rewatches", "coming_soon")
        coalesced = self.run_task("comfort_rewatches")
        rebuilt = self.run_task("coming_soon")
        with patch("app.discover.service.refresh_rows_for_user", return_value=1):
            results = [
                refresh_discover_rows(self.user.id, "movie", ["coming_soon"]),
                refresh_discover_rows(0, "movie", ["coming_soon"]),
            ]
        self.user.show_discover = False
        self.user.save(update_fields=["show_discover"])
        results.append(refresh_discover_rows(self.user.id, "movie", ["coming_soon"]))

        self.assertEqual(coalesced.call_count, 0)
        self.assertEqual(rebuilt.call_count, 1)
        for result in results:
            json.dumps(result)

    def test_a_coalesced_result_has_no_internal_keys(self):
        self.queue("comfort_rewatches", "coming_soon")
        with (
            patch("app.discover.service.refresh_rows_for_user", return_value=1),
            patch("app.discover.tab_cache.refresh_tab_cache"),
        ):
            result = refresh_discover_rows(self.user.id, "movie", ["comfort_rewatches"])

        self.assertEqual(
            result,
            {"refreshed": 1, "user_id": self.user.id, "media_type": "movie"},
        )

    def test_a_disabled_media_type_still_releases_its_lock(self):
        self.user.comic_enabled = False
        self.user.save(update_fields=["comic_enabled"])
        service._queue_stale_refresh(self.user.id, "comic", "coming_soon", False)

        refresh_discover_rows(self.user.id, "comic", ["coming_soon"])

        self.assertIsNone(
            cache.get(
                service.row_refresh_lock_key(self.user.id, "comic", "coming_soon", False)
            )
        )


class TabRefreshCoalescingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username="tabs", password="x")

    @patch("app.discover.tab_cache.refresh_tab_cache")
    def test_a_copy_queued_behind_the_one_that_ran_does_nothing(self, rebuild):
        tab_cache.set_tab_cache(self.user.id, "movie", [])
        lock_key = tab_cache._refresh_lock_key(self.user.id, "movie", show_more=False)
        cache.set(lock_key, {"started_at": timezone.now().isoformat()})

        result = refresh_discover_tab_cache(self.user.id, "movie")

        self.assertEqual(result["reason"], "already_fresh")
        rebuild.assert_not_called()
        self.assertIsNone(cache.get(lock_key))

    @patch("app.discover.tab_cache.refresh_tab_cache", return_value=[])
    def test_a_forced_refresh_runs_even_when_the_tab_is_fresh(self, rebuild):
        tab_cache.set_tab_cache(self.user.id, "movie", [])

        refresh_discover_tab_cache(self.user.id, "movie", force=True)

        rebuild.assert_called_once()

    @patch("app.discover.tab_cache.refresh_tab_cache", return_value=[])
    def test_a_stale_tab_is_rebuilt(self, rebuild):
        refresh_discover_tab_cache(self.user.id, "movie")

        rebuild.assert_called_once()


class ComfortPoolBoundTests(TestCase):
    def test_a_library_pool_reads_a_bounded_number_of_entries(self):
        user = get_user_model().objects.create_user(username="lib", password="x")
        old = timezone.now() - timedelta(days=900)
        for index in range(8):
            item = Item.objects.create(
                media_id=str(index),
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title=f"Movie {index}",
            )
            Movie.objects.create(
                user=user,
                item=item,
                status=Status.COMPLETED.value,
                score=9 if index < 4 else None,
                end_date=old - timedelta(days=index),
            )

        with patch.object(service, "COMFORT_LIBRARY_ENTRY_LIMIT", 2):
            candidates = service._comfort_candidates(
                user,
                MediaTypes.MOVIE.value,
                row_key="comfort_rewatches",
                source_reason="Past favorite",
                older_than_days=365,
            )

        # Two rated and two unrated entries, not all eight.
        self.assertEqual(len(candidates), 4)
