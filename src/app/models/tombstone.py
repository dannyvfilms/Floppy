from django.conf import settings
from django.db import models
from django.db.models import UniqueConstraint

from app.models.choices import MediaTypes, Sources


class DeletedMedia(models.Model):
    """Marks a top-level tracked media item the user explicitly deleted.

    Importers check this before recreating an item so that a locally-deleted
    show/movie/etc. isn't silently resurrected by a later sync just because
    the source (e.g. Trakt) still reports it. Cleared automatically when the
    user manually tracks that item again.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    media_type = models.CharField(max_length=20, choices=MediaTypes)
    source = models.CharField(max_length=20, choices=Sources)
    media_id = models.CharField(max_length=20)
    deleted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Meta options for DeletedMedia."""

        constraints = [
            UniqueConstraint(
                fields=["user", "media_type", "source", "media_id"],
                name="deletedmedia_unique_user_media_type_source_media_id",
            ),
        ]

    def __str__(self):
        """Return a readable identifier for the tombstone."""
        return f"{self.user_id}:{self.media_type}:{self.source}:{self.media_id}"
