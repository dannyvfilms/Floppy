"""Statistics requests must not rebuild or unpickle more than they show."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from app import statistics_cache, statistics_sync, statistics_views


class StatisticsRequestCostTests(TestCase):
    """Pollers read snapshot metadata; the talent section is rebuilt off-request."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="statscost")

    def setUp(self):
        cache.clear()
        self.client.force_login(self.user)

    def tearDown(self):
        # Tests here stub out the refresh task, so a queued-refresh marker
        # stays behind; rolled-back test users reuse ids, so drop it.
        cache.clear()

    def test_cache_status_reads_metadata_not_the_snapshot(self):
        statistics_sync.publish_snapshot(
            self.user.id, "Last 7 Days", {"hours_per_media_type": {}}, generation=0
        )

        with patch.object(
            statistics_sync, "load_snapshot", wraps=statistics_sync.load_snapshot
        ) as full_load:
            response = self.client.get(
                reverse("cache_status"),
                {"cache_type": "statistics", "range_name": "Last 7 Days"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["exists"])
        full_load.assert_not_called()

    def test_snapshot_metadata_survives_a_cache_flush(self):
        statistics_sync.publish_snapshot(
            self.user.id, "Last 7 Days", {"hours_per_media_type": {}}, generation=3
        )
        cache.clear()

        meta = statistics_sync.load_snapshot_meta(self.user.id, "Last 7 Days")

        self.assertEqual(meta["generation"], 3)
        self.assertIsNotNone(meta["built_at"])

    def test_talent_section_serves_last_copy_after_a_data_change(self):
        url = reverse("statistics_talent_fragment") + "?start-date=all&end-date=all"
        self.assertEqual(self.client.get(url).status_code, 200)

        # A play bumps the history version, so the exact section key misses.
        statistics_cache.invalidate_statistics_cache(self.user.id)
        with (
            patch.object(
                statistics_views,
                "_build_talent_fragment_context",
                wraps=statistics_views._build_talent_fragment_context,
            ) as build,
            patch(
                "app.tasks_interactive.refresh_statistics_talent_fragment_task.delay"
            ) as queued,
        ):
            response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        build.assert_not_called()
        queued.assert_called_once()

    def test_plays_during_a_queued_rebuild_do_not_queue_more(self):
        url = reverse("statistics_talent_fragment") + "?start-date=all&end-date=all"
        self.assertEqual(self.client.get(url).status_code, 200)

        with patch(
            "app.tasks_interactive.refresh_statistics_talent_fragment_task.delay"
        ) as queued:
            # Two plays, each a new history version, before the rebuild runs.
            for _ in range(2):
                statistics_cache.invalidate_statistics_cache(self.user.id)
                self.assertEqual(self.client.get(url).status_code, 200)

        queued.assert_called_once()
