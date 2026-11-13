"""Crash markers for the web process.

A container that dies leaves no traceback: an OOM kill or ``docker kill`` ends
every process at once. This module leaves evidence on the log volume instead:

* ``run-state.json`` is rewritten every minute with the time and the container's
  memory use. A clean stop (gunicorn's ``on_exit`` hook) marks it clean.
* On the next start, a state that was never marked clean is reported in
  ``floppy.log`` with the last heartbeat and how close memory was to its limit.
* ``faulthandler.log`` receives the Python traceback of a segfault or abort.
* The signal that asked gunicorn to stop is recorded, so the next start can say
  "stopped by SIGTERM" (``docker stop``, a restart, a NAS task) rather than
  leave a crash to be inferred.
* A memory line is logged every few minutes, so the log shows the trend that
  led up to a crash. It splits memory into program (anon) and file cache, and
  counts how often the container hit its limit, because the OOM counter is
  missing on some kernels (Synology).
* Every start appends a "Restart:" line to ``restart-history.log`` saying how
  the previous run ended, how long it was down, and whether the container or
  the version changed. A daily stop from outside the container (a scheduler,
  an updater) then shows up as a pattern instead of a bare timestamp.

Everything here is best effort: a failure to write must never stop Floppy.
"""

import faulthandler
import json
import logging
import os
import socket
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

STATE_NAME = "run-state.json"
FAULT_NAME = "faulthandler.log"
HISTORY_NAME = "restart-history.log"
HISTORY_MAX_LINES = 200
HEARTBEAT_SECONDS = 60
MEMORY_LINE_EVERY = 5  # heartbeats between memory lines in floppy.log
NEAR_LIMIT_RATIO = 0.9
# Sized in docker-compose.yml: celery waits up to 60 s per worker for a running
# task (supervisord.conf), the web server up to 30 s, and supervisord stops them
# one after another.
STOP_GRACE_HINT = (
    "Docker kills a container that is still shutting down when its stop timeout "
    "(10 s by default) runs out, so set stop_grace_period: 150s on the floppy "
    "service."
)
# cgroup v1 reports "no limit" as a number close to 2**63.
_UNLIMITED_BYTES = 1 << 60
_CGROUP_V2 = "/sys/fs/cgroup"
_CGROUP_V1 = "/sys/fs/cgroup/memory"

_fault_file = None  # faulthandler keeps only the descriptor, so hold the file
_state = {}
_lock = threading.Lock()
_stopped = threading.Event()


def _now():
    return datetime.now(UTC).replace(microsecond=0)


def _read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def _cgroup_bytes(v2_name, v1_name):
    """Return a cgroup memory figure (v2 first, then v1), or None."""
    for path in (f"{_CGROUP_V2}/{v2_name}", f"{_CGROUP_V1}/{v1_name}"):
        value = _read(path)
        if value and value.isdigit() and int(value) < _UNLIMITED_BYTES:
            return int(value)
    return None


def _oom_kills():
    """Return the cgroup's OOM kill counter, or None when it is not exposed."""
    for path in (f"{_CGROUP_V2}/memory.events", f"{_CGROUP_V1}/memory.oom_control"):
        for line in (_read(path) or "").splitlines():
            key, _, value = line.partition(" ")
            if key == "oom_kill" and value.isdigit():
                return int(value)
    return None


def _cgroup_split():
    """Return (program, file cache) bytes from the cgroup, either version."""
    for path, anon_key, file_key in (
        (f"{_CGROUP_V2}/memory.stat", "anon", "file"),
        (f"{_CGROUP_V1}/memory.stat", "total_rss", "total_cache"),
    ):
        stat = {}
        for line in (_read(path) or "").splitlines():
            key, _, value = line.partition(" ")
            if value.isdigit():
                stat[key] = int(value)
        if anon_key in stat:
            return stat[anon_key], stat.get(file_key)
    return None, None


def _limit_hits():
    """Return how often the container hit its memory limit, or None.

    Counted even when the kernel has no ``oom_kill`` counter (cgroup v1 on
    Synology), so memory pressure is visible without one.
    """
    failcnt = _read(f"{_CGROUP_V1}/memory.failcnt")
    if failcnt and failcnt.isdigit():
        return int(failcnt)
    for line in (_read(f"{_CGROUP_V2}/memory.events") or "").splitlines():
        key, _, value = line.partition(" ")
        if key == "max" and value.isdigit():
            return int(value)
    return None


def _host_available():
    """Return the host's available memory in bytes (MemAvailable), or None."""
    for line in (_read("/proc/meminfo") or "").splitlines():
        parts = line.split()
        if parts[:1] == ["MemAvailable:"] and len(parts) > 1 and parts[1].isdigit():
            return int(parts[1]) * 1024
    return None


def _sample():
    anon, file_cache = _cgroup_split()
    return {
        "memory": _cgroup_bytes("memory.current", "memory.usage_in_bytes"),
        "memory_peak": _cgroup_bytes("memory.peak", "memory.max_usage_in_bytes"),
        "memory_limit": _cgroup_bytes("memory.max", "memory.limit_in_bytes"),
        "oom_kills": _oom_kills(),
        "anon": anon,
        "file_cache": file_cache,
        "limit_hits": _limit_hits(),
        "host_available": _host_available(),
    }


def _container_started_at():
    """Return when the container's first process started, or None.

    PID 1 is supervisord in the image, so its start time is when Docker started
    the container. The gap to Floppy's own start is the entrypoint's work
    (database check, migrations).
    """
    try:
        stat = Path("/proc/1/stat").read_text()
        # The command name can contain spaces; fields after ")" start at state.
        ticks = int(stat.rsplit(")", 1)[1].split()[19])
        boot = next(
            int(line.split()[1])
            for line in Path("/proc/stat").read_text().splitlines()
            if line.startswith("btime ")
        )
        started = boot + ticks / os.sysconf("SC_CLK_TCK")
        return datetime.fromtimestamp(started, UTC).replace(microsecond=0).isoformat()
    except (OSError, ValueError, IndexError, StopIteration):
        return None


def _mib(value):
    return "unknown" if value is None else f"{value // (1024 * 1024)}MiB"


def state_path():
    """Return where the run state is kept."""
    return Path(settings.LOG_DIR) / STATE_NAME


def read_state():
    """Return the saved run state, or None when absent or unreadable."""
    try:
        return json.loads(state_path().read_text())
    except (OSError, ValueError):
        return None


def _write_state(state):
    path = state_path()
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(state))
        tmp.replace(path)
    except OSError:
        logger.debug("Could not write %s", path, exc_info=True)


def describe_unclean_exit(previous):
    """Return the log line for a previous run that never marked itself clean."""
    memory, limit = previous.get("memory"), previous.get("memory_limit")
    parts = [
        f"Previous run ended without a clean shutdown (started "
        f"{previous.get('started_at')}, last heartbeat {previous.get('last_heartbeat')}).",
        f"Memory at the last heartbeat: {_mib(memory)} of {_mib(limit)} limit "
        f"(peak {_mib(previous.get('memory_peak'))}).",
    ]
    if previous.get("oom_kills"):
        parts.append(
            f"The kernel had already killed {previous['oom_kills']} process(es) "
            "for running out of memory."
        )
    if memory and limit and memory >= limit * NEAR_LIMIT_RATIO:
        parts.append(
            "Memory was at the container limit, so this was likely an OOM kill."
        )
    else:
        parts.append(
            "To check for an OOM kill, run: docker inspect <container> "
            "--format '{{.State.OOMKilled}}' (or dmesg | grep -i oom on the host)."
        )
    if previous.get("stop_signal"):
        parts.append(
            f"A stop was requested ({previous['stop_signal']} at "
            f"{previous.get('stop_requested_at')}) but shutdown did not finish, "
            f"so it was killed part way. {STOP_GRACE_HINT}"
        )
    else:
        parts.append(
            "If a stop was requested from outside (docker stop, a restart, a "
            f"NAS task) and cut short, the stop signal never reached Floppy. {STOP_GRACE_HINT}"
        )
    return " ".join(parts)


def _parse_time(value):
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _duration(seconds):
    seconds = max(int(seconds), 0)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m{secs:02d}s" if minutes else f"{secs}s"


def describe_restart(previous, current):
    """Return one line saying how the previous run ended and what changed."""
    ended = _parse_time(previous.get("last_heartbeat"))
    began = _parse_time(previous.get("started_at"))
    now = _parse_time(current.get("started_at"))
    clean = previous.get("clean", True)
    parts = [
        f"previous run {'stopped cleanly' if clean else 'ended WITHOUT a clean stop'}"
    ]
    if previous.get("stop_signal"):
        parts[0] += f" after {previous['stop_signal']}"
    if ended and began:
        parts.append(f"after {_duration((ended - began).total_seconds())} up")
    if ended and now:
        down = _duration((now - ended).total_seconds())
        parts.append(f"{'down' if clean else 'down at most'} {down} before this start")
    old_host, new_host = previous.get("hostname"), current.get("hostname")
    if old_host and new_host:
        parts.append(
            f"same container ({new_host})"
            if old_host == new_host
            else f"new container ({old_host} -> {new_host})"
        )
    old_version, new_version = previous.get("version"), current.get("version")
    if old_version and new_version:
        parts.append(
            f"version unchanged ({new_version})"
            if old_version == new_version
            else f"version {old_version} -> {new_version}"
        )
    booted, started = _parse_time(current.get("container_started_at")), now
    if booted and started and started >= booted:
        parts.append(
            f"container process started {booted.isoformat()}, "
            f"Floppy {_duration((started - booted).total_seconds())} later"
        )
    return "Restart: " + "; ".join(parts) + "."


def _append_history(line):
    """Keep the last restart lines on the log volume, past floppy.log rotation."""
    path = Path(settings.LOG_DIR) / HISTORY_NAME
    try:
        try:
            lines = path.read_text().splitlines()
        except OSError:
            lines = []
        lines = [*lines, f"{_now().isoformat()} {line}"][-HISTORY_MAX_LINES:]
        path.write_text("\n".join(lines) + "\n")
    except OSError:
        logger.debug("Could not write %s", path, exc_info=True)


def describe_requested_stop(previous):
    """Return the log line for a previous run that was asked to stop."""
    return (
        f"Previous run was stopped by {previous['stop_signal']} at "
        f"{previous.get('stop_requested_at')} and shut down cleanly. "
        "That signal comes from outside Floppy (docker stop, docker restart, "
        "docker compose, a NAS scheduled task or updater), so this was not a "
        "crash."
    )


def start():
    """Report how the previous run ended, then begin the heartbeat."""
    previous = read_state()
    last_unclean = (previous or {}).get("last_unclean_at")
    if previous and not previous.get("clean", True):
        logger.warning("[run-state] %s", describe_unclean_exit(previous))
        last_unclean = previous.get("last_heartbeat")
    elif previous and previous.get("stop_signal"):
        logger.info("[run-state] %s", describe_requested_stop(previous))
    elif previous:
        logger.info(
            "[run-state] Previous run shut down cleanly at %s.",
            previous.get("last_heartbeat"),
        )

    _state.clear()
    _state.update(
        started_at=_now().isoformat(),
        version=settings.VERSION,
        hostname=socket.gethostname(),
        container_started_at=_container_started_at(),
        last_unclean_at=last_unclean,
    )
    if previous:
        restart = describe_restart(previous, _state)
        logger.info("[run-state] %s", restart)
        _append_history(restart)
    _stopped.clear()
    _beat(clean=False)
    logger.info("[run-state] Started; %s", _memory_summary(_state))
    threading.Thread(
        target=_heartbeat_loop, name="floppy-run-state", daemon=True
    ).start()


def _beat(*, clean):
    with _lock:
        _state.update(_sample())
        _state["last_heartbeat"] = _now().isoformat()
        _state["clean"] = clean
        _write_state(_state)


def _memory_summary(sample):
    load = f"{os.getloadavg()[0]:.2f}" if hasattr(os, "getloadavg") else "unknown"
    return (
        f"memory={_mib(sample['memory'])} peak={_mib(sample['memory_peak'])} "
        f"limit={_mib(sample['memory_limit'])} oom_kills={sample['oom_kills']} "
        f"limit_hits={sample['limit_hits']} anon={_mib(sample['anon'])} "
        f"file_cache={_mib(sample['file_cache'])} "
        f"host_available={_mib(sample['host_available'])} load={load}"
    )


def _heartbeat_loop():
    ticks = 0
    while not _stopped.wait(HEARTBEAT_SECONDS):
        ticks += 1
        _beat(clean=False)
        if ticks % MEMORY_LINE_EVERY == 0:
            logger.info("[run-state] %s", _memory_summary(_state))


def note_stop_signal(name):
    """Record the signal that asked gunicorn to stop, before it shuts down.

    Written immediately, still marked unclean: if the container is killed
    before shutdown finishes, the next start reports a stop that was cut short
    instead of an unexplained crash.
    """
    if _state:
        _state.update(stop_signal=name, stop_requested_at=_now().isoformat())
        _beat(clean=False)


def stop():
    """Mark this run as shut down on purpose (gunicorn ``on_exit``)."""
    _stopped.set()
    if _state:
        _beat(clean=True)


def enable_fault_log():
    """Send the traceback of a fatal signal (segfault, abort) to a file."""
    global _fault_file  # noqa: PLW0603 - must outlive this call
    try:
        _fault_file = (Path(settings.LOG_DIR) / FAULT_NAME).open("a")
        faulthandler.enable(file=_fault_file, all_threads=True)
    except OSError:
        logger.warning("Could not open %s for crash tracebacks", FAULT_NAME)


def log_worker_shutdown(sig, how):
    """Say what a Celery worker was running when it was told to stop.

    A stop that arrives mid-task is why a slow shutdown gets killed by Docker's
    ten second timeout, so the log needs the task names and how long they ran.
    """
    from celery.worker.state import active_requests

    now = time.time()
    running = sorted(
        f"{request.name} ({_duration(now - request.time_start)})"
        for request in list(active_requests)
        if request.time_start
    )
    logger.info(
        "[run-state] Celery worker shutting down (signal=%s how=%s); running tasks: %s",
        sig,
        how,
        ", ".join(running) or "none",
    )
