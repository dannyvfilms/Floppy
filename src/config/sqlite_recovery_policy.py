"""Apply incident-scoped SQLite recovery without discarding recoverable user data."""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import stat
import time
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from config.sqlite_integrity import (
    _create_verified_backup,
    _decision_path,
    _describe_affected,
    _incident_from_report,
    _incident_report_path,
    _inspect_foreign_keys,
    _log,
    _print_incident,
    _publish_report,
    _read_incident_report,
    _reconcile_report,
    _report_corruption,
    _valid_blocked_token,
    _write_incident_report,
    read_startup_status,
    recent_verification,
    record_verified_database,
    warm_database_cache,
    write_startup_status,
)
from config.sqlite_repair import apply_repair_plan, build_repair_plan

if TYPE_CHECKING:
    from pathlib import Path

_ACTION_ENV = "FLOPPY_SQLITE_CONFLICT_ACTION"
_AUTO_REPAIR_ENV = "FLOPPY_SQLITE_AUTO_REPAIR"
_PROGRESS_INSTRUCTIONS = 10_000
_PROGRESS_REPORT_INTERVAL_SECONDS = 10.0

StatusEmitter = Callable[..., None]


def _status_emitter(db_path: str) -> StatusEmitter:
    """Build a closure that reports startup-scan progress to the status sidecar.

    Every call carries the same start time and process, so ``elapsed_seconds``
    is a plain monotonic delta rather than something reconstructed from disk.
    """
    started_monotonic = time.monotonic()
    started_at = datetime.now(UTC).isoformat()
    version = os.environ.get("VERSION")
    commit_sha = os.environ.get("COMMIT_SHA")
    current_phase = None
    phase_started_at = started_at
    last_progress_at = None

    def emit(
        status: str,
        phase: str,
        *,
        progress_callbacks: int | None = None,
        progress_at: str | None = None,
        read_bytes: int | None = None,
        error_class: str | None = None,
        error_message: str | None = None,
    ) -> None:
        nonlocal current_phase, last_progress_at, phase_started_at
        if phase != current_phase:
            current_phase = phase
            phase_started_at = datetime.now(UTC).isoformat()
            last_progress_at = None
        if progress_at is not None:
            last_progress_at = progress_at
        _log(f"[integrity] phase={phase} status={status}")
        write_startup_status(
            db_path,
            status=status,
            phase=phase,
            started_at=started_at,
            elapsed_seconds=time.monotonic() - started_monotonic,
            read_bytes=read_bytes,
            progress_callbacks=progress_callbacks,
            phase_started_at=phase_started_at,
            last_progress_at=last_progress_at,
            version=version,
            commit_sha=commit_sha,
            error_class=error_class,
            error_message=error_message,
        )

    return emit


def _run_with_progress(
    conn: sqlite3.Connection,
    operation: Callable[[], object],
    *,
    phase: str,
    emit: StatusEmitter,
) -> tuple[object, int, str | None]:
    """Run one SQLite operation and periodically publish progress counts."""
    progress_callbacks = 0
    last_report = time.monotonic()
    last_progress_monotonic = None
    last_progress_at = None

    def progress() -> int:
        nonlocal last_progress_at, last_progress_monotonic, last_report, progress_callbacks
        progress_callbacks += 1
        now = time.monotonic()
        last_progress_monotonic = now
        if now - last_report >= _PROGRESS_REPORT_INTERVAL_SECONDS:
            last_progress_at = datetime.now(UTC).isoformat()
            _log(
                f"[integrity] phase={phase} status=running "
                f"progress_callbacks={progress_callbacks}",
            )
            emit(
                "running",
                phase,
                progress_callbacks=progress_callbacks,
                progress_at=last_progress_at,
            )
            last_report = now
        return 0

    conn.set_progress_handler(progress, _PROGRESS_INSTRUCTIONS)
    try:
        result = operation()
    finally:
        conn.set_progress_handler(None, 0)
        if last_progress_monotonic is not None and last_progress_at is None:
            last_progress_at = datetime.now(UTC).isoformat()
    return result, progress_callbacks, last_progress_at


class UnsafeRecoverySchemaError(sqlite3.IntegrityError):
    """Raised when the current relationship shape is not safe to repair."""


class RecoveryDidNotConvergeError(sqlite3.IntegrityError):
    """Raised when required repair leaves one or more foreign-key conflicts."""

    def __init__(self, conflict_count: int):
        """Record how many relationship conflicts remained after repair."""
        message = f"{conflict_count} relationship conflict(s) remain after repair"
        super().__init__(message)


def _auto_repair_enabled() -> bool:
    return os.environ.get(_AUTO_REPAIR_ENV, "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _publish_policy_report(
    db_path: str,
    report: dict,
    plan: dict,
    *,
    status: str = "blocked",
    resolution: str | None = None,
    backup_path: Path | None = None,
    repair_result: dict | None = None,
    prior_safe_repair: dict | None = None,
) -> None:
    """Publish only recovery choices that this policy can complete."""
    payload = dict(report)
    token = payload.get("incident_token")
    actions = {"halt": "halt"}
    if status == "blocked" and token and plan.get("can_repair"):
        actions["quarantine"] = f"quarantine:{token}"
    payload.update(
        {
            "actions": actions,
            "backup_path": str(backup_path) if backup_path else payload.get("backup_path"),
            "can_quarantine": bool(plan.get("can_repair")),
            "incident_token": token if status == "blocked" else None,
            "repair_plan": plan,
            "repair_result": repair_result,
            "resolution": resolution,
            "status": status,
        }
    )
    if prior_safe_repair:
        payload["safe_repair"] = prior_safe_repair
    contents = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    _publish_report(_incident_report_path(db_path), contents)


def reopen_previous_acceptance(db_path: str) -> bool:
    """Turn a legacy keep-rows decision back into a blocked incident."""
    report = _read_incident_report(db_path)
    if not report or report.get("status") != "accepted":
        return False

    incident = _incident_from_report(report)
    incident.update(
        {
            "affected": report.get("affected", []),
            "other_titles": report.get("affected_other_titles", 0),
            "other_titles_count": report.get("affected_other_titles_count", 0),
            "unidentified": report.get("affected_unidentified", 0),
        },
    )
    _write_incident_report(
        db_path,
        incident,
        status="blocked",
        resolution="accept-retired",
        incident_token=secrets.token_hex(16),
    )
    return True


def _current_incident(conn: sqlite3.Connection, report: dict) -> dict:
    incident = _inspect_foreign_keys(conn)
    if incident["fingerprint"] != report.get("fingerprint"):
        msg = "database relationships changed after the recovery page was rendered"
        raise sqlite3.IntegrityError(msg)
    return incident


def _require_repairable(plan: dict) -> None:
    if not plan.get("can_repair"):
        raise UnsafeRecoverySchemaError


def _require_converged(remaining: dict) -> None:
    conflict_count = int(remaining.get("total_conflicts", 0))
    if conflict_count:
        raise RecoveryDidNotConvergeError(conflict_count)


def _describe_incident(conn: sqlite3.Connection, incident: dict) -> None:
    """Add bounded human context without making it a recovery prerequisite."""
    try:
        incident.update(_describe_affected(conn))
    except Exception as error:
        # A damaged schema still needs a bounded incident report. Naming titles
        # is useful context, but it is not allowed to suppress the recovery path.
        _log(f"[entrypoint] Could not name the affected entries: {error}")


def _scan_and_publish_block(
    db_path: str,
    emit: StatusEmitter,
) -> dict | None:
    """Scan storage and publish the policy's blocked relationship report."""
    prior_report = _read_incident_report(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        emit("running", "quick_check", progress_callbacks=0)
        phase_started = time.monotonic()
        result, quick_progress, quick_last_progress = _run_with_progress(
            conn,
            lambda: conn.execute("PRAGMA quick_check").fetchone(),
            phase="quick_check",
            emit=emit,
        )
        _log(f"[integrity] phase=quick_check seconds={time.monotonic() - phase_started:.1f}")
        status = result[0] if result else None
        if status != "ok":
            _log(
                "[entrypoint] Database integrity check failed: "
                f"quick_check returned {status!r}",
            )
            emit(
                "failed",
                "quick_check",
                progress_callbacks=quick_progress,
                progress_at=quick_last_progress,
                error_class="corruption",
                error_message=f"quick_check returned {status!r}",
            )
            _report_corruption(db_path, f"quick_check returned {status!r}")
            raise SystemExit(1)

        emit(
            "running",
            "foreign_key_check",
            progress_callbacks=0,
        )
        phase_started = time.monotonic()
        incident, foreign_key_progress, foreign_key_last_progress = _run_with_progress(
            conn,
            lambda: _inspect_foreign_keys(conn),
            phase="foreign_key_check",
            emit=emit,
        )
        _log(
            "[integrity] phase=foreign_key_check "
            f"seconds={time.monotonic() - phase_started:.1f}",
        )
        if not incident["total_conflicts"]:
            if prior_report:
                try:
                    _reconcile_report(db_path, prior_report)
                except (KeyError, OSError, sqlite3.DatabaseError) as error:
                    _log(
                        "[entrypoint] SQLite recovery report could not be finalized; "
                        f"the database is healthy and startup continues: {error}",
                    )
            emit(
                "ok",
                "foreign_key_check",
                progress_callbacks=foreign_key_progress,
                progress_at=foreign_key_last_progress,
            )
            return None

        emit("running", "describe_incident")
        _describe_incident(conn, incident)
        _print_incident(db_path, incident)
        incident_token = _valid_blocked_token(prior_report, incident)
        if incident_token is None:
            incident_token = secrets.token_hex(16)
        emit("running", "publish_report")
        try:
            report_path = _write_incident_report(
                db_path,
                incident,
                status="blocked",
                incident_token=incident_token,
            )
        except OSError as error:
            emit(
                "failed",
                "publish_report",
                error_class=type(error).__name__,
                error_message=str(error),
            )
            _log(f"[entrypoint] Could not publish SQLite incident report: {error}")
            raise SystemExit(1) from error
        _log(f"[entrypoint] Startup is blocked by report {report_path}")
        emit("blocked", "publish_report")
        return _read_incident_report(db_path)
    except sqlite3.DatabaseError as error:
        emit(
            "failed",
            "foreign_key_check",
            error_class=type(error).__name__,
            error_message=str(error),
        )
        _log(f"[entrypoint] Database integrity check failed: {error}")
        raise SystemExit(1) from error
    finally:
        conn.close()


def _read_policy_decision(db_path: str, report: dict) -> str | None:
    """Consume one exact fingerprint-and-token decision from the recovery page."""
    decision_path = _decision_path(db_path)
    try:
        descriptor = os.open(
            decision_path,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
        )
    except OSError:
        return None

    decision = None
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
        with suppress(OSError):
            decision_path.unlink()

    if not isinstance(decision, dict):
        return None
    if decision.get("action") not in {"accept", "quarantine"}:
        return None
    if decision.get("fingerprint") != report.get("fingerprint"):
        _log("[entrypoint] Recovery choice belongs to a different incident; using halt")
        return None
    expected = report.get("incident_token")
    supplied = decision.get("token")
    if not (
        isinstance(expected, str)
        and expected
        and isinstance(supplied, str)
        and secrets.compare_digest(supplied, expected)
    ):
        _log("[entrypoint] Recovery choice does not carry the current code; using halt")
        return None
    return str(decision["action"])


def _selected_policy_action(report: dict) -> str:
    """Read an incident-scoped headless action from the environment."""
    configured = os.environ.get(_ACTION_ENV, "halt").strip()
    if configured in {"", "halt"}:
        return "halt"

    action, separator, supplied = configured.partition(":")
    expected = report.get("incident_token")
    if action == "accept":
        return "accept"
    if action != "quarantine" or not separator:
        _log(f"[entrypoint] Invalid {_ACTION_ENV}; using halt")
        return "halt"
    if not (
        isinstance(expected, str)
        and expected
        and supplied
        and secrets.compare_digest(supplied, expected)
    ):
        _log(f"[entrypoint] {_ACTION_ENV} does not carry the current code; using halt")
        return "halt"
    return "quarantine"


def _apply_plan(
    db_path: str,
    report: dict,
    *,
    include_required: bool,
) -> tuple[dict, dict, dict, Path, dict]:
    """Apply one validated plan under a write lock and verified backup."""
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute("BEGIN IMMEDIATE")
        incident = _current_incident(conn, report)
        plan = build_repair_plan(conn, incident)
        _require_repairable(plan)
        backup_path = _create_verified_backup(db_path, incident["fingerprint"])
        result = apply_repair_plan(
            conn,
            plan,
            include_required=include_required,
        )
        remaining = _inspect_foreign_keys(conn)
        if include_required:
            _require_converged(remaining)
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()
        return incident, plan, result, backup_path, remaining
    finally:
        conn.close()


def _repair_summary(result: dict, backup_path: Path) -> dict:
    return {
        "backup_path": str(backup_path),
        "references_cleared": int(result.get("references_cleared", 0)),
        "relationship_rows_removed": int(result.get("relationship_rows_removed", 0)),
        "required_rows_removed": int(result.get("required_rows_removed", 0)),
    }


def _handle_operator_decision(db_path: str, report: dict) -> bool:
    """Apply a one-use decision if one exists."""
    decision_path = _decision_path(db_path)
    configured = os.environ.get(_ACTION_ENV, "halt").strip()
    if not decision_path.exists() and configured in {"", "halt"}:
        return False

    action = (
        _read_policy_decision(db_path, report)
        if decision_path.exists()
        else _selected_policy_action(report)
    )
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        incident = _current_incident(conn, report)
        plan = build_repair_plan(conn, incident)
    finally:
        conn.close()

    if action == "accept":
        _publish_policy_report(
            db_path,
            report,
            plan,
            resolution="accept-retired",
        )
        _log(
            "[entrypoint] Keeping invalid relationships cannot make migrations safe. "
            "No rows were changed; choose repair or restore a backup.",
        )
        raise SystemExit(1)
    if action != "quarantine":
        return False

    _incident, plan, result, backup_path, _remaining = _apply_plan(
        db_path,
        report,
        include_required=True,
    )
    summary = _repair_summary(result, backup_path)
    _publish_policy_report(
        db_path,
        report,
        plan,
        status="resolved",
        resolution="operator-repair",
        backup_path=backup_path,
        repair_result=summary,
    )
    _log(
        "[entrypoint] Repaired SQLite relationships after a verified backup: "
        f"cleared {summary['references_cleared']} optional reference(s), removed "
        f"{summary['relationship_rows_removed']} derived relationship row(s), and "
        f"removed {summary['required_rows_removed']} row(s) whose required parent "
        f"was missing. Backup: {backup_path}",
    )
    return True


def _annotate_blocked_report(
    db_path: str,
    report: dict,
    *,
    prior_safe_repair: dict | None = None,
) -> dict:
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        plan = build_repair_plan(conn, report)
    finally:
        conn.close()
    _publish_policy_report(
        db_path,
        report,
        plan,
        resolution="repair-required",
        prior_safe_repair=prior_safe_repair,
    )
    return plan


def _log_blocked_recovery_options(report: dict, plan: dict) -> None:
    """Print the current repair approval code for a final blocked incident."""
    token = report.get("incident_token")
    if not plan.get("can_repair") or not isinstance(token, str) or not token:
        return
    _log(f"[entrypoint] SQLite recovery approval code: {token}")
    _log(
        "[entrypoint] To approve relationship repair, set "
        f"{_ACTION_ENV}=quarantine:{token} and restart Floppy.",
    )


def _skip_recently_verified(
    db_path: str,
    previous_status: dict | None,
    emit: StatusEmitter,
) -> bool:
    """Skip the full scan when a recent full check still vouches for the file.

    The database is still opened and its schema read, which replays a leftover
    WAL and fails fast on a file SQLite cannot open. Any error here falls
    through to the full scan, which owns the reporting for damaged files.
    """
    record, reason = recent_verification(db_path, previous_status)
    if record is None:
        _log(f"[integrity] Running the full storage check: {reason}")
        return False
    emit("running", "open_check")
    try:
        conn = sqlite3.connect(db_path, timeout=30.0)
        try:
            conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        finally:
            conn.close()
    except sqlite3.DatabaseError as error:
        _log(f"[integrity] Running the full storage check: open check failed: {error}")
        return False
    _log(f"[integrity] Skipped the full storage check: {reason}")
    emit("ok", "open_check")
    return True


def _warm_cache(db_path: str, emit: StatusEmitter) -> None:
    """Read the file sequentially so the scan below runs from the page cache."""
    emit("running", "warm_cache", read_bytes=0)

    def progress(read_bytes: int) -> None:
        emit(
            "running",
            "warm_cache",
            read_bytes=read_bytes,
            progress_at=datetime.now(UTC).isoformat(),
        )

    read_bytes, seconds = warm_database_cache(db_path, on_progress=progress)
    rate = read_bytes / 1_048_576 / seconds if seconds > 0 else 0.0
    _log(
        f"[integrity] phase=warm_cache read={read_bytes / 1_048_576:.0f}MB "
        f"seconds={seconds:.1f} rate={rate:.0f}MB/s",
    )


def check_database_for_startup(db_path: str) -> None:
    """Repair safe relationship damage or block before migrations."""
    previous_status = read_startup_status(db_path)
    emit = _status_emitter(db_path)
    emit("running", "connect")
    reopened = reopen_previous_acceptance(db_path)
    if reopened:
        _log(
            "[entrypoint] The old keep-rows choice cannot make schema migrations "
            "safe. Floppy reopened recovery without changing the database.",
        )

    report = _read_incident_report(db_path)
    if (
        report
        and report.get("status") == "blocked"
        and _handle_operator_decision(db_path, report)
    ):
        emit("ok", "repair")
        return

    if _skip_recently_verified(db_path, previous_status, emit):
        return
    _warm_cache(db_path, emit)
    report = _scan_and_publish_block(db_path, emit)
    if report is None:
        record_verified_database(db_path, source="startup")
        return

    plan = _annotate_blocked_report(db_path, report)
    if not (
        _auto_repair_enabled()
        and plan.get("can_repair")
        and int(plan.get("safe_relationships", 0)) > 0
    ):
        _log_blocked_recovery_options(report, plan)
        raise SystemExit(1)

    emit("running", "repair")
    try:
        _incident, applied_plan, result, backup_path, remaining = _apply_plan(
            db_path,
            report,
            include_required=False,
        )
    except (OSError, sqlite3.DatabaseError, ValueError) as error:
        emit(
            "failed",
            "repair",
            error_class=type(error).__name__,
            error_message=str(error),
        )
        _log(
            "[entrypoint] Safe SQLite relationship repair failed without changing "
            f"the live database: {error}",
        )
        raise SystemExit(1) from error

    safe_summary = _repair_summary(result, backup_path)
    _log(
        "[entrypoint] Preserved user data while repairing safe SQLite relationships: "
        f"cleared {safe_summary['references_cleared']} optional reference(s) and "
        f"removed {safe_summary['relationship_rows_removed']} derived relationship "
        f"row(s). Backup: {backup_path}",
    )
    if not remaining["total_conflicts"]:
        _publish_policy_report(
            db_path,
            report,
            applied_plan,
            status="resolved",
            resolution="automatic-safe-repair",
            backup_path=backup_path,
            repair_result=safe_summary,
        )
        emit("ok", "repair")
        return

    # The safe subset changed the incident fingerprint. Re-scan through this
    # policy so the next approval code is tied to the exact remaining rows.
    refreshed = _scan_and_publish_block(db_path, emit)
    if refreshed is None:
        return
    refreshed_plan = _annotate_blocked_report(
        db_path,
        refreshed,
        prior_safe_repair=safe_summary,
    )
    _log_blocked_recovery_options(refreshed, refreshed_plan)
    raise SystemExit(1)
