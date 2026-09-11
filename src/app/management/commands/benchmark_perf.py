"""Management command to benchmark performance of key endpoints.

Run before and after optimizations to measure improvement:
    python manage.py benchmark_perf --username alice
    python manage.py benchmark_perf --username alice --verbose
"""

import resource
import statistics
import sys
import time
from unittest.mock import patch

from django import conf
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, reset_queries
from django.db.models import Model
from django.test import Client

ENDPOINTS = [
    ("GET", "/settings/home-screen"),
    ("GET", "/"),
    ("GET", "/home/rest/"),
    ("GET", "/medialist/tv"),
    ("GET", "/medialist/season"),
    ("GET", "/medialist/anime"),
    ("GET", "/medialist/movie"),
    ("GET", "/medialist/game"),
    ("GET", "/medialist/book"),
    ("GET", "/medialist/manga"),
    ("GET", "/medialist/music"),
    ("GET", "/medialist/podcast"),
    ("GET", "/statistics"),
    ("GET", "/history"),
    ("GET", "/discover"),
    ("GET", "/calendar"),
    ("GET", "/lists"),
    ("GET", "/health/"),
]

# medialist paths whose "scroll" (pagination) requests we also benchmark
# separately from first-load, matching how issue #865 was reported: a slow
# first render followed by additional slow requests while scrolling further
# pages of the same list.
MEDIALIST_SCROLL_PATHS = [
    "/medialist/tv",
    "/medialist/movie",
]
SCROLL_PAGES = 3

RUNS = 3


class Command(BaseCommand):
    """Command."""

    help = "Benchmark response time and query count for key slow endpoints."

    def add_arguments(self, parser):
        """Register this command's command-line options."""
        parser.add_argument(
            "--username",
            required=True,
            help="Username to authenticate as for the benchmark requests.",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print individual SQL queries for each endpoint.",
        )
        parser.add_argument(
            "--runs",
            type=int,
            default=RUNS,
            help=f"Number of times to hit each endpoint (median is reported). Default: {RUNS}.",
        )

    def handle(self, *args, **options):
        """Benchmark response time and query count for key slow endpoints."""
        user_model = get_user_model()
        username = options["username"]
        try:
            user = user_model.objects.get(username=username)
        except user_model.DoesNotExist:
            msg = f"user_model '{username}' not found."
            raise CommandError(msg) from None

        # Enable query logging and allow the test client's default host.
        original_debug = conf.settings.DEBUG
        original_allowed_hosts = conf.settings.ALLOWED_HOSTS
        conf.settings.DEBUG = True
        conf.settings.ALLOWED_HOSTS = [
            *list(original_allowed_hosts),
            "testserver",
            "localhost",
        ]

        client = Client()
        client.force_login(user)

        runs = options["runs"]
        verbose = options["verbose"]

        def rss_mb():
            value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if sys.platform == "darwin":
                value /= 1024 * 1024
            else:
                value /= 1024
            return value

        col_w = [32, 9, 15, 16, 14, 12]
        header = (
            f"{'Endpoint':<{col_w[0]}} | {'Queries':>{col_w[1]}} | "
            f"{'SQL time (ms)':>{col_w[2]}} | {'Python (ms)':>{col_w[3]}} | "
            f"{'Wall time (ms)':>{col_w[4]}} | {'Hydrated':>{col_w[5]}} | RSS Δ (MB)"
        )
        divider = "-" * len(header)

        self.stdout.write("")
        self.stdout.write(header)
        self.stdout.write(divider)

        for method, path in ENDPOINTS:
            wall_times = []
            query_counts = []
            sql_times = []
            python_times = []
            last_queries = []
            hydrated_counts = []
            rss_deltas = []

            for _ in range(runs):
                reset_queries()
                hydrated_objects = 0
                original_from_db = Model.from_db.__func__

                def counted_from_db(
                    cls,
                    db,
                    field_names,
                    values,
                    original_from_db=original_from_db,
                ):
                    nonlocal hydrated_objects
                    if cls._meta.app_label in {"app", "lists"}:
                        hydrated_objects += 1
                    return original_from_db(cls, db, field_names, values)

                rss_before_mb = rss_mb()
                with patch.object(Model, "from_db", classmethod(counted_from_db)):
                    t0 = time.perf_counter()
                    if method == "GET":
                        client.get(path)
                    else:
                        client.post(path)
                wall_ms = (time.perf_counter() - t0) * 1000
                captured = list(connection.queries)
                sql_ms = sum(float(q["time"]) * 1000 for q in captured)
                wall_times.append(wall_ms)
                query_counts.append(len(captured))
                sql_times.append(sql_ms)
                python_times.append(max(wall_ms - sql_ms, 0))
                hydrated_counts.append(hydrated_objects)
                rss_deltas.append(max(rss_mb() - rss_before_mb, 0))
                last_queries = captured

            label = f"{method} {path}"
            q_median = int(statistics.median(query_counts))
            sql_median = statistics.median(sql_times)
            python_median = statistics.median(python_times)
            wall_median = statistics.median(wall_times)
            hydrated_median = int(statistics.median(hydrated_counts))
            rss_delta_median = statistics.median(rss_deltas)

            self.stdout.write(
                f"{label:<{col_w[0]}} | {q_median:>{col_w[1]}} | "
                f"{sql_median:>{col_w[2]}.1f} | {python_median:>{col_w[3]}.1f} | "
                f"{wall_median:>{col_w[4]}.1f} | {hydrated_median:>{col_w[5]}} | "
                f"{rss_delta_median:.2f}"
            )

            if verbose and last_queries:
                self.stdout.write("")
                for i, q in enumerate(last_queries, 1):
                    ms = float(q["time"]) * 1000
                    self.stdout.write(f"  [{i:03d}] {ms:6.1f}ms  {q['sql'][:120]}")
                self.stdout.write("")

        self.stdout.write(divider)
        self.stdout.write(
            f"(median of {runs} runs per endpoint; first run warms Django caches)"
        )
        self.stdout.write("")

        # Reproduce the issue #865 report: a cold first load followed by
        # scrolling through several more pages of the same list. Each row
        # here is ONE request (not a median), in request order, so a
        # regression that only shows up after the cache warms (or only on
        # page >= 2) is visible instead of averaged away.
        if MEDIALIST_SCROLL_PATHS:
            self.stdout.write("Scroll reproduction (issue #865): cold load + N page requests")
            self.stdout.write(divider)
            for path in MEDIALIST_SCROLL_PATHS:
                for page in range(1, SCROLL_PAGES + 2):
                    reset_queries()
                    t0 = time.perf_counter()
                    client.get(path, {"page": page} if page > 1 else {})
                    wall_ms = (time.perf_counter() - t0) * 1000
                    n_queries = len(connection.queries)
                    label = f"{path} page={page}" + (" (first load)" if page == 1 else "")
                    self.stdout.write(
                        f"{label:<{col_w[0]}} | {n_queries:>{col_w[1]}} | "
                        f"{'':>{col_w[2]}} | {'':>{col_w[3]}} | "
                        f"{wall_ms:>{col_w[4]}.1f} | {'':>{col_w[5]}} |"
                    )
            self.stdout.write(divider)
            self.stdout.write("")

        conf.settings.DEBUG = original_debug
        conf.settings.ALLOWED_HOSTS = original_allowed_hosts
