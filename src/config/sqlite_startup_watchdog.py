"""Supervise the startup database check: stop it when it stalls, not when it is slow.

A wall-clock bound cannot tell a large database on slow storage from a scan
that is stuck, so it eventually stops healthy work. This watchdog runs the
check as a child process and watches what the child is actually doing: bytes
it has read (``rchar`` in ``/proc/<pid>/io``, which counts reads served from
the page cache too) and CPU time it has used (``/proc/<pid>/stat``). The check
is stopped only when neither has moved for ``STALL_SECONDS`` -- a read blocked
on a dead mount, a lock that never clears -- or when it passes a generous
absolute ceiling that exists only to end a runaway loop.

Where ``/proc`` cannot be read, the scan's own status sidecar is the progress
signal instead, and the ceiling still applies.

The sidecar lives next to the database, on the same storage that may be the
thing that stalled. Every sidecar read or write here therefore runs on a
helper thread with a short bound, so a dead mount can delay a heartbeat line
but never the stall decision.

Usage: ``python -m config.sqlite_startup_watchdog DB_FILE COMMAND [ARG...]``.
Exits with the child's status, or 124 when the watchdog stopped it, which is
the status ``timeout(1)`` used and the entrypoint already handles.
"""

from __future__ import annotations

import contextlib
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from config.sqlite_integrity import (
    _log,
    mark_startup_status_timeout,
    print_startup_heartbeat,
    read_startup_status,
)

STALL_SECONDS = 180.0
CEILING_SECONDS = 4 * 3600.0
POLL_SECONDS = 5.0
HEARTBEAT_SECONDS = 30.0
TIMEOUT_EXIT = 124
_STOP_GRACE_SECONDS = 10.0
_SIDECAR_IO_SECONDS = 10.0


def _bounded(function, *args, **kwargs) -> tuple[bool, object]:
    """Run sidecar I/O on a helper thread; give up waiting after a short bound.

    Returns ``(finished, result)``. A call blocked on a dead mount is left
    behind on its daemon thread instead of holding up the watchdog.
    """
    outcome = []

    def run() -> None:
        try:
            outcome.append(function(*args, **kwargs))
        except Exception as error:  # best-effort diagnostics only
            _log(f"[entrypoint] SQLite startup watchdog sidecar I/O failed: {error}")
            outcome.append(None)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(_SIDECAR_IO_SECONDS)
    return (bool(outcome), outcome[0] if outcome else None)


def _activity(pid: int) -> tuple[int, int] | None:
    """Bytes read and CPU ticks used so far, or ``None`` where /proc cannot say."""
    try:
        io_text = Path(f"/proc/{pid}/io").read_text()
        stat_text = Path(f"/proc/{pid}/stat").read_text()
        rchar = next(
            int(line.split()[1])
            for line in io_text.splitlines()
            if line.startswith("rchar:")
        )
        # The command name may hold spaces or parentheses; fields after the
        # last ")" are fixed. utime and stime are fields 14 and 15 overall.
        fields = stat_text.rsplit(")", 1)[1].split()
        cpu_ticks = int(fields[11]) + int(fields[12])
    except (OSError, ValueError, IndexError, StopIteration):
        return None
    return rchar, cpu_ticks


def _status_stamp(db_path: str) -> tuple[object, object]:
    _finished, status = _bounded(read_startup_status, db_path)
    status = status or {}
    return status.get("phase"), status.get("updated_at")


def _stop(child: subprocess.Popen) -> None:
    child.terminate()
    try:
        child.wait(timeout=_STOP_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        child.kill()
        # A process stuck in uninterruptible I/O cannot die until that I/O
        # returns; startup still has to park rather than wait on it.
        with contextlib.suppress(subprocess.TimeoutExpired):
            child.wait(timeout=_STOP_GRACE_SECONDS)


def _exit_status(returncode: int) -> int:
    """Report a signal death the way a shell does: 128 + the signal number."""
    return 128 - returncode if returncode < 0 else returncode


def supervise(
    db_path: str,
    command: list[str],
    *,
    stall_seconds: float = STALL_SECONDS,
    ceiling_seconds: float = CEILING_SECONDS,
    poll_seconds: float = POLL_SECONDS,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
) -> int:
    """Run ``command`` and return its exit status, or 124 if it had to be stopped."""
    child = subprocess.Popen(command)  # noqa: S603

    def forward(signum: int, _frame: object) -> None:
        # The entrypoint stops the check by signalling this process; the scan
        # itself must stop too, not be orphaned.
        child.send_signal(signum)

    previous_handlers = {
        signum: signal.signal(signum, forward)
        for signum in (signal.SIGTERM, signal.SIGINT)
    }
    try:
        return _watch(
            db_path,
            child,
            stall_seconds=stall_seconds,
            ceiling_seconds=ceiling_seconds,
            poll_seconds=poll_seconds,
            heartbeat_seconds=heartbeat_seconds,
        )
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def _watch(
    db_path: str,
    child: subprocess.Popen,
    *,
    stall_seconds: float,
    ceiling_seconds: float,
    poll_seconds: float,
    heartbeat_seconds: float,
) -> int:
    started = last_change = last_heartbeat = time.monotonic()
    migrating = "migrate" in child.args
    last_seen = None
    read_bytes = None
    while True:
        try:
            return _exit_status(child.wait(timeout=poll_seconds))
        except subprocess.TimeoutExpired:
            pass
        now = time.monotonic()
        activity = _activity(child.pid)
        if activity is not None:
            read_bytes = activity[0]
        # /proc is the progress signal whenever it answers; the sidecar sits on
        # the database's own storage and is only the fallback.
        seen = activity if activity is not None else _status_stamp(db_path)
        if seen != last_seen:
            last_seen = seen
            last_change = now

        reason = None
        if now - last_change >= stall_seconds:
            reason = f"no read or CPU progress for {now - last_change:.0f}s"
        elif now - started >= ceiling_seconds:
            reason = f"still running at the {ceiling_seconds:g}s ceiling"
        if reason:
            _stop(child)
            _log(f"[entrypoint] SQLite startup watchdog stopped the check: {reason}")
            finished, _result = _bounded(
                mark_startup_status_timeout,
                db_path,
                now - started,
                reason=reason,
                read_bytes=read_bytes,
            )
            if not finished:
                _log(
                    "[entrypoint] Could not record the stopped check next to the "
                    "database; its storage is not responding.",
                )
            return TIMEOUT_EXIT

        if now - last_heartbeat >= heartbeat_seconds:
            extra = f"quiet_for={now - last_change:.0f}s"
            if activity is not None:
                extra = (
                    f"process_read={activity[0] / 1_048_576:.0f}MB "
                    f"cpu_ticks={activity[1]} {extra}"
                )
            if migrating:
                # The scan sidecar still says "admission" here; describe the
                # work that is actually running instead.
                _log(
                    "[entrypoint] Database migration heartbeat: "
                    f"elapsed={now - started:.0f}s {extra}"
                )
            else:
                _bounded(print_startup_heartbeat, db_path, extra=extra)
            last_heartbeat = now


def main(argv: list[str]) -> int:
    """Parse ``DB_FILE COMMAND [ARG...]`` and supervise the command."""
    if len(argv) < 2:  # noqa: PLR2004
        _log("usage: python -m config.sqlite_startup_watchdog DB_FILE COMMAND [ARG...]")
        return 2
    return supervise(argv[0], argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
