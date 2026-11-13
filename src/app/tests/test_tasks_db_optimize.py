from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings

from app.models import TV, Item, Season, Status
from app.tasks_db_optimize import optimize_database_statistics

SEASON_BY_ITEM = (
    "SELECT s.id FROM app_season s JOIN app_item i ON i.id = s.item_id "
    "WHERE i.media_id = '7' AND i.source = 'tmdb' AND i.media_type = 'season' "
    "AND i.season_number = 1 AND s.user_id = %s"
)


def _plan(sql, params):
    with connection.cursor() as cursor:
        cursor.execute("EXPLAIN QUERY PLAN " + sql, params)
        return " | ".join(row[-1] for row in cursor.fetchall())


class OptimizeStatisticsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="u", password="x")
        shows = Item.objects.bulk_create(
            Item(media_id=str(n), source="tmdb", media_type="tv", title="t", image="x")
            for n in range(400)
        )
        tvs = TV.objects.bulk_create(
            TV(item=i, user=cls.user, status=Status.COMPLETED.value) for i in shows
        )
        seasons = Item.objects.bulk_create(
            Item(
                media_id=str(n), source="tmdb", media_type="season",
                season_number=s, title="t", image="x",
            )
            for n in range(400)
            for s in (1, 2, 3)
        )
        by_show = {tv.item.media_id: tv for tv in tvs}
        Season.objects.bulk_create(
            Season(
                item=i, related_tv=by_show[i.media_id], user=cls.user,
                status=Status.COMPLETED.value,
            )
            for i in seasons
        )

    def test_statistics_move_the_planner_to_the_item_index(self):
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS sqlite_stat1")
        before = _plan(SEASON_BY_ITEM, [self.user.id])
        self.assertIn("app_season_user_id", before)

        result = optimize_database_statistics()

        self.assertEqual(result["status"], "ok")
        self.assertGreater(result["stat_rows_after"], result["stat_rows_before"])
        after = _plan(SEASON_BY_ITEM, [self.user.id])
        self.assertNotIn("app_season_user_id", after)
        # app_item_type_lookup_idx (0213) covers the same lookup and wins when present.
        self.assertTrue(
            "app_item_media_lookup_idx" in after or "app_item_type_lookup_idx" in after,
            after,
        )

    def test_second_run_is_a_no_op_on_row_count(self):
        optimize_database_statistics()
        rows = optimize_database_statistics()["stat_rows_before"]
        self.assertEqual(optimize_database_statistics()["stat_rows_after"], rows)

    @override_settings(DB_OPTIMIZE_ENABLED=False)
    def test_disabled_skips(self):
        self.assertEqual(
            optimize_database_statistics(), {"status": "skipped", "reason": "disabled"},
        )

    @override_settings(USING_SQLITE_DATABASE=False)
    def test_skips_off_sqlite(self):
        self.assertEqual(
            optimize_database_statistics(), {"status": "skipped", "reason": "postgres"},
        )
