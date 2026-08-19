"""Tests for the SQLite startup integrity guard (issue #593)."""

import io
import sqlite3
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from config.sqlite_integrity import check_database_integrity

ENTRYPOINT = Path(__file__).resolve().parents[3] / "entrypoint.sh"


class SqliteIntegrityTests(SimpleTestCase):
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

    def test_unknown_foreign_key_violation_stops_startup(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "db.sqlite3")
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                PRAGMA foreign_keys=ON;
                CREATE TABLE parent (id INTEGER PRIMARY KEY);
                CREATE TABLE child (
                    id INTEGER PRIMARY KEY,
                    parent_id INTEGER NOT NULL REFERENCES parent(id)
                );
                INSERT INTO parent VALUES (1);
                """
            )
            conn.executemany(
                "INSERT INTO child VALUES (?, 1)",
                ((row_id,) for row_id in range(1, 13)),
            )
            conn.commit()
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("DELETE FROM parent WHERE id = 1")
            conn.commit()
            conn.close()

            with (
                self.assertRaises(SystemExit) as ctx,
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
            ):
                check_database_integrity(db_path)

            self.assertEqual(ctx.exception.code, 1)
            output = stderr.getvalue()
            self.assertEqual(output.count("foreign key check failed"), 12)
            self.assertIn("table='child', row=12, parent='parent'", output)
            self.assertIn("Back up the SQLite file", output)
            conn = sqlite3.connect(db_path)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM child").fetchone()[0], 12
            )
            conn.close()

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
                if not statement.startswith("DELETE FROM app_albumartist"):
                    return
                try:
                    competing_conn.execute("INSERT INTO app_album VALUES (345)")
                    competing_conn.commit()
                except sqlite3.OperationalError as error:
                    competing_result.append(str(error))

            check_conn.set_trace_callback(attempt_competing_repair)
            with (
                mock.patch(
                    "config.sqlite_integrity.sqlite3.connect",
                    return_value=check_conn,
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
            with (
                mock.patch(
                    "config.sqlite_integrity.sqlite3.connect",
                    return_value=check_conn,
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
            check_database_integrity("irrelevant.sqlite3")

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
            check_database_integrity("irrelevant.sqlite3")

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
            check_database_integrity("irrelevant.sqlite3")

        self.assertEqual(ctx.exception.code, 1)
        fake_conn.close.assert_called_once()

    def test_database_error_still_handled(self):
        with (
            mock.patch("sqlite3.connect", side_effect=sqlite3.DatabaseError("bad")),
            self.assertRaises(SystemExit) as ctx,
            mock.patch("sys.stderr"),
        ):
            check_database_integrity("irrelevant.sqlite3")

        self.assertEqual(ctx.exception.code, 1)

    def test_connection_closed_on_ok_path(self):
        fake_conn = mock.MagicMock()
        fake_conn.execute.return_value.fetchone.return_value = ("ok",)

        with mock.patch("sqlite3.connect", return_value=fake_conn):
            check_database_integrity("irrelevant.sqlite3")

        fake_conn.close.assert_called_once()

    def test_entrypoint_stops_when_integrity_check_times_out(self):
        script = ENTRYPOINT.read_text()
        timeout = "integrity_timed_out=1"
        stop = (
            'if [ "$integrity_timed_out" -eq 1 ] || [ "$integrity_status" -ne 0 ]; then'
        )

        self.assertLess(script.index(timeout), script.index(stop))
        self.assertIn("exit 1", script[script.index(stop) : script.index(stop) + 150])
