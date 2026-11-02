"""YouTube-style video tracker and one play per watched day."""

from django.db import models, transaction
from django.utils import timezone
from model_utils import FieldTracker

from app.models.choices import Status
from app.models.media import Media

COMPLETED_RATIO = 0.8


class Video(Media):
    """A video that is not a movie. YouTube first, other sources later."""

    tracker = FieldTracker()
    channel = models.CharField(max_length=255, blank=True, default="")
    watch_url = models.URLField(max_length=500, blank=True, default="")
    length_seconds = models.PositiveIntegerField(default=0)

    class Meta:
        """One row per user and item."""

        unique_together = ("item", "user")

    def upsert_play(self, external_id, progress_seconds, end_date=None):
        """Create or raise the play for this external id.

        @param external_id - Idempotency key, `youtube:<id>:<day>`.
        @param progress_seconds - Position reached in this report, in seconds.
        @param end_date - When the watch counts. Defaults to now.
        @returns The play and whether it was created.
        """
        when = end_date or timezone.now()
        # Two retries of the same report can arrive together. Locking the video
        # row makes the second wait, so it sees the first one's play and
        # progress instead of racing to insert the same play.
        with transaction.atomic():
            Video.objects.select_for_update().filter(pk=self.pk).first()
            self.refresh_from_db(fields=["progress", "status", "end_date"])
            # A report can arrive late or out of order, so nothing here moves
            # backwards: progress and dates only grow, and a completed video
            # stays completed when a later day is reported at a lower position.
            self.progress = max(self.progress, progress_seconds)
            completed = (
                self.length_seconds > 0
                and self.progress >= COMPLETED_RATIO * self.length_seconds
            )
            if completed or self.status == Status.COMPLETED.value:
                self.status = Status.COMPLETED.value
            else:
                self.status = Status.IN_PROGRESS.value
            if not self.end_date or when > self.end_date:
                self.end_date = when
            self.save(
                update_fields=[
                    "progress",
                    "status",
                    "end_date",
                    "channel",
                    "watch_url",
                    "length_seconds",
                ]
            )

            play, created = VideoPlay.objects.get_or_create(
                video=self,
                external_id=external_id,
                defaults={"progress": progress_seconds, "end_date": when},
            )
            if not created:
                play.progress = max(play.progress, progress_seconds)
                play.end_date = max(play.end_date, when)
                play.save(update_fields=["progress", "end_date"])
        return play, created


class VideoPlay(models.Model):
    """One viewing of a video, keyed by external id."""

    created_at = models.DateTimeField(auto_now_add=True)
    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name="plays")
    external_id = models.CharField(max_length=255)
    progress = models.PositiveIntegerField(default=0)
    end_date = models.DateTimeField()

    class Meta:
        """Same external id updates one play."""

        constraints = [
            models.UniqueConstraint(
                fields=["video", "external_id"],
                name="app_videoplay_unique_video_external_id",
            ),
        ]
        indexes = [
            models.Index(
                fields=["video", "end_date"],
                name="app_videoplay_video_end_idx",
            ),
        ]

    def __str__(self):
        """Return the play's external id."""
        return self.external_id
