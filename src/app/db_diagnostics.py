"""Low-overhead diagnostics for database contention (#1609).

The 2026-10-17 SQLite incident showed *who waited* but not what held the
writer or how long the transaction had been open. This module keeps that
answer cheap enough to leave on in production:

* Every query is observed only enough to notice BEGIN/COMMIT/ROLLBACK, so a
  transaction over the configured threshold logs one line with its duration
  and the request/task that owned it.
* A lock failure logs its SQLite code, configured journal/timeout and caller
  identity. It never claims an owner: SQLite does not expose one.

Nothing here logs SQL, parameters, database paths or user data.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from django.conf import settings
from django.db import DatabaseError

if __debug__:
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from collections.abc import Callable

        from django.http import HttpRequest

logger = logging.getLogger(__name__)

_request_context = contextvars.ContextVar("db_request_context", default=None)
_task_context = contextvars.ContextVar("db_task_context", default=None)
_task_tokens = threading.local()

_state = threading.local()

DEFAULT_RETRY_AFTER_SECONDS = 5
MAX_TRACKED_TASKS = 64
_SQLITE_PRIMARY_MASK = 0xFF
_SQLITE_BUSY = sqlite3.SQLITE_BUSY
_SQLITE_LOCKED = sqlite3.SQLITE_LOCKED
_SQLITE_IOERR = sqlite3.SQLITE_IOERR
_POSTGRES_CONTENTION_STATES = frozenset({"40P01", "40001", "55P03"})


@dataclass(frozen=True)
class DatabaseContention:
    """A classified technical database failure, safe to expose to API clients."""

    code: str
    detail: str
    retryable: bool
    retry_after: int | None
    sqlite_code: int | None = None
    sqlite_extended: int | None = None
    kind: str = ""


def _safe_path(request: HttpRequest | None) -> str:
    if request is None:
        return ""
    try:
        return (getattr(request, "path", "") or "")[:500]
    except Exception:
        return ""


@contextlib.contextmanager
def bind_request(request: HttpRequest | None):
    """Publish the request's method and path for a whole request."""
    context = {
        "kind": "request",
        "method": str(getattr(request, "method", "") or "")[:16],
        "path": _safe_path(request),
    }
    token = _request_context.set(context)
    try:
        yield
    finally:
        _request_context.reset(token)


def task_started(task_id: str | None, task_name: str | None) -> None:
    """Publish the running Celery task for its DB diagnostics."""
    if not task_id:
        return
    tokens = getattr(_task_tokens, "tokens", None)
    if tokens is None:
        tokens = {}
        _task_tokens.tokens = tokens
    if len(tokens) >= MAX_TRACKED_TASKS:
        _old_id, old_token = next(iter(tokens.items()))
        tokens.pop(_old_id)
        _task_context.reset(old_token)
    tokens[str(task_id)] = _task_context.set(
        {
            "kind": "task",
            "task": str(task_name or "<unknown>")[:200],
            "task_id": str(task_id),
        },
    )


def task_finished(task_id: str | None) -> None:
    """Clear the context set by :func:`task_started`."""
    if not task_id:
        return
    tokens = getattr(_task_tokens, "tokens", {})
    token = tokens.pop(str(task_id), None)
    if token is not None:
        _task_context.reset(token)


def connect_celery_signals() -> None:
    """Bind task identity around every Celery task, once per process."""
    from celery.signals import task_postrun, task_prerun

    def _prerun(task_id=None, task=None, **_kwargs):
        task_started(task_id, getattr(task, "name", "<unknown>"))

    def _postrun(task_id=None, **_kwargs):
        task_finished(task_id)

    task_prerun.connect(
        _prerun,
        weak=False,
        dispatch_uid="db_diagnostics_task_prerun",
    )
    task_postrun.connect(
        _postrun,
        weak=False,
        dispatch_uid="db_diagnostics_task_postrun",
    )


def _context_fields() -> list[tuple[str, object]]:
    task = _task_context.get()
    if task is not None:
        return [
            ("context", "task"),
            ("task", task["task"]),
            ("task_id", task["task_id"]),
        ]
    request = _request_context.get()
    if request is not None:
        return [
            ("context", "request"),
            ("method", request["method"]),
            ("path", request["path"]),
        ]
    return [("context", "none")]


def _normalized(sql: str) -> str:
    return " ".join((sql or "").strip().split()).upper()


def _transaction_state() -> dict:
    transactions = getattr(_state, "transactions", None)
    if transactions is None:
        transactions = {}
        _state.transactions = transactions
    return transactions


def _begin_transaction(alias: str, mode: str) -> None:
    _transaction_state()[alias] = {
        "started": time.perf_counter(),
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "mode": mode,
        "queries": 0,
    }


def _finish_transaction(alias: str, outcome: str) -> None:
    state = _transaction_state().pop(alias, None)
    if state is None:
        return
    duration_ms = (time.perf_counter() - state["started"]) * 1000
    threshold = getattr(settings, "PERF_LOG_SLOW_TRANSACTION_MS", 1000)
    if duration_ms < threshold:
        return
    fields = " ".join(f"{key}={value}" for key, value in _context_fields())
    logger.info(
        "slow_transaction alias=%s mode=%s outcome=%s duration_ms=%.1f "
        "queries=%s started_at=%s pid=%s thread=%s %s",
        alias,
        state["mode"],
        outcome,
        duration_ms,
        state["queries"],
        state["started_at"],
        os.getpid(),
        threading.current_thread().name,
        fields,
    )


def track_query(execute: Callable, sql: str, params, many, context):
    """Wrap one query: time top-level transactions and record lock waits.

    Installed by the request and Celery query wrappers. A thread can have both
    active when an eager task runs inside a request, so only the outermost
    wrapper observes each statement.
    """
    depth = getattr(_state, "depth", 0)
    if depth:
        return execute(sql, params, many, context)

    _state.depth = 1
    connection = (context or {}).get("connection")
    alias = getattr(connection, "alias", "default")
    statement = _normalized(sql)
    started = time.perf_counter()
    try:
        if statement.startswith("BEGIN"):
            _begin_transaction(alias, "write" if "IMMEDIATE" in statement else "deferred")
        elif alias in _transaction_state():
            _transaction_state()[alias]["queries"] += 1
        try:
            result = execute(sql, params, many, context)
        except DatabaseError as error:
            _finish_transaction(alias, "error")
            if describe_database_error(error) is not None:
                _state.last_wait_ms = (time.perf_counter() - started) * 1000
            raise
        else:
            if statement.startswith(("COMMIT", "END")):
                _finish_transaction(alias, "commit")
            elif statement.startswith("ROLLBACK"):
                _finish_transaction(alias, "rollback")
            return result
    finally:
        _state.depth = 0


def _pop_wait_ms() -> float | None:
    value = getattr(_state, "last_wait_ms", None)
    if value is not None:
        _state.last_wait_ms = None
    return value


def _error_chain(error: BaseException):
    current = error
    while current is not None:
        yield current
        current = current.__cause__


def _sqlite_code(error: BaseException) -> int | None:
    for current in _error_chain(error):
        code = getattr(current, "sqlite_errorcode", None)
        if isinstance(code, int):
            return code
    return None


def _sqlstate(error: BaseException) -> str | None:
    for current in _error_chain(error):
        state = getattr(current, "sqlstate", None)
        if state:
            return str(state)
    return None


def describe_database_error(error: BaseException) -> DatabaseContention | None:
    """Classify a technical database failure, never an ordinary request error."""
    if not isinstance(error, DatabaseError):
        return None

    code = _sqlite_code(error)
    primary = code & _SQLITE_PRIMARY_MASK if code is not None else None
    message = " ".join(str(current).lower() for current in _error_chain(error))
    sqlstate = _sqlstate(error)

    if (
        primary in {_SQLITE_BUSY, _SQLITE_LOCKED}
        or "database is locked" in message
        or "database table is locked" in message
        or "database file is locked" in message
    ):
        kind = "locked" if primary == _SQLITE_LOCKED or "table is locked" in message else "busy"
        return DatabaseContention(
            code="DATABASE_BUSY",
            detail="The database is busy. Retry the request.",
            retryable=True,
            retry_after=DEFAULT_RETRY_AFTER_SECONDS,
            sqlite_code=code,
            sqlite_extended=code,
            kind=kind,
        )

    if sqlstate in _POSTGRES_CONTENTION_STATES:
        return DatabaseContention(
            code="DATABASE_BUSY",
            detail="The database is busy. Retry the request.",
            retryable=True,
            retry_after=DEFAULT_RETRY_AFTER_SECONDS,
            kind="postgres_contention",
        )

    if primary == _SQLITE_IOERR or any(
        signal in message
        for signal in ("disk i/o error", "disk i/o", "i/o error", "unable to open database file")
    ):
        return DatabaseContention(
            code="DATABASE_UNAVAILABLE",
            detail="The database is unavailable. Try again later.",
            retryable=False,
            retry_after=None,
            sqlite_code=code,
            sqlite_extended=code,
            kind="io_error",
        )

    return None


def _sqlite_runtime_fields() -> list[tuple[str, object]]:
    fields: list[tuple[str, object]] = []
    if getattr(settings, "USING_SQLITE_DATABASE", False):
        fields.extend(
            [
                ("journal_mode", getattr(settings, "SQLITE_JOURNAL_MODE", "unknown")),
                (
                    "busy_timeout_ms",
                    int(getattr(settings, "SQLITE_BUSY_TIMEOUT_SECONDS", 0) * 1000),
                ),
                ("transaction_mode", "IMMEDIATE"),
            ],
        )
    else:
        fields.extend([("backend", "postgresql")])
    return fields


def report_database_error(
    error: BaseException,
    *,
    request: HttpRequest | None = None,
    operation: str = "database operation",
    wait_ms: float | None = None,
) -> DatabaseContention | None:
    """Log one bounded contention diagnostic and return its API classification."""
    info = describe_database_error(error)
    if info is None:
        return None
    if getattr(error, "_floppy_db_contention_reported", False):
        return info
    measured_wait = wait_ms if wait_ms is not None else _pop_wait_ms()
    wait_field = "unknown" if measured_wait is None else f"{measured_wait:.1f}"

    fields: list[tuple[str, object]] = [
        ("code", info.code),
        ("kind", info.kind),
        ("operation", operation),
        ("wait_ms", wait_field),
        ("sqlite_code", info.sqlite_code if info.sqlite_code is not None else "-"),
        ("sqlite_extended", info.sqlite_extended if info.sqlite_extended is not None else "-"),
        # SQLite does not expose a lock owner. Say so instead of guessing one.
        ("owner", "unknown"),
        ("pid", os.getpid()),
        ("thread", threading.current_thread().name),
    ]
    if request is not None:
        fields.extend(
            [
                ("context", "request"),
                ("method", str(getattr(request, "method", "") or "")[:16]),
                ("path", _safe_path(request)),
            ],
        )
    else:
        fields.extend(_context_fields())
    fields.extend(_sqlite_runtime_fields())
    fields.append(("error", str(error)[:200].replace("\n", " ")))

    logger.warning(
        "db_contention %s",
        " ".join(f"{key}={value}" for key, value in fields),
    )
    with contextlib.suppress(Exception):
        error._floppy_db_contention_reported = True
    return info
