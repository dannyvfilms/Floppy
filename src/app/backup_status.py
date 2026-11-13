"""Last successful and failed backup runs, kept apart from task dispatch (#1627).

A Celery beat dispatch, or a healthy web process, says nothing about whether a
backup was actually published. Each backup kind records its own outcome in a
small JSON file next to the backups it describes, so the record survives
restarts and needs no model or migration. One file per kind keeps concurrent
writers (several users' CSV exports, the snapshot task) from clobbering each
other.
"""

import json
import logging
import os
import shutil
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

SNAPSHOT = "snapshot"
CSV_EXPORT = "csv_export"
_ERROR_MAX_CHARS = 300


def _status_path(kind: str) -> Path:
    return Path(settings.BACKUP_DIR) / f".status-{kind}.json"


def _load(kind: str) -> dict:
    try:
        data = json.loads(_status_path(kind).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _store(kind: str, data: dict) -> None:
    """Atomically replace the record; never let bookkeeping fail a backup."""
    path = _status_path(kind)
    tmp_name = None
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".status-tmp-")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        Path(tmp_name).replace(path)
    except OSError:
        logger.warning("Could not record %s backup status", kind, exc_info=True)
        if tmp_name:
            with suppress(OSError):
                Path(tmp_name).unlink()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def record_success(kind: str, name: str) -> None:
    """Record a published backup; keeps the previous failure for context."""
    data = _load(kind)
    data.update(last_success_at=_now(), last_success_name=name)
    _store(kind, data)


def record_failure(kind: str, error: object) -> None:
    """Record a failed run without erasing the last success."""
    data = _load(kind)
    data.update(last_failure_at=_now(), last_failure=str(error)[:_ERROR_MAX_CHARS])
    _store(kind, data)


def _age_seconds(iso: str | None):
    if not iso:
        return None
    try:
        then = datetime.fromisoformat(iso)
    except ValueError:
        return None
    return max(0, int((datetime.now(UTC) - then).total_seconds()))


def destination_check(directory: Path) -> dict:
    """Writability and free space of a backup directory.

    Says only whether a write could plausibly succeed now; it is not evidence
    that any backup is fresh.
    """
    try:
        free = shutil.disk_usage(directory).free
    except OSError:
        free = None
    return {
        "writable": directory.is_dir() and os.access(directory, os.W_OK | os.X_OK),
        "free_bytes": free,
    }


def freshness(kind: str) -> dict:
    """Last success, last failure and their ages, independent of dispatch.

    A failure newer than the last success is flagged so the caller can show
    the current state rather than only the history.
    """
    data = _load(kind)
    success_at = data.get("last_success_at")
    failure_at = data.get("last_failure_at")
    return {
        "last_success_at": success_at,
        "last_success_name": data.get("last_success_name"),
        "last_success_age_seconds": _age_seconds(success_at),
        "last_failure_at": failure_at,
        "last_failure": data.get("last_failure"),
        "last_failure_age_seconds": _age_seconds(failure_at),
        "failing": bool(failure_at and (not success_at or failure_at > success_at)),
    }
