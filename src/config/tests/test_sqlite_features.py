import copy
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from django.db import OperationalError, connection
from django.db.backends.sqlite3.features import DatabaseFeatures as DjangoFeatures
from django.test import SimpleTestCase

from config.sqlite_backend.base import DatabaseFeatures, DatabaseWrapper


class SQLiteJSONFeatureTests(SimpleTestCase):
    def test_json_probe_works_while_another_connection_holds_the_write_lock(self):
        with TemporaryDirectory() as directory:
            database = str(Path(directory) / "features.sqlite3")
            writer = sqlite3.connect(database)
            self.addCleanup(writer.close)
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("CREATE TABLE example (value INTEGER)")
            settings_dict = copy.deepcopy(connection.settings_dict)
            settings_dict.update(
                ENGINE="config.sqlite_backend",
                NAME=database,
                OPTIONS={"timeout": 0.01, "transaction_mode": "IMMEDIATE"},
            )
            probe = DatabaseWrapper(settings_dict, alias="json-probe")
            try:
                probe.ensure_connection()
                writer.execute("BEGIN IMMEDIATE")
                # Reproduce Django's false negative on the very same database.
                with patch("django.db.transaction.get_connection", return_value=probe):
                    self.assertFalse(DjangoFeatures(probe).supports_json_field)
                self.assertTrue(probe.features.supports_json_field)
                self.assertTrue(probe.features.can_introspect_json_field)
                self.assertTrue(probe.features.has_json_object_function)
                self.assertEqual(probe.transaction_mode, "IMMEDIATE")
            finally:
                writer.rollback()
                probe.close()

    def test_missing_json_function_is_unsupported(self):
        wrapper = MagicMock()
        cursor = wrapper.cursor.return_value.__enter__.return_value
        cursor.execute.side_effect = OperationalError("no such function: JSON")
        self.assertFalse(DatabaseFeatures(wrapper).supports_json_field)

    def test_operational_errors_are_not_cached_as_missing_json(self):
        for message in ("database is locked", "disk I/O error"):
            with self.subTest(message=message):
                wrapper = MagicMock()
                cursor = wrapper.cursor.return_value.__enter__.return_value
                cursor.execute.side_effect = OperationalError(message)
                features = DatabaseFeatures(wrapper)
                with self.assertRaisesRegex(OperationalError, message):
                    _ = features.supports_json_field
                cursor.execute.side_effect = None
                self.assertTrue(features.supports_json_field)
