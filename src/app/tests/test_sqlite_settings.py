import copy
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.db import OperationalError, connection
from django.db.backends.sqlite3.base import DatabaseWrapper
from django.test import SimpleTestCase

from config import settings as project_settings


class SQLiteSettingsTests(SimpleTestCase):
    """Regression coverage for SQLite-specific runtime settings."""

    def test_configure_sqlite_connection_uses_configured_busy_timeout(self):
        """SQLite connections should honor the configured timeout value."""
        cursor = MagicMock()
        cursor.fetchone.return_value = ("wal",)
        connection = SimpleNamespace(
            vendor="sqlite",
            cursor=MagicMock(return_value=cursor),
        )

        with (
            patch.object(project_settings, "SQLITE_JOURNAL_MODE", "WAL"),
            patch.object(project_settings, "SQLITE_SYNCHRONOUS", "NORMAL"),
            patch.object(project_settings, "SQLITE_BUSY_TIMEOUT_SECONDS", 17),
        ):
            project_settings.configure_sqlite_connection(
                sender=None,
                connection=connection,
            )

        cursor.execute.assert_any_call("PRAGMA journal_mode=WAL")
        cursor.execute.assert_any_call("PRAGMA synchronous=NORMAL")
        cursor.execute.assert_any_call("PRAGMA busy_timeout=17000")
        cursor.close.assert_called_once()

    def test_configure_sqlite_connection_logs_journal_mode_mismatch(self):
        """A journal_mode that didn't actually apply must be logged loudly."""
        cursor = MagicMock()
        cursor.fetchone.return_value = ("delete",)
        connection = SimpleNamespace(
            vendor="sqlite",
            cursor=MagicMock(return_value=cursor),
        )

        with (
            patch.object(project_settings, "SQLITE_JOURNAL_MODE", "WAL"),
            patch.object(project_settings, "SQLITE_SYNCHRONOUS", "NORMAL"),
            patch.object(project_settings, "SQLITE_BUSY_TIMEOUT_SECONDS", 17),
            self.assertLogs(project_settings.__name__, level="ERROR") as logs,
        ):
            project_settings.configure_sqlite_connection(
                sender=None,
                connection=connection,
            )

        self.assertIn("journal_mode mismatch", logs.output[0])

    def test_discover_warmup_defaults_off_on_sqlite(self):
        """SQLite deployments should not auto-enable Discover warmup by default."""
        self.assertFalse(settings.DISCOVER_WARMUP_ON_STARTUP)

    def test_img_none_default_is_embedded_data_uri(self):
        """IMG_NONE should default to a self-contained data URI, not a hotlink."""
        self.assertTrue(settings.IMG_NONE.startswith("data:image/svg+xml;base64,"))
        self.assertNotIn("themoviedb.org", settings.IMG_NONE)


@skipUnless(connection.vendor == "sqlite", "SQLite lock behaviour")
class SQLiteTransactionModeTests(SimpleTestCase):
    """A read-then-write transaction must wait for a concurrent writer."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def _wrapper(self, options, *, close_on_cleanup=True):
        settings_dict = copy.deepcopy(connection.settings_dict)
        settings_dict["NAME"] = str(self.database_path)
        settings_dict["OPTIONS"] = {**options, "timeout": 5}
        wrapper = DatabaseWrapper(settings_dict, alias="lock-test")
        if close_on_cleanup:
            self.addCleanup(wrapper.close)
        return wrapper

    def _read_then_write_while_another_connection_writes(self, options, journal_mode):
        """Return the error the reader's write raised, or None.

        The reader opens a transaction the way ``atomic()`` does, reads, and
        writes half a second later; another connection writes in between.
        """
        reader = self._wrapper(options)
        reader.ensure_connection()
        with reader.cursor() as cursor:
            cursor.execute(f"PRAGMA journal_mode={journal_mode}")
            cursor.execute("CREATE TABLE locks (value INTEGER)")
        failures = []

        def other_writer():
            # Created in this thread, so it must be closed in this thread.
            writer = self._wrapper(options, close_on_cleanup=False)
            try:
                time.sleep(0.2)
                with writer.cursor() as cursor:
                    cursor.execute("INSERT INTO locks VALUES (1)")
            except OperationalError as error:  # pragma: no cover - failure path
                failures.append(error)
            finally:
                writer.close()

        thread = threading.Thread(target=other_writer)
        # What atomic() does on entry.
        reader.set_autocommit(False, force_begin_transaction_with_broken_autocommit=True)
        error = None
        try:
            with reader.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM locks")
                cursor.fetchall()
            thread.start()
            time.sleep(0.5)
            try:
                with reader.cursor() as cursor:
                    cursor.execute("INSERT INTO locks VALUES (2)")
                reader.commit()
            except OperationalError as caught:
                error = caught
                reader.rollback()
        finally:
            reader.set_autocommit(True)
            thread.join()
        self.assertEqual(failures, [])
        return error

    def _check(self, options, journal_mode):
        # A fresh file per run, in the journal mode being tried.
        self.database_path = self.directory / f"{journal_mode}-{id(options)}.sqlite3"
        return self._read_then_write_while_another_connection_writes(
            options, journal_mode
        )

    def test_project_setting_makes_the_reader_wait_for_the_writer(self):
        options = settings.DATABASES["default"]["OPTIONS"]
        self.assertEqual(options["transaction_mode"], "IMMEDIATE")
        for journal_mode in ("wal", "delete"):
            with self.subTest(journal_mode=journal_mode):
                self.assertIsNone(self._check(options, journal_mode))

    def test_a_plain_begin_fails_at_once(self):
        """Without the setting the same sequence fails, which is the bug."""
        options = {
            key: value
            for key, value in settings.DATABASES["default"]["OPTIONS"].items()
            if key != "transaction_mode"
        }
        for journal_mode in ("wal", "delete"):
            with self.subTest(journal_mode=journal_mode):
                error = self._check(options, journal_mode)
                self.assertIsNotNone(error)
                self.assertIn("locked", str(error))
