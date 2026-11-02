# ruff: noqa: INP001, T201, PLR2004, S108, S603, S607 -- fixed tmpfs paths and nofollow lock; standalone opt-in benchmark orchestration
"""BENCH-06: isolated application-quota matrix using existing offline workers."""

import argparse
import contextlib
import fcntl
import gzip
import hashlib
import json
import os
import runpy
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import benchmark_fixtures as common  # noqa: E402
from scripts import benchmark_server as server  # noqa: E402

PROTOCOL = "bench10-matrix-v2"
# Match constrained_benchmark.sh's application quotas, not whole-host limits.
PROFILES = {
    "minimal": {"cpus": 1, "memory": 1024**3},
    "constrained": {"cpus": 2, "memory": 2 * 1024**3},
}
NEW_FILES = (
    "scripts/benchmark_matrix.py",
    "scripts/Dockerfile.benchmark",
    "src/app/tests/test_benchmark_matrix.py",
)
NOTES = [
    "No production speedup claimed; this calibrates reliable comparisons and correctness under synthetic load.",
    "Profiles cap the application container (including synthetic Redis for Celery). PostgreSQL has a separate 0.5 CPU/256 MiB budget, not part of that cap.",
    "Containers share a physical host/VM. CPU quotas and a local lock do not eliminate external contention, thermal variation or noisy neighbors. Idle host probes are a screening gate, not proof of isolation.",
    "Hosted CI is rejected. Explicit dedicated self-hosted CI may run this manually; these artifacts are not PR timing gates.",
    "Container wall includes schema/fixture creation, worker startup/shutdown and serialization. Raw existing-worker samples retain separate generation, cold/warm or task timings.",
    "Sampler CPU and idle probe calibration are reported without subtraction. Observer-off keeps supervision and boundary reads; only periodic process/cgroup samples and calibration are disabled. Child-process probe cost is not separately isolated.",
    "Process snapshots may miss short-lived/exited processes. RSS sums double-count sharing; USS/PSS are null if unsupported/denied. Sampled memory maxima are not exact peaks; cgroup memory.peak is retained separately.",
    "Only synthetic fixtures and mocked providers; no production DB, broker, beat or HTTP server. Current-model schema is not migration replay. No production throughput or webhook claim.",
    "Fixture/plan/graph invariants repeat for pinned code/image/backend/seed; timings/resources and overlap pairs vary. Small N is calibration, not statistical significance.",
]


def ci_allowed(environment, dedicated):
    """Reject shared CI; require an explicit self-hosted dedicated declaration."""
    active = any(
        environment.get(key, "").lower() not in {"", "0", "false"}
        for key in ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "BUILD_BUILDID")
    )
    return not active or (
        dedicated and environment.get("RUNNER_ENVIRONMENT") == "self-hosted"
    )


def source_files(root):
    """Use tracked code plus this task's files; never archive local runtime data."""
    names = (
        subprocess.check_output(
            [
                "git",
                "ls-files",
                "-z",
                "src",
                "scripts",
                "mcp_server",
                "pyproject.toml",
                "uv.lock",
            ],
            cwd=root,
        )
        .decode()
        .split("\0")
    )
    result = []
    for name in sorted(set(filter(None, [*names, *NEW_FILES]))):
        path = root / name
        parts = Path(name).parts
        if any(
            part in {"db", "logs", "backups", ".git", ".venv"}
            or part.startswith(".env")
            for part in parts
        ):
            continue
        if path.is_symlink():
            message = "Source snapshots refuse symlinks"
            raise ValueError(message)
        if path.is_file() and path.suffix not in {".sqlite3", ".pyc"}:
            result.append(name)
    return result


def snapshot(root, target):
    """Copy a deterministic allowlisted build context and hash names/content."""
    digest = hashlib.sha256()
    for name in source_files(root):
        data = (root / name).read_bytes()
        digest.update(name.encode() + b"\0" + hashlib.sha256(data).digest())
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    (target / "source-manifest.json").write_text(
        json.dumps(
            {
                name: hashlib.sha256((target / name).read_bytes()).hexdigest()
                for name in source_files(root)
            },
            sort_keys=True,
        )
    )
    return digest.hexdigest()


def source_worker(script, arguments, output):
    """Assert actual imported project code against the frozen image manifest."""
    manifest = json.loads((ROOT / "source-manifest.json").read_text())
    previous_argv = sys.argv
    sys.argv = [str(ROOT / "scripts" / script), *arguments]
    try:
        runpy.run_path(sys.argv[0], run_name="__main__")
    finally:
        origins = {}
        failures = []
        for name, module in list(sys.modules.items()):
            path = getattr(module, "__file__", None)
            if not path:
                continue
            path = Path(path).resolve()
            owned = name.split(".")[0] in {
                "app",
                "api",
                "config",
                "events",
                "integrations",
                "lists",
                "users",
            }
            if path.is_relative_to(ROOT) and ".venv" not in path.parts:
                relative = path.relative_to(ROOT).as_posix()
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
                origins[relative] = actual
                if manifest.get(relative) != actual:
                    failures.append(relative)
            elif owned:
                failures.append(name + ":outside-frozen-root")
        relative = "scripts/" + script
        actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        origins[relative] = actual
        if manifest.get(relative) != actual:
            failures.append(relative)
        Path(output).write_text(
            json.dumps(
                {
                    "passed": not failures,
                    "loaded_sha256": origins,
                    "failures": failures,
                    "root": str(ROOT),
                },
                indent=2,
            )
            + "\n"
        )
        sys.argv = previous_argv
        if failures:
            message = "Loaded source does not match frozen manifest"
            raise RuntimeError(message)


def boundary(event):
    """Record lifecycle clocks without process arguments or environment."""
    return {
        "event": event,
        "wall_epoch_s": time.time(),
        "monotonic_s": time.monotonic(),
    }


def support_snapshot(container):
    """Read owned service and shared VM counters without commands/credentials."""
    result = {
        "boundary": boundary("support_snapshot"),
        "cpu_usage_usec": None,
        "vm_cpu_ticks": None,
        "memory_available_bytes": None,
        "cpu_pressure": None,
        "external_cpu_s": None,
        "scope": "owned PostgreSQL cgroup; /proc counters span shared Linux VM",
    }
    if not container:
        result["scope"] = "PostgreSQL absent"
        return result
    command = "cat /sys/fs/cgroup/cpu.stat; echo VM; head -n 1 /proc/stat; echo MEM; cat /proc/meminfo; echo PSI; cat /proc/pressure/cpu"
    try:
        raw = run(["docker", "exec", container, "sh", "-c", command])
        cpu, rest = raw.split("VM\n", 1)
        vm, rest = rest.split("MEM\n", 1)
        memory, pressure = rest.split("PSI\n", 1)
        result["cpu_usage_usec"] = int(
            dict(line.split() for line in cpu.splitlines())["usage_usec"]
        )
        result["vm_cpu_ticks"] = [int(value) for value in vm.split()[1:9]]
        result["memory_available_bytes"] = (
            int(
                next(
                    line.split()[1]
                    for line in memory.splitlines()
                    if line.startswith("MemAvailable:")
                )
            )
            * 1024
        )
        result["cpu_pressure"] = pressure.strip()
    except (subprocess.CalledProcessError, ValueError, KeyError, StopIteration):
        result["unsupported"] = "service counters unavailable"
    return result


def cleanup_owned(containers):
    """Remove only owned IDs and verify their absence; retain shutdown tail."""
    events = [boundary("service_shutdown_start")]
    receipts = {}
    for role, container in containers.items():
        if not container:
            continue
        removed = subprocess.run(
            ["docker", "rm", "-f", "-v", container],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        try:
            remaining = run(
                ["docker", "ps", "--all", "--no-trunc", "--format", "{{.ID}}"]
            )
            absent = container not in remaining.splitlines()
        except subprocess.CalledProcessError:
            absent = False  # Daemon failure is not evidence of absence.
        receipts[role] = {"remove_exit": removed, "absence_verified": absent}
    events.append(boundary("cleanup_verified"))
    return {
        "events": events,
        "containers": receipts,
        "passed": all(
            r["remove_exit"] == 0 and r["absence_verified"] for r in receipts.values()
        ),
    }


def run(command, **kwargs):
    """Run fixed argument lists, never shell strings."""
    return subprocess.check_output(command, text=True, **kwargs).strip()


def cgroup():
    """Read bounded cgroup-v2 metrics; leave unavailable counters null."""
    result = {}
    for name in (
        "cpu.max",
        "cpu.stat",
        "cpu.pressure",
        "memory.max",
        "memory.current",
        "memory.peak",
        "memory.events",
        "io.stat",
        "pids.max",
    ):
        try:
            result[name] = (Path("/sys/fs/cgroup") / name).read_text()[:12000].strip()
        except OSError:
            result[name] = None
    return result


def process_sample(process, labels):
    """Collect this container's process tree without exporting IDs or arguments."""
    import psutil

    rows = []
    for child in [process, *process.children(recursive=True)]:
        try:
            key = (child.pid, child.create_time())
            label = labels.setdefault(key, f"process-{len(labels) + 1}")
            cpu = child.cpu_times()
            rows.append(
                {
                    "process": label,
                    "pid": child.pid,
                    "start_epoch_s": child.create_time(),
                    "cpu_s": cpu.user + cpu.system,
                    "memory_bytes": common.memory(child.pid),
                }
            )
        except (psutil.Error, OSError):
            continue
    return rows


def correctness(workload, receipt, fixture, seed, size):
    """Verify raw exported inputs and existing worker-specific load invariants."""
    expected = receipt["fixture_sha256"]
    if hashlib.sha256(fixture.read_bytes()).hexdigest() != expected:
        message = "Portable fixture checksum mismatch"
        raise ValueError(message)
    # Validate portable JSON format independently, not only a producer counter.
    with gzip.open(fixture, "rt") as stream:
        rows = json.load(stream)
    users = [row for row in rows if row["model"] == "users.user"]
    if len(users) != 3 or any(
        not row["fields"]["username"].startswith("bench-user-") for row in users
    ):
        message = "Fixture users are not the expected synthetic dataset"
        raise ValueError(message)
    if workload == "fixtures":
        if receipt["size"] != size or receipt["seed"] != seed:
            message = "Fixture input mismatch"
            raise ValueError(message)
        actual_counts = Counter(row["model"] for row in rows)
        if any(
            actual_counts.get(model, 0) != count
            for model, count in receipt["counts"].items()
        ):
            message = "Portable fixture model counts disagree with workload counts"
            raise ValueError(message)
        invariants = {"model_counts": receipt["counts"], "users": 3}
    else:
        checksums = {
            job["job"]: hashlib.pbkdf2_hmac(
                "sha256", b"bench05", str(seed).encode(), job["iterations"]
            ).hex()
            for job in receipt["plan"]
        }
        for measurement in receipt["measurements"]:
            for job, result in zip(
                receipt["plan"], measurement["body_results"], strict=True
            ):
                if (
                    result["checksum"] != checksums[job["job"]]
                    or result["attempt"] != int(job["retry_once"])
                    or result["provider_calls"] != job["calls"]
                ):
                    message = "Load changed deterministic task results"
                    raise ValueError(message)
        traced = next(
            m["trace"] for m in receipt["measurements"] if m["mode"] == "enabled"
        )
        ends = [
            e
            for attempt in traced["attempts"]
            for e in attempt["events"]
            if e["event"] == "end"
        ]
        if (
            traced["incomplete_attempts"]
            or traced["duplicate_attempts"]
            or not traced["overlap"]
            or len(ends) != 7
            or sum(e["provider_calls"] for e in ends) != 9
        ):
            message = "Load trace invariants failed"
            raise ValueError(message)
        invariants = {
            "logical_jobs": 6,
            "attempts": 7,
            "provider_calls": 9,
            "event_graph": traced["event_checksum"],
            "plan_sha256": receipt["plan_sha256"],
            "inventory_sha256": receipt["inventory_sha256"],
        }
    return {"passed": True, "fixture_sha256": expected, "invariants": invariants}


def container_worker(options):
    """Supervise an existing offline worker with opt-in process/cgroup sampling."""
    import psutil

    directory = options.output
    directory.mkdir(parents=True, exist_ok=True)
    script = (
        "benchmark_fixtures.py"
        if options.workload == "fixtures"
        else "benchmark_celery.py"
    )
    command = [
        sys.executable,
        str(ROOT / "scripts" / script),
        "--worker",
        "--size",
        str(options.size),
        "--seed",
        str(options.seed),
        "--database",
        options.database,
        "--repeat-index",
        str(options.repeat_index),
        "--output",
        str(directory / "work"),
    ]
    if options.workload == "fixtures":
        command += ["--runs", str(options.runs)]
    command = [
        sys.executable,
        "-c",
        "from scripts.benchmark_matrix import source_worker; import sys; "
        "source_worker(sys.argv[1], sys.argv[3:], sys.argv[2])",
        script,
        str(directory / "origins.json"),
        *command[2:],
    ]
    if options.workload in {"empty", "idle"}:
        command = [
            sys.executable,
            "-c",
            "import time; time.sleep("
            + str(options.control_seconds if options.workload == "idle" else 0)
            + ")",
        ]
    labels = {}
    parent = psutil.Process()
    cpu, started = time.process_time(), time.perf_counter()
    for _ in range(20 if options.observer == "on" else 0):
        process_sample(parent, labels)
    calibration = {
        "calls": 20 if options.observer == "on" else 0,
        "wall_s": time.perf_counter() - started,
        "cpu_s": time.process_time() - cpu,
    }
    from scripts import container_memory_sample as memory_sampler
    from scripts.memory_aging_report import exposure_summary, resource_delta

    before = cgroup()
    resource_before = memory_sampler.sample()
    started, cpu = time.perf_counter(), time.process_time()
    samples = []
    with (directory / "worker.log").open("w") as log:
        child = subprocess.Popen(command, stdout=log, stderr=log)
        while child.poll() is None:
            if options.observer == "on":
                samples.append(
                    {
                        "elapsed_s": time.perf_counter() - started,
                        "exposure": {"start": memory_sampler._clocks()},
                        "processes": process_sample(parent, labels),
                        "cgroup": cgroup(),
                    }
                )
            with contextlib.suppress(subprocess.TimeoutExpired):
                child.wait(timeout=options.sample_interval)
    wall = time.perf_counter() - started
    sampler_cpu = time.process_time() - cpu
    if child.returncode:
        message = "Offline worker failed; inspect the private worker.log"
        raise RuntimeError(message)
    if options.workload in {"empty", "idle"}:
        receipt = {"control": options.workload, "observer": options.observer}
        check = {"passed": True, "fixture_sha256": None, "invariants": receipt}
        origins = None
        units = 0
    else:
        receipt = json.loads((directory / "work/sample.json").read_text())
        check = correctness(
            options.workload,
            receipt,
            directory / "work/fixture.json.gz",
            options.seed,
            options.size,
        )
        origins = json.loads((directory / "origins.json").read_text())
        units = (
            options.size
            if options.workload == "fixtures"
            else 6 * len(receipt["measurements"])
        )
    resource_after = memory_sampler.sample()
    exposure = exposure_summary([resource_before, *samples, resource_after])
    result = {
        "protocol": PROTOCOL,
        "wall_s": wall,
        "observer": options.observer,
        "loaded_origins": origins,
        "completed_units": units,
        "throughput_units_per_s": units / wall,
        "throughput_scope": "fixture items or logical Celery jobs per supervised worker wall including setup",
        "redis_scope": "embedded application cgroup for celery; separate CPU unavailable"
        if options.workload == "celery"
        else "absent",
        "sampler_cpu_s": sampler_cpu,
        "calibration": calibration,
        "cgroup_before": before,
        "cgroup_after": cgroup(),
        "resource_before": resource_before,
        "resource_after": resource_after,
        "resource_delta": resource_delta(resource_before, resource_after),
        "exposure": exposure,
        "samples": samples,
        "correctness": check,
        "runtime": common.machine(),
        "receipt": receipt,
    }
    (directory / "cell.json").write_text(json.dumps(result, indent=2) + "\n")


def compatible(current, previous, code_change=False):
    """Withhold ratios when metadata, correctness or noise invalidates a run."""
    keys = (
        ["method_sha256", "runtime_sha256"]
        if code_change
        else ["source_sha256", "image"]
    )
    mismatch = [
        key
        for key in (
            *keys,
            "protocol",
            "postgres_image",
            "policy",
            "host",
            "inputs",
            "container_host",
            "docker_server_version",
        )
        if current.get(key) != previous.get(key)
    ]
    if not current["eligible"] or not previous.get("eligible"):
        mismatch.append("quality_gate")
    if mismatch:
        return {"compatible": False, "mismatches": mismatch, "wall_ratios": {}}
    return {
        "compatible": True,
        "mismatches": [],
        "wall_ratios": {
            name: row["median"] / previous["summary"][name]["median"]
            for name, row in current["summary"].items()
        },
    }


def host_noise():
    """Screen idle host utilization outside timed container execution."""
    import psutil

    return {
        "scope": "controller OS global; Docker VM attribution unknown",
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "available_ram_bytes": psutil.virtual_memory().available,
    }


def wait_for_idle(maximum, timeout):
    """Bound settling after builds; retain failed qualification instead of hiding it."""
    started = time.monotonic()
    observations, quiet = [], 0
    while True:
        observation = host_noise()
        observations.append(observation)
        quiet = quiet + 1 if observation["cpu_percent"] <= maximum else 0
        if quiet >= 2 or time.monotonic() - started >= timeout:
            return {
                "qualified": quiet >= 2,
                "samples": observations,
                "wall_s": time.monotonic() - started,
            }


def matrix(options):
    """Build a safe source image and run serial, capped, disposable cells."""
    if not ci_allowed(os.environ, options.dedicated_host):
        message = "Shared CI is forbidden; dedicated self-hosted CI requires --dedicated-host and RUNNER_ENVIRONMENT=self-hosted"
        raise ValueError(message)
    options.output.mkdir(parents=True, exist_ok=False)
    lock_fd = os.open(
        "/tmp/floppy-benchmark-matrix.lock",
        os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
        0o600,
    )
    with (
        os.fdopen(lock_fd, "w"),
        tempfile.TemporaryDirectory(prefix="floppy-bench06-") as scratch,
    ):
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lifecycle = [boundary("setup_start")]
        source_sha = snapshot(ROOT, Path(scratch))
        image = options.image or f"floppy:bench06-{source_sha[:12]}"
        if options.build:
            with (options.output / "build.log").open("w") as log:
                subprocess.run(
                    [
                        "docker",
                        "build",
                        "-f",
                        str(Path(scratch) / "scripts/Dockerfile.benchmark"),
                        "--label",
                        f"org.floppy.benchmark.source={source_sha}",
                        "-t",
                        image,
                        scratch,
                    ],
                    check=True,
                    stdout=log,
                    stderr=log,
                )
        lifecycle.append(boundary("build_complete"))
        metadata = json.loads(run(["docker", "image", "inspect", image]))[0]
        if (metadata["Config"]["Labels"] or {}).get(
            "org.floppy.benchmark.source"
        ) != source_sha:
            message = "Benchmark image source mismatch; use --build"
            raise ValueError(message)
        image_id = metadata["Id"]
        pg_image = (
            json.loads(run(["docker", "image", "inspect", options.postgres_image]))[0][
                "Id"
            ]
            if "postgresql" in options.databases
            else None
        )
        cells = []
        for profile in options.profiles:
            quota = PROFILES[profile]
            for database in options.databases:
                for workload in options.workloads:
                    for repeat in range(1, options.repeats + 1):
                        key = f"{profile}/{database}/{workload}"
                        target = (
                            options.output / profile / database / workload / str(repeat)
                        )
                        target.mkdir(parents=True)
                        postgres = application = None
                        cell_events = [boundary("cell_setup_start")]
                        cell = None
                        settling = wait_for_idle(
                            options.max_host_cpu_percent, options.quiet_wait_seconds
                        )
                        noise_before = settling["samples"][-1]
                        try:
                            if database == "postgresql":
                                postgres = run(
                                    [
                                        "docker",
                                        "run",
                                        "--detach",
                                        "--network",
                                        "none",
                                        "--cpus",
                                        "0.5",
                                        "--memory",
                                        "256m",
                                        "--memory-swap",
                                        "256m",
                                        "--pids-limit",
                                        "128",
                                        "--shm-size",
                                        "128m",
                                        "-e",
                                        "POSTGRES_USER=bench",
                                        "-e",
                                        "POSTGRES_PASSWORD=bench",
                                        *(
                                            [
                                                "--tmpfs",
                                                "/var/lib/postgresql/data:rw,size=128m",
                                            ]
                                            if options.postgres_tmpfs
                                            else []
                                        ),
                                        pg_image,
                                    ]
                                )
                                for _ in range(120):
                                    if (
                                        subprocess.run(
                                            [
                                                "docker",
                                                "exec",
                                                postgres,
                                                "pg_isready",
                                                "-U",
                                                "bench",
                                            ],
                                            stdout=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL,
                                            check=False,
                                        ).returncode
                                        == 0
                                    ):
                                        break
                                    time.sleep(0.25)
                                else:
                                    message = (
                                        "Disposable PostgreSQL did not become ready"
                                    )
                                    raise RuntimeError(message)
                            command = [
                                "docker",
                                "run",
                                "--detach",
                                "--read-only",
                                "--network",
                                f"container:{postgres}" if postgres else "none",
                                "--cpus",
                                str(quota["cpus"]),
                                "--memory",
                                str(quota["memory"]),
                                "--memory-swap",
                                str(quota["memory"]),
                                "--pids-limit",
                                "128",
                                "--tmpfs",
                                "/tmp:rw,size=128m",
                                "-v",
                                f"{target}:/out",
                                "-e",
                                "FLOPPY_DATA_DIR=/tmp/data",
                                "-e",
                                "LOG_DIR=/tmp/logs",
                                "-e",
                                "BENCH_POSTGRES_USER=bench",
                                "-e",
                                "BENCH_POSTGRES_PASSWORD=bench",
                                image_id,
                                "--output",
                                "/out",
                                "--workload",
                                workload,
                                "--database",
                                database,
                                "--size",
                                str(options.size),
                                "--seed",
                                str(options.seed),
                                "--runs",
                                str(options.runs),
                                "--repeat-index",
                                str(repeat),
                                "--sample-interval",
                                str(options.sample_interval),
                                "--observer",
                                options.observer,
                                "--control-seconds",
                                str(options.control_seconds),
                            ]
                            support_before = support_snapshot(postgres)
                            cell_events.append(boundary("workload_launch"))
                            application = run(command)
                            status = run(["docker", "wait", application])
                            cell_events.append(boundary("application_exit"))
                            inspection = json.loads(
                                run(["docker", "inspect", application])
                            )[0]
                            if status != "0":
                                (target / "container.log").write_text(
                                    run(
                                        ["docker", "logs", application],
                                        stderr=subprocess.STDOUT,
                                    )
                                )
                                message = f"Matrix cell failed: {key}; inspect its container.log"
                                raise RuntimeError(message)
                            result = json.loads((target / "cell.json").read_text())
                            actual = {
                                "nano_cpus": inspection["HostConfig"]["NanoCpus"],
                                "memory_bytes": inspection["HostConfig"]["Memory"],
                                "swap_bytes": inspection["HostConfig"]["MemorySwap"],
                                "pids_limit": inspection["HostConfig"]["PidsLimit"],
                                "oom_killed": inspection["State"]["OOMKilled"],
                            }
                            cell = {
                                "key": key,
                                "repeat": repeat,
                                "limits": actual,
                                "noise_before": noise_before,
                                "settling": settling,
                                "noise_before_cleanup": host_noise(),
                                "lifecycle": cell_events,
                                "postgresql_before": support_before,
                                "postgresql_after": support_snapshot(postgres),
                                "application_identity": {
                                    "container_id": application,
                                    "started_at": inspection["State"]["StartedAt"],
                                    "finished_at": inspection["State"]["FinishedAt"],
                                },
                                **result,
                            }
                            cells.append(cell)
                            print(f"Finished {key} repeat={repeat}", flush=True)
                        finally:
                            if postgres:
                                with contextlib.suppress(subprocess.CalledProcessError):
                                    (target / "postgresql.log").write_text(
                                        run(
                                            ["docker", "logs", postgres],
                                            stderr=subprocess.STDOUT,
                                        )
                                    )
                            cleanup = cleanup_owned(
                                {"application": application, "postgresql": postgres}
                            )
                            post = host_noise()
                            (target / "cleanup.json").write_text(
                                json.dumps(
                                    {
                                        "cleanup": cleanup,
                                        "noise_after": post,
                                        "lifecycle": cell_events,
                                    },
                                    indent=2,
                                )
                                + "\n"
                            )
                            if cell is not None:
                                cell["cleanup"] = cleanup
                                cell["noise_after"] = post
        summary = {
            key: server.summarize(
                [cell["wall_s"] for cell in cells if cell["key"] == key]
            )
            for key in sorted({c["key"] for c in cells})
        }
        issues = []
        for cell in cells:
            if not cell["cleanup"]["passed"]:
                issues.append("cleanup_unverified")
            if not cell["settling"]["qualified"]:
                issues.append("host_did_not_settle")
            profile = cell["key"].split("/")[0]
            if (
                cell["limits"]["nano_cpus"] != PROFILES[profile]["cpus"] * 10**9
                or cell["limits"]["memory_bytes"] != PROFILES[profile]["memory"]
                or cell["limits"]["swap_bytes"] != PROFILES[profile]["memory"]
                or cell["limits"]["oom_killed"]
            ):
                issues.append("container_limits_or_oom")
            if (
                max(
                    cell["noise_before"]["cpu_percent"],
                    cell["noise_after"]["cpu_percent"],
                    cell["noise_before_cleanup"]["cpu_percent"],
                )
                > options.max_host_cpu_percent
            ):
                issues.append("host_cpu_noise")
        # Profile-dependent schedules are recorded per cell; data and work
        # results must still agree across quotas for each backend/workload.
        inputs, datasets = {}, {}
        for cell in cells:
            key = cell["key"]
            check = cell["correctness"]
            if key in inputs and inputs[key] != check:
                issues.append("correctness_or_input_drift")
            inputs[key] = check
            data_key = "/".join(key.split("/")[1:])
            data = {
                "fixture_sha256": check["fixture_sha256"],
                "invariants": {
                    name: value
                    for name, value in check["invariants"].items()
                    if name != "inventory_sha256"
                },
            }
            if data_key in datasets and datasets[data_key] != data:
                issues.append("cross_profile_result_drift")
            datasets[data_key] = data
        report = {
            "schema_version": 2,
            "lifecycle": lifecycle,
            "protocol": PROTOCOL,
            "git_sha": run(["git", "rev-parse", "HEAD"], cwd=ROOT),
            "source_sha256": source_sha,
            "image": image_id,
            "postgres_image": pg_image,
            "runtime_sha256": hashlib.sha256(
                json.dumps(metadata["RootFS"]["Layers"][:-2]).encode()
            ).hexdigest(),
            "method_sha256": hashlib.sha256(
                b"".join(
                    name.encode()
                    + hashlib.sha256((Path(scratch) / name).read_bytes()).digest()
                    for name in json.loads(
                        (Path(scratch) / "source-manifest.json").read_text()
                    )
                    if name.startswith("scripts/benchmark_")
                    or name
                    in {
                        "scripts/celery_trace.py",
                        "scripts/container_memory_sample.py",
                        "scripts/memory_aging_report.py",
                        "scripts/Dockerfile.benchmark",
                        "src/app/benchmark_data.py",
                        "src/config/test_settings.py",
                        "src/config/test_network.py",
                        "uv.lock",
                        "pyproject.toml",
                    }
                )
            ).hexdigest(),
            "host": common.machine(),
            "container_host": cells[0]["runtime"],
            "docker_server_version": run(
                ["docker", "version", "--format", "{{.Server.Version}}"]
            ),
            "inputs": inputs,
            "policy": {
                "profiles": options.profiles,
                "databases": options.databases,
                "workloads": options.workloads,
                "size": options.size,
                "seed": options.seed,
                "runs": options.runs,
                "repeats": options.repeats,
                "sample_interval_s": options.sample_interval,
                "observer": options.observer,
                "control_seconds": options.control_seconds,
                "postgres_storage": "tmpfs128MiB"
                if options.postgres_tmpfs
                else "disposable-volume",
                "max_host_cpu_percent": options.max_host_cpu_percent,
                "quiet_wait_seconds": options.quiet_wait_seconds,
                "dedicated_ci": options.dedicated_host,
            },
            "eligible": not issues,
            "resource_claim_eligible": False,
            "resource_claim_issues": [
                "exclusive_host_unverified",
                "owned_redis_cpu_not_separated",
                "long_windows_not_run_by_matrix",
            ],
            "quality_issues": sorted(set(issues)),
            "cells": cells,
            "summary": summary,
            "notes": NOTES,
            "command": [
                "python",
                "scripts/benchmark_matrix.py",
                *(["--postgres-tmpfs"] if options.postgres_tmpfs else []),
                "--observer",
                options.observer,
                "--control-seconds",
                str(options.control_seconds),
                "--profiles",
                *options.profiles,
                "--databases",
                *options.databases,
                "--workloads",
                *options.workloads,
                "--size",
                str(options.size),
                "--seed",
                str(options.seed),
                "--runs",
                str(options.runs),
                "--repeats",
                str(options.repeats),
                "--sample-interval",
                str(options.sample_interval),
                "--max-host-cpu-percent",
                str(options.max_host_cpu_percent),
                "--quiet-wait-seconds",
                str(options.quiet_wait_seconds),
                "--output",
                "<new-directory>",
            ],
        }
        if options.baseline:
            report["comparison"] = compatible(
                report,
                json.loads(options.baseline.read_text()),
                options.compare_code_change,
            )
        (options.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        lines = [
            "# Constrained comparison matrix",
            "",
            f"Commit `{report['git_sha']}`; source `{source_sha}`.",
            "",
            "Command: `" + " ".join(report["command"]) + "`",
            "",
            f"Eligible: **{report['eligible']}**; issues: `{report['quality_issues']}`.",
            "",
            "| Profile/database/workload | N | Container wall median s | Min-max s | CV % |",
            "|---|---:|---:|---:|---:|",
        ]
        for key, row in summary.items():
            lines.append(
                f"| {key} | {row['n']} | {row['median']:.6f} | {row['min']:.6f}-{row['max']:.6f} | {row['cv_pct']:.3f} |"
            )
        lines += [
            "",
            "Resource/idle/growth claims eligible: **False**. Exclusive host and long-window attribution require separate receipts; scalar host screens alone do not qualify these claims.",
            "",
            "## Resources and correctness",
            "",
            "| Cell/repeat | Sampler CPU s | Process snapshots | Fixture SHA256 |",
            "|---|---:|---:|---|",
        ]
        for cell in cells:
            lines.append(
                f"| {cell['key']}/{cell['repeat']} | {cell['sampler_cpu_s']:.6f} | {len(cell['samples'])} | {cell['correctness']['fixture_sha256']} |"
            )
        lines += [
            "",
            "Raw cgroup/process CPU/RSS/USS/PSS, peak memory, input invariants, calibration, limits and idle-host probes are in report.json and each cell.json. Null means unavailable.",
            "",
        ]
        if "comparison" in report:
            lines += [
                "## Comparison",
                "",
                "```json",
                json.dumps(report["comparison"], indent=2),
                "```",
                "",
            ]
        lines += ["## Limitations", "", *[f"- {note}" for note in NOTES]]
        (options.output / "report.md").write_text("\n".join(lines) + "\n")


def main():
    """Select a local manual matrix; shared CI and concurrent matrices fail."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--image")
    parser.add_argument(
        "--postgres-tmpfs",
        action="store_true",
        help="Use bounded disposable PostgreSQL tmpfs, recorded as distinct storage scope",
    )
    parser.add_argument("--postgres-image", default="postgres:16-alpine")
    parser.add_argument(
        "--profiles", choices=PROFILES, nargs="+", default=list(PROFILES)
    )
    parser.add_argument(
        "--databases",
        choices=("sqlite", "postgresql"),
        nargs="+",
        default=["sqlite", "postgresql"],
    )
    parser.add_argument(
        "--workloads",
        choices=("fixtures", "celery", "empty", "idle"),
        nargs="+",
        default=["fixtures", "celery"],
    )
    parser.add_argument("--observer", choices=("on", "off"), default="on")
    parser.add_argument("--control-seconds", type=float, default=5)
    parser.add_argument("--size", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--sample-interval", type=float, default=0.5)
    parser.add_argument("--max-host-cpu-percent", type=float, default=25)
    parser.add_argument("--quiet-wait-seconds", type=float, default=30)
    parser.add_argument("--dedicated-host", action="store_true")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument(
        "--compare-code-change",
        action="store_true",
        help="Allow application image/source changes only when benchmark method/runtime/inputs still match",
    )
    parser.add_argument("--container", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--database", choices=("sqlite", "postgresql"), help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--workload",
        choices=("fixtures", "celery", "empty", "idle"),
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--repeat-index", type=int, default=1, help=argparse.SUPPRESS)
    options = parser.parse_args()
    options.output = options.output.resolve()
    if (
        not 0 <= options.control_seconds <= 86400
        or options.size < 10
        or options.size % 10
        or min(options.runs, options.repeats) < 2
        or not 0.1 <= options.sample_interval <= 30
        or not 0 <= options.max_host_cpu_percent <= 100
        or not 0 <= options.quiet_wait_seconds <= 300
    ):
        parser.error(
            "size >=10 divisible by10; runs/repeats >=2; sample interval0.1..30; host CPU threshold0..100"
        )
    if options.container:
        container_worker(options)
    else:
        matrix(options)


if __name__ == "__main__":
    main()
