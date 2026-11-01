"""A user's own choice of which game a video is about."""

from django.conf import settings
from django.db import models

from app.models.item import Item


class VideoGameLink(models.Model):
    """Overrides the automatic match between a video and a Floppy game.

    `game_item` set means the user linked the video to that game. `game_item`
    empty means the user said the video is not about any game, which also stops
    the automatic match. No row means the automatic match applies. Linking never
    changes the game's playtime, status or tracking.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="video_game_links"
    )
    video_item = models.ForeignKey(
        Item, on_delete=models.CASCADE, related_name="video_game_links"
    )
    game_item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="linked_video_links",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """One choice per user and video."""

        constraints = [
            models.UniqueConstraint(
                fields=["user", "video_item"], name="app_videogamelink_unique_user_video"
            ),
        ]

    def __str__(self):
        """Return who linked what."""
        return f"{self.user_id}: {self.video_item_id} -> {self.game_item_id}"
