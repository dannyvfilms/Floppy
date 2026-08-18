from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0158_podcast_end_date_inferred"),
    ]

    operations = [
        migrations.AlterField(
            model_name="studio",
            name="logo",
            field=models.TextField(blank=True, default=""),
        ),
    ]
