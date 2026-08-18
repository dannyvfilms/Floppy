"""Apply incident-scoped SQLite recovery without discarding recoverable user data."""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
from pathlib import Path

from config.sqlite_integrity import (
    _create_verified_backup,
    _incident_from_report,
    _incident_report_path,
    _inspect_foreign_keys,
    _log,
    _publish_report,
    _read_decision,
    _read_incident_report,
    _selected_action,
    _write_incident_report,
    check_database_integrity,
)
from config.sqlite_repair import apply_repair_plan, build_repair_plan

_SAFE_CHECK_ENV = {
    "FLOPPY_SQLITE_AUTO_REPAIR": "false",
    "FLOPPY_SQLITE_CONFLICT_ACTION": "halt",
}


class UnsafeRecoverySchemaError(sqlite3.IntegrityError):
    """Raised when the current relationship shape is not safe to repair."""


class RecoveryDidNotConvergeError(sqlite3.IntegrityError):
    """Raised when required repair leaves one or more foreign-key conflicts."""

    def __init__(self, conflict_count: int):
        message = f"{conflict_count} relationship conflict(s) remain after repair"
        super().__init__(message)


def _auto_repair_enabled() -> bool:
    return os.environ.get("FLOPPY_SQLITE_AUTO_REPAIR", "true").strip().lower() not in {
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


def _run_checker_without_legacy_repair(db_path: str) -> None:
    """Run the existing scanner while disabling its generalized delete path."""
    previous = {name: os.environ.get(name) for name in _SAFE_CHECK_ENV}
    try:
        os.environ.update(_SAFE_CHECK_ENV)
        check_database_integrity(db_path)
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


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
    decision_path = Path(f"{db_path}.integrity.decision")
    configured = os.environ.get("FLOPPY_SQLITE_CONFLICT_ACTION", "halt").strip()
    if not decision_path.exists() and configured in {"", "halt"}:
        return False

    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute("BEGIN IMMEDIATE")
        incident = _current_incident(conn, report)
        token = report.get("incident_token") or ""
        action = _read_decision(db_path, incident, token) if decision_path.exists() else None
        if action is None:
            action = _selected_action(incident, token)
        plan = build_repair_plan(conn, incident)
        conn.rollback()
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


def _run_and_capture_block(db_path: str) -> dict | None:
    try:
        _run_checker_without_legacy_repair(db_path)
    except SystemExit as error:
        if error.code != 1:
            raise
        report = _read_incident_report(db_path)
        if not report or report.get("status") != "blocked":
            raise
        return report
    return None


def check_database_for_startup(db_path: str) -> None:
    """Repair safe relationship damage or block before migrations."""
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
        return

    report = _run_and_capture_block(db_path)
    if report is None:
        return

    plan = _annotate_blocked_report(db_path, report)
    if not (
        _auto_repair_enabled()
        and plan.get("can_repair")
        and int(plan.get("safe_relationships", 0)) > 0
    ):
        raise SystemExit(1)

    try:
        _incident, applied_plan, result, backup_path, remaining = _apply_plan(
            db_path,
            report,
            include_required=False,
        )
    except (OSError, sqlite3.DatabaseError, ValueError) as error:
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
        return

    # The safe subset changed the incident fingerprint. Re-scan through the
    # existing reporting path so the next approval token is tied to the exact
    # remaining rows rather than the pre-repair incident.
    refreshed = _run_and_capture_block(db_path)
    if refreshed is None:
        return
    _annotate_blocked_report(
        db_path,
        refreshed,
        prior_safe_repair=safe_summary,
    )
    raise SystemExit(1)
