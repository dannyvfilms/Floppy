"""Startup claims remain exclusive until their scheduled sweeps can run."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from app.apps import STARTUP_SWEEP_COUNTDOWNS, AppConfig
from app.tasks_game_groups import GAME_GROUPS_BACKFILL_VERSION
from app.tasks_igdb_ratings import IGDB_RATINGS_BACKFILL_VERSION

CASES = (
    (
        "igdb_ratings",
        IGDB_RATINGS_BACKFILL_VERSION,
        "_schedule_igdb_rating_backfill_reconcile",
        "app.tasks_igdb_ratings.reconcile_igdb_rating_backfill.apply_async",
        "IGDB_RATINGS_BACKFILL_VERSION",
    ),
    (
        "game_groups",
        GAME_GROUPS_BACKFILL_VERSION,
        "_schedule_game_groups_backfill_reconcile",
        "app.tasks_game_groups.reconcile_game_groups_backfill.apply_async",
        "GAME_GROUPS_BACKFILL_VERSION",
    ),
)


class StaleReadCache:
    """Cache wrapper whose reads wait for the other reader before returning."""

    def __init__(self, real_cache, barrier):
        """Wrap ``real_cache``; reads rendezvous on ``barrier``."""
        self._real_cache = real_cache
        self._barrier = barrier

    def get(self, *args, **kwargs):
        value = self._real_cache.get(*args, **kwargs)
        self._barrier.wait(timeout=10)
        return value

    def __getattr__(self, name):
        """Delegate every other cache method untouched."""
        return getattr(self._real_cache, name)


class StartupReconcileClaimTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.config = AppConfig("app", import_module("app"))
        # The game-groups schedule first reopens rows that failed for lack of
        # IGDB credentials, which queries the database; these tests only cover
        # the claim logic and run without one.
        reopen = patch("app.tasks_game_groups.reopen_unconfigured_game_groups")
        reopen.start()
        self.addCleanup(reopen.stop)

    def tearDown(self):
        cache.clear()

    def test_pending_claim_survives_countdown_and_expires_for_lost_message(self):
        for field, _version, method, path, _ in CASES:
            with self.subTest(field=field):
                cache.clear()
                now = time.time()
                with patch(path) as publish:
                    with patch("time.time", return_value=now):
                        getattr(self.config, method)()
                    with patch("time.time", return_value=now + 301):
                        getattr(self.config, method)()
                    publish.assert_called_once()
                    with patch(
                        "time.time",
                        return_value=now + STARTUP_SWEEP_COUNTDOWNS[field] + 301,
                    ):
                        getattr(self.config, method)()
                    self.assertEqual(publish.call_count, 2)

    def test_concurrent_stale_reads_publish_only_one_message(self):
        # Patch module-level names, not attributes on ``cache`` or the Celery
        # task proxy: both resolve per thread, so a patch made here may not be
        # seen by the pool threads (CI then ran the real task eagerly).
        for field, _version, method, path, _ in CASES:
            with self.subTest(field=field):
                cache.clear()
                barrier = threading.Barrier(2)
                with (
                    patch(path.rsplit(".", 1)[0]) as task,
                    patch("app.apps.cache", StaleReadCache(cache, barrier)),
                    self.assertNoLogs("app.apps", level="WARNING"),
                    ThreadPoolExecutor(max_workers=2) as pool,
                ):
                    list(
                        pool.map(
                            lambda _, method=method: getattr(self.config, method)(),
                            range(2),
                        )
                    )
                task.apply_async.assert_called_once()

    def test_failed_publication_releases_claim_for_retry(self):
        for field, version, method, path, _ in CASES:
            with self.subTest(field=field):
                cache.clear()
                with patch(
                    path, side_effect=[RuntimeError("fixture broker failure"), None]
                ) as publish:
                    getattr(self.config, method)()
                    self.assertIsNone(cache.get(f"{field}_backfilled_v{version}"))
                    getattr(self.config, method)()
                self.assertEqual(publish.call_count, 2)
                self.assertEqual(cache.get(f"{field}_backfilled_v{version}"), "pending")

    def test_cache_failure_does_not_publish_an_unclaimed_sweep(self):
        for field, _version, method, path, _ in CASES:
            with self.subTest(field=field):
                cache.clear()
                with (
                    patch("app.apps.cache.add", side_effect=ConnectionError("fixture")),
                    patch(path) as publish,
                ):
                    getattr(self.config, method)()
                publish.assert_not_called()

    def test_completed_strategy_stays_quiet_and_new_strategy_can_run(self):
        for field, version, method, path, constant in CASES:
            with self.subTest(field=field):
                cache.clear()
                cache.set(f"{field}_backfilled_v{version}", "done", timeout=None)
                with patch(path) as publish:
                    getattr(self.config, method)()
                    publish.assert_not_called()
                    with patch(path.rsplit(".", 2)[0] + "." + constant, version + 1):
                        getattr(self.config, method)()
                    publish.assert_called_once()
                    self.assertEqual(
                        publish.call_args.kwargs["kwargs"]["strategy_version"],
                        version + 1,
                    )
