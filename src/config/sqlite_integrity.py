from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import sqlite3
import stat
import sys
import tempfile
import time
from collections import Counter
from contextlib import suppress
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

_CORRUPTION_HINT = (
    "[entrypoint] The SQLite file may be corrupt (see README: SQLite "
    "network filesystem caveat)"
)
_RELATIONSHIP_HINT = (
    "[entrypoint] Back up the SQLite file, then inspect these relationship "
    "errors before you restart"
)
_BUSY_HINT = (
    "[entrypoint] The SQLite database is busy. Stop other Floppy processes, "
    "then restart"
)
_ALBUM_ARTIST_TABLE = "app_albumartist"
_ACTION_ENV = "FLOPPY_SQLITE_CONFLICT_ACTION"
_MAX_CONFLICT_SAMPLES = 5
_MAX_AFFECTED_TITLES = 5
_REPORT_SUFFIX = ".integrity.json"
_DECISION_SUFFIX = ".integrity.decision"
_STATUS_SUFFIX = ".integrity.status.json"
_RECOVERY_PAGE_NAME = "floppy-recovery.html"
_PROGRESS_QUIET_AFTER_SECONDS = 45.0
# Lock contention and scan duration are different failures and need different
# bounds. A long busy timeout turns a fast "another process holds the database"
# answer into a long stall, so the diagnostic scan waits briefly for the lock and
# bounds the scan itself with a progress handler instead.
_SCAN_BUSY_TIMEOUT_SECONDS = 5.0
_SCAN_PROGRESS_INSTRUCTIONS = 10_000


def _log(message: str) -> None:
    """Write one operator line to stderr, where the entrypoint collects it."""
    print(message, file=sys.stderr)  # noqa: T201


class _ResolvedReportPublicationError(OSError):
    def __init__(self, message: str, *, previous_restored: bool):
        super().__init__(message)
        self.previous_restored = previous_restored


def _inspect_foreign_keys(conn: sqlite3.Connection) -> dict:
    """Summarize every relationship conflict without retaining every row."""
    counts = Counter()
    samples = []
    conflict_hash = 0
    can_quarantine = True
    total = 0

    for table, row_id, parent, foreign_key_id in conn.execute(
        "PRAGMA foreign_key_check"
    ):
        total += 1
        counts[(table, parent, foreign_key_id)] += 1
        can_quarantine = can_quarantine and row_id is not None
        if len(samples) < _MAX_CONFLICT_SAMPLES:
            samples.append(
                {
                    "foreign_key_id": foreign_key_id,
                    "parent": parent,
                    "row": row_id,
                    "table": table,
                }
            )
        conflict_hash = (
            conflict_hash
            + int.from_bytes(
                sha256(
                    json.dumps(
                        [table, row_id, parent, foreign_key_id],
                        separators=(",", ":"),
                    ).encode()
                ).digest(),
                byteorder="big",
            )
        ) % (1 << 256)

    groups = [
        {
            "count": count,
            "foreign_key_id": foreign_key_id,
            "parent": parent,
            "table": table,
        }
        for (table, parent, foreign_key_id), count in sorted(counts.items())
    ]
    unsafe_reasons = []
    affected_tables = {table for table, _parent, _foreign_key_id in counts}
    for table in sorted(affected_tables):
        schema_rows = conn.execute(
            "SELECT type, sql FROM main.sqlite_schema WHERE name = ? COLLATE BINARY",
            [table],
        ).fetchall()
        if len(schema_rows) != 1 or schema_rows[0][0] != "table":
            unsafe_reasons.append(f"affected object {table!r} is not one main table")
            continue
        shadowed_aliases = sorted(
            name
            for name, in conn.execute(
                "SELECT name FROM pragma_table_xinfo(?, 'main')",
                [table],
            )
            if name.casefold() in {"rowid", "_rowid_", "oid"}
        )
        if shadowed_aliases:
            unsafe_reasons.append(
                f"affected table {table!r} declares {shadowed_aliases!r} and "
                "shadows hidden row identity"
            )
        # sqlite_schema.tbl_name keeps the spelling used by CREATE TRIGGER while
        # foreign_key_check reports the canonical table name. SQLite resolves
        # both case-insensitively, so a BINARY match would miss a trigger
        # declared as ON CHILD and let quarantine fire it.
        triggers = conn.execute(
            "SELECT name FROM main.sqlite_schema "
            "WHERE type = 'trigger' AND tbl_name = ? COLLATE NOCASE "
            "UNION ALL SELECT name FROM temp.sqlite_schema "
            "WHERE type = 'trigger' AND tbl_name = ? COLLATE NOCASE",
            [table, table],
        )
        for trigger_name, in triggers:
            unsafe_reasons.append(
                f"affected table {table!r} has trigger {trigger_name!r}; "
                "DELETE trigger safety cannot be proven"
            )

    if not can_quarantine:
        unsafe_reasons.append("one or more affected tables use WITHOUT ROWID")
    can_quarantine = can_quarantine and not unsafe_reasons
    fingerprint_source = json.dumps(
        {
            "conflict_hash": f"{conflict_hash:064x}",
            "groups": groups,
            "total": total,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return {
        "can_quarantine": can_quarantine,
        "fingerprint": sha256(fingerprint_source.encode()).hexdigest(),
        "groups": groups,
        "samples": samples,
        "total_conflicts": total,
        "unsafe_reasons": unsafe_reasons,
    }


def _incident_report_path(db_path: str) -> Path:
    database_path = Path(db_path).resolve()
    return database_path.with_name(f"{database_path.name}{_REPORT_SUFFIX}")


def _read_incident_report(db_path: str) -> dict | None:
    report_path = _incident_report_path(db_path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(report_path, flags)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return None
        with os.fdopen(descriptor) as report_file:
            descriptor = -1
            report = json.load(report_file)
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return None
    finally:
        if descriptor != -1:
            os.close(descriptor)
    if report.get("database") != str(Path(db_path).resolve()):
        return None
    return report


def _status_path(db_path: str) -> Path:
    database_path = Path(db_path).resolve()
    return database_path.with_name(f"{database_path.name}{_STATUS_SUFFIX}")


def write_startup_status(
    db_path: str,
    *,
    status: str,
    phase: str,
    started_at: str,
    elapsed_seconds: float,
    read_bytes: int | None = None,
    progress_callbacks: int | None = None,
    phase_started_at: str | None = None,
    last_progress_at: str | None = None,
    error_class: str | None = None,
    error_message: str | None = None,
    version: str | None = None,
    commit_sha: str | None = None,
) -> None:
    """Persist a bounded, non-secret snapshot of the startup scan's progress.

    Unlike the incident report, this sidecar carries nothing that needs the
    approval-token protections behind ``_publish_report``'s default mode, so
    it is published world-readable. A write failure here is logged and
    swallowed: this file only describes what was happening when the scan was
    last observed, and must never itself change whether startup may continue.
    """
    updated_at = datetime.now(UTC)
    payload = {
        "commit_sha": commit_sha,
        "database": str(Path(db_path).resolve()),
        "elapsed_seconds": elapsed_seconds,
        "error_class": error_class,
        "error_message": error_message,
        "phase": phase,
        "phase_started_at": phase_started_at or started_at,
        "progress_callbacks": progress_callbacks,
        "last_progress_at": last_progress_at,
        "read_bytes": read_bytes,
        "schema_version": 1,
        "started_at": started_at,
        "status": status,
        "updated_at": updated_at.isoformat(),
        "version": version,
    }
    diagnostics = startup_progress_diagnostics(payload, now=updated_at)
    payload.update(
        {
            "progress_age_seconds": diagnostics["last_progress_age_seconds"],
            "progress_rate_per_minute": diagnostics["progress_rate_per_minute"],
            "progress_state": diagnostics["progress_state"],
        }
    )
    contents = json.dumps(payload, sort_keys=True) + "\n"
    try:
        _publish_report(_status_path(db_path), contents, mode=0o644)
    except OSError as error:
        _log(f"[entrypoint] Could not publish SQLite startup status: {error}")


def read_startup_status(db_path: str) -> dict | None:
    """Read the startup-status sidecar, or ``None`` if absent or unreadable."""
    status_path = _status_path(db_path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(status_path, flags)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return None
        with os.fdopen(descriptor) as status_file:
            descriptor = -1
            status = json.load(status_file)
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return None
    finally:
        if descriptor != -1:
            os.close(descriptor)
    if not isinstance(status, dict) or status.get("database") != str(
        Path(db_path).resolve()
    ):
        return None
    return status


def _live_elapsed_text(status: dict) -> str:
    """Compute elapsed time as of now, not as of the sidecar's last write.

    A phase that blocks on one long call has no progress callback to update
    the sidecar with -- ``PRAGMA quick_check`` on a large file, for example,
    writes its status once at the start of the phase and not again until it
    finishes. Echoing the stored ``elapsed_seconds`` verbatim would freeze
    every heartbeat at that phase's start time for its entire duration,
    which is exactly the case a heartbeat exists to cover.
    """
    try:
        started = datetime.fromisoformat(str(status.get("started_at")))
    except (TypeError, ValueError):
        elapsed = status.get("elapsed_seconds")
        return f"{elapsed:.0f}s" if isinstance(elapsed, int | float) else "unknown"
    elapsed = (datetime.now(UTC) - started).total_seconds()
    return f"{max(elapsed, 0):.0f}s"


def _parse_timestamp(value: object) -> datetime | None:
    try:
        timestamp = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp


def _timestamp_age_seconds(value: object, *, now: datetime) -> float | None:
    timestamp = _parse_timestamp(value)
    if timestamp is None:
        return None
    return max((now - timestamp).total_seconds(), 0.0)


def startup_progress_diagnostics(
    status: dict,
    *,
    now: datetime | None = None,
) -> dict:
    """Calculate operator-facing progress facts from one status snapshot.

    A quiet progress state means that no SQLite VM progress callback has been
    observed recently. It is a useful warning about slow I/O or a blocked
    operation, not proof that the database is corrupt or permanently stuck.
    Timeout snapshots use their own publication time as the reference so the
    report describes the scan when it stopped, even if the page is opened much
    later.
    """
    reference = now or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    if status.get("status") == "timeout":
        timeout_at = _parse_timestamp(status.get("updated_at"))
        if timeout_at is not None:
            reference = timeout_at

    phase_elapsed = _timestamp_age_seconds(
        status.get("phase_started_at") or status.get("started_at"),
        now=reference,
    )
    progress_age = _timestamp_age_seconds(
        status.get("last_progress_at"),
        now=reference,
    )
    progress_callbacks = status.get("progress_callbacks")
    if not isinstance(progress_callbacks, int | float):
        progress_callbacks = None

    if progress_age is None and progress_callbacks == 0:
        progress_age = phase_elapsed
        progress_state = (
            "quiet"
            if progress_age is not None
            and progress_age > _PROGRESS_QUIET_AFTER_SECONDS
            else "none_yet"
        )
    elif progress_age is None:
        progress_state = "unknown"
    elif progress_age > _PROGRESS_QUIET_AFTER_SECONDS:
        progress_state = "quiet"
    else:
        progress_state = "active"

    progress_rate = None
    if progress_callbacks is not None and phase_elapsed and phase_elapsed > 0:
        progress_rate = progress_callbacks / phase_elapsed * 60

    return {
        "last_progress_age_seconds": progress_age,
        "phase_elapsed_seconds": phase_elapsed,
        "progress_callbacks": progress_callbacks,
        "progress_rate_per_minute": progress_rate,
        "progress_state": progress_state,
    }


def _format_seconds(value: object) -> str:
    return f"{value:.0f}s" if isinstance(value, int | float) else "unknown"


def print_startup_heartbeat(db_path: str) -> None:
    """Emit one operator heartbeat line from the startup-status sidecar.

    Called periodically by the entrypoint while the scan runs, in place of the
    ``/proc/<pid>/io`` polling this used to do directly. Best-effort only: a
    missing or unreadable sidecar still produces a line rather than silence.
    """
    status = read_startup_status(db_path)
    if status is None:
        _log("[entrypoint] SQLite integrity scan heartbeat: still running")
        return
    phase = status.get("phase", "unknown")
    diagnostics = startup_progress_diagnostics(status)
    detail = (
        f"phase={phase} elapsed={_live_elapsed_text(status)} "
        f"phase_elapsed={_format_seconds(diagnostics['phase_elapsed_seconds'])}"
    )
    read_bytes = status.get("read_bytes")
    if isinstance(read_bytes, int | float) and read_bytes:
        detail += f" read={read_bytes / 1_048_576:.0f}MB"
    progress_callbacks = status.get("progress_callbacks")
    if isinstance(progress_callbacks, int | float):
        detail += f" progress_callbacks={progress_callbacks:.0f}"
    progress_rate = diagnostics["progress_rate_per_minute"]
    if isinstance(progress_rate, int | float):
        detail += f" progress_rate={progress_rate:.1f}/min"
    progress_age = diagnostics["last_progress_age_seconds"]
    progress_age_text = _format_seconds(progress_age)
    detail += (
        f" last_progress={progress_age_text}_ago"
        if progress_age_text != "unknown"
        else " last_progress=unknown"
    )
    detail += f" progress_state={diagnostics['progress_state']}"
    _log(f"[entrypoint] SQLite integrity scan heartbeat: {detail}")


def mark_startup_status_timeout(db_path: str, timeout_seconds: float) -> None:
    """Ensure the sidecar reflects a timeout even if the scanner was killed.

    Also logs the last observed phase/elapsed/bytes. The entrypoint's
    external ``timeout`` wrapper can SIGKILL the scanner
    before it publishes its own terminal status, so this is called from the
    shell immediately after that happens. It preserves whatever the scanner
    last reported and only fills in what is missing.
    """
    previous = read_startup_status(db_path) or {}
    phase = previous.get("phase", "unknown")
    elapsed = previous.get("elapsed_seconds")
    elapsed = float(elapsed) if isinstance(elapsed, int | float) else float(timeout_seconds)
    elapsed = max(elapsed, float(timeout_seconds))
    read_bytes = previous.get("read_bytes")
    progress_callbacks = previous.get("progress_callbacks")
    phase_started_at = previous.get("phase_started_at")
    last_progress_at = previous.get("last_progress_at")
    write_startup_status(
        db_path,
        status="timeout",
        phase=phase,
        started_at=previous.get("started_at") or datetime.now(UTC).isoformat(),
        elapsed_seconds=elapsed,
        read_bytes=read_bytes,
        progress_callbacks=progress_callbacks,
        phase_started_at=phase_started_at,
        last_progress_at=last_progress_at,
        error_class="timeout",
        error_message=f"scan exceeded {timeout_seconds:g}s",
        version=previous.get("version") or os.environ.get("VERSION"),
        commit_sha=previous.get("commit_sha") or os.environ.get("COMMIT_SHA"),
    )
    timeout_status = read_startup_status(db_path) or previous
    diagnostics = startup_progress_diagnostics(timeout_status)
    detail = (
        f"phase={phase} elapsed={elapsed:.0f}s "
        f"phase_elapsed={_format_seconds(diagnostics['phase_elapsed_seconds'])}"
    )
    if isinstance(read_bytes, int | float) and read_bytes:
        detail += f" read={read_bytes / 1_048_576:.0f}MB"
    if isinstance(progress_callbacks, int | float):
        detail += f" progress_callbacks={progress_callbacks:.0f}"
    progress_rate = diagnostics["progress_rate_per_minute"]
    if isinstance(progress_rate, int | float):
        detail += f" progress_rate={progress_rate:.1f}/min"
    progress_age = diagnostics["last_progress_age_seconds"]
    progress_age_text = _format_seconds(progress_age)
    detail += (
        f" last_progress={progress_age_text}_ago"
        if progress_age_text != "unknown"
        else " last_progress=unknown"
    )
    detail += f" progress_state={diagnostics['progress_state']}"
    _log(
        "[entrypoint] SQLite integrity scan timed out after "
        f"{timeout_seconds:g}s; last observed {detail}",
    )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish_report(report_path: Path, contents: str, *, mode: int = 0o600) -> None:
    """Publish text atomically, so a reader never sees a half-written file.

    The report holds an approval token and stays owner-only. The recovery page
    holds nothing secret and must stay readable by the person who opens it.
    """
    descriptor, temporary_name = tempfile.mkstemp(
        dir=report_path.parent,
        prefix=f".{report_path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w") as report_file:
            descriptor = -1
            report_file.write(contents)
            report_file.flush()
            os.fsync(report_file.fileno())
        temporary_path.replace(report_path)
        _fsync_directory(report_path.parent)
    finally:
        if descriptor != -1:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)


def _write_incident_report(
    db_path: str,
    incident: dict,
    *,
    status: str,
    resolution: str | None = None,
    backup_path: Path | None = None,
    incident_token: str | None = None,
    deleted_rows: int | None = None,
) -> Path:
    """Persist a bounded machine-readable recovery report beside SQLite."""
    report_path = _incident_report_path(db_path)
    actions = {"halt": "halt"}
    if status == "blocked" and incident_token:
        actions["accept"] = f"accept:{incident_token}"
        if incident["can_quarantine"]:
            actions["quarantine"] = f"quarantine:{incident_token}"
    payload = {
        "actions": actions,
        "affected": incident.get("affected", []),
        "affected_other_titles": incident.get("other_titles", 0),
        "affected_other_titles_count": incident.get("other_titles_count", 0),
        "affected_unidentified": incident.get("unidentified", 0),
        "backup_path": str(backup_path) if backup_path else None,
        "can_quarantine": incident["can_quarantine"],
        "database": str(Path(db_path).resolve()),
        "deleted_rows": deleted_rows,
        "fingerprint": incident["fingerprint"],
        "groups": incident["groups"],
        "incident_token": incident_token,
        "recorded_at": datetime.now(UTC).isoformat(),
        "resolution": resolution,
        "samples": incident["samples"],
        "status": status,
        "total_conflicts": incident["total_conflicts"],
        "unsafe_reasons": incident.get("unsafe_reasons", []),
        "version": 1,
    }
    contents = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    previous = _read_incident_report(db_path) if status == "resolved" else None
    try:
        _publish_report(report_path, contents)
    except OSError as publication_error:
        if previous is None:
            raise
        previous_contents = json.dumps(previous, indent=2, sort_keys=True) + "\n"
        try:
            _publish_report(report_path, previous_contents)
        except OSError as restoration_error:
            message = (
                "resolved report publication failed and prior report restoration "
                f"could not be confirmed: {restoration_error}"
            )
            raise _ResolvedReportPublicationError(
                message,
                previous_restored=False,
            ) from publication_error
        message = f"resolved report publication failed: {publication_error}"
        raise _ResolvedReportPublicationError(
            message,
            previous_restored=True,
        ) from publication_error
    return report_path


def _print_incident(db_path: str, incident: dict) -> None:
    shown = len(incident["samples"])
    _log(
        f"[entrypoint] Found {incident['total_conflicts']} foreign key conflict(s) "
        f"across {len(incident['groups'])} relationship group(s); showing {shown}",
    )
    for sample in incident["samples"]:
        _log(
            "[entrypoint] Database foreign key check failed: "
            f"table={sample['table']!r}, row={sample['row']!r}, "
            f"parent={sample['parent']!r}",
        )
    _log(
        f"[entrypoint] Incident fingerprint: {incident['fingerprint']}",
    )
    _log(
        f"[entrypoint] Bounded report: {_incident_report_path(db_path)}",
    )


def _print_resolution_options(incident: dict, incident_token: str) -> None:
    _log(
        "[entrypoint] Resolution options (back up the database first):",
    )
    _log(
        "[entrypoint] - Restore a known-good SQLite backup, then restart.",
    )
    _log(
        "[entrypoint] - Accept without changing rows: "
        f"{_ACTION_ENV}=accept:{incident_token}",
    )
    if incident["can_quarantine"]:
        _log(
            "[entrypoint] - Back up and remove orphaned child rows: "
            f"{_ACTION_ENV}=quarantine:{incident_token}",
        )
    else:
        for reason in incident.get("unsafe_reasons", []):
            _log(f"[entrypoint] - Manual repair required: {reason}")


def _decision_path(db_path: str) -> Path:
    database_path = Path(db_path).resolve()
    return database_path.with_name(f"{database_path.name}{_DECISION_SUFFIX}")


def _read_decision(db_path: str, incident: dict, incident_token: str) -> str | None:
    """Read a choice made on the recovery page, then remove the file.

    The choice carries the identity of the incident it was made for. A choice
    made for an earlier incident must never apply to a later one, so the file
    is held to the same test as the environment variable.
    """
    decision_path = _decision_path(db_path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(decision_path, flags)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return None
        with os.fdopen(descriptor) as decision_file:
            descriptor = -1
            decision = json.load(decision_file)
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        decision = None
    finally:
        if descriptor != -1:
            os.close(descriptor)
    # Remove the file whether or not it was valid. A choice is used once.
    with suppress(OSError):
        decision_path.unlink()
    if not isinstance(decision, dict):
        return None
    if decision.get("fingerprint") != incident["fingerprint"]:
        _log(
            "[entrypoint] The choice on file was made for a different problem; "
            "using halt",
        )
        return None
    token = decision.get("token")
    if token and token != incident_token:
        _log("[entrypoint] The choice on file has an old code; using halt")
        return None
    action = decision.get("action")
    return action if action in {"accept", "quarantine"} else None


def _selected_action(incident: dict, incident_token: str) -> str:
    configured = os.environ.get(_ACTION_ENV, "halt").strip()
    if not configured or configured == "halt":
        return "halt"

    action, separator, supplied_token = configured.partition(":")
    if action not in {"accept", "quarantine"}:
        _log(
            f"[entrypoint] Invalid {_ACTION_ENV}={configured!r}; using halt",
        )
        return "halt"
    if separator and supplied_token != incident_token:
        # The operator supplied a token, but it does not match current incident
        _log(
            f"[entrypoint] {_ACTION_ENV} does not carry the current incident "
            f"token for fingerprint {incident['fingerprint']}; using halt",
        )
        return "halt"
    return action


def _prune_recovery_backups(recovery_dir: Path, max_keep: int = 10) -> None:
    """Retain only the most recent recovery backups to bound disk usage."""
    try:
        backups = [
            path
            for path in recovery_dir.glob("*.sqlite3")
            if path.is_file() and not path.is_symlink() and not path.name.startswith(".")
        ]
        if len(backups) <= max_keep:
            return
        backups.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for stale in backups[max_keep:]:
            with suppress(OSError):
                stale.unlink()
    except OSError:
        pass


def _check_disk_space(recovery_dir: Path, database_path: Path) -> None:
    """Verify available space before attempting to stage a backup."""
    try:
        free_bytes = shutil.disk_usage(recovery_dir).free
    except (AttributeError, OSError):
        return
    db_size = database_path.stat().st_size
    if free_bytes < db_size:
        message = (
            f"insufficient free disk space in {recovery_dir} "
            f"({free_bytes} bytes free, {db_size} bytes needed for backup)"
        )
        raise OSError(message)


def _report_corruption(db_path: str, reason: str) -> None:
    """Publish the report that makes the recovery page show the damaged card.

    A damaged file cannot be repaired by removing rows, so any choice left on
    disk is stale. It is removed here; otherwise the entrypoint sees a choice
    that no code path consumes and never parks.
    """
    with suppress(OSError):
        _decision_path(db_path).unlink()
    try:
        _write_incident_report(
            db_path,
            {
                # groups and samples are read without a default, so a report
                # that omits them is never written and the page never appears.
                "groups": [],
                "samples": [],
                "total_conflicts": 0,
                "fingerprint": secrets.token_hex(32),
                "can_quarantine": False,
                "unsafe_reasons": [f"Physical corruption detected: {reason}"],
            },
            status="corrupt",
        )
    except (OSError, KeyError, TypeError, ValueError) as error:
        # The page is a courtesy; the log is the record. Say why it is missing
        # rather than hiding the reason behind a bare except.
        _log(f"[entrypoint] Could not publish the damaged-file report: {error}")


def _create_verified_backup(db_path: str, fingerprint: str) -> Path:
    """Create a consistent SQLite backup while the caller holds the write lock."""
    database_path = Path(db_path).resolve()
    recovery_dir = database_path.parent / "sqlite-recovery"
    with suppress(FileExistsError):
        recovery_dir.mkdir(mode=0o700)
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        recovery_descriptor = os.open(recovery_dir, directory_flags)
    except OSError as error:
        message = f"recovery directory is not a safe real directory: {error}"
        raise OSError(message) from error
    recovery_stat = os.fstat(recovery_descriptor)
    try:
        if not stat.S_ISDIR(recovery_stat.st_mode):
            message = "recovery directory is not a safe real directory"
            raise OSError(message)
        os.fchmod(recovery_descriptor, 0o700)
        _check_disk_space(recovery_dir, database_path)

        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        final_name = (
            f"{database_path.stem}-{timestamp}-{fingerprint}-"
            f"{secrets.token_hex(4)}.sqlite3"
        )
        staging_name = f".{database_path.stem}-{secrets.token_hex(16)}.sqlite3.tmp"
        staging_descriptor = os.open(
            staging_name,
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=recovery_descriptor,
        )
        os.close(staging_descriptor)
        staging_path = Path(f"/proc/self/fd/{recovery_descriptor}/{staging_name}")

        source = None
        destination = None
        published = False
        succeeded = False
        try:
            source = sqlite3.connect(f"{database_path.as_uri()}?mode=ro", uri=True)
            destination = sqlite3.connect(staging_path)
            source.backup(destination)
            result = destination.execute("PRAGMA quick_check").fetchone()
            if not result or result[0] != "ok":
                message = "backup quick_check did not return 'ok'"
                raise sqlite3.DatabaseError(message)
            destination.close()
            destination = None
            source.close()
            source = None

            staging_descriptor = os.open(
                staging_name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=recovery_descriptor,
            )
            try:
                if not stat.S_ISREG(os.fstat(staging_descriptor).st_mode):
                    message = "backup staging path is not a regular file"
                    raise OSError(message)
                os.fsync(staging_descriptor)
            finally:
                os.close(staging_descriptor)

            current_stat = recovery_dir.stat(follow_symlinks=False)
            if (current_stat.st_dev, current_stat.st_ino) != (
                recovery_stat.st_dev,
                recovery_stat.st_ino,
            ):
                message = "recovery directory changed during backup"
                raise OSError(message)
            os.link(
                staging_name,
                final_name,
                src_dir_fd=recovery_descriptor,
                dst_dir_fd=recovery_descriptor,
                follow_symlinks=False,
            )
            published = True
            os.unlink(staging_name, dir_fd=recovery_descriptor)
            os.fsync(recovery_descriptor)
            succeeded = True
            # Prune after the new copy is in place, never before. Pruning first
            # would leave max_keep copies and then add one more, so the folder
            # would settle one above the bound it is meant to hold.
            _prune_recovery_backups(recovery_dir)
            return recovery_dir / final_name
        finally:
            if destination is not None:
                destination.close()
            if source is not None:
                source.close()
            with suppress(FileNotFoundError):
                os.unlink(staging_name, dir_fd=recovery_descriptor)
            # Key the rollback off this call's own outcome. sys.exc_info() also
            # reports an exception the caller is already handling, which would
            # delete a good backup and leave the delete path without one.
            if published and not succeeded:
                with suppress(FileNotFoundError):
                    os.unlink(final_name, dir_fd=recovery_descriptor)
    finally:
        os.close(recovery_descriptor)


def create_live_database_snapshot(
    db_path: str,
    dest_dir: Path,
    *,
    max_keep: int,
    timeout_seconds: float,
) -> Path | None:
    """Write a verified SQLite snapshot from a live, concurrently-written database.

    Unlike _create_verified_backup, the caller holds no write lock here: other
    processes (gunicorn, other Celery workers) may be writing to db_path at the
    same time. WAL mode's MVCC is what makes this safe -- the backup's read
    snapshot never blocks, and is never blocked by, a concurrent writer; that
    is what the online backup API is for. This is deliberately a separate,
    self-contained function rather than a refactor of _create_verified_backup:
    that function is hardened for the pre-Django bootstrap context (no
    concurrent writers, caller holds the write lock), and is proven there.
    Duplicating its staging/publish logic here is a smaller risk than
    reshaping it. Every failure is caught and reported as None; a bad day for
    backups must never be a bad day for the worker that calls this.
    """
    try:
        return _write_live_snapshot(
            Path(db_path).resolve(),
            dest_dir,
            max_keep=max_keep,
            timeout_seconds=timeout_seconds,
        )
    except sqlite3.DatabaseError as error:
        _log(f"[db-snapshot] Could not write a database snapshot: {error}")
        busy = getattr(error, "sqlite_errorcode", None) in {
            sqlite3.SQLITE_BUSY,
            sqlite3.SQLITE_LOCKED,
        }
        if not busy:
            # Mirrors check_database_integrity's bootstrap-path reporting: a
            # damaged source database must surface the same recovery-page
            # report here, not just a log line, or a live snapshot failure
            # leaves operators with no record of why backups stopped.
            _report_corruption(db_path, str(error))
        return None
    except (OSError, ValueError) as error:
        _log(f"[db-snapshot] Could not write a database snapshot: {error}")
        return None


def _write_live_snapshot(
    database_path: Path,
    dest_dir: Path,
    *,
    max_keep: int,
    timeout_seconds: float,
) -> Path:
    with suppress(FileExistsError):
        dest_dir.mkdir(mode=0o700, parents=True)
    directory_flags = (
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        dest_descriptor = os.open(dest_dir, directory_flags)
    except OSError as error:
        message = f"destination directory is not a safe real directory: {error}"
        raise OSError(message) from error
    dest_stat = os.fstat(dest_descriptor)
    try:
        if not stat.S_ISDIR(dest_stat.st_mode):
            message = "destination directory is not a safe real directory"
            raise OSError(message)
        os.fchmod(dest_descriptor, 0o700)
        _check_disk_space(dest_dir, database_path)

        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        final_name = f"{database_path.stem}-{timestamp}-{secrets.token_hex(4)}.sqlite3"
        staging_name = f".{database_path.stem}-{secrets.token_hex(16)}.sqlite3.tmp"
        staging_descriptor = os.open(
            staging_name,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=dest_descriptor,
        )
        os.close(staging_descriptor)
        staging_path = Path(f"/proc/self/fd/{dest_descriptor}/{staging_name}")

        source = None
        destination = None
        published = False
        succeeded = False
        try:
            source = sqlite3.connect(
                f"{database_path.as_uri()}?mode=ro",
                uri=True,
                timeout=timeout_seconds,
            )
            destination = sqlite3.connect(staging_path, timeout=timeout_seconds)
            source.backup(destination)
            result = destination.execute("PRAGMA quick_check").fetchone()
            if not result or result[0] != "ok":
                message = "snapshot quick_check did not return 'ok'"
                raise sqlite3.DatabaseError(message)
            destination.close()
            destination = None
            source.close()
            source = None

            staging_check = os.open(
                staging_name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=dest_descriptor,
            )
            try:
                if not stat.S_ISREG(os.fstat(staging_check).st_mode):
                    message = "snapshot staging path is not a regular file"
                    raise OSError(message)
                os.fsync(staging_check)
            finally:
                os.close(staging_check)

            current_stat = dest_dir.stat(follow_symlinks=False)
            if (current_stat.st_dev, current_stat.st_ino) != (
                dest_stat.st_dev,
                dest_stat.st_ino,
            ):
                message = "destination directory changed during snapshot"
                raise OSError(message)
            os.link(
                staging_name,
                final_name,
                src_dir_fd=dest_descriptor,
                dst_dir_fd=dest_descriptor,
                follow_symlinks=False,
            )
            published = True
            os.unlink(staging_name, dir_fd=dest_descriptor)
            os.fsync(dest_descriptor)
            succeeded = True
            # Prune after the new copy is in place, never before -- see the
            # matching comment on the _create_verified_backup call site.
            _prune_recovery_backups(dest_dir, max_keep=max_keep)
            return dest_dir / final_name
        finally:
            if destination is not None:
                destination.close()
            if source is not None:
                source.close()
            with suppress(FileNotFoundError):
                os.unlink(staging_name, dir_fd=dest_descriptor)
            if published and not succeeded:
                with suppress(FileNotFoundError):
                    os.unlink(final_name, dir_fd=dest_descriptor)
    finally:
        os.close(dest_descriptor)


def _quote_identifier(identifier: str) -> str:
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


def _drop_conflict_snapshot(conn: sqlite3.Connection) -> None:
    """Remove the snapshot. The table may not exist if the build failed."""
    with suppress(sqlite3.DatabaseError):
        conn.execute("DROP TABLE floppy_fk_conflicts")


def _snapshot_conflicts(conn: sqlite3.Connection, *, require_row_ids: bool) -> int:
    """Record every conflicting row id in a temporary table.

    The delete path must refuse a row it cannot address, so it sets
    ``require_row_ids``. The description path only reads, so it skips such rows.
    """
    conn.execute(
        "CREATE TEMP TABLE floppy_fk_conflicts ("
        "table_name TEXT NOT NULL, row_id INTEGER NOT NULL, "
        "PRIMARY KEY (table_name, row_id))"
    )
    skipped = 0
    cursor = conn.execute("PRAGMA foreign_key_check")
    while rows := cursor.fetchmany(500):
        if require_row_ids and any(
            row_id is None for _table, row_id, _parent, _key in rows
        ):
            message = (
                "one or more conflicts cannot be quarantined automatically "
                "because the child table has no rowid"
            )
            raise ValueError(message)
        skipped += sum(1 for _t, row_id, _p, _k in rows if row_id is None)
        conn.executemany(
            "INSERT OR IGNORE INTO floppy_fk_conflicts VALUES (?, ?)",
            (
                (table, row_id)
                for table, row_id, _parent, _key in rows
                if row_id is not None
            ),
        )
    # A row we cannot address is still an affected row. Report it rather than
    # let the breakdown quietly add up to less than the total.
    return skipped


def _describe_affected(conn: sqlite3.Connection) -> dict:
    """Name the affected content, grouped and bounded.

    The reference that broke is not the one that carries the title. An affected
    row usually still points at a valid ``app_item``, so the title survives even
    though the parent row is gone. This only reads columns that already exist.
    """
    described: Counter = Counter()
    unidentified = 0
    # The scan below reads every foreign key, so test the one thing that makes
    # it worth doing before paying for it.
    has_item_table = conn.execute(
        "SELECT 1 FROM main.sqlite_schema "
        "WHERE type = 'table' AND name = 'app_item' COLLATE NOCASE",
    ).fetchone()
    if not has_item_table:
        return {}
    try:
        unidentified += _snapshot_conflicts(conn, require_row_ids=False)
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT table_name FROM floppy_fk_conflicts "
                "ORDER BY table_name",
            )
        ]
        for table in tables:
            total = conn.execute(
                "SELECT COUNT(*) FROM floppy_fk_conflicts WHERE table_name = ?",
                [table],
            ).fetchone()[0]
            columns = {
                name.casefold()
                for name, in conn.execute(
                    "SELECT name FROM pragma_table_xinfo(?, 'main')",
                    [table],
                )
            }
            if "item_id" not in columns:
                unidentified += total
                continue
            named = 0
            for title, season, count in conn.execute(
                f"SELECT i.title, i.season_number, COUNT(*) "  # noqa: S608
                f"FROM main.{_quote_identifier(table)} AS child "
                "JOIN main.app_item AS i ON i.id = child.item_id "
                "WHERE child.rowid IN ("
                "SELECT row_id FROM floppy_fk_conflicts WHERE table_name = ?) "
                "GROUP BY i.title, i.season_number",
                [table],
            ):
                described[(title, season)] += count
                named += count
            unidentified += total - named
    finally:
        _drop_conflict_snapshot(conn)

    affected = [
        {"count": count, "season": season, "title": title}
        for (title, season), count in described.most_common(_MAX_AFFECTED_TITLES)
    ]
    remaining = sum(described.values()) - sum(item["count"] for item in affected)
    return {
        "affected": affected,
        "other_titles": len(described) - len(affected),
        "other_titles_count": remaining,
        "unidentified": unidentified,
    }


def _delete_orphaned_rows(conn: sqlite3.Connection) -> int:
    """Delete every child row named by the stable foreign-key snapshot."""
    try:
        return _delete_snapshotted_rows(conn)
    finally:
        _drop_conflict_snapshot(conn)


def _delete_snapshotted_rows(conn: sqlite3.Connection) -> int:
    _snapshot_conflicts(conn, require_row_ids=True)
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT table_name FROM floppy_fk_conflicts ORDER BY table_name"
        )
    ]
    deleted = 0
    for table in tables:
        result = conn.execute(
            f"DELETE FROM main.{_quote_identifier(table)} "  # noqa: S608
            "WHERE rowid IN (SELECT row_id FROM floppy_fk_conflicts "
            "WHERE table_name = ?)",
            [table],
        )
        deleted += result.rowcount
    return deleted


def _incident_from_report(report: dict) -> dict:
    return {
        "can_quarantine": report["can_quarantine"],
        "fingerprint": report["fingerprint"],
        "groups": report["groups"],
        "samples": report["samples"],
        "total_conflicts": report["total_conflicts"],
        "unsafe_reasons": report.get("unsafe_reasons", []),
    }


def _reconcile_report(db_path: str, report: dict) -> None:
    if report.get("status") not in {"accepted", "blocked", "prepared"}:
        return
    incident = _incident_from_report(report)
    resolution = "manual-repair"
    backup_path = None
    deleted_rows = report.get("deleted_rows")
    if report["status"] == "prepared":
        resolution = report.get("resolution") or "quarantine"
        raw_backup_path = report.get("backup_path")
        if not raw_backup_path:
            message = "prepared recovery report has no verified backup"
            raise OSError(message)
        backup_path = Path(raw_backup_path)
        expected_directory = Path(db_path).resolve().parent / "sqlite-recovery"
        try:
            backup_stat = backup_path.lstat()
        except OSError as error:
            message = f"prepared recovery backup is unavailable: {error}"
            raise OSError(message) from error
        if (
            backup_path.parent != expected_directory
            or not stat.S_ISREG(backup_stat.st_mode)
            or backup_path.is_symlink()
        ):
            message = "prepared recovery backup path is unsafe"
            raise OSError(message)
        backup = sqlite3.connect(f"{backup_path.as_uri()}?mode=ro", uri=True)
        try:
            result = backup.execute("PRAGMA quick_check").fetchone()
            if not result or result[0] != "ok":
                message = "prepared recovery backup failed quick_check"
                raise sqlite3.DatabaseError(message)
        finally:
            backup.close()
    _write_incident_report(
        db_path,
        incident,
        status="resolved",
        resolution=resolution,
        backup_path=backup_path,
        deleted_rows=deleted_rows,
    )


def _valid_blocked_token(report: dict | None, incident: dict) -> str | None:
    if (
        report
        and report.get("status") == "blocked"
        and report.get("fingerprint") == incident["fingerprint"]
    ):
        token = report.get("incident_token")
        if isinstance(token, str) and re.fullmatch(r"[0-9a-f]{32}", token):
            return token
    return None


def _check_foreign_keys(conn: sqlite3.Connection, db_path: str) -> None:
    prior_report = _read_incident_report(db_path)
    conn.execute("BEGIN IMMEDIATE")
    incident = _inspect_foreign_keys(conn)
    if not incident["total_conflicts"]:
        conn.commit()
        if prior_report:
            try:
                _reconcile_report(db_path, prior_report)
            except (KeyError, OSError, sqlite3.DatabaseError) as error:
                # Every relationship is already clean and any quarantine delete
                # is already committed, so refusing to start cannot protect the
                # data; it only wedges a healthy container. Leave the report
                # untouched so the next startup retries the reconciliation.
                _log(
                    "[entrypoint] SQLite recovery report could not be finalized; "
                    f"the database is healthy and startup continues: {error}",
                )
        return

    # Naming the affected titles is a convenience. The report is the only way
    # out of the incident, so a failure here must never stop it being written.
    try:
        incident.update(_describe_affected(conn))
    except Exception as error:
        _log(f"[entrypoint] Could not name the affected entries: {error}")
    _print_incident(db_path, incident)
    if (
        prior_report
        and prior_report.get("status") == "accepted"
        and prior_report.get("fingerprint") == incident["fingerprint"]
    ):
        conn.rollback()
        _log(
            f"[entrypoint] Previously accepted {incident['total_conflicts']} "
            "unchanged foreign key conflict(s) without changing rows",
        )
        return

    incident_token = _valid_blocked_token(prior_report, incident)
    if incident_token is None:
        incident_token = secrets.token_hex(16)
    action = _read_decision(db_path, incident, incident_token) or _selected_action(
        incident,
        incident_token,
    )
    try:
        report_path = _write_incident_report(
            db_path,
            incident,
            status="blocked",
            incident_token=incident_token,
        )
    except OSError as error:
        conn.rollback()
        _log(
            f"[entrypoint] Could not publish SQLite incident report: {error}",
        )
        sys.exit(1)

    if action == "accept":
        conn.rollback()
        try:
            _write_incident_report(
                db_path,
                incident,
                status="accepted",
                resolution="accept",
            )
        except OSError as error:
            _log(
                f"[entrypoint] Could not publish SQLite acceptance: {error}",
            )
            sys.exit(1)
        _log(
            f"[entrypoint] Accepted {incident['total_conflicts']} foreign key "
            "conflict(s) without changing rows",
        )
        return

    only_album_artist = {
        group["table"] for group in incident["groups"]
    } == {_ALBUM_ARTIST_TABLE}
    auto_repair_enabled = (
        os.environ.get("FLOPPY_SQLITE_AUTO_REPAIR", "true").strip().lower()
        not in {"0", "false", "no", "off"}
    )
    should_quarantine = (
        action == "quarantine"
        or (auto_repair_enabled and incident["can_quarantine"])
        or only_album_artist
    )
    if should_quarantine:
        if not incident["can_quarantine"]:
            conn.rollback()
            _log(
                "[entrypoint] One or more conflicts cannot be quarantined "
                "automatically; manual repair is required",
            )
            _print_resolution_options(incident, incident_token)
            sys.exit(1)

        backup_path = None
        try:
            backup_path = _create_verified_backup(
                db_path,
                incident["fingerprint"],
            )
            deleted = _delete_orphaned_rows(conn)
            remaining = _inspect_foreign_keys(conn)
            if remaining["total_conflicts"]:
                message = (
                    f"{remaining['total_conflicts']} conflict(s) remain after quarantine"
                )
                raise sqlite3.IntegrityError(message)
            if only_album_artist and action != "quarantine" and not auto_repair_enabled:
                resolution = "automatic-album-artist"
            elif action == "quarantine":
                resolution = "quarantine"
            else:
                resolution = "auto-repair"
            _write_incident_report(
                db_path,
                incident,
                status="prepared",
                resolution=resolution,
                backup_path=backup_path,
                deleted_rows=deleted,
            )
        except (OSError, sqlite3.DatabaseError, ValueError) as error:
            conn.rollback()
            with suppress(OSError):
                _write_incident_report(
                    db_path,
                    incident,
                    status="blocked",
                    resolution="quarantine-failed",
                    backup_path=backup_path,
                    incident_token=incident_token,
                )
            _log(
                f"[entrypoint] SQLite quarantine failed without changing the "
                f"database: {error}",
            )
            _print_resolution_options(incident, incident_token)
            sys.exit(1)

        try:
            conn.commit()
        except sqlite3.DatabaseError as error:
            conn.rollback()
            _log(
                f"[entrypoint] SQLite quarantine commit failed; the prepared "
                f"report and verified backup remain: {error}",
            )
            sys.exit(1)

        try:
            _write_incident_report(
                db_path,
                incident,
                status="resolved",
                resolution=resolution,
                backup_path=backup_path,
                deleted_rows=deleted,
            )
        except OSError as error:
            if (
                isinstance(error, _ResolvedReportPublicationError)
                and error.previous_restored
            ):
                message = (
                    "SQLite quarantine committed, but final report publication "
                    f"failed; the prepared report was restored: {error}"
                )
            else:
                message = (
                    "SQLite quarantine committed, but final report publication "
                    "failed; prior report restoration could not be confirmed. "
                    f"Inspect the report and verified backup before restart: {error}"
                )
            _log(f"[entrypoint] {message}")
            sys.exit(1)
        if only_album_artist and resolution == "automatic-album-artist":
            _log(
                f"[entrypoint] Removed {deleted} orphaned album artist credit "
                f"row(s) after backup to {backup_path}",
            )
        elif resolution == "auto-repair":
            _log(
                f"[entrypoint] Auto-repaired {deleted} orphaned child row(s); "
                f"backup: {backup_path}",
            )
        else:
            _log(
                f"[entrypoint] Quarantined {deleted} orphaned row(s); "
                f"backup: {backup_path}",
            )
        return

    conn.rollback()
    _log(
        f"[entrypoint] Startup is blocked by report {report_path}",
    )
    _print_resolution_options(incident, incident_token)
    _log(_RELATIONSHIP_HINT)
    sys.exit(1)


class IntegrityScanTimeoutError(Exception):
    """The storage scan did not finish inside its deadline."""


def inspect_database(db_path: str, *, timeout_seconds: float | None = None) -> dict:
    """Report SQLite storage and relationship state without changing anything.

    Returns ``{"quick_check": str, "conflicts": dict | None}``. ``conflicts`` is
    the summary from :func:`_inspect_foreign_keys`, or ``None`` when every
    relationship is intact.

    The startup path (:func:`check_database_integrity`) reaches its verdict from
    the same two primitives, but it also repairs rows, quarantines them,
    publishes incident reports and exits the process. Diagnostics need the
    verdict alone. The two callers therefore share the primitives; neither calls
    the other. :func:`_check_foreign_keys` inspects inside ``BEGIN IMMEDIATE``
    because the quarantine delete that follows must operate on the rows that
    inspection found. Taking that write lock here would block a running Floppy,
    so this function does not take it.

    ``timeout_seconds`` bounds the scan. ``sqlite3.connect(timeout=...)`` bounds
    only the wait for a lock, so ``PRAGMA quick_check`` on a large file would run
    past any value given there. A progress handler aborts the running statement
    instead, and raises :class:`IntegrityScanTimeoutError`.

    SQLite may checkpoint the write-ahead log when the last connection closes.
    That moves committed data from the log into the main file. It does not change
    what the database contains.
    """
    conn = None
    deadline = None
    if timeout_seconds is not None:
        deadline = time.monotonic() + timeout_seconds
    try:
        conn = sqlite3.connect(db_path, timeout=_SCAN_BUSY_TIMEOUT_SECONDS)
        if deadline is not None:
            # Returning non-zero from the handler aborts the running statement.
            conn.set_progress_handler(
                lambda: 1 if time.monotonic() > deadline else 0,
                _SCAN_PROGRESS_INSTRUCTIONS,
            )
        try:
            row = conn.execute("PRAGMA quick_check").fetchone()
            status = row[0] if row else None
            incident = _inspect_foreign_keys(conn)
        except sqlite3.OperationalError as error:
            if deadline is not None and time.monotonic() > deadline:
                message = f"storage scan exceeded {timeout_seconds:g}s"
                raise IntegrityScanTimeoutError(message) from error
            raise
    finally:
        if conn is not None:
            conn.set_progress_handler(None, 0)
            conn.close()

    return {
        "quick_check": status,
        "conflicts": incident if incident["total_conflicts"] else None,
    }


def check_database_integrity(db_path: str) -> None:
    """Check SQLite storage and foreign keys before migrations."""
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=30.0)
        result = conn.execute("PRAGMA quick_check").fetchone()
        status = result[0] if result else None
        if status != "ok":
            _log(
                "[entrypoint] Database integrity check failed: "
                f"quick_check returned {status!r}",
            )
            _log(_CORRUPTION_HINT)
            _report_corruption(db_path, f"quick_check returned {status!r}")
            sys.exit(1)

        _check_foreign_keys(conn, db_path)
    except sqlite3.DatabaseError as e:
        _log(f"[entrypoint] Database integrity check failed: {e}")
        busy = getattr(e, "sqlite_errorcode", None) in {
            sqlite3.SQLITE_BUSY,
            sqlite3.SQLITE_LOCKED,
        }
        _log(_BUSY_HINT if busy else _CORRUPTION_HINT)
        if not busy:
            # A damaged file usually raises here rather than returning a
            # quick_check string, so the recovery page needs the same report
            # it gets from the returned-status path.
            _report_corruption(db_path, str(e))
        sys.exit(1)
    finally:
        if conn is not None:
            conn.close()
