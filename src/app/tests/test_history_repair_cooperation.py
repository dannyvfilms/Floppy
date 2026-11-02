"""History coverage repair must stop between days when someone is browsing."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from app import history_cache_reader
from app.interactive_requests import mark_interactive_request

MISSING_DAYS = [f"2026-01-{day:02d}" for day in range(1, 11)]


@patch.object(
    history_cache_reader, "_missing_history_day_keys", return_value=MISSING_DAYS
)
@patch.object(history_cache_reader, "build_history_index", return_value=MISSING_DAYS)
@patch.object(history_cache_reader, "_build_and_cache_history_day", return_value={})
class HistoryRepairCooperationTests(TestCase):
    """A repair batch yields to page loads instead of running to the end."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="repair")

    def setUp(self):
        cache.clear()

    def test_repair_stops_after_one_day_while_browsing(self, build_day, *_mocks):
        mark_interactive_request()

        result = history_cache_reader.repair_history_day_cache_coverage(
            self.user.id, batch_size=len(MISSING_DAYS)
        )

        self.assertEqual(build_day.call_count, 1)
        self.assertEqual(result["remaining"], len(MISSING_DAYS) - 1)

    def test_repair_runs_the_whole_batch_when_idle(self, build_day, *_mocks):
        result = history_cache_reader.repair_history_day_cache_coverage(
            self.user.id, batch_size=len(MISSING_DAYS)
        )

        self.assertEqual(build_day.call_count, len(MISSING_DAYS))
        self.assertEqual(result["remaining"], 0)
