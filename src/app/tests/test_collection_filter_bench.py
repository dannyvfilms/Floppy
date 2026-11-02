"""Collection rating/completeness filter cost on a large library (SURFACE-08).

Slow benchmark: builds ~5k collection entries (movies plus shows with many
episodes), requests each filter variant and records queries, CPU, peak Python
memory and a digest of the result so before/after runs can be diffed. Set
``COLLECTION_BENCH_OUT`` to write the JSON report.
"""

import hashlib
import json
import os
import time
import tracemalloc
from pathlib import Path

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, tag
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from app.models import (
    TV,
    CollectionEntry,
    Item,
    MediaTypes,
    Movie,
    Sources,
    Status,
)

MOVIES = 3500
SHOWS = 400
SEASONS = 4
EPISODES = 12


def _digest(values):
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()[:16]


@tag("slow", "benchmark")
class CollectionFilterBenchmark(TestCase):
    """Measure the filtered collection page; results must not change."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="bench", password="x")
        movies = Item.objects.bulk_create(
            Item(
                media_id=f"m{n}",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title=f"Movie {n:05d}",
                image="x",
            )
            for n in range(MOVIES)
        )
        shows = Item.objects.bulk_create(
            Item(
                media_id=f"s{n}",
                source=Sources.TMDB.value,
                media_type=MediaTypes.TV.value,
                title=f"Show {n:05d}",
                image="x",
            )
            for n in range(SHOWS)
        )
        seasons = []
        episodes = []
        for n in range(SHOWS):
            for season in range(1, SEASONS + 1):
                seasons.append(
                    Item(
                        media_id=f"s{n}",
                        source=Sources.TMDB.value,
                        media_type=MediaTypes.SEASON.value,
                        season_number=season,
                        title=f"Show {n:05d}",
                        image="x",
                    ),
                )
                episodes.extend(
                    Item(
                        media_id=f"s{n}",
                        source=Sources.TMDB.value,
                        media_type=MediaTypes.EPISODE.value,
                        season_number=season,
                        episode_number=ep,
                        title=f"Show {n:05d}",
                        image="x",
                    )
                    for ep in range(1, EPISODES + 1)
                )
        seasons = Item.objects.bulk_create(seasons)
        episodes = Item.objects.bulk_create(episodes)

        entries = [CollectionEntry(user=cls.user, item=item) for item in movies]
        entries += [CollectionEntry(user=cls.user, item=item) for item in shows]
        # Mix of ownership shapes: whole show, some seasons, some episodes, none.
        for index, season in enumerate(seasons):
            if index % 4 == 1:
                entries.append(CollectionEntry(user=cls.user, item=season))
        for index, episode in enumerate(episodes):
            if index % 40 == 7:
                entries.append(CollectionEntry(user=cls.user, item=episode))
        entries += [
            CollectionEntry(user=cls.user, item=season)
            for index, season in enumerate(seasons)
            if (index % 4 == 0 and index % 16 != 0)
            or ((index // SEASONS) % 10 == 0 and index % 4 != 1)
        ]
        CollectionEntry.objects.bulk_create(entries)

        Movie.objects.bulk_create(
            Movie(
                item=item,
                user=cls.user,
                status=Status.COMPLETED.value,
                score=8 if n % 3 == 0 else None,
            )
            for n, item in enumerate(movies)
        )
        TV.objects.bulk_create(
            TV(
                item=item,
                user=cls.user,
                status=Status.COMPLETED.value,
                score=7 if n % 2 == 0 else None,
            )
            for n, item in enumerate(shows)
        )

    def _run(self, params):
        self.client.force_login(self.user)
        url = reverse("collection_list")
        tracemalloc.start()
        started = time.process_time()
        wall = time.perf_counter()
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(url, params)
        cpu = time.process_time() - started
        wall = time.perf_counter() - wall
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        self.assertEqual(response.status_code, 200)
        page = response.context["collection_entries"]
        ids = [entry.id for entry in page.object_list]
        return {
            "queries": len(ctx),
            "sql_seconds": round(sum(float(q["time"]) for q in ctx.captured_queries), 4),
            "cpu_seconds": round(cpu, 4),
            "wall_seconds": round(wall, 4),
            "peak_py_mb": round(peak / 1e6, 1),
            "count": page.paginator.count,
            "pages": page.paginator.num_pages,
            "page_ids_digest": _digest(ids),
            "page_len": len(ids),
        }

    def test_filter_variants(self):
        variants = {
            "all": {},
            "rated": {"rating": "rated"},
            "not_rated": {"rating": "not_rated"},
            "rated_movie": {"rating": "rated", "type": "movie"},
            "partial": {"completeness": "partial"},
            "full": {"completeness": "full"},
            "partial_tv": {"completeness": "partial", "type": "tv"},
            "partial_unrated_deep": {
                "completeness": "partial",
                "rating": "not_rated",
                "page": "3",
            },
            "rated_deep": {"rating": "rated", "page": "40"},
        }
        report = {}
        for name, params in variants.items():
            self._run(params)  # warm
            report[name] = self._run(params)
        for name in ("rated", "not_rated", "partial", "full"):
            self.assertGreater(report[name]["count"], 0, name)
        out = os.environ.get("COLLECTION_BENCH_OUT")
        if out:
            with Path(out).open("w") as handle:
                json.dump(report, handle, indent=1, sort_keys=True)
