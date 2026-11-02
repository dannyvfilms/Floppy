"""Resolved logo and backdrop artwork for games, with where each came from.

The logo and the backdrop are resolved independently, so a game can have a
SteamGridDB logo and a ScreenScraper backdrop. Keeping the provider and its id
next to each URL is what lets a later "Refresh artwork" or "Pick another" be
added without reshaping the data.
"""

from django.db import models


class GameArtwork(models.Model):
    """The logo and backdrop Floppy resolved for one provider game."""

    source = models.CharField(max_length=20)
    media_id = models.CharField(max_length=500)
    logo_url = models.URLField(max_length=1000, blank=True, default="")
    logo_provider = models.CharField(max_length=20, blank=True, default="")
    logo_provider_id = models.CharField(max_length=100, blank=True, default="")
    backdrop_url = models.URLField(max_length=1000, blank=True, default="")
    backdrop_provider = models.CharField(max_length=20, blank=True, default="")
    backdrop_provider_id = models.CharField(max_length=100, blank=True, default="")
    resolved_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model options."""

        constraints = [
            models.UniqueConstraint(
                fields=["source", "media_id"],
                name="app_gameartwork_unique_game",
            ),
        ]

    def __str__(self):
        """Readable representation."""
        return f"{self.source}:{self.media_id} artwork"
