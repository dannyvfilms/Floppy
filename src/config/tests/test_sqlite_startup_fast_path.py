"""Tests for how the startup database check stays fast and fair.

Three things keep a healthy database from being stopped at startup: the scan
reads the file sequentially first, a recent full check lets the next start skip
the scan, and the watchdog stops only a scan that has stopped making progress.
"""

import contextlib
import io
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock, skipUnless

from django.test import SimpleTestCase

from config import sqlite_integrity, sqlite_recovery_policy, sqlite_startup_watchdog
from config.sqlite_recovery_policy import check_database_for_startup

requires_linux = skipUnless(
    sys.platform.startswith("linux"),
    "needs /proc (Linux-only, like the container)",
)


def _create_database(tmp_dir: str) -> str:
    db_path = str(Path(tmp_dir) / "db.sqlite3")
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE parent (id INTEGER PRIMARY KEY);
        CREATE TABLE child (
            id INTEGER PRIMARY KEY,
            parent_id INTEGER NOT NULL REFERENCES parent(id)
        );
        INSERT INTO parent (id) VALUES (1);
        INSERT INTO child (parent_id) VALUES (1);
        """
    )
    conn.close()
    return db_path


class _Base(SimpleTestCase):
    def setUp(self):
        super().setUp()
        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp_dir, ignore_errors=True)
        self.db_path = _create_database(tmp_dir)
        env = mock.patch.dict(
            os.environ,
            {"COMMIT_SHA": "abc1234", "FLOPPY_SQLITE_AUTO_REPAIR": "false"},
        )
        env.start()
        self.addCleanup(env.stop)

    def run_startup_check(self) -> str:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            check_database_for_startup(self.db_path)
        return stderr.getvalue()

    def recent_verification(self):
        return sqlite_integrity.recent_verification(
            self.db_path, sqlite_integrity.read_startup_status(self.db_path)
        )

    def rewrite_record(self, **changes):
        path = sqlite_integrity._verified_path(self.db_path)
        record = json.loads(path.read_text())
        record.update(changes)
        path.write_text(json.dumps(record))


class RecentVerificationTests(_Base):
    def test_a_passing_startup_check_lets_the_next_start_skip_the_scan(self):
        first = self.run_startup_check()
        self.assertIn(
            "Running the full storage check: no verification on record", first
        )
        self.assertIn("phase=quick_check seconds=", first)

        with mock.patch.object(
            sqlite_recovery_policy,
            "_scan_and_publish_block",
            side_effect=AssertionError("the full scan must not run"),
        ):
            second = self.run_startup_check()

        self.assertIn("Skipped the full storage check: verified by startup", second)
        status = sqlite_integrity.read_startup_status(self.db_path)
        self.assertEqual((status["status"], status["phase"]), ("ok", "open_check"))

    def test_each_reason_for_doubt_forces_the_full_scan(self):
        self.run_startup_check()
        record, _reason = self.recent_verification()
        self.assertIsNotNone(record)

        stale = (datetime.now(UTC) - timedelta(hours=49)).isoformat()
        future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        cases = {
            "old": lambda: self.rewrite_record(verified_at=stale),
            "no usable time": lambda: self.rewrite_record(verified_at=future),
            "image changed": lambda: self.rewrite_record(commit_sha="other"),
            "replaced": lambda: self.rewrite_record(inode=-1),
        }
        for expected, make_doubt in cases.items():
            with self.subTest(expected):
                self.run_startup_check()
                make_doubt()
                record, reason = self.recent_verification()
                self.assertIsNone(record)
                self.assertIn(expected, reason)

    def test_a_build_without_a_commit_never_skips(self):
        self.run_startup_check()
        with mock.patch.dict(os.environ, {"COMMIT_SHA": ""}):
            record, reason = self.recent_verification()
        self.assertIsNone(record)
        self.assertIn("image changed", reason)

    def test_a_placeholder_commit_never_skips(self):
        # Local image builds bake COMMIT_SHA=unknown, so two different local
        # builds must not look like the same image.
        with mock.patch.dict(os.environ, {"COMMIT_SHA": "unknown"}):
            self.run_startup_check()
            record, reason = self.recent_verification()
        self.assertIsNone(record)
        self.assertIn("image changed", reason)

    def test_a_replaced_database_file_never_inherits_the_record(self):
        self.run_startup_check()
        replacement = f"{self.db_path}.restored"
        shutil.copyfile(self.db_path, replacement)
        Path(replacement).replace(self.db_path)

        record, reason = self.recent_verification()

        self.assertIsNone(record)
        self.assertIn("replaced", reason)

    def test_an_open_recovery_report_forces_the_full_scan(self):
        self.run_startup_check()
        with mock.patch.object(
            sqlite_integrity,
            "_read_incident_report",
            return_value={"status": "blocked"},
        ):
            record, reason = self.recent_verification()
        self.assertIsNone(record)
        self.assertIn("blocked", reason)

    def test_a_previous_timeout_forces_the_full_scan(self):
        self.run_startup_check()
        sqlite_integrity.write_startup_status(
            self.db_path,
            status="timeout",
            phase="quick_check",
            started_at=datetime.now(UTC).isoformat(),
            elapsed_seconds=200.0,
        )

        record, reason = self.recent_verification()

        self.assertIsNone(record)
        self.assertIn("timeout", reason)

    def test_a_failed_scan_records_nothing(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO child (parent_id) VALUES (99)")
        conn.commit()
        conn.close()

        with self.assertRaises(SystemExit):
            self.run_startup_check()

        self.assertFalse(sqlite_integrity._verified_path(self.db_path).exists())

    def test_a_file_that_cannot_be_opened_falls_through_to_the_full_scan(self):
        self.run_startup_check()
        with (
            mock.patch.object(
                sqlite_recovery_policy.sqlite3,
                "connect",
                side_effect=sqlite3.DatabaseError("file is not a database"),
            ),
            mock.patch.object(
                sqlite_recovery_policy, "_scan_and_publish_block", return_value=None
            ) as full_scan,
        ):
            output = self.run_startup_check()

        full_scan.assert_called_once()
        self.assertIn("open check failed", output)

    @requires_linux
    def test_a_structural_snapshot_does_not_vouch_for_relationships(self):
        backups = Path(self.db_path).parent / "backups"

        snapshot = sqlite_integrity.create_live_database_snapshot(
            self.db_path,
            backups,
            max_keep=2,
            timeout_seconds=5.0,
        )

        self.assertIsNotNone(snapshot)
        record, reason = self.recent_verification()
        self.assertIsNone(record)
        self.assertIn("does not verify relationships", reason)


class WarmCacheTests(_Base):
    def test_reads_the_database_and_its_wal_front_to_back(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA wal_autocheckpoint=0")
        conn.execute("INSERT INTO parent (id) VALUES (2)")
        conn.commit()
        wal = Path(f"{self.db_path}-wal")
        expected = Path(self.db_path).stat().st_size + wal.stat().st_size
        self.assertGreater(wal.stat().st_size, 0)

        reported = []
        with mock.patch.object(sqlite_integrity, "_WARM_REPORT_INTERVAL_SECONDS", 0.0):
            read_bytes, _seconds = sqlite_integrity.warm_database_cache(
                self.db_path, on_progress=reported.append
            )
        conn.close()

        self.assertEqual(read_bytes, expected)
        self.assertEqual(reported[-1], expected)

    def test_a_missing_wal_is_not_an_error(self):
        Path(f"{self.db_path}-wal").unlink(missing_ok=True)

        read_bytes, _seconds = sqlite_integrity.warm_database_cache(self.db_path)

        self.assertEqual(read_bytes, Path(self.db_path).stat().st_size)

    def test_an_unreadable_file_ends_the_warm_up_without_failing(self):
        with (
            mock.patch.object(Path, "open", side_effect=PermissionError("denied")),
            contextlib.redirect_stderr(io.StringIO()) as stderr,
        ):
            read_bytes, _seconds = sqlite_integrity.warm_database_cache(self.db_path)

        self.assertEqual(read_bytes, 0)
        self.assertIn("warm-up stopped early", stderr.getvalue())


@requires_linux
class WatchdogTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp_dir, ignore_errors=True)
        self.tmp_path = Path(tmp_dir)
        self.db_path = str(self.tmp_path / "db.sqlite3")

    def supervise(self, code: str, **bounds) -> tuple[int, str]:
        bounds = {"poll_seconds": 0.1, "heartbeat_seconds": 60.0, **bounds}
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            status = sqlite_startup_watchdog.supervise(
                self.db_path, [sys.executable, "-c", code], **bounds
            )
        return status, stderr.getvalue()

    def test_a_silent_child_is_stopped_as_stalled(self):
        started = time.monotonic()
        status, output = self.supervise(
            "import time; time.sleep(30)", stall_seconds=1.0, ceiling_seconds=60.0
        )

        self.assertEqual(status, sqlite_startup_watchdog.TIMEOUT_EXIT)
        self.assertLess(time.monotonic() - started, 15)
        recorded = sqlite_integrity.read_startup_status(self.db_path)
        self.assertEqual(recorded["status"], "timeout")
        self.assertIn("no read or CPU progress", recorded["error_message"])
        self.assertIn("no read or CPU progress", output)

    def test_a_child_that_keeps_reading_outlives_the_stall_window(self):
        data = self.tmp_path / "data.bin"
        data.write_bytes(b"x" * 65536)
        code = (
            "import time, pathlib\n"
            "end = time.monotonic() + 2.5\n"
            "while time.monotonic() < end:\n"
            f"    pathlib.Path({str(data)!r}).read_bytes()\n"
            "    time.sleep(0.05)\n"
        )

        status, _output = self.supervise(code, stall_seconds=1.0, ceiling_seconds=60.0)

        self.assertEqual(status, 0)

    def test_the_ceiling_stops_a_child_that_never_ends(self):
        status, _output = self.supervise(
            "while True: pass", stall_seconds=60.0, ceiling_seconds=1.0
        )

        self.assertEqual(status, sqlite_startup_watchdog.TIMEOUT_EXIT)
        recorded = sqlite_integrity.read_startup_status(self.db_path)
        self.assertIn("ceiling", recorded["error_message"])

    def test_a_hung_sidecar_cannot_hold_up_the_stall_decision(self):
        # The sidecar lives on the database's storage. When that storage stops
        # answering, every sidecar call blocks; the watchdog must still stop
        # the check and return.
        never = threading.Event()

        def hang(*_args, **_kwargs):
            never.wait()

        started = time.monotonic()
        with (
            mock.patch.object(sqlite_startup_watchdog, "_SIDECAR_IO_SECONDS", 0.2),
            mock.patch.object(sqlite_startup_watchdog, "read_startup_status", hang),
            mock.patch.object(sqlite_startup_watchdog, "print_startup_heartbeat", hang),
            mock.patch.object(
                sqlite_startup_watchdog, "mark_startup_status_timeout", hang
            ),
            mock.patch.object(sqlite_startup_watchdog, "_activity", return_value=None),
        ):
            status, output = self.supervise(
                "import time; time.sleep(30)",
                stall_seconds=1.0,
                ceiling_seconds=60.0,
                heartbeat_seconds=0.3,
            )
        never.set()

        self.assertEqual(status, sqlite_startup_watchdog.TIMEOUT_EXIT)
        self.assertLess(time.monotonic() - started, 15)
        self.assertIn("storage is not responding", output)

    def test_the_childs_own_exit_status_is_passed_through(self):
        status, _output = self.supervise("raise SystemExit(3)", stall_seconds=60.0)

        self.assertEqual(status, 3)

    def test_the_heartbeat_reports_what_the_process_read(self):
        _status, output = self.supervise(
            "import time; time.sleep(0.6)", stall_seconds=60.0, heartbeat_seconds=0.2
        )

        self.assertIn("SQLite integrity scan heartbeat", output)
        self.assertIn("process_read=", output)

    def test_stopping_the_watchdog_stops_the_check(self):
        pid_file = self.tmp_path / "child.pid"
        code = (
            "import os, pathlib, time\n"
            f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()))\n"
            "time.sleep(30)\n"
        )
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])}
        watchdog = subprocess.Popen(  # noqa: S603
            [
                sys.executable,
                "-m",
                "config.sqlite_startup_watchdog",
                self.db_path,
                sys.executable,
                "-c",
                code,
            ],
            env=env,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 10
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        child_pid = int(pid_file.read_text())

        watchdog.send_signal(signal.SIGTERM)

        self.assertEqual(watchdog.wait(timeout=10), 128 + signal.SIGTERM)
        with self.assertRaises(ProcessLookupError):
            os.kill(child_pid, 0)
