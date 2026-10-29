"""The game YouTube associates with a video, kept apart from any Floppy game."""

from django.db import models

from app.models.item import Item


class VideoGameTag(models.Model):
    """What a lookup of a video's watch page found. One row per shared video item.

    The title and id are YouTube's own words. Matching them to a Floppy game is a
    separate step, so nothing here touches a game's playtime or status.
    """

    class Status(models.TextChoices):
        """Outcome of the last lookup."""

        FOUND = "found", "Found"
        NOT_FOUND = "not_found", "Not found"
        UNAVAILABLE = "unavailable", "Unavailable"

    item = models.OneToOneField(
        Item, on_delete=models.CASCADE, related_name="video_game_tag"
    )
    status = models.CharField(max_length=16, choices=Status.choices)
    game_title = models.CharField(max_length=255, blank=True, default="")
    # YouTube's own game id (a channel-style `UC...` browse id), stable across videos.
    game_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    release_year = models.CharField(max_length=8, blank=True, default="")
    checked_at = models.DateTimeField()
    failures = models.PositiveSmallIntegerField(default=0)

    def __str__(self):
        """Return the lookup outcome."""
        return f"{self.item_id}: {self.status} {self.game_title}"
