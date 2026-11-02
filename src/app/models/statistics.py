"""Durable state for keeping the Statistics page warm.

Statistics used to keep all of this in the cache: the dirty-day list, the
freshness token, the refresh lock and the published range payloads. The cache
is volatile-lru and shares its memory budget with provider payloads, so an
eviction silently dropped invalidations or turned a warm page cold, and a lost
Celery message left a range stuck. What must survive lives here instead; the
per-day payloads stay in the cache because they are derived and rebuildable.
See docs/architecture/statistics-sync.md.
"""

import uuid

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import UniqueConstraint


class StatisticsDirtyDay(models.Model):
    """A day whose cached statistics payload no longer matches the database.

    Marking rewrites ``token``. A sync clears only rows whose token still
    matches the one it read, so a day re-marked while it was being rebuilt
    stays dirty for the next pass.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="+",
    )
    day = models.DateField()
    token = models.UUIDField(default=uuid.uuid4)
    marked_at = models.DateTimeField()

    class Meta:
        """Model and field configuration."""

        constraints = [
            UniqueConstraint(
                fields=["user", "day"],
                name="statistics_dirty_day_unique_user_day",
            ),
        ]

    def __str__(self):
        """Return the user and day this row marks."""
        return f"{self.user_id}:{self.day}"


class StatisticsSyncState(models.Model):
    """Per-user progress of the Statistics sync.

    ``generation`` counts changes. A published snapshot records the generation
    it was built against; it is stale while it is behind. The synced
    generations let the reconciler find unfinished work with one query.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="+",
    )
    generation = models.BigIntegerField(default=1)
    hot_synced_generation = models.BigIntegerField(default=0)
    heavy_synced_generation = models.BigIntegerField(default=0)
    # When the heavy ranges were last rebuilt; caps how long they may trail.
    heavy_synced_at = models.DateTimeField(null=True, blank=True)
    # The local date every range was last rebuilt for. Rolling windows move at
    # midnight, so a sync that has not run today owes every range.
    synced_day = models.DateField(null=True, blank=True)
    last_marked_at = models.DateTimeField(null=True, blank=True)
    # Set when a sync must also rebuild day payloads that are missing from the
    # cache (Redis flushed, first build). Cleared by the sync that finishes it.
    full_sweep_requested_at = models.DateTimeField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    # Identity of the worker that holds the lease. Claims rotate it; lease
    # renewals, publications and marker updates are fenced on it so an
    # expired worker cannot act on a successor's sync (see statistics_sync).
    lease_token = models.UUIDField(null=True, blank=True)
    last_started_at = models.DateTimeField(null=True, blank=True)
    last_finished_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")

    def __str__(self):
        """Return the user and generation."""
        return f"{self.user_id} g{self.generation}"


class StatisticsSnapshot(models.Model):
    """The last published payload for one predefined range.

    ``payload`` is dehydrated: model instances are stored as references and
    re-fetched on read (see ``app.statistics_sync.hydrate_payload``).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="+",
    )
    range_name = models.CharField(max_length=32)
    payload = models.JSONField(encoder=DjangoJSONEncoder, default=dict)
    generation = models.BigIntegerField(default=0)
    built_day = models.DateField()
    built_at = models.DateTimeField()
    schema_version = models.PositiveIntegerField(default=0)

    class Meta:
        """Model and field configuration."""

        constraints = [
            UniqueConstraint(
                fields=["user", "range_name"],
                name="statistics_snapshot_unique_user_range",
            ),
        ]

    def __str__(self):
        """Return the user and range."""
        return f"{self.user_id}:{self.range_name}"
