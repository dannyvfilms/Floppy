"""Coverage for the startup Trakt popularity reconcile.

The task had no test at all while it was the largest process-anonymous
high-water source in production (VmHWM 198 MiB -> 799 MiB for 2972 rows). The
memory-shaped assertions here are the ones that matter: the task must never
hydrate a full ``Item``, and its write count must scale with chunks rather
than with rows.
"""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from app.models import Item, MediaTypes, Movie, Sources, Status
from app.services import trakt_popularity as trakt_popularity_service
from app.tasks_trakt import RECONCILE_CHUNK_SIZE, reconcile_trakt_popularity


class ReconcileTraktPopularityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="trakt-reconcile-user",
            password="pw12345",
        )

    def _tracked_movie(self, media_id, *, fetched=True, rating=8.0, votes=1200):
        item = Item.objects.create(
            media_id=str(media_id),
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title=f"Movie {media_id}",
            image="https://example.com/movie.jpg",
            synopsis="x" * 2000,
            watch_providers={"US": {"flatrate": [{"provider_name": "y" * 2000}]}},
            trakt_rating=rating,
            trakt_rating_count=votes,
            trakt_popularity_fetched_at=(
                timezone.now() - timedelta(days=1) if fetched else None
            ),
        )
        # bulk_create, like the sibling task tests: Movie.save() reaches for
        # provider metadata to compute max progress, which this task ignores.
        Movie.objects.bulk_create(
            [
                Movie(
                    item=item,
                    user=self.user,
                    status=Status.IN_PROGRESS.value,
                    progress=0,
                ),
            ],
        )
        return item

    def test_fetched_items_have_score_and_rank_recomputed(self):
        item = self._tracked_movie(1)

        result = reconcile_trakt_popularity(score_version=7)

        item.refresh_from_db()
        expected_score = trakt_popularity_service.compute_popularity_score(8.0, 1200)
        self.assertAlmostEqual(item.trakt_popularity_score, expected_score, places=6)
        self.assertEqual(
            item.trakt_popularity_rank,
            trakt_popularity_service.estimate_rank_from_score(expected_score),
        )
        self.assertEqual(result["recomputed"], 1)
        self.assertEqual(result["total"], 1)

    def test_never_fetched_items_are_enqueued_and_not_written(self):
        item = self._tracked_movie(2, fetched=False)

        with (
            patch.object(
                trakt_popularity_service.trakt_provider,
                "is_configured",
                return_value=True,
            ),
            patch(
                "app.tasks_trakt.enqueue_trakt_popularity_backfill_items",
                return_value=1,
            ) as enqueue,
        ):
            result = reconcile_trakt_popularity()

        enqueue.assert_called_once()
        self.assertEqual(list(enqueue.call_args.args[0]), [item.id])
        self.assertEqual(result["recomputed"], 0)
        self.assertEqual(result["enqueued_for_fetch"], 1)

        item.refresh_from_db()
        self.assertIsNone(item.trakt_popularity_score)
        self.assertIsNone(item.trakt_popularity_rank)

    def test_unconfigured_provider_does_not_enqueue(self):
        self._tracked_movie(3, fetched=False)

        with (
            patch.object(
                trakt_popularity_service.trakt_provider,
                "is_configured",
                return_value=False,
            ),
            patch(
                "app.tasks_trakt.enqueue_trakt_popularity_backfill_items",
            ) as enqueue,
        ):
            result = reconcile_trakt_popularity()

        enqueue.assert_not_called()
        self.assertEqual(result["enqueued_for_fetch"], 0)

    def test_version_key_is_stamped_only_when_a_version_is_given(self):
        self._tracked_movie(4)

        reconcile_trakt_popularity()
        self.assertIsNone(cache.get("trakt_popularity_reconciled_v9"))

        reconcile_trakt_popularity(score_version=9)
        self.assertEqual(cache.get("trakt_popularity_reconciled_v9"), "done")

    def test_the_task_never_selects_the_large_item_columns(self):
        self._tracked_movie(5)

        with CaptureQueriesContext(connection) as queries:
            reconcile_trakt_popularity()

        selects = [
            query["sql"]
            for query in queries.captured_queries
            if query["sql"].lstrip().upper().startswith("SELECT")
        ]
        self.assertTrue(selects)
        for sql in selects:
            # Loading these to read four scalars is the whole 600 MiB bug.
            self.assertNotIn("watch_providers", sql)
            self.assertNotIn("synopsis", sql)

    def test_writes_scale_with_chunks_not_with_rows(self):
        rows = 25
        for media_id in range(100, 100 + rows):
            self._tracked_movie(media_id)

        with CaptureQueriesContext(connection) as queries:
            result = reconcile_trakt_popularity()

        self.assertEqual(result["recomputed"], rows)
        updates = [
            query["sql"]
            for query in queries.captured_queries
            if query["sql"].lstrip().upper().startswith("UPDATE")
        ]
        # One bulk_update per chunk, not one UPDATE per row. The original
        # implementation issued `rows` of them.
        expected_chunks = -(-rows // RECONCILE_CHUNK_SIZE)
        self.assertLessEqual(len(updates), expected_chunks)

    def test_rows_without_ratings_are_reset_rather_than_skipped(self):
        item = self._tracked_movie(200, rating=None, votes=None)

        reconcile_trakt_popularity()

        item.refresh_from_db()
        self.assertIsNone(item.trakt_popularity_score)
        self.assertIsNone(item.trakt_popularity_rank)
