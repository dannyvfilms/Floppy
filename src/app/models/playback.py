from django.conf import settings
from django.db import models
from django.db.models import UniqueConstraint

from app.models.item import Item


class PlaybackProgress(models.Model):
    """Durable second-level resume position for a movie or episode.

    ``Media.progress`` can't carry this: its unit varies per media type
    (episodes for TV, 1 for movies, pages for books, minutes for podcasts),
    and ``live_playback`` only keeps a cache entry for the user's *current*
    item. This is the durable, per-item store third-party clients read and
    write for bidirectional resume sync.

    Keyed on Item rather than Movie/Episode because Episode is not a Media
    subclass — Item is the only uniform key across both. Podcast positions
    stay on ``Podcast.played_up_to_seconds``, which the podcast UI reads.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="playback_progress",
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="playback_progress",
    )
    position_seconds = models.PositiveIntegerField()
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    completed = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Meta options for PlaybackProgress."""

        ordering = ["-updated_at"]
        verbose_name_plural = "Playback progress"
        constraints = [
            UniqueConstraint(
                fields=["user", "item"],
                name="playbackprogress_unique_user_item",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "-updated_at"]),
        ]

    def __str__(self):
        """Return a readable position label."""
        return f"{self.user_id}:{self.item_id}@{self.position_seconds}s"
