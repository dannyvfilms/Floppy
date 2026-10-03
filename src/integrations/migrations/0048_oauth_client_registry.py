# Generated for the source-native OAuth port.

from django.db import migrations, models

import integrations.oauth_models


class Migration(migrations.Migration):

    dependencies = [
        ("integrations", "0047_merge_20260910_1141"),
    ]

    operations = [
        migrations.CreateModel(
            name="OAuthClient",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "client_id",
                    models.CharField(
                        db_index=True,
                        max_length=96,
                        unique=True,
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                (
                    "allowed_scopes",
                    models.JSONField(
                        default=integrations.oauth_models.default_oauth_scopes
                    ),
                ),
                (
                    "grant_types",
                    models.JSONField(
                        default=integrations.oauth_models.default_oauth_grant_types
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "ordering": ["name", "client_id"],
            },
        ),
    ]
