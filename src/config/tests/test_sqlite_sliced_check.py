"""The background verifier is sliced, resumable and bounded per day."""

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from config import sqlite_integrity as integrity
from config import sqlite_sliced_check as sliced


class SlicedCheckTests(TestCase):
    def setUp(self):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(directory, True))
        self.database = str(directory / "db.sqlite3")
        with sqlite3.connect(self.database) as db:
            db.executescript(
                "CREATE TABLE parent(id INTEGER PRIMARY KEY);"
                "CREATE TABLE child(id INTEGER PRIMARY KEY, "
                "parent_id INTEGER REFERENCES parent(id), note TEXT);"
                "INSERT INTO parent VALUES (1);"
            )
            db.executemany(
                "INSERT INTO child VALUES (?, 1, ?)",
                [(i, "x" * 6000) for i in range(1, 400)],
            )

    def progress(self):
        return json.loads(
            Path(f"{self.database}.verification.progress.json").read_text()
        )

    def test_clean_database_completes_and_reports_verified_through(self):
        state = sliced.run_slice(self.database)
        self.assertEqual(state["status"], "ok")
        self.assertEqual(state["unverified_units"], [])
        self.assertTrue(state["verified_through"])
        self.assertEqual(
            sliced.run_slice(self.database)["status"], "ok"
        )  # fresh: no work

    def test_image_change_does_not_restart_verification(self):
        sliced.run_slice(self.database)
        with patch.dict("os.environ", {"COMMIT_SHA": "another-image"}):
            with patch.object(sliced, "_check_table") as check:
                sliced.run_slice(self.database)
        check.assert_not_called()

    def test_expired_slice_resumes_without_redoing_finished_units(self):
        with patch.object(sliced, "SLICE_SECONDS", 0.0001):
            first = sliced.run_slice(self.database)
        self.assertEqual(first["status"], "partial")
        done = {n for n, u in first["units"].items() if u.get("verified_at")}
        with patch.object(sliced, "_scan_pages", wraps=sliced._scan_pages) as pages:
            final = sliced.run_slice(self.database)
        self.assertEqual(final["status"], "ok")
        if sliced._PAGES in done:
            pages.assert_not_called()

    def test_deep_check_over_budget_is_listed_not_blocking(self):
        with patch.object(sliced, "UNIT_SECONDS", 0.0):
            state = sliced.run_slice(self.database)
        self.assertIn(state["status"], {"ok", "partial"})
        self.assertFalse(state["units"]["child"].get("fk_incomplete"))

    def test_daily_budget_caps_total_work(self):
        with patch.object(sliced, "DAILY_BUDGET_SECONDS", 0.0):
            state = sliced.run_slice(self.database)
        self.assertEqual(state["status"], "waiting-budget")

    def test_damaged_overflow_chain_is_found_by_the_sweep(self):
        pages = sqlite3.connect(self.database)
        overflow = pages.execute(
            "SELECT pageno FROM dbstat WHERE pagetype='overflow' LIMIT 1"
        ).fetchone()[0]
        pages.close()
        with Path(self.database).open("r+b") as handle:
            handle.seek(4096 * (overflow - 1))
            handle.write(b"\xff" * 16)
        with patch.object(sliced, "DEEP_SECONDS", 10**12):  # sweep alone
            state = sliced.run_slice(self.database)
        self.assertEqual(state["status"], "failed")
        self.assertEqual(
            integrity._read_incident_report(self.database)["status"], "corrupt"
        )

    def test_damaged_page_publishes_a_corruption_incident(self):
        with Path(self.database).open("r+b") as handle:
            handle.seek(4096 * 3)
            handle.write(b"\xff" * 64)
        state = sliced.run_slice(self.database)
        self.assertEqual(state["status"], "failed")
        report = integrity._read_incident_report(self.database)
        self.assertEqual(report["status"], "corrupt")

    def test_foreign_key_conflict_blocks_without_touching_rows(self):
        with sqlite3.connect(self.database) as db:
            db.execute("INSERT INTO child VALUES (9999, 77, 'orphan')")
        state = sliced.run_slice(self.database)
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(
            integrity._read_incident_report(self.database)["status"], "blocked"
        )
        with sqlite3.connect(self.database) as db:
            self.assertEqual(
                db.execute("SELECT count(*) FROM child").fetchone()[0], 400
            )

    def test_replaced_database_file_discards_old_progress(self):
        sliced.run_slice(self.database)
        Path(self.database).rename(f"{self.database}.old")
        with sqlite3.connect(self.database) as db:
            db.execute("CREATE TABLE t(id INTEGER)")
        state = sliced.run_slice(self.database)
        self.assertEqual(set(state["units"]), {sliced._PAGES, "t"})

    def test_requested_deferred_quick_check_runs_then_clears(self):
        sliced.run_slice(self.database)
        sliced.request_deferred_quick_check(self.database, reason="test")
        self.assertIn("deferred_quick_check", self.progress())
        state = sliced.run_slice(self.database)
        self.assertNotIn("deferred_quick_check", state)
        tables = [n for n in state["units"] if n != sliced._PAGES]
        self.assertTrue(all(state["units"][n].get("deep_at") for n in tables))

    def test_deferred_quick_check_failure_publishes_an_incident(self):
        sliced.run_slice(self.database)
        sliced.request_deferred_quick_check(self.database, reason="test")
        real_connect = sqlite3.connect

        class Damaged(sqlite3.Connection):
            def execute(self, sql, *args):
                if sql.startswith("PRAGMA quick_check("):
                    return real_connect(":memory:").execute("SELECT 'bad record'")
                return super().execute(sql, *args)

        def connect(*args, **kwargs):
            return real_connect(*args, factory=Damaged, **kwargs)

        with patch.object(sliced.sqlite3, "connect", connect):
            state = sliced.run_slice(self.database)
        self.assertEqual(state["status"], "failed")
        self.assertEqual(
            integrity._read_incident_report(self.database)["status"], "corrupt"
        )
