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
    media_id = models.CharField(max_length=500)
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


class DeletedEntry(models.Model):
    """Records that a tracked entry was deleted, for clients mirroring the library.

    Unlike ``DeletedMedia`` (which importers read and which covers only
    top-level types), this covers every tracked type, seasons, comic issues and
    videos included, and is never cleared. It is the source of
    ``GET /api/v1/library/deleted/``. A repeat deletion refreshes
    ``deleted_at``.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    media_type = models.CharField(max_length=20, choices=MediaTypes)
    source = models.CharField(max_length=20, choices=Sources)
    media_id = models.CharField(max_length=500)
    season_number = models.PositiveIntegerField(null=True, blank=True)
    deleted_at = models.DateTimeField(db_index=True)

    class Meta:
        """Meta options for DeletedEntry."""

        constraints = [
            UniqueConstraint(
                fields=["user", "media_type", "source", "media_id"],
                condition=models.Q(season_number__isnull=True),
                name="deletedentry_unique_user_type_source_id",
            ),
            UniqueConstraint(
                fields=["user", "media_type", "source", "media_id", "season_number"],
                condition=models.Q(season_number__isnull=False),
                name="deletedentry_unique_user_type_source_id_season",
            ),
        ]
        indexes = [models.Index(fields=["user", "deleted_at"])]

    def __str__(self):
        """Return a readable identifier for the record."""
        return f"{self.user_id}:{self.media_type}:{self.source}:{self.media_id}"
