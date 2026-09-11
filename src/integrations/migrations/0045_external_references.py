from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


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
    """Return True when a named PostgreSQL constraint already exists."""
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
        except Exception:  # noqa: BLE001 - introspection quirks are non-fatal
            return False
    return index_name in constraints


class AddFieldIfNotExists(migrations.AddField):
    """Add a field only when the backing column does not already exist."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        """Skip the ALTER when the column is already present."""
        to_model = to_state.apps.get_model(app_label, self.model_name)
        field = to_model._meta.get_field(self.name)  # noqa: SLF001
        if _column_exists(schema_editor, to_model._meta.db_table, field.column):  # noqa: SLF001
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)


class AddIndexIfNotExists(migrations.AddIndex):
    """Add an index only when it does not already exist."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        """Skip the CREATE INDEX when the index is already present."""
        to_model = to_state.apps.get_model(app_label, self.model_name)
        if _index_exists(schema_editor, to_model._meta.db_table, self.index.name):  # noqa: SLF001
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)


class AddConstraintIfNotExists(migrations.AddConstraint):
    """Add a constraint only when it does not already exist."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        """Skip the ADD CONSTRAINT when the constraint is already present."""
        to_model = to_state.apps.get_model(app_label, self.model_name)
        if _constraint_exists(
            schema_editor,
            to_model._meta.db_table,  # noqa: SLF001
            self.constraint.name,
        ):
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)


class RemoveConstraintIfExists(migrations.RemoveConstraint):
    """Remove a constraint only when it exists on PostgreSQL."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        """Skip the DROP when PostgreSQL says the constraint is absent."""
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
    """Persist safe, user-scoped Plex and Trakt match decisions."""

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("integrations", "0044_integrationtoken_writable_list_ids"),
    ]

    operations = [
        AddFieldIfNotExists(
            model_name="plexwatchlistsyncitem",
            name="source_server_id",
            field=models.CharField(default="", max_length=255),
        ),
        RemoveConstraintIfExists(
            model_name="plexwatchlistsyncitem",
            name="integrations_plexwatchlistsyncitem_unique_user_item_source",
        ),
        AddConstraintIfNotExists(
            model_name="plexwatchlistsyncitem",
            constraint=models.UniqueConstraint(
                fields=("user", "item", "source_username", "source_server_id"),
                name="integrations_plexwatchlistsyncitem_unique_user_item_server",
            ),
        ),
        AddIndexIfNotExists(
            model_name="plexwatchlistsyncitem",
            index=models.Index(
                fields=("user", "source_server_id"),
                name="integrations__user_id_1f8c46_idx",
            ),
        ),
        migrations.CreateModel(
            name="ExternalReference",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("integration", models.CharField(max_length=32)),
                ("source_account", models.CharField(default="", max_length=255)),
                ("external_namespace", models.CharField(max_length=32)),
                ("external_identity", models.CharField(max_length=500)),
                ("media_type", models.CharField(max_length=10)),
                (
                    "review_status",
                    models.CharField(
                        choices=[
                            ("resolved", "Resolved automatically"),
                            ("needs_review", "Needs review"),
                            ("corrected", "Corrected"),
                            ("ignored", "Ignored"),
                        ],
                        default="resolved",
                        max_length=20,
                    ),
                ),
                ("episode_mapping", models.JSONField(blank=True, default=dict)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("decision_note", models.CharField(default="", max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "corrected_item",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="corrected_external_references",
                        to="app.item",
                    ),
                ),
                (
                    "matched_item",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="matched_external_references",
                        to="app.item",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="external_references",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "external reference",
                "verbose_name_plural": "external references",
                "ordering": ["-updated_at"],
                "indexes": [
                    models.Index(
                        fields=["user", "review_status"],
                        name="integrations_ex_user_id_8f34b1_idx",
                    ),
                    models.Index(
                        fields=["user", "integration", "source_account"],
                        name="integrations_ex_user_id_6dbf91_idx",
                    ),
                    models.Index(
                        fields=["matched_item", "media_type"],
                        name="integrations_ex_matched_7e4b3a_idx",
                    ),
                ],
            },
        ),
        AddConstraintIfNotExists(
            model_name="externalreference",
            constraint=models.UniqueConstraint(
                fields=(
                    "user",
                    "integration",
                    "source_account",
                    "external_namespace",
                    "external_identity",
                    "media_type",
                ),
                name="unique_user_external_reference",
            ),
        ),
    ]
