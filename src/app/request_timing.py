"""Context-local accounting of request I/O and rendering boundaries.

Performance middleware and Celery task diagnostics start context-local tallies;
provider request helpers add to them. Without an active tally, recording does
nothing.
"""

import contextlib
import contextvars
import functools
import hashlib
import re
import socket
import time
import traceback
from pathlib import Path

_tally = contextvars.ContextVar("request_provider_tally", default=None)
# api_request retries by calling itself and calls resilient_request; only the
# outermost call is timed so the same wait is never counted twice.
_inside_call = contextvars.ContextVar("request_provider_inside_call", default=False)
_span = contextvars.ContextVar("request_timing_span", default=None)
_redis_connect = contextvars.ContextVar("request_timing_redis_connect", default=False)
_sql_profile = contextvars.ContextVar("request_timing_sql_profile", default=None)
_SQL_LITERALS = re.compile(r"'(?:''|[^'])*'|\b\d+(?:\.\d+)?\b")
_SOURCE_ROOT = str(Path(__file__).resolve().parents[1]) + "/"
SQL_PROFILE_SHAPE_LIMIT = 64
SQL_PROFILE_SITE_LIMIT = 8


@contextlib.contextmanager
def profile_sql():
    """Capture bounded SQL shapes, never parameters, for an explicit diagnostic."""
    profile = {"queries": {}, "overflow_count": 0}
    token = _sql_profile.set(profile)
    try:
        yield profile
    finally:
        _sql_profile.reset(token)


def record_sql(sql, elapsed):
    """Attribute one execution to a normalized fingerprint, call site and span."""
    profile = _sql_profile.get()
    if profile is None:
        return
    shape = re.sub(r"/\*.*?\*/|--[^\n]*", " ", sql, flags=re.DOTALL)
    shape = _SQL_LITERALS.sub("?", shape)
    shape = re.sub(r"%s|\$\d+", "?", shape)
    shape = re.sub(r"(?:\?\s*,\s*)+\?", "?list", shape)
    shape = " ".join(shape.split())
    fingerprint = hashlib.sha256(shape.encode()).hexdigest()[:16]
    site = "unattributed"
    for frame in reversed(traceback.extract_stack(limit=35)):
        if frame.filename.startswith(_SOURCE_ROOT) and not frame.filename.endswith(("request_timing.py", "middleware.py")):
            site = f"{frame.filename.removeprefix(_SOURCE_ROOT)}:{frame.lineno}:{frame.name}"
            break
    span = (_span.get() or {}).get("name", "request")
    key = fingerprint
    rows = profile["queries"]
    if key not in rows:
        if len(rows) >= SQL_PROFILE_SHAPE_LIMIT:
            profile["overflow_count"] += 1
            return
        rows[key] = {"fingerprint": fingerprint, "shape": shape[:800], "site": site,
                     "span": span, "count": 0, "cumulative_ms": 0.0, "max_ms": 0.0,
                     "attribution": []}
    row = rows[key]
    row["count"] += 1
    row["cumulative_ms"] += elapsed * 1000
    row["max_ms"] = max(row["max_ms"], elapsed * 1000)
    attribution = next((entry for entry in row["attribution"] if (entry["site"], entry["span"]) == (site, span)), None)
    if attribution is None and len(row["attribution"]) < SQL_PROFILE_SITE_LIMIT:
        attribution = {"site": site, "span": span, "count": 0, "cumulative_ms": 0.0}
        row["attribution"].append(attribution)
    if attribution is not None:
        attribution["count"] += 1
        attribution["cumulative_ms"] += elapsed * 1000


@contextlib.contextmanager
def boundary(name):
    """Record exclusive wall time; nested boundaries own their elapsed time."""
    tally = _tally.get()
    if tally is None:
        yield
        return
    parent = _span.get()
    calls = tally["boundary_calls"]
    calls[name] = calls.get(name, 0) + 1
    frame = {"children": 0.0, "name": name}
    token = _span.set(frame)
    started = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - started
        _span.reset(token)
        if parent is not None:
            parent["children"] += elapsed
        spans = tally["boundaries"]
        spans[name] = spans.get(name, 0.0) + elapsed - frame["children"]


def _wrap_boundary(cls, method, name):
    """Install a context-local timer once, without wrapping each request."""
    original = getattr(cls, method)
    if getattr(original, "_request_timing_boundary", False):
        return

    @functools.wraps(original)
    def wrapped(*args, **kwargs):
        if _tally.get() is None:
            return original(*args, **kwargs)
        with boundary(name):
            return original(*args, **kwargs)

    wrapped._request_timing_boundary = True
    setattr(cls, method, wrapped)


def install_boundaries():
    """Time shared I/O boundaries, including sessions and task publication.

    Installed when the performance middleware is constructed, before requests
    run. Outside an instrumented request the wrappers do not collect anything.
    Cache spans include pool acquisition, network waits and deserialization;
    broker spans include publication retries and result-backend hooks.
    """
    from celery.app.task import Task
    from django.db.backends.base.base import BaseDatabaseWrapper
    from django.template.base import Template
    from django_redis.cache import RedisCache
    from redis.connection import Connection, ConnectionPool

    for method in ("get", "set", "add", "delete", "get_many", "set_many", "delete_many", "incr", "has_key", "touch"):
        _wrap_boundary(RedisCache, method, "cache")
    _wrap_boundary(Task, "apply_async", "broker")
    _wrap_boundary(BaseDatabaseWrapper, "connect", "db_connect")
    _wrap_boundary(Template, "render", "render")
    _wrap_boundary(ConnectionPool, "get_connection", "redis_pool")
    _wrap_boundary(Connection, "send_packed_command", "redis_send")
    _wrap_boundary(Connection, "read_response", "redis_read")
    # Socket timeouts apply after getaddrinfo. Keep resolver waits visible
    # without timing unrelated provider DNS or logging network addresses.
    if not getattr(Connection._connect, "_request_timing_boundary", False):
        original_connect = Connection._connect

        @functools.wraps(original_connect)
        def connect(*args, **kwargs):
            if _tally.get() is None:
                return original_connect(*args, **kwargs)
            token = _redis_connect.set(True)
            try:
                with boundary("redis_connect"):
                    return original_connect(*args, **kwargs)
            finally:
                _redis_connect.reset(token)

        connect._request_timing_boundary = True
        Connection._connect = connect
    if not getattr(socket.getaddrinfo, "_request_timing_boundary", False):
        original_resolve = socket.getaddrinfo

        @functools.wraps(original_resolve)
        def resolve(*args, **kwargs):
            if not _redis_connect.get():
                return original_resolve(*args, **kwargs)
            with boundary("redis_dns"):
                return original_resolve(*args, **kwargs)

        resolve._request_timing_boundary = True
        socket.getaddrinfo = resolve


def begin():
    """Start a tally for the current request and return it with its reset token."""
    tally = {"calls": 0, "seconds": 0.0, "boundaries": {}, "boundary_calls": {}}
    return tally, _tally.set(tally)


def end(token):
    """Stop the tally started by begin()."""
    _tally.reset(token)


def timed_provider_call(func):
    """Add the wrapped call's wall time (waits and retries included) to the tally."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        tally = _tally.get()
        if tally is None or _inside_call.get():
            return func(*args, **kwargs)
        marker = _inside_call.set(True)
        started = time.perf_counter()
        try:
            with boundary("provider"):
                return func(*args, **kwargs)
        finally:
            _inside_call.reset(marker)
            tally["calls"] += 1
            tally["seconds"] += time.perf_counter() - started

    return wrapper
