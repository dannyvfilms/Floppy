import re

from django.db import OperationalError
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.backends.sqlite3.base import DatabaseWrapper as SQLiteDatabaseWrapper
from django.db.backends.sqlite3.features import (
    DatabaseFeatures as SQLiteDatabaseFeatures,
)
from django.db.backends.sqlite3.schema import (
    DatabaseSchemaEditor as SQLiteDatabaseSchemaEditor,
)
from django.utils.functional import cached_property


class DatabaseFeatures(SQLiteDatabaseFeatures):
    """Keep capability detection independent of SQLite's writer lock."""

    @cached_property
    def supports_json_field(self):
        """Probe JSON without taking IMMEDIATE's write lock for a SELECT.

        Django 5.2 wraps this in atomic() and treats every OperationalError,
        including a busy database, as missing JSON support. A standalone
        SQLite SELECT needs no transaction wrapper; operational failures must
        remain visible instead of being cached as a capability result.
        """
        with self.connection.cursor() as cursor:
            try:
                cursor.execute('SELECT JSON(\'{"a": "b"}\')')
                cursor.fetchone()
            except OperationalError as error:
                if str(error).lower() == "no such function: json":
                    return False
                raise
        return True


_INDEX_DDL = re.compile(
    r"\s*(CREATE\s+(UNIQUE\s+)?INDEX|DROP\s+INDEX)\b", re.IGNORECASE
)


_ROW_WRITE = re.compile(r"\s*(INSERT|UPDATE|DELETE|REPLACE)\b", re.IGNORECASE)
# Django 5.2 records the migration in django_migrations inside the editor's
# ``with``; that one insert is expected and changes no relational data.
_MIGRATION_RECORD = "django_migrations"


class DatabaseSchemaEditor(SQLiteDatabaseSchemaEditor):
    """Skip the whole-database foreign-key scan after an index-only migration.

    Django's SQLite editor runs ``foreign_key_check`` over every table when it
    exits, so each index migration on a multi-GB database re-reads all child
    tables and probes their parents (about 50s each on a 4 GB test database,
    far more on spinning storage). Creating or dropping an index changes no
    row and no foreign key, so the scan can find nothing new. It is skipped
    only when every statement the editor ran was CREATE/DROP [UNIQUE] INDEX
    and no row was written other than the migration's own record (a RunPython
    in the same migration would show up there). Anything else, including table rebuilds, still gets
    Django's full check.
    """

    def __enter__(self):
        """Start tracking whether this migration only touches indexes."""
        self._index_only = True
        self._index_statements = 0
        editor = super().__enter__()
        self.connection.connection.set_trace_callback(self._watch_statement)
        return editor

    def _watch_statement(self, statement):
        """Note any row write other than the migration's own record."""
        if _ROW_WRITE.match(statement) and _MIGRATION_RECORD not in statement:
            self._index_only = False

    def execute(self, sql, params=()):
        """Record any statement that is not index DDL."""
        if not _INDEX_DDL.match(str(sql)):
            self._index_only = False
        else:
            self._index_statements += 1
        return super().execute(sql, params)

    def __exit__(self, exc_type, exc_value, traceback):
        """Run Django's foreign-key scan unless the migration was index-only."""
        self.connection.connection.set_trace_callback(None)
        if exc_type is None and self._index_only and self._index_statements:
            # A migration may have swapped in its own check_constraints (events
            # 0017 does); the scan it would have consumed is skipped here, so
            # drop the override or it outlives the migration.
            override = self.connection.__dict__.get("check_constraints")
            if getattr(override, "__name__", "") == "skip_check":
                del self.connection.check_constraints
            BaseDatabaseSchemaEditor.__exit__(self, exc_type, exc_value, traceback)
            self.connection.enable_constraint_checking()
            return
        super().__exit__(exc_type, exc_value, traceback)


class DatabaseWrapper(SQLiteDatabaseWrapper):
    """Use Django's SQLite backend with the corrected JSON probe."""

    features_class = DatabaseFeatures
    SchemaEditorClass = DatabaseSchemaEditor
