"""Report whether aged processes return to a floor or stair-step upward.

Reads the output of scripts/memory_aging.sh. The question this answers is not
"how much memory does Floppy use" but "does a process that has done hours of
work end where it started", so everything here is reported against process age
and completed-cycle count rather than as a single number.
"""
# Standalone diagnostic run from a checkout, not an installed package.
# ruff: noqa: INP001, T201, PLR2004

import argparse
import json
import statistics
from itertools import pairwise
from pathlib import Path

MIB = 1024 * 1024
KIB_PER_MIB = 1024
# A role whose members are not interchangeable (a worker run with --beat parents
# both a pool child and the embedded scheduler, indistinguishable from outside).
# Its per-process series are reported individually.
SPLIT_ROLES = {"celery-worker-beat-child"}
# The workload driver runs inside the container so its requests are local, but
# it is the harness, not the application. Counting it would put its own ~100 MiB
# into every Floppy budget reported here.
HARNESS_ROLES = {"other"}
# Discarded before measuring drift: a process climbs steeply while its imports,
# connection pools and caches fill, and that is not aging.
WARMUP_SECONDS = 600
# A drift rate needs a baseline and a later reading far enough apart to mean
# something. A pool child that is retired after two minutes never has one, and
# extrapolating its warm-up to an hourly rate invents a trend it cannot show.
MIN_DRIFT_SPAN_HOURS = 0.25


def load(directory):
    """Return samples ordered by wall clock, skipping any truncated file."""
    samples = []
    for path in sorted((directory / "samples").glob("*.json")):
        try:
            sample = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        stem = path.stem.split("-")[0]
        if not stem.isdigit():
            continue
        sample["at"] = int(stem)
        samples.append(sample)
    samples.sort(key=lambda item: item["at"])
    return samples


def cycles(directory):
    """Return the completed workload cycles, oldest first."""
    path = directory / "workload.ndjson"
    if not path.exists():
        return []
    done = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if record.get("phase") == "complete":
            done.append(record)
    return done


def series(samples):
    """Return one PSS series per role, splitting roles that mix process kinds."""
    tracks = {}
    for sample in samples:
        by_role = {}
        for process in sample["processes"]:
            by_role.setdefault(process["role"], []).append(process)
        for role, budget in sample["roles"].items():
            members = by_role.get(role, [])
            if role in SPLIT_ROLES:
                groups = [([process], process.get("pss_kib")) for process in members]
            else:
                groups = [(members, budget.get("pss_kib"))]
            for processes, value in groups:
                # A reused PID is a new lifetime. Aggregate roles also restart
                # when membership changes, so replacement cannot become aging.
                identity = ",".join(
                    f"{process['pid']}:{process.get('start_ticks', 'unknown')}"
                    for process in sorted(processes, key=lambda item: item["pid"])
                )
                boot = sample.get("resource_scope", {}).get("boot_id") or "unknown-boot"
                key = f"{role}#{boot}:{identity or 'unknown-members'}"
                tracks.setdefault(key, []).append((sample["at"], value))
    return tracks


def trend(points, warmup_seconds=WARMUP_SECONDS):
    """Return the shape of one process group's footprint over the run.

    Every process climbs steeply while its imports and caches fill; reading a
    slope through that start reports warm-up as if it were aging. The drift
    here is therefore measured between the first and last quarters of what
    remains after the warm-up window, and the whole window is reported so a
    reader can see how much was discarded.
    """
    measured = [(at, value / KIB_PER_MIB) for at, value in points if value is not None]
    if len(measured) < 2:
        return None
    start = measured[0][0]
    warm = [item for item in measured if item[0] - start >= warmup_seconds] or measured
    span_hours = (warm[-1][0] - warm[0][0]) / 3600
    quarter = max(1, len(warm) // 4)
    early = statistics.median(value for _, value in warm[:quarter])
    late = statistics.median(value for _, value in warm[-quarter:])
    drift = (late - early) / span_hours if span_hours >= MIN_DRIFT_SPAN_HOURS else None
    return {
        "samples": len(measured),
        "warm_samples": len(warm),
        "span_hours": round(span_hours, 2),
        "first_mib": round(measured[0][1], 1),
        "last_mib": round(measured[-1][1], 1),
        "peak_mib": round(max(value for _, value in measured), 1),
        "median_mib": round(statistics.median(value for _, value in warm), 1),
        "early_mib": round(early, 1),
        "late_mib": round(late, 1),
        "drift_mib_per_hour": round(drift, 1) if drift is not None else None,
    }


def resource_delta(before, after):
    """Compare cumulative counters, retaining unknown ownership and resets."""
    reasons = []
    before_boot = before.get("resource_scope", {}).get("boot_id")
    after_boot = after.get("resource_scope", {}).get("boot_id")
    same_boot = before_boot is not None and before_boot == after_boot
    if not same_boot:
        reasons.append("boot identity missing or changed")

    def delta(first, last, scale=1):
        if not same_boot or first is None or last is None:
            return None
        if last < first:
            reasons.append("cumulative counter reset")
            return None
        return (last - first) / scale

    ticks = before.get("clock_ticks_per_second")
    global_before = before.get("global", {})
    global_after = after.get("global", {})
    first_cpu = global_before.get("cpu_ticks")
    last_cpu = global_after.get("cpu_ticks")
    global_cpu = None
    global_total = None
    if (
        first_cpu
        and last_cpu
        and ticks
        and ticks == after.get("clock_ticks_per_second")
        and first_cpu.keys() == last_cpu.keys()
    ):
        global_total = delta(sum(first_cpu.values()), sum(last_cpu.values()), ticks)
        global_cpu = delta(
            sum(
                value
                for key, value in first_cpu.items()
                if key not in {"idle", "iowait"}
            ),
            sum(
                value
                for key, value in last_cpu.items()
                if key not in {"idle", "iowait"}
            ),
            ticks,
        )
    pressure = {}
    for scope, first, last in (
        ("global", global_before.get("pressure", {}), global_after.get("pressure", {})),
        ("cgroup", before.get("cgroup_pressure", {}), after.get("cgroup_pressure", {})),
    ):
        pressure[scope] = {}
        for kind in ("cpu", "memory", "io"):
            first_pressure = first.get(kind) or {}
            last_pressure = last.get(kind) or {}
            pressure[scope][kind] = {
                level: delta(
                    first_pressure.get(level, {}).get("total"),
                    last_pressure.get(level, {}).get("total"),
                    1_000_000,
                )
                for level in ("some", "full")
            }
    return {
        "global_busy_cpu_seconds": global_cpu,
        "global_total_cpu_seconds": global_total,
        "cgroup_cpu_seconds": delta(
            before.get("cpu_usage_usec"), after.get("cpu_usage_usec"), 1_000_000
        ),
        "pressure_stall_seconds": pressure,
        "external_cpu_seconds": None,
        "scope": "global Linux VM and visible cgroup; ownership/continuous lifetime requires runner receipts",
        "counter_warnings": sorted(set(reasons)),
    }


def exposure_summary(samples):
    """Keep absent old clocks unknown and expose gaps without assuming idle."""
    intervals = []
    for previous, current in pairwise(samples):
        start = previous.get("exposure", {}).get("start", {})
        end = current.get("exposure", {}).get("start", {})
        if any(
            start.get(key) is None or end.get(key) is None
            for key in (
                "wall_seconds",
                "monotonic_seconds",
            )
        ):
            continue
        wall = end["wall_seconds"] - start["wall_seconds"]
        monotonic = end["monotonic_seconds"] - start["monotonic_seconds"]
        intervals.append(
            {
                "wall_seconds": wall,
                "monotonic_seconds": monotonic,
                "wall_minus_monotonic_seconds": wall - monotonic,
                "boottime_minus_monotonic_seconds": (
                    end["boottime_seconds"] - start["boottime_seconds"] - monotonic
                    if start.get("boottime_seconds") is not None
                    and end.get("boottime_seconds") is not None
                    else None
                ),
            }
        )
    collector = []
    for sample in samples:
        exposure = sample.get("exposure", {})
        start_cpu = exposure.get("start", {}).get("collector_cpu_seconds")
        end_cpu = exposure.get("end", {}).get("collector_cpu_seconds")
        collector.append(
            end_cpu - start_cpu
            if start_cpu is not None and end_cpu is not None and end_cpu >= start_cpu
            else None
        )
    return {
        "resource_delta": resource_delta(samples[0], samples[-1]) if samples else None,
        "clocked_intervals": len(intervals),
        "missing_clock_intervals": max(0, len(samples) - 1 - len(intervals)),
        "max_wall_gap_seconds": max(
            (item["wall_seconds"] for item in intervals), default=None
        ),
        "max_absolute_wall_monotonic_difference_seconds": max(
            (abs(item["wall_minus_monotonic_seconds"]) for item in intervals),
            default=None,
        ),
        "max_suspend_exposure_seconds": max(
            (
                item["boottime_minus_monotonic_seconds"]
                for item in intervals
                if item["boottime_minus_monotonic_seconds"] is not None
            ),
            default=None,
        ),
        "sampler_capture_cpu_seconds": (
            sum(collector)
            if collector and all(value is not None for value in collector)
            else None
        ),
        "collector_scope": "capture CPU deltas; excludes interpreter startup/import, docker exec/client, shell and exit",
        "growth_cause": "unknown; counters alone cannot distinguish GC, CoW and cache growth",
    }


def main():
    """Print the aging verdict for one run directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    arguments = parser.parse_args()

    samples = load(arguments.directory)
    if not samples:
        message = "No samples found"
        raise SystemExit(message)
    done = cycles(arguments.directory)
    span = (samples[-1]["at"] - samples[0]["at"]) / 3600

    print(f"samples={len(samples)} span={span:.2f}h cycles_completed={len(done)}")
    print("exposure=" + json.dumps(exposure_summary(samples), sort_keys=True))
    print(
        f"unusable_sample_files={len(list((arguments.directory / 'samples').glob('*.json'))) - len(samples)} (retained on disk)"
    )
    first, last = samples[0], samples[-1]
    for label, sample in (("first", first), ("last", last)):
        harness = sum(
            budget.get("pss_kib") or 0
            for role, budget in sample["roles"].items()
            if role in HARNESS_ROLES
        )
        application = sample["reconciliation"]["process_pss_bytes"] - harness * 1024
        print(
            f"  {label:5s} cgroup={sample['current_bytes'] / MIB:7.0f}MiB "
            f"peak={(sample['peak_bytes'] or 0) / MIB:7.0f}MiB "
            f"floppy_pss={application / MIB:7.0f}MiB "
            f"harness_pss={harness / KIB_PER_MIB:6.0f}MiB "
            f"oom_kill={sample['oom_kill']}"
        )

    print(
        f"\nper-process-group PSS, MiB "
        f"(drift measured after a {WARMUP_SECONDS}s warm-up window):"
    )
    header = (
        f"{'track':<34}{'n':>4}{'warm':>5}{'peak':>8}"
        f"{'early':>8}{'late':>8}{'drift/h':>9}"
    )
    print(header)
    rows = []
    for track, points in series(samples).items():
        summary = trend(points)
        if summary:
            rows.append((track, summary))
    for track, summary in sorted(rows, key=lambda row: -row[1]["peak_mib"]):
        print(
            f"{track:<34}{summary['samples']:>4}{summary['warm_samples']:>5}"
            f"{summary['peak_mib']:>8}{summary['early_mib']:>8}"
            f"{summary['late_mib']:>8}"
            f"{(summary['drift_mib_per_hour'] if summary['drift_mib_per_hour'] is not None else 'short'):>9}"
        )

    if done:
        print("\ncycle duration drift (a rising cost confounds a rising footprint):")
        chunk = max(1, len(done) // 6)
        for start in range(0, len(done), chunk):
            window = done[start : start + chunk]
            seconds = statistics.median(record["seconds"] for record in window)
            current = statistics.median(
                record.get("cgroup_current_bytes", 0) for record in window
            )
            print(
                f"  cycles {start:>5}-{start + len(window) - 1:<5} "
                f"median_seconds={seconds:8.2f} "
                f"median_cgroup={current / MIB:7.0f}MiB"
            )


if __name__ == "__main__":
    main()
