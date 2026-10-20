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


class AddFieldIfNotExists(migrations.AddField):
    """Add a field only when the backing column doesn't already exist."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        """Skip the ALTER when the column is already there."""
        to_model = to_state.apps.get_model(app_label, self.model_name)
        field = to_model._meta.get_field(self.name)  # noqa: SLF001
        if _column_exists(schema_editor, to_model._meta.db_table, field.column):  # noqa: SLF001
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0202_clear_stale_deleted_media"),
    ]

    operations = [
        AddFieldIfNotExists(
            model_name="book",
            name="reading_time",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Minutes spent reading, added up from check-ins or entered by hand.",
            ),
        ),
        AddFieldIfNotExists(
            model_name="comic",
            name="reading_time",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Minutes spent reading, added up from check-ins or entered by hand.",
            ),
        ),
        AddFieldIfNotExists(
            model_name="historicalbook",
            name="reading_time",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Minutes spent reading, added up from check-ins or entered by hand.",
            ),
        ),
        AddFieldIfNotExists(
            model_name="historicalcomic",
            name="reading_time",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Minutes spent reading, added up from check-ins or entered by hand.",
            ),
        ),
        AddFieldIfNotExists(
            model_name="historicalmanga",
            name="reading_time",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Minutes spent reading, added up from check-ins or entered by hand.",
            ),
        ),
        AddFieldIfNotExists(
            model_name="manga",
            name="reading_time",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Minutes spent reading, added up from check-ins or entered by hand.",
            ),
        ),
    ]
