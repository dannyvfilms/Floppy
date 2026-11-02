"""Tests for purging long-expired durable Discover cache rows."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from app.discover import cache_repo
from app.models import DiscoverApiCache, DiscoverRowCache, DiscoverTasteProfile
from app.tasks import purge_expired_discover_caches


class PurgeExpiredDiscoverCachesTests(TestCase):
    """Expired-row retention and bounded cleanup."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="u", password="x")
        self.now = timezone.now()

    def _seed(self, age: timedelta, tag: str):
        expires = self.now - age
        DiscoverApiCache.objects.create(
            provider="tmdb", endpoint=tag, params_hash=tag, expires_at=expires
        )
        DiscoverRowCache.objects.create(
            user=self.user, media_type="movie", row_key=tag, expires_at=expires
        )
        DiscoverTasteProfile.objects.create(
            user=self.user, media_type=tag, expires_at=expires
        )

    def test_purges_only_rows_past_retention(self):
        self._seed(timedelta(days=30), "old")
        self._seed(timedelta(days=1), "recently_expired")
        self._seed(-timedelta(days=1), "fresh")

        deleted = cache_repo.purge_expired_caches(now=self.now)

        self.assertEqual(
            deleted,
            {"DiscoverApiCache": 1, "DiscoverRowCache": 1, "DiscoverTasteProfile": 1},
        )
        self.assertEqual(
            set(DiscoverApiCache.objects.values_list("endpoint", flat=True)),
            {"recently_expired", "fresh"},
        )
        self.assertEqual(DiscoverRowCache.objects.count(), 2)
        self.assertEqual(DiscoverTasteProfile.objects.count(), 2)

    def test_stale_row_inside_retention_is_still_served_stale(self):
        cache_repo.set_row_cache(1, "movie", "k", {"a": 1}, ttl_seconds=-60)
        # Not purged, still readable as stale.
        DiscoverRowCache.objects.all().update(user=self.user)
        cache_repo.purge_expired_caches(now=self.now)
        payload, is_stale = cache_repo.get_row_cache(self.user.id, "movie", "k")
        self.assertEqual(payload, {"a": 1})
        self.assertTrue(is_stale)

    def test_bounded_per_call_and_drains_over_runs(self):
        for i in range(7):
            self._seed(timedelta(days=30), f"old{i}")

        first = cache_repo.purge_expired_caches(
            now=self.now, batch_size=2, max_batches=2
        )
        self.assertEqual(first["DiscoverApiCache"], 4)
        self.assertEqual(DiscoverApiCache.objects.count(), 3)

        cache_repo.purge_expired_caches(now=self.now, batch_size=2, max_batches=2)
        cache_repo.purge_expired_caches(now=self.now, batch_size=2, max_batches=2)
        self.assertEqual(DiscoverApiCache.objects.count(), 0)
        self.assertEqual(DiscoverRowCache.objects.count(), 0)
        self.assertEqual(DiscoverTasteProfile.objects.count(), 0)

    def test_task_runs(self):
        self._seed(timedelta(days=30), "old")
        result = purge_expired_discover_caches()
        self.assertEqual(result["DiscoverApiCache"], 1)
