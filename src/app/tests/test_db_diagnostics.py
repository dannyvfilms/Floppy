import sqlite3
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

from django.db import OperationalError
from django.test import SimpleTestCase, override_settings

from app import db_diagnostics


class DatabaseErrorClassificationTests(SimpleTestCase):
    def test_busy_and_locked_are_machine_readable_and_retryable(self):
        for message, code, kind in (
            ("database is locked", sqlite3.SQLITE_BUSY, "busy"),
            ("database table is locked", sqlite3.SQLITE_LOCKED, "locked"),
        ):
            with self.subTest(message=message):
                error = OperationalError(message)
                error.sqlite_errorcode = code

                info = db_diagnostics.describe_database_error(error)

                self.assertIsNotNone(info)
                self.assertEqual(info.code, "DATABASE_BUSY")
                self.assertTrue(info.retryable)
                self.assertEqual(info.retry_after, 5)
                self.assertEqual(info.kind, kind)
                self.assertEqual(info.sqlite_code, code)

    def test_disk_io_is_not_reported_as_retryable_contention(self):
        error = OperationalError("disk I/O error")
        error.sqlite_errorcode = sqlite3.SQLITE_IOERR

        info = db_diagnostics.describe_database_error(error)

        self.assertIsNotNone(info)
        self.assertEqual(info.code, "DATABASE_UNAVAILABLE")
        self.assertFalse(info.retryable)
        self.assertIsNone(info.retry_after)

    def test_postgres_transaction_conflicts_are_busy(self):
        error = OperationalError("transaction conflict")
        cause = RuntimeError("postgres conflict")
        cause.sqlstate = "40001"
        error.__cause__ = cause

        info = db_diagnostics.describe_database_error(error)

        self.assertIsNotNone(info)
        self.assertEqual(info.code, "DATABASE_BUSY")
        self.assertTrue(info.retryable)

    def test_non_database_errors_are_not_reclassified(self):
        self.assertIsNone(db_diagnostics.describe_database_error(ValueError("bad input")))
        self.assertIsNone(
            db_diagnostics.describe_database_error(
                OperationalError("server closed the connection unexpectedly"),
            ),
        )

    @override_settings(
        USING_SQLITE_DATABASE=True,
        SQLITE_JOURNAL_MODE="WAL",
        SQLITE_BUSY_TIMEOUT_SECONDS=30,
    )
    def test_contention_log_carries_caller_wait_and_no_owner_guess(self):
        error = OperationalError("database is locked")
        error.sqlite_errorcode = sqlite3.SQLITE_BUSY
        request = SimpleNamespace(method="POST", path="/api/v1/media/game")

        with self.assertLogs("app.db_diagnostics", level="WARNING") as logs:
            info = db_diagnostics.report_database_error(
                error,
                request=request,
                operation="api",
                wait_ms=30002.4,
            )

        self.assertIsNotNone(info)
        line = logs.output[0]
        self.assertIn("db_contention", line)
        self.assertIn("code=DATABASE_BUSY", line)
        self.assertIn("wait_ms=30002.4", line)
        self.assertIn("method=POST", line)
        self.assertIn("path=/api/v1/media/game", line)
        self.assertIn(f"sqlite_code={sqlite3.SQLITE_BUSY}", line)
        self.assertIn("owner=unknown", line)
        self.assertIn("journal_mode=WAL", line)
        self.assertIn("busy_timeout_ms=30000", line)
        self.assertNotIn("SELECT", line)
        self.assertNotIn("secret", line)


class SQLiteTwoConnectionContentionTests(SimpleTestCase):
    """A deterministic reproduction of the writer-wait incident shape."""

    def test_two_connections_report_the_wait_and_the_unknown_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "contention.sqlite3")
            holder = sqlite3.connect(path)
            waiter = None
            try:
                holder.execute("PRAGMA journal_mode=WAL")
                holder.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, value TEXT)")
                holder.commit()
                holder.execute("BEGIN IMMEDIATE")
                holder.execute("INSERT INTO t (value) VALUES ('held')")

                waiter = sqlite3.connect(path, timeout=0.2)
                waiter.execute("PRAGMA busy_timeout=200")
                started = time.perf_counter()
                with self.assertRaises(sqlite3.OperationalError) as caught:
                    waiter.execute("INSERT INTO t (value) VALUES ('waiting')")
                wait_ms = (time.perf_counter() - started) * 1000
            finally:
                if waiter is not None:
                    waiter.close()
                holder.rollback()
                holder.close()

            error = OperationalError(str(caught.exception))
            error.sqlite_errorcode = getattr(
                caught.exception,
                "sqlite_errorcode",
                sqlite3.SQLITE_BUSY,
            )
            request = SimpleNamespace(method="GET", path="/api/v1/media/game/1")

            with self.assertLogs("app.db_diagnostics", level="WARNING") as logs:
                info = db_diagnostics.report_database_error(
                    error,
                    request=request,
                    operation="query",
                    wait_ms=wait_ms,
                )

        self.assertIsNotNone(info)
        self.assertEqual(info.code, "DATABASE_BUSY")
        self.assertGreater(info.sqlite_code or 0, 0)
        self.assertIn("wait_ms=", logs.output[0])
        self.assertIn("owner=unknown", logs.output[0])
        self.assertIn("path=/api/v1/media/game/1", logs.output[0])


class TransactionDurationTests(SimpleTestCase):
    @override_settings(PERF_LOG_SLOW_TRANSACTION_MS=0)
    def test_slow_transaction_logs_mode_outcome_and_caller(self):
        class Connection:
            alias = "diagnostics_test"
            vendor = "sqlite"

        context = {"connection": Connection()}
        request = SimpleNamespace(method="POST", path="/api/v1/media/game")

        with db_diagnostics.bind_request(request):
            db_diagnostics.track_query(
                lambda *args: None, "BEGIN IMMEDIATE", [], False, context
            )
            with self.assertLogs("app.db_diagnostics", level="INFO") as logs:
                db_diagnostics.track_query(
                    lambda *args: None, "COMMIT", [], False, context
                )

        line = logs.output[0]
        self.assertIn("slow_transaction", line)
        self.assertIn("alias=diagnostics_test", line)
        self.assertIn("mode=write", line)
        self.assertIn("outcome=commit", line)
        self.assertIn("method=POST", line)
        self.assertIn("path=/api/v1/media/game", line)
        self.assertIn("started_at=", line)

    @override_settings(PERF_LOG_SLOW_TRANSACTION_MS=0)
    def test_rollback_is_reported_as_rollback(self):
        class Connection:
            alias = "diagnostics_rollback"
            vendor = "sqlite"

        context = {"connection": Connection()}
        db_diagnostics.track_query(
            lambda *args: None, "BEGIN IMMEDIATE", [], False, context
        )

        with self.assertLogs("app.db_diagnostics", level="INFO") as logs:
            db_diagnostics.track_query(
                lambda *args: None, "ROLLBACK", [], False, context
            )

        self.assertIn("outcome=rollback", logs.output[0])
