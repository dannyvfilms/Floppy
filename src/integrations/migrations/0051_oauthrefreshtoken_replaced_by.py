import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("integrations", "0050_oauth_token_exchange"),
    ]

    operations = [
        migrations.AddField(
            model_name="oauthrefreshtoken",
            name="replaced_by",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="replaces",
                to="integrations.oauthrefreshtoken",
            ),
        ),
    ]
