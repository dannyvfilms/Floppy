"""The History day index must ask the database for distinct days, not rows.

Models with a default ordering (every historical table, Episode, Movie, ...)
add their ORDER BY columns to ``SELECT DISTINCT``, so the "distinct day" query
returned one row per play. A cold index build then streamed millions of rows
into Python: 458 s for 7.2M ``HistoricalMusic`` rows alone.
"""

import re

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from app.history_cache_index import build_history_index


class HistoryIndexDistinctDaysTests(TestCase):
    """Every distinct-day query selects only the day and is unordered."""

    def test_distinct_day_queries_select_only_the_day(self):
        user = get_user_model().objects.create_user(
            username="index-distinct",
            password="12345",
        )
        with CaptureQueriesContext(connection) as queries:
            build_history_index(user, logging_style_override="repeats")

        distinct = [
            " ".join(query["sql"].split())
            for query in queries.captured_queries
            if query["sql"].startswith("SELECT DISTINCT")
        ]
        self.assertTrue(distinct)
        for sql in distinct:
            select_list = sql.split(" FROM ", 1)[0]
            self.assertEqual(
                len(re.findall(r" AS ", select_list)),
                1,
                f"distinct day query selects more than the day: {sql}",
            )
            self.assertNotIn("ORDER BY", sql)


class HistoryIndexSharedScanTests(TestCase):
    """Refreshing both styles of one save scans the shared types once."""

    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="index-shared",
            password="12345",
        )

    def _build(self, style, eras):
        with CaptureQueriesContext(connection) as queries:
            days = build_history_index(
                self.user, logging_style_override=style, memo_eras=eras,
            )
        distinct = sum(
            q["sql"].startswith("SELECT DISTINCT") for q in queries.captured_queries
        )
        return days, distinct

    def test_second_style_reuses_shared_scan_and_matches_unmemoized(self):
        eras = ("era-a", "era-b")
        _, first = self._build("sessions", eras)
        repeats, second = self._build("repeats", eras)
        plain, plain_count = self._build("repeats", None)

        self.assertLess(second, first)
        self.assertLess(second, plain_count)
        self.assertEqual(repeats, plain)

    def test_changed_era_rebuilds_shared_scan(self):
        _, first = self._build("sessions", ("era-a", "era-b"))
        _, again = self._build("sessions", ("era-a2", "era-b"))
        self.assertEqual(again, first)
