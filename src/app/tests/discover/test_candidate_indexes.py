from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.utils import timezone

from app.discover.service_helpers import _activity_filter_query, _activity_ordering
from app.models import Movie, Status


class DiscoverCandidateIndexTests(TestCase):
    """The comfort/recent candidate queries are served by the activity indexes."""

    def _plan(self, queryset):
        if connection.vendor != "sqlite":
            self.skipTest("EXPLAIN QUERY PLAN output is SQLite-specific")
        sql, params = queryset.query.sql_with_params()
        with connection.cursor() as cursor:
            cursor.execute("EXPLAIN QUERY PLAN " + sql, params)
            return " | ".join(row[3] for row in cursor.fetchall())

    def test_recent_query_uses_activity_index_without_sort(self):
        user = get_user_model().objects.create_user(username="d6", password="x")
        cutoff = timezone.now() - timedelta(days=90)
        queryset = (
            Movie.objects.filter(user=user, status=Status.COMPLETED.value)
            .filter(_activity_filter_query(Movie, cutoff, newer_than=True))
            .order_by(*_activity_ordering(Movie))[:300]
        )
        plan = self._plan(queryset)
        self.assertIn("app_movie_usr_act_idx", plan)
        self.assertNotIn("TEMP B-TREE", plan)

    def test_rated_query_uses_score_index_without_sort(self):
        user = get_user_model().objects.create_user(username="d6", password="x")
        cutoff = timezone.now() - timedelta(days=365)
        queryset = (
            Movie.objects.filter(
                user=user, status=Status.COMPLETED.value, score__gte=8.0
            )
            .filter(_activity_filter_query(Movie, cutoff, newer_than=False))
            .order_by("-score", *_activity_ordering(Movie))[:1500]
        )
        plan = self._plan(queryset)
        self.assertIn("app_movie_usr_scr_idx", plan)
        self.assertNotIn("TEMP B-TREE", plan)
