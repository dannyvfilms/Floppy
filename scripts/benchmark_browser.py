# ruff: noqa: INP001, T201, PLR2004 -- opt-in standalone benchmark dimensions
"""BENCH-03: disposable Playwright journeys; JSON/Markdown, never personal tabs."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import statistics
import subprocess
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
from wsgiref.simple_server import make_server

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import benchmark_fixtures as common  # noqa: E402

PROTOCOL = "bench03-browser-v1"
VIEWPORTS = {
    "desktop": {"width": 1280, "height": 900},
    "mobile": {"width": 390, "height": 844},
}
ROUTES = {
    "home": "/",
    "movies": "/medialist/movie",
    "tv": "/medialist/tv",
    "music": "/medialist/music",
    "podcasts": "/medialist/podcast",
    "history": "/history",
    "statistics": "/statistics",
    "calendar": "/calendar",
    "collection": "/collection/",
    "lists": "/lists",
    "list_detail": "/list/bench-browser-list",
}
OBSERVER = ROOT / "scripts/browser_journey_observers.js"
NAV_FIELDS = (
    "fetchStart",
    "domainLookupStart",
    "domainLookupEnd",
    "connectStart",
    "connectEnd",
    "requestStart",
    "responseStart",
    "responseEnd",
    "domInteractive",
    "domContentLoadedEventEnd",
    "loadEventEnd",
    "transferSize",
    "encodedBodySize",
    "decodedBodySize",
)


def safe_path(url):
    """Drop origin, fragment, queries and identifier segments from exported URLs."""
    parsed = urlsplit(url)
    if parsed.scheme and parsed.scheme not in {"http", "https"}:
        return f"<{parsed.scheme}>"
    path = parsed.path
    return "/".join(
        "<id>" if part.isdecimal() or re.fullmatch(r"[a-fA-F0-9]{16,}", part) else part
        for part in path.split("/")
    )


def polling(waterfall, observed_ms):
    """Report repeat fetches and intervals; repetition alone does not prove polling."""
    groups = defaultdict(list)
    for row in waterfall:
        if row["resource_type"] in {"fetch", "xhr"}:
            groups[(row["method"], row["path"], row.get("group", row["path"]))].append(
                row["start_ms"]
            )
    return [
        {
            "method": method,
            "path": path,
            "group": group,
            "count": len(times),
            "requests_per_second": len(times) / (observed_ms / 1000),
            "intervals_ms": [
                b - a for a, b in zip(sorted(times), sorted(times)[1:], strict=False)
            ],
            "frequency_hz": 1000
            / statistics.median(
                [b - a for a, b in zip(sorted(times), sorted(times)[1:], strict=False)]
            )
            if len(times) > 1 and len(set(times)) == len(times)
            else None,
            "note": "repeat endpoint candidate, not proof of a timer; short windows are right-censored",
        }
        for (method, path, group), times in sorted(groups.items())
    ]


def browser_resources(session):
    """Snapshot only this dedicated browser's processes; retain partial-metric notes."""
    rows = [
        {
            "pid": info["id"],
            "type": info["type"],
            "cpu_s": info["cpuTime"],
            "memory_bytes": common.memory(int(info["id"])),
        }
        for info in session.send("SystemInfo.getProcessInfo")["processInfo"]
    ]
    totals = {}
    for metric in ("rss", "uss", "pss"):
        values = [row["memory_bytes"][metric] for row in rows]
        totals[metric] = {
            "bytes": sum(values)
            if all(value is not None for value in values)
            else None,
            "available_processes": sum(value is not None for value in values),
            "processes": len(rows),
        }
    # PIDs are kept internally for deltas, never exported.
    return {"processes": rows, "memory": totals}


def resource_delta(before, after):
    """Compute surviving/new-process CPU; explicitly count vanished processes."""
    old = {row["pid"]: row for row in before["processes"]}
    new = {row["pid"]: row for row in after["processes"]}
    return {
        "cpu_s": sum(
            max(row["cpu_s"] - old.get(pid, {"cpu_s": 0})["cpu_s"], 0)
            for pid, row in new.items()
        ),
        "new_processes": len(new.keys() - old.keys()),
        "exited_processes": len(old.keys() - new.keys()),
        "memory_before_bytes": before["memory"],
        "memory_after_bytes": after["memory"],
    }


def navigate(context, browser_session, base, path, mode, observe_ms, profile=False):
    """Measure bounded readiness/observation without waiting for network idle."""
    page = context.new_page()
    # Playwright's clock replaces Performance entries too. Anchor Date only.
    page.add_init_script("""(() => {
      const RealDate = Date, origin = performance.now();
      const epoch = RealDate.parse('2025-01-01T00:00:00Z');
      const now = () => epoch + performance.now() - origin;
      function FixtureDate(...args) {
        if (!new.target) return new RealDate(now()).toString();
        return Reflect.construct(RealDate, args.length ? args : [now()], new.target);
      }
      Object.setPrototypeOf(FixtureDate, RealDate);
      FixtureDate.prototype = RealDate.prototype;
      FixtureDate.now = now;
      window.Date = FixtureDate;
    })();""")
    cdp = context.new_cdp_session(page)
    cdp.send("Performance.enable")
    if mode == "instrumented":
        page.add_init_script(path=str(OBSERVER))
    if profile:
        cdp.send("Profiler.enable")
        cdp.send("Profiler.start")
    waterfall, requests = [], {}
    started = None
    dropped = 0
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(True))

    def request_start(request):
        nonlocal dropped
        if len(waterfall) >= 10000:
            dropped += 1
            return
        row = {
            "path": safe_path(request.url)
            if urlsplit(request.url).netloc == urlsplit(base).netloc
            else "<external>",
            "method": request.method,
            "group": hashlib.sha256(urlsplit(request.url).path.encode()).hexdigest()[
                :16
            ],
            "resource_type": request.resource_type,
            "start_ms": (time.perf_counter() - started) * 1000,
            "status": None,
            "finished_ms": None,
            "failed": False,
        }
        requests[request] = row
        waterfall.append(row)

    def response_received(response):
        if response.request in requests:
            requests[response.request]["status"] = response.status

    def request_end(request):
        if request in requests:
            row = requests[request]
            row.update(
                finished_ms=(time.perf_counter() - started) * 1000,
                timing_ms={
                    key: value
                    for key, value in request.timing.items()
                    if key != "startTime"
                },
            )

    def request_failed(request):
        if request in requests:
            requests[request].update(
                failed=True, finished_ms=(time.perf_counter() - started) * 1000
            )

    if mode == "instrumented":
        page.on("request", request_start)
        page.on("response", response_received)
        page.on("requestfinished", request_end)
        page.on("requestfailed", request_failed)
    before = browser_resources(browser_session)
    own_before = common.memory()
    own_cpu = time.process_time()
    started = time.perf_counter()
    try:
        response = page.goto(base + path, wait_until="domcontentloaded", timeout=30000)
        if response.status != 200 or urlsplit(page.url).path != urlsplit(path).path:
            msg = f"Journey did not reach its authenticated route: {path} status={response.status}"
            raise RuntimeError(msg)
        shell_ms = (time.perf_counter() - started) * 1000
        selector = "main .media-card" if path.startswith("/medialist/") else "main"
        page.locator(selector).first.wait_for(state="visible", timeout=15000)
        page.evaluate(
            "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
        )
        ready_ms = (time.perf_counter() - started) * 1000
        ready_pending = page.evaluate("""() => ({rows: document.querySelectorAll('[data-home-row-slot]').length,
          htmx: document.querySelectorAll('.htmx-request').length})""")
        page.wait_for_timeout(observe_ms)
        elapsed_ms = (time.perf_counter() - started) * 1000
        own_cpu = time.process_time() - own_cpu
        result = page.evaluate("""() => ({
          navigation: performance.getEntriesByType('navigation')[0]?.toJSON() || {},
          observers: window.__floppyBenchmark ? window.__floppyBenchmark() : null,
          cards: document.querySelectorAll('main .media-card').length,
          pending_rows: document.querySelectorAll('[data-home-row-slot]').length,
          inflight_htmx: document.querySelectorAll('.htmx-request').length,
          declared_polls: Array.from(document.querySelectorAll('[hx-trigger]')).map(e => e.getAttribute('hx-trigger')).filter(v => /every\\s/.test(v))
        })""")
        metrics = {
            row["name"]: row["value"]
            for row in cdp.send("Performance.getMetrics")["metrics"]
        }
        after = browser_resources(browser_session)
        sample = {
            "mode": mode,
            "shell_ms": shell_ms,
            "ready_ms": ready_ms,
            "wall_ms": elapsed_ms,
            "readiness_selector": selector,
            "pending_rows_at_ready": ready_pending["rows"],
            "inflight_htmx_at_ready": ready_pending["htmx"],
            "status": response.status,
            "navigation": {key: result["navigation"].get(key) for key in NAV_FIELDS},
            "observers": result["observers"],
            "waterfall": waterfall,
            "dropped_network_entries": dropped,
            "page_error_count": len(page_errors),
            "polling": polling(waterfall, elapsed_ms)
            if mode == "instrumented"
            else None,
            "declared_poll_triggers": result["declared_polls"],
            "cards": result["cards"],
            "pending_rows": result["pending_rows"],
            "inflight_htmx": result["inflight_htmx"],
            "runner": {
                "cpu_s": own_cpu,
                "memory_before_bytes": own_before,
                "memory_after_bytes": common.memory(),
            },
            "browser": resource_delta(before, after),
            "renderer_cdp": {
                key: metrics.get(key)
                for key in (
                    "TaskDuration",
                    "ScriptDuration",
                    "LayoutDuration",
                    "RecalcStyleDuration",
                    "JSHeapUsedSize",
                )
            },
        }
        if profile:
            cpu_profile = cdp.send("Profiler.stop")["profile"]
            for node in cpu_profile["nodes"]:
                frame = node["callFrame"]
                frame["url"] = safe_path(frame["url"])
            sample["cpu_profile"] = cpu_profile
        return sample
    finally:
        page.close()


def worker(options):
    """Seed and serve a disposable SQLite instance before starting Playwright."""
    directory = options.output
    directory.mkdir(parents=True, exist_ok=False)
    database = directory / "dataset.sqlite3"
    os.environ.update(
        DJANGO_SETTINGS_MODULE="config.test_settings",
        SECRET="bench-browser-only",  # noqa: S106
        FLOPPY_DB_PATH=str(database),
        FLOPPY_TEST_ALLOW_NETWORK="0",
    )
    sys.path.insert(0, str(ROOT / "src"))
    import django
    from django.conf import settings

    settings.DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": str(database),
            "OPTIONS": {"timeout": 30},
        }
    }
    settings.CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
    }
    settings.DEBUG = False
    settings.ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]
    settings.ALLAUTH_TRUSTED_CLIENT_IP_HEADER = None
    settings.CELERY_TASK_ALWAYS_EAGER = False
    settings.CELERY_BROKER_URL = "memory://"
    django.setup()
    import requests
    from django.apps import apps
    from django.contrib.staticfiles.handlers import StaticFilesHandler
    from django.core.cache import cache
    from django.core.management import call_command
    from django.core.servers.basehttp import ThreadedWSGIServer
    from django.core.wsgi import get_wsgi_application
    from django.db import connections
    from django.test import Client
    from django.test.testcases import QuietWSGIRequestHandler
    from playwright.sync_api import sync_playwright

    from app.benchmark_data import EPOCH, build_dataset
    from lists.models import CustomList, CustomListItem
    from users.home_screen import ensure_home_screen_rows
    from users.models import HomeScreenRow, User

    settings.MIGRATION_MODULES = dict.fromkeys(
        app.label for app in apps.get_app_configs()
    )
    call_command("migrate", run_syncdb=True, verbosity=0)
    with connections["default"].cursor() as cursor:
        cursor.execute("PRAGMA journal_mode=WAL")
    with (
        patch("django.utils.timezone.now", return_value=EPOCH),
        patch(
            "requests.sessions.Session.request",
            side_effect=requests.ConnectionError("Synthetic offline provider"),
        ) as providers,
        patch("celery.app.task.Task.apply_async", return_value=None) as queued,
    ):
        models, generation = common.measure(
            lambda: build_dataset(options.size, options.seed)
        )
        user = User.objects.get(username="bench-user-1")
        User.objects.filter(pk=user.pk).update(statistics_default_range="All Time")
        ensure_home_screen_rows(user)
        custom_list = CustomList.objects.bulk_create(
            [
                CustomList(
                    owner=user,
                    name="Synthetic browser list",
                    visibility="public",
                    public_slug="bench-browser-list",
                )
            ]
        )[0]
        from app.models import (
            Album,
            AlbumTracker,
            Artist,
            ArtistTracker,
            Item,
            PodcastShow,
            PodcastShowTracker,
        )

        ArtistTracker.objects.bulk_create(
            [ArtistTracker(user=user, artist=Artist.objects.first())]
        )
        AlbumTracker.objects.bulk_create(
            [AlbumTracker(user=user, album=Album.objects.first())]
        )
        PodcastShowTracker.objects.bulk_create(
            [PodcastShowTracker(user=user, show=PodcastShow.objects.first())]
        )

        CustomListItem.objects.bulk_create(
            [
                CustomListItem(custom_list=custom_list, item=item, added_by=user)
                for item in Item.objects.filter(media_type="movie").order_by("pk")[:24]
            ]
        )
        client = Client()
        client.force_login(user)
        cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
        models += [
            HomeScreenRow,
            CustomList,
            CustomListItem,
            ArtistTracker,
            AlbumTracker,
            PodcastShowTracker,
        ]
        checksum = common.export_fixture(models, directory / "fixture.json.gz")
        if "statistics" in options.routes:
            from app.statistics_sync import run_sync

            stats = run_sync(user.pk, only_ranges=["All Time"])
            if stats["status"] != "done":
                msg = f"Statistics preparation failed: {stats['status']}"
                raise RuntimeError(msg)
        database_info = common.database_metadata(connections["default"])
        connections.close_all()
        server = make_server(
            "127.0.0.1",
            0,
            StaticFilesHandler(get_wsgi_application()),
            server_class=ThreadedWSGIServer,
            handler_class=QuietWSGIRequestHandler,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        samples = []
        mocked_assets = 0

        def browser_route(route):
            nonlocal mocked_assets
            if urlsplit(route.request.url).netloc == urlsplit(base).netloc:
                route.continue_()
            else:
                mocked_assets += 1
                route.fulfill(
                    status=200,
                    content_type="image/svg+xml",
                    body='<svg xmlns="http://www.w3.org/2000/svg" width="64" height="96"><rect width="64" height="96" fill="#777"/></svg>',
                )

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                session = browser.new_browser_cdp_session()
                version = browser.version
                for viewport in options.viewports:
                    for name in options.routes:
                        # Alternate the control/instrument order across repeat workers.
                        modes = (
                            ["control", "instrumented"]
                            if options.control
                            else ["instrumented"]
                        )
                        if options.repeat_index % 2 == 0:
                            modes.reverse()
                        for mode in modes:
                            cache.clear()
                            context = browser.new_context(
                                viewport=VIEWPORTS[viewport],
                                is_mobile=viewport == "mobile",
                                has_touch=viewport == "mobile",
                                device_scale_factor=1,
                                service_workers="block",
                                locale="en-US",
                                timezone_id="UTC",
                                color_scheme="light",
                            )
                            context.add_cookies(
                                [
                                    {
                                        "name": settings.SESSION_COOKIE_NAME,
                                        "value": cookie,
                                        "url": base,
                                    }
                                ]
                            )
                            context.route("**/*", browser_route)
                            try:
                                for state in options.states:
                                    sample = navigate(
                                        context,
                                        session,
                                        base,
                                        ROUTES[name],
                                        mode,
                                        options.observe_ms,
                                    )
                                    samples.append(
                                        {
                                            **sample,
                                            "route": name,
                                            "viewport": viewport,
                                            "state": state,
                                        }
                                    )
                                    print(
                                        f"repeat={options.repeat_index} {viewport} {name} {mode} {state}",
                                        flush=True,
                                    )
                                if options.profile and mode == "instrumented":
                                    profiled = navigate(
                                        context,
                                        session,
                                        base,
                                        ROUTES[name],
                                        "instrumented",
                                        options.observe_ms,
                                        profile=True,
                                    )
                                    artifact = f"profile-{viewport}-{name}.cpuprofile"
                                    (directory / artifact).write_text(
                                        json.dumps(profiled.pop("cpu_profile"))
                                    )
                                    samples.append(
                                        {
                                            **profiled,
                                            "mode": "profiled",
                                            "route": name,
                                            "viewport": viewport,
                                            "state": "repeat",
                                            "cpu_profile_artifact": artifact,
                                        }
                                    )
                            finally:
                                context.close()
                cpu, started = time.process_time(), time.perf_counter()
                for _ in range(5):
                    browser_resources(session)
                collector = {
                    "calls": 5,
                    "wall_s": time.perf_counter() - started,
                    "cpu_s": time.process_time() - cpu,
                }
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=10)
            connections.close_all()
        receipt = {
            "protocol": PROTOCOL,
            "repeat": options.repeat_index,
            "fixture_sha256": checksum,
            "size": options.size,
            "seed": options.seed,
            "browser_version": version,
            "database": database_info,
            "generation": generation,
            "samples": samples,
            "provider_calls_mocked": providers.call_count,
            "queued_tasks_mocked": queued.call_count,
            "external_assets_mocked": mocked_assets,
            "browser_resource_collector": collector,
        }
        (directory / "sample.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n"
        )
    for path in directory.glob("dataset.sqlite3*"):
        path.unlink()


def compare_reports(current, baseline):
    """Withhold ratios when recorded browser, fixture or journey settings differ."""
    keys = (
        "schema_version",
        "protocol",
        "machine",
        "size",
        "seed",
        "observe_ms",
        "viewports",
        "routes",
        "states",
        "control",
        "profile",
        "settings",
        "playwright_version",
    )
    reasons = [
        f"{key} differs" for key in keys if current.get(key) != baseline.get(key)
    ]
    for key in ("fixture_sha256", "browser_version", "database"):
        if any(
            row[key] != current["executions"][0][key]
            for row in [*current["executions"], *baseline["executions"]]
        ):
            reasons.append(f"{key} differs")  # noqa: PERF401 -- explicit compatibility gates
    old = {
        (row["route"], row["viewport"], row["state"], row["mode"]): row
        for row in baseline["summaries"]
    }
    rows = []
    for row in current["summaries"]:
        key = (row["route"], row["viewport"], row["state"], row["mode"])
        notes = [*reasons, *([] if key in old else ["group absent from baseline"])]
        result = {
            "route": key[0],
            "viewport": key[1],
            "state": key[2],
            "mode": key[3],
            "comparable": not notes,
            "notes": notes,
        }
        if not notes:
            before = old[key]["ready_median_ms"]
            result.update(
                before_ready_ms=before,
                after_ready_ms=row["ready_median_ms"],
                ratio=row["ready_median_ms"] / before if before else None,
                before_n=old[key].get("n"),
                after_n=row.get("n"),
            )
        rows.append(result)
    return rows


def report(options, executions):
    """Write raw receipts and variance/overhead tables for compatible journey groups."""
    if len({row["fixture_sha256"] for row in executions}) != 1:
        msg = "Repeated browser fixture checksums differ"
        raise RuntimeError(msg)
    groups = defaultdict(list)
    for execution in executions:
        for sample in execution["samples"]:
            groups[
                (sample["route"], sample["viewport"], sample["state"], sample["mode"])
            ].append(sample)
    summaries = []
    for (route, viewport, state, mode), samples in sorted(groups.items()):
        values = [sample["ready_ms"] for sample in samples]
        lcp = [
            sample["observers"]["lcp"]["start_ms"]
            for sample in samples
            if sample["observers"] and sample["observers"]["lcp"]
        ]
        tasks = [
            len(sample["observers"]["long_tasks"])
            for sample in samples
            if sample["observers"] and "longtask" in sample["observers"]["supported"]
        ]
        summaries.append(
            {
                "route": route,
                "viewport": viewport,
                "state": state,
                "mode": mode,
                "n": len(values),
                "ready_median_ms": statistics.median(values),
                "ready_min_ms": min(values),
                "ready_max_ms": max(values),
                "ready_cv_percent": statistics.pstdev(values)
                / statistics.mean(values)
                * 100,
                "lcp_median_ms": statistics.median(lcp) if lcp else None,
                "long_tasks_median": statistics.median(tasks) if tasks else None,
                "network_requests_median": statistics.median(
                    len(sample["waterfall"]) for sample in samples
                )
                if mode != "control"
                else None,
                "browser_cpu_median_s": statistics.median(
                    sample["browser"]["cpu_s"] for sample in samples
                ),
                "runner_cpu_median_s": statistics.median(
                    sample["runner"]["cpu_s"] for sample in samples
                ),
            }
        )
    notes = [
        "Synthetic SQLite WSGI server; no personal browser/profile/session data is read or exported. Cookies, headers, bodies, console text and DOM text are excluded.",
        "Readiness = DOMContentLoaded + visible main/card selector + two animation frames. Pending deferred rows/HTMX are reported; this is not full application idle.",
        "Fresh means a new authenticated context and cleared isolated server cache; repeat reuses that context. HTTP caching is disabled by Playwright routing; service workers blocked. OS caches and DB buffers are not reset.",
        "LCP is the latest observed candidate at the bounded window, not a final Web Vital; null means unsupported/no candidate. Long tasks are tasks >=50 ms, capped at 10000; control mode does not install observers/listeners.",
        "Polling groups repeated fetch/xhr paths with queries/identifier segments removed. Repetition is not proof of a timer. Short windows are right-censored; no observed repetition does not mean no polling. Declared HTMX timer strings are retained.",
        "Python CPU includes the in-process server and Playwright driver callbacks. Browser CPU is a process-snapshot delta: exited processes are missed and new-process CPU includes startup. RSS sums double-count shared memory; PSS/USS totals are null if any listed process is unavailable.",
        "The Playwright Node driver and total machine resources are not measured. Mobile is viewport/touch emulation on desktop Chromium with DPR=1, not mobile CPU/network throttling.",
        "Browser resource collection is calibrated separately and lies outside operation timers. Opt-in profiles and instrument/control ratios are observations, not significance tests or production speedups.",
        "Provider HTTP raises a synthetic offline error; tasks are recorded but not run. Statistics All Time is prebuilt. Artwork/background completion is not represented. Navigation failures/auth redirects fail the run.",
    ]
    payload = {
        "schema_version": 1,
        "protocol": PROTOCOL,
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"],  # noqa: S607 -- fixed Git command
            cwd=ROOT,
            text=True,
        ).strip(),
        "tracked_tree_dirty": subprocess.run(
            ["git", "diff", "--quiet", "HEAD"],  # noqa: S607 -- fixed Git command
            cwd=ROOT,
            check=False,
        ).returncode
        != 0,
        "machine": common.machine(),
        "size": options.size,
        "seed": options.seed,
        "repeats": options.repeats,
        "command": [
            "python",
            "scripts/benchmark_browser.py",
            *[
                "<output>"
                if index and sys.argv[index] == "--output"
                else "<baseline>"
                if index and sys.argv[index] == "--baseline"
                else argument
                for index, argument in enumerate(sys.argv[1:])
            ],
        ],
        "observe_ms": options.observe_ms,
        "viewports": {key: VIEWPORTS[key] for key in options.viewports},
        "routes": options.routes,
        "states": options.states,
        "control": options.control,
        "profile": options.profile,
        "playwright_version": importlib.metadata.version("playwright"),
        "settings": {
            "clock": "2025-01-01T00:00:00Z",
            "server": "ThreadedWSGIServer",
            "debug": False,
            "cache": "isolated locmem",
            "broker": "memory://; tasks mocked",
            "http_cache": "disabled by routing",
            "service_workers": "blocked",
            "locale": "en-US",
            "timezone": "UTC",
            "color_scheme": "light",
            "device_scale_factor": 1,
            "browser_date_clock": "fixed epoch plus native monotonic elapsed; Performance/timers unchanged",
            "statistics_prebuilt": "All Time"
            if "statistics" in options.routes
            else None,
        },
        "source_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in (
                "scripts/benchmark_browser.py",
                "scripts/browser_journey_observers.js",
                "scripts/benchmark_fixtures.py",
                "src/app/benchmark_data.py",
                "uv.lock",
            )
        },
        "summaries": summaries,
        "executions": executions,
        "notes": notes,
    }
    payload["instrumentation_overhead"] = []
    by_group = {
        (row["route"], row["viewport"], row["state"], row["mode"]): row
        for row in summaries
    }
    for row in summaries:
        control = by_group.get((row["route"], row["viewport"], row["state"], "control"))
        if row["mode"] == "instrumented" and control:
            payload["instrumentation_overhead"].append(
                {
                    "route": row["route"],
                    "viewport": row["viewport"],
                    "state": row["state"],
                    "control_ready_ms": control["ready_median_ms"],
                    "instrumented_ready_ms": row["ready_median_ms"],
                    "ready_ratio": row["ready_median_ms"] / control["ready_median_ms"],
                    "control_n": control["n"],
                    "instrumented_n": row["n"],
                }
            )
    if options.baseline:
        raw = options.baseline.read_bytes()
        payload["baseline_sha256"] = hashlib.sha256(raw).hexdigest()
        payload["baseline_comparison"] = compare_reports(payload, json.loads(raw))
    (options.output / "report.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    )
    lines = [
        "# BENCH-03 browser journeys",
        "",
        f"Commit: `{payload['commit']}`; seed `{options.seed}`; size `{options.size}`; observation `{options.observe_ms} ms`.",
        f"Fixture SHA-256: `{executions[0]['fixture_sha256']}`",
        "",
        "| Route / viewport / state / mode | N | Ready median ms | Min-max ms | CV % |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in summaries:
        lines.append(  # noqa: PERF401 -- readable Markdown table
            f"| {row['route']} / {row['viewport']} / {row['state']} / {row['mode']} | {row['n']} | {row['ready_median_ms']:.2f} | {row['ready_min_ms']:.2f}-{row['ready_max_ms']:.2f} | {row['ready_cv_percent']:.1f} |"
        )
    lines += [
        "",
        "| Route / viewport / state / mode | LCP candidate ms | Long tasks | Requests | Browser CPU ms | Python CPU ms |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in summaries:
        lines.append(
            f"| {row['route']} / {row['viewport']} / {row['state']} / {row['mode']} | {row['lcp_median_ms']} | {row['long_tasks_median']} | {row['network_requests_median']} | {row['browser_cpu_median_s'] * 1000:.1f} | {row['runner_cpu_median_s'] * 1000:.1f} |"
        )
    lines += [
        "",
        "Null LCP/long-task/request metrics mean control disabled, unsupported or no candidate; raw observer support flags distinguish these cases.",
        "",
        "| Route / viewport / state | Instrumented / control readiness ratio |",
        "| --- | --- |",
    ]
    lines += [
        f"| {row['route']} / {row['viewport']} / {row['state']} | {row['ready_ratio']:.3f} |"
        for row in payload["instrumentation_overhead"]
    ]
    if not options.control:
        lines += ["", "Matched-control overhead unavailable: rerun with --control."]
    if options.baseline:
        lines += [
            "",
            "| Route / viewport / state / mode | New / baseline readiness ratio or incompatibility |",
            "| --- | --- |",
        ]
        for row in payload["baseline_comparison"]:
            value = row.get("ratio") if row["comparable"] else "; ".join(row["notes"])
            lines.append(
                f"| {row['route']} / {row['viewport']} / {row['state']} / {row['mode']} | {value} |"
            )
    lines += [
        "",
        "Machine: `" + json.dumps(payload["machine"], sort_keys=True) + "`",
        "",
    ]
    lines += [f"- {note}" for note in notes]
    lines += [
        "",
        "All navigation, LCP/long-task entries, request waterfalls, polling intervals and CPU/memory snapshots are in report.json and per-worker sample.json.",
    ]
    (options.output / "report.md").write_text("\n".join(lines) + "\n")


def main():
    """Run repeat workers in fresh processes; output directories must be new."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--size", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--observe-ms", type=int, default=1000)
    parser.add_argument(
        "--routes", choices=list(ROUTES), nargs="+", default=list(ROUTES)
    )
    parser.add_argument(
        "--viewports", choices=list(VIEWPORTS), nargs="+", default=list(VIEWPORTS)
    )
    parser.add_argument(
        "--states", choices=("fresh", "repeat"), nargs="+", default=["fresh", "repeat"]
    )
    parser.add_argument(
        "--control",
        action="store_true",
        help="Add matched journeys without observers/network listeners",
    )
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--repeat-index", type=int, default=1, help=argparse.SUPPRESS)
    parser.add_argument(
        "--profile",
        action="store_true",
        help="Add separate warm CPU-profile trials with sanitized .cpuprofile artifacts",
    )
    parser.add_argument(
        "--baseline", type=Path, help="Compare a matching BENCH-03 report.json"
    )
    options = parser.parse_args()
    options.output = options.output.resolve()
    if (
        options.size < 10
        or options.size % 10
        or options.repeats < 2
        or options.observe_ms < 100
    ):
        parser.error("Use size >=10 divisible by 10, repeats >=2, observe-ms >=100")
    if options.states not in (["fresh", "repeat"], ["fresh"]):
        parser.error("--states must be 'fresh' or 'fresh repeat' in that order")
    if options.worker:
        worker(options)
        return
    if (
        options.baseline
        and json.loads(options.baseline.read_text()).get("protocol") != PROTOCOL
    ):
        parser.error("--baseline requires a BENCH-03 report with matching protocol")
    options.output.mkdir(parents=True, exist_ok=False)
    receipts = []
    for repeat in range(1, options.repeats + 1):
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker",
            "--output",
            str(options.output / f"repeat-{repeat}"),
            "--size",
            str(options.size),
            "--seed",
            str(options.seed),
            "--observe-ms",
            str(options.observe_ms),
            "--repeat-index",
            str(repeat),
            "--routes",
            *options.routes,
            "--viewports",
            *options.viewports,
            "--states",
            *options.states,
        ]
        if options.control:
            command.append("--control")
        if options.profile:
            command.append("--profile")
        subprocess.run(  # noqa: S603 -- fixed interpreter/script, no shell
            command,
            cwd=ROOT,
            env={**os.environ, "TZ": "UTC", "PYTHONHASHSEED": "0"},
            check=True,
        )
        receipts.append(
            json.loads((options.output / f"repeat-{repeat}/sample.json").read_text())
        )
    report(options, receipts)
    print(f"Reports: {options.output / 'report.json'} and report.md")


if __name__ == "__main__":
    main()
