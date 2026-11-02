"""Scaling evidence for the Trakt popularity reconcile.

This measures **Python allocation** with ``tracemalloc``, not container RSS.
It is relative evidence about the shape of the algorithm; only a Docker
capture can claim a memory figure for the container.

Two shapes are measured at each library size:

``hydrated``
    what the task used to do - ``list(tracked_items_queryset().iterator())``,
    every ``Item`` fully hydrated and held at once. Its peak grows with both
    library width and per-row payload, which is the point being demonstrated.

``projected``
    what the task does now - chunked scalar projections. Its peak is a
    function of the chunk, so it should stay roughly flat as the library
    grows.

``ru_maxrss`` is deliberately not used: it is a process high-water that never
decreases, so it cannot report a per-size peak from inside one test process.

Run with::

    scripts/test.sh --slow app.tests.test_trakt_popularity_benchmarks

Sizes and the per-row payload are configurable::

    TRAKT_RECONCILE_BENCHMARK_SIZES=500,1000
    TRAKT_RECONCILE_BENCHMARK_PAYLOAD_BYTES=8192
"""

import json
import os
import time
import tracemalloc

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, tag
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from app.models import Item, MediaTypes, Movie, Sources, Status
from app.services import trakt_popularity as trakt_popularity_service
from app.tasks_trakt import reconcile_trakt_popularity

# Production rows carry roughly 146 KiB of watch-provider JSON. Seeding that
# here would build a multi-gigabyte test database, so the default payload is
# far smaller and the report extrapolates instead of pretending otherwise.
PRODUCTION_ROW_PAYLOAD_BYTES = 146 * 1024
DEFAULT_PAYLOAD_BYTES = 8 * 1024
DEFAULT_SIZES = (500, 1000, 3000, 10000)


def _sizes():
    raw = os.environ.get("TRAKT_RECONCILE_BENCHMARK_SIZES")
    if not raw:
        return DEFAULT_SIZES
    return tuple(int(part) for part in raw.split(",") if part.strip())


def _payload_bytes():
    return int(
        os.environ.get(
            "TRAKT_RECONCILE_BENCHMARK_PAYLOAD_BYTES",
            DEFAULT_PAYLOAD_BYTES,
        ),
    )


@tag("slow", "benchmark")
class TraktPopularityReconcileScalingTests(TestCase):
    """Report how reconcile allocation scales with library width and payload."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="trakt-reconcile-benchmark",
            password="pw12345",
        )

    def _seed(self, count, payload_bytes):
        blob = "y" * payload_bytes
        now = timezone.now()
        items = [
            Item(
                media_id=str(media_id),
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                # bulk_create bypasses Item.save(), which is what normally
                # fills this in. Without it tracked_items_queryset() matches
                # nothing and the benchmark silently measures an empty library.
                library_media_type=MediaTypes.MOVIE.value,
                title=f"Movie {media_id}",
                image="https://example.com/movie.jpg",
                synopsis=blob,
                watch_providers={"US": {"flatrate": [{"provider_name": blob}]}},
                trakt_rating=8.0,
                trakt_rating_count=1200,
                trakt_popularity_fetched_at=now,
            )
            for media_id in range(count)
        ]
        Item.objects.bulk_create(items, batch_size=500)
        Movie.objects.bulk_create(
            [
                Movie(
                    item=item,
                    user=self.user,
                    status=Status.IN_PROGRESS.value,
                    progress=0,
                )
                for item in Item.objects.all().only("id")
            ],
            batch_size=500,
        )

    @staticmethod
    def _measure(callable_under_test):
        tracemalloc.start()
        tracemalloc.reset_peak()
        started = time.perf_counter()
        with CaptureQueriesContext(connection) as queries:
            callable_under_test()
        duration = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return {
            "peak_kib": round(peak / 1024),
            "duration_s": round(duration, 3),
            "queries": len(queries.captured_queries),
        }

    @staticmethod
    def _hydrated_control():
        # The pre-fix shape, kept only as a control so the report shows why
        # the old implementation grew rather than only that the new one is
        # smaller. Deliberately holds everything, exactly as the task did.
        return list(
            trakt_popularity_service.tracked_items_queryset().iterator(chunk_size=500),
        )

    def test_reconcile_allocation_scales_with_chunk_not_library(self):
        payload_bytes = _payload_bytes()
        report = {
            "payload_bytes_per_row": payload_bytes,
            "production_payload_bytes_per_row": PRODUCTION_ROW_PAYLOAD_BYTES,
            "sizes": {},
        }

        for size in _sizes():
            Movie.objects.all().delete()
            Item.objects.all().delete()
            self._seed(size, payload_bytes)

            hydrated = self._measure(self._hydrated_control)
            projected = self._measure(reconcile_trakt_popularity)
            report["sizes"][size] = {
                "hydrated": hydrated,
                "projected": projected,
                "peak_ratio": round(
                    hydrated["peak_kib"] / max(projected["peak_kib"], 1),
                    2,
                ),
            }

        print(json.dumps(report, indent=2))

        sizes = sorted(report["sizes"])
        smallest = report["sizes"][sizes[0]]["projected"]["peak_kib"]
        largest = report["sizes"][sizes[-1]]["projected"]["peak_kib"]
        growth = sizes[-1] / sizes[0]
        # Bounded means sub-linear, not constant: the id list still grows, and
        # it is ints. A generous factor keeps this an anti-regression gate
        # rather than a flaky exact-number assertion.
        self.assertLess(
            largest,
            smallest * growth,
            f"projected peak grew linearly with library size: {report['sizes']}",
        )
