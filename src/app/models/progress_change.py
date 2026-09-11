"""Ordered, explicit changes to resume progress.

``PlaybackProgress`` stays the current-state store. This is the additive log a
synchronizing client reads to learn what moved, in server order, including the
deletes that ``?updated_since=`` could never express: a row that is gone is
absent from a timestamp query, and absence is not a delete.

Sequences come from the same per-user allocator as watched state, so one client
holds one monotonic position per resource and the checkpoint and compaction
machinery is shared rather than duplicated.
"""

import uuid

from django.conf import settings
from django.db import models

from app.models.item import Item


class ProgressChangeKind(models.TextChoices):
    """Whether a change asserts a position or retracts it."""

    UPSERT = "upsert", "Upsert"
    DELETE = "delete", "Delete"


class ProgressChange(models.Model):
    """One accepted resume-position transition, in server order."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="progress_changes",
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="progress_changes",
    )
    sequence = models.BigIntegerField()
    kind = models.CharField(
        max_length=8,
        choices=ProgressChangeKind,
        default=ProgressChangeKind.UPSERT.value,
    )
    position_seconds = models.PositiveIntegerField(default=0)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    completed = models.BooleanField(default=False)
    # Which connection caused this, so a client can skip its own echo instead
    # of applying it and emitting another change.
    origin_key = models.CharField(max_length=128, blank=True, default="")
    correlation_id = models.UUIDField(default=uuid.uuid4)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Model options."""

        verbose_name = "Progress change"
        verbose_name_plural = "Progress changes"
        ordering = ["sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "sequence"],
                name="unique_progress_change_sequence",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "sequence"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        """Readable representation."""
        return f"ProgressChange({self.user_id}, {self.sequence}, {self.kind})"
