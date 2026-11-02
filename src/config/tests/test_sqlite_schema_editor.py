import copy
from unittest.mock import patch

from django.db import connections
from django.test import SimpleTestCase

from config.sqlite_backend.base import DatabaseWrapper


class IndexOnlySchemaEditorTests(SimpleTestCase):
    def setUp(self):
        settings_dict = copy.deepcopy(connections["default"].settings_dict)
        settings_dict.update(
            ENGINE="config.sqlite_backend",
            NAME=":memory:",
            OPTIONS={"transaction_mode": "IMMEDIATE"},
        )
        self.db = DatabaseWrapper(settings_dict, alias="schema-editor-test")
        connections[self.db.alias] = self.db
        self.addCleanup(self._close)
        with self.db.cursor() as cursor:
            cursor.execute("CREATE TABLE t (id integer PRIMARY KEY, v integer)")
            cursor.execute("INSERT INTO t (v) VALUES (1)")

    def _close(self):
        self.db.close()
        del connections[self.db.alias]

    def _foreign_key_scans(self, work):
        with patch.object(
            self.db, "check_constraints", wraps=self.db.check_constraints
        ) as check:
            with self.db.schema_editor() as editor:
                work(editor)
        return check.call_count

    def test_index_only_migration_skips_foreign_key_scan(self):
        def work(editor):
            editor.execute('CREATE INDEX "t_v_idx" ON "t" ("v")')
            editor.execute('DROP INDEX "t_v_idx"')

        self.assertEqual(self._foreign_key_scans(work), 0)
        self.assertTrue(self.db.features.supports_foreign_keys)
        self.assertTrue(self.db.connection.execute("PRAGMA foreign_keys").fetchone()[0])

    def test_migration_record_insert_keeps_scan_skipped(self):
        def work(editor):
            editor.execute('CREATE INDEX "t_v_idx" ON "t" ("v")')
            with self.db.cursor() as cursor:
                cursor.execute("CREATE TABLE django_migrations (id integer)")
                cursor.execute("INSERT INTO django_migrations (id) VALUES (1)")

        self.assertEqual(self._foreign_key_scans(work), 0)

    def test_table_change_keeps_foreign_key_scan(self):
        def work(editor):
            editor.execute('CREATE INDEX "t_v_idx" ON "t" ("v")')
            editor.execute("CREATE TABLE u (id integer PRIMARY KEY)")

        self.assertEqual(self._foreign_key_scans(work), 1)

    def test_row_change_keeps_foreign_key_scan(self):
        def work(editor):
            editor.execute('CREATE INDEX "t_v_idx" ON "t" ("v")')
            with self.db.cursor() as cursor:
                cursor.execute("UPDATE t SET v = 2")

        self.assertEqual(self._foreign_key_scans(work), 1)

    def test_failed_migration_still_rolls_back(self):
        with self.assertRaises(RuntimeError):
            with self.db.schema_editor() as editor:
                editor.execute('CREATE INDEX "t_v_idx" ON "t" ("v")')
                raise RuntimeError
        with self.db.cursor() as cursor:
            cursor.execute("SELECT name FROM sqlite_master WHERE name = 't_v_idx'")
            self.assertEqual(cursor.fetchall(), [])
