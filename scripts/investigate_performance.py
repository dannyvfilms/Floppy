"""Disposable local Trakt/foreground contention experiment.

Run with `uv run --no-sync python scripts/investigate_performance.py --entries 200`.
Requires redis-server. Uses real Redis, HTTP, SQLite and a selectable Celery pool;
Gunicorn, storage and resource-quota behavior require the Docker benchmark.
Never reads the application's database or uses its broker/cache services.
"""

# ruff: noqa: INP001 -- standalone command, not a package

import argparse
import contextlib
import copy
import faulthandler
import gc
import json
import logging
import multiprocessing
import os
import random
import resource
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import tracemalloc
from collections import Counter
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

MISSING_SEASONS = (21, 1986)


def percentile(values, fraction):
    """Return a nearest-rank percentile from a nonempty sample."""
    import math

    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def main():
    """Run isolated workloads and save measured request/import results."""
    faulthandler.dump_traceback_later(90, repeat=True)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entries", type=int, default=200)
    parser.add_argument("--provider-delay-ms", type=float, default=2)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--sample-through-import", action="store_true", help="Continue foreground sampling through persistence, up to 10000 request records per phase")
    parser.add_argument("--sample-interval-seconds", type=float, default=1)
    parser.add_argument("--followup-probe-interval-seconds", type=float, default=90, help="Allow the production 30-second browser-priority marker to expire between Home probes")
    parser.add_argument("--profile-home", action="store_true", help="Trace Home allocations; reported Home timings include profiler overhead")
    parser.add_argument("--home-diagnostics", action="store_true", help="Capture bounded candidate/graph counts and serialized Home cache bytes")
    parser.add_argument("--control-disable-compact-episodes", action="store_true", help="Disposable comparison with full historical episode graphs")
    parser.add_argument("--dedupe-scaling", action="store_true", help="Measure indexed 1k/5k/10k/80849 temporal histories in three insertion orders")
    parser.add_argument("--scenarios", nargs="+", choices=("success", "missing", "primary_metadata_skipped"), default=["success", "missing", "primary_metadata_skipped"])
    parser.add_argument("--cache-delay-ms", type=float, default=0)
    parser.add_argument("--database-delay-ms", type=float, default=0)
    parser.add_argument("--broker-delay-ms", type=float, default=0)
    parser.add_argument("--worker-concurrency", type=int, choices=(1, 2), default=2)
    parser.add_argument("--worker-pool", choices=("threads", "prefork"), default="threads")
    parser.add_argument("--control-disable-negative", action="store_true", help="Reproduce repeated absent-season requests; disposable harness only")
    parser.add_argument("--control-disable-memos", action="store_true", help="Clear import-local metadata/Item memos before each lookup")
    parser.add_argument("--control-progress-every-row", action="store_true", help="Reproduce one progress cache write per report")
    parser.add_argument("--separate-redis", action="store_true")
    parser.add_argument("--sqlite-contention", action="store_true", help="Enable production signal receivers, bulk-import scope, Statistics and foreground saves")
    parser.add_argument("--sqlite-journal", choices=("DELETE", "WAL"), default="DELETE")
    parser.add_argument("--sqlite-busy-timeout-ms", type=int, default=5000)
    parser.add_argument("--statistics-drain-seconds", type=float, default=300)
    parser.add_argument("--control-disable-statistics-coordination", action="store_true", help="Disposable comparison: disable import coalescing and Statistics import/browser priority guards")
    parser.add_argument("--drain-enrichment", action="store_true", help="After sampling, execute real queued follow-up tasks against the local provider stub")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    max_entries = 200000
    if not 1 <= args.entries <= max_entries or args.samples < 1 or min(args.provider_delay_ms, args.cache_delay_ms, args.database_delay_ms, args.broker_delay_ms) < 0:
        parser.error("entries must be 1..200000, samples positive, delay nonnegative")
    if args.sample_interval_seconds < 0:
        parser.error("sampling interval must be nonnegative")
    if args.followup_probe_interval_seconds <= 0:
        parser.error("follow-up probe interval must be positive")
    if args.sqlite_busy_timeout_ms < 0 or args.statistics_drain_seconds <= 0:
        parser.error("SQLite timeout must be nonnegative and Statistics drain limit positive")
    if args.drain_enrichment and not args.sqlite_contention:
        parser.error("--drain-enrichment requires --sqlite-contention")
    if args.output is None:
        args.output = Path(tempfile.mkdtemp(prefix="floppy-results-")) / "measurements.json"
    redis_binary = shutil.which("redis-server")
    if not redis_binary:
        parser.error("redis-server is required")

    with tempfile.TemporaryDirectory(prefix="floppy-investigate-", dir="/tmp") as scratch, contextlib.ExitStack() as stack:
        root = Path(scratch)
        sockets = []
        for name in ("cache", "broker") if args.separate_redis else ("cache",):
            socket = root / f"{name}.sock"
            process = subprocess.Popen(  # noqa: S603 -- resolved installed binary, fixed flags
                [redis_binary, "--port", "0", "--unixsocket", str(socket), "--save", "", "--appendonly", "no"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            def stop(process=process):
                process.terminate()
                process.wait(timeout=10)
            stack.callback(stop)
            sockets.append(socket)
            deadline = time.monotonic() + 10
            while not socket.exists():
                if process.poll() is not None or time.monotonic() > deadline:
                    message = "Disposable Redis did not start"
                    raise RuntimeError(message)
                time.sleep(0.01)

        # Set these before Django import; all writable state belongs to scratch.
        os.environ.update(
            DJANGO_SETTINGS_MODULE="config.test_settings", SECRET=secrets.token_urlsafe(),
            FLOPPY_TEST_FAST_DB="1", LOG_DIR=str(root / "logs"),
            FLOPPY_DB_PATH=str(root / "unused.sqlite3"),
            DB_HOST="",
            REDIS_URL=f"unix://{sockets[0]}?db=0",
            CELERY_BROKER_URL=f"redis+socket://{sockets[-1]}?virtual_host=1",
        )
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
        import django
        django.setup()
        if args.dedupe_scaling:
            from app.fork_services_play_dedupe import PlayTimes

            class CountedDateTime(datetime):
                comparisons = 0

                def __sub__(self, other):
                    type(self).comparisons += 1
                    return super().__sub__(other)

            measurements = []
            for size in (1000, 5000, 10000, 80849):
                for order in ("chronological", "reverse", "shuffled"):
                    indexes = list(range(size))
                    if order == "reverse":
                        indexes.reverse()
                    elif order == "shuffled":
                        random.Random(642).shuffle(indexes)  # noqa: S311 -- deterministic fixture
                    times = PlayTimes()
                    anchor = CountedDateTime(1980, 1, 1, tzinfo=UTC)
                    CountedDateTime.comparisons = 0
                    cpu_started = time.thread_time()
                    started = time.perf_counter()
                    for index in indexes:
                        candidate = anchor + timedelta(hours=4 * index)
                        if times.is_duplicate("same", candidate):
                            message = "Temporal fixture lost a distinct watch"
                            raise RuntimeError(message)
                        times.add("same", candidate, 30)
                    measurements.append({"entries": size, "order": order,
                                         "wall_ms": (time.perf_counter() - started) * 1000,
                                         "cpu_ms": (time.thread_time() - cpu_started) * 1000,
                                         "window_comparisons": CountedDateTime.comparisons,
                                         "retained": len(times.times_for("same"))})
            args.output.write_text(json.dumps({"completed": True, "dedupe_scaling": measurements}, indent=2))
            print(json.dumps(measurements, indent=2))  # noqa: T201 -- CLI result
            faulthandler.cancel_dump_traceback_later()
            return
        import redis
        from celery import Celery
        from celery.contrib.testing.worker import start_worker
        from django.conf import settings
        from django.core.cache import cache
        from django.db import close_old_connections, connection, connections
        from django.db.backends.signals import connection_created
        from django.db.models import F, Q
        from django.test import Client, override_settings
        from django.test.utils import setup_databases, teardown_databases

        from app import backfill_queue, live_playback, request_timing, statistics_sync
        from app.mixins import disable_fetch_releases
        from app.models import (
            Episode,
            Item,
            MediaTypes,
            Movie,
            Sources,
            StatisticsDirtyDay,
            StatisticsSyncState,
            Status,
        )
        from app.providers import services, tmdb, tvdb
        from config.settings import CACHES as PRODUCTION_CACHES
        from config.sqlite_safety import resolve_sqlite_journal_mode
        from integrations import anime_mapping, import_progress
        from integrations.imports import trakt
        from integrations.models import ImportRun
        from users.models import User

        if args.control_disable_compact_episodes:
            from app.models.manager import MediaManager

            original_prefetch = MediaManager._apply_prefetch_related
            def full_graphs(manager, *args_, **kwargs):
                kwargs["compact_episodes"] = False
                return original_prefetch(manager, *args_, **kwargs)
            stack.enter_context(patch.object(MediaManager, "_apply_prefetch_related", full_graphs))

        home_counts = threading.local()
        if args.home_diagnostics:
            from app.library_query import executor as library_executor
            from users import home_screen

            original_row_items = home_screen._row_items
            def counted_row_items(*args_, **kwargs):
                items, total = original_row_items(*args_, **kwargs)
                if getattr(home_counts, "active", None) is not None:
                    home_counts.active["matched_candidates"] += total
                    home_counts.active["window_items"] += len(items)
                return items, total
            stack.enter_context(patch.object(home_screen, "_row_items", counted_row_items))
            original_attach = library_executor._attach_media
            def counted_attach(user, batch, needs):
                if getattr(home_counts, "active", None) is not None:
                    home_counts.active["ranking_candidates"] += len(batch)
                return original_attach(user, batch, needs)
            stack.enter_context(patch.object(library_executor, "_attach_media", counted_attach))
            original_lookup = home_screen._media_lookup_for_items
            def counted_lookup(user, items, **kwargs):
                result = original_lookup(user, items, **kwargs)
                if getattr(home_counts, "active", None) is not None:
                    home_counts.active["decoration_candidates"] += len(items)
                    home_counts.active["card_trackers"] += len(result)
                    for media in result.values():
                        related = getattr(media, "_prefetched_objects_cache", {})
                        seasons = related.get("seasons", [])
                        for season in [media, *seasons]:
                            episodes = getattr(season, "_prefetched_objects_cache", {}).get("episodes", [])
                            home_counts.active["card_episode_nodes"] += len(episodes)
                return result
            stack.enter_context(patch.object(home_screen, "_media_lookup_for_items", counted_lookup))

        logging.disable(logging.WARNING)  # Keep worker failures, suppress routine noise.
        services.logger.setLevel(logging.CRITICAL)
        settings.DATABASES["default"]["TEST"]["NAME"] = str(root / "test.sqlite3")
        databases = setup_databases(verbosity=0, interactive=False)
        stack.callback(teardown_databases, databases, verbosity=0)
        journal_mode, safety_fallback = resolve_sqlite_journal_mode(args.sqlite_journal)
        if args.sqlite_contention:
            def configure_contention_connection(sender, connection, **_kwargs):
                with connection.cursor() as cursor:
                    cursor.execute(f"PRAGMA journal_mode={journal_mode}")
                    cursor.execute("PRAGMA synchronous=FULL")
                    cursor.execute(f"PRAGMA busy_timeout={args.sqlite_busy_timeout_ms}")
            connection_created.connect(configure_contention_connection, weak=False)
            stack.callback(connection_created.disconnect, configure_contention_connection)
            connection.close()
        stack.enter_context(override_settings(
            CACHES={"default": {
                "BACKEND": "django_redis.cache.RedisCache",
                # Different URL from test_settings: django-redis caches pools
                # by URL and the initial settings may have made a fake pool.
                "LOCATION": f"unix://{sockets[0]}?db=3", "TIMEOUT": 86400,
                "OPTIONS": copy.deepcopy(PRODUCTION_CACHES["default"]["OPTIONS"]) if args.sqlite_contention else {},
            }}, PERF_LOG_ENABLED=True, PERF_LOG_SLOW_REQUEST_MS=0,
            ALLOWED_HOSTS=["testserver"],
            TESTING=not args.sqlite_contention,
            CELERY_TASK_ALWAYS_EAGER=not args.sqlite_contention,
        ))
        redis_client = redis.Redis(unix_socket_path=str(sockets[0]), db=3)
        if "Fake" in cache.client.get_client().connection_pool.connection_class.__name__:
            message = "Harness cache must use real Redis, not the test fake pool"
            raise RuntimeError(message)
        broker_client = redis.Redis(unix_socket_path=str(sockets[-1]), db=1)
        app = Celery("investigation", broker=os.environ["CELERY_BROKER_URL"], backend=f"redis+socket://{sockets[-1]}?virtual_host=2")
        app.conf.update(task_default_queue="investigation", worker_prefetch_multiplier=1)
        from kombu.transport.redis import Channel as RedisChannel

        priority_steps = app.conf.broker_transport_options.get("priority_steps", RedisChannel.priority_steps)
        priority_separator = app.conf.broker_transport_options.get("sep", RedisChannel.sep)
        def queue_depth(name):
            pipeline = broker_client.pipeline()
            for priority in priority_steps:
                pipeline.llen(name if not priority else f"{name}{priority_separator}{priority}")
            return sum(pipeline.execute())
        if args.worker_pool == "prefork":
            event_context = multiprocessing.get_context("fork")
            started_event = event_context.Event()
            finished_event = event_context.Event()
        else:
            started_event = threading.Event()
            finished_event = threading.Event()

        counts = Counter()
        counts_lock = threading.Lock()
        class Provider(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                query = parse_qs(urlparse(self.path).query)
                appended = query.get("append_to_response", [""])[0].split(",")
                with counts_lock:
                    counts["http"] += 1
                    counts["season_fetch"] += any(key.startswith("season/") for key in appended)
                time.sleep(args.provider_delay_ms / 1000)
                path = urlparse(self.path).path
                if path.startswith("/tvmaze/"):
                    body = b"{}"
                    self.send_response(404)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                identity = path.rsplit("/", 1)[-1]
                if not identity.isdigit():
                    # Empty catalogue/search results for unrelated foreground
                    # provider probes; never reach a real provider.
                    body = b'{"results":[],"total_pages":1,"total_results":0}'
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                media_id = int(identity)
                payload = {
                    "id": media_id, "name": "Diagnostic show", "original_name": "Diagnostic show",
                    "number_of_episodes": 2, "number_of_seasons": 1, "poster_path": None,
                    "overview": "", "genres": [], "vote_average": 0, "vote_count": 0,
                    "first_air_date": "2020-01-01", "last_air_date": "2020-01-02", "status": "Returning Series",
                    "episode_run_time": [30], "production_companies": [], "production_countries": [],
                    "spoken_languages": [], "seasons": [{"season_number": 1, "name": "Season 1", "episode_count": 2, "poster_path": None, "air_date": "2020-01-01"}], "external_ids": {"tvdb_id": 123},
                }
                if "season/1" in appended:
                    payload["season/1"] = {
                        "name": "Season 1", "poster_path": None, "season_number": 1,
                        "overview": "", "vote_average": 0, "air_date": "2020-01-01",
                        "episodes": [{"episode_number": n, "runtime": 30, "vote_count": 0,
                                      "vote_average": 0, "air_date": "2020-01-01", "name": f"Episode {n}",
                                      "still_path": None} for n in (1, 2)],
                    }
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        stack.callback(server.server_close)
        stack.callback(server.shutdown)
        local_url = f"http://127.0.0.1:{server.server_port}"
        stack.enter_context(patch.object(tmdb, "base_url", local_url))
        stack.enter_context(patch.object(tmdb.credentials, "get", return_value="diagnostic-only"))
        # The fixture configures TMDB only; never inherit optional provider
        # credentials from the workstation during artwork fallback.
        stack.enter_context(patch.object(tvdb, "enabled", return_value=False))
        stack.enter_context(patch.object(services, "_get_tmdb_proxy_url", return_value=None))
        import requests
        original_request = requests.sessions.Session.request
        def local_request(session, method, url, **kwargs):
            if url.startswith("https://api.tvmaze.com/"):
                url = local_url + "/tvmaze/" + url.removeprefix("https://api.tvmaze.com/")
            if not url.startswith(local_url + "/"):
                message = "Harness forbids external provider requests"
                raise RuntimeError(message)
            # Local fixtures must not consult proxy credentials or macOS
            # system proxy APIs in a forked child.
            session.trust_env = False
            return original_request(session, method, url, **kwargs)
        stack.enter_context(patch.object(requests.sessions.Session, "request", local_request))
        if args.sqlite_contention:
            stack.enter_context(patch.object(
                anime_mapping, "_load_source_data",
                return_value=({}, "diagnostic-empty-mapping", anime_mapping._canonical_digest({})),
            ))
            if args.control_disable_statistics_coordination:
                stack.enter_context(patch.object(statistics_sync, "coalesce_import_changes", side_effect=lambda _user_id: contextlib.nullcontext()))
                stack.enter_context(patch.object(statistics_sync, "_bulk_import_active", return_value=False))
                stack.enter_context(patch.object(statistics_sync, "interactive_request_active", return_value=False))
                stack.enter_context(patch.object(statistics_sync, "higher_priority_task_waiting", return_value=False))

        viewer = User.objects.create_user(username="viewer")
        client = Client(raise_request_exception=not args.sqlite_contention)
        client.force_login(viewer)
        request_timing.install_boundaries()
        if args.control_disable_negative:
            from django_redis.cache import RedisCache
            original_cache_set = RedisCache.set
            def without_negative(redis_cache, key, value, *args_, **kwargs):
                if value == tmdb._ABSENT_SEASON:
                    return None
                return original_cache_set(redis_cache, key, value, *args_, **kwargs)
            stack.enter_context(patch.object(RedisCache, "set", without_negative))
            original_not_found = services.raise_not_found_error
            def unconfirmed(*args_, **kwargs):
                kwargs["confirmed_absent"] = False
                return original_not_found(*args_, **kwargs)
            stack.enter_context(patch.object(services, "raise_not_found_error", unconfirmed))
        if args.control_progress_every_row:
            original_progress = import_progress.report
            def every_row(*args_, **kwargs):
                import_progress._last_report.set(None)
                return original_progress(*args_, **kwargs)
            stack.enter_context(patch.object(import_progress, "report", every_row))
        if args.control_disable_memos:
            for method in ("_get_metadata", "_get_or_create_item"):
                original_method = getattr(trakt.TraktMetadataResolverMixin, method)
                def without_memos(importer, *args_, _method=original_method, **kwargs):
                    for attribute in ("_metadata_memo", "_missing_metadata", "_item_memo"):
                        if hasattr(importer, attribute):
                            getattr(importer, attribute).clear()
                    return _method(importer, *args_, **kwargs)
                stack.enter_context(patch.object(trakt.TraktMetadataResolverMixin, method, without_memos))
        if args.broker_delay_ms:
            from kombu import Producer
            original_publish = Producer.publish
            def delayed_publish(producer, *args_, **kwargs):
                time.sleep(args.broker_delay_ms / 1000)
                return original_publish(producer, *args_, **kwargs)
            stack.enter_context(patch.object(Producer, "publish", delayed_publish))
        if args.database_delay_ms:
            from django.db.backends.sqlite3.base import SQLiteCursorWrapper
            original_execute = SQLiteCursorWrapper.execute
            def delayed_execute(cursor, *args_, **kwargs):
                time.sleep(args.database_delay_ms / 1000)
                return original_execute(cursor, *args_, **kwargs)
            stack.enter_context(patch.object(SQLiteCursorWrapper, "execute", delayed_execute))
        from django_redis.client import DefaultClient
        original_cache_get = DefaultClient.get
        def cache_get(redis_cache, key, *args_, **kwargs):
            if str(key) == live_playback._cache_key(viewer.id):
                time.sleep(args.cache_delay_ms / 1000)
            return original_cache_get(redis_cache, key, *args_, **kwargs)
        if args.cache_delay_ms:
            stack.enter_context(patch.object(DefaultClient, "get", cache_get))
        @app.task(ignore_result=True)
        def artwork_probe(_user_id):
            return None
        @app.task
        def interactive_probe(submitted):
            return (time.perf_counter() - submitted) * 1000
        @app.task(ignore_result=True)
        def statistics_probe(user_id):
            started = time.perf_counter()
            cpu_started = time.thread_time()
            import_active = started_event.is_set() and not finished_event.is_set()
            try:
                result = statistics_sync.sync_task_body(user_id)
                event = {"status": result["status"], "ranges": len(result["published"]), "duration_ms": (time.perf_counter() - started) * 1000, "thread_cpu_ms": (time.thread_time() - cpu_started) * 1000, "import_active_at_start": import_active}
            except Exception as exc:
                event = {"error": type(exc).__name__, "sqlite_locked": "database is locked" in str(exc).lower()}
                redis_client.rpush("investigation:statistics", json.dumps(event))
                redis_client.ltrim("investigation:statistics", -1000, -1)
                raise
            redis_client.rpush("investigation:statistics", json.dumps(event))
            redis_client.ltrim("investigation:statistics", -1000, -1)
        stack.enter_context(patch(
            "app.tasks_interactive.resolve_playback_image.delay",
            side_effect=lambda user_id: artwork_probe.apply_async(args=[user_id], queue="interactive"),
        ))

        @app.task
        def import_probe(user_id, missing, suppress_metadata):
            started_event.set()
            started = time.perf_counter()
            cpu_started = time.thread_time()
            user = User.objects.get(pk=user_id)
            rows_before = Episode.objects.filter(related_season__user=user).count()
            run = ImportRun.objects.create(user=user, source="trakt", task_id="diagnostic-import") if args.sqlite_contention else None
            importer = trakt.TraktImporter("diagnostic", user, "new")
            history = trakt.HistoryPages()
            try:
                for first in range(args.entries - 1, -1, -trakt.BULK_PAGE_SIZE):
                    history.extend([{
                        "type": "episode", "show": {"title": "Diagnostic show", "ids": {"tmdb": 123, "trakt": 123}},
                        "episode": {"season": MISSING_SEASONS[n % len(MISSING_SEASONS)] if missing else 1, "number": 1},
                        # Four hours exceeds the unknown-runtime dedupe window.
                        "watched_at": (datetime(2025, 1, 1, tzinfo=UTC) - timedelta(hours=4 * (args.entries - 1 - n))).isoformat(),
                    } for n in range(first, max(-1, first - trakt.BULK_PAGE_SIZE), -1)])
            except BaseException:
                history.close()
                raise
            query_counts = Counter()
            transaction_state = None
            transaction_counts = Counter()
            transaction_samples = []
            transaction_peaks = {"atomic_ms": 0.0, "first_write_to_end_ms": 0.0, "after_first_write_ms": 0.0}
            entry_errors = Counter()
            class EntryErrorCounter(logging.Handler):
                def emit(self, record):
                    if record.getMessage() == "Skipping Trakt history entry":
                        entry_errors["skipped_entries"] += 1
                        if record.exc_info and "database is locked" in str(record.exc_info[1]).lower():
                            entry_errors["sqlite_locked_entries"] += 1
            entry_counter = EntryErrorCounter()
            progress_writes = 0
            original_set = cache.set
            def count_progress(key, *args_, **kwargs):
                nonlocal progress_writes
                if str(key).startswith(import_progress.PROGRESS_CACHE_PREFIX + ":"):
                    progress_writes += 1
                return original_set(key, *args_, **kwargs)
            def queries(execute, sql, params, many, context):
                nonlocal transaction_state
                command = sql.split(None, 1)[0].lower()
                query_counts[command] += 1
                if command == "begin":
                    transaction_state = {"started": time.perf_counter(), "first_write_start": None, "first_write_end": None, "writes": 0}
                first_write = transaction_state is not None and command in {"insert", "update", "delete"}
                if first_write:
                    transaction_state["writes"] += 1
                    if transaction_state["first_write_start"] is None:
                        transaction_state["first_write_start"] = time.perf_counter()
                result = execute(sql, params, many, context)
                if first_write and transaction_state["first_write_end"] is None:
                    transaction_state["first_write_end"] = time.perf_counter()
                return result

            def transaction_end(method, outcome):
                def finish():
                    nonlocal transaction_state
                    result = method()
                    if transaction_state is not None:
                        now = time.perf_counter()
                        observed = {"outcome": outcome, "writes": transaction_state["writes"],
                                    "atomic_ms": (now - transaction_state["started"]) * 1000,
                                    "first_write_to_end_ms": (now - transaction_state["first_write_start"]) * 1000 if transaction_state["first_write_start"] is not None else 0.0,
                                    "after_first_write_ms": (now - transaction_state["first_write_end"]) * 1000 if transaction_state["first_write_end"] is not None else 0.0}
                        transaction_counts[outcome] += 1
                        for metric, previous in transaction_peaks.items():
                            transaction_peaks[metric] = max(previous, observed[metric])
                        transaction_samples.append(observed)
                        transaction_samples.sort(key=lambda row: row["first_write_to_end_ms"], reverse=True)
                        del transaction_samples[16:]
                        transaction_state = None
                    return result
                return finish
            tally, token = request_timing.begin()
            try:
                with contextlib.ExitStack() as phase:
                    trakt.logger.addHandler(entry_counter)
                    phase.callback(trakt.logger.removeHandler, entry_counter)
                    phase.enter_context(connection.execute_wrapper(queries))
                    database = connections["default"]
                    phase.enter_context(patch.object(database, "commit", transaction_end(database.commit, "commit")))
                    phase.enter_context(patch.object(database, "rollback", transaction_end(database.rollback, "rollback")))
                    phase.enter_context(patch.object(cache, "set", count_progress))
                    phase.enter_context(patch.object(importer, "_get_paginated_data", return_value=history))
                    if suppress_metadata:
                        phase.enter_context(patch.object(importer, "_get_metadata", return_value=None))
                    with (
                        import_progress.tracking("diagnostic-import", run.id if run else None),
                        backfill_queue.defer_backfill_publication(),
                        disable_fetch_releases(),
                        (statistics_sync.coalesce_import_changes(user_id) if args.sqlite_contention else contextlib.nullcontext()) as statistics_changes,
                    ):
                        importer.process_history()
                        from integrations.imports import durable

                        durable.run_import(importer, prepare_input=False)
                        if statistics_changes is not None:
                            statistics_changes["unchanged"] = Episode.objects.filter(related_season__user=user).count() == rows_before
                if run:
                    ImportRun.objects.filter(pk=run.pk).update(status=ImportRun.Status.COMPLETED, finished_at=datetime.now(UTC))
                    run.refresh_from_db()
                    durable.publish_pending(run)
                    statistics_sync.ensure_sync(user_id, bypass_gate=True)
            except BaseException:
                if run:
                    ImportRun.objects.filter(pk=run.pk).update(status=ImportRun.Status.FAILED, finished_at=datetime.now(UTC))
                raise
            finally:
                request_timing.end(token)
                history.close()
                finished_event.set()
            duration = time.perf_counter() - started
            chunk_rows = Counter()
            chunk_statements = Counter()
            chunk_peaks = {}
            chunks = []
            chunk_count = 0
            persisted = 0
            if run:
                for receipt in run.chunk_receipts.values("phase", "start", "end", "rows_persisted", "metrics").iterator(chunk_size=500):
                    chunk_count += 1
                    persisted += receipt["rows_persisted"]
                    metrics = receipt["metrics"]
                    chunk_rows[metrics.get("chunk_rows", 0)] += 1
                    chunk_statements.update(metrics.get("total_statements", metrics.get("statements", {})))
                    for name in ("first_write_to_commit_ms", "after_first_write_ms", "wall_ms", "first_write_call_ms", "wait_before_first_write_ms"):
                        chunk_peaks[name] = max(chunk_peaks.get(name, 0), metrics.get(name, 0))
                    chunks.append(receipt)
                    chunks.sort(key=lambda row: row["metrics"].get("first_write_to_commit_ms", 0), reverse=True)
                    del chunks[16:]
            return {"duration_ms": duration * 1000,
                    "entries_per_second": args.entries / duration,
                    "thread_cpu_ms": (time.thread_time() - cpu_started) * 1000,
                    "process_peak_rss_native_units": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                    "warnings": len(importer.warnings), "entries": args.entries,
                    "entry_errors": dict(entry_errors),
                    "transactions": {"counts": dict(transaction_counts), "peaks": transaction_peaks, "largest_write_windows": transaction_samples},
                    "durable_chunks": {"count": chunk_count, "rows_persisted": persisted,
                                       "row_histogram": dict(chunk_rows), "statements": dict(chunk_statements),
                                       "peaks": chunk_peaks, "largest_write_windows": chunks,
                                       "staging_bytes": run.prepared_state.get("staging_bytes", 0) if run else 0,
                                       "pending_publication": run.chunk_receipts.filter(publication_pending=True).count() if run else 0},
                    "episode_rows": Episode.objects.filter(related_season__user=user).count(),
                    "episode_rows_before": rows_before,
                    "progress_writes": progress_writes,
                    "memo_entries": {name: len(getattr(importer, name, ())) for name in ("_metadata_memo", "_missing_metadata", "_item_memo")},
                    "queries": dict(query_counts), "provider_calls": tally["calls"],
                    "provider_ms": tally["seconds"] * 1000,
                    "boundary_calls": tally["boundary_calls"],
                    "boundaries_ms": {key: value * 1000 for key, value in tally["boundaries"].items()}}

        def sample(phase, through_import=False, *, rounds=None, include_saves=True):
            results = []
            sample_number = 0
            max_request_records = 10000
            minimum_rounds = args.samples if rounds is None else rounds
            while sample_number < minimum_rounds or (through_import and not finished_event.is_set() and len(results) < max_request_records):
                routes = ["/api/active-playback/", "/", "/medialist/tv", "/settings/account"]
                if args.sqlite_contention:
                    routes.append("/home/rest/")
                    if include_saves and sample_number % 5 == 0:
                        routes.append("/media_save")
                for route in routes:
                    active = started_event.is_set() and not finished_event.is_set()
                    home_counts.active = Counter() if args.home_diagnostics and route in ("/", "/home/rest/") else None
                    profile_home = args.profile_home and route in ("/", "/home/rest/")
                    if profile_home:
                        tracemalloc.start()
                    cpu_started = time.thread_time()
                    started = time.perf_counter()
                    sql_context = request_timing.profile_sql() if home_counts.active is not None else contextlib.nullcontext(None)
                    with sql_context as sql_profile:
                        response = client.post(route, save_data | {"score": str(5 + sample_number % 5)}, HTTP_HX_REQUEST="true") if route == "/media_save" else client.get(route)
                    wall_ms = (time.perf_counter() - started) * 1000
                    cpu_ms = (time.thread_time() - cpu_started) * 1000
                    home_metrics = {"thread_cpu_ms": cpu_ms}
                    if sql_profile is not None:
                        home_metrics["sql_profile"] = {
                            "queries": sorted(sql_profile["queries"].values(), key=lambda row: row["cumulative_ms"], reverse=True),
                            "overflow_count": sql_profile["overflow_count"],
                        }
                    if profile_home:
                        home_metrics["allocation_peak_bytes"] = tracemalloc.get_traced_memory()[1]
                        tracemalloc.stop()
                    if home_counts.active is not None:
                        from app.cache_utils import HOME_ROW_CACHE_PREFIX

                        home_metrics["home_counts"] = dict(home_counts.active)
                        sizes = [redis_client.strlen(key) for key in redis_client.scan_iter(match=f"*{HOME_ROW_CACHE_PREFIX}*", count=100)]
                        home_metrics["home_cache_bytes"] = {"keys": len(sizes), "total": sum(sizes), "max": max(sizes, default=0)}
                    home_counts.active = None
                    usage = resource.getrusage(resource.RUSAGE_SELF)
                    ping_started = time.perf_counter()
                    redis_client.ping()
                    ping_ms = (time.perf_counter() - ping_started) * 1000
                    results.append({"phase": phase, "route": route, "status": response.status_code,
                                    "wall_ms": wall_ms, **home_metrics,
                                    "server_timing": response.get("Server-Timing"),
                                    "import_active_at_start": active,
                                    "redis_ping_ms": ping_ms,
                                    "process_cpu_seconds": usage.ru_utime + usage.ru_stime,
                                    "process_peak_rss_native_units": usage.ru_maxrss,
                                    "queue_depth": queue_depth("investigation"),
                                    **({"statistics_queue_depth": queue_depth("statistics"), "followup_queue_depth": queue_depth("investigation_followup")} if args.sqlite_contention else {})})
                sample_number += 1
                if through_import and not finished_event.is_set():
                    time.sleep(args.sample_interval_seconds)
            return results

        report = {"completed": False, "configuration": vars(args) | {"output": str(args.output)},
                  "effective_settings": {name: getattr(settings, name, None) for name in (
                      "RESOURCE_TIER", "RUNTIME_WEB_CONCURRENCY", "RUNTIME_GUNICORN_THREADS",
                      "CELERY_WORKER_CONCURRENCY", "CELERY_WORKER_PREFETCH_MULTIPLIER",
                      "PERF_LOG_ENABLED", "PERF_LOG_SLOW_TASK_MS",
                      "TRAKT_IMPORT_CHUNK_ROWS", "TRAKT_IMPORT_CHUNK_TARGET_MS", "TRAKT_IMPORT_STAGING_BYTES",
                  )},
                  "limitations": ["SQLite file database; model-built schema, no migration replay",
                                  "Local Celery worker and Django test client, no Gunicorn or CPU quota",
                                  "TESTING suppresses production enrichment signals and uses a fake provider limiter",
                                  "Trakt retrieval supplied locally; TMDB HTTP/parsing/cache and history/persistence run",
                                  "Primary-metadata-skipped control skips importing rows; it does not isolate backfills",
                                  "Viewer has an empty library; measures cross-user resource contention",
                                  "No production completion cascades/calendar/statistics catch-up; sequential scenarios share cache"],
                  "requests": [], "imports": []}
        def save_checkpoint():
            error = sys.exc_info()[1]
            if error is not None:
                report["acceptance_passed"] = False
                report["failure_type"] = type(error).__name__
            args.output.write_text(json.dumps(report, indent=2))
        stack.callback(save_checkpoint)
        if args.sqlite_contention:
            report["limitations"] = [
                "File SQLite with model-built schema; production signal receivers enabled after test-settings startup",
                "Local Celery worker and Django Client, no Gunicorn, beat, storage quota or NAS topology",
                "Local TMDB stub; Trakt retrieval and an empty anime mapping supplied locally",
                "Background enrichment/calendar tasks publish to an isolated follow-up queue and are not executed",
                "Statistics reconciliation runs every 250ms in the harness instead of the production minute",
                "One show with repeated watches; does not represent a large distinct-show Home library",
            ]
            report["sqlite"] = {"runtime_version": sqlite3.sqlite_version, "requested_journal": args.sqlite_journal, "safety_fallback": safety_fallback}
            with connection.cursor() as cursor:
                for key in ("journal_mode", "synchronous", "busy_timeout"):
                    cursor.execute(f"PRAGMA {key}")
                    report["sqlite"][key] = cursor.fetchone()[0]
            allowed_tasks = {task.name for task in (artwork_probe, interactive_probe, import_probe, statistics_probe)}
            if args.drain_enrichment:
                from celery.signals import task_postrun, task_prerun

                # Register before prefork children exist, so their completion
                # states cross the process boundary through disposable Redis.
                task_metrics = {}
                def observe_task_start(task_id=None, **_kwargs):
                    queries = Counter()
                    def count_operation(execute, sql, params, many, context):
                        queries[sql.lstrip().split(None, 1)[0].lower()] += 1
                        return execute(sql, params, many, context)
                    wrapper = connections["default"].execute_wrapper(count_operation)
                    wrapper.__enter__()
                    task_metrics[task_id] = (wrapper, queries, time.perf_counter(), time.thread_time())
                def observe_followup(sender=None, task=None, state=None, task_id=None, **_kwargs):
                    name = getattr(task or sender, "name", "")
                    metric = task_metrics.pop(task_id, None)
                    if metric is not None:
                        wrapper, queries, wall_started, cpu_started = metric
                        wrapper.__exit__(None, None, None)
                        redis_client.rpush("investigation:worker_operations", json.dumps({
                            "task": name, "state": state, "queries": dict(queries),
                            "worker_pid": os.getpid(),
                            "wall_ms": (time.perf_counter() - wall_started) * 1000,
                            "thread_cpu_ms": (time.thread_time() - cpu_started) * 1000,
                            "process_peak_rss_native_units": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                        }))
                        redis_client.ltrim("investigation:worker_operations", -1000, -1)
                    if name not in allowed_tasks:
                        redis_client.rpush("investigation:followup", json.dumps({"task": name, "state": state}))
                        redis_client.ltrim("investigation:followup", -1000, -1)
                task_prerun.connect(observe_task_start, weak=False)
                stack.callback(task_prerun.disconnect, observe_task_start)
                task_postrun.connect(observe_followup, weak=False)
                stack.callback(task_postrun.disconnect, observe_followup)
            from celery.app.task import Task
            original_apply_async = Task.apply_async
            def isolated_publication(task, *args_, **kwargs):
                if task.name not in allowed_tasks:
                    kwargs["queue"] = "investigation_followup"
                return original_apply_async(task, *args_, **kwargs)
            stack.enter_context(patch.object(Task, "apply_async", isolated_publication))
            stack.enter_context(patch(
                "app.tasks_interactive.statistics_sync_task.apply_async",
                side_effect=lambda args, **_kwargs: statistics_probe.apply_async(args=args, queue="statistics"),
            ))
            item = Item.objects.create(media_id="diagnostic-save", source=Sources.MANUAL.value, media_type=MediaTypes.MOVIE.value, title="Diagnostic foreground save", runtime_minutes=100)
            movie = Movie.objects.create(user=viewer, item=item, status=Status.COMPLETED.value, end_date=datetime.now(UTC), score=5)
            save_data = {"media_id": item.media_id, "source": item.source, "media_type": item.media_type, "instance_id": str(movie.id), "status": movie.status, "progress": "", "start_date": "", "end_date": movie.end_date.date().isoformat(), "notes": ""}
            statistics_errors = []
            reconciliation_counts = Counter()
            stop_statistics = threading.Event()
            def reconcile_statistics():
                close_old_connections()
                def count_operation(execute, sql, params, many, context):
                    reconciliation_counts[f"sql_{sql.lstrip().split(None, 1)[0].lower()}"] += 1
                    return execute(sql, params, many, context)
                wrapper = connection.execute_wrapper(count_operation)
                wrapper.__enter__()
                try:
                    while not stop_statistics.wait(0.25):
                        try:
                            reconciliation_counts["passes"] += 1
                            reconciliation_counts["queued"] += statistics_sync.reconcile()
                            reconciliation_counts["deferred_during_import"] += bool(started_event.is_set() and not finished_event.is_set() and statistics_sync._bulk_import_active(viewer.id))
                        except Exception as exc:
                            statistics_errors.append(type(exc).__name__)
                finally:
                    wrapper.__exit__(None, None, None)
                    connection.close()
            reconciliation_thread = threading.Thread(target=reconcile_statistics, daemon=True)
            def stop_reconciliation():
                stop_statistics.set()
                reconciliation_thread.join(timeout=10)
            stack.callback(stop_reconciliation)
        # AsyncResult holds promise cycles; collect them after worker shutdown
        # while its disposable Redis backend is still available.
        stack.callback(gc.collect)
        worker = stack.enter_context(start_worker(
            app, pool=args.worker_pool, concurrency=args.worker_concurrency, queues=["investigation", "interactive", "statistics"] if args.sqlite_contention else ["investigation", "interactive"],
            perform_ping_check=False,
        ))
        if args.sqlite_contention:
            reconciliation_thread.start()
        for state in ("empty", "artwork", "missing_artwork", "expired"):
            cache.delete(live_playback._cache_key(viewer.id))
            if state != "empty":
                cache.set(live_playback._cache_key(viewer.id), {
                    "media_id": "123", "media_type": "movie", "source": "tmdb", "title": "Diagnostic movie",
                    "status": "playing", "image": "/static/img/none.svg" if state == "artwork" else None,
                    "expires_at_ts": 1 if state == "expired" else int(time.time()) + 3600,
                }, 3600)
            report["requests"].extend(sample(f"idle_{state}"))
        for missing, suppressed, label in ((False, False, "success"), (True, False, "missing"), (True, True, "primary_metadata_skipped")):
            if label not in args.scenarios:
                continue
            user = viewer if args.sqlite_contention else User.objects.create_user(username=label)
            before = redis_client.info()
            with counts_lock:
                counts.clear()
            started_event.clear()
            finished_event.clear()
            future = import_probe.apply_async(args=[user.id, missing, suppressed], queue="investigation")
            if not started_event.wait(timeout=30):
                message = "Import task did not start within 30 seconds"
                raise RuntimeError(message)
            interactive = interactive_probe.apply_async(args=[time.perf_counter()], queue="interactive")
            report["requests"].extend(sample(f"during_{label}", through_import=args.sample_through_import))
            result_timeout = max(120, args.entries * (args.provider_delay_ms / 1000 + 0.1))
            result = future.get(timeout=result_timeout)
            del future  # Cancel result subscriptions before disposable Redis stops.
            result["interactive_queue_wait_ms"] = interactive.get(timeout=120)
            del interactive
            after = redis_client.info()
            result.update(scenario=label, http=dict(counts), redis_commands=after["total_commands_processed"] - before["total_commands_processed"],
                          redis_hits=after["keyspace_hits"] - before["keyspace_hits"],
                          redis_misses=after["keyspace_misses"] - before["keyspace_misses"],
                          redis_evicted_keys=after["evicted_keys"] - before["evicted_keys"],
                          redis_used_memory=after["used_memory"], redis_used_memory_peak=after["used_memory_peak"])
            report["imports"].append(result)
            # Preserve measured phases even if a later large replay/drain fails.
            args.output.write_text(json.dumps(report, indent=2))
            if args.sqlite_contention and label == "success" and result["episode_rows"] != args.entries:
                message = "Successful history fixture lost or duplicated watches"
                raise RuntimeError(message)
            if label == "missing" and not args.control_disable_negative and counts["season_fetch"] > len(MISSING_SEASONS):
                message = "Missing metadata amplification regressed"
                raise RuntimeError(message)
            if result["memo_entries"]["_metadata_memo"] > trakt.METADATA_MEMO_SIZE or result["memo_entries"]["_item_memo"] > trakt.ITEM_MEMO_SIZE:
                message = "Import-local memo bound regressed"
                raise RuntimeError(message)
            if label == "success" and not args.control_disable_memos and not result["memo_entries"]["_metadata_memo"]:
                message = "Real provider DTOs were not admitted to the import memo"
                raise RuntimeError(message)
            report["requests"].extend(sample(f"after_{label}"))
            # Replaying identical watches exercises persisted-data deduplication.
            if label == "success":
                replay = import_probe.apply_async(args=[user.id, missing, suppressed], queue="investigation").get(timeout=result_timeout)
                report["imports"].append(replay | {"scenario": "existing_replay"})
                if args.sqlite_contention and replay["episode_rows"] != args.entries:
                    message = "Replaying history changed its watch count"
                    raise RuntimeError(message)
        if args.sqlite_contention and args.drain_enrichment:
            from app.tasks_credits import CREDITS_BACKFILL_ITEMS_QUEUE_KEY
            from app.tasks_genre import GENRE_BACKFILL_ITEMS_QUEUE_KEY
            from app.tasks_runtime import (
                RUNTIME_BACKFILL_EPISODES_QUEUE_KEY,
                RUNTIME_BACKFILL_ITEMS_QUEUE_KEY,
            )

            queues = {
                "runtime": RUNTIME_BACKFILL_ITEMS_QUEUE_KEY,
                "episode_runtime": RUNTIME_BACKFILL_EPISODES_QUEUE_KEY,
                "genres": GENRE_BACKFILL_ITEMS_QUEUE_KEY,
                "credits": CREDITS_BACKFILL_ITEMS_QUEUE_KEY,
            }
            followup_started = time.perf_counter()
            deadline = followup_started + args.statistics_drain_seconds
            # Two embedded workers share Kombu's process-local event loop.
            # Enable this queue on the existing worker after foreground sampling.
            app.control.add_consumer("investigation_followup", destination=[worker.hostname])
            inspector = app.control.inspect(destination=[worker.hostname], timeout=1)
            stable = 0
            required_quiet_samples = 2
            next_probe = 0
            while stable < required_quiet_samples:
                if time.perf_counter() >= next_probe:
                    report["requests"].extend(sample("during_followup", rounds=1, include_saves=False))
                    next_probe = time.perf_counter() + args.followup_probe_interval_seconds
                counts_by_queue = {name: len(backfill_queue.members(key, coerce=str)) for name, key in queues.items()}
                pending_tasks = sum(
                    len(rows)
                    for method in (inspector.active, inspector.reserved, inspector.scheduled)
                    for rows in (method() or {}).values()
                )
                busy = queue_depth("investigation_followup") or any(counts_by_queue.values()) or pending_tasks
                stable = 0 if busy else stable + 1
                if time.perf_counter() >= deadline:
                    message = "Actual enrichment tasks did not drain within the configured limit"
                    raise RuntimeError(message)
                time.sleep(0.25)
            events = [json.loads(row) for row in redis_client.lrange("investigation:followup", 0, -1)]
            report["enrichment"] = {"duration_ms": (time.perf_counter() - followup_started) * 1000, "tasks": events, "remaining_queue_members": counts_by_queue, "worker_pool": args.worker_pool, "extra_worker_slots": 0, "runtime_known_items": Item.objects.exclude(runtime_minutes__isnull=True).count()}
            if any(event["state"] != "SUCCESS" for event in events):
                message = "Actual enrichment task failed; the local stub may not cover its provider path"
                raise RuntimeError(message)
            report["limitations"] = [line for line in report["limitations"] if "are not executed" not in line] + ["Follow-up queue enabled on the existing worker only after foreground/import sampling; metadata coverage is the local stub's"]
            report["requests"].extend(sample("after_followup_completion"))

        if args.sqlite_contention:
            drain_started = time.perf_counter()
            deadline = drain_started + args.statistics_drain_seconds
            next_probe = 0
            while (
                StatisticsSyncState.objects.filter(
                    Q(hot_synced_generation__lt=F("generation"))
                    | Q(heavy_synced_generation__lt=F("generation")),
                ).exists()
                or statistics_sync.users_needing_sync()
                or statistics_sync.sync_is_running(viewer.id)
                or queue_depth("statistics")
            ):
                if time.perf_counter() >= next_probe:
                    report["requests"].extend(sample("during_statistics_drain", rounds=1, include_saves=False))
                    next_probe = time.perf_counter() + args.followup_probe_interval_seconds
                if time.perf_counter() >= deadline:
                    message = "Statistics did not finish within the configured drain limit"
                    raise RuntimeError(message)
                time.sleep(0.25)
            report["requests"].extend(sample("after_statistics_completion", include_saves=False))
            if args.drain_enrichment:
                quiet = 0
                while quiet < required_quiet_samples:
                    pending_tasks = sum(
                        len(rows)
                        for method in (inspector.active, inspector.reserved, inspector.scheduled)
                        for rows in (method() or {}).values()
                    )
                    remaining = {name: len(backfill_queue.members(key, coerce=str)) for name, key in queues.items()}
                    depths = {name: queue_depth(name) for name in ("investigation", "interactive", "statistics", "investigation_followup")}
                    behind = StatisticsSyncState.objects.filter(
                        Q(hot_synced_generation__lt=F("generation"))
                        | Q(heavy_synced_generation__lt=F("generation")),
                    ).exists()
                    busy = pending_tasks or any(remaining.values()) or any(depths.values()) or statistics_sync.users_needing_sync() or behind
                    quiet = 0 if busy else quiet + 1
                    if time.perf_counter() >= deadline:
                        message = "Final foreground probes left background work that did not converge"
                        raise RuntimeError(message)
                    time.sleep(0.25)
                report["final_queue_activity"] = {"depths": depths, "active_reserved_scheduled": pending_tasks, "backfill_members": remaining}
                events = [json.loads(row) for row in redis_client.lrange("investigation:followup", 0, -1)]
                report["enrichment"]["tasks"] = events
                if any(event["state"] != "SUCCESS" for event in events):
                    message = "A follow-up task failed after foreground sampling"
                    raise RuntimeError(message)
            stop_reconciliation()
            statistics_events = [json.loads(row) for row in redis_client.lrange("investigation:statistics", 0, -1)]
            if args.drain_enrichment:
                report["worker_operations"] = [json.loads(row) for row in redis_client.lrange("investigation:worker_operations", 0, -1)]
            report["statistics"] = {"reconciliation": dict(reconciliation_counts), "reconciliation_errors": statistics_errors, "tasks": statistics_events, "drain_ms": (time.perf_counter() - drain_started) * 1000, "pending_dirty_days": StatisticsDirtyDay.objects.count(), "generation": list(StatisticsSyncState.objects.values("generation", "hot_synced_generation", "heavy_synced_generation")), "queue_depth": queue_depth("statistics"), "followup_queue_depth": queue_depth("investigation_followup")}
            if statistics_errors or any("error" in event for event in statistics_events):
                args.output.write_text(json.dumps(report, indent=2))
                message = "Statistics encountered errors under SQLite contention"
                raise RuntimeError(message)
        report["summary"] = []
        for phase, route in sorted({(row["phase"], row["route"]) for row in report["requests"]}):
            rows = [row for row in report["requests"] if row["phase"] == phase and row["route"] == route]
            values = [row["wall_ms"] for row in rows]
            active_values = [row["wall_ms"] for row in rows if row["import_active_at_start"]]
            report["summary"].append({"phase": phase, "route": route, "samples": len(rows),
                                      "active_import_samples": sum(row["import_active_at_start"] for row in rows),
                                      "errors": sum(row["status"] != HTTPStatus.OK for row in rows),
                                      "error_rate": sum(row["status"] != HTTPStatus.OK for row in rows) / len(rows),
                                      "active_import_percentiles_ms": {f"p{int(p * 100)}": percentile(active_values, p) for p in (0.5, 0.95, 0.99)} if active_values else None,
                                      **{f"p{int(p * 100)}_ms": percentile(values, p) for p in (0.5, 0.95, 0.99)}})
        report["completed"] = True
        report["acceptance_passed"] = not any(row["status"] >= HTTPStatus.BAD_REQUEST for row in report["requests"])
        args.output.write_text(json.dumps(report, indent=2))
        if args.sqlite_contention and any(row["status"] >= HTTPStatus.BAD_REQUEST for row in report["requests"]):
            message = "Foreground errors escaped during the SQLite contention workload; see the saved report"
            raise RuntimeError(message)
        print(json.dumps({"output": str(args.output), "imports": report["imports"], "summary": report["summary"]}, indent=2))  # noqa: T201 -- CLI result
        faulthandler.cancel_dump_traceback_later()


if __name__ == "__main__":
    main()
