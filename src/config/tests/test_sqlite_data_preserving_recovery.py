import json
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from config import sqlite_recovery_server
from config.sqlite_recovery_policy import check_database_for_startup


class SqliteDataPreservingRecoveryTests(SimpleTestCase):
    """Recovery must preserve rows when only optional relationships are broken."""

    def _create_mixed_music_incident(self, tmp_dir):
        db_path = str(Path(tmp_dir) / "db.sqlite3")
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            PRAGMA foreign_keys=OFF;
            CREATE TABLE app_item (
                id INTEGER PRIMARY KEY,
                title TEXT,
                season_number INTEGER
            );
            CREATE TABLE app_album (id INTEGER PRIMARY KEY);
            CREATE TABLE app_track (id INTEGER PRIMARY KEY);
            CREATE TABLE app_artist (id INTEGER PRIMARY KEY);
            CREATE TABLE app_music (
                id INTEGER PRIMARY KEY,
                item_id INTEGER NOT NULL REFERENCES app_item(id),
                album_id INTEGER REFERENCES app_album(id),
                track_id INTEGER REFERENCES app_track(id)
            );
            CREATE TABLE app_albumartist (
                id INTEGER PRIMARY KEY,
                album_id INTEGER NOT NULL REFERENCES app_album(id),
                artist_id INTEGER NOT NULL REFERENCES app_artist(id)
            );
            CREATE TABLE app_albumtracker (
                id INTEGER PRIMARY KEY,
                album_id INTEGER NOT NULL REFERENCES app_album(id),
                notes TEXT
            );
            INSERT INTO app_item VALUES (1, 'Preserve this music entry', NULL);
            INSERT INTO app_artist VALUES (30);
            """
        )
        # Use explicit column lists so this fixture stays readable if the table
        # layout above changes during review.
        conn.execute(
            "INSERT INTO app_music (id, item_id, album_id, track_id) "
            "VALUES (1, 1, 10, 20)"
        )
        conn.execute(
            "INSERT INTO app_albumartist (id, album_id, artist_id) VALUES (1, 10, 30)"
        )
        conn.execute(
            "INSERT INTO app_albumtracker (id, album_id, notes) "
            "VALUES (1, 10, 'keep my album tracking state')"
        )
        conn.commit()
        conn.close()
        return db_path

    @staticmethod
    def _read_report(db_path):
        return json.loads(Path(f"{db_path}.integrity.json").read_text())

    @staticmethod
    def _assert_tracking_rows_unchanged(db_path):
        conn = sqlite3.connect(db_path)
        try:
            assert conn.execute("SELECT COUNT(*) FROM app_music").fetchone()[0] == 1
            assert (
                conn.execute("SELECT COUNT(*) FROM app_albumtracker").fetchone()[0]
                == 1
            )
        finally:
            conn.close()

    def test_mixed_music_damage_preserves_tracking_until_explicit_repair(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self._create_mixed_music_incident(tmp_dir)
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "FLOPPY_SQLITE_AUTO_REPAIR": "true",
                        "FLOPPY_SQLITE_CONFLICT_ACTION": "halt",
                    },
                ),
                self.assertRaises(SystemExit) as blocked,
                mock.patch("sys.stderr"),
            ):
                check_database_for_startup(db_path)

            self.assertEqual(blocked.exception.code, 1)
            conn = sqlite3.connect(db_path)
            self.assertEqual(
                conn.execute(
                    "SELECT album_id, track_id FROM app_music WHERE id = 1"
                ).fetchone(),
                (None, None),
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM app_albumartist").fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT notes FROM app_albumtracker WHERE id = 1"
                ).fetchone()[0],
                "keep my album tracking state",
            )
            remaining = conn.execute("PRAGMA foreign_key_check").fetchall()
            self.assertEqual(len(remaining), 1)
            self.assertEqual(remaining[0][0], "app_albumtracker")
            conn.close()

            report = self._read_report(db_path)
            self.assertEqual(report["status"], "blocked")
            self.assertNotIn("accept", report["actions"])
            self.assertIn("quarantine", report["actions"])
            self.assertEqual(report["repair_plan"]["safe_relationships"], 0)
            self.assertEqual(report["repair_plan"]["required_relationships"], 1)
            self.assertEqual(report["safe_repair"]["references_cleared"], 2)
            self.assertEqual(report["safe_repair"]["relationship_rows_removed"], 1)
            self.assertTrue(Path(report["safe_repair"]["backup_path"]).is_file())

            page = sqlite_recovery_server.render_page(report, interactive=True)
            self.assertNotIn("action='/accept'", page)
            self.assertIn("broken relationship", page)
            self.assertIn("One row can have more than one broken relationship", page)
            self.assertIn("Repair relationships and start Floppy", page)

            Path(f"{db_path}.integrity.decision").write_text(
                json.dumps(
                    {
                        "action": "quarantine",
                        "fingerprint": report["fingerprint"],
                        "token": report["incident_token"],
                    }
                )
            )
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "FLOPPY_SQLITE_AUTO_REPAIR": "true",
                        "FLOPPY_SQLITE_CONFLICT_ACTION": "halt",
                    },
                ),
                mock.patch("sys.stderr"),
            ):
                check_database_for_startup(db_path)

            conn = sqlite3.connect(db_path)
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM app_music").fetchone()[0],
                1,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM app_albumtracker").fetchone()[0],
                0,
            )
            conn.close()

            resolved = self._read_report(db_path)
            self.assertEqual(resolved["status"], "resolved")
            self.assertEqual(resolved["resolution"], "operator-repair")
            self.assertEqual(resolved["repair_result"]["required_rows_removed"], 1)
            self.assertTrue(Path(resolved["backup_path"]).is_file())

    def test_legacy_accept_is_rejected_without_modifying_rows(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self._create_mixed_music_incident(tmp_dir)
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "FLOPPY_SQLITE_AUTO_REPAIR": "false",
                        "FLOPPY_SQLITE_CONFLICT_ACTION": "halt",
                    },
                ),
                self.assertRaises(SystemExit),
                mock.patch("sys.stderr"),
            ):
                check_database_for_startup(db_path)

            report = self._read_report(db_path)
            Path(f"{db_path}.integrity.decision").write_text(
                json.dumps(
                    {
                        "action": "accept",
                        "fingerprint": report["fingerprint"],
                        "token": report["incident_token"],
                    }
                )
            )
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "FLOPPY_SQLITE_AUTO_REPAIR": "false",
                        "FLOPPY_SQLITE_CONFLICT_ACTION": "halt",
                    },
                ),
                self.assertRaises(SystemExit),
                mock.patch("sys.stderr"),
            ):
                check_database_for_startup(db_path)

            self._assert_tracking_rows_unchanged(db_path)
            refreshed = self._read_report(db_path)
            self.assertNotIn("accept", refreshed["actions"])
            self.assertEqual(refreshed["resolution"], "accept-retired")

    def test_bare_headless_quarantine_is_rejected_without_modifying_rows(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self._create_mixed_music_incident(tmp_dir)
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "FLOPPY_SQLITE_AUTO_REPAIR": "false",
                        "FLOPPY_SQLITE_CONFLICT_ACTION": "halt",
                    },
                ),
                self.assertRaises(SystemExit),
                mock.patch("sys.stderr"),
            ):
                check_database_for_startup(db_path)

            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "FLOPPY_SQLITE_AUTO_REPAIR": "false",
                        "FLOPPY_SQLITE_CONFLICT_ACTION": "quarantine",
                    },
                ),
                self.assertRaises(SystemExit),
                mock.patch("sys.stderr"),
            ):
                check_database_for_startup(db_path)

            self._assert_tracking_rows_unchanged(db_path)
            self.assertTrue(self._read_report(db_path)["incident_token"])

    def test_decision_without_current_code_is_consumed_and_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self._create_mixed_music_incident(tmp_dir)
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "FLOPPY_SQLITE_AUTO_REPAIR": "false",
                        "FLOPPY_SQLITE_CONFLICT_ACTION": "halt",
                    },
                ),
                self.assertRaises(SystemExit),
                mock.patch("sys.stderr"),
            ):
                check_database_for_startup(db_path)

            report = self._read_report(db_path)
            decision_path = Path(f"{db_path}.integrity.decision")
            decision_path.write_text(
                json.dumps(
                    {
                        "action": "quarantine",
                        "fingerprint": report["fingerprint"],
                    }
                )
            )
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "FLOPPY_SQLITE_AUTO_REPAIR": "false",
                        "FLOPPY_SQLITE_CONFLICT_ACTION": "halt",
                    },
                ),
                self.assertRaises(SystemExit),
                mock.patch("sys.stderr"),
            ):
                check_database_for_startup(db_path)

            self.assertFalse(decision_path.exists())
            self._assert_tracking_rows_unchanged(db_path)
            self.assertTrue(self._read_report(db_path)["incident_token"])
