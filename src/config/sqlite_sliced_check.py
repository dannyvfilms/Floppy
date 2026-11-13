"""Fast, resumable background verification of a live SQLite database.

The full check is ``sqlite_page_sweep``: one pass over the file in physical
order (sequential I/O), rebuilding the page graph in memory. ``quick_check``
walks each b-tree in key order, which on churned databases and slow storage is
one random read per page (a 5.2 GB database took 1.9 h, nearly all I/O wait).

Per invocation (every few minutes, niced), oldest unit first:

* ``__pages__``: the sweep, at most every 7 days; it never needs a copy.
* per table ``foreign_key_check(table)``, at most every 7 days.
* per table ``quick_check(table)``: the deep tier (record format, key order),
  best effort, at most every 30 days, limited to ``UNIT_SECONDS`` per table;
  tables that do not finish are listed in ``deep_incomplete`` and never block.

Slices and a daily cap keep any single run short; progress persists across
restarts and image changes. Findings reuse the incident reports; nothing
repairs live rows.
"""

from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import threading
import time
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path

from config import sqlite_integrity as integrity
from config import sqlite_page_sweep as page_sweep

SLICE_SECONDS = float(os.environ.get("FLOPPY_SQLITE_VERIFY_SLICE_SECONDS", "300"))
DAILY_BUDGET_SECONDS = float(
    os.environ.get("FLOPPY_SQLITE_VERIFY_DAILY_SECONDS", "3600")
)
UNIT_SECONDS = float(os.environ.get("FLOPPY_SQLITE_VERIFY_UNIT_SECONDS", "150"))
SWEEP_SECONDS = float(os.environ.get("FLOPPY_SQLITE_VERIFY_SWEEP_SECONDS", "1800"))
REVERIFY_SECONDS = 7 * 86400.0
DEEP_SECONDS = 30 * 86400.0
_CHUNK_BYTES = 8 * 1024 * 1024
_DAY = 86400.0
_MIN_BUDGET = 5.0
_PAGES = "__pages__"
_PROGRESS_INSTRUCTIONS = 100_000


class _Expired(Exception):  # noqa: N818 - control flow, not an error
    """The unit or slice deadline passed; the work interrupted is retried."""


def _path(db_path: str) -> Path:
    return Path(f"{Path(db_path).resolve()}.verification.progress.json")


def _load(db_path: str) -> dict:
    state = integrity._read_sidecar(_path(db_path), db_path) or {}
    file_stat = Path(db_path).stat()
    identity = [file_stat.st_dev, file_stat.st_ino]
    if state.get("identity") != identity:  # replaced file: nothing carries over
        state = {"units": {}, "slices": []}
    state["identity"] = identity
    state["database"] = str(Path(db_path).resolve())
    return state


def _summarize(state: dict) -> None:
    units = state["units"]
    stamps = [u.get("verified_at") for u in units.values()]
    state["verified_through"] = min(stamps) if stamps and all(stamps) else None
    state["unverified_units"] = sorted(
        n for n, u in units.items() if not u.get("verified_at")
    )


def _save(db_path: str, state: dict) -> None:
    state["updated_at"] = datetime.now(UTC).isoformat()
    _summarize(state)
    integrity._publish_report(
        _path(db_path), json.dumps(state, sort_keys=True) + "\n", mode=0o644
    )


def _now() -> float:
    return time.time()


def _stamp() -> str:
    return datetime.now(UTC).isoformat()


def _age(unit: dict) -> float:
    verified = integrity._parse_timestamp(unit.get("verified_at"))
    return (
        float("inf")
        if verified is None
        else (datetime.now(UTC) - verified).total_seconds()
    )


@contextmanager
def _guarded(conn: sqlite3.Connection, deadline: float):
    """Interrupt the connection's statement at ``deadline``.

    The progress handler alone is not enough: ``quick_check`` runs as a single
    VDBE opcode, so only ``sqlite3_interrupt`` can stop it. The handler stays
    to pace row-reading statements.
    """

    def progress():
        time.sleep(0.002)  # pace: leave I/O and CPU to the application
        return 0

    conn.set_progress_handler(progress, _PROGRESS_INSTRUCTIONS)
    timer = threading.Timer(max(deadline - time.monotonic(), 0.0), conn.interrupt)
    timer.daemon = True
    timer.start()
    try:
        yield
    finally:
        timer.cancel()


def _fail(db_path: str, error: sqlite3.DatabaseError) -> bool:
    """Publish real damage; return False for transient (busy/IO/interrupted)."""
    code = (getattr(error, "sqlite_errorcode", 0) or 0) & 0xFF
    if code in {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB}:
        integrity._report_corruption(db_path, str(error))
        return True
    return False


def _scan_pages(db_path: str, unit: dict, deadline: float) -> bool:
    """Whole-file structural sweep in physical order; True when it passed."""
    del unit
    try:
        result = page_sweep.sweep(db_path, deadline=deadline)
    except page_sweep.SweepExpiredError:
        return False
    except page_sweep.SweepUnavailableError:
        return _read_sequentially(db_path, deadline)
    if result["problems"]:
        message = "; ".join(result["problems"][:5])
        integrity._report_corruption(db_path, f"page sweep: {message}")
        raise sqlite3.DatabaseError(message)
    return True


def _read_sequentially(db_path: str, deadline: float) -> bool:
    """Fallback when pages may live in the WAL: prove the file is readable."""
    with Path(db_path).open("rb", buffering=0) as handle:
        while handle.read(_CHUNK_BYTES):
            if time.monotonic() > deadline:
                return False
    return True


def _header_problem(conn: sqlite3.Connection, db_path: str) -> str | None:
    pages = conn.execute("PRAGMA page_count").fetchone()[0]
    size = conn.execute("PRAGMA page_size").fetchone()[0]
    free = conn.execute("PRAGMA freelist_count").fetchone()[0]
    on_disk = Path(db_path).stat().st_size
    wal = Path(f"{db_path}-wal")
    if wal.exists() and wal.stat().st_size:
        return None  # pages may exist only in the WAL; the size test would lie
    if pages * size > on_disk:
        return f"header page_count*page_size={pages * size} exceeds file size {on_disk}"
    if free > pages:
        return f"freelist_count {free} exceeds page_count {pages}"
    return None


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _interrupted(error: sqlite3.OperationalError) -> bool:
    if "interrupt" not in str(error).lower():
        raise error
    return True


def _check_table(
    conn, db_path: str, table: str, unit: dict, slice_deadline: float
) -> bool:
    """Verify one table; True when it is finished this slice.

    The relationship check is required. The deep ``quick_check`` is best effort:
    it walks b-trees in key order (random reads on slow storage), so it runs at
    most every ``DEEP_SECONDS`` and a table that exceeds ``UNIT_SECONDS`` is
    recorded in ``deep_incomplete`` rather than blocking verification.
    """
    deep_age = _age({"verified_at": unit.get("deep_at")})
    if deep_age > DEEP_SECONDS and "deep_tried" not in unit:
        unit["deep_tried"] = True
        unit_deadline = time.monotonic() + UNIT_SECONDS
        try:
            with _guarded(conn, min(slice_deadline, unit_deadline)):
                result = conn.execute(f"PRAGMA quick_check({_quote(table)})").fetchall()
        except sqlite3.OperationalError as error:
            _interrupted(error)
            unit["deep_incomplete"] = True
        else:
            if result != [("ok",)]:
                integrity._report_corruption(
                    db_path, f"quick_check({table}): {result[0][0]}"
                )
                raise sqlite3.DatabaseError(result[0][0])
            unit["deep_at"] = _stamp()
            unit.pop("deep_incomplete", None)
    if "fk_done" not in unit:
        try:
            with _guarded(conn, slice_deadline):
                incident = integrity._inspect_foreign_keys(conn, only_table=table)
        except sqlite3.OperationalError as error:
            _interrupted(error)
            unit["fk_incomplete"] = True  # not resumable; retried next slice
            return False
        if incident["total_conflicts"]:
            integrity._write_incident_report(db_path, incident, status="blocked")
            msg = f"foreign-key conflicts in {table}; no live rows changed"
            raise sqlite3.IntegrityError(msg)
        unit["fk_done"] = True
        unit.pop("fk_incomplete", None)
    return True


def request_deferred_quick_check(db_path: str, *, reason: str) -> None:
    """Make the next slices re-run every table's ``quick_check`` promptly.

    The pre-migration snapshot was gated by the page sweep only, so record
    format and key order are unproven until this runs on the migrated database.
    Clearing each unit's verification makes all of them due, and clearing
    ``deep_at`` makes the deep tier eligible regardless of its 30-day cadence.
    """
    state = _load(db_path)
    for unit in state.setdefault("units", {}).values():
        for key in ("verified_at", "deep_at", "deep_incomplete", "deep_tried"):
            unit.pop(key, None)
    state["deferred_quick_check"] = {"requested_at": _stamp(), "reason": reason}
    _save(db_path, state)
    integrity._log(f"[sqlite-verification] deferred quick_check scheduled ({reason})")


def _settle_deferred(state: dict) -> None:
    """Close the deferred request once every table has had its deep check."""
    deferred = state.get("deferred_quick_check")
    if not deferred:
        return
    tables = [n for n in state["units"] if n != _PAGES]
    pending = sorted(n for n in tables if not state["units"][n].get("deep_at"))
    deferred["pending_tables"] = pending
    if not pending:
        state.pop("deferred_quick_check")
        integrity._log("[sqlite-verification] deferred quick_check completed")


def run_slice(db_path: str) -> dict:
    """Do one bounded slice of verification; returns the persisted state."""
    started = time.monotonic()
    state = _load(db_path)
    now = _now()
    state["slices"] = [s for s in state.get("slices", []) if now - s[0] < _DAY]
    budget = DAILY_BUDGET_SECONDS - sum(s[1] for s in state["slices"])
    if budget < _MIN_BUDGET:
        state["status"] = "waiting-budget"
        _save(db_path, state)
        return state
    slice_deadline = started + min(SLICE_SECONDS, budget)
    lock_descriptor = os.open(
        f"{db_path}.verification.lock", os.O_RDWR | os.O_CREAT, 0o600
    )
    with os.fdopen(lock_descriptor, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            state["status"] = "another-verifier-running"
            return state
        state["status"] = "running"
        try:
            with closing(
                sqlite3.connect(
                    f"{Path(db_path).resolve().as_uri()}?mode=ro",
                    uri=True,
                    timeout=5,
                    check_same_thread=False,
                )
            ) as conn:
                conn.execute("PRAGMA cache_size=-65536")
                conn.execute("PRAGMA mmap_size=0")
                tables = sorted(
                    r[0]
                    for r in conn.execute(
                        "SELECT name FROM sqlite_schema WHERE type='table' "
                        "AND name NOT LIKE 'sqlite_%'"
                    )
                )
                units = state["units"]
                for name in [_PAGES, *tables]:
                    units.setdefault(name, {})
                for name in list(units):
                    if name not in {_PAGES, *tables}:
                        del units[name]
                problem = _header_problem(conn, db_path)
                if problem:
                    integrity._report_corruption(db_path, problem)
                    state["status"] = "failed"
                    state["error"] = problem
                    return state
                due = sorted(
                    (n for n in units if _age(units[n]) > REVERIFY_SECONDS),
                    key=lambda n: (-_age(units[n]), n != _PAGES, n),
                )
                for name in due:
                    if time.monotonic() >= slice_deadline:
                        break
                    unit = units[name]
                    started_unit = time.monotonic()
                    if _age(unit) <= REVERIFY_SECONDS:
                        continue
                    if name == _PAGES:
                        finished = _scan_pages(
                            db_path, unit, started_unit + SWEEP_SECONDS
                        )
                    else:
                        finished = _check_table(
                            conn, db_path, name, unit, slice_deadline
                        )
                    if finished:
                        keep = {
                            k: unit[k]
                            for k in ("deep_at", "deep_incomplete")
                            if k in unit
                        }
                        units[name] = {**keep, "verified_at": _stamp()}
                    _save(db_path, state)
                _settle_deferred(state)
                _summarize(state)
                state["status"] = "partial" if state["unverified_units"] else "ok"
        except sqlite3.DatabaseError as error:
            state["status"] = "failed"
            state["error"] = str(error)
            _fail(db_path, error)
            if isinstance(error, sqlite3.IntegrityError):
                state["status"] = "blocked"
        finally:
            state["slices"].append([now, time.monotonic() - started])
            _save(db_path, state)
    return state
