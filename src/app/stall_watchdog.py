"""Report requests that are still running after a threshold, before they finish.

slow_request is logged when a request completes, so a request that hangs, or
whose worker is killed, leaves nothing. Requests register here on entry; one
daemon thread per process scans the registry and logs each overdue request once
with its route pattern, age, pid, in-flight count and the blocked thread's
stack (file:line:function only: no locals, arguments, paths or queries).
"""

import itertools
import logging
import os
import sys
import threading
import time

logger = logging.getLogger(__name__)

MAX_STACK_FRAMES = 25
_lock = threading.Lock()
_requests = {}
_ids = itertools.count(1)
_state = {"pid": None, "window_start": 0.0, "window_count": 0}


def _route(path):
    """Return the URL pattern for path, never the path itself (it can hold tokens)."""
    from django.urls import Resolver404, resolve

    try:
        return resolve(path).route or "/"
    except Resolver404:
        return "unresolved"


def _stack(thread_id):
    frame = sys._current_frames().get(thread_id)
    lines = []
    while frame is not None and len(lines) < MAX_STACK_FRAMES:
        code = frame.f_code
        lines.append(f"{code.co_filename}:{frame.f_lineno}:{code.co_name}")
        frame = frame.f_back
    return " <- ".join(lines)


def enter(method, path):
    """Register the current thread's request; return a token for leave()."""
    _ensure_thread()
    token = next(_ids)
    with _lock:
        _requests[token] = [time.monotonic(), threading.get_ident(), method, path, False]
    return token


def leave(token):
    """Forget a finished request; return True if it had been reported as stalled."""
    with _lock:
        entry = _requests.pop(token, None)
    return bool(entry and entry[4])


def _ensure_thread():
    """Start the scanner in this process (also after a gunicorn fork)."""
    pid = os.getpid()
    if _state["pid"] == pid:
        return
    with _lock:
        if _state["pid"] == pid:
            return
        _state["pid"] = pid
        _requests.clear()
    threading.Thread(target=_run, name="stall-watchdog", daemon=True).start()


def _allowed(now, limit):
    """Allow at most limit reports per minute so a stall storm cannot flood logs."""
    if now - _state["window_start"] >= 60:  # noqa: PLR2004
        _state["window_start"] = now
        _state["window_count"] = 0
    if _state["window_count"] >= limit:
        return False
    _state["window_count"] += 1
    return True


def scan(now=None):
    """Log every unreported request older than the threshold; return the count."""
    from django.conf import settings

    threshold = settings.PERF_STALL_WARN_MS / 1000
    limit = settings.PERF_STALL_MAX_REPORTS_PER_MINUTE
    now = time.monotonic() if now is None else now
    with _lock:
        inflight = len(_requests)
        overdue = [
            (token, entry)
            for token, entry in _requests.items()
            if not entry[4] and now - entry[0] >= threshold
        ]
        for _, entry in overdue:
            entry[4] = True
    reported = 0
    for _, (started, thread_id, method, path, _flag) in overdue:
        if not _allowed(now, limit):
            continue
        reported += 1
        logger.warning(
            "stalled_request method=%s route=%s age_ms=%.0f pid=%s thread=%s "
            "inflight=%s stack=%s",
            method,
            _route(path),
            (now - started) * 1000,
            os.getpid(),
            thread_id,
            inflight,
            _stack(thread_id),
        )
    return reported


def _run():
    from django.conf import settings

    interval = max(0.25, min(1.0, settings.PERF_STALL_WARN_MS / 4000))
    while True:
        time.sleep(interval)
        try:
            scan()
        except Exception:
            logger.debug("stall watchdog scan failed", exc_info=True)
