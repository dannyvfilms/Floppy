# ruff: noqa: INP001, T201, PLR2004 -- standalone benchmark with explicit dimensions
"""Run isolated BENCH-01 fixtures through the BENCH-02 measurement protocol."""

import argparse
import contextlib
import gzip
import hashlib
import importlib.metadata
import io
import json
import os
import platform
import resource
import sqlite3
import statistics
import subprocess
import sys
import time
import zlib
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = "bench02-data-v1"


@contextlib.contextmanager
def disposable_database(options):
    """Create only a new benchmark database; destroy PostgreSQL even on failure."""
    if options.database == "sqlite":
        yield {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": str(options.output / "dataset.sqlite3"),
        }
        return
    import psycopg
    from psycopg import sql

    host = os.environ.get("BENCH_POSTGRES_HOST", "127.0.0.1")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        msg = "BENCH_POSTGRES_HOST must be loopback; use a disposable local server"
        raise ValueError(msg)
    user = os.environ.get("BENCH_POSTGRES_USER")
    if not user:
        msg = "PostgreSQL requires BENCH_POSTGRES_USER with CREATEDB on a disposable server"
        raise ValueError(msg)
    port = int(os.environ.get("BENCH_POSTGRES_PORT", "5432"))
    password = os.environ.get("BENCH_POSTGRES_PASSWORD", "")
    name = "floppy_bench02_" + uuid4().hex
    with psycopg.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        dbname="postgres",
        autocommit=True,
        connect_timeout=5,
    ) as admin:
        admin.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(
                sql.Identifier(name)
            )
        )
        try:
            yield {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": name,
                "HOST": host,
                "PORT": port,
                "USER": user,
                "PASSWORD": password,
                "OPTIONS": {"connect_timeout": 5},
            }
        finally:
            from django.db import connections

            connections.close_all()
            admin.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )


def phase_samples(operation, runs, reset):
    """Separate application-cache-cold samples from explicitly warmed samples."""
    cold = []
    for iteration in range(runs):
        _, reset_cost = measure(reset)
        _, sample = measure(operation)
        cold.append({**sample, "iteration": iteration + 1, "reset": reset_cost})
    operation()  # one explicit, unmeasured warm-up
    warm = [
        {**measure(operation)[1], "iteration": iteration + 1}
        for iteration in range(runs)
    ]
    return cold, warm


def database_metadata(connection):
    """Read a fixed allowlist of effective database settings without credentials."""
    with connection.cursor() as cursor:
        if connection.vendor == "sqlite":
            values = {}
            for name in (
                "journal_mode",
                "synchronous",
                "cache_size",
                "page_size",
                "foreign_keys",
            ):
                cursor.execute(f"PRAGMA {name}")
                values[name] = cursor.fetchone()[0]
            return {
                "engine": "sqlite",
                "version": sqlite3.sqlite_version,
                "settings": values,
                "storage": "fresh disposable file",
            }
        values = {}
        for name in (
            "server_version",
            "transaction_isolation",
            "max_connections",
            "shared_buffers",
            "work_mem",
        ):
            cursor.execute(f"SHOW {name}")
            values[name] = cursor.fetchone()[0]
        return {
            "engine": "postgresql",
            "version": values.pop("server_version"),
            "settings": values,
            "storage": "fresh disposable database",
        }


def memory(pid=None):
    """Return process bytes, explicitly identifying unsupported metrics."""
    result = {"rss": None, "uss": None, "pss": None}
    try:
        import psutil
    except ImportError:
        return result
    try:
        process = psutil.Process(pid) if pid is not None else psutil.Process()
        result["rss"] = process.memory_info().rss
        info = process.memory_full_info()
        result.update({key: getattr(info, key, None) for key in result})
    except (psutil.Error, OSError):
        pass  # Preserve RSS when the OS refuses USS/PSS access.
    return result


def measure(operation):
    """Measure process CPU and wall time; snapshots sit outside timed work."""
    before = memory()
    cpu, wall = time.process_time(), time.perf_counter()
    value = operation()
    elapsed = {"wall_s": time.perf_counter() - wall, "cpu_s": time.process_time() - cpu}
    elapsed.update(memory_before_bytes=before, memory_after_bytes=memory())
    return value, elapsed


def export_fixture(models, target):
    """Stream dependency-ordered Django JSON; gzip header excludes date/path."""
    from django.core import serializers

    def rows():
        for model in models:
            yield from model.objects.order_by("pk").iterator(chunk_size=500)

    with (
        target.open("wb") as raw,
        gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw,
            mtime=0,
        ) as compressed,
        io.TextIOWrapper(compressed, encoding="utf-8") as stream,
    ):
        serializers.serialize("json", rows(), stream=stream, ensure_ascii=True)
    digest = hashlib.sha256()
    with target.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def worker(options, database_config):
    """Use a fresh database, never the configured application database."""
    directory = options.output
    directory.mkdir(parents=True, exist_ok=False)
    database = directory / "dataset.sqlite3"
    # Set these before importing any application settings. Override .env values
    # via Django settings as well; no live database/cache/broker is opened.
    os.environ.update(
        SECRET="bench-only-disabled",  # noqa: S106 -- synthetic benchmark key
        DJANGO_SETTINGS_MODULE="config.test_settings",
        FLOPPY_DB_PATH=str(database),
        FLOPPY_TEST_ALLOW_NETWORK="0",
    )
    sys.path.insert(0, str(ROOT / "src"))
    import django
    from django.conf import settings

    settings.DATABASES = {"default": database_config}
    settings.USING_SQLITE_DATABASE = options.database == "sqlite"
    settings.DEBUG = False
    settings.CELERY_TASK_ALWAYS_EAGER = False
    settings.CELERY_BROKER_URL = "memory://"
    settings.CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
    }
    django.setup()
    from django.apps import apps
    from django.core.cache import cache
    from django.core.management import call_command
    from django.db import connection

    from app.benchmark_data import TRACKERS, build_dataset
    from app.library_query import LibraryQuery, LibraryQueryExecutor
    from app.models import CollectionEntry, Episode
    from users.models import User

    # Schema-only setup, not an upgrade test. No seed/data migration side effects.
    settings.MIGRATION_MODULES = dict.fromkeys(
        app.label for app in apps.get_app_configs()
    )
    _, schema = measure(lambda: call_command("migrate", run_syncdb=True, verbosity=0))
    models, generation = measure(lambda: build_dataset(options.size, options.seed))
    checksum, export = measure(
        lambda: export_fixture(models, directory / "fixture.json.gz")
    )
    database_info = database_metadata(connection)
    user = User.objects.get(username="bench-user-1")
    workloads = {
        media_type: lambda media_type=media_type: LibraryQueryExecutor(
            user,
            LibraryQuery(media_types=(media_type,)),
        ).page(0, 24)
        for media_type in ("movie", "tv", "music", "podcast")
    }
    workloads["episode_history"] = lambda: list(
        Episode.history.filter(history_user=user).order_by(
            "-history_date", "-history_id"
        )[:24],
    )
    workloads["collection"] = lambda: list(
        CollectionEntry.objects.filter(user=user)
        .select_related("item")
        .order_by("pk")[:24],
    )
    samples, cold_samples = {}, {}

    def reset():
        cache.clear()
        connection.close()

    for name, operation in workloads.items():
        cold_samples[name], samples[name] = phase_samples(
            operation, options.runs, reset
        )
    profile = {}
    if options.profile:
        import tracemalloc

        from django.test.utils import CaptureQueriesContext

        for name, operation in workloads.items():
            with CaptureQueriesContext(connection) as queries:
                tracemalloc.start()
                try:
                    _, timing = measure(operation)
                    _, peak = tracemalloc.get_traced_memory()
                finally:
                    tracemalloc.stop()
            normal = statistics.median(row["wall_s"] for row in samples[name])
            profile[name] = {
                **timing,
                "queries": len(queries),
                "python_peak_bytes": peak,
                "wall_ratio_to_unprofiled_median": timing["wall_s"] / normal,
            }
    cpu, wall = time.process_time(), time.perf_counter()
    for _ in range(50):
        memory()
    probe = {
        "calls": 50,
        "wall_s": time.perf_counter() - wall,
        "cpu_s": time.process_time() - cpu,
    }

    def no_operation():
        return None

    cpu, wall = time.process_time(), time.perf_counter()
    for _ in range(50):
        measure(no_operation)
    collector = {
        "calls": 50,
        "wall_s": time.perf_counter() - wall,
        "cpu_s": time.process_time() - cpu,
    }
    cpu, wall = time.process_time(), time.perf_counter()
    for _ in range(50):
        no_operation()
    collector["bare_calls"] = {
        "wall_s": time.perf_counter() - wall,
        "cpu_s": time.process_time() - cpu,
    }
    counts = {model._meta.label_lower: model.objects.count() for model in models}
    tracked = sum(counts[model._meta.label_lower] for model in dict.fromkeys(TRACKERS))
    if tracked != options.size:
        msg = f"Expected {options.size} tracking rows, got {tracked}"
        raise RuntimeError(msg)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    receipt = {
        "schema_version": 2,
        "protocol": PROTOCOL,
        "repeat": options.repeat_index,
        "seed": options.seed,
        "size": options.size,
        "fixture_sha256": checksum,
        "counts": counts,
        "schema": schema,
        "generation": generation,
        "export": export,
        "samples": samples,
        "cold_samples": cold_samples,
        "database": database_info,
        "process": {
            "role": "single synchronous Python worker",
            "debug": settings.DEBUG,
            "cache_backend": settings.CACHES["default"]["BACKEND"],
            "celery_eager": settings.CELERY_TASK_ALWAYS_EAGER,
            "celery_broker": "memory://",
            "provider_network": "blocked; HTTP and task dispatch mocked as failures",
            "schema_setup": "current models; migrations disabled",
            "warmup_calls_per_workload": 1,
            "runs_per_phase": options.runs,
            "phase_order": ["application_cold", "warm"],
            "cold_reset": [
                "clear isolated application cache",
                "close Django database connection",
            ],
            "os_database_page_cache": "not reset; fixture generation/export already touched data",
            "python_hash_seed": "0",
            "timezone": "UTC",
            "thread_limits": {
                key: int(value)
                if (value := os.environ.get(key, "")).isdecimal()
                else None
                for key in (
                    "OMP_NUM_THREADS",
                    "OPENBLAS_NUM_THREADS",
                    "MKL_NUM_THREADS",
                )
            },
            "database_conn_max_age": connection.settings_dict["CONN_MAX_AGE"],
        },
        "profile": profile,
        "memory_probe_overhead": probe,
        "collector_overhead": collector,
        "process_peak_rss_bytes": peak * (1 if sys.platform == "darwin" else 1024),
        "fixture_bytes": (directory / "fixture.json.gz").stat().st_size,
        "sqlite_bytes": database.stat().st_size
        if options.database == "sqlite"
        else None,
    }
    connection.close()
    if options.database == "sqlite" and not options.keep_database:
        database.unlink()
    (directory / "sample.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    )


def machine():
    """Record limits without usernames, hostnames, paths or environment secrets."""
    limits = {}
    for name in ("cpu.max", "memory.max", "cpuset.cpus.effective"):
        path = Path("/sys/fs/cgroup") / name
        limits[name] = path.read_text().strip() if path.exists() else None
    try:
        import psutil

        ram = psutil.virtual_memory().total
        try:
            affinity = psutil.Process().cpu_affinity()
        except (AttributeError, psutil.Error, OSError):
            affinity = None
        psutil_version = psutil.__version__
    except ImportError:
        ram, affinity, psutil_version = None, None, None
    return {
        "os": platform.system(),
        "release": platform.release(),
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "django": importlib.metadata.version("django"),
        "sqlite": sqlite3.sqlite_version,
        "zlib": zlib.ZLIB_RUNTIME_VERSION,
        "logical_cpus": os.cpu_count(),
        "cpu_model": platform.processor() or None,
        "cpu_affinity": affinity,
        "psutil": psutil_version,
        "ram_bytes": ram,
        "cgroup_v2": limits,
        "rlimit_cpu": [
            value if value != resource.RLIM_INFINITY else -1
            for value in resource.getrlimit(resource.RLIMIT_CPU)
        ],
        "rlimit_address_space": [
            value if value != resource.RLIM_INFINITY else -1
            for value in resource.getrlimit(resource.RLIMIT_AS)
        ],
    }


def baseline_comparison(current, baseline):
    """Compare only matching protocol, data, database and machine configurations."""
    if baseline.get("schema_version") != 2 or baseline.get("protocol") != PROTOCOL:
        msg = "Baseline requires BENCH-02 schema_version=2 and matching protocol (legacy BENCH-01 is not comparable)"
        raise ValueError(msg)
    output = []
    for size in sorted({row["size"] for row in current["executions"]}):
        new = [row for row in current["executions"] if row["size"] == size]
        old = [row for row in baseline["executions"] if row["size"] == size]
        reasons = []
        if not old:
            reasons.append("size absent from baseline")
        else:
            for key in ("seed", "fixture_sha256", "database"):
                if any(row[key] != new[0][key] for row in [*new, *old]):
                    reasons.append(f"{key} differs")  # noqa: PERF401 -- explicit compatibility checks
            # Repetitions may differ; the operation and cache-state definitions may not.
            for key in (
                "role",
                "debug",
                "cache_backend",
                "celery_eager",
                "celery_broker",
                "provider_network",
                "schema_setup",
                "warmup_calls_per_workload",
                "phase_order",
                "cold_reset",
                "os_database_page_cache",
                "python_hash_seed",
                "timezone",
                "database_conn_max_age",
                "thread_limits",
            ):
                if any(
                    row["process"][key] != new[0]["process"][key]
                    for row in [*new, *old]
                ):
                    reasons.append(f"process.{key} differs")  # noqa: PERF401 -- explicit compatibility checks
        if current["machine"] != baseline["machine"]:
            reasons.append("machine/runtime/limits differ")
        for state, field in (("application_cold", "cold_samples"), ("warm", "samples")):
            for workload in new[0][field]:
                row = {
                    "size": size,
                    "state": state,
                    "workload": workload,
                    "comparable": not reasons,
                    "notes": list(reasons),
                }
                if not reasons and any(
                    workload not in execution[field] for execution in old
                ):
                    row.update(
                        comparable=False, notes=["workload absent from baseline"]
                    )
                if row["comparable"]:
                    before = [
                        sample["wall_s"]
                        for execution in old
                        for sample in execution[field][workload]
                    ]
                    after = [
                        sample["wall_s"]
                        for execution in new
                        for sample in execution[field][workload]
                    ]
                    a, b = statistics.median(before), statistics.median(after)
                    row.update(
                        baseline_n=len(before),
                        current_n=len(after),
                        baseline_median_wall_s=a,
                        current_median_wall_s=b,
                        wall_ratio=b / a if a else None,
                        change_percent=(b / a - 1) * 100 if a else None,
                    )
                output.append(row)
    return output


def report(options, receipts):
    """Write raw samples plus a readable comparison with explicit variance."""
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],  # noqa: S607 -- fixed local Git invocation
        cwd=ROOT,
        text=True,
    ).strip()
    notes = [
        "Synthetic persisted import outcomes; no real user data, provider calls or importer throughput.",
        "In-process library/history/collection probes, not HTTP, Celery, Redis or deployment benchmarks.",
        "Application-cold means clear this isolated locmem cache and close the DB connection before each sample; warm means one unmeasured priming call then repeated requests. OS/DB page caches, Python imports and user-object caches are not reset.",
        "CPU is this Python process only. Memory is before/after snapshots, not sampled peaks; RSS peak is process lifetime.",
        "Null PSS/USS/RSS means unavailable (OS support, psutil absent or access denied). PSS is normally unavailable on macOS.",
        "Schema built from current models, not migrations. Portable fixture requires the same model schema; load only into an empty disposable DB.",
        "Determinism applies to fixture bytes within the same Python/Django/zlib versions; timings and memory vary with machine/cache/load.",
        "Memory probe collection is outside operation timers; profile ratios include SQL capture and tracemalloc overhead and are noisy single samples.",
        "No production instrumentation or speedup. Unprofiled samples are the instrumentation baseline; profiling is opt-in.",
        "cgroup null means unavailable; rlimit -1 means unlimited. Host RAM/CPU can exceed container allocation.",
        "Null CPU affinity/model means unavailable. Thread-limit null means unset/non-numeric. Collector calibration is timed end-to-end around empty calls; operation timers exclude memory snapshots and cold resets.",
        "Database-server, Redis, Celery and child-process CPU/memory are unavailable in this protocol; use the existing constrained/container harness for deployment measurements.",
    ]
    comparisons, lines = (
        [],
        [
            "# BENCH-02 unified data measurement",
            "",
            f"Commit: `{commit}`",
            f"Protocol: `{PROTOCOL}`; seed `{options.seed}`; database `{options.database}`; repeats `{options.repeats}`; samples per phase `{options.runs}`.",
            "",
            "| Size | SHA-256 equal | Generation wall s (min-max) |",
            "| --- | --- | --- |",
        ],
    )
    for size in options.sizes:
        group = [row for row in receipts if row["size"] == size]
        equal = len({row["fixture_sha256"] for row in group}) == 1
        if not equal:
            msg = f"Fixture checksum mismatch for size {size}"
            raise RuntimeError(msg)
        walls = [row["generation"]["wall_s"] for row in group]
        comparison = {
            "size": size,
            "checksums_equal": equal,
            "generation_wall_min_s": min(walls),
            "generation_wall_max_s": max(walls),
            "generation_wall_cv_percent": statistics.pstdev(walls)
            / statistics.mean(walls)
            * 100,
            "workloads": {},
        }
        lines.append(f"| {size} | {equal} | {min(walls):.3f}-{max(walls):.3f} |")
        for state, field in (("application_cold", "cold_samples"), ("warm", "samples")):
            for name in group[0][field]:
                values = [
                    sample["wall_s"] for row in group for sample in row[field][name]
                ]
                comparison["workloads"][f"{state}/{name}"] = {
                    "n": len(values),
                    "median_wall_s": statistics.median(values),
                    "min_wall_s": min(values),
                    "max_wall_s": max(values),
                    "cv_percent": statistics.pstdev(values)
                    / statistics.mean(values)
                    * 100,
                }
        comparisons.append(comparison)
    payload = {
        "schema_version": 2,
        "protocol": PROTOCOL,
        "commit": commit,
        "tracked_code_diff_sha256": hashlib.sha256(
            subprocess.check_output(
                [  # noqa: S607 -- fixed Git command
                    "git",
                    "diff",
                    "HEAD",
                    "--",
                    "scripts",
                    "src",
                    "pyproject.toml",
                    "uv.lock",
                ],
                cwd=ROOT,
            )
        ).hexdigest(),
        "tracked_tree_dirty": subprocess.run(
            ["git", "diff", "--quiet", "HEAD"],  # noqa: S607 -- fixed Git command
            cwd=ROOT,
            check=False,
        ).returncode
        != 0,
        "source_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in (
                "scripts/benchmark_fixtures.py",
                "src/app/benchmark_data.py",
                "uv.lock",
            )
        },
        "machine": machine(),
        "command": [
            "python",
            "scripts/benchmark_fixtures.py",
            *[
                "<output>"
                if index and sys.argv[index] == "--output"
                else "<baseline>"
                if index and sys.argv[index] == "--baseline"
                else argument
                for index, argument in enumerate(sys.argv[1:])
            ],
        ],
        "notes": notes,
        "comparisons": comparisons,
        "executions": receipts,
    }
    if options.baseline:
        baseline_bytes = options.baseline.read_bytes()
        payload["baseline_sha256"] = hashlib.sha256(baseline_bytes).hexdigest()
        payload["baseline_comparison"] = baseline_comparison(
            payload, json.loads(baseline_bytes)
        )
    (options.output / "report.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    )
    lines += [
        "",
        "| Size / workload | Samples | Median wall ms | Min-max ms | CV % |",
        "| --- | --- | --- | --- | --- |",
    ]
    for comparison in comparisons:
        for name, values in comparison["workloads"].items():
            lines.append(
                f"| {comparison['size']} / {name} | {values['n']} | "
                f"{values['median_wall_s'] * 1000:.3f} | "
                f"{values['min_wall_s'] * 1000:.3f}-{values['max_wall_s'] * 1000:.3f} | "
                f"{values['cv_percent']:.1f} |"
            )
    lines += [
        "",
        "| Size / repeat | Generate CPU s | Export CPU s | Peak RSS MiB | Collector us/call | Fixture SHA-256 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in receipts:
        cost = row["collector_overhead"]
        lines.append(
            f"| {row['size']} / {row['repeat']} | {row['generation']['cpu_s']:.3f} | "
            f"{row['export']['cpu_s']:.3f} | {row['process_peak_rss_bytes'] / 1048576:.1f} | "
            f"{cost['wall_s'] / cost['calls'] * 1e6:.1f} | `{row['fixture_sha256']}` |"
        )
    lines += [
        "",
        "Machine and limits: `" + json.dumps(payload["machine"], sort_keys=True) + "`",
        "",
        "Database: `" + json.dumps(receipts[0]["database"], sort_keys=True) + "`",
        "",
        "Process settings: `"
        + json.dumps(receipts[0]["process"], sort_keys=True)
        + "`",
        "",
    ]
    if options.baseline:
        lines += [
            "| Size / state / workload | Before median ms | After median ms | Change % / notes |",
            "| --- | --- | --- | --- |",
        ]
        for row in payload["baseline_comparison"]:
            label = f"{row['size']} / {row['state']} / {row['workload']}"
            if row["comparable"]:
                change = (
                    f"{row['change_percent']:.1f}%"
                    if row["change_percent"] is not None
                    else "baseline median is zero"
                )
                lines.append(
                    f"| {label} | {row['baseline_median_wall_s'] * 1000:.3f} | "
                    f"{row['current_median_wall_s'] * 1000:.3f} | {change} |"
                )
            else:
                lines.append(
                    f"| {label} | unavailable | unavailable | {'; '.join(row['notes'])} |"
                )
        lines += [
            "",
            "Changes are observations, not significance tests or production speedup claims.",
            "",
        ]
    lines += [f"- {note}" for note in notes]
    lines += [
        "",
        "Raw CPU/wall/memory samples, counts, checksums and overhead: `report.json` and each `sample.json`.",
    ]
    (options.output / "report.md").write_text("\n".join(lines) + "\n")


def main():
    """Run every size twice in fresh processes and refuse existing output paths."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sizes", type=int, nargs="+", default=[1000, 10000, 50000])
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--profile", action="store_true")
    parser.add_argument(
        "--database", choices=("sqlite", "postgresql"), default="sqlite"
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        help="Compare a BENCH-02 report.json with matching inputs/protocol",
    )
    parser.add_argument("--keep-database", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--size", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--repeat-index", type=int, default=1, help=argparse.SUPPRESS)
    options = parser.parse_args()
    options.output = options.output.resolve()
    if (
        options.repeats < 2
        or options.runs < 2
        or any(size < 10 or size % 10 for size in options.sizes)
    ):
        parser.error("Use repeats/runs >= 2 and sizes >= 10 divisible by 10")
    if options.worker:
        with (
            disposable_database(options) as config,
            patch(
                "requests.sessions.Session.request",
                side_effect=AssertionError("Unexpected provider HTTP in BENCH-02"),
            ) as http,
            patch(
                "celery.app.task.Task.apply_async",
                side_effect=AssertionError("Unexpected task dispatch in BENCH-02"),
            ) as dispatch,
        ):
            worker(options, config)
            if http.called or dispatch.called:
                msg = "A workload attempted provider HTTP or task dispatch; receipt is invalid"
                raise RuntimeError(msg)
        return
    if options.keep_database and options.database != "sqlite":
        parser.error(
            "--keep-database is SQLite-only; PostgreSQL databases are always destroyed"
        )
    if options.baseline:
        previous = json.loads(options.baseline.read_text())
        if previous.get("schema_version") != 2 or previous.get("protocol") != PROTOCOL:
            parser.error(
                "--baseline requires a BENCH-02 schema_version=2 report with matching protocol"
            )
    options.output.mkdir(parents=True, exist_ok=False)
    receipts = []
    for size in options.sizes:
        for repeat in range(options.repeats):
            directory = options.output / f"{size}-{repeat + 1}"
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                "--size",
                str(size),
                "--seed",
                str(options.seed),
                "--runs",
                str(options.runs),
                "--output",
                str(directory),
                "--database",
                options.database,
                "--repeat-index",
                str(repeat + 1),
            ]
            command += [
                flag
                for flag, enabled in (
                    ("--profile", options.profile),
                    ("--keep-database", options.keep_database),
                )
                if enabled
            ]
            subprocess.run(  # noqa: S603 -- fixed interpreter/script, argument list only
                command,
                cwd=ROOT,
                check=True,
                env={**os.environ, "PYTHONHASHSEED": "0", "TZ": "UTC"},
            )
            receipts.append(json.loads((directory / "sample.json").read_text()))
            print(f"Finished size={size} repeat={repeat + 1}", flush=True)
    report(options, receipts)
    print(f"Reports: {options.output / 'report.json'} and report.md")


if __name__ == "__main__":
    main()
