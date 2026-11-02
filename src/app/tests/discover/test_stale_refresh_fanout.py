"""A refresh task's own tab render must not queue refreshes for other rows."""

from django.core.cache import cache
from django.test import TestCase

from app.discover import service


class StaleRefreshFanoutTests(TestCase):
    """Only page views queue stale-row refreshes."""

    def setUp(self):
        cache.clear()

    def _lock_key(self):
        return "discover:refresh:1:movie:top_picks_for_you:0"

    def test_page_render_queues_a_stale_row(self):
        service._queue_stale_refresh(1, "movie", "top_picks_for_you", False)

        self.assertTrue(cache.get(self._lock_key()))

    def test_refresh_task_render_does_not_fan_out(self):
        with service.stale_refresh_suppressed():
            service._queue_stale_refresh(1, "movie", "top_picks_for_you", False)

        self.assertIsNone(cache.get(self._lock_key()))
