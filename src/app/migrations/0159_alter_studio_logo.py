from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0158_podcast_end_date_inferred"),
    ]

    operations = [
        migrations.AlterField(
            model_name="podcastshow",
            name="rss_feed_url",
            field=models.TextField(
                blank=True,
                default="",
                help_text="RSS feed URL for fetching full episode list",
            ),
        ),
        migrations.AlterField(
            model_name="studio",
            name="logo",
            field=models.TextField(blank=True, default=""),
        ),
    ]
