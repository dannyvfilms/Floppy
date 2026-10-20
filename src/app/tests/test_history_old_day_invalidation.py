from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from app import history_cache
from app.models import Item, MediaTypes, Movie, Sources, Status


class HistoryOldDayInvalidationTests(TestCase):
    """A row that moves to another day must drop the day it left from History."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="mover", password="pass"
        )
        item = Item.objects.create(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Movie",
            image="https://example.com/m.jpg",
        )
        self.first_day = timezone.now() - timedelta(days=10)
        self.second_day = timezone.now() - timedelta(days=3)
        self.movie = Movie.objects.create(
            user=self.user,
            item=item,
            status=Status.COMPLETED.value,
            end_date=self.first_day,
        )

    def _forced_days(self, mock_invalidate_days):
        return {
            day
            for call in mock_invalidate_days.call_args_list
            if call.kwargs.get("force")
            for day in call.kwargs["day_keys"]
        }

    @patch("app.history_cache.invalidate_history_days")
    def test_moving_the_date_invalidates_the_old_history_day(self, mock_days):
        self.movie.end_date = self.second_day
        self.movie.save()

        self.assertIn(
            history_cache.history_day_key(self.first_day),
            self._forced_days(mock_days),
        )

    @patch("app.history_cache.invalidate_history_days")
    def test_saving_without_moving_the_date_leaves_old_days_alone(self, mock_days):
        self.movie.progress = 1
        self.movie.save()

        self.assertEqual(self._forced_days(mock_days), set())
