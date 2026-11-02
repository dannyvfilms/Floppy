import datetime
import unittest

from django.db import connection
from django.test import TestCase
from django.utils import timezone

from app.models import VideoPlay


class VideoPlayIndexTests(TestCase):
    """The History video query ranges on end_date within each video."""

    @unittest.skipUnless(
        connection.vendor == "sqlite", "plan text is checked on SQLite only"
    )
    def test_date_range_uses_video_end_date_index(self):
        """The (video, end_date) index serves the History date filter."""
        now = timezone.now()
        plays = VideoPlay.objects.filter(
            video__user_id=1,
            end_date__gte=now - datetime.timedelta(days=1),
            end_date__lte=now,
        )
        plan = plays.explain()
        self.assertIn("app_videoplay_video_end_idx", plan)
