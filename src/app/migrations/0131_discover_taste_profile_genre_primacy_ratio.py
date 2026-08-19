from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0130_remove_item_app_item_source_valid_alter_item_source_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="discovertasteprofile",
            name="genre_primacy_ratio",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
