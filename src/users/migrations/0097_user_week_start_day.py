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


def _constraint_exists(schema_editor, table_name, constraint_name):
    """Return True when a database constraint already exists."""
    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        return False
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM pg_constraint WHERE conname = %s",
            [constraint_name],
        )
        return cursor.fetchone() is not None


class AddFieldIfNotExists(migrations.AddField):
    """Add a field only when the backing column doesn't already exist."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        to_model = to_state.apps.get_model(app_label, self.model_name)
        field = to_model._meta.get_field(self.name)
        if _column_exists(schema_editor, to_model._meta.db_table, field.column):
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)


class AddConstraintIfNotExists(migrations.AddConstraint):
    """Add a constraint only when it doesn't already exist."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        to_model = to_state.apps.get_model(app_label, self.model_name)
        if _constraint_exists(schema_editor, to_model._meta.db_table, self.constraint.name):
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0096_alter_user_date_format"),
    ]

    operations = [
        AddFieldIfNotExists(
            model_name="user",
            name="week_start_day",
            field=models.CharField(
                choices=[("monday", "Monday"), ("sunday", "Sunday")],
                default="monday",
                max_length=10,
            ),
        ),
        AddConstraintIfNotExists(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(week_start_day__in=["monday", "sunday"]),
                name="week_start_day_valid",
            ),
        ),
    ]
