from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0157_statistics_default_media_types"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="sidebar_pins",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Sidebar pins: {'nav': [link keys], 'lists': [{'id', 'name', 'url'}]}",
            ),
        ),
    ]
