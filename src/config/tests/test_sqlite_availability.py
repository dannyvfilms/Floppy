"""Admission stays cheap; only an unchanged offline snapshot permits migration."""

import copy
import fcntl
import io
import json
import signal
import sqlite3
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, connections
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.loader import MigrationLoader
from django.test import SimpleTestCase, override_settings

from config import sqlite_availability as admission
from config import sqlite_integrity as integrity
from config.sqlite_backend.base import DatabaseWrapper


class SQLiteAvailabilityTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.migrations = tuple(MigrationLoader(None).disk_migrations)

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = str((Path(directory.name) / "live.sqlite3").resolve())
        self.backups = Path(directory.name) / "backups"
        self.enterContext(override_settings(FLOPPY_DB_PATH=Path(self.database)))
        with sqlite3.connect(self.database) as db:
            db.execute(
                "CREATE TABLE django_migrations (id INTEGER PRIMARY KEY, app TEXT, name TEXT, applied TEXT)"
            )
            db.executemany(
                "INSERT INTO django_migrations (app, name, applied) VALUES (?, ?, '2026-01-01')",
                self.migrations,
            )
            db.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
            db.execute(
                "CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id))"
            )
        options = copy.deepcopy(connection.settings_dict)
        options.update(NAME=self.database, OPTIONS={"timeout": 0.1})
        self.wrapper = DatabaseWrapper(options, alias="admission-probe")
        self.addCleanup(self.wrapper.close)
        connections["admission-probe"] = self.wrapper
        self.addCleanup(connections.__delitem__, "admission-probe")
        self.enterContext(
            patch("config.sqlite_availability.apps.get_models", return_value=[])
        )

    def sidecar(self, path, **values):
        path.write_text(json.dumps({"database": self.database, **values}))

    def pending(self):
        executor = self.enterContext(
            patch("django.db.migrations.executor.MigrationExecutor")
        )
        executor.return_value.migration_plan.return_value = [
            (
                SimpleNamespace(app_label="events", name="0017_event_datetime_index"),
                False,
            )
        ]
        return executor

    def gate(self):
        return admission.startup_gate(self.database, self.wrapper)

    def verify(self, *, prepare=False, fast=False):
        admission.verify_snapshot(
            self.database,
            self.backups,
            prepare=prepare,
            connection=self.wrapper,
            fast=fast,
        )

    def test_current_history_never_runs_full_storage_or_relationship_checks(self):
        # These conditions used to force hours of foreground preflight work.
        for previous in (None, "expired", "new-image", "timeout"):
            with self.subTest(previous=previous):
                if previous:
                    integrity.record_verified_database(self.database, source="startup")
                    record = json.loads(
                        integrity._verified_path(self.database).read_text()
                    )
                    record.update(
                        verified_at="2000-01-01T00:00:00+00:00", commit_sha="old"
                    )
                    integrity._verified_path(self.database).write_text(
                        json.dumps(record)
                    )
                if previous == "timeout":
                    self.sidecar(
                        integrity._status_path(self.database), status="timeout"
                    )
                with (
                    patch.object(
                        integrity, "create_live_database_snapshot"
                    ) as snapshot,
                    patch.object(integrity, "_inspect_foreign_keys") as foreign_keys,
                    patch.dict("os.environ", {"COMMIT_SHA": "new"}),
                ):
                    self.assertFalse(self.gate())
                snapshot.assert_not_called()
                foreign_keys.assert_not_called()

    def test_slow_python_graph_loading_does_not_expire_the_sql_deadline(self):
        clock = time.monotonic
        offset = [0]

        def load_graph(connection):
            executor = MigrationExecutor(connection)
            offset[0] += 20  # module imports took time, without expensive SQL
            return executor

        with (
            patch(
                "django.db.migrations.executor.MigrationExecutor",
                side_effect=load_graph,
            ),
            patch.object(
                admission.time, "monotonic", side_effect=lambda: clock() + offset[0]
            ),
        ):
            self.assertFalse(self.gate())

    def test_current_history_is_readable_with_wal_and_active_writer(self):
        with sqlite3.connect(self.database) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("INSERT INTO parent VALUES (1)")
            writer.commit()
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("INSERT INTO parent VALUES (2)")
            self.assertFalse(self.gate())
            writer.rollback()

    def test_current_history_with_missing_model_column_blocks_startup(self):
        model = SimpleNamespace(
            _meta=SimpleNamespace(
                managed=True,
                proxy=False,
                swapped=False,
                db_table="parent",
                local_concrete_fields=[SimpleNamespace(column="missing_column")],
            )
        )
        with (
            patch("config.sqlite_availability.apps.get_models", return_value=[model]),
            self.assertRaisesRegex(admission.StartupBlockedError, "schema disagrees"),
        ):
            self.gate()

    def test_preparation_with_real_current_history_issues_empty_plan_permit(self):
        self.verify(prepare=True)
        permit = json.loads(admission._permit_path(self.database).read_text())
        self.assertEqual(permit["plan"], [])
        self.assertTrue(Path(permit["backup"]).is_file())
        self.assertFalse(self.gate())

    def test_preparation_authorizes_real_pending_migration_plan(self):
        loader = MigrationLoader(None)
        pending = next(
            key for key, node in loader.graph.node_map.items() if not node.children
        )
        with sqlite3.connect(self.database) as db:
            db.execute(
                "DELETE FROM django_migrations WHERE app = ? AND name = ?", pending
            )
        with self.assertRaises(admission.StartupBlockedError):
            self.gate()
        self.verify(prepare=True)
        permit = json.loads(admission._permit_path(self.database).read_text())
        self.assertIn([*pending, False], permit["plan"])
        self.assertTrue(all(not backwards for _, _, backwards in permit["plan"]))
        self.assertTrue(self.gate())

    def test_fast_preparation_skips_only_the_relational_scan(self):
        with sqlite3.connect(self.database) as db:
            db.execute("INSERT INTO child (id, parent_id) VALUES (1, 99)")
        self.verify(prepare=True, fast=True)
        permit = json.loads(admission._permit_path(self.database).read_text())
        self.assertTrue(Path(permit["backup"]).is_file())

    def test_fast_preparation_gates_on_page_sweep_and_defers_quick_check(self):
        real = integrity._backup_to_staging
        used = []

        def spy(*args, **kwargs):
            used.append(kwargs.get("verify"))
            return real(*args, **kwargs)

        with (
            patch.object(integrity, "_backup_to_staging", side_effect=spy),
            patch.object(
                integrity, "_sweep_copy", wraps=integrity._sweep_copy
            ) as swept,
        ):
            self.verify(prepare=True, fast=True)
        self.assertEqual(used, ["page_sweep"])
        swept.assert_called_once()
        permit = json.loads(admission._permit_path(self.database).read_text())
        self.assertEqual(permit["snapshot_verified"], "page_sweep")
        self.assertTrue(permit["quick_check_deferred"])
        progress = json.loads(
            Path(f"{self.database}.verification.progress.json").read_text()
        )
        self.assertIn("deferred_quick_check", progress)

    def test_non_fast_preparation_keeps_quick_check(self):
        self.verify(prepare=True)
        permit = json.loads(admission._permit_path(self.database).read_text())
        self.assertEqual(permit["snapshot_verified"], "quick_check")
        self.assertFalse(permit["quick_check_deferred"])
        self.assertFalse(Path(f"{self.database}.verification.progress.json").exists())

    def test_failed_page_sweep_on_the_copy_blocks_the_permit(self):
        with patch.object(integrity, "_sweep_copy", return_value=False):
            with self.assertRaises(admission.StartupBlockedError):
                self.verify(prepare=True, fast=True)
        self.assertFalse(admission._permit_path(self.database).exists())

    def test_missing_permit_is_distinguishable_for_the_entrypoint(self):
        self.pending()
        with self.assertRaises(admission.MigrationPermitRequiredError):
            self.gate()

    def test_new_image_invalidates_pending_migration_permit(self):
        self.pending()
        with patch.dict("os.environ", {"COMMIT_SHA": "old"}):
            self.verify(prepare=True)
        with (
            patch.dict("os.environ", {"COMMIT_SHA": "new"}),
            self.assertRaises(admission.StartupBlockedError),
        ):
            self.gate()

    def test_unresolved_or_unreadable_incident_blocks_before_graph_loading(self):
        report = integrity._incident_report_path(self.database)
        for contents in (
            "broken json",
            "[]",
            *(
                json.dumps({"database": self.database, "status": status})
                for status in ("blocked", "accepted", "prepared", "corrupt")
            ),
        ):
            with self.subTest(contents=contents):
                report.write_text(contents)
                with (
                    patch(
                        "django.db.migrations.executor.MigrationExecutor"
                    ) as executor,
                    self.assertRaises(admission.StartupBlockedError),
                ):
                    self.gate()
                executor.assert_not_called()

    def test_previous_failed_or_blocked_check_blocks_startup(self):
        for status in ("failed", "blocked"):
            with self.subTest(status=status):
                self.sidecar(integrity._status_path(self.database), status=status)
                with self.assertRaises(admission.StartupBlockedError):
                    self.gate()

    def test_replaced_verified_database_blocks_startup(self):
        integrity.record_verified_database(self.database, source="startup")
        replacement = Path(f"{self.database}.replacement")
        replacement.write_bytes(Path(self.database).read_bytes())
        replacement.replace(self.database)
        with self.assertRaisesRegex(admission.StartupBlockedError, "replaced"):
            self.gate()

    def test_corrupt_database_never_admitted(self):
        Path(self.database).write_bytes(b"not a SQLite database")
        with self.assertRaises((sqlite3.DatabaseError, admission.StartupBlockedError)):
            self.gate()

    def test_current_schema_admission_reads_wal_without_requesting_writer_lock(self):
        with sqlite3.connect(self.database, timeout=0) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("INSERT INTO parent VALUES (12)")
            self.assertFalse(self.gate())

    def test_failed_status_names_runnable_fix_and_prepare_clears_it(self):
        integrity.write_startup_status(
            self.database,
            status="failed",
            phase="admission",
            started_at="2026-01-01T00:00:00+00:00",
            elapsed_seconds=1,
        )
        with self.assertRaises(admission.StartupBlockedError) as raised:
            self.gate()
        message = str(raised.exception)
        self.assertIn("python manage.py sqlite_startup --prepare-migrations", message)
        self.assertIn("sqlite-startup-recovery.md", message)
        self.verify(prepare=True)
        self.assertFalse(self.gate())

    def test_pending_requires_offline_preparation(self):
        self.pending()
        with self.assertRaisesRegex(
            admission.StartupBlockedError, "prepare-migrations"
        ) as raised:
            self.gate()
        self.assertIn("python manage.py sqlite_startup", str(raised.exception))
        self.assertIn("sqlite-startup-recovery.md", str(raised.exception))
        self.verify()
        self.assertFalse(admission._permit_path(self.database).exists())
        with self.assertRaises(admission.StartupBlockedError):
            self.gate()
        self.verify(prepare=True)
        self.assertTrue(self.gate())

    def test_database_wal_backup_and_plan_changes_invalidate_permit(self):
        executor = self.pending()
        for changed in ("main", "wal", "backup", "plan"):
            with self.subTest(changed=changed):
                self.verify(prepare=True)
                permit = json.loads(admission._permit_path(self.database).read_text())
                if changed == "main":
                    with sqlite3.connect(self.database) as db:
                        db.execute("INSERT INTO parent DEFAULT VALUES")
                elif changed == "wal":
                    Path(f"{self.database}-wal").write_bytes(b"changed")
                elif changed == "backup":
                    Path(permit["backup"]).write_bytes(b"changed")
                else:
                    executor.return_value.migration_plan.return_value = [
                        (SimpleNamespace(app_label="events", name="different"), False)
                    ]
                with self.assertRaises(admission.StartupBlockedError):
                    self.gate()
                Path(f"{self.database}-wal").unlink(missing_ok=True)

    def test_changed_database_during_preparation_gets_no_permit(self):
        self.pending()
        snapshot = integrity.create_live_database_snapshot

        def mutate(*args, **kwargs):
            result = snapshot(*args, **kwargs)
            with sqlite3.connect(self.database) as db:
                db.execute("INSERT INTO parent VALUES (9)")
            return result

        with (
            patch.object(
                integrity, "create_live_database_snapshot", side_effect=mutate
            ),
            self.assertRaisesRegex(admission.StartupBlockedError, "changed during"),
        ):
            self.verify(prepare=True)
        self.assertFalse(admission._permit_path(self.database).exists())

    def test_backup_creating_an_empty_wal_does_not_invalidate_preparation(self):
        self.pending()
        snapshot = integrity.create_live_database_snapshot

        def create_empty_wal(*args, **kwargs):
            result = snapshot(*args, **kwargs)
            Path(f"{self.database}-wal").touch()
            return result

        with patch.object(
            integrity, "create_live_database_snapshot", side_effect=create_empty_wal
        ):
            self.verify(prepare=True)
        self.assertTrue(self.gate())

    def test_foreign_key_findings_never_modify_live_rows(self):
        with sqlite3.connect(self.database) as db:
            db.execute("INSERT INTO child VALUES (1, 999)")
        before = Path(self.database).read_bytes()
        with (
            self.assertRaisesRegex(admission.StartupBlockedError, "foreign-key"),
            patch.object(integrity, "_prune_recovery_backups") as prune,
        ):
            self.verify()
        prune.assert_not_called()
        self.assertEqual(Path(self.database).read_bytes(), before)
        self.assertEqual(
            integrity._read_incident_report(self.database)["status"], "blocked"
        )
        self.assertFalse(admission._permit_path(self.database).exists())
        status = json.loads(Path(f"{self.database}.verification.json").read_text())
        self.assertEqual(status["status"], "failed")

    def test_copy_verification_does_not_hold_a_live_writer_lock(self):
        inspect = integrity._inspect_foreign_keys

        def inspect_while_writing(copied):
            with sqlite3.connect(self.database, timeout=0) as live:
                live.execute("INSERT INTO parent VALUES (7)")
            return inspect(copied)

        with patch.object(
            integrity, "_inspect_foreign_keys", side_effect=inspect_while_writing
        ):
            self.verify()
        with sqlite3.connect(self.database) as live:
            self.assertEqual(live.execute("SELECT id FROM parent").fetchall(), [(7,)])

    def test_failed_preparation_revokes_an_older_permit(self):
        self.pending()
        self.verify(prepare=True)
        self.assertTrue(admission._permit_path(self.database).exists())
        with patch.object(
            integrity, "create_live_database_snapshot", return_value=None
        ):
            with self.assertRaises(admission.StartupBlockedError):
                self.verify(prepare=True)
        self.assertFalse(admission._permit_path(self.database).exists())

    def test_duplicate_verification_fails_before_snapshot(self):
        with Path(f"{self.database}.verification.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with (
                patch.object(integrity, "create_live_database_snapshot") as snapshot,
                self.assertRaisesRegex(admission.StartupBlockedError, "Another"),
            ):
                self.verify()
            snapshot.assert_not_called()

    def test_staging_cleanup_does_not_follow_backup_directory_symlink(self):
        outside = Path(self.database).parent / "unrelated"
        outside.mkdir()
        staging = outside / f".live-{'a' * 32}.sqlite3.tmp"
        staging.write_text("unrelated data")
        self.backups.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(admission.StartupBlockedError):
            self.verify()
        self.assertEqual(staging.read_text(), "unrelated data")

    def test_successful_background_verification_is_throttled(self):
        status_path = Path(f"{self.database}.verification.json")
        self.sidecar(
            status_path,
            status="ok",
            checked_at=datetime.now(UTC).isoformat(),
            identity=admission._state(self.database)["main"][:2],
        )
        with patch.object(integrity, "create_live_database_snapshot") as snapshot:
            self.verify()
        snapshot.assert_not_called()
        self.sidecar(
            status_path,
            status="ok",
            checked_at=(datetime.now(UTC) - timedelta(days=3)).isoformat(),
        )
        self.verify()
        self.assertEqual(json.loads(status_path.read_text())["status"], "ok")
        self.assertEqual(status_path.stat().st_mode & 0o777, 0o644)

    def test_snapshot_failure_records_failure_without_permit(self):
        with (
            patch.object(integrity, "create_live_database_snapshot", return_value=None),
            self.assertRaises(admission.StartupBlockedError),
        ):
            self.verify(prepare=True)
        self.assertEqual(
            json.loads(Path(f"{self.database}.verification.json").read_text())[
                "status"
            ],
            "failed",
        )
        self.assertFalse(admission._permit_path(self.database).exists())

    def test_failed_background_attempt_is_not_repeated_every_hour(self):
        status_path = Path(f"{self.database}.verification.json")
        for state in ("failed", "running"):
            self.sidecar(
                status_path,
                status=state,
                checked_at=datetime.now(UTC).isoformat(),
                identity=admission._state(self.database)["main"][:2],
            )
            with (
                patch.object(integrity, "create_live_database_snapshot") as snapshot,
                self.assertRaisesRegex(admission.StartupBlockedError, "48h"),
            ):
                self.verify()
            snapshot.assert_not_called()

    @override_settings(USING_SQLITE_DATABASE=True)
    def test_command_skips_migrate_when_history_current(self):
        with (
            override_settings(FLOPPY_DB_PATH=self.database),
            patch(
                "app.management.commands.sqlite_startup.startup_gate",
                return_value=False,
            ),
        ):
            with self.assertRaises(SystemExit) as caught:
                call_command("sqlite_startup")
        self.assertEqual(caught.exception.code, 10)

    @override_settings(USING_SQLITE_DATABASE=True)
    def test_command_maintenance_has_a_process_deadline(self):
        with (
            patch("app.management.commands.sqlite_startup.subprocess.Popen") as run,
            patch("app.management.commands.sqlite_startup._stop") as stop,
        ):
            run.return_value.wait.side_effect = subprocess.TimeoutExpired("worker", 12)
            with self.assertRaisesRegex(CommandError, "deadline"):
                call_command("sqlite_startup", prepare_migrations=True, timeout=12)
        self.assertEqual(run.return_value.wait.call_args.kwargs["timeout"], 12)
        self.assertIn("--worker", run.call_args.args[0])
        stop.assert_called_once_with(run.return_value)

    @override_settings(USING_SQLITE_DATABASE=True)
    def test_command_rejects_nonpositive_maintenance_timeout(self):
        with self.assertRaisesRegex(CommandError, "positive"):
            call_command("sqlite_startup", background=True, timeout=0)

    @override_settings(USING_SQLITE_DATABASE=False)
    def test_postgresql_does_not_run_sqlite_admission_or_maintenance(self):
        with (
            patch("app.management.commands.sqlite_startup.startup_gate") as gate,
            patch("app.management.commands.sqlite_startup.subprocess.Popen") as worker,
        ):
            call_command("sqlite_startup")
            call_command("sqlite_startup", background=True)
        gate.assert_not_called()
        worker.assert_not_called()

    def test_stale_recovery_approval_does_not_trigger_another_full_scan(self):
        for report in (None, {"database": self.database, "status": "resolved"}):
            if report:
                integrity._incident_report_path(self.database).write_text(
                    json.dumps(report)
                )
            integrity._decision_path(self.database).write_text("quarantine:old-token")
            with patch(
                "config.sqlite_recovery_policy.check_database_for_startup"
            ) as scan:
                call_command(
                    "sqlite_startup", recover=True, worker=True, stdout=io.StringIO()
                )
            scan.assert_not_called()
            self.assertFalse(integrity._decision_path(self.database).exists())

    def test_maintenance_forwards_termination_and_restores_signal_handler(self):
        previous = signal.getsignal(signal.SIGTERM)
        with patch("app.management.commands.sqlite_startup.subprocess.Popen") as worker:

            def terminate(**_kwargs):
                signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
                return -signal.SIGTERM

            worker.return_value.wait.side_effect = terminate
            with self.assertRaises(CommandError):
                call_command("sqlite_startup", background=True)
            worker.return_value.send_signal.assert_called_once_with(signal.SIGTERM)
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous)
