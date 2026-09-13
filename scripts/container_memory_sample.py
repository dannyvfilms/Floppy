"""Read Linux container memory counters; run via `docker exec -i ... python -`."""
# ruff: noqa: INP001, T201

import json
import os
from pathlib import Path


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


def sample():
    """Return cgroup accounting and readable process proportional/private memory."""
    root = Path("/sys/fs/cgroup")
    pre_sampler_current = os.environ.get("FLOPPY_CGROUP_CURRENT_BEFORE_SAMPLER")
    if (root / "memory.current").exists():
        observed_current = int((root / "memory.current").read_text())
        current = int(pre_sampler_current or observed_current)
        peak_path = root / "memory.peak"
        peak = int(peak_path.read_text()) if peak_path.exists() else None
        events = {
            key: int(value)
            for key, value in (
                line.split()
                for line in (root / "memory.events").read_text().splitlines()
            )
        }
        oom = events["oom"]
        oom_kill = events["oom_kill"]
        memory_stat = {
            key: int(value)
            for key, value in (
                line.split()
                for line in (root / "memory.stat").read_text().splitlines()
            )
        }
    else:
        root /= "memory"
        observed_current = int((root / "memory.usage_in_bytes").read_text())
        current = int(pre_sampler_current or observed_current)
        peak = int((root / "memory.max_usage_in_bytes").read_text())
        # v1 failcnt counts failed charges, not OOM kills. Do not mislabel it.
        oom = oom_kill = None
        events = None
        memory_stat = {}

    processes = []
    unreadable = 0
    sampler = None
    self_pid = os.getpid()
    for rollup in Path("/proc").glob("[0-9]*/smaps_rollup"):
        try:
            values = {}
            for line in rollup.read_text().splitlines()[1:]:
                key, value = line.split(":", 1)
                values[key] = int(value.split()[0])
            pid = int(rollup.parent.name)
            status = (rollup.parent / "status").read_text().splitlines()
            ppid = int(next(line.split()[1] for line in status if line.startswith("PPid:")))
            command = (rollup.parent / "cmdline").read_bytes().split(b"\0")
            process = {
                "pid": pid,
                "ppid": ppid,
                "name": (rollup.parent / "comm").read_text().strip(),
                "argv0": command[0].decode(errors="replace") if command and command[0] else "",
                "pss_kib": values["Pss"],
                "rss_kib": values["Rss"],
                "private_kib": sum(
                    values.get(key, 0)
                    for key in ("Private_Clean", "Private_Dirty", "Private_Hugetlb")
                ),
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
            if pid == self_pid:
                sampler = process
            else:
                processes.append(process)
        except (OSError, ValueError, KeyError):
            # A process may exit between glob and read; permissions also vary.
            unreadable += 1
    processes_by_pid = {process["pid"]: process for process in processes}
    child_pids = {process["ppid"] for process in processes}
    for process in processes:
        process["role"] = _process_role(process, child_pids, processes_by_pid)
    for process in processes:
        del process["is_beat"]
        del process["worker_queue"]
    if sampler:
        del sampler["is_beat"]
        del sampler["worker_queue"]
    processes.sort(key=lambda process: (-process["pss_kib"], process["pid"]))

    roles = {}
    for process in processes:
        budget = roles.setdefault(
            process["role"],
            {"process_count": 0, "pss_kib": 0, "rss_kib": 0, "private_kib": 0},
        )
        budget["process_count"] += 1
        for key in ("pss_kib", "rss_kib", "private_kib"):
            budget[key] += process[key]

    pss_bytes = sum(process["pss_kib"] for process in processes) * 1024
    private_bytes = sum(process["private_kib"] for process in processes) * 1024
    return {
        "current_bytes": current,
        "current_observed_bytes": observed_current,
        "peak_bytes": peak,
        "oom": oom,
        "oom_kill": oom_kill,
        "events": events,
        "processes": processes,
        "roles": roles,
        "sampler": sampler,
        "memory_stat": memory_stat,
        "reconciliation": {
            "process_pss_bytes": pss_bytes,
            "process_private_bytes": private_bytes,
            "cgroup_minus_process_pss_bytes": current - pss_bytes,
            "cgroup_minus_process_private_bytes": current - private_bytes,
        },
        "unreadable_processes": unreadable,
    }


if __name__ == "__main__":
    print(json.dumps(sample()))
