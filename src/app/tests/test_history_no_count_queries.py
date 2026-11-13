"""History build must not issue COUNT(*) queries it only used for logging."""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from app import history_cache
from app.models import Item, MediaTypes, Movie, Sources, Status


class HistoryNoCountQueriesTests(TestCase):
    """Each per-type queryset is iterated once, never counted first."""

    def test_build_history_days_issues_no_count_queries(self):
        cache.clear()
        user = get_user_model().objects.create_user(username="nocount", password="x")
        item = Item.objects.create(
            media_id="nocount-movie",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="No Count",
            image="http://example.com/m.jpg",
        )
        Movie.objects.create(
            item=item,
            user=user,
            status=Status.COMPLETED.value,
            end_date=timezone.now(),
        )

        with CaptureQueriesContext(connection) as queries:
            days = history_cache.build_history_days(user)

        self.assertTrue(days)
        counts = [q["sql"] for q in queries if q["sql"].startswith("SELECT COUNT(*)")]
        self.assertEqual(counts, [])
