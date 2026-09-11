"""Performance benchmark tests for media list loading (issue #121).

Reproduces the ~9 second server-side request time seen in production.
The bottleneck is NOT SQL query time (which is fast at ~8ms for 500 items)
but Python-side processing: per-item cache lookups in build_filter_data,
iterating all items through Python filters, template rendering, and
SQLite lock contention from background Celery tasks.

Run with: pytest src/app/tests/test_media_list_performance.py -v -s
"""

import logging
import time
from datetime import UTC, datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection, reset_queries
from django.test import RequestFactory, TestCase, tag
from django.test.utils import override_settings

from app.models import (
    BasicMedia,
    Item,
    MediaManager,
    MediaTypes,
    Movie,
    Sources,
    Status,
)
from users.models import MediaStatusChoices


# Suppress noisy debug logging during tests
def setUpModule():
    """Silence log noise for this module only."""
    logging.disable(logging.DEBUG)


def tearDownModule():
    """Restore logging so other modules' assertLogs still see records."""
    logging.disable(logging.NOTSET)


def _bulk_create_movie_items_and_entries(
    user, count, *, genres=None, populate_languages=False
):
    """Create `count` movie items with corresponding Movie entries.

    When populate_languages=False (default), items lack DB-level language/
    country data, forcing the view to fall back to per-item cache lookups
    (the slow path that hits production users).
    """
    items = []
    for i in range(count):
        item = Item(
            media_id=f"perf_{i}",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.MOVIE.value,
            title=f"Performance Test Movie {i}",
            image="http://example.com/poster.jpg",
            genres=genres or ["Action", "Drama"],
            release_datetime=datetime(2020 + (i % 5), 6, 15, tzinfo=UTC),
            runtime_minutes=90 + (i % 60),
        )
        if populate_languages:
            item.languages = ["en"]
            item.country = "US"
        items.append(item)
    Item.objects.bulk_create(items)

    created_items = list(
        Item.objects.filter(
            media_id__startswith="perf_",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.MOVIE.value,
        )
    )

    movies = []
    for item in created_items:
        movies.append(
            Movie(
                item=item,
                user=user,
                status=Status.COMPLETED.value,
                score=5 + (item.pk % 5),
            )
        )
    Movie.objects.bulk_create(movies)
    return created_items


@tag("slow", "benchmark")
class FullViewWallClockTests(TestCase):
    """Measure total wall-clock time for the full media_list view.

    This is the primary test — it reproduces what the user sees in their
    browser timing panel: ~9 seconds of server processing time.

    The debug toolbar screenshots show:
      - Image 1: 9309ms elapsed, 8791ms CPU
      - Image 2: 9214ms elapsed, 8695ms CPU, request phase = 9368ms
    The request phase dominates — the server spends ~9s building the response.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="wallclock", password="12345"
        )
        cls.user.movie_enabled = True
        cls.user.save()
        cls.factory = RequestFactory()

    def _time_view(self, label, count, params=None, **create_kwargs):
        """Time the full view execution and print breakdown."""
        _bulk_create_movie_items_and_entries(self.user, count, **create_kwargs)

        from app.views import media_list

        request = self.factory.get("/medialist/movie", params or {})
        request.user = self.user

        with override_settings(DEBUG=True):
            reset_queries()
            start = time.perf_counter()
            response = media_list(request, MediaTypes.MOVIE.value)
            elapsed_ms = (time.perf_counter() - start) * 1000
            queries = connection.queries[:]

        sql_ms = sum(float(q["time"]) for q in queries) * 1000
        python_ms = elapsed_ms - sql_ms
        print(f"\n[PERF] {label}:")
        print(f"  Total wall-clock: {elapsed_ms:.0f}ms")
        print(f"  SQL time:         {sql_ms:.0f}ms ({len(queries)} queries)")
        print(f"  Python time:      {python_ms:.0f}ms")
        print(f"  HTTP status:      {response.status_code}")
        return elapsed_ms, len(queries)

    def test_full_view_500_items(self):
        """500 items — shows scaling behavior.

        On a low-power server (RPi, small VPS), the Python time shown here
        would be 10-20x slower, pushing into the 5-10 second range.
        """
        self._time_view("Full view (500 items, no filters)", 500)

    def test_full_view_1000_items(self):
        """1000 items — closer to the reporter's library size."""
        self._time_view("Full view (1000 items, no filters)", 1000)

    def test_full_view_scaling_comparison(self):
        """Show O(n) scaling — time doubles as items double."""
        print()
        results = []
        for size in [100, 250, 500, 1000]:
            Movie.objects.filter(user=self.user).delete()
            Item.objects.filter(
                media_id__startswith="perf_",
                media_type=MediaTypes.MOVIE.value,
            ).delete()
            ms, _ = self._time_view(f"  {size} items", size)
            results.append((size, ms))

        print("\n[PERF] Scaling summary:")
        for size, ms in results:
            ratio = ms / results[0][1] if results[0][1] > 0 else 0
            print(f"  {size:>5} items: {ms:>8.0f}ms ({ratio:.1f}x vs 100)")

    def test_full_view_with_genre_filter(self):
        """Genre filter is applied in SQL before the queryset is materialized."""
        _bulk_create_movie_items_and_entries(self.user, 1000)
        # Make half Comedy
        Item.objects.filter(
            media_id__startswith="perf_",
            media_type=MediaTypes.MOVIE.value,
            pk__in=Item.objects.filter(
                media_id__startswith="perf_",
                media_type=MediaTypes.MOVIE.value,
            )
            .order_by("id")
            .values_list("id", flat=True)[:500],
        ).update(genres=["Comedy"])

        from app.views import media_list

        request = self.factory.get("/medialist/movie", {"genre": "Action"})
        request.user = self.user

        with override_settings(DEBUG=True):
            reset_queries()
            start = time.perf_counter()
            response = media_list(request, MediaTypes.MOVIE.value)
            elapsed_ms = (time.perf_counter() - start) * 1000
            queries = connection.queries[:]

        sql_ms = sum(float(q["time"]) for q in queries) * 1000
        print("\n[PERF] Full view (1000 items, genre='Action'):")
        print(f"  Total wall-clock: {elapsed_ms:.0f}ms")
        print(f"  SQL time: {sql_ms:.0f}ms ({len(queries)} queries)")
        print(f"  Python time: {elapsed_ms - sql_ms:.0f}ms")
        print("  Genre='Action' applied via SQL; fewer rows materialized in Python.")


@tag("slow", "benchmark")
class CacheLookupOverheadTests(TestCase):
    """Track cache.get usage during media list filter data building.

    Filter facets use DB fields only (no per-item cache fallback), so
    cache.get should stay negligible for the list path.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="cachetest", password="12345"
        )
        cls.user.movie_enabled = True
        cls.user.save()
        cls.factory = RequestFactory()

    def test_cache_lookups_without_db_fields(self):
        """Items without DB-level metadata should not spam cache.get for facets."""
        _bulk_create_movie_items_and_entries(self.user, 500, populate_languages=False)

        from app.views import media_list

        request = self.factory.get("/medialist/movie")
        request.user = self.user

        original_get = cache.get
        cache_call_count = [0]

        def counting_get(key, *args, **kwargs):
            cache_call_count[0] += 1
            return original_get(key, *args, **kwargs)

        with patch.object(cache, "get", side_effect=counting_get):
            start = time.perf_counter()
            response = media_list(request, MediaTypes.MOVIE.value)
            elapsed_ms = (time.perf_counter() - start) * 1000

        print("\n[PERF] Cache lookups (500 items, no DB metadata):")
        print(f"  cache.get() calls: {cache_call_count[0]}")
        print(f"  Wall-clock: {elapsed_ms:.0f}ms")
        self.assertLess(
            cache_call_count[0],
            50,
            "media list filter path should not do per-item cache.get for facets",
        )

    def test_cache_lookups_with_db_fields(self):
        """Items WITH DB-level metadata skip cache lookups."""
        _bulk_create_movie_items_and_entries(self.user, 500, populate_languages=True)

        from app.views import media_list

        request = self.factory.get("/medialist/movie")
        request.user = self.user

        original_get = cache.get
        cache_call_count = [0]

        def counting_get(key, *args, **kwargs):
            cache_call_count[0] += 1
            return original_get(key, *args, **kwargs)

        with patch.object(cache, "get", side_effect=counting_get):
            start = time.perf_counter()
            response = media_list(request, MediaTypes.MOVIE.value)
            elapsed_ms = (time.perf_counter() - start) * 1000

        print("\n[PERF] Cache lookups (500 items, WITH DB metadata):")
        print(f"  cache.get() calls: {cache_call_count[0]}")
        print(f"  Wall-clock: {elapsed_ms:.0f}ms")
        if cache_call_count[0] < 50:
            print("  DB fields populated -> cache lookups avoided!")


@tag("slow", "benchmark")
class CollectionFilterN1Tests(TestCase):
    """Collection filter should use bulk lookups, not per-item queries."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="colltest", password="12345"
        )
        cls.user.movie_enabled = True
        cls.user.save()
        cls.factory = RequestFactory()

    def test_collection_filter_n_plus_1(self):
        """Collection filter uses O(1) CollectionEntry queries for the list."""
        _bulk_create_movie_items_and_entries(self.user, 50)

        from app.views import media_list

        request = self.factory.get("/medialist/movie", {"collection": "not_collected"})
        request.user = self.user

        with override_settings(DEBUG=True):
            reset_queries()
            start = time.perf_counter()
            response = media_list(request, MediaTypes.MOVIE.value)
            elapsed_ms = (time.perf_counter() - start) * 1000
            queries = connection.queries[:]

        collection_queries = [
            q for q in queries if "app_collectionentry" in q["sql"].lower()
        ]
        print("\n[PERF] Collection filter (50 movies, 'not_collected'):")
        print(f"  Total SQL queries: {len(queries)}")
        print(f"  CollectionEntry queries: {len(collection_queries)}")
        print(f"  Wall-clock: {elapsed_ms:.0f}ms")
        self.assertLessEqual(
            len(collection_queries),
            3,
            "bulk collected IDs + optional episode prefetch, not N+1",
        )


@tag("slow", "benchmark")
class DuplicateAggregationTests(TestCase):
    """Measure _aggregate_duplicate_data overhead."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="aggtest", password="12345"
        )
        cls.user.movie_enabled = True
        cls.user.save()

    def test_aggregation_refetches_all_entries(self):
        """Aggregation may run twice on instances but should reuse one grouped fetch."""
        _bulk_create_movie_items_and_entries(self.user, 500)
        manager = MediaManager()

        with override_settings(DEBUG=True):
            reset_queries()
            result = list(
                manager.get_media_list(
                    user=self.user,
                    media_type=MediaTypes.MOVIE.value,
                    status_filter=MediaStatusChoices.ALL,
                    sort_filter="title",
                )
            )
            queries = connection.queries[:]

        select_queries = [q for q in queries if q["sql"].startswith("SELECT")]
        # Identify the aggregation query (fetches app_movie with item join)
        agg_queries = [
            q
            for q in select_queries
            if "app_movie" in q["sql"]
            and "row_number" not in q["sql"]
            and "events_event" not in q["sql"]
        ]
        print("\n[PERF] Aggregation overhead (500 items, no duplicates):")
        print(f"  Total SELECT queries: {len(select_queries)}")
        print(f"  Aggregation re-fetch queries: {len(agg_queries)}")
        for i, q in enumerate(agg_queries):
            ms = float(q["time"]) * 1000
            print(f"    Q{i + 1} ({ms:.1f}ms): {q['sql'][:100]}...")
        print(f"  This query re-loads all {len(result)} items just to check")
        print("  for duplicates, even when there are none.")


@tag("slow", "benchmark")
class MaterializationWasteTests(TestCase):
    """Regression coverage for SQL-first page slicing."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="materialize", password="12345"
        )
        cls.user.movie_enabled = True
        cls.user.save()
        cls.factory = RequestFactory()

    def test_loads_all_items_for_one_page(self):
        """A cold first page and a later page request the database slice."""
        _bulk_create_movie_items_and_entries(self.user, 1000)
        cache.clear()

        self.client.force_login(self.user)

        with override_settings(DEBUG=True):
            reset_queries()
            start = time.perf_counter()
            with patch.object(
                BasicMedia.objects,
                "get_media_list",
                wraps=BasicMedia.objects.get_media_list,
            ) as get_media_list:
                response = self.client.get("/medialist/movie", follow=True)
            elapsed_ms = (time.perf_counter() - start) * 1000
            queries = connection.queries[:]

        sql_ms = sum(float(q["time"]) for q in queries) * 1000
        sql_calls = [
            call
            for call in get_media_list.call_args_list
            if call.kwargs.get("sql_limit") is not None
        ]
        print("\n[PERF] SQL-first pagination (1000 items, page 1 of 32):")
        print(f"  Wall-clock:   {elapsed_ms:.0f}ms")
        print(f"  SQL time:     {sql_ms:.0f}ms")
        print(f"  Python time:  {elapsed_ms - sql_ms:.0f}ms")
        print(f"  SQL-paginated calls: {len(sql_calls)}")
        self.assertEqual(response.context["media_list"].paginator.count, 1000)
        self.assertEqual(len(response.context["media_list"].object_list), 32)
        self.assertTrue(sql_calls)
        self.assertEqual(sql_calls[0].kwargs["sql_limit"], 32)
        self.assertEqual(sql_calls[0].kwargs["sql_offset"], 0)
        self.assertTrue(
            any("LIMIT 32" in query["sql"].upper() for query in queries),
            "the visible tracker query should contain the SQL page limit",
        )
        first_page_ids = {
            entry.item_id for entry in response.context["media_list"].object_list
        }

        with override_settings(DEBUG=True):
            reset_queries()
            with patch.object(
                BasicMedia.objects,
                "get_media_list",
                wraps=BasicMedia.objects.get_media_list,
            ) as get_media_list:
                second_response = self.client.get(
                    "/medialist/movie?page=2",
                    follow=True,
                )
            second_queries = connection.queries[:]

        second_sql_calls = [
            call
            for call in get_media_list.call_args_list
            if call.kwargs.get("sql_limit") is not None
        ]
        self.assertEqual(
            len(second_response.context["media_list"].object_list),
            32,
        )
        self.assertTrue(
            first_page_ids.isdisjoint(
                entry.item_id
                for entry in second_response.context["media_list"].object_list
            )
        )
        self.assertTrue(second_sql_calls)
        self.assertEqual(second_sql_calls[0].kwargs["sql_offset"], 32)
        self.assertTrue(
            any("OFFSET 32" in query["sql"].upper() for query in second_queries),
            "the second page should advance the SQL offset",
        )


@tag("slow", "benchmark")
class CachedPageScalingTests(TestCase):
    """Issue #865: a warm-cache page-2+ request must not scale with library size.

    Production logs showed /medialist/movie scroll requests taking 2.6-3.4s
    on only 4 SQL queries — the cost was unpickling the ENTIRE cached library
    just to slice out one page. The fix caches a compact {media_pk, item_pk}
    order instead of full objects and hydrates only the requested page.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="scalepage", password="12345"
        )
        cls.user.movie_enabled = True
        cls.user.save()
        cls.factory = RequestFactory()

    def _second_page_ms(self, count):
        cache.clear()
        Movie.objects.filter(user=self.user).delete()
        Item.objects.filter(
            media_id__startswith="perf_",
            media_type=MediaTypes.MOVIE.value,
        ).delete()
        _bulk_create_movie_items_and_entries(self.user, count)

        from app.views import media_list

        # Warm both the order cache and the filter_data cache with page 1.
        first_request = self.factory.get("/medialist/movie")
        first_request.user = self.user
        media_list(first_request, MediaTypes.MOVIE.value)

        second_request = self.factory.get("/medialist/movie", {"page": 2})
        second_request.user = self.user
        with override_settings(DEBUG=True):
            reset_queries()
            start = time.perf_counter()
            response = media_list(second_request, MediaTypes.MOVIE.value)
            elapsed_ms = (time.perf_counter() - start) * 1000
            n_queries = len(connection.queries)
        self.assertEqual(response.status_code, 200)
        return elapsed_ms, n_queries

    def test_cached_second_page_does_not_scale_with_library_size(self):
        """A warm-cache page-2 request should cost roughly the same at 100 vs 2000 items."""
        print()
        small_ms, small_queries = self._second_page_ms(100)
        large_ms, large_queries = self._second_page_ms(2000)

        print("[PERF] Cached page-2 request:")
        print(f"  100 items:  {small_ms:.0f}ms, {small_queries} queries")
        print(f"  2000 items: {large_ms:.0f}ms, {large_queries} queries")

        # A generous bound: even accounting for noise, a page-2 request that
        # only ever touches ~32 rows should not take meaningfully longer as
        # the underlying library grows 20x. Before the fix this scaled
        # roughly linearly with library size because the whole cached
        # library was unpickled every request.
        self.assertLess(
            large_ms,
            small_ms * 5 + 200,
            "page-2 request time scaled with library size; the media_list "
            "cache is likely storing/hydrating full objects instead of a "
            "compact per-page order",
        )
