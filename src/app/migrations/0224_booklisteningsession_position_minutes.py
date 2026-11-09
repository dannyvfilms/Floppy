"""Repair databases that ran an earlier draft of 0221 without ``position_minutes``.

Migration 0221 was edited after it had already run on some databases, so Django
recorded it as applied while the ``position_minutes`` column was never created.
Listening history then failed with ``no such column``. This adds the column only
when it is missing, so a fresh install and a repaired database end up the same.
"""

from django.db import migrations


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


def add_position_minutes_if_missing(apps, schema_editor):
    """Create the column when an earlier draft of 0221 left it out."""
    model = apps.get_model("app", "BookListeningSession")
    field = model._meta.get_field("position_minutes")
    if _column_exists(schema_editor, model._meta.db_table, field.column):
        return
    schema_editor.add_field(model, field)


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0223_podcastepisode_description_podcastepisode_image"),
    ]

    operations = [
        migrations.RunPython(
            add_position_minutes_if_missing,
            migrations.RunPython.noop,
        ),
    ]
