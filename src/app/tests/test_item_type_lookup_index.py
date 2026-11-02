from django.db import connection
from django.db.models import Max
from django.test import TestCase

from app.models import Item, MediaTypes


class ItemTypeLookupIndexTests(TestCase):
    """Queries that lead with media_type no longer scan the whole item table."""

    def _plan(self, queryset):
        if connection.vendor != "sqlite":
            self.skipTest("EXPLAIN QUERY PLAN output is SQLite-specific")
        sql, params = queryset.query.sql_with_params()
        with connection.cursor() as cursor:
            cursor.execute("EXPLAIN QUERY PLAN " + sql, params)
            return " | ".join(row[3] for row in cursor.fetchall())

    def test_media_type_filter_uses_index(self):
        plan = self._plan(
            Item.objects.filter(
                media_type__in=(MediaTypes.TV.value, MediaTypes.SEASON.value),
                title__icontains="the",
            ).values("id")
        )
        self.assertIn("app_item_type_lookup_idx", plan)

    def test_released_episode_aggregate_is_covered(self):
        plan = self._plan(
            Item.objects.filter(
                media_type=MediaTypes.EPISODE.value,
                media_id__in=["1", "2"],
                source__in=["tmdb"],
                release_datetime__isnull=False,
                season_number__gt=0,
            )
            .values("media_id", "source", "season_number")
            .annotate(max_episode=Max("episode_number"))
        )
        self.assertIn("COVERING INDEX app_item_type_lookup_idx", plan)
