"""Test helpers that show when a request needs SQLite's single write lock.

``record_writes`` lists the statements SQLite itself reports that are not
reads. Django's ``execute_wrapper`` is not enough for this: the ``BEGIN
IMMEDIATE`` that takes the write lock never passes through it.

``use_database_file`` and ``hold_write_lock`` reproduce a busy writer. The
suite's shared in-memory database cannot: it answers a second connection with
a table lock that ignores ``busy_timeout``, where a database file waits.
"""

from __future__ import annotations

import sqlite3
import threading
import traceback
from contextlib import contextmanager
from dataclasses import dataclass

from django.db import connection, connections

READ_KEYWORDS = frozenset({"SELECT", "PRAGMA", "EXPLAIN", "WITH"})
# Frames that every statement passes through and that name no write source.
_PASS_THROUGH = (
    "app/tests/sqlite_writes.py",
    "app/db_diagnostics.py",
    "app/request_timing.py",
)
_SRC_MARKER = "/src/"


@dataclass(frozen=True, slots=True)
class Write:
    """One non-read statement and the application code that issued it."""

    keyword: str
    sql: str
    source: str


def _source(stack) -> str:
    """Name the innermost application function below the test itself."""
    session_save = False
    for frame in reversed(stack):
        filename = frame.filename
        if "/django/contrib/sessions/" in filename:
            session_save = True
        if _SRC_MARKER not in filename or "/site-packages/" in filename:
            continue
        relative = filename.split(_SRC_MARKER)[-1]
        if relative.startswith(_PASS_THROUGH) or "/tests/" in relative:
            continue
        if session_save:
            return "django.contrib.sessions"
        if relative == "app/middleware.py":
            # Reached a middleware with no view frame below it: the write came
            # from Django or a third-party middleware, not from Floppy code.
            continue
        return f"{relative}:{frame.name}"
    return "django.contrib.sessions" if session_save else "unknown"


@contextmanager
def record_writes():
    """Collect every non-read statement the default connection runs."""
    writes: list[Write] = []

    def trace(statement: str) -> None:
        words = statement.split(None, 1)
        keyword = words[0].upper() if words else ""
        if keyword in READ_KEYWORDS:
            return
        writes.append(
            Write(keyword, statement[:120], _source(traceback.extract_stack()[:-1]))
        )

    connection.ensure_connection()
    raw = connection.connection
    raw.set_trace_callback(trace)
    try:
        yield writes
    finally:
        raw.set_trace_callback(None)


def copy_database_to_file(path) -> None:
    """Copy the default database, schema and rows, into a WAL database file.

    Call it outside any transaction (before ``TestCase.setUpClass``): SQLite's
    backup waits for an open write transaction on the source to end.
    """
    source = connections["default"]
    source.ensure_connection()
    target = sqlite3.connect(path)
    try:
        source.connection.backup(target)
        target.execute("PRAGMA journal_mode=WAL")
    finally:
        target.close()


@contextmanager
def use_database_file(path, *, busy_timeout_seconds: float = 5.0):
    """Point the default connection at a database file for the block.

    The settings match production where it matters here:
    ``transaction_mode=IMMEDIATE`` and a busy timeout.
    """
    original = connections["default"]
    replacement = type(original)(
        {
            **original.settings_dict,
            "NAME": str(path),
            "OPTIONS": {
                "timeout": busy_timeout_seconds,
                "transaction_mode": "IMMEDIATE",
            },
        },
        "default",
    )
    connections["default"] = replacement
    try:
        yield
    finally:
        replacement.close()
        connections["default"] = original


@contextmanager
def hold_write_lock(path, *, seconds: float | None = None):
    """Hold SQLite's write lock from a second connection.

    With ``seconds`` the lock is released by a timer, as a real writer would;
    without it the lock lasts for the whole block.
    """
    holder = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    holder.execute("BEGIN IMMEDIATE")
    timer = None
    released = threading.Event()

    def release() -> None:
        if not released.is_set():
            released.set()
            holder.execute("ROLLBACK")

    if seconds is not None:
        timer = threading.Timer(seconds, release)
        timer.start()
    try:
        yield
    finally:
        if timer is not None:
            timer.cancel()
            timer.join()
        release()
        holder.close()
