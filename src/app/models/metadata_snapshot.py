from django.db import models


class MetadataSnapshot(models.Model):
    """Store one durable last-known-good metadata payload."""

    class State(models.TextChoices):
        READY = "ready", "Ready"
        LOCAL = "local", "Local"
        REFRESHING = "refreshing", "Refreshing"
        FAILED = "failed", "Failed"
        BLOCKED = "blocked", "Blocked"

    class Origin(models.TextChoices):
        PROVIDER = "provider", "Provider"
        ITEM = "item", "Item"
        IMPORT = "import", "Import"
        API = "api", "API"
        REFRESH = "refresh", "Refresh"
        MANUAL = "manual", "Manual"

    cache_key = models.CharField(max_length=64, unique=True)
    source = models.CharField(max_length=20)
    media_type = models.CharField(max_length=32)
    media_id = models.CharField(max_length=500)
    language = models.CharField(max_length=35, blank=True, default="")
    season_numbers = models.JSONField(blank=True, default=list)
    episode_number = models.PositiveIntegerField(null=True, blank=True)
    edition_id = models.CharField(max_length=128, blank=True, default="")

    payload = models.JSONField(blank=True, default=dict)
    payload_hash = models.CharField(max_length=64, blank=True, default="")
    payload_size = models.PositiveIntegerField(default=0)
    schema_version = models.PositiveSmallIntegerField(default=1)

    state = models.CharField(
        max_length=16,
        choices=State.choices,
        default=State.LOCAL,
    )
    origin = models.CharField(
        max_length=16,
        choices=Origin.choices,
        default=Origin.ITEM,
    )
    fetched_at = models.DateTimeField(null=True, blank=True)
    last_attempted_at = models.DateTimeField(null=True, blank=True)
    refresh_started_at = models.DateTimeField(null=True, blank=True)
    last_failure_at = models.DateTimeField(null=True, blank=True)
    failure_code = models.CharField(max_length=80, blank=True, default="")
    consecutive_failures = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["source", "media_type", "media_id"],
                name="app_meta_snap_lookup_idx",
            ),
            models.Index(
                fields=["state", "last_attempted_at"],
                name="app_meta_snap_state_idx",
            ),
            models.Index(
                fields=["fetched_at"],
                name="app_meta_snap_fetched_idx",
            ),
        ]
        ordering = ["source", "media_type", "media_id", "cache_key"]

    def __str__(self):
        return f"{self.source}:{self.media_type}:{self.media_id}"
