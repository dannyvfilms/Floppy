# src/users/migrations/0122_add_show_each_play.py
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0121_add_movie_show_each_play"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="anime_show_each_play",
            field=models.BooleanField(
                default=False,
                help_text="Show each play/entry as its own row instead of aggregating duplicates",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="manga_show_each_play",
            field=models.BooleanField(
                default=False,
                help_text="Show each play/entry as its own row instead of aggregating duplicates",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="game_show_each_play",
            field=models.BooleanField(
                default=False,
                help_text="Show each play/entry as its own row instead of aggregating duplicates",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="book_show_each_play",
            field=models.BooleanField(
                default=False,
                help_text="Show each play/entry as its own row instead of aggregating duplicates",
            ),
        ),
    ]