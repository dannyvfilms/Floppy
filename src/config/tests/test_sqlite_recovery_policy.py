import json
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from config import sqlite_integrity, sqlite_recovery_policy


class SqliteRecoveryPolicyTests(SimpleTestCase):
    """A keep-rows decision must not become a permanent integrity bypass."""

    @staticmethod
    def _incident():
        return {
            "affected": [{"count": 3, "season": None, "title": "Affected Show"}],
            "can_quarantine": True,
            "fingerprint": "a" * 64,
            "groups": [
                {
                    "count": 3,
                    "foreign_key_id": 0,
                    "parent": "parent",
                    "table": "child",
                },
            ],
            "other_titles": 2,
            "other_titles_count": 4,
            "samples": [],
            "total_conflicts": 3,
            "unidentified": 1,
            "unsafe_reasons": [],
        }

    def test_previous_acceptance_reopens_with_new_incident_token(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "db.sqlite3")
            Path(db_path).touch()
            sqlite_integrity._write_incident_report(
                db_path,
                self._incident(),
                status="accepted",
                resolution="accept",
            )

            reopened = sqlite_recovery_policy.reopen_previous_acceptance(db_path)

            self.assertTrue(reopened)
            report = json.loads(Path(f"{db_path}.integrity.json").read_text())
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["resolution"], "accept-expired")
            self.assertEqual(report["fingerprint"], "a" * 64)
            self.assertEqual(len(report["incident_token"]), 32)
            self.assertIn("accept", report["actions"])
            self.assertIn("quarantine", report["actions"])
            self.assertEqual(
                report["affected"],
                [{"count": 3, "season": None, "title": "Affected Show"}],
            )
            self.assertEqual(report["affected_other_titles"], 2)
            self.assertEqual(report["affected_other_titles_count"], 4)
            self.assertEqual(report["affected_unidentified"], 1)

    def test_nonaccepted_incident_is_left_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "db.sqlite3")
            Path(db_path).touch()
            sqlite_integrity._write_incident_report(
                db_path,
                self._incident(),
                status="blocked",
                incident_token="b" * 32,
            )
            report_path = Path(f"{db_path}.integrity.json")
            before = report_path.read_text()

            reopened = sqlite_recovery_policy.reopen_previous_acceptance(db_path)

            self.assertFalse(reopened)
            self.assertEqual(report_path.read_text(), before)
