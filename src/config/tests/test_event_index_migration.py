import copy
from importlib import import_module
from unittest.mock import patch

from django.db import connections, models
from django.db.backends.postgresql.base import DatabaseWrapper as PostgreSQLWrapper
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.state import ModelState, ProjectState
from django.test import SimpleTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from config.sqlite_backend.base import DatabaseWrapper


@override_settings(MIGRATION_MODULES={})
class EventIndexMigrationTests(SimpleTestCase):
    def setUp(self):
        settings_dict = copy.deepcopy(connections["default"].settings_dict)
        settings_dict.update(
            ENGINE="config.sqlite_backend",
            NAME=":memory:",
            OPTIONS={"transaction_mode": "IMMEDIATE"},
        )
        self.db = DatabaseWrapper(settings_dict, alias="event-index-migration")
        connections[self.db.alias] = self.db
        self.addCleanup(self._close)
        self.state = ProjectState(
            {
                ("events", "event"): ModelState(
                    "events",
                    "Event",
                    [
                        ("id", models.BigAutoField(primary_key=True)),
                        ("datetime", models.DateTimeField()),
                    ],
                ),
            }
        )
        with self.db.schema_editor() as editor:
            editor.create_model(self.state.apps.get_model("events", "Event"))
        with self.db.cursor() as cursor:
            cursor.execute(
                "INSERT INTO events_event (datetime) VALUES ('2026-10-24 12:00:00')"
            )
        self.executor = MigrationExecutor(self.db)
        self.executor.recorder.ensure_schema()
        self.migration = import_module(
            "events.migrations.0017_event_datetime_index"
        ).Migration("0017_event_datetime_index", "events")

    def _close(self):
        self.db.close()
        del connections[self.db.alias]

    def test_adds_index_without_scanning_foreign_keys_or_rebuilding_table(self):
        original_check = self.db.check_constraints
        with CaptureQueriesContext(self.db) as queries:
            state = self.executor.apply_migration(self.state, self.migration)
        statements = [query["sql"].upper() for query in queries]
        self.assertFalse(any("FOREIGN_KEY_CHECK" in sql for sql in statements))
        self.assertFalse(any("CREATE TABLE" in sql for sql in statements))
        self.assertIn("BEGIN IMMEDIATE", statements)
        with self.db.cursor() as cursor:
            constraints = self.db.introspection.get_constraints(cursor, "events_event")
            cursor.execute("SELECT datetime FROM events_event")
            self.assertEqual(str(cursor.fetchone()[0]), "2026-10-24 12:00:00")
            cursor.execute("PRAGMA foreign_keys")
            self.assertEqual(cursor.fetchone()[0], 1)
        self.assertEqual(
            constraints["events_event_datetime_idx"]["columns"], ["datetime"]
        )
        self.assertEqual(
            state.apps.get_model("events", "Event")._meta.indexes[0].name,
            "events_event_datetime_idx",
        )
        self.assertIn(
            ("events", self.migration.name), self.executor.recorder.applied_migrations()
        )
        self.assertEqual(self.db.check_constraints, original_check)

    def test_failed_record_rolls_back_index_and_can_retry(self):
        original_check = self.db.check_constraints
        with (
            patch.object(
                self.executor,
                "record_migration",
                side_effect=RuntimeError("interrupted"),
            ),
            self.assertRaisesMessage(RuntimeError, "interrupted"),
        ):
            self.executor.apply_migration(self.state.clone(), self.migration)
        self.assertEqual(self.db.check_constraints, original_check)
        with self.db.cursor() as cursor:
            constraints = self.db.introspection.get_constraints(cursor, "events_event")
        self.assertNotIn("events_event_datetime_idx", constraints)
        self.assertNotIn(
            ("events", self.migration.name), self.executor.recorder.applied_migrations()
        )
        self.executor.apply_migration(self.state.clone(), self.migration)
        self.assertIn(
            ("events", self.migration.name), self.executor.recorder.applied_migrations()
        )
        # The next schema editor retains its ordinary integrity check.
        with (
            CaptureQueriesContext(self.db) as queries,
            self.db.schema_editor() as editor,
        ):
            editor.execute("CREATE TABLE scratch (id integer PRIMARY KEY)")
        self.assertIn("PRAGMA foreign_key_check", [q["sql"] for q in queries])

    def test_postgresql_still_generates_normal_index_ddl(self):
        settings_dict = copy.deepcopy(self.db.settings_dict)
        settings_dict["ENGINE"] = "django.db.backends.postgresql"
        db = PostgreSQLWrapper(settings_dict, alias="event-index-postgresql-sql")
        connections[db.alias] = db
        self.addCleanup(connections.__delitem__, db.alias)
        original_check = db.check_constraints
        with db.schema_editor(collect_sql=True, atomic=False) as editor:
            self.migration.apply(self.state, editor, collect_sql=True)
        self.assertEqual(
            [sql for sql in editor.collected_sql if not sql.startswith("--")],
            [
                'CREATE INDEX "events_event_datetime_idx" '
                'ON "events_event" ("datetime");'
            ],
        )
        self.assertEqual(db.check_constraints, original_check)
