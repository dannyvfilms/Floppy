"""Lease-ownership fencing for the Statistics sync (#1272 follow-up).

An expired worker must not renew or release a successor's lease, overwrite a
newer snapshot, clear dirty work added after its captured generation, or
regress synchronized-generation markers. These tests drive those schedules
deterministically — leases are expired and re-claimed from inside patched
build hooks, never by sleeping.
"""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from app import statistics_sync
from app.models import (
    Item,
    MediaTypes,
    Movie,
    Sources,
    StatisticsDirtyDay,
    StatisticsSnapshot,
    StatisticsSyncState,
    Status,
)


class LeaseFencingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username=f"fence-{self.id()[-40:]}", password="secret123"
        )
        item = Item.objects.create(
            media_id="fence-1",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.MOVIE.value,
            title="Fence movie",
            runtime_minutes=100,
        )
        Movie.objects.create(
            user=self.user,
            item=item,
            status=Status.COMPLETED.value,
            end_date=timezone.now() - timedelta(days=1),
            score=7,
        )
        # Creating the fixture fired marks; keep the state row (claims filter
        # on it) but start each test from clean dirty days.
        statistics_sync._ensure_state(self.user.id)
        StatisticsDirtyDay.objects.filter(user_id=self.user.id).delete()
        cache.clear()

    def tearDown(self):
        cache.clear()

    def state(self):
        return StatisticsSyncState.objects.get(user_id=self.user.id)

    def _expire(self, token):
        """Expire the given owner's lease as if its lease seconds elapsed."""
        StatisticsSyncState.objects.filter(
            user_id=self.user.id, lease_token=token
        ).update(lease_expires_at=timezone.now() - timedelta(seconds=1))

    def _snapshot(self, range_name="Today"):
        return StatisticsSnapshot.objects.get(
            user_id=self.user.id, range_name=range_name
        )

    def test_metadata_tracks_new_publication_after_warm_read(self):
        statistics_sync.publish_snapshot(self.user.id, "Today", {"count": 1}, 1)
        statistics_sync.load_snapshot_meta(self.user.id, "Today")
        statistics_sync.publish_snapshot(self.user.id, "Today", {"count": 2}, 2)
        self.assertEqual(
            statistics_sync.load_snapshot_meta(self.user.id, "Today")["generation"], 2
        )

    def test_metadata_does_not_survive_rolled_back_first_publication(self):
        from django.db import transaction

        with transaction.atomic():
            statistics_sync.publish_snapshot(self.user.id, "Today", {"count": 1}, 1)
            statistics_sync.load_snapshot_meta(self.user.id, "Today")
            transaction.set_rollback(True)
        self.assertIsNone(statistics_sync.load_snapshot_meta(self.user.id, "Today"))

    def test_second_claim_while_leased_is_rejected(self):
        first = statistics_sync._claim_lease(self.user.id, takeover=False)
        self.assertIsNotNone(first)
        self.assertIsNone(statistics_sync._claim_lease(self.user.id, takeover=False))
        # Takeover claims deliberately steal; fencing makes the victim inert.
        second = statistics_sync._claim_lease(self.user.id, takeover=True)
        self.assertIsNotNone(second)
        self.assertNotEqual(first, second)
        self.assertFalse(statistics_sync._renew_lease(self.user.id, first))

    def test_delayed_cache_publish_does_not_hide_newer_durable_snapshot(self):
        from app.statistics_cache import _cache_key

        key = _cache_key(self.user.id, "Today")
        real_set = cache.set
        delayed = []

        def publish_successor_before_old_cache_write(cache_key, entry, **kwargs):
            if cache_key == key and not delayed:
                delayed.append(True)
                statistics_sync.publish_snapshot(self.user.id, "Today", {"count": 2}, 2)
            return real_set(cache_key, entry, **kwargs)

        with patch.object(
            cache, "set", side_effect=publish_successor_before_old_cache_write
        ):
            statistics_sync.publish_snapshot(self.user.id, "Today", {"count": 1}, 1)

        self.assertEqual(self._snapshot().generation, 2)
        entry = statistics_sync.load_snapshot(self.user.id, "Today")
        self.assertEqual(entry["generation"], 2)
        self.assertEqual(entry["data"]["count"], 2)

    def test_rolled_back_snapshot_is_not_visible_from_cache(self):
        from django.db import transaction

        statistics_sync.publish_snapshot(self.user.id, "Today", {"count": 1}, 1)
        with transaction.atomic():
            statistics_sync.publish_snapshot(self.user.id, "Today", {"count": 2}, 2)
            transaction.set_rollback(True)

        self.assertEqual(self._snapshot().generation, 1)
        entry = statistics_sync.load_snapshot(self.user.id, "Today")
        self.assertEqual(entry["generation"], 1)
        self.assertEqual(entry["data"]["count"], 1)

    def test_rolled_back_first_publication_is_not_visible(self):
        from django.db import transaction

        with transaction.atomic():
            statistics_sync.publish_snapshot(self.user.id, "Today", {"count": 2}, 2)
            transaction.set_rollback(True)
        self.assertIsNone(statistics_sync.load_snapshot(self.user.id, "Today"))

    def test_equal_generation_rebuild_checks_the_publication_time(self):
        from app.statistics_cache import _cache_key

        key = _cache_key(self.user.id, "Today")
        statistics_sync.publish_snapshot(self.user.id, "Today", {"count": 1}, 1)
        old = cache.get(key)
        statistics_sync.publish_snapshot(self.user.id, "Today", {"count": 2}, 1)
        cache.set(key, old)
        self.assertEqual(
            statistics_sync.load_snapshot(self.user.id, "Today")["data"]["count"], 2
        )

    def test_cache_hit_only_reads_snapshot_metadata(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        statistics_sync.publish_snapshot(self.user.id, "Today", {"count": 1}, 1)
        with CaptureQueriesContext(connection) as queries:
            entry = statistics_sync.load_snapshot(self.user.id, "Today")
        self.assertEqual(entry["data"]["count"], 1)
        self.assertEqual(len(queries), 1)
        self.assertNotIn('"payload"', queries[0]["sql"])

    def test_cache_miss_reloads_payload_and_revision_together(self):
        statistics_sync.publish_snapshot(self.user.id, "Today", {"count": 1}, 1)

        def publish_during_cache_lookup(*args, **kwargs):
            statistics_sync.publish_snapshot(self.user.id, "Today", {"count": 2}, 2)

        with patch.object(cache, "get", side_effect=publish_during_cache_lookup):
            entry = statistics_sync.load_snapshot(self.user.id, "Today")
        self.assertEqual(entry["generation"], 2)
        self.assertEqual(entry["data"]["count"], 2)

    def test_lease_lost_during_day_build_cannot_overwrite_successor_days(self):
        from app.statistics_day_cache import _day_cache_key

        token = statistics_sync._claim_lease(self.user.id, takeover=False)
        day = timezone.localdate()
        key = _day_cache_key(self.user.id, day)

        def build_then_steal(*args, **kwargs):
            self._expire(token)
            statistics_sync._claim_lease(self.user.id, takeover=False)
            cache.set(key, {"owner": "successor"})
            return {"owner": "expired"}

        with (
            patch(
                "app.statistics_day_builder._build_prefetch_for_range", return_value={}
            ),
            patch(
                "app.statistics_day_builder.build_stats_for_day",
                side_effect=build_then_steal,
            ),
            self.assertRaises(statistics_sync._LostLeaseError),
        ):
            statistics_sync._build_days(self.user, [day], None, {}, lease_token=token)
        self.assertEqual(cache.get(key), {"owner": "successor"})

    def test_expired_owner_cannot_renew_or_release_successor_lease(self):
        worker_a = statistics_sync._claim_lease(self.user.id, takeover=False)
        self.assertIsNotNone(worker_a)
        self._expire(worker_a)
        worker_b = statistics_sync._claim_lease(self.user.id, takeover=False)
        self.assertIsNotNone(worker_b)

        # The expired worker's fenced operations all miss.
        self.assertFalse(statistics_sync._renew_lease(self.user.id, worker_a))
        statistics_sync._release_lease(self.user.id, worker_a)

        state = self.state()
        self.assertEqual(state.lease_token, worker_b)
        self.assertIsNotNone(state.lease_expires_at)
        self.assertTrue(statistics_sync.sync_is_running(self.user.id))

    def test_publication_of_dispossessed_worker_writes_nothing(self):
        worker_b = statistics_sync._claim_lease(self.user.id, takeover=False)
        statistics_sync._bump_generation(self.user.id, timezone.now())
        generation = self.state().generation
        statistics_sync.publish_snapshot(
            self.user.id, "Today", {"count": 7}, generation, lease_token=worker_b
        )
        self.assertEqual(self._snapshot().generation, generation)

        # A stale worker still holding an older generation and a dead token:
        # the fence stops it before any write, database or cache.
        self._expire(worker_b)
        stale_token = statistics_sync._claim_lease(self.user.id, takeover=False)
        self.assertIsNotNone(stale_token)
        self._expire(stale_token)
        worker_c = statistics_sync._claim_lease(self.user.id, takeover=False)
        self.assertIsNotNone(worker_c)
        with self.assertRaises(statistics_sync._LostLeaseError):
            statistics_sync.publish_snapshot(
                self.user.id,
                "Today",
                {"count": 3},
                generation - 1,
                lease_token=stale_token,
            )
        self.assertEqual(self._snapshot().generation, generation)
        self.assertEqual(self._snapshot().payload["count"], 7)

        # Even without a lease token (inline builders), an older generation
        # cannot regress the published snapshot or its cache copy.
        statistics_sync.publish_snapshot(
            self.user.id, "Today", {"count": 3}, generation - 1
        )
        self.assertEqual(self._snapshot().payload["count"], 7)
        from app.statistics_cache import _cache_key

        entry = cache.get(_cache_key(self.user.id, "Today"))
        self.assertEqual(entry["generation"], generation)
        self.assertEqual(entry["data"]["count"], 7)

    def test_lost_lease_mid_sync_reports_and_leaves_successor_state_alone(self):
        with patch.object(statistics_sync, "ensure_sync"):
            first = statistics_sync.run_sync(self.user.id)
        self.assertEqual(first["status"], "done")
        generation = self.state().generation

        statistics_sync.mark_aggregate(self.user.id, reason="test")
        stale_generation = self.state().generation

        real_aggregate = statistics_sync._aggregate_range
        stolen = []
        successor_token = []

        def aggregate_then_steal(user, range_name, hints, deadline=None, **kwargs):
            if not stolen:
                stolen.append(range_name)
                # The stale worker's lease lapses and a successor claims it,
                # advancing the synced markers beyond the stale generation.
                StatisticsSyncState.objects.filter(user_id=self.user.id).update(
                    lease_expires_at=timezone.now() - timedelta(seconds=1)
                )
                successor_token.append(
                    statistics_sync._claim_lease(self.user.id, takeover=False)
                )
                StatisticsSyncState.objects.filter(user_id=self.user.id).update(
                    hot_synced_generation=stale_generation + 5,
                    heavy_synced_generation=stale_generation + 5,
                )
            return real_aggregate(user, range_name, hints, deadline, **kwargs)

        with (
            patch.object(statistics_sync, "_aggregate_range", aggregate_then_steal),
            patch.object(statistics_sync, "ensure_sync"),
        ):
            result = statistics_sync.run_sync(self.user.id)

        self.assertEqual(result["status"], "lost_lease")
        state = self.state()
        # The stale pass did not regress the synced markers, did not record
        # an error, and did not release the successor's lease.
        self.assertEqual(state.hot_synced_generation, stale_generation + 5)
        self.assertEqual(state.heavy_synced_generation, stale_generation + 5)
        self.assertEqual(state.last_error, "")
        self.assertEqual(state.lease_token, successor_token[0])
        self.assertIsNotNone(state.lease_expires_at)
        # What it published before losing the lease stays at its generation.
        self.assertLessEqual(self._snapshot().generation, state.generation)
        self.assertGreater(generation, 0)

    def test_exception_path_releases_own_lease_and_records_error(self):
        def explode(user, range_name, hints, deadline=None, **kwargs):
            msg = "boom"
            raise ValueError(msg)

        with (
            patch.object(statistics_sync, "_aggregate_range", explode),
            patch.object(statistics_sync, "ensure_sync"),
        ):
            with self.assertRaises(ValueError):
                statistics_sync.run_sync(self.user.id)

        state = self.state()
        self.assertIsNone(state.lease_expires_at)
        self.assertIn("ValueError", state.last_error)

        # A stale token cannot scribble an error over a successor either.
        dead = statistics_sync._claim_lease(self.user.id, takeover=False)
        self._expire(dead)
        statistics_sync._claim_lease(self.user.id, takeover=False)
        StatisticsSyncState.objects.filter(user_id=self.user.id).update(last_error="")
        with patch.object(statistics_sync, "ensure_sync"):
            result = statistics_sync.run_sync(self.user.id)
        self.assertEqual(result["status"], "busy")
        self.assertEqual(self.state().last_error, "")
        self.assertTrue(statistics_sync.sync_is_running(self.user.id))

    def test_remarked_dirty_day_survives_stale_clear(self):
        """The dirty-row token fence: a day re-marked after a stale worker
        captured its tokens must stay dirty for the successor.
        """
        with patch.object(statistics_sync, "ensure_sync"):
            statistics_sync.run_sync(self.user.id)
        day = timezone.localdate() - timedelta(days=1)
        statistics_sync.mark_days(self.user.id, [day], reason="first")
        stale_tokens = dict(
            StatisticsDirtyDay.objects.filter(user_id=self.user.id).values_list(
                "day", "token"
            )
        )
        # Re-marked while the stale worker was building (new token).
        statistics_sync.mark_days(self.user.id, [day], reason="second")

        statistics_sync._clear_dirty(self.user.id, [day], stale_tokens)
        self.assertTrue(
            StatisticsDirtyDay.objects.filter(user_id=self.user.id, day=day).exists(),
            "a re-marked day must survive a stale worker's clear",
        )

        # The successor's captured tokens do clear it.
        fresh_tokens = dict(
            StatisticsDirtyDay.objects.filter(user_id=self.user.id).values_list(
                "day", "token"
            )
        )
        statistics_sync._clear_dirty(self.user.id, [day], fresh_tokens)
        self.assertFalse(
            StatisticsDirtyDay.objects.filter(user_id=self.user.id, day=day).exists()
        )

    def test_full_sweep_marker_survives_dispossessed_worker(self):
        with patch.object(statistics_sync, "ensure_sync"):
            statistics_sync.run_sync(self.user.id)
        StatisticsSyncState.objects.filter(user_id=self.user.id).update(
            full_sweep_requested_at=timezone.now()
        )
        stale_token = statistics_sync._claim_lease(self.user.id, takeover=False)
        self._expire(stale_token)
        successor = statistics_sync._claim_lease(self.user.id, takeover=False)
        self.assertIsNotNone(successor)

        # The stale worker's completion path must not clear the newer sweep.
        StatisticsSyncState.objects.filter(
            user_id=self.user.id,
            lease_token=stale_token,
            full_sweep_requested_at__lte=timezone.now(),
        ).update(full_sweep_requested_at=None)
        self.assertIsNotNone(self.state().full_sweep_requested_at)

        # The owner's path does.
        StatisticsSyncState.objects.filter(
            user_id=self.user.id,
            lease_token=successor,
            full_sweep_requested_at__lte=timezone.now(),
        ).update(full_sweep_requested_at=None)
        self.assertIsNone(self.state().full_sweep_requested_at)
