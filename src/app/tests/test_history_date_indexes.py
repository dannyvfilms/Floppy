from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection, models
from django.test import TestCase
from django.utils import timezone

from app.models import Movie


class HistoryDateIndexTests(TestCase):
    """The History day query is served by the (user, end_date, start_date) index."""

    def test_day_query_uses_date_index(self):
        if connection.vendor != "sqlite":
            self.skipTest("EXPLAIN QUERY PLAN output is SQLite-specific")
        user = get_user_model().objects.create_user(username="d1", password="x")
        day_start = timezone.now()
        day_end = day_start + timedelta(days=1)
        queryset = (
            Movie.objects.filter(user=user)
            .filter(
                models.Q(end_date__isnull=False) | models.Q(start_date__isnull=False),
            )
            .filter(
                models.Q(end_date__gte=day_start, end_date__lt=day_end)
                | (
                    models.Q(end_date__isnull=True)
                    & models.Q(start_date__gte=day_start, start_date__lt=day_end)
                ),
            )
            .order_by("-end_date")
        )
        sql, params = queryset.query.sql_with_params()
        with connection.cursor() as cursor:
            cursor.execute("EXPLAIN QUERY PLAN " + sql, params)
            plan = " | ".join(row[3] for row in cursor.fetchall())
        self.assertIn("app_movie_usr_dates_idx", plan)
