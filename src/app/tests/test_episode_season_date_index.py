import datetime
import unittest

from django.db import connection
from django.db.models import Q
from django.test import TestCase
from django.utils import timezone

from app.models import Episode


class EpisodeSeasonDateIndexTests(TestCase):
    """History probes each of the user's seasons by date (DATA-03)."""

    @unittest.skipUnless(
        connection.vendor == "sqlite", "plan text is checked on SQLite only"
    )
    def test_history_range_uses_season_date_indexes(self):
        """The date range and the open-play branch both seek within a season."""
        day = timezone.now()
        end = day + datetime.timedelta(days=1)
        plan = (
            Episode.all_objects.filter(related_season__user_id=1)
            .filter(
                Q(end_date__gte=day, end_date__lt=end)
                | (
                    Q(end_date__isnull=True)
                    & Q(start_date__gte=day, start_date__lt=end)
                ),
            )
            .explain()
        )
        self.assertIn("app_episode_season_end_idx", plan)
        self.assertIn("app_episode_season_open_idx", plan)
