"""A type-filtered history page must not rebuild each missing day on its own (#1873)."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from app import history_cache_reader
from app.models import Item, MediaTypes, Movie, Sources, Status


class TypedHistoryWindowQueryTests(TestCase):
    """Query count stays flat as the number of uncached days grows."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = get_user_model().objects.create_user(username="typed", password="x")
        self.base = timezone.now() - timedelta(days=60)

    def _add_days(self, count, start=0):
        for index in range(start, start + count):
            item = Item.objects.create(
                media_id=f"typed-movie-{index}",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title=f"Typed Movie {index}",
                image="http://example.com/m.jpg",
            )
            Movie.objects.create(
                item=item,
                user=self.user,
                status=Status.COMPLETED.value,
                end_date=self.base + timedelta(days=index),
            )

    def _typed_page(self):
        cache.clear()
        with CaptureQueriesContext(connection) as queries:
            days, total = history_cache_reader.get_cached_history_window(
                self.user,
                limit=50,
                offset=0,
                filters={"media_type": "movie"},
            )
        return days, total, len(queries)

    def test_query_count_does_not_grow_with_the_number_of_uncached_days(self):
        self._add_days(6)
        small_days, small_total, small_queries = self._typed_page()
        self._add_days(30, start=6)
        large_days, large_total, large_queries = self._typed_page()

        self.assertEqual((len(small_days), small_total), (6, 6))
        self.assertEqual((len(large_days), large_total), (36, 36))
        # Day-by-day builds cost a bundle of queries per day; the span-wide
        # load costs the same for 6 days as for 36.
        self.assertLessEqual(large_queries, small_queries + 2)

    def test_typed_days_hold_only_the_requested_type(self):
        self._add_days(4)

        days, _total, _queries = self._typed_page()

        entry_types = {
            entry["media_type"] for day in days for entry in day["entries"]
        }
        self.assertEqual(entry_types, {"movie"})
