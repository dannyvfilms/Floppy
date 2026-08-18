"""SQLite runtime safety policy.

Keep version and PRAGMA validation in one place so every runtime uses the same
rules, including Docker, source installs, and future packaged distributions.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, MutableMapping, Sequence
from typing import Any

ALLOWED_JOURNAL_MODES = frozenset({"DELETE", "TRUNCATE", "PERSIST", "WAL"})
ALLOWED_SYNCHRONOUS_MODES = frozenset(
    {"NORMAL", "FULL", "EXTRA", "1", "2", "3"},
)


def _version_triplet(version_info: Sequence[int]) -> tuple[int, int, int]:
    """Return a comparable SQLite major/minor/patch tuple."""
    if len(version_info) < 3:
        msg = "SQLite version must include major, minor, and patch values."
        raise ValueError(msg)
    return tuple(int(part) for part in version_info[:3])


def sqlite_wal_reset_fix_present(version_info: Sequence[int]) -> bool:
    """Return whether this SQLite release contains the WAL-reset fix.

    The fix is in SQLite 3.51.3 and later. SQLite also backported it to the
    3.44 and 3.50 release lines as 3.44.6 and 3.50.7 respectively. The ranges
    are intentionally explicit because 3.45-3.49 and 3.51.0-3.51.2 remain
    affected despite sorting above a fixed backport version.
    """
    version = _version_triplet(version_info)
    return (
        version >= (3, 51, 3)
        or (3, 50, 7) <= version < (3, 51, 0)
        or (3, 44, 6) <= version < (3, 45, 0)
    )


def normalize_sqlite_journal_mode(value: str) -> str:
    """Validate and normalize a crash-recoverable SQLite journal mode."""
    normalized = str(value).strip().upper()
    if normalized not in ALLOWED_JOURNAL_MODES:
        allowed = ", ".join(sorted(ALLOWED_JOURNAL_MODES))
        msg = f"Unsupported SQLITE_JOURNAL_MODE {value!r}. Allowed values: {allowed}."
        raise ValueError(msg)
    return normalized


def normalize_sqlite_synchronous(value: str) -> str:
    """Validate and normalize a crash-recoverable synchronous mode."""
    normalized = str(value).strip().upper()
    if normalized not in ALLOWED_SYNCHRONOUS_MODES:
        allowed = ", ".join(sorted(ALLOWED_SYNCHRONOUS_MODES))
        msg = f"Unsupported SQLITE_SYNCHRONOUS {value!r}. Allowed values: {allowed}."
        raise ValueError(msg)
    return normalized


def resolve_sqlite_journal_mode(
    requested_mode: str,
    version_info: Sequence[int] | None = None,
) -> tuple[str, bool]:
    """Return the effective journal mode and whether a safety fallback applied."""
    requested = normalize_sqlite_journal_mode(requested_mode)
    runtime_version = sqlite3.sqlite_version_info if version_info is None else version_info

    if requested == "WAL" and not sqlite_wal_reset_fix_present(runtime_version):
        return "DELETE", True

    return requested, False


def prepare_sqlite_environment(
    config_reader: Callable[..., Any],
    environment: MutableMapping[str, str],
    version_info: Sequence[int] | None = None,
) -> tuple[str, str, str, bool] | None:
    """Validate SQLite settings and publish the safe effective values.

    This runs before Django settings are loaded. Environment values override a
    local .env file in python-decouple, so the effective values are then read by
    the existing settings code without a second SQLite policy path.
    """
    if config_reader("DB_HOST", default=None):
        return None

    requested = normalize_sqlite_journal_mode(
        config_reader("SQLITE_JOURNAL_MODE", default="WAL"),
    )
    synchronous = normalize_sqlite_synchronous(
        config_reader("SQLITE_SYNCHRONOUS", default="NORMAL"),
    )
    effective, fallback_applied = resolve_sqlite_journal_mode(
        requested,
        version_info,
    )

    # NORMAL is the preferred WAL balance, but SQLite documents a small
    # corruption risk with NORMAL + rollback journal after a power failure on
    # older filesystems. FULL keeps the compatibility fallback crash-safe.
    if fallback_applied and synchronous in {"NORMAL", "1"}:
        synchronous = "FULL"

    environment["SQLITE_JOURNAL_MODE"] = effective
    environment["SQLITE_SYNCHRONOUS"] = synchronous
    return requested, effective, synchronous, fallback_applied
