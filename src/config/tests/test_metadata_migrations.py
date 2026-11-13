import copy
from importlib import import_module

from django.db import connections, models
from django.db.backends.postgresql.base import DatabaseWrapper as PostgreSQLWrapper
from django.db.migrations import Migration
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.state import ModelState, ProjectState
from django.test import SimpleTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from app.models import MetadataBackfillState
from config.sqlite_backend.base import DatabaseWrapper


@override_settings(MIGRATION_MODULES={})
class MetadataMigrationTests(SimpleTestCase):
    def setUp(self):
        settings_dict = copy.deepcopy(connections["default"].settings_dict)
        settings_dict.update(
            ENGINE="config.sqlite_backend",
            NAME=":memory:",
            OPTIONS={"transaction_mode": "IMMEDIATE"},
        )
        self.db = DatabaseWrapper(settings_dict, alias="metadata-migrations")
        connections[self.db.alias] = self.db
        self.addCleanup(self._close)
        backfill = ModelState.from_model(MetadataBackfillState)
        del backfill.fields["terminal"]
        backfill.fields["field"].choices = [
            choice
            for choice in backfill.fields["field"].choices
            if choice[0] != "game_groups"
        ]
        self.state = ProjectState(
            {
                ("app", "item"): ModelState(
                    "app",
                    "Item",
                    [("id", models.BigAutoField(primary_key=True))],
                ),
                ("app", "metadatabackfillstate"): backfill,
            }
        )
        with self.db.schema_editor() as editor:
            editor.create_model(self.state.apps.get_model("app", "Item"))
            editor.create_model(
                self.state.apps.get_model("app", "MetadataBackfillState")
            )
        self.executor = MigrationExecutor(self.db)
        self.executor.recorder.ensure_schema()

    def _close(self):
        self.db.close()
        del connections[self.db.alias]

    def _migration(self, name):
        return import_module(f"app.migrations.{name}").Migration(name, "app")

    def test_choice_only_migration_records_without_ddl_or_foreign_key_scan(self):
        migration = self._migration("0206_metadata_backfill_game_groups")
        original_check = self.db.check_constraints
        with CaptureQueriesContext(self.db) as queries:
            self.state = self.executor.apply_migration(self.state, migration)
        statements = [query["sql"].upper() for query in queries]
        self.assertFalse(any("FOREIGN_KEY_CHECK" in sql for sql in statements))
        self.assertFalse(
            any(sql.startswith(("ALTER", "CREATE", "DROP")) for sql in statements)
        )
        self.assertIn("BEGIN IMMEDIATE", statements)
        self.assertIn(
            ("app", migration.name), self.executor.recorder.applied_migrations()
        )
        self.assertEqual(self.db.check_constraints, original_check)
        choices = (
            self.state.apps.get_model("app", "MetadataBackfillState")
            ._meta.get_field("field")
            .choices
        )
        self.assertIn(("game_groups", "Game Groups"), choices)

    def test_original_choice_only_operation_still_scans_all_foreign_keys(self):
        original = Migration("original_choice_only", "app")
        original.operations = self._migration(
            "0206_metadata_backfill_game_groups"
        ).operations
        with CaptureQueriesContext(self.db) as queries:
            self.executor.apply_migration(self.state, original)
        self.assertIn("PRAGMA foreign_key_check", [q["sql"] for q in queries])

    def test_choice_only_migration_also_generates_no_postgresql_ddl(self):
        settings_dict = copy.deepcopy(self.db.settings_dict)
        settings_dict["ENGINE"] = "django.db.backends.postgresql"
        db = PostgreSQLWrapper(settings_dict, alias="postgresql-sql-only")
        connections[db.alias] = db
        self.addCleanup(connections.__delitem__, db.alias)
        migration = self._migration("0206_metadata_backfill_game_groups")
        # SQL collection for this operation needs no PostgreSQL server.
        with db.schema_editor(collect_sql=True, atomic=False) as editor:
            migration.apply(self.state, editor, collect_sql=True)
        self.assertFalse(
            any(
                sql.startswith(("ALTER", "CREATE", "DROP"))
                for sql in editor.collected_sql
            )
        )

    def test_terminal_migration_preserves_rows_checks_only_changed_table_and_retries(
        self,
    ):
        first = self._migration("0206_metadata_backfill_game_groups")
        self.state = self.executor.apply_migration(self.state, first)
        self.state.apps.get_model("app", "Item").objects.using(self.db.alias).create(
            id=1
        )
        backfill = self.state.apps.get_model("app", "MetadataBackfillState")
        backfill.objects.using(self.db.alias).create(
            item_id=1, field="runtime", fail_count=3
        )
        migration = self._migration("0207_metadata_backfill_terminal")
        original_check = self.db.check_constraints
        before = self.state.clone()
        with CaptureQueriesContext(self.db) as queries:
            self.state = self.executor.apply_migration(self.state, migration)
        checks = [q["sql"] for q in queries if "foreign_key_check" in q["sql"]]
        self.assertEqual(
            checks, ['PRAGMA foreign_key_check("app_metadatabackfillstate")']
        )
        self.assertEqual(self.db.check_constraints, original_check)
        row = (
            self.state.apps.get_model("app", "MetadataBackfillState")
            .objects.using(self.db.alias)
            .get()
        )
        self.assertEqual(row.fail_count, 3)
        self.assertFalse(row.terminal)
        # An existing terminal column (an interrupted/manual attempt) is safe.
        with CaptureQueriesContext(self.db) as queries:
            self.executor.apply_migration(before, migration)
        self.assertFalse(any("CREATE TABLE" in q["sql"] for q in queries))
