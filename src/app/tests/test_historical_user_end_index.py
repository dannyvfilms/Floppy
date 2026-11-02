import datetime
import unittest

from django.apps import apps
from django.db import connection
from django.test import TestCase
from django.utils import timezone


class HistoricalUserEndIndexTests(TestCase):
    """The History page ranges on end_date within each history_user."""

    @unittest.skipUnless(
        connection.vendor == "sqlite", "plan text is checked on SQLite only"
    )
    def test_date_range_uses_user_end_index(self):
        """Music and podcast history seek by (history_user, end_date)."""
        now = timezone.now()
        for name, index in (
            ("HistoricalPodcast", "app_histpodcast_user_end_idx"),
            ("HistoricalMusic", "app_histmusic_user_end_idx"),
        ):
            model = apps.get_model("app", name)
            plan = model.objects.filter(
                history_user_id=1,
                end_date__gte=now - datetime.timedelta(days=1),
                end_date__lte=now,
            ).explain()
            self.assertIn(index, plan)

    def test_other_media_history_is_not_indexed(self):
        """Only music and podcast history tables carry the extra index."""
        movie = apps.get_model("app", "HistoricalMovie")
        self.assertEqual(movie._meta.indexes, [])
