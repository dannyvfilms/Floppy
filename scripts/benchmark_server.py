# ruff: noqa: INP001, T201, PLR2004 -- opt-in standalone benchmark dimensions
"""BENCH-04: existing server timers, optional plans and controlled lock evidence."""

import argparse
import hashlib
import json
import logging
import os
import re
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import benchmark_fixtures as common  # noqa: E402

PROTOCOL = "bench04-server-v1"
ROUTES = {
    "home": "/",
    "movies": "/medialist/movie",
    "tv": "/medialist/tv",
    "music": "/medialist/music",
    "podcasts": "/medialist/podcast",
    "history": "/history",
    "collection": "/collection/",
    "lists": "/lists",
}
NOTES = [
    "No production speedup is claimed. Timings include instrumentation cost.",
    "Cold means cleared local cache and closed DB connection; OS/DB page caches remain warm.",
    "Django Client includes middleware/template rendering, excludes network/server queueing and static assets.",
    "SQL duration covers execute, including waits; cursor fetching outside execute is not separately timed.",
    "SQLite native busy-handler sleep and lock owner are unavailable in application requests. Failed execution duration is an upper bound, not pure lock wait.",
    "Controlled writer overlap attributes only this synthetic lock; it is not a production owner detector.",
    "PSS/USS are null when unsupported/denied; RSS includes shared pages. Snapshots are not peak memory.",
    "CPU is process CPU for outer samples, thread CPU in Server-Timing and contention trials; these overlap SQL/wall.",
    "Plans/profile are separate opt-in requests, not part of regular request timing. No EXPLAIN ANALYZE or raw SQL/parameters exported.",
    "Fixtures deterministic for pinned source/runtime/backend; timing, memory, scheduling and plans are variable. Small samples cannot establish significance.",
    "Providers fail offline and background publication is suppressed; LocMem cache and current-model schema are used, not production Redis/Celery or migration replay.",
]


class RequestMetrics(logging.Handler):
    """Read the existing middleware's numeric log fields without retaining logs."""

    def __init__(self):
        """Initialize an empty numeric-only sample sink."""
        super().__init__()
        self.samples = []

    def emit(self, record):
        """Extract allowlisted numeric fields from the existing log contract."""
        if record.getMessage().startswith("slow_request "):
            self.samples.append(
                {
                    key: float(value)
                    for key, value in re.findall(
                        r"\b(duration_ms|queries|cpu_ms|db_ms|provider_ms|provider_calls|inflight)=([0-9.]+)",
                        record.getMessage(),
                    )
                }
            )


def plan_summary(vendor, rows):
    """Allowlist structural plan fields; never export predicates or literals."""
    if vendor == "sqlite":
        return [
            {"id": row[0], "parent": row[1], "operation": str(row[3]).split()[0]}
            for row in rows
        ]
    root = rows[0][0][0]["Plan"]

    def node(value):
        result = {
            key: value[key]
            for key in (
                "Node Type",
                "Join Type",
                "Startup Cost",
                "Total Cost",
                "Plan Rows",
                "Plan Width",
            )
            if key in value
        }
        result["Plans"] = [node(child) for child in value.get("Plans", [])]
        return result

    return node(root)


def profile_request(connection, operation):
    """Reuse bounded SQL attribution and privately retain at most 32 SELECTs."""
    from app import request_timing

    statements = []
    dropped = 0

    def capture(execute, sql, params, many, context):
        nonlocal dropped
        # Only standalone SELECTs; never execute captured mutations or CTEs.
        if not many and sql.lstrip().upper().startswith("SELECT "):
            if len(statements) < 32:
                statements.append((sql, params))
            else:
                dropped += 1
        return execute(sql, params, many, context)

    with request_timing.profile_sql() as profile, connection.execute_wrapper(capture):
        _, timing = common.measure(operation)
    plans = []
    prefix = (
        "EXPLAIN QUERY PLAN "
        if connection.vendor == "sqlite"
        else "EXPLAIN (FORMAT JSON) "
    )
    with connection.cursor() as cursor:
        for index, (sql, params) in enumerate(statements):
            started = time.perf_counter()
            cursor.execute(prefix + sql, params)
            plans.append(
                {
                    "statement_index": index,
                    "fingerprint": hashlib.sha256(sql.encode()).hexdigest()[:16],
                    "wall_s": time.perf_counter() - started,
                    "plan": plan_summary(connection.vendor, cursor.fetchall()),
                }
            )
    # Existing normalizer's SQL shapes are deliberately omitted at this boundary.
    return {
        "timing": timing,
        "sql_profile": {
            "queries": [
                {key: value for key, value in row.items() if key != "shape"}
                for row in profile["queries"].values()
            ],
            "overflow_count": profile["overflow_count"],
        },
        "plans": plans,
        "selects_dropped": dropped,
    }


def lock_trials(path, runs):
    """Known synthetic SQLite writer; no access to the application database."""
    from django.db import OperationalError

    from app import db_diagnostics

    owner = sqlite3.connect(path, isolation_level=None)
    owner.execute("PRAGMA journal_mode=WAL")
    owner.execute("CREATE TABLE probe (id INTEGER PRIMARY KEY, value INTEGER)")
    owner.execute("INSERT INTO probe VALUES (1, 0)")
    results = []
    try:
        for scenario in ("uncontended", "released", "timeout"):
            for _ in range(runs):
                started_event = threading.Event()
                holder = {}
                if scenario != "uncontended":
                    owner.execute("BEGIN IMMEDIATE")
                    owner.execute("UPDATE probe SET value=value+1 WHERE id=1")

                def waiter(holder=holder, started_event=started_event):
                    db = sqlite3.connect(path, timeout=0.08, isolation_level=None)
                    memory_before = common.memory()
                    start, cpu = time.perf_counter(), time.thread_time()
                    holder["start"] = start
                    started_event.set()

                    def execute(sql, params, many, context):
                        try:
                            return db.execute(sql)
                        except sqlite3.OperationalError as error:
                            message = "Synthetic contention"
                            raise OperationalError(message) from error

                    try:
                        db_diagnostics.track_query(
                            execute,
                            "UPDATE probe SET value=value+1 WHERE id=1",
                            None,
                            False,
                            {},
                        )
                        holder["outcome"] = "ok"
                    except OperationalError as error:
                        info = db_diagnostics.describe_database_error(error)
                        holder.update(
                            outcome="busy",
                            sqlite_code=info.sqlite_code,
                            kind=info.kind,
                            failed_execution_ms=db_diagnostics._pop_wait_ms(),
                        )
                    finally:
                        holder.update(
                            end=time.perf_counter(),
                            cpu_s=time.thread_time() - cpu,
                            memory_before=memory_before,
                            memory_after=common.memory(),
                        )
                        db.close()

                thread = threading.Thread(target=waiter)
                thread.start()
                if not started_event.wait(timeout=10):
                    message = "Contention waiter did not start"
                    raise RuntimeError(message)
                if scenario == "released":
                    time.sleep(0.04)
                    owner.rollback()
                released = time.perf_counter() if scenario == "released" else None
                thread.join(timeout=10)
                if thread.is_alive() or "outcome" not in holder:
                    message = "Contention waiter did not complete"
                    raise RuntimeError(message)
                owner.rollback()
                end, start = holder.pop("end"), holder.pop("start")
                results.append(
                    {
                        "scenario": scenario,
                        "busy_timeout_ms": 80,
                        "known_owner": "synthetic_writer"
                        if scenario != "uncontended"
                        else None,
                        "execution_s": end - start,
                        "writer_overlap_s": max(0, min(end, released or end) - start)
                        if scenario != "uncontended"
                        else 0,
                        "native_busy_sleep_s": None,
                        **holder,
                    }
                )
    finally:
        owner.close()
        for suffix in ("", "-wal", "-shm"):
            Path(str(path) + suffix).unlink(missing_ok=True)
    return results


def worker(options, config):
    """Fresh process/current-model schema, synthetic user, no live services."""
    options.output.mkdir(parents=True, exist_ok=False)
    os.environ.update(
        SECRET="bench-only-disabled",  # noqa: S106 -- disposable synthetic key
        DJANGO_SETTINGS_MODULE="config.test_settings",
        FLOPPY_TEST_ALLOW_NETWORK="0",
    )
    sys.path.insert(0, str(ROOT / "src"))
    import django
    from django.conf import settings

    settings.DATABASES = {"default": config}
    settings.USING_SQLITE_DATABASE = options.database == "sqlite"
    settings.CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
    }
    settings.DEBUG = False
    settings.MEMORY_HIGH_WATER_ENABLED = False
    settings.ALLOWED_HOSTS = ["testserver"]
    settings.ALLAUTH_TRUSTED_CLIENT_IP_HEADER = None
    settings.CELERY_TASK_ALWAYS_EAGER = False
    settings.CELERY_BROKER_URL = "memory://"
    settings.PERF_LOG_SLOW_REQUEST_MS = 0
    settings.PERF_LOG_QUERY_COUNT_THRESHOLD = 0
    settings.LOGGING = {
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {"null": {"class": "logging.NullHandler"}},
        "root": {"handlers": ["null"], "level": "ERROR"},
        "loggers": {"app": {"handlers": ["null"], "propagate": False}},
    }
    django.setup()
    import requests
    from django.apps import apps
    from django.core.cache import cache
    from django.core.management import call_command
    from django.db import connection, connections
    from django.test import Client

    from app.benchmark_data import EPOCH, build_dataset
    from users.home_screen import ensure_home_screen_rows
    from users.models import HomeScreenRow, User

    settings.MIGRATION_MODULES = dict.fromkeys(
        app.label for app in apps.get_app_configs()
    )
    call_command("migrate", run_syncdb=True, verbosity=0)
    if options.database == "sqlite":
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA journal_mode=WAL")
    metrics = RequestMetrics()
    logger = logging.getLogger("app.middleware")
    logger.addHandler(metrics)
    logger.setLevel(logging.INFO)
    try:
        with (
            patch("django.utils.timezone.now", return_value=EPOCH),
            patch(
                "requests.sessions.Session.request",
                side_effect=requests.ConnectionError("Synthetic offline provider"),
            ) as providers,
            patch("celery.app.task.Task.apply_async", return_value=None) as tasks,
        ):
            models, generation = common.measure(
                lambda: build_dataset(options.size, options.seed)
            )
            user = User.objects.get(username="bench-user-1")
            ensure_home_screen_rows(user)
            checksum = common.export_fixture(
                [*models, HomeScreenRow], options.output / "fixture.json.gz"
            )
            client = Client()
            client.force_login(user)
            database = common.database_metadata(connection)
            if connection.vendor == "sqlite":
                with connection.cursor() as cursor:
                    cursor.execute("PRAGMA busy_timeout")
                    database["busy_timeout_ms"] = cursor.fetchone()[0]
            samples, profiles = [], {}

            def request(path):
                response = client.get(path)
                if response.status_code != 200:
                    message = (
                        f"Benchmark route failed with status {response.status_code}"
                    )
                    raise RuntimeError(message)
                return response

            modes = [False, True] if options.repeat_index % 2 else [True, False]
            for enabled in modes:
                settings.PERF_LOG_ENABLED = enabled
                # Construct middleware enabled once even when control is first.
                from app import request_timing

                request_timing.install_boundaries()
                for name in options.routes:
                    path = ROUTES[name]
                    for state in ("cold", "warm"):
                        if state == "warm":
                            request(path)
                        for _ in range(options.runs):
                            if state == "cold":
                                cache.clear()
                                connection.close()
                            metrics.samples.clear()
                            response, timing = common.measure(
                                lambda path=path: request(path)
                            )
                            samples.append(
                                {
                                    "route": name,
                                    "state": state,
                                    "mode": "enabled" if enabled else "control",
                                    "status": response.status_code,
                                    "bytes": len(response.content),
                                    "server_timing": response.get("Server-Timing"),
                                    "middleware": metrics.samples[-1]
                                    if enabled
                                    else None,
                                    **timing,
                                }
                            )
            if options.profile:
                settings.PERF_LOG_ENABLED = True
                for name in options.routes:
                    cache.clear()
                    connection.close()
                    profiles[name] = {
                        "state": "cold",
                        **profile_request(
                            connection, lambda name=name: request(ROUTES[name])
                        ),
                    }
            # Probe overhead separately, never subtract it from raw samples.
            _, probe = common.measure(lambda: [common.memory() for _ in range(20)])
            receipt = {
                "fixture_sha256": checksum,
                "size": options.size,
                "seed": options.seed,
                "database": database,
                "generation": generation,
                "samples": samples,
                "profiles": profiles,
                "memory_probe_20_calls": probe,
                "mocked_provider_calls": providers.call_count,
                "suppressed_tasks": tasks.call_count,
                "settings": {
                    "debug": False,
                    "memory_high_water_enabled": False,
                    "cache": "LocMem",
                    "broker": "memory",
                    "schema": "syncdb-current-models",
                    "clock": EPOCH.isoformat(),
                    "hash_seed": os.environ.get("PYTHONHASHSEED"),
                    "sql_profile": options.profile,
                    "runs": options.runs,
                },
                "sqlite_contention": lock_trials(
                    options.output / "lock.sqlite3", options.runs
                )
                if options.database == "sqlite"
                else None,
            }
            (options.output / "sample.json").write_text(
                json.dumps(receipt, indent=2) + "\n"
            )
    finally:
        logger.removeHandler(metrics)
        connections.close_all()
        if options.database == "sqlite":
            for suffix in ("", "-wal", "-shm"):
                Path(str(options.output / "dataset.sqlite3") + suffix).unlink(
                    missing_ok=True
                )


def summarize(values):
    """Keep variability explicit; no confidence claim from a few repetitions."""
    mean = statistics.mean(values)
    return {
        "n": len(values),
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
        "cv_pct": statistics.stdev(values) / mean * 100
        if len(values) > 1 and mean
        else None,
    }


def comparison(current, previous):
    """Only compare matching protocol, inputs, machine and instrumentation."""
    keys = ("protocol", "machine", "sources", "scenario")
    mismatch = [key for key in keys if current.get(key) != previous.get(key)]
    if mismatch:
        return {"compatible": False, "mismatches": mismatch, "wall_ratios": {}}
    return {
        "compatible": True,
        "mismatches": [],
        "wall_ratios": {
            key: value["wall_s"]["median"]
            / previous["summary"][key]["wall_s"]["median"]
            for key, value in current["summary"].items()
        },
    }


def report(options, receipts):
    """Portable raw samples, strict comparisons and readable tables."""
    summary = {}
    for name in options.routes:
        for state in ("cold", "warm"):
            for mode in ("control", "enabled"):
                rows = [
                    s
                    for r in receipts
                    for s in r["samples"]
                    if (s["route"], s["state"], s["mode"]) == (name, state, mode)
                ]
                summary[f"{name}/{state}/{mode}"] = {
                    field: summarize([s[field] for s in rows])
                    for field in ("wall_s", "cpu_s")
                }

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()  # noqa: S603, S607 -- fixed Git executable, no shell

    result = {
        "schema_version": 1,
        "protocol": PROTOCOL,
        "git": {
            "sha": git("rev-parse", "HEAD"),
            "dirty": bool(git("status", "--porcelain", "--untracked-files=normal")),
        },
        "sources": {
            path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            for path in (
                "scripts/benchmark_server.py",
                "scripts/benchmark_fixtures.py",
                "src/app/benchmark_data.py",
                "src/app/middleware.py",
                "src/app/request_timing.py",
                "src/app/db_diagnostics.py",
                "src/config/settings.py",
                "src/config/test_settings.py",
                "uv.lock",
            )
        },
        "machine": common.machine(),
        "command": [
            "python",
            "scripts/benchmark_server.py",
            "--size",
            str(options.size),
            "--seed",
            str(options.seed),
            "--runs",
            str(options.runs),
            "--repeats",
            str(options.repeats),
            "--database",
            options.database,
            "--routes",
            *options.routes,
            *(["--profile"] if options.profile else []),
            "--output",
            "<new-directory>",
        ],
        "scenario": {
            "fixtures": [r["fixture_sha256"] for r in receipts],
            "size": options.size,
            "seed": options.seed,
            "database": receipts[0]["database"],
            "settings": receipts[0]["settings"],
            "routes": options.routes,
            "repeats": options.repeats,
        },
        "notes": NOTES,
        "receipts": receipts,
        "summary": summary,
        "enabled_over_control_wall_ratios": {
            f"{name}/{state}": summary[f"{name}/{state}/enabled"]["wall_s"]["median"]
            / summary[f"{name}/{state}/control"]["wall_s"]["median"]
            for name in options.routes
            for state in ("cold", "warm")
        },
    }
    if options.baseline:
        result["comparison"] = comparison(
            result, json.loads(options.baseline.read_text())
        )
    (options.output / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    lines = [
        "# Server/database benchmark",
        "",
        f"Commit: `{result['git']['sha']}`. Protocol: `{PROTOCOL}`.",
        "",
        "Command: `" + " ".join(result["command"]) + "`",
        "",
        "| Route/state/mode | N | Wall median ms | CPU median ms | Wall CV % | Wall min-max ms |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for key, row in summary.items():
        w = row["wall_s"]
        lines.append(
            f"| {key} | {w['n']} | {w['median'] * 1000:.3f} | {row['cpu_s']['median'] * 1000:.3f} | {w['cv_pct']:.2f} | {w['min'] * 1000:.3f}-{w['max'] * 1000:.3f} |"
        )
    lines += [
        "",
        "## Existing middleware SQL totals",
        "",
        "| Route/state | Queries median | SQL execute median ms |",
        "|---|---:|---:|",
    ]
    for name in options.routes:
        for state in ("cold", "warm"):
            rows = [
                s["middleware"]
                for r in receipts
                for s in r["samples"]
                if s["route"] == name and s["state"] == state and s["mode"] == "enabled"
            ]
            lines.append(
                f"| {name}/{state} | {statistics.median(s['queries'] for s in rows):g} | {statistics.median(s['db_ms'] for s in rows):.3f} |"
            )
    lines += [
        "",
        "## Instrumentation overhead",
        "",
        "Enabled/control median wall ratios (order reversed in alternate workers):",
        "",
        "```json",
        json.dumps(result["enabled_over_control_wall_ratios"], indent=2),
        "```",
        "",
        "## Inputs and metric availability",
        "",
        f"Fixture checksums: `{result['scenario']['fixtures']}`.",
        "Machine, limits, process settings, raw timings, query totals, Server-Timing, SQL plans and memory snapshots are in report.json.",
        "",
    ]
    for index, receipt in enumerate(receipts, 1):
        memory = receipt["samples"][0]["memory_after_bytes"]
        lines.append(
            f"Worker {index} first memory snapshot: `{memory}`; null metrics unavailable. 20 memory probes: `{receipt['memory_probe_20_calls']}`."
        )
        for scenario in ("uncontended", "released", "timeout"):
            rows = [
                r["execution_s"]
                for r in receipt["sqlite_contention"] or []
                if r["scenario"] == scenario
            ]
            if rows:
                lines.append(
                    f"SQLite {scenario} execution seconds: `{summarize(rows)}`."
                )
    if options.database != "sqlite":
        lines += [
            "SQLite lock attribution unavailable for PostgreSQL; no PostgreSQL contention experiment is implied."
        ]
    if "comparison" in result:
        lines += [
            "",
            "## Baseline comparison",
            "",
            "```json",
            json.dumps(result["comparison"], indent=2),
            "```",
        ]
    lines += ["", "## Limits", "", *[f"- {note}" for note in NOTES]]
    (options.output / "report.md").write_text("\n".join(lines) + "\n")


def main():
    """Run separate workers and write comparison artifacts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--size", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument(
        "--database", choices=("sqlite", "postgresql"), default="sqlite"
    )
    parser.add_argument("--routes", nargs="+", choices=ROUTES, default=list(ROUTES))
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--repeat-index", type=int, default=1, help=argparse.SUPPRESS)
    options = parser.parse_args()
    options.output = options.output.resolve()
    if options.size < 10 or options.size % 10 or min(options.runs, options.repeats) < 2:
        parser.error("size must be >=10 divisible by 10; runs and repeats >=2")
    if options.worker:
        with common.disposable_database(options) as config:
            worker(options, config)
        return
    options.output.mkdir(parents=True, exist_ok=False)
    receipts = []
    for repeat in range(1, options.repeats + 1):
        target = options.output / f"repeat-{repeat}"
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker",
            "--output",
            str(target),
            "--size",
            str(options.size),
            "--seed",
            str(options.seed),
            "--runs",
            str(options.runs),
            "--database",
            options.database,
            "--repeat-index",
            str(repeat),
            "--routes",
            *options.routes,
        ]
        if options.profile:
            command.append("--profile")
        subprocess.run(  # noqa: S603 -- fixed interpreter and script, argument list only
            command,
            cwd=ROOT,
            check=True,
            env={**os.environ, "PYTHONHASHSEED": "0", "TZ": "UTC"},
        )
        receipts.append(json.loads((target / "sample.json").read_text()))
        print(f"Finished repeat={repeat}", flush=True)
    report(options, receipts)
    print("Reports: report.json and report.md", flush=True)


if __name__ == "__main__":
    main()
