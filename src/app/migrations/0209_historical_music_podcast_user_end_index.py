from django.conf import settings
from django.db import migrations, models


def _index_exists(schema_editor, table_name, index_name):
    """Return True when the named index already exists on the table."""
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        try:
            constraints = connection.introspection.get_constraints(cursor, table_name)
        except Exception:  # noqa: BLE001 - introspection quirks shouldn't break migrate
            return False
    return index_name in constraints


class AddIndexIfNotExists(migrations.AddIndex):
    """Add an index only when it doesn't already exist."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        """Skip the index add when the index is already there."""
        to_model = to_state.apps.get_model(app_label, self.model_name)
        if _index_exists(schema_editor, to_model._meta.db_table, self.index.name):
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0208_videoplay_video_end_date_index"),
        ("integrations", "0063_wetrakr_account"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        AddIndexIfNotExists(
            model_name="historicalmusic",
            index=models.Index(
                fields=["history_user", "end_date"], name="app_histmusic_user_end_idx"
            ),
        ),
        AddIndexIfNotExists(
            model_name="historicalpodcast",
            index=models.Index(
                fields=["history_user", "end_date"], name="app_histpodcast_user_end_idx"
            ),
        ),
    ]
