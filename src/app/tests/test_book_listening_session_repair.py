"""Migration 0224 restores a ``position_minutes`` column that 0221 never created."""

from importlib import import_module

from django.apps import apps
from django.db import connection
from django.test import TransactionTestCase

from app.models import BookListeningSession

repair = import_module("app.migrations.0224_booklisteningsession_position_minutes")


def _columns():
    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(
            cursor, BookListeningSession._meta.db_table,
        )
    return {column.name for column in description}


class BookListeningSessionRepairTest(TransactionTestCase):
    """A database that ran an earlier draft of 0221 has no such column."""

    def _drop_column(self):
        field = BookListeningSession._meta.get_field("position_minutes")
        with connection.schema_editor() as editor:
            editor.remove_field(BookListeningSession, field)

    def _run(self):
        with connection.schema_editor() as editor:
            repair.add_position_minutes_if_missing(apps, editor)

    def test_adds_the_missing_column(self):
        """The column is created, and listening history queries work again."""
        self._drop_column()
        self.assertNotIn("position_minutes", _columns())
        self._run()
        self.assertIn("position_minutes", _columns())
        self.assertEqual(BookListeningSession.objects.count(), 0)

    def test_leaves_a_complete_table_alone(self):
        """Running it on a healthy database, or twice, changes nothing."""
        before = _columns()
        self._run()
        self._run()
        self.assertEqual(_columns(), before)
