from django.conf import settings
from django.db import migrations, models


def _column_exists(schema_editor, table_name, column_name):
    """Return True when a database column already exists."""
    connection = schema_editor.connection
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = current_schema() "
                "AND table_name = %s AND column_name = %s",
                [table_name, column_name],
            )
            return cursor.fetchone() is not None
    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(cursor, table_name)
        columns = {getattr(column, "name", column[0]) for column in description}
        return column_name in columns


class AddFieldIfNotExists(migrations.AddField):
    """Add a field, or its through table for a many-to-many, only when absent."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        to_model = to_state.apps.get_model(app_label, self.model_name)
        field = to_model._meta.get_field(self.name)
        if field.many_to_many:
            table_names = schema_editor.connection.introspection.table_names()
            if field.remote_field.through._meta.db_table in table_names:
                return
        elif _column_exists(schema_editor, to_model._meta.db_table, field.column):
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)


class Migration(migrations.Migration):
    dependencies = [
        ("lists", "0017_customlistitem_rank"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        AddFieldIfNotExists(
            model_name="customlist",
            name="viewers",
            field=models.ManyToManyField(
                blank=True,
                help_text="Users who can read this list without changing it.",
                related_name="viewable_lists",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="customlist",
            name="visibility",
            field=models.CharField(
                choices=[
                    ("public", "Public"),
                    ("unlisted", "Unlisted"),
                    ("private", "Private"),
                ],
                default="private",
                max_length=10,
            ),
        ),
    ]
