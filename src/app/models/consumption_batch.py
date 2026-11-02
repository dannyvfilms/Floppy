from django.conf import settings
from django.db import models
from django.db.models import UniqueConstraint


class ConsumptionBatchItem(models.Model):
    """One requested consumption inside a caller-named batch operation.

    The row is created ``pending`` when the batch is accepted and finished in
    the same transaction that writes the consumption, so a worker that dies
    mid-item leaves either a finished row or a retryable one, never a created
    consumption without its row. ``(user, operation_id, client_ref)`` is the
    idempotency key.
    """

    class Outcome(models.TextChoices):
        """Where an item stands."""

        PENDING = "pending"
        RUNNING = "running"
        CREATED = "created"
        SKIPPED = "skipped"
        FAILED = "failed"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    operation_id = models.CharField(max_length=64)
    client_ref = models.CharField(max_length=255)
    payload_digest = models.CharField(max_length=64)
    outcome = models.CharField(
        max_length=10,
        choices=Outcome,
        default=Outcome.PENDING,
    )
    consumption_id = models.BigIntegerField(null=True, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Meta options for ConsumptionBatchItem."""

        constraints = [
            UniqueConstraint(
                fields=["user", "operation_id", "client_ref"],
                name="consumptionbatchitem_unique_user_operation_ref",
            ),
        ]
        indexes = [models.Index(fields=["created_at"])]

    def __str__(self):
        """Return a readable identifier for the item."""
        return f"{self.operation_id}:{self.client_ref}:{self.outcome}"
