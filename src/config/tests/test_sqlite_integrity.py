"""Tests for the SQLite startup integrity guard (issue #593)."""

import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from config import sqlite_integrity
from config.sqlite_integrity import check_database_integrity

ENTRYPOINT = Path(__file__).resolve().parents[3] / "entrypoint.sh"
_ACTION_ENV = "FLOPPY_SQLITE_CONFLICT_ACTION"
# How long to wait for the entrypoint shell script to reach the state under
# test. This budget covers process startup on a shared runner, not the timing of
# the behaviour itself, so it is generous on purpose: five seconds was enough on
# an idle machine and ran out on CI, which failed the assertion that followed as
# if the entrypoint had misbehaved.
_STARTUP_WAIT_SECONDS = 60


class SqliteIntegrityTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.env_patcher = mock.patch.dict(os.environ, {"FLOPPY_SQLITE_AUTO_REPAIR": "false"})
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        super().tearDown()

    def unused_path(self):
        """Name a database the test never opens, outside the working tree.

        The connection is mocked, so the file is never read. The path still
        decides where a report is written, and a bare name writes it into
        whichever directory the suite was started from.
        """
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        return str(Path(tmp_dir.name) / "unused.sqlite3")

    def create_orphan_database(
        self,
        tmp_dir,
        *,
        rows=1,
        without_rowid=False,
        db_name="db.sqlite3",
    ):
        """Create a small database with missing parent relationships."""
        db_path = str(Path(tmp_dir) / db_name)
        conn = sqlite3.connect(db_path)
        child_suffix = " WITHOUT ROWID" if without_rowid else ""
        conn.executescript(
            f"""
            PRAGMA foreign_keys=ON;
            CREATE TABLE parent (id INTEGER PRIMARY KEY);
            CREATE TABLE child (
                id INTEGER PRIMARY KEY,
                parent_id INTEGER NOT NULL REFERENCES parent(id)
            ){child_suffix};
            INSERT INTO parent VALUES (1);
            """  # noqa: S608
        )
        conn.executemany(
            "INSERT INTO child VALUES (?, 1)",
            ((row_id,) for row_id in range(1, rows + 1)),
        )
        conn.commit()
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("DELETE FROM parent WHERE id = 1")
        conn.commit()
        conn.close()
        return db_path

    @staticmethod
    def read_incident_report(db_path):
        """Read the bounded recovery report written beside the database."""
        return json.loads(Path(f"{db_path}.integrity.json").read_text())

    def test_orphaned_album_artist_credit_is_removed(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "db.sqlite3")
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                PRAGMA foreign_keys=ON;
                CREATE TABLE app_album (id INTEGER PRIMARY KEY);
                CREATE TABLE app_artist (id INTEGER PRIMARY KEY);
                CREATE TABLE app_albumartist (
                    id INTEGER PRIMARY KEY,
                    album_id INTEGER NOT NULL REFERENCES app_album(id),
                    artist_id INTEGER NOT NULL REFERENCES app_artist(id)
                );
                INSERT INTO app_album VALUES (345);
                INSERT INTO app_artist VALUES (12);
                INSERT INTO app_albumartist VALUES (1, 345, 12);
                """
            )
            conn.commit()
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("DELETE FROM app_album WHERE id = 345")
            conn.commit()
            conn.close()

            with mock.patch("sys.stderr"):
                check_database_integrity(db_path)

            conn = sqlite3.connect(db_path)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM app_albumartist").fetchone()[0],
                0,
            )
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            conn.close()

            report = self.read_incident_report(db_path)
            self.assertEqual(report["status"], "resolved")
            self.assertEqual(report["resolution"], "automatic-album-artist")
            backup = sqlite3.connect(report["backup_path"])
            self.assertEqual(
                backup.execute("SELECT COUNT(*) FROM app_albumartist").fetchone()[0],
                1,
            )
            self.assertEqual(len(backup.execute("PRAGMA foreign_key_check").fetchall()), 1)
            backup.close()

    def test_unknown_foreign_key_violation_writes_bounded_report(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_orphan_database(tmp_dir, rows=1000)

            with (
                self.assertRaises(SystemExit) as ctx,
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
            ):
                check_database_integrity(db_path)

            self.assertEqual(ctx.exception.code, 1)
            output = stderr.getvalue()
            self.assertEqual(output.count("foreign key check failed"), 5)
            self.assertIn("1000 foreign key conflict(s)", output)
            self.assertIn("FLOPPY_SQLITE_CONFLICT_ACTION=accept:", output)
            self.assertIn("FLOPPY_SQLITE_CONFLICT_ACTION=quarantine:", output)

            report = self.read_incident_report(db_path)
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["total_conflicts"], 1000)
            self.assertEqual(
                report["groups"],
                [
                    {
                        "count": 1000,
                        "foreign_key_id": 0,
                        "parent": "parent",
                        "table": "child",
                    }
                ],
            )
            self.assertEqual(len(report["samples"]), 5)
            self.assertEqual(len(report["fingerprint"]), 64)
            self.assertEqual(len(report["incident_token"]), 32)

            conn = sqlite3.connect(db_path)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM child").fetchone()[0], 1000
            )
            conn.close()

    def test_matching_accept_action_preserves_rows_and_allows_startup(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_orphan_database(tmp_dir, rows=3)
            with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
                check_database_integrity(db_path)

            incident_token = self.read_incident_report(db_path)["incident_token"]
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "FLOPPY_SQLITE_CONFLICT_ACTION": f"accept:{incident_token}",
                    },
                ),
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
            ):
                check_database_integrity(db_path)

            self.assertIn("Accepted 3 foreign key conflict(s)", stderr.getvalue())
            self.assertEqual(self.read_incident_report(db_path)["status"], "accepted")
            conn = sqlite3.connect(db_path)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM child").fetchone()[0], 3)
            conn.close()

    def test_mismatched_accept_token_stops_startup(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_orphan_database(tmp_dir)
            with (
                mock.patch.dict(
                    os.environ,
                    {"FLOPPY_SQLITE_CONFLICT_ACTION": "accept:wrong-incident"},
                ),
                self.assertRaises(SystemExit) as ctx,
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
            ):
                check_database_integrity(db_path)

            self.assertEqual(ctx.exception.code, 1)
            output = stderr.getvalue()
            self.assertIn("does not carry the current incident token", output)
            # The operator must be sent to the token, never to the fingerprint.
            report = self.read_incident_report(db_path)
            self.assertIn(f"accept:{report['incident_token']}", output)
            self.assertNotIn(f"accept:{report['fingerprint']}", output)

    def test_quarantine_action_backs_up_then_deletes_orphans(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_orphan_database(tmp_dir, rows=3)
            with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
                check_database_integrity(db_path)

            incident_token = self.read_incident_report(db_path)["incident_token"]
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "FLOPPY_SQLITE_CONFLICT_ACTION": f"quarantine:{incident_token}",
                    },
                ),
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
            ):
                check_database_integrity(db_path)

            report = self.read_incident_report(db_path)
            self.assertEqual(report["status"], "resolved")
            self.assertEqual(report["resolution"], "quarantine")
            backup_path = Path(report["backup_path"])
            self.assertTrue(backup_path.is_file())
            self.assertIn("Quarantined 3 orphaned row(s)", stderr.getvalue())

            conn = sqlite3.connect(db_path)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM child").fetchone()[0], 0)
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            conn.close()

            backup = sqlite3.connect(backup_path)
            self.assertEqual(backup.execute("SELECT COUNT(*) FROM child").fetchone()[0], 3)
            self.assertEqual(len(backup.execute("PRAGMA foreign_key_check").fetchall()), 3)
            backup.close()

    def test_quarantine_refuses_rows_without_a_rowid(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_orphan_database(tmp_dir, without_rowid=True)
            with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
                check_database_integrity(db_path)

            report = self.read_incident_report(db_path)
            incident_token = report["incident_token"]
            self.assertFalse(report["can_quarantine"])
            self.assertNotIn("quarantine", report["actions"])
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "FLOPPY_SQLITE_CONFLICT_ACTION": f"quarantine:{incident_token}",
                    },
                ),
                self.assertRaises(SystemExit) as ctx,
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
            ):
                check_database_integrity(db_path)

            self.assertEqual(ctx.exception.code, 1)
            self.assertIn("cannot be quarantined automatically", stderr.getvalue())
            conn = sqlite3.connect(db_path)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM child").fetchone()[0], 1)
            conn.close()

    def test_foreign_key_groups_include_constraint_identity(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "db.sqlite3")
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE parent (id INTEGER PRIMARY KEY);
                CREATE TABLE child (
                    id INTEGER PRIMARY KEY,
                    left_id INTEGER REFERENCES parent(id),
                    right_id INTEGER REFERENCES parent(id)
                );
                INSERT INTO child VALUES (1, 10, 20);
                """
            )
            conn.commit()
            conn.close()

            with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
                check_database_integrity(db_path)

            groups = self.read_incident_report(db_path)["groups"]
            self.assertEqual(len(groups), 2)
            self.assertEqual({group["foreign_key_id"] for group in groups}, {0, 1})
            self.assertTrue(all(group["count"] == 1 for group in groups))

    def test_blocked_incident_reuses_random_authorization_token(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_orphan_database(tmp_dir)
            with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
                check_database_integrity(db_path)
            first = self.read_incident_report(db_path)

            with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
                check_database_integrity(db_path)
            second = self.read_incident_report(db_path)

            self.assertEqual(second["incident_token"], first["incident_token"])
            self.assertNotEqual(second["incident_token"], second["fingerprint"])

    def test_special_database_paths_backup_the_exact_live_database(self):
        names_and_decoys = {
            "db?real.sqlite3": "db",
            "db#real.sqlite3": "db",
            "db%20real.sqlite3": "db real.sqlite3",
            "db space ☃.sqlite3": None,
        }
        for db_name, decoy_name in names_and_decoys.items():
            with self.subTest(db_name=db_name), tempfile.TemporaryDirectory() as tmp_dir:
                db_path = self.create_orphan_database(tmp_dir, db_name=db_name)
                live = sqlite3.connect(db_path)
                live.execute("CREATE TABLE marker (value TEXT)")
                live.execute("INSERT INTO marker VALUES ('live')")
                live.commit()
                live.close()

                if decoy_name:
                    decoy_path = self.create_orphan_database(
                        tmp_dir,
                        db_name=decoy_name,
                    )
                    decoy = sqlite3.connect(decoy_path)
                    decoy.execute("CREATE TABLE marker (value TEXT)")
                    decoy.execute("INSERT INTO marker VALUES ('decoy')")
                    decoy.commit()
                    decoy.close()

                with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
                    check_database_integrity(db_path)
                token = self.read_incident_report(db_path)["incident_token"]
                with (
                    mock.patch.dict(
                        os.environ,
                        {_ACTION_ENV: f"quarantine:{token}"},
                    ),
                    mock.patch("sys.stderr"),
                ):
                    check_database_integrity(db_path)

                report = self.read_incident_report(db_path)
                backup = sqlite3.connect(report["backup_path"])
                self.assertEqual(
                    backup.execute("SELECT value FROM marker").fetchone()[0],
                    "live",
                )
                self.assertEqual(backup.execute("SELECT COUNT(*) FROM child").fetchone()[0], 1)
                backup.close()

    def test_report_publication_does_not_follow_predictable_symlink(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_orphan_database(tmp_dir)
            victim = Path(tmp_dir) / "victim"
            victim.write_text("do not overwrite")
            Path(f"{db_path}.integrity.json.tmp").symlink_to(victim)

            with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
                check_database_integrity(db_path)

            self.assertEqual(victim.read_text(), "do not overwrite")
            self.assertTrue(Path(f"{db_path}.integrity.json").is_file())

    def test_report_publication_replaces_destination_symlink_not_its_target(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_orphan_database(tmp_dir)
            victim = Path(tmp_dir) / "victim"
            victim.write_text("do not overwrite")
            report_path = Path(f"{db_path}.integrity.json")
            report_path.symlink_to(victim)

            with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
                check_database_integrity(db_path)

            self.assertEqual(victim.read_text(), "do not overwrite")
            self.assertFalse(report_path.is_symlink())
            self.assertEqual(json.loads(report_path.read_text())["status"], "blocked")

    def test_resolved_quarantine_token_cannot_delete_a_recreated_conflict(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_orphan_database(tmp_dir)
            with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
                check_database_integrity(db_path)
            old_token = self.read_incident_report(db_path)["incident_token"]
            action = f"quarantine:{old_token}"
            with mock.patch.dict(os.environ, {_ACTION_ENV: action}), mock.patch(
                "sys.stderr"
            ):
                check_database_integrity(db_path)

            conn = sqlite3.connect(db_path)
            conn.execute("INSERT INTO child VALUES (1, 1)")
            conn.commit()
            conn.close()

            with (
                mock.patch.dict(os.environ, {_ACTION_ENV: action}),
                self.assertRaises(SystemExit),
                mock.patch("sys.stderr"),
            ):
                check_database_integrity(db_path)

            report = self.read_incident_report(db_path)
            self.assertNotEqual(report["incident_token"], old_token)
            conn = sqlite3.connect(db_path)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM child").fetchone()[0], 1)
            conn.close()

    def test_quarantine_refuses_delete_triggers_before_changing_rows(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_orphan_database(tmp_dir)
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE unrelated (id INTEGER PRIMARY KEY);
                INSERT INTO unrelated VALUES (1);
                CREATE TRIGGER child_cleanup AFTER DELETE ON child BEGIN
                    DELETE FROM unrelated WHERE id = OLD.id;
                END;
                """
            )
            conn.commit()
            conn.close()

            with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
                check_database_integrity(db_path)
            report = self.read_incident_report(db_path)
            self.assertFalse(report["can_quarantine"])
            self.assertNotIn("quarantine", report["actions"])

            with (
                mock.patch.dict(
                    os.environ,
                    {_ACTION_ENV: f"quarantine:{report['incident_token']}"},
                ),
                self.assertRaises(SystemExit),
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
            ):
                check_database_integrity(db_path)

            self.assertIn("DELETE trigger", stderr.getvalue())
            conn = sqlite3.connect(db_path)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM child").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM unrelated").fetchone()[0], 1)
            conn.close()

    def test_quarantine_refuses_commented_delete_trigger_without_collateral_deletion(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_orphan_database(tmp_dir)
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE unrelated (id INTEGER PRIMARY KEY);
                INSERT INTO unrelated VALUES (1);
                CREATE TRIGGER child_cleanup AFTER DELETE /* gap */ ON child BEGIN
                    DELETE FROM unrelated WHERE id = OLD.id;
                END;
                """
            )
            conn.commit()
            conn.close()

            with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
                check_database_integrity(db_path)
            report = self.read_incident_report(db_path)

            self.assertFalse(report["can_quarantine"])
            self.assertNotIn("quarantine", report["actions"])
            conn = sqlite3.connect(db_path)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM child").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM unrelated").fetchone()[0], 1)
            conn.close()

    def test_quarantine_refuses_case_mismatched_delete_trigger(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_orphan_database(tmp_dir)
            conn = sqlite3.connect(db_path)
            # sqlite_schema.tbl_name keeps the spelling used by CREATE TRIGGER,
            # but SQLite still fires the trigger for the canonical table name.
            conn.executescript(
                """
                CREATE TABLE unrelated (id INTEGER PRIMARY KEY);
                INSERT INTO unrelated VALUES (1);
                CREATE TRIGGER child_cleanup AFTER DELETE ON CHILD BEGIN
                    DELETE FROM unrelated;
                END;
                """
            )
            conn.commit()
            conn.close()

            with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
                check_database_integrity(db_path)
            report = self.read_incident_report(db_path)
            self.assertFalse(report["can_quarantine"])
            self.assertNotIn("quarantine", report["actions"])

            with (
                mock.patch.dict(
                    os.environ,
                    {_ACTION_ENV: f"quarantine:{report['incident_token']}"},
                ),
                self.assertRaises(SystemExit),
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
            ):
                check_database_integrity(db_path)

            self.assertIn("DELETE trigger", stderr.getvalue())
            conn = sqlite3.connect(db_path)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM child").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM unrelated").fetchone()[0], 1)
            conn.close()

    def test_quarantine_refuses_declared_rowid_without_deleting_duplicate_values(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "db.sqlite3")
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE parent (id INTEGER PRIMARY KEY);
                INSERT INTO parent VALUES (1);
                CREATE TABLE child (
                    rowid INTEGER NOT NULL,
                    parent_id INTEGER REFERENCES parent(id)
                );
                INSERT INTO child VALUES (1, 42);
                INSERT INTO child VALUES (1, 1);
                """
            )
            conn.commit()
            conn.close()

            with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
                check_database_integrity(db_path)
            report = self.read_incident_report(db_path)

            self.assertFalse(report["can_quarantine"])
            self.assertNotIn("quarantine", report["actions"])
            self.assertTrue(
                any("shadows hidden row identity" in reason for reason in report["unsafe_reasons"])
            )
            conn = sqlite3.connect(db_path)
            self.assertEqual(
                conn.execute("SELECT rowid, parent_id FROM child ORDER BY parent_id").fetchall(),
                [(1, 1), (1, 42)],
            )
            conn.close()

    def test_quarantine_refuses_symlinked_recovery_directory(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_orphan_database(tmp_dir)
            victim_dir = Path(tmp_dir) / "victim-backups"
            victim_dir.mkdir()
            (Path(tmp_dir) / "sqlite-recovery").symlink_to(victim_dir)
            with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
                check_database_integrity(db_path)
            report = self.read_incident_report(db_path)

            with (
                mock.patch.dict(
                    os.environ,
                    {_ACTION_ENV: f"quarantine:{report['incident_token']}"},
                ),
                self.assertRaises(SystemExit),
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
            ):
                check_database_integrity(db_path)

            self.assertIn("recovery directory", stderr.getvalue())
            self.assertEqual(list(victim_dir.iterdir()), [])
            conn = sqlite3.connect(db_path)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM child").fetchone()[0], 1)
            conn.close()

    def test_failed_backup_verification_leaves_no_official_or_staging_file(self):
        class BadQuickCheckConnection(sqlite3.Connection):
            def execute(self, sql, parameters=(), /):
                if sql.strip().upper() == "PRAGMA QUICK_CHECK":
                    return super().execute("SELECT 'bad backup'")
                return super().execute(sql, parameters)

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_orphan_database(tmp_dir)
            with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
                check_database_integrity(db_path)
            report = self.read_incident_report(db_path)
            real_connect = sqlite3.connect

            def connect(database, *args, **kwargs):
                if str(database).endswith(".sqlite3.tmp"):
                    kwargs["factory"] = BadQuickCheckConnection
                return real_connect(database, *args, **kwargs)

            with (
                mock.patch(
                    "config.sqlite_integrity.sqlite3.connect",
                    side_effect=connect,
                ),
                mock.patch.dict(
                    os.environ,
                    {_ACTION_ENV: f"quarantine:{report['incident_token']}"},
                ),
                self.assertRaises(SystemExit),
                mock.patch("sys.stderr"),
            ):
                check_database_integrity(db_path)

            self.assertEqual(list((Path(tmp_dir) / "sqlite-recovery").iterdir()), [])
            conn = sqlite3.connect(db_path)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM child").fetchone()[0], 1)
            conn.close()

    def test_backup_publication_collision_fails_closed_and_cleans_staging(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_orphan_database(tmp_dir)
            with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
                check_database_integrity(db_path)
            report = self.read_incident_report(db_path)

            with (
                mock.patch.dict(
                    os.environ,
                    {_ACTION_ENV: f"quarantine:{report['incident_token']}"},
                ),
                mock.patch(
                    "config.sqlite_integrity.os.link",
                    side_effect=FileExistsError("collision"),
                ),
                self.assertRaises(SystemExit),
                mock.patch("sys.stderr"),
            ):
                check_database_integrity(db_path)

            self.assertEqual(list((Path(tmp_dir) / "sqlite-recovery").iterdir()), [])
            conn = sqlite3.connect(db_path)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM child").fetchone()[0], 1)
            conn.close()

    def test_verified_backup_survives_call_during_exception_handling(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_orphan_database(tmp_dir)
            # Cleanup must key off this call's own outcome. A caller that is
            # already handling an unrelated exception must still get a backup,
            # otherwise rows are deleted against a file that was just removed.
            try:
                json.loads("{")
            except ValueError:
                backup_path = sqlite_integrity._create_verified_backup(
                    db_path,
                    "0" * 64,
                )

            self.assertTrue(backup_path.is_file())
            backup = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
            self.assertEqual(backup.execute("PRAGMA quick_check").fetchone(), ("ok",))
            backup.close()

    def test_prepared_report_survives_resolved_report_failure_and_reconciles(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_orphan_database(tmp_dir)
            with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
                check_database_integrity(db_path)
            report = self.read_incident_report(db_path)
            real_write = sqlite_integrity._write_incident_report

            def fail_resolved(*args, **kwargs):
                if kwargs["status"] == "resolved":
                    raise OSError("simulated report failure")
                return real_write(*args, **kwargs)

            with (
                mock.patch.dict(
                    os.environ,
                    {_ACTION_ENV: f"quarantine:{report['incident_token']}"},
                ),
                mock.patch.object(
                    sqlite_integrity,
                    "_write_incident_report",
                    side_effect=fail_resolved,
                ),
                self.assertRaises(SystemExit),
                mock.patch("sys.stderr"),
            ):
                check_database_integrity(db_path)

            prepared = self.read_incident_report(db_path)
            self.assertEqual(prepared["status"], "prepared")
            self.assertTrue(Path(prepared["backup_path"]).is_file())
            conn = sqlite3.connect(db_path)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM child").fetchone()[0], 0)
            conn.close()

            check_database_integrity(db_path)
            resolved = self.read_incident_report(db_path)
            self.assertEqual(resolved["status"], "resolved")
            self.assertEqual(resolved["resolution"], "quarantine")

    def test_resolved_directory_fsync_failure_restores_prepared_report(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_orphan_database(tmp_dir)
            with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
                check_database_integrity(db_path)
            blocked = self.read_incident_report(db_path)
            real_fsync_directory = sqlite_integrity._fsync_directory
            failed_resolved = False

            def fail_after_resolved_replace(directory):
                nonlocal failed_resolved
                report = self.read_incident_report(db_path)
                if report["status"] == "resolved" and not failed_resolved:
                    failed_resolved = True
                    raise OSError("simulated resolved directory fsync failure")
                return real_fsync_directory(directory)

            with (
                mock.patch.dict(
                    os.environ,
                    {_ACTION_ENV: f"quarantine:{blocked['incident_token']}"},
                ),
                mock.patch.object(
                    sqlite_integrity,
                    "_fsync_directory",
                    side_effect=fail_after_resolved_replace,
                ),
                self.assertRaises(SystemExit),
                mock.patch("sys.stderr"),
            ):
                check_database_integrity(db_path)

            self.assertTrue(failed_resolved)
            prepared = self.read_incident_report(db_path)
            self.assertEqual(prepared["status"], "prepared")
            backup_path = Path(prepared["backup_path"])
            self.assertTrue(backup_path.is_file())
            backup = sqlite3.connect(backup_path)
            self.assertEqual(backup.execute("PRAGMA quick_check").fetchone(), ("ok",))
            self.assertEqual(backup.execute("SELECT COUNT(*) FROM child").fetchone()[0], 1)
            backup.close()
            conn = sqlite3.connect(db_path)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM child").fetchone()[0], 0)
            conn.close()

            check_database_integrity(db_path)
            resolved = self.read_incident_report(db_path)
            self.assertEqual(resolved["status"], "resolved")
            self.assertEqual(resolved["resolution"], "quarantine")

    def test_resolved_report_restoration_failure_does_not_claim_success(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_orphan_database(tmp_dir)
            with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
                check_database_integrity(db_path)
            blocked = self.read_incident_report(db_path)
            real_fsync_directory = sqlite_integrity._fsync_directory
            resolved_failed = False

            def fail_resolved_and_restoration(directory):
                nonlocal resolved_failed
                status = self.read_incident_report(db_path)["status"]
                if status == "resolved":
                    resolved_failed = True
                    raise OSError("simulated resolved fsync failure")
                if resolved_failed and status == "prepared":
                    raise OSError("simulated restoration fsync failure")
                return real_fsync_directory(directory)

            with (
                mock.patch.dict(
                    os.environ,
                    {_ACTION_ENV: f"quarantine:{blocked['incident_token']}"},
                ),
                mock.patch.object(
                    sqlite_integrity,
                    "_fsync_directory",
                    side_effect=fail_resolved_and_restoration,
                ),
                self.assertRaises(SystemExit),
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
            ):
                check_database_integrity(db_path)

            output = stderr.getvalue()
            self.assertIn("restoration could not be confirmed", output)
            self.assertNotIn("prepared report was restored", output)
            conn = sqlite3.connect(db_path)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM child").fetchone()[0], 0)
            conn.close()

    def test_unverifiable_prepared_backup_does_not_block_a_healthy_database(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_orphan_database(tmp_dir)
            with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
                check_database_integrity(db_path)
            report = self.read_incident_report(db_path)
            real_write = sqlite_integrity._write_incident_report

            def fail_resolved(*args, **kwargs):
                if kwargs["status"] == "resolved":
                    raise OSError("simulated report failure")
                return real_write(*args, **kwargs)

            with (
                mock.patch.dict(
                    os.environ,
                    {_ACTION_ENV: f"quarantine:{report['incident_token']}"},
                ),
                mock.patch.object(
                    sqlite_integrity,
                    "_write_incident_report",
                    side_effect=fail_resolved,
                ),
                self.assertRaises(SystemExit),
                mock.patch("sys.stderr"),
            ):
                check_database_integrity(db_path)

            prepared = self.read_incident_report(db_path)
            self.assertEqual(prepared["status"], "prepared")
            # The operator prunes sqlite-recovery/ after reading the report.
            Path(prepared["backup_path"]).unlink()

            with mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
                check_database_integrity(db_path)

            # The delete is already committed and the relationships are clean,
            # so bookkeeping must not wedge an otherwise healthy container.
            self.assertIn("could not be finalized", stderr.getvalue())
            self.assertEqual(self.read_incident_report(db_path)["status"], "prepared")

    def test_main_table_named_like_conflict_staging_table_is_quarantined(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "db.sqlite3")
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE parent (id INTEGER PRIMARY KEY);
                CREATE TABLE floppy_fk_conflicts (
                    id INTEGER PRIMARY KEY,
                    parent_id INTEGER REFERENCES parent(id)
                );
                INSERT INTO floppy_fk_conflicts VALUES (1, 42);
                """
            )
            conn.commit()
            conn.close()

            with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
                check_database_integrity(db_path)
            report = self.read_incident_report(db_path)
            with (
                mock.patch.dict(
                    os.environ,
                    {_ACTION_ENV: f"quarantine:{report['incident_token']}"},
                ),
                mock.patch("sys.stderr"),
            ):
                check_database_integrity(db_path)

            conn = sqlite3.connect(db_path)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM main.floppy_fk_conflicts").fetchone()[0],
                0,
            )
            conn.close()

    def test_wal_backup_is_complete_and_restorable(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "db.sqlite3")
            setup = sqlite3.connect(db_path)
            setup.execute("PRAGMA journal_mode=WAL")
            setup.execute("PRAGMA wal_autocheckpoint=0")
            setup.executescript(
                """
                CREATE TABLE parent (id INTEGER PRIMARY KEY);
                CREATE TABLE child (
                    id INTEGER PRIMARY KEY,
                    parent_id INTEGER REFERENCES parent(id)
                );
                CREATE TABLE marker (value TEXT);
                INSERT INTO child VALUES (1, 42);
                INSERT INTO marker VALUES ('in wal');
                """
            )
            setup.commit()

            with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
                check_database_integrity(db_path)
            report = self.read_incident_report(db_path)
            with (
                mock.patch.dict(
                    os.environ,
                    {_ACTION_ENV: f"quarantine:{report['incident_token']}"},
                ),
                mock.patch("sys.stderr"),
            ):
                check_database_integrity(db_path)
            setup.close()

            backup_path = self.read_incident_report(db_path)["backup_path"]
            backup = sqlite3.connect(backup_path)
            restored_path = str(Path(tmp_dir) / "restored.sqlite3")
            restored = sqlite3.connect(restored_path)
            backup.backup(restored)
            backup.close()
            self.assertEqual(restored.execute("PRAGMA quick_check").fetchone(), ("ok",))
            self.assertEqual(restored.execute("SELECT value FROM marker").fetchone(), ("in wal",))
            self.assertEqual(restored.execute("SELECT COUNT(*) FROM child").fetchone()[0], 1)
            restored.close()

    def test_entrypoint_parks_once_instead_of_polling_exited_checker(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = self.create_orphan_database(tmp_dir, rows=1000)
            bin_path = tmp_path / "bin"
            bin_path.mkdir()
            wrappers = {
                "python": (
                    "#!/bin/sh\n"
                    'case "$2" in\n'
                    "  *check_database_integrity*)\n"
                    '    echo "[entrypoint] bounded integrity failure" >&2\n'
                    "    exit 1\n"
                    "    ;;\n"
                    "esac\n"
                    f'exec "{sys.executable}" "$@"\n'
                ),
                "sleep": (
                    "#!/bin/sh\n"
                    'echo "$$" > "$PARKING_PID_FILE"\n'
                    "exec /bin/sleep 30\n"
                ),
            }
            for name, script in wrappers.items():
                wrapper = bin_path / name
                wrapper.write_text(script)
                wrapper.chmod(0o755)

            env = {
                **os.environ,
                "DB_HOST": "",
                "PARKING_PID_FILE": str(tmp_path / "parking.pid"),
                "FLOPPY_DATA_DIR": tmp_dir,
                "FLOPPY_DB_PATH": db_path,
                "PATH": f"{bin_path}:{os.environ['PATH']}",
                "PYTHONPATH": str(ENTRYPOINT.parent / "src"),
            }
            output_path = tmp_path / "entrypoint.log"
            with output_path.open("w") as output:
                process = subprocess.Popen(  # noqa: S603
                    ["/bin/sh", str(ENTRYPOINT)],
                    cwd=ENTRYPOINT.parent,
                    env=env,
                    stdout=output,
                    stderr=output,
                    text=True,
                )
                deadline = time.monotonic() + _STARTUP_WAIT_SECONDS
                while (
                    (
                        "SQLite startup is paused" not in output_path.read_text()
                        or not (tmp_path / "parking.pid").is_file()
                    )
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.02)
                parked_before_term = process.poll() is None
                parking_pid = (
                    int((tmp_path / "parking.pid").read_text())
                    if (tmp_path / "parking.pid").is_file()
                    else None
                )
                parking_child_before_term = False
                if parking_pid is not None:
                    try:
                        os.kill(parking_pid, 0)
                        parking_child_before_term = True
                    except ProcessLookupError:
                        pass
                process.terminate()
                process.wait(timeout=5)
            output = output_path.read_text()

            # Report the entrypoint log on failure. Without it these read as
            # "False is not true", which does not say whether the entrypoint
            # behaved wrongly or simply had not started yet.
            self.assertTrue(
                parked_before_term,
                f"entrypoint exited instead of parking. Log:\n{output}",
            )
            self.assertTrue(
                parking_child_before_term,
                f"no live parking child was found. Log:\n{output}",
            )
            self.assertEqual(process.returncode, 0)
            self.assertEqual(output.count("bounded integrity failure"), 1)
            self.assertNotIn("Still checking SQLite integrity", output)
            self.assertIn("SQLite startup is paused", output)
            self.assertNotIn("exceeded its 600s timeout", output)
            self.assertNotIn("Applying database migrations", output)
            with self.assertRaises(ProcessLookupError):
                os.kill(parking_pid, 0)

    def test_entrypoint_term_during_integrity_check_stops_before_migrations(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = self.create_orphan_database(tmp_dir)
            bin_path = tmp_path / "bin"
            bin_path.mkdir()
            python_wrapper = bin_path / "python"
            python_wrapper.write_text(
                "#!/bin/sh\n"
                'case "$2" in\n'
                "  *check_database_integrity*)\n"
                '    echo "$$" > "$CHECKER_PID_FILE"\n'
                '    echo "[entrypoint] checker waiting" >&2\n'
                "    exec /bin/sleep 30\n"
                "    ;;\n"
                "esac\n"
                f'exec "{sys.executable}" "$@"\n'
            )
            python_wrapper.chmod(0o755)
            timeout_wrapper = bin_path / "timeout"
            timeout_wrapper.write_text('#!/bin/sh\nshift\nexec "$@"\n')
            timeout_wrapper.chmod(0o755)
            env = {
                **os.environ,
                "DB_HOST": "",
                "CHECKER_PID_FILE": str(tmp_path / "checker.pid"),
                "FLOPPY_DATA_DIR": tmp_dir,
                "FLOPPY_DB_PATH": db_path,
                "PATH": f"{bin_path}:{os.environ['PATH']}",
                "PYTHONPATH": str(ENTRYPOINT.parent / "src"),
            }
            output_path = tmp_path / "entrypoint-term.log"
            with output_path.open("w") as output:
                process = subprocess.Popen(  # noqa: S603
                    ["/bin/sh", str(ENTRYPOINT)],
                    cwd=ENTRYPOINT.parent,
                    env=env,
                    stdout=output,
                    stderr=output,
                    text=True,
                )
                deadline = time.monotonic() + _STARTUP_WAIT_SECONDS
                while (
                    "checker waiting" not in output_path.read_text()
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.02)
                process.terminate()
                process.wait(timeout=5)
            output = output_path.read_text()

            self.assertEqual(process.returncode, 0)
            self.assertIn("checker waiting", output)
            self.assertNotIn("Applying database migrations", output)
            checker_pid = int((tmp_path / "checker.pid").read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(checker_pid, 0)

    def test_repair_holds_write_lock_from_check_through_delete(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "db.sqlite3")
            setup = sqlite3.connect(db_path)
            setup.executescript(
                """
                CREATE TABLE app_album (id INTEGER PRIMARY KEY);
                CREATE TABLE app_artist (id INTEGER PRIMARY KEY);
                CREATE TABLE app_albumartist (
                    id INTEGER PRIMARY KEY,
                    album_id INTEGER NOT NULL REFERENCES app_album(id),
                    artist_id INTEGER NOT NULL REFERENCES app_artist(id)
                );
                INSERT INTO app_artist VALUES (12);
                INSERT INTO app_albumartist VALUES (1, 345, 12);
                """
            )
            setup.commit()
            setup.close()

            check_conn = sqlite3.connect(db_path)
            competing_conn = sqlite3.connect(db_path, timeout=0)
            competing_result = []

            def attempt_competing_repair(statement):
                if not statement.startswith('DELETE FROM main."app_albumartist"'):
                    return
                try:
                    competing_conn.execute("INSERT INTO app_album VALUES (345)")
                    competing_conn.commit()
                except sqlite3.OperationalError as error:
                    competing_result.append(str(error))

            check_conn.set_trace_callback(attempt_competing_repair)
            real_connect = sqlite3.connect
            primary_opened = False

            def connect(path, *args, **kwargs):
                nonlocal primary_opened
                if str(path) == db_path and not primary_opened:
                    primary_opened = True
                    return check_conn
                return real_connect(path, *args, **kwargs)

            with (
                mock.patch(
                    "config.sqlite_integrity.sqlite3.connect",
                    side_effect=connect,
                ),
                mock.patch("sys.stderr"),
            ):
                check_database_integrity(db_path)

            self.assertEqual(competing_result, ["database is locked"])
            competing_conn.close()

    def test_repair_stays_below_sqlite_variable_limit(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "db.sqlite3")
            setup = sqlite3.connect(db_path)
            setup.executescript(
                """
                CREATE TABLE app_album (id INTEGER PRIMARY KEY);
                CREATE TABLE app_artist (id INTEGER PRIMARY KEY);
                CREATE TABLE app_albumartist (
                    id INTEGER PRIMARY KEY,
                    album_id INTEGER NOT NULL REFERENCES app_album(id),
                    artist_id INTEGER NOT NULL REFERENCES app_artist(id)
                );
                INSERT INTO app_artist VALUES (12);
                """
            )
            setup.executemany(
                "INSERT INTO app_albumartist VALUES (?, ?, 12)",
                ((row_id, row_id) for row_id in range(1, 7)),
            )
            setup.commit()
            setup.close()

            check_conn = sqlite3.connect(db_path)
            check_conn.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 5)
            real_connect = sqlite3.connect
            primary_opened = False

            def connect(path, *args, **kwargs):
                nonlocal primary_opened
                if str(path) == db_path and not primary_opened:
                    primary_opened = True
                    return check_conn
                return real_connect(path, *args, **kwargs)

            with (
                mock.patch(
                    "config.sqlite_integrity.sqlite3.connect",
                    side_effect=connect,
                ),
                mock.patch("sys.stderr"),
            ):
                check_database_integrity(db_path)

            verify = sqlite3.connect(db_path)
            self.assertEqual(
                verify.execute("SELECT COUNT(*) FROM app_albumartist").fetchone()[0],
                0,
            )
            verify.close()

    def test_busy_database_reports_lock_action(self):
        error = sqlite3.OperationalError("database is locked")
        error.sqlite_errorcode = sqlite3.SQLITE_BUSY

        with (
            mock.patch("sqlite3.connect", side_effect=error),
            self.assertRaises(SystemExit) as ctx,
            mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
        ):
            check_database_integrity(self.unused_path())

        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("Stop other Floppy processes", stderr.getvalue())
        self.assertNotIn("corrupt", stderr.getvalue())

    def test_healthy_database_passes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "db.sqlite3")
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE t (id INTEGER)")
            conn.commit()
            conn.close()

            check_database_integrity(db_path)

    def test_non_ok_result_without_exception_exits(self):
        fake_conn = mock.MagicMock()
        fake_conn.execute.return_value.fetchone.return_value = (
            "*** in database main ***\ncorruption found",
        )

        with (
            mock.patch("sqlite3.connect", return_value=fake_conn),
            self.assertRaises(SystemExit) as ctx,
            mock.patch("sys.stderr"),
        ):
            check_database_integrity(self.unused_path())

        self.assertEqual(ctx.exception.code, 1)
        fake_conn.close.assert_called_once()

    def test_missing_result_treated_as_failure(self):
        fake_conn = mock.MagicMock()
        fake_conn.execute.return_value.fetchone.return_value = None

        with (
            mock.patch("sqlite3.connect", return_value=fake_conn),
            self.assertRaises(SystemExit) as ctx,
            mock.patch("sys.stderr"),
        ):
            check_database_integrity(self.unused_path())

        self.assertEqual(ctx.exception.code, 1)
        fake_conn.close.assert_called_once()

    def test_database_error_still_handled(self):
        with (
            mock.patch("sqlite3.connect", side_effect=sqlite3.DatabaseError("bad")),
            self.assertRaises(SystemExit) as ctx,
            mock.patch("sys.stderr"),
        ):
            check_database_integrity(self.unused_path())

        self.assertEqual(ctx.exception.code, 1)

    def test_connection_closed_on_ok_path(self):
        fake_conn = mock.MagicMock()
        fake_conn.execute.return_value.fetchone.return_value = ("ok",)

        with mock.patch("sqlite3.connect", return_value=fake_conn):
            check_database_integrity(self.unused_path())

        fake_conn.close.assert_called_once()

    def test_entrypoint_bounds_integrity_check_without_background_polling(self):
        script = ENTRYPOINT.read_text()
        check = (
            'timeout "$integrity_timeout" python -c '
            "'from config.sqlite_integrity import "
            "check_database_integrity; import sys; "
            'check_database_integrity(sys.argv[1])\' "$DB_FILE"'
        )

        self.assertIn(check, script)
        # The bound and the message it reports must come from one definition.
        self.assertIn("integrity_timeout=600", script)
        self.assertIn('"$DB_FILE" &', script)
        self.assertNotIn("kill -0", script)
        self.assertNotIn("/proc/", script)
        self.assertNotIn("Still checking SQLite integrity", script)
        launch = script.index(check)
        cleanup_trap = script.index(
            "trap 'kill \"$integrity_pid\" 2>/dev/null || :; "
            "wait \"$integrity_pid\" 2>/dev/null || :; exit 0' TERM INT"
        )
        wait = script.index('wait "$integrity_pid"', launch)
        reset_trap = script.index("trap - TERM INT", wait)
        self.assertLess(cleanup_trap, launch)
        self.assertLess(launch, wait)
        self.assertLess(wait, reset_trap)
        timeout_case = script.index("124|143)")
        failure_case = script.index("*)", timeout_case)
        self.assertIn(
            "exceeded its ${integrity_timeout}s timeout",
            script[timeout_case:failure_case],
        )
        self.assertIn("integrity check failed", script[failure_case:])
        self.assertIn(
            "trap 'kill \"$parking_pid\" 2>/dev/null || :; "
            "wait \"$parking_pid\" 2>/dev/null || :; exit 0' TERM INT",
            script,
        )
        self.assertIn("sleep 86400 &", script)
        self.assertIn("parking_pid=$!", script)
        self.assertIn('wait "$parking_pid" || :', script)
        self.assertNotIn("tail -f /dev/null", script)

    def test_the_report_survives_a_failure_to_name_the_titles(self):
        """The report is the only way out. Nothing may suppress it."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_orphan_database(tmp_dir, rows=3)

            def raise_damaged(_conn):
                message = "database disk image is malformed"
                raise sqlite3.DatabaseError(message)

            with (
                mock.patch.object(
                    sqlite_integrity,
                    "_describe_affected",
                    raise_damaged,
                ),
                self.assertRaises(SystemExit) as ctx,
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
            ):
                check_database_integrity(db_path)

            self.assertEqual(ctx.exception.code, 1)
            output = stderr.getvalue()
            self.assertIn("Could not name the affected entries", output)
            # The operator still gets the report and the way out of the incident.
            report = self.read_incident_report(db_path)
            self.assertEqual(report["status"], "blocked")
            self.assertIn(f"accept:{report['incident_token']}", output)
            self.assertEqual(report["affected"], [])

    def test_default_auto_repair_removes_orphans_and_boots(self):
        """When auto-repair is enabled (default), startup cleans safe orphans and continues."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_orphan_database(tmp_dir, rows=5)

            with (
                mock.patch.dict(os.environ, {"FLOPPY_SQLITE_AUTO_REPAIR": "true"}),
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
            ):
                check_database_integrity(db_path)

            output = stderr.getvalue()
            self.assertIn("Auto-repaired 5 orphaned child row(s)", output)

            conn = sqlite3.connect(db_path)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM child").fetchone()[0], 0)
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            conn.close()

            report = self.read_incident_report(db_path)
            self.assertEqual(report["status"], "resolved")
            self.assertEqual(report["resolution"], "auto-repair")
            self.assertEqual(report["deleted_rows"], 5)

            backup_path = Path(report["backup_path"])
            self.assertTrue(backup_path.is_file())
            backup = sqlite3.connect(backup_path)
            self.assertEqual(backup.execute("SELECT COUNT(*) FROM child").fetchone()[0], 5)
            backup.close()

    def test_auto_repair_handles_multiple_arbitrary_tables(self):
        """Auto-repair cleans multiple damaged child tables atomically."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "db.sqlite3")
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                PRAGMA foreign_keys=ON;
                CREATE TABLE p1 (id INTEGER PRIMARY KEY);
                CREATE TABLE p2 (id INTEGER PRIMARY KEY);
                CREATE TABLE c1 (id INTEGER PRIMARY KEY, p1_id INTEGER REFERENCES p1(id));
                CREATE TABLE c2 (id INTEGER PRIMARY KEY, p2_id INTEGER REFERENCES p2(id));
                INSERT INTO p1 VALUES (10);
                INSERT INTO p2 VALUES (20);
                INSERT INTO c1 VALUES (1, 10);
                INSERT INTO c2 VALUES (2, 20);
                """
            )
            conn.commit()
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("DELETE FROM p1 WHERE id = 10")
            conn.execute("DELETE FROM p2 WHERE id = 20")
            conn.commit()
            conn.close()

            with (
                mock.patch.dict(os.environ, {"FLOPPY_SQLITE_AUTO_REPAIR": "true"}),
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
            ):
                check_database_integrity(db_path)

            output = stderr.getvalue()
            self.assertIn("Auto-repaired 2 orphaned child row(s)", output)

            conn = sqlite3.connect(db_path)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM c1").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM c2").fetchone()[0], 0)
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            conn.close()

    def test_prune_recovery_backups_bounds_retention(self):
        """_prune_recovery_backups keeps only max_keep newest files."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            recovery_dir = Path(tmp_dir) / "sqlite-recovery"
            recovery_dir.mkdir()
            for i in range(15):
                file_path = recovery_dir / f"db-backup-{i:02d}.sqlite3"
                file_path.write_text("backup")
                # Set distinct mtimes
                os.utime(file_path, (1000 + i * 10, 1000 + i * 10))

            sqlite_integrity._prune_recovery_backups(recovery_dir, max_keep=10)

            remaining = sorted(p.name for p in recovery_dir.glob("*.sqlite3"))
            self.assertEqual(len(remaining), 10)
            # The 5 oldest (00 to 04) must have been pruned
            self.assertNotIn("db-backup-00.sqlite3", remaining)
            self.assertNotIn("db-backup-04.sqlite3", remaining)
            self.assertIn("db-backup-14.sqlite3", remaining)
            self.assertIn("db-backup-05.sqlite3", remaining)

    def test_repeated_repairs_do_not_grow_the_recovery_folder(self):
        """Retention must run during a repair, not only when called by hand."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            recovery_dir = Path(tmp_dir) / "sqlite-recovery"
            for _ in range(13):
                Path(tmp_dir, "db.sqlite3").unlink(missing_ok=True)
                db_path = self.create_orphan_database(tmp_dir, rows=1)
                with (
                    mock.patch.dict(os.environ, {"FLOPPY_SQLITE_AUTO_REPAIR": "true"}),
                    mock.patch("sys.stderr", new_callable=io.StringIO),
                ):
                    check_database_integrity(db_path)

            self.assertLessEqual(len(list(recovery_dir.glob("*.sqlite3"))), 10)

    def test_a_damaged_file_clears_a_choice_no_code_path_can_apply(self):
        """A choice removes rows. A damaged file has no rows to remove.

        The entrypoint parks only while no choice is on disk. A choice left by
        a repair that cannot run would keep the boot loop turning forever.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "db.sqlite3")
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
            conn.commit()
            conn.close()
            raw = bytearray(Path(db_path).read_bytes())
            raw[100:400] = b"\x00" * 300
            Path(db_path).write_bytes(bytes(raw))

            decision = Path(f"{db_path}.integrity.decision")
            decision.write_text('{"action":"quarantine","fingerprint":"old"}')

            with (
                mock.patch("sys.stderr", new_callable=io.StringIO),
                self.assertRaises(SystemExit) as ctx,
            ):
                check_database_integrity(db_path)

            self.assertEqual(ctx.exception.code, 1)
            self.assertFalse(decision.exists())
            self.assertEqual(self.read_incident_report(db_path)["status"], "corrupt")


