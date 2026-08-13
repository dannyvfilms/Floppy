# src/users/migrations/0121_add_movie_show_each_play.py
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0120_user_onboarding_connected_sources"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="movie_show_each_play",
            field=models.BooleanField(
                default=False,
                help_text="Show each play/entry as its own row instead of aggregating duplicates",
            ),
        ),
    ]