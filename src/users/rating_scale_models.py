"""Custom rating scales: named criteria, weight tiers and per-entry values.

Entries keep Floppy's internal 0-10 `score`. A custom scale only describes how
that score is derived (see `users.rating_scales.compute_score`), so sorting,
filters, statistics, integrations and cards are unchanged.
"""

import uuid
from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class RatingScale(models.Model):
    """A user-defined rating scale. Deleting one archives it, never its ratings."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="rating_scales",
    )
    name = models.CharField(max_length=60)
    position = models.PositiveIntegerField(default=0)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Order by position."""

        ordering = ["position", "created_at"]

    def __str__(self):
        """Return the scale name."""
        return self.name


class RatingCriterion(models.Model):
    """One scored aspect of a scale; `weight` is its tier (1 = lightest)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scale = models.ForeignKey(
        RatingScale,
        on_delete=models.CASCADE,
        related_name="criteria",
    )
    name = models.CharField(max_length=60)
    minimum = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal(0))
    maximum = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal(10))
    weight = models.PositiveSmallIntegerField(default=1)
    position = models.PositiveIntegerField(default=0)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        """Tier order, with range sanity checks."""

        ordering = ["weight", "position"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(maximum__gt=models.F("minimum")),
                name="rating_criterion_max_gt_min",
            ),
            models.CheckConstraint(
                condition=models.Q(weight__gte=1),
                name="rating_criterion_weight_positive",
            ),
        ]

    def __str__(self):
        """Return the criterion name."""
        return self.name


class EntryRating(models.Model):
    """Per-criterion values for one tracked entry, kept beside its `score`.

    `values` maps criterion id to the number the user picked on that
    criterion's own range. A missing key is an empty criterion; 0 is a score.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="entry_ratings",
    )
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    entry = GenericForeignKey("content_type", "object_id")
    scale = models.ForeignKey(
        RatingScale,
        on_delete=models.PROTECT,
        related_name="entry_ratings",
    )
    values = models.JSONField(default=dict, blank=True)
    computed_score = models.DecimalField(
        max_digits=3,
        decimal_places=1,
        null=True,
        blank=True,
    )
    is_manual = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """One rating record per entry."""

        constraints = [
            models.UniqueConstraint(
                fields=["content_type", "object_id"],
                name="entry_rating_one_per_entry",
            ),
        ]

    def __str__(self):
        """Return a short description."""
        return f"{self.content_type_id}:{self.object_id}"


def _persist_pending_entry_rating(sender, instance, **kwargs):
    """Store criteria values a form attached to an entry it just saved."""
    pending = getattr(instance, "_pending_entry_rating", None)
    if pending is None:
        return
    from users import rating_scales

    instance._pending_entry_rating = None
    rating_scales.save_entry_rating(
        pending["user"],
        instance,
        pending["values"],
        pending["computed"],
        manual=pending["manual"],
    )


# Forms save with commit=False and the view saves later, so the write follows the save.
models.signals.post_save.connect(
    _persist_pending_entry_rating,
    dispatch_uid="users.persist_pending_entry_rating",
)
