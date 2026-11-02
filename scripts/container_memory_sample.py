"""Read Linux container memory counters; run via `docker exec -i ... python -`."""
# ruff: noqa: INP001, T201

import json
import os
import time
from contextlib import suppress
from pathlib import Path

# Pss_Anon/Pss_File/Pss_Shmem need kernel >= 4.14. Shared_* and Private_* are
# older. Absent keys are reported as null rather than zero: a zero silently
# corrupts every sum and median downstream, a null forces the reader to decide.
_ROLLUP_KEYS = {
    "pss_kib": ("Pss",),
    "rss_kib": ("Rss",),
    "private_kib": ("Private_Clean", "Private_Dirty"),
    "shared_clean_kib": ("Shared_Clean",),
    "shared_dirty_kib": ("Shared_Dirty",),
    "pss_anon_kib": ("Pss_Anon",),
    "pss_file_kib": ("Pss_File",),
    "pss_shmem_kib": ("Pss_Shmem",),
}
# Reported only where huge pages are in use, so it is added when present
# rather than required -- demanding it would null out private_kib everywhere.
_OPTIONAL_ROLLUP_FIELDS = {"private_kib": ("Private_Hugetlb",)}
_MEASURED_KEYS = tuple(_ROLLUP_KEYS)
# Summed across a role. rss_kib is excluded: it is the one value the rss-only
# path still provides, so it sums over a different (larger) set of processes.
_SUMMED_KEYS = tuple(key for key in _ROLLUP_KEYS if key != "rss_kib")


def _read_text(path):
    """Return a file's contents, or None if it cannot be read."""
    try:
        return path.read_text()
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def _read_bytes(path):
    """Return a file's bytes, or None if it cannot be read."""
    try:
        return path.read_bytes()
    except (OSError, ValueError):
        return None


def _list_dir(path):
    """Return a directory's entries, or None if it cannot be listed."""
    try:
        return [entry.name for entry in path.iterdir()]
    except OSError:
        return None


def _parse_smaps_rollup(text):
    """Return the rollup's byte counters in KiB, or None if unusable.

    Reading this file needs PTRACE_MODE_READ, which a container without
    CAP_SYS_PTRACE does not have for another user's processes. That is the
    common case outside the benchmark stack, hence the rss-only fallback.
    """
    if not text:
        return None
    values = {}
    for line in text.splitlines()[1:]:
        key, _, rest = line.partition(":")
        parts = rest.split()
        if not parts:
            continue
        try:
            values[key] = int(parts[0])
        except ValueError:
            continue
    if "Pss" not in values:
        return None
    measured = {}
    for name, fields in _ROLLUP_KEYS.items():
        if any(field not in values for field in fields):
            measured[name] = None
            continue
        total = sum(values[field] for field in fields)
        for field in _OPTIONAL_ROLLUP_FIELDS.get(name, ()):
            total += values.get(field, 0)
        measured[name] = total
    return measured


def _parse_status(text):
    """Return the ppid and VmRSS this process reports in /proc/<pid>/status."""
    if not text:
        return None
    ppid = None
    vmrss_kib = None
    for line in text.splitlines():
        if line.startswith("PPid:"):
            parts = line.split()
            if len(parts) > 1:
                try:
                    ppid = int(parts[1])
                except ValueError:
                    ppid = None
        elif line.startswith("VmRSS:"):
            parts = line.split()
            if len(parts) > 1:
                try:
                    vmrss_kib = int(parts[1])
                except ValueError:
                    vmrss_kib = None
    if ppid is None:
        return None
    return {"ppid": ppid, "vmrss_kib": vmrss_kib}


def _parse_start_ticks(text):
    """Return field 22 of /proc/<pid>/stat, the process start time in ticks.

    ``comm`` is field 2, parenthesised, and may itself contain spaces and
    parentheses, so the fields cannot simply be split apart.
    """
    if not text:
        return None
    _, separator, rest = text.rpartition(") ")
    if not separator:
        return None
    parts = rest.split()
    # state is field 3, so field 22 is index 19 of what follows comm.
    index = 19
    if len(parts) <= index:
        return None
    try:
        return int(parts[index])
    except ValueError:
        return None


def _fd_count(proc_dir):
    """Return the process's open descriptor count, or None if unreadable."""
    entries = _list_dir(proc_dir / "fd")
    return None if entries is None else len(entries)


def _measure_process(proc_dir, clock_ticks, boot_uptime):
    """Return one process's memory, descriptors and age, or None if it is gone.

    Falls back to VmRSS from ``status`` when ``smaps_rollup`` cannot be read.
    ``status`` is world-readable, so a process is counted rather than dropped;
    ``measurement`` says which of the two it is.
    """
    initial_stat = _read_text(proc_dir / "stat")
    status = _parse_status(_read_text(proc_dir / "status"))
    if status is None:
        return None
    if status["vmrss_kib"] is None:
        # No VmRSS means a kernel thread, which has no user-space memory.
        return "kernel-thread"

    command = (_read_bytes(proc_dir / "cmdline") or b"").split(b"\0")
    comm = _read_text(proc_dir / "comm")
    measured = _parse_smaps_rollup(_read_text(proc_dir / "smaps_rollup"))
    process = {
        "pid": int(proc_dir.name),
        "ppid": status["ppid"],
        "name": (comm or "").strip(),
        "argv0": command[0].decode(errors="replace") if command and command[0] else "",
        "measurement": "full" if measured else "rss-only",
        "fd_count": _fd_count(proc_dir),
        "uptime_seconds": None,
        # Read task flags to classify Beat, but never emit process arguments:
        # command lines may contain deployment-specific connection details.
        "is_beat": any(b"beat" in argument for argument in command),
        "worker_queue": next(
            (
                argument.decode(errors="replace")
                for index, argument in enumerate(command[:-1])
                if argument in {b"--queues", b"-Q"}
                for argument in (command[index + 1],)
            ),
            "",
        ),
    }
    for key in _MEASURED_KEYS:
        process[key] = measured[key] if measured else None
    if not measured:
        process["rss_kib"] = status["vmrss_kib"]

    final_stat = _read_text(proc_dir / "stat")
    start_ticks = _parse_start_ticks(final_stat)
    if start_ticks != _parse_start_ticks(initial_stat):
        return None  # PID was reused during the non-atomic procfs walk.
    process["start_ticks"] = start_ticks
    process["cpu_seconds"] = None
    if final_stat and clock_ticks:
        fields = final_stat.rpartition(") ")[2].split()
        with suppress(ValueError, IndexError):
            process["cpu_seconds"] = (int(fields[11]) + int(fields[12])) / clock_ticks
    if start_ticks is not None and boot_uptime is not None and clock_ticks:
        process["uptime_seconds"] = round(boot_uptime - start_ticks / clock_ticks, 1)
    return process


def _process_role(process, child_pids, processes_by_pid):
    """Classify the supervised processes without relying on PID ordering."""
    command = f"{process['name']} {process['argv0']}".lower()
    pid = process["pid"]
    parent = processes_by_pid.get(process["ppid"], {})

    if "gunicorn" in command:
        return "gunicorn-master" if pid in child_pids else "gunicorn-worker"
    if "celery" in command:
        if pid in child_pids:
            return (
                "celery-worker-beat"
                if process["is_beat"]
                else (
                    "celery-interactive-parent"
                    if process["worker_queue"] == "interactive"
                    else "celery-worker-parent"
                )
            )
        if parent:
            if parent.get("is_beat"):
                return "celery-worker-beat-child"
            if parent.get("worker_queue") == "interactive":
                return "celery-interactive-child"
            return "celery-worker-child"
        if process["is_beat"]:
            return "celery-beat"
        return "celery"
    if "nginx" in command:
        return "nginx-master" if pid in child_pids else "nginx-worker"
    if "supervisord" in command:
        return "supervisord"
    return "other"


def _roll_up(processes):
    """Return per-role totals, keeping measured and rss-only counts distinct."""
    roles = {}
    for process in processes:
        budget = roles.setdefault(
            process["role"],
            {
                "process_count": 0,
                "measured_count": 0,
                "rss_only_count": 0,
                "rss_kib": 0,
                "fd_count": 0,
                "max_uptime_seconds": None,
                "max_pss_kib": None,
                "max_pss_pid": None,
                **dict.fromkeys(_SUMMED_KEYS, 0),
            },
        )
        budget["process_count"] += 1
        # A role can hold processes that are not interchangeable: a worker run
        # with --beat parents both its prefork pool child and the embedded
        # scheduler, and nothing outside the process tells them apart. Without
        # this, a 500 MiB pool child and a 60 MiB scheduler read as one
        # unremarkable 280 MiB average.
        if process["pss_kib"] is not None and (
            budget["max_pss_kib"] is None or process["pss_kib"] > budget["max_pss_kib"]
        ):
            budget["max_pss_kib"] = process["pss_kib"]
            budget["max_pss_pid"] = process["pid"]
        if process["measurement"] == "full":
            budget["measured_count"] += 1
        else:
            budget["rss_only_count"] += 1
        if process["rss_kib"] is not None:
            budget["rss_kib"] += process["rss_kib"]
        if process["fd_count"] is not None:
            budget["fd_count"] += process["fd_count"]
        if process["uptime_seconds"] is not None:
            current = budget["max_uptime_seconds"]
            budget["max_uptime_seconds"] = (
                process["uptime_seconds"]
                if current is None
                else max(current, process["uptime_seconds"])
            )
        for key in _SUMMED_KEYS:
            value = process[key]
            # One unmeasurable process makes the role's total unknowable. Say
            # so rather than reporting a sum that silently omits it.
            if value is None or budget[key] is None:
                budget[key] = None
            else:
                budget[key] += value
    return roles


def _read_cgroup():
    """Return the cgroup's accounting, spanning v2 and v1 layouts."""
    root = Path("/sys/fs/cgroup")
    pre_sampler_current = os.environ.get("FLOPPY_CGROUP_CURRENT_BEFORE_SAMPLER")
    if (root / "memory.current").exists():
        observed_current = int((root / "memory.current").read_text())
        peak_path = root / "memory.peak"
        events = {
            key: int(value)
            for key, value in (
                line.split()
                for line in (root / "memory.events").read_text().splitlines()
            )
        }
        cpu_stat_path = root / "cpu.stat"
        cpu_stat = (
            dict(line.split() for line in cpu_stat_path.read_text().splitlines())
            if cpu_stat_path.exists()
            else {}
        )
        return {
            "current_bytes": int(pre_sampler_current or observed_current),
            "current_observed_bytes": observed_current,
            # Cumulative CPU time; the delta between two samples is the CPU
            # the container spent in between (idle cost, #1158).
            "cpu_usage_usec": (
                int(cpu_stat["usage_usec"]) if "usage_usec" in cpu_stat else None
            ),
            "peak_bytes": int(peak_path.read_text()) if peak_path.exists() else None,
            "oom": events["oom"],
            "oom_kill": events["oom_kill"],
            "events": events,
            "memory_stat": {
                key: int(value)
                for key, value in (
                    line.split()
                    for line in (root / "memory.stat").read_text().splitlines()
                )
            },
        }
    root /= "memory"
    if not (root / "memory.usage_in_bytes").exists():
        # Neither layout is present. A cgroup v2 host exposes no controller
        # files on the root cgroup, so a process running outside a container
        # there sees no memory accounting at all. Report that as unknown
        # rather than raising: an absent bound is a fact about the host, and
        # the same "never mislabel an unknown as a number" rule that keeps v1
        # failcnt out of `oom` applies to it.
        return {
            "current_bytes": None,
            "current_observed_bytes": None,
            "cpu_usage_usec": None,
            "peak_bytes": None,
            "oom": None,
            "oom_kill": None,
            "events": None,
            "memory_stat": {},
        }
    observed_current = int((root / "memory.usage_in_bytes").read_text())
    return {
        "current_bytes": int(pre_sampler_current or observed_current),
        "current_observed_bytes": observed_current,
        "cpu_usage_usec": None,
        "peak_bytes": int((root / "memory.max_usage_in_bytes").read_text()),
        # v1 failcnt counts failed charges, not OOM kills. Do not mislabel it.
        "oom": None,
        "oom_kill": None,
        "events": None,
        "memory_stat": {},
    }


def _capture_warning(measured, rss_only, processes):
    """Explain why a capture is not usable, or return None if it is.

    Note `smaps_detail` reports "full" when nothing was measured at all, since
    there are then no rss-only processes to report. That is the one case a
    reader is most likely to mistake for success, so it is named separately.
    """
    if not processes:
        return "no processes found; this is not a capture of a running container"
    if not measured:
        return (
            "no process could be measured via smaps_rollup; re-run with "
            "`docker exec --privileged -u 0` (CAP_SYS_PTRACE is required to "
            "read another uid's smaps_rollup, and Docker drops it by default)"
        )
    if rss_only:
        return (
            f"PSS unavailable for {len(rss_only)} of {len(processes)} "
            "processes; re-run with `docker exec --privileged -u 0`"
        )
    return None


def _sum_or_none(processes, key):
    """Return the summed KiB for a key, or None if any process lacks it."""
    total = 0
    for process in processes:
        value = process[key]
        if value is None:
            return None
        total += value
    return total * 1024


def _pressure(path):
    """Read PSI counters; missing controller/kernel support stays unknown."""
    text = _read_text(path)
    if text is None:
        return None
    values = {}
    try:
        for line in text.splitlines():
            name, *fields = line.split()
            values[name] = {
                key: int(value) if key == "total" else float(value)
                for key, value in (field.split("=", 1) for field in fields)
            }
    except (ValueError, TypeError):
        return None
    return values


def _global_resources():
    """Expose VM/global counters, without attributing their residual to a tenant."""
    cpu = _read_text(Path("/proc/stat"))
    ticks = None
    if cpu:
        fields = cpu.splitlines()[0].split()
        if fields and fields[0] == "cpu":
            with suppress(ValueError):
                ticks = dict(
                    zip(
                        (
                            "user",
                            "nice",
                            "system",
                            "idle",
                            "iowait",
                            "irq",
                            "softirq",
                            "steal",
                        ),
                        (int(value) for value in fields[1:9]),
                        strict=False,
                    )
                )
    memory = {}
    for line in (_read_text(Path("/proc/meminfo")) or "").splitlines():
        name, _, value = line.partition(":")
        if name in {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}:
            try:
                memory[name] = int(value.split()[0]) * 1024
            except (ValueError, IndexError):
                continue
    return {
        "cpu_ticks": ticks,
        "memory_total_bytes": memory.get("MemTotal"),
        "memory_available_bytes": memory.get("MemAvailable"),
        "swap_total_bytes": memory.get("SwapTotal"),
        "swap_free_bytes": memory.get("SwapFree"),
        "pressure": {
            kind: _pressure(Path("/proc/pressure") / kind)
            for kind in ("cpu", "memory", "io")
        },
    }


def _clocks():
    """Read wall and suspend-aware clocks; absent boottime is explicit."""
    return {
        "wall_seconds": time.time(),
        "monotonic_seconds": time.monotonic(),
        "boottime_seconds": (
            time.clock_gettime(time.CLOCK_BOOTTIME)
            if hasattr(time, "CLOCK_BOOTTIME")
            else None
        ),
        "collector_cpu_seconds": time.process_time(),
    }


def sample():
    """Return cgroup accounting and readable process proportional/private memory."""
    exposure_start = _clocks()
    cgroup = _read_cgroup()
    global_resources = _global_resources()
    cgroup_pressure = {
        kind: _pressure(Path("/sys/fs/cgroup") / f"{kind}.pressure")
        for kind in ("cpu", "memory", "io")
    }

    uptime_text = _read_text(Path("/proc/uptime"))
    boot_uptime = float(uptime_text.split()[0]) if uptime_text else None
    try:
        clock_ticks = os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError):
        clock_ticks = None

    processes = []
    unreadable = 0
    kernel_threads = 0
    sampler = None
    self_pid = os.getpid()
    # Iterate over status, not smaps_rollup: status is world-readable, so a
    # process stays counted even where the rollup is denied.
    for status_path in Path("/proc").glob("[0-9]*/status"):
        proc_dir = status_path.parent
        try:
            pid = int(proc_dir.name)
        except ValueError:
            continue
        process = _measure_process(proc_dir, clock_ticks, boot_uptime)
        if process is None:
            # A process may exit between the glob and the read.
            unreadable += 1
            continue
        if process == "kernel-thread":
            kernel_threads += 1
            continue
        if pid == self_pid:
            sampler = process
        else:
            processes.append(process)

    processes_by_pid = {process["pid"]: process for process in processes}
    child_pids = {process["ppid"] for process in processes}
    for process in processes:
        process["role"] = _process_role(process, child_pids, processes_by_pid)
    for process in (*processes, *((sampler,) if sampler else ())):
        del process["is_beat"]
        del process["worker_queue"]
    processes.sort(key=lambda process: (-(process["pss_kib"] or 0), process["pid"]))

    roles = _roll_up(processes)
    measured = [process for process in processes if process["measurement"] == "full"]
    rss_only = [process for process in processes if process["measurement"] != "full"]
    pss_bytes = _sum_or_none(measured, "pss_kib") or 0
    private_bytes = _sum_or_none(measured, "private_kib") or 0
    current = cgroup["current_bytes"]

    return {
        **cgroup,
        "exposure": {"start": exposure_start, "end": _clocks()},
        "global": global_resources,
        "cgroup_pressure": cgroup_pressure,
        "resource_scope": {
            "global": "Linux /proc global; Docker Desktop VM, not physical host",
            "cgroup": "/sys/fs/cgroup visible root; ownership requires runner receipt",
            "processes": "visible PID namespace; sampler excluded from role totals",
            "collector": "Python process cumulative CPU through capture; excludes docker exec/client, shell and exit",
            "external_cpu_seconds": None,
            "external_attribution": "unknown; global minus owned is not proof of external work",
            "boot_id": (
                _read_text(Path("/proc/sys/kernel/random/boot_id")) or ""
            ).strip()
            or None,
        },
        "processes": processes,
        "roles": roles,
        "sampler": sampler,
        "measured_processes": len(measured),
        "rss_only_processes": len(rss_only),
        "kernel_threads": kernel_threads,
        "smaps_detail": (
            "full" if not rss_only else ("none" if not measured else "partial")
        ),
        # A capture that silently fell back to VmRSS reports no PSS for the
        # processes it could not read, and a reader who does not notice will
        # compare a partial number against a full one. Docker drops
        # CAP_SYS_PTRACE by default, so `docker exec --user root` is not
        # enough: smaps_rollup for a process owned by another uid still fails
        # the ptrace access check. Re-run with `docker exec --privileged -u 0`.
        "capture_valid": not rss_only and bool(measured),
        "capture_warning": _capture_warning(measured, rss_only, processes),
        "pss_breakdown_available": bool(measured)
        and measured[0]["pss_anon_kib"] is not None,
        "clock_ticks_per_second": clock_ticks,
        "reconciliation": {
            "process_pss_bytes": pss_bytes,
            "process_private_bytes": private_bytes,
            "process_pss_anon_bytes": _sum_or_none(measured, "pss_anon_kib"),
            "process_pss_file_bytes": _sum_or_none(measured, "pss_file_kib"),
            "process_pss_shmem_bytes": _sum_or_none(measured, "pss_shmem_kib"),
            "unmeasured_process_rss_bytes": _sum_or_none(rss_only, "rss_kib"),
            # False means cgroup_minus_process_pss_bytes is an upper bound on
            # non-process memory, not a reconciliation of it.
            "process_pss_complete": not rss_only,
            # Without a cgroup bound there is nothing to subtract from, so
            # these stay unknown rather than being reported as a total.
            "cgroup_minus_process_pss_bytes": (
                None if current is None else current - pss_bytes
            ),
            "cgroup_minus_process_private_bytes": (
                None if current is None else current - private_bytes
            ),
        },
        "unreadable_processes": unreadable,
    }


if __name__ == "__main__":
    print(json.dumps(sample()))
