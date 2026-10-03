# Generated for the source-native OAuth port.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import integrations.oauth_models


class Migration(migrations.Migration):

    dependencies = [
        ("integrations", "0048_oauth_client_registry"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="OAuthDeviceAuthorization",
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
                    "device_code_digest",
                    models.CharField(
                        db_index=True,
                        max_length=64,
                        unique=True,
                    ),
                ),
                (
                    "user_code_digest",
                    models.CharField(
                        db_index=True,
                        max_length=64,
                        unique=True,
                    ),
                ),
                ("requested_scopes", models.JSONField(default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField()),
                (
                    "interval",
                    models.PositiveSmallIntegerField(
                        default=integrations.oauth_models.OAUTH_DEVICE_POLL_INTERVAL_SECONDS
                    ),
                ),
                ("last_polled_at", models.DateTimeField(blank=True, null=True)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("denied_at", models.DateTimeField(blank=True, null=True)),
                ("consumed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "client",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="device_authorizations",
                        to="integrations.oauthclient",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="oauth_device_authorizations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
