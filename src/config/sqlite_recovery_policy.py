"""Keep SQLite recovery choices incident-scoped across startup attempts."""

from __future__ import annotations

import secrets

from config.sqlite_integrity import (
    _incident_from_report,
    _read_incident_report,
    _write_incident_report,
)


def reopen_previous_acceptance(db_path: str) -> bool:
    """Turn a prior keep-rows decision back into a blocked incident.

    Keeping invalid relationship rows can be useful for one startup attempt, but
    it cannot be a permanent bypass. A later migration can require valid foreign
    keys and fail after the integrity check has already returned success.

    Reopen the same incident before the next startup attempt. The caller can then
    disable automatic quarantine for that check, so Floppy does not delete rows
    only because an earlier attempt failed to start.
    """
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
        resolution="accept-expired",
        incident_token=secrets.token_hex(16),
    )
    return True
