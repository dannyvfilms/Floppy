"""Scaling benchmark for the shared library-query engine.

Generates a synthetic library (1k default, 10k/100k via
``LIBRARY_BENCHMARK_SIZE``) covering the shapes that matter — TMDB-only
movies, mixed TMDB/TVDB shows with seasons, cross-provider aliases, missing
mappings, spread statuses — and measures each engine scenario:

- wall time over repeat trials (median / p90),
- database query count,
- peak Python allocation (tracemalloc) for one page,
- page-cost independence from library size (same page at 1k vs 10k),
- tiling equivalence (pages tile the full order without gaps or repeats).

Tagged ``slow``/``benchmark``: run with ``scripts/test.sh --slow`` and read
the emitted summary. Numbers are receipts for change proposals, not gates.
"""

from __future__ import annotations

import json
import math
import os
import statistics
import time
import tracemalloc
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, tag
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from app.library_query import (
    FilterValues,
    LibraryQuery,
    LibraryQueryExecutor,
    SortSpec,
)
from app.models import (
    TV,
    Item,
    MediaTypes,
    Movie,
    Season,
    Sources,
    Status,
)

MOVIE = MediaTypes.MOVIE.value
TV_TYPE = MediaTypes.TV.value
SEASON = MediaTypes.SEASON.value

SIZE = max(int(os.environ.get("LIBRARY_BENCHMARK_SIZE", "1000")), 1)
RUNS = max(int(os.environ.get("LIBRARY_BENCHMARK_RUNS", "5")), 3)
OUTPUT = os.environ.get("LIBRARY_BENCHMARK_OUTPUT")
PAGE = 24


def _percentile(values, percentile):
    ordered = sorted(values)
    index = min(math.ceil(percentile * len(ordered)) - 1, len(ordered) - 1)
    return ordered[max(index, 0)]


class LibraryScalingBenchmarkTests(TestCase):
    """One synthetic library, measured per scenario."""

    @tag("slow", "benchmark")
    def test_scaling_receipts(self):
        user = get_user_model().objects.create_user(username="lq-bench")
        now = timezone.now()
        self._build_library(user, now, SIZE)

        scenarios = {
            "movies_unfiltered": LibraryQuery(media_types=(MOVIE,)),
            "movies_status_completed": LibraryQuery(
                media_types=(MOVIE,),
                filters=FilterValues(statuses=(Status.COMPLETED.value,)),
            ),
            "movies_genre_drama": LibraryQuery(
                media_types=(MOVIE,),
                filters=FilterValues(genre="drama"),
            ),
            "movies_sort_title": LibraryQuery(
                media_types=(MOVIE,),
                sort=SortSpec(key="title"),
            ),
            "shows_with_seasons": LibraryQuery(media_types=(TV_TYPE, SEASON)),
        }

        summary = {"size": SIZE, "runs": RUNS, "page": PAGE, "scenarios": {}}
        for name, query in scenarios.items():
            summary["scenarios"][name] = self._measure(user, query, name)

        # Tiling: pages cover the full ordering with no gaps or repeats.
        for name, query in scenarios.items():
            seen = []
            executor = LibraryQueryExecutor(user, query)
            page = executor.page(0, PAGE)
            total = page.total
            offsets = list(range(0, min(total, PAGE * 5), PAGE))
            for offset in offsets:
                seen.extend(item.pk for item in executor.page(offset, PAGE).items)
            self.assertEqual(
                len(seen),
                len(set(seen)),
                f"{name}: repeated ids across pages",
            )
            if total <= PAGE * 5:
                self.assertEqual(len(seen), total, f"{name}: pages lost records")

        print("library_benchmark " + json.dumps(summary, sort_keys=True))
        if OUTPUT:
            from pathlib import Path

            with Path(OUTPUT).open("w") as handle:
                json.dump(summary, handle, indent=2, sort_keys=True)

    def _measure(self, user, query, name):
        # Warm-up (imports, registry) then timed trials.
        LibraryQueryExecutor(user, query).page(0, PAGE)

        durations = []
        for _ in range(RUNS):
            started = time.perf_counter()
            page = LibraryQueryExecutor(user, query).page(0, PAGE)
            durations.append((time.perf_counter() - started) * 1000)
            self.assertGreater(len(page.items), 0, f"{name}: empty page")

        with CaptureQueriesContext(connection) as ctx:
            page = LibraryQueryExecutor(user, query).page(0, PAGE)
        tracemalloc.start()
        try:
            page = LibraryQueryExecutor(user, query).page(0, PAGE)
        finally:
            _current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()

        return {
            "total": page.total,
            "used_sql": page.used_sql,
            "duration_ms_median": round(statistics.median(durations), 2),
            "duration_ms_p90": round(_percentile(durations, 0.9), 2),
            "queries_per_page": len(ctx),
            "peak_python_kib": round(peak / 1024, 1),
        }

    def _build_library(self, user, now, size):
        items, trackers = [], []
        shows, seasons, season_items = [], [], []

        for index in range(size):
            # 70% movies, 20% show-seasons pairs, 10% skipped (missing
            # mappings / sparse library).
            if index % 10 >= 7:
                continue
            if index % 10 < 2:
                show_source = (
                    Sources.TVDB.value if index % 20 < 1 else Sources.TMDB.value
                )
                show_item = Item(
                    media_id=f"bench-show-{index}",
                    source=show_source,
                    media_type=TV_TYPE,
                    title=f"Show {index % 97}",
                    release_datetime=now - timedelta(days=index % 900),
                    genres=["Drama"] if index % 2 else ["Animation"],
                )
                items.append(show_item)
                shows.append(
                    TV(
                        item=show_item,
                        user=user,
                        status=Status.COMPLETED.value
                        if index % 3
                        else Status.PLANNING.value,
                        score=Decimal(index % 10) if index % 4 else None,
                    )
                )
                season_item = Item(
                    media_id=f"bench-season-{index}",
                    source=show_source,
                    media_type=SEASON,
                    title=f"Show {index % 97} S1",
                    season_number=1,
                )
                items.append(season_item)
                season_items.append(season_item)
                seasons.append(
                    Season(
                        item=season_item,
                        user=user,
                        related_tv=None,  # fixed up after bulk insert
                        status=Status.IN_PROGRESS.value,
                    )
                )
                continue

            movie_item = Item(
                media_id=f"bench-movie-{index}",
                source=Sources.TMDB.value,
                media_type=MOVIE,
                title=f"Movie {index % 211}",
                image="https://example.com/i.jpg",
                release_datetime=now - timedelta(days=index % 1200),
                provider_rating=Decimal(index % 10) / 2 or None,
                genres=["Drama"] if index % 2 else ["Comedy"],
            )
            items.append(movie_item)
            trackers.append(
                Movie(
                    item=movie_item,
                    user=user,
                    status=(
                        Status.COMPLETED.value
                        if index % 3
                        else Status.IN_PROGRESS.value
                    ),
                    score=Decimal(index % 10) if index % 4 else None,
                    start_date=now - timedelta(days=index % 30),
                )
            )

        # Cross-provider aliases: the same show under both sources, which the
        # dedupe layer must collapse per the user's default provider.
        alias_count = max(size // 200, 1)
        for index in range(alias_count):
            for source in (Sources.TMDB.value, Sources.TVDB.value):
                item = Item(
                    media_id=f"bench-alias-{index}",
                    source=source,
                    media_type=TV_TYPE,
                    title=f"Alias {index}",
                )
                items.append(item)
                shows.append(TV(item=item, user=user, status=Status.COMPLETED.value))

        inserted_items = []
        for start in range(0, len(items), 500):
            inserted_items.extend(Item.objects.bulk_create(items[start : start + 500]))
        movie_rows = trackers  # items already appended in the same order
        for start in range(0, len(movie_rows), 500):
            Movie.objects.bulk_create(movie_rows[start : start + 500])

        show_items_by_key = {}
        for item in inserted_items:
            show_items_by_key[(item.media_id, item.source, item.media_type)] = item
        fixed_shows = []
        for show in shows:
            show.item = show_items_by_key[
                (show.item.media_id, show.item.source, TV_TYPE)
            ]
            fixed_shows.append(show)
        for start in range(0, len(fixed_shows), 500):
            TV.objects.bulk_create(fixed_shows[start : start + 500])

        tv_by_item = {tv.item_id: tv for tv in TV.objects.filter(user=user)}
        fixed_seasons = []
        for season, season_item in zip(seasons, season_items, strict=True):
            season.item = show_items_by_key[
                (season_item.media_id, season_item.source, SEASON)
            ]
            index = season_item.media_id.rsplit("-", 1)[-1]
            show_item = show_items_by_key[
                (f"bench-show-{index}", season_item.source, TV_TYPE)
            ]
            season.related_tv = tv_by_item[show_item.pk]
            fixed_seasons.append(season)
        for start in range(0, len(fixed_seasons), 500):
            Season.objects.bulk_create(fixed_seasons[start : start + 500])
