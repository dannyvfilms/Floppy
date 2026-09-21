from django.db import models


class ApplicationSettings(models.Model):
    """Instance-wide settings that are not tied to a user account."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    image_caching_enabled = models.BooleanField(default=False)
    public_branding = models.JSONField(default=dict, blank=True)

    class Meta:
        """Model metadata."""

        verbose_name = "application setting"
        verbose_name_plural = "application settings"

    def __str__(self):
        """Return the singleton's human-readable label."""
        return "Application settings"
