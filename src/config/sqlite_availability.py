"""Bounded startup admission and offline migration preparation for SQLite.

Verification age is a maintenance concern. An unresolved finding is an
availability concern. Only an unchanged, fully checked recovery snapshot can
authorize pending migrations; online verification never grants that permit.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import sqlite3
import stat
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from django.apps import apps

from config import sqlite_integrity as integrity
from config import sqlite_sliced_check

_PROGRESS_REPORT_SECONDS = 10


class StartupBlockedError(RuntimeError):
    """Startup needs an explicit maintenance operation."""


class MigrationPermitRequiredError(StartupBlockedError):
    """Only a recovery snapshot is missing; the entrypoint can take one."""


def _signature(path: Path) -> list[int] | None:
    try:
        info = path.stat()
    except FileNotFoundError:
        return None
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]


def _state(db_path: str) -> dict:
    database = Path(db_path).resolve()
    wal = _signature(Path(f"{database}-wal"))
    # SQLite can create an empty WAL while a read-only backup opens a WAL-mode
    # database. It contains no frames; absent and zero bytes are equivalent.
    if wal and wal[2] == 0:
        wal = None
    return {
        "database": str(database),
        "main": _signature(database),
        "wal": wal,
        "journal": _signature(Path(f"{database}-journal")),
    }


def _permit_path(db_path: str) -> Path:
    return Path(f"{Path(db_path).resolve()}.migration-ready.json")


def _require_no_incident(db_path: str) -> None:
    report = integrity._read_incident_report(db_path)
    if integrity._incident_report_path(db_path).exists() and (
        not report or report.get("status") != "resolved"
    ):
        msg = (
            "Unresolved or unreadable SQLite recovery report. Inspect the recovery "
            "page/report. Steps: " + integrity.RECOVERY_DOC_URL
        )
        raise StartupBlockedError(msg)
    previous = integrity.read_startup_status(db_path)
    if previous and previous.get("status") in {"failed", "blocked"}:
        msg = (
            "The last SQLite startup check did not finish; a timeout or crash alone "
            "does not mean corruption. With Floppy stopped, run "
            f"`{integrity.PREPARE_COMMAND}` in /floppy. Steps: "
            + integrity.RECOVERY_DOC_URL
        )
        raise StartupBlockedError(msg)


def startup_gate(db_path: str, connection) -> bool:
    """Return whether migrations are needed; never scan application tables.

    The outer entrypoint provides a 30-second process deadline, including
    Django imports and filesystem I/O. SQLite's progress deadline bounds SQL
    work, including migration-history reads. A read-only connection includes
    active WAL data without checkpointing or taking a writer transaction.
    """
    from django.db.migrations.executor import MigrationExecutor

    _require_no_incident(db_path)
    database = Path(db_path).resolve()
    record = integrity._read_sidecar(integrity._verified_path(db_path), db_path)
    if record and (record.get("device"), record.get("inode")) != tuple(
        _signature(database)[:2]
    ):
        msg = "Database was replaced since verification; prepare it offline before startup."
        raise StartupBlockedError(msg)
    deadline = time.monotonic() + 5
    with closing(
        sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True, timeout=2)
    ) as db:
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        db.execute("SELECT name FROM sqlite_schema LIMIT 1").fetchone()
        # Use Django's migration graph, but not its connection initialization
        # (journal-mode PRAGMAs can need writer locks). This wrapper is private
        # to this short-lived command and is never used for writes.
        connection.connection = db

        def bounded_statement(execute, sql, params, many, context):
            nonlocal deadline
            deadline = time.monotonic() + 5
            return execute(sql, params, many, context)

        try:
            # Python migration-module imports can be slow on bind mounts.
            # Bound each SQL statement, not time spent importing the graph;
            # the outer process deadline still bounds the entire admission.
            with connection.execute_wrapper(bounded_statement):
                executor = MigrationExecutor(connection)
                executor.loader.check_consistent_history(connection)
                targets = executor.loader.graph.leaf_nodes()
                plan = executor.migration_plan(targets)
        finally:
            connection.connection = None
    if not plan:
        with closing(
            sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True, timeout=2)
        ) as db:
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            for model in apps.get_models(include_auto_created=True):
                meta = model._meta
                if not meta.managed or meta.proxy or meta.swapped:
                    continue
                deadline = time.monotonic() + 5
                columns = {
                    row[1]
                    for row in db.execute(
                        "SELECT * FROM pragma_table_info(?)", [meta.db_table]
                    )
                }
                if (
                    not {field.column for field in meta.local_concrete_fields}
                    <= columns
                ):
                    msg = f"SQLite schema disagrees with migration history at {meta.db_table}; inspect/restore offline."
                    raise StartupBlockedError(msg)
        integrity._log(
            "[sqlite-startup] schema current; full verification runs after startup"
        )
        return False

    permit = integrity._read_sidecar(_permit_path(db_path), db_path)
    expected_plan = [
        [migration.app_label, migration.name, backwards]
        for migration, backwards in plan
    ]
    if (
        not permit
        or permit.get("state") != _state(db_path)
        or permit.get("plan") != expected_plan
        or permit.get("commit_sha") != os.environ.get("COMMIT_SHA")
    ):
        msg = (
            "Pending migrations require an unchanged verified recovery snapshot. "
            "Stop all database writers, then run "
            f"`{integrity.PREPARE_COMMAND}` in /floppy (up to one hour by default), "
            "then restart. Steps: " + integrity.RECOVERY_DOC_URL
        )
        raise MigrationPermitRequiredError(msg)
    if not isinstance(permit.get("backup"), str) or not permit["backup"]:
        msg = "Migration recovery snapshot record is malformed; prepare again."
        raise StartupBlockedError(msg)
    backup = Path(permit["backup"])
    if _signature(backup) != permit.get("backup_signature") or not backup.is_file():
        msg = "Migration recovery snapshot is missing or changed; prepare again."
        raise StartupBlockedError(msg)
    integrity._log(
        f"[sqlite-startup] migrations authorized; recovery snapshot={backup}"
    )
    return True


def verify_snapshot(
    db_path: str,
    backup_dir: Path,
    *,
    prepare: bool,
    connection=None,
    fast: bool = False,
) -> None:
    """Check a private online copy; publish findings, never repair live rows.

    Preparation requires stopped writers. Main/WAL signatures bracket the
    entire operation and the permit is rechecked on startup. Online snapshots
    are observations of their copy time, never authority for a later migration.
    """
    from django.db.migrations.executor import MigrationExecutor

    descriptor = os.open(
        f"{db_path}.verification.lock",
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(descriptor, "a") as lock:
        if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
            msg = "Verification lock is not a regular file"
            raise StartupBlockedError(msg)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            msg = "Another SQLite verification is running"
            raise StartupBlockedError(msg) from error
        if prepare:
            _permit_path(db_path).unlink(missing_ok=True)
            report = integrity._read_incident_report(db_path)
            if integrity._incident_report_path(db_path).exists() and (
                not report or report.get("status") != "resolved"
            ):
                msg = (
                    "Resolve the existing recovery incident before preparing migrations"
                )
                raise StartupBlockedError(msg)
            # Production connection initialization may establish/checkpoint
            # WAL. Finish it BEFORE fingerprinting and copying the database,
            # so our own journal setup cannot invalidate a healthy snapshot.
            try:
                executor = MigrationExecutor(connection)
                executor.loader.check_consistent_history(connection)
                plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
            finally:
                connection.close()
        status_path = Path(f"{db_path}.verification.json")
        previous = integrity._read_sidecar(status_path, db_path)
        if (
            not prepare
            and previous
            and previous.get("identity") == _state(db_path)["main"][:2]
        ):
            checked_at = integrity._parse_timestamp(previous.get("checked_at"))
            if (
                checked_at
                and 0 <= (datetime.now(UTC) - checked_at).total_seconds() < 48 * 3600
            ):
                if previous.get("status") == "ok":
                    return
                msg = "Previous verification failed or was interrupted; automatic full scans are limited to once per 48h. Inspect its logs or prepare offline."
                raise StartupBlockedError(msg)
        before = _state(db_path)
        started = time.monotonic()

        def status(value: str, phase: str, **extra) -> None:
            integrity._log(f"[sqlite-verification] status={value} phase={phase}")
            integrity._publish_report(
                status_path,
                json.dumps(
                    {
                        "database": str(Path(db_path).resolve()),
                        "status": value,
                        "phase": phase,
                        "checked_at": datetime.now(UTC).isoformat(),
                        "elapsed_seconds": time.monotonic() - started,
                        "identity": before["main"][:2],
                        **extra,
                    }
                )
                + "\n",
                mode=0o644,  # same non-secret metadata policy as startup status
            )

        try:
            # A killed deadline worker cannot run its finally block. Only
            # unpublished staging files in this verifier's private directory
            # may be removed, under the same duplicate-run lock.
            try:
                directory = os.open(
                    backup_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                )
            except FileNotFoundError:
                pass
            except OSError as error:
                msg = f"Verification directory is not safely accessible: {error}"
                raise StartupBlockedError(msg) from error
            else:
                try:
                    pattern = rf"\.{re.escape(Path(db_path).stem)}-[0-9a-f]{{32}}\.sqlite3\.tmp"
                    for name in os.listdir(directory):  # noqa: PTH208 - pinned directory fd
                        if re.fullmatch(pattern, name):
                            os.unlink(name, dir_fd=directory)
                finally:
                    os.close(directory)
            # fast: the copy is gated by the sequential page sweep, not
            # quick_check (random reads, hours on slow storage).
            gate = "page_sweep" if fast else "quick_check"
            status("running", f"snapshot_and_{gate}")
            outcome: dict = {}
            snapshot = integrity.create_live_database_snapshot(
                db_path,
                backup_dir,
                max_keep=None,  # prune only after BOTH checks succeed
                timeout_seconds=2,
                verify=gate,
                outcome=outcome,
            )
            if snapshot is None:
                msg = "Snapshot/structural verification failed; inspect snapshot logs"
                raise StartupBlockedError(msg)  # noqa: TRY301
            status("running", "foreign_key_check", backup=str(snapshot))
            # fast: entrypoint-taken snapshot. Structural check only; the
            # relational scan then runs after startup (documented tradeoff).
            incident = {"total_conflicts": 0}
            if not fast:
                with closing(sqlite3.connect(snapshot)) as copied:
                    last_report = time.monotonic()
                    callbacks = 0

                    def progress():
                        nonlocal last_report, callbacks
                        callbacks += 1
                        if time.monotonic() - last_report >= _PROGRESS_REPORT_SECONDS:
                            status(
                                "running",
                                "foreign_key_check",
                                backup=str(snapshot),
                                structural="ok",
                                progress_callbacks=callbacks,
                            )
                            last_report = time.monotonic()
                        # Yield CPU/I/O between bounded instruction batches. All
                        # expensive checks run on the copy, without a live read txn.
                        time.sleep(0.002)
                        return 0

                    copied.set_progress_handler(progress, 100_000)
                    incident = integrity._inspect_foreign_keys(copied)
            with snapshot.open("rb") as checked:
                integrity._release_page_cache(checked.fileno(), snapshot.name)
            if incident["total_conflicts"]:
                integrity._write_incident_report(db_path, incident, status="blocked")
                msg = "Snapshot contains foreign-key conflicts; no live rows changed"
                raise StartupBlockedError(msg)  # noqa: TRY301
            if prepare:
                if _state(db_path) != before:
                    msg = "Database changed during preparation; stop all writers and retry"
                    raise StartupBlockedError(msg)  # noqa: TRY301
                permit = {
                    "database": str(Path(db_path).resolve()),
                    "state": before,
                    "plan": [[m.app_label, m.name, backwards] for m, backwards in plan],
                    "backup": str(snapshot),
                    "backup_signature": _signature(snapshot),
                    "commit_sha": os.environ.get("COMMIT_SHA"),
                    "snapshot_verified": outcome.get("verified", "quick_check"),
                    "quick_check_deferred": outcome.get("verified") == "page_sweep",
                }
                integrity._publish_report(
                    _permit_path(db_path), json.dumps(permit) + "\n"
                )
                integrity.record_verified_database(db_path, source="offline-snapshot")
                # A successful explicit offline check can clear an old failed
                # scan status, but never an unresolved incident.
                integrity.write_startup_status(
                    db_path,
                    status="ok",
                    phase="maintenance_verified",
                    started_at=datetime.now(UTC).isoformat(),
                    elapsed_seconds=time.monotonic() - started,
                )
            verified = outcome.get("verified", "quick_check")
            deferred = verified == "page_sweep"
            if prepare and deferred:
                sqlite_sliced_check.request_deferred_quick_check(
                    db_path, reason="snapshot gated by page sweep"
                )
            status(
                "ok",
                "complete",
                backup=str(snapshot),
                structural="ok",
                snapshot_verified=verified,
                quick_check_deferred=deferred,
                relational="skipped" if fast else "ok",
            )
            integrity._prune_recovery_backups(backup_dir, max_keep=7, newest=snapshot)
        except (OSError, sqlite3.DatabaseError, StartupBlockedError) as error:
            status("failed", "verification", error=str(error))
            raise
