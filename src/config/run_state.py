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
  led up to a crash.

Everything here is best effort: a failure to write must never stop Floppy.
"""

import faulthandler
import json
import logging
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

STATE_NAME = "run-state.json"
FAULT_NAME = "faulthandler.log"
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


def _sample():
    return {
        "memory": _cgroup_bytes("memory.current", "memory.usage_in_bytes"),
        "memory_peak": _cgroup_bytes("memory.peak", "memory.max_usage_in_bytes"),
        "memory_limit": _cgroup_bytes("memory.max", "memory.limit_in_bytes"),
        "oom_kills": _oom_kills(),
    }


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
        last_unclean_at=last_unclean,
    )
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
        f"load={load}"
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
