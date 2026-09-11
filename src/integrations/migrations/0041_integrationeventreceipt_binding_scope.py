"""Scope idempotency receipts to a binding and index them for compaction.

Idempotent operations throughout: an upgrade may replay this against a database
where an operator already applied part of it by hand, and a migration that dies
half-way leaves an instance that will not start.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def _column_exists(schema_editor, table_name, column_name):
    """Return True when the backing column already exists."""
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(
            cursor,
            table_name,
        )
        columns = {getattr(column, "name", column[0]) for column in description}
    return column_name in columns


def _constraint_exists(schema_editor, table_name, constraint_name):
    """Return True when a Postgres constraint already exists.

    Postgres only: a UniqueConstraint created with the table is baked into
    SQLite's CREATE TABLE rather than stored as a named index, so there is no
    cheap way to detect it by name there.
    """
    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        return False
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM pg_constraint WHERE conname = %s",
            [constraint_name],
        )
        return cursor.fetchone() is not None


def _index_exists(schema_editor, table_name, index_name):
    """Return True when the named index already exists on the table."""
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        try:
            constraints = connection.introspection.get_constraints(
                cursor,
                table_name,
            )
        except Exception:  # noqa: BLE001 - introspection quirks shouldn't break migrate
            return False
    return index_name in constraints


class AddFieldIfNotExists(migrations.AddField):
    """Add a field only when the backing column doesn't already exist."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        """Skip the ALTER when the column is already there."""
        to_model = to_state.apps.get_model(app_label, self.model_name)
        field = to_model._meta.get_field(self.name)  # noqa: SLF001
        if _column_exists(schema_editor, to_model._meta.db_table, field.column):  # noqa: SLF001
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)


class AddIndexIfNotExists(migrations.AddIndex):
    """Add an index only when it doesn't already exist."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        """Skip the CREATE INDEX when the index is already there."""
        to_model = to_state.apps.get_model(app_label, self.model_name)
        if _index_exists(schema_editor, to_model._meta.db_table, self.index.name):  # noqa: SLF001
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)


class AddConstraintIfNotExists(migrations.AddConstraint):
    """Add a constraint only when it doesn't already exist."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        """Skip the ADD CONSTRAINT when it is already there."""
        to_model = to_state.apps.get_model(app_label, self.model_name)
        if _constraint_exists(
            schema_editor,
            to_model._meta.db_table,  # noqa: SLF001
            self.constraint.name,
        ):
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)


class RemoveConstraintIfExists(migrations.RemoveConstraint):
    """Remove a constraint only when it exists.

    SQLite always proceeds: it implements constraint removal as a full table
    rebuild from the target state, which is idempotent whatever the
    constraint's current physical form.
    """

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        """Skip the DROP when Postgres says the constraint is already gone."""
        connection = schema_editor.connection
        if connection.vendor == "postgresql":
            from_model = from_state.apps.get_model(app_label, self.model_name)
            if not _constraint_exists(
                schema_editor,
                from_model._meta.db_table,  # noqa: SLF001
                self.name,
            ):
                return
        super().database_forwards(app_label, schema_editor, from_state, to_state)


class Migration(migrations.Migration):
    """Replace the user-wide receipt constraint with a binding-scoped pair."""

    dependencies = [
        ("integrations", "0040_embyaccount_kodiaccount_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        RemoveConstraintIfExists(
            model_name="integrationeventreceipt",
            name="unique_user_client_event_id",
        ),
        AddFieldIfNotExists(
            model_name="integrationeventreceipt",
            name="binding",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="event_receipts",
                to="integrations.syncbinding",
            ),
        ),
        AddIndexIfNotExists(
            model_name="integrationeventreceipt",
            index=models.Index(
                fields=["created_at"],
                name="integration_created_52500b_idx",
            ),
        ),
        AddConstraintIfNotExists(
            model_name="integrationeventreceipt",
            constraint=models.UniqueConstraint(
                condition=models.Q(("binding__isnull", True)),
                fields=("user", "client_event_id"),
                name="unique_unbound_user_client_event_id",
            ),
        ),
        AddConstraintIfNotExists(
            model_name="integrationeventreceipt",
            constraint=models.UniqueConstraint(
                condition=models.Q(("binding__isnull", False)),
                fields=("binding", "client_event_id"),
                name="unique_binding_client_event_id",
            ),
        ),
    ]
