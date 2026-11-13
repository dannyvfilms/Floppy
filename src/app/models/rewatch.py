"""User cancellations of read-only rewatch interpretations."""

from django.db import models


class RewatchCancellation(models.Model):
    """Remember the run's evidence without changing any play or tracking state."""

    tv = models.ForeignKey("app.TV", on_delete=models.CASCADE)
    order_key = models.CharField(max_length=100)
    run_key = models.CharField(max_length=64)
    season_number = models.PositiveIntegerField(null=True)
    anchor = models.DateTimeField()
    evidence = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """A cancellation is idempotent for a run in one tracking graph."""

        constraints = [models.UniqueConstraint(
            fields=["tv", "order_key", "run_key"],
            name="app_rewatch_cancellation_unique",
        )]

    def __str__(self):
        """Identify the canceled run without loading its history."""
        return f"{self.tv_id}: {self.run_key}"
