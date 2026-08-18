from datetime import timedelta
from unittest.mock import patch

import requests
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from app.models import TV, Item, Season
from app.models.choices import MediaTypes, Sources, Status
from integrations import stremio_playback as playback
from integrations.imports.helpers import MediaImportError
from integrations.models import StremioAccount


class FakeRedis:
    def __init__(self):
        """Create an empty in-memory Redis script surface."""
        self.values = {}

    def eval(self, script, _keys, key, index_key, *args):
        if script == playback.CREATE_SCRIPT:
            value, _ttl = args
            if key not in self.values:
                self.values[key] = value
                self.values[index_key] = key
            return self.values[key]
        old, new, _ttl = args
        if self.values.get(key) != old:
            return 0
        if new:
            self.values[key] = new
        else:
            self.values.pop(key, None)
            self.values.pop(index_key, None)
        return 1

    def get(self, key):
        return self.values.get(key)


class StremioPlaybackRedisGuardTests(SimpleTestCase):
    def setUp(self):
        """Clear fakeredis so Lua guard behavior is isolated."""
        cache.clear()

    def test_real_redis_guard_atomically_reuses_active_session(self):
        now = timezone.now()
        first = playback.start_session(
            {"id": "tt-redis", "type": "movie"}, 999, now=now
        )
        duplicate = playback.start_session(
            {"id": "tt-redis", "type": "movie"},
            999,
            now=now + timedelta(minutes=31),
        )

        self.assertEqual(first.status, "schedule")
        self.assertEqual(duplicate.status, "duplicate")
        self.assertEqual(duplicate.session_id, first.session_id)
        _client, key, raw = playback._read_session(first.session_id)
        self.assertIsNotNone(key)
        self.assertEqual(playback._load(raw)["id"], first.session_id)


class StremioPlaybackSessionTests(TestCase):
    def setUp(self):
        self.redis = FakeRedis()
        self.now = timezone.now().replace(microsecond=0)
        self.user = get_user_model().objects.create_user(
            username="stremio-verifier", password="test"
        )
        StremioAccount.objects.create(user=self.user, auth_key="encrypted")
        self.library = []
        self.client_patch = patch.object(playback, "_client", return_value=self.redis)
        self.decrypt_patch = patch.object(
            playback.helpers, "decrypt_or_raise", return_value="auth"
        )
        self.library_patch = patch.object(
            playback, "get_library_items", side_effect=lambda _auth: self.library
        )
        self.client_patch.start()
        self.decrypt_patch.start()
        self.library_patch.start()
        self.addCleanup(self.client_patch.stop)
        self.addCleanup(self.decrypt_patch.stop)
        self.addCleanup(self.library_patch.stop)

    def state(
        self,
        media_id,
        percent,
        *,
        runtime_minutes=45,
        watched_at=None,
        flagged=0,
        times=0,
    ):
        duration = runtime_minutes * 60 * 1000
        return [
            {
                "_id": media_id.split(":", 1)[0],
                "state": {
                    "video_id": media_id,
                    "duration": duration,
                    "timeWatched": duration * percent / 100,
                    "timeOffset": 0,
                    "flaggedWatched": flagged,
                    "timesWatched": times,
                    "lastWatched": (watched_at or self.now).isoformat(),
                },
            }
        ]

    def start(self, media_id="tt100", media_type="movie"):
        decision = playback.start_session(
            {"id": media_id, "type": media_type}, self.user.id, now=self.now
        )
        self.assertEqual(decision.status, "schedule")
        return decision.session_id

    def observe(self, session_id, seconds):
        return playback.observe_session(
            session_id, now=self.now + timedelta(seconds=seconds)
        )

    def establish_movie_progress(self, runtime=45):
        session_id = self.start()
        self.library = self.state("tt100", 1, runtime_minutes=runtime)
        self.assertEqual(self.observe(session_id, 60).reason, "baseline_captured")
        return session_id

    def test_movie_completion_at_ninety_percent(self):
        session_id = self.establish_movie_progress()
        self.library = self.state(
            "tt100", 90, watched_at=self.now + timedelta(minutes=41), flagged=1
        )
        decision = self.observe(session_id, 41 * 60)
        self.assertEqual(decision.status, "complete")
        self.assertTrue(decision.payload["_floppy_verified_completion"])

    def test_runtime_deadlines_allow_normal_playback_to_reach_ninety_percent(self):
        for runtime in (45, 90, 120, 180):
            with self.subTest(runtime=runtime):
                self.redis.values.clear()
                session_id = self.establish_movie_progress(runtime)
                at_ninety = runtime * 60 * 0.9
                self.library = self.state(
                    "tt100",
                    90,
                    runtime_minutes=runtime,
                    watched_at=self.now + timedelta(seconds=at_ninety),
                    flagged=1,
                )
                decision = self.observe(session_id, at_ninety)
                self.assertEqual(decision.status, "complete")

    def test_normal_episode_completion(self):
        session_id = self.start("tt200:1:2", "series")
        self.library = self.state("tt200:1:2", 10)
        self.observe(session_id, 60)
        self.library = self.state(
            "tt200:1:2", 91, watched_at=self.now + timedelta(minutes=42), flagged=1
        )
        self.assertEqual(self.observe(session_id, 42 * 60).status, "complete")

    def test_pause_then_resume_are_current_session_progress(self):
        session_id = self.establish_movie_progress()
        self.assertEqual(self.observe(session_id, 120).status, "schedule")
        self.library = self.state(
            "tt100", 20, watched_at=self.now + timedelta(minutes=10)
        )
        self.assertEqual(self.observe(session_id, 600).status, "schedule")
        self.library = self.state(
            "tt100", 90, watched_at=self.now + timedelta(minutes=41), flagged=1
        )
        self.assertEqual(self.observe(session_id, 41 * 60).status, "complete")

    def test_seek_after_baseline_is_current_session_progress(self):
        session_id = self.establish_movie_progress()
        self.library = self.state(
            "tt100", 70, watched_at=self.now + timedelta(minutes=5)
        )
        self.assertEqual(self.observe(session_id, 300).status, "schedule")
        self.library = self.state(
            "tt100", 90, watched_at=self.now + timedelta(minutes=8), flagged=1
        )
        self.assertEqual(self.observe(session_id, 480).status, "complete")

    def test_slowly_published_state_does_not_complete_or_consume_failure_budget(self):
        session_id = self.establish_movie_progress()
        for second in (120, 180, 240):
            decision = self.observe(session_id, second)
            self.assertEqual(decision.status, "schedule")
        session = playback._load(
            next(value for value in self.redis.values.values() if value.startswith("{"))
        )
        self.assertEqual(session["transient_failures"], 0)
        self.library = self.state(
            "tt100", 90, watched_at=self.now + timedelta(minutes=41), flagged=1
        )
        self.assertEqual(self.observe(session_id, 41 * 60).status, "complete")

    def test_duplicate_request_after_ingress_window_reuses_active_session(self):
        first = self.start()
        with patch.object(playback.timezone, "now", return_value=self.now + timedelta(minutes=31)):
            duplicate = playback.start_session(
                {"id": "tt100", "type": "movie"}, self.user.id
            )
        self.assertEqual(duplicate.status, "duplicate")
        self.assertEqual(duplicate.session_id, first)

    def test_recent_replay_does_not_complete_from_stale_state(self):
        session_id = self.start()
        stale_time = self.now - timedelta(minutes=1)
        self.library = self.state("tt100", 95, watched_at=stale_time, flagged=1, times=1)
        self.observe(session_id, 60)
        self.assertEqual(self.observe(session_id, 90).status, "schedule")
        self.library = self.state("tt100", 2, watched_at=self.now + timedelta(minutes=2), times=1)
        self.observe(session_id, 120)
        self.library = self.state("tt100", 20, watched_at=self.now + timedelta(minutes=8), times=1)
        self.observe(session_id, 480)
        self.library = self.state("tt100", 92, watched_at=self.now + timedelta(minutes=43), flagged=1, times=2)
        self.assertEqual(self.observe(session_id, 43 * 60).status, "complete")

    def test_high_stale_baseline_without_sequential_transition_remains_pending(self):
        session_id = self.start("tt200:1:2", "series")
        stale_time = self.now - timedelta(minutes=1)
        self.library = self.state(
            "tt200:1:2", 95, watched_at=stale_time, flagged=1, times=1
        )
        self.assertEqual(self.observe(session_id, 60).reason, "baseline_captured")

        decision = self.observe(session_id, 120)

        self.assertEqual(decision.status, "schedule")

    def _local_season(self, episode_count):
        tv_item = Item.objects.create(
            media_id="123", source=Sources.TMDB.value, media_type=MediaTypes.TV.value,
            title="Show", provider_external_ids={"imdb_id": "tt200"},
        )
        tv = TV.objects.create(
            user=self.user, item=tv_item, status=Status.IN_PROGRESS.value
        )
        season_item = Item.objects.create(
            media_id="123", source=Sources.TMDB.value, media_type=MediaTypes.SEASON.value,
            title="Show", season_number=1, local_season_episode_count=episode_count,
        )
        Season.objects.create(
            user=self.user,
            item=season_item,
            related_tv=tv,
            status=Status.IN_PROGRESS.value,
        )

    def _auto_next(self, target, current):
        session_id = self.start(target, "series")
        self.library = self.state(target, 86, flagged=1)
        self.observe(session_id, 60)
        self.library = self.state(
            target, 87, watched_at=self.now + timedelta(minutes=40), flagged=1
        )
        self.observe(session_id, 40 * 60)
        self.library = self.state(current, 1, watched_at=self.now + timedelta(minutes=41))
        self.library[0]["_id"] = target.split(":", 1)[0]
        return self.observe(session_id, 41 * 60)

    def _baseline_auto_next(
        self,
        target,
        current,
        *,
        percent=86,
        flagged=1,
        baseline_watched_at=None,
    ):
        session_id = self.start(target, "series")
        self.library = self.state(
            target,
            percent,
            flagged=flagged,
            watched_at=baseline_watched_at,
        )
        self.assertEqual(self.observe(session_id, 60).reason, "baseline_captured")
        self.library = self.state(
            current,
            1,
            watched_at=self.now + timedelta(minutes=2),
        )
        self.library[0]["_id"] = target.split(":", 1)[0]
        return self.observe(session_id, 120)

    def test_target_baseline_can_support_immediate_same_season_auto_next(self):
        decision = self._baseline_auto_next("tt200:1:2", "tt200:1:3")
        self.assertEqual(decision.status, "complete")

    def test_target_baseline_can_support_authoritative_cross_season_auto_next(self):
        self._local_season(10)
        decision = self._baseline_auto_next("tt200:1:10", "tt200:2:1")
        self.assertEqual(decision.status, "complete")

    def test_stale_target_baseline_cannot_support_same_season_auto_next(self):
        stale = self.now - timedelta(
            seconds=playback.PUBLICATION_DELAY_TOLERANCE_SECONDS + 1
        )
        decision = self._baseline_auto_next(
            "tt200:1:2", "tt200:1:3", baseline_watched_at=stale
        )
        self.assertEqual(decision.status, "schedule")

    def test_stale_finale_baseline_cannot_support_cross_season_auto_next(self):
        self._local_season(10)
        stale = self.now - timedelta(
            seconds=playback.PUBLICATION_DELAY_TOLERANCE_SECONDS + 1
        )
        decision = self._baseline_auto_next(
            "tt200:1:10", "tt200:2:1", baseline_watched_at=stale
        )
        self.assertEqual(decision.status, "schedule")

    def test_baseline_inside_publication_tolerance_supports_auto_next(self):
        inside = self.now - timedelta(
            seconds=playback.PUBLICATION_DELAY_TOLERANCE_SECONDS - 1
        )
        decision = self._baseline_auto_next(
            "tt200:1:2", "tt200:1:3", baseline_watched_at=inside
        )
        self.assertEqual(decision.status, "complete")

    def test_baseline_outside_publication_tolerance_cannot_support_auto_next(self):
        outside = self.now - timedelta(
            seconds=playback.PUBLICATION_DELAY_TOLERANCE_SECONDS + 1
        )
        decision = self._baseline_auto_next(
            "tt200:1:2", "tt200:1:3", baseline_watched_at=outside
        )
        self.assertEqual(decision.status, "schedule")

    def test_target_baseline_does_not_allow_midseason_cross_season_jump(self):
        self._local_season(10)
        decision = self._baseline_auto_next("tt200:1:2", "tt200:2:1")
        self.assertEqual(decision.status, "superseded")

    def test_target_baseline_does_not_allow_unrelated_switch(self):
        decision = self._baseline_auto_next("tt200:1:2", "tt999:1:1")
        self.assertEqual(decision.status, "superseded")

    def test_target_baseline_below_threshold_does_not_complete_auto_next(self):
        decision = self._baseline_auto_next(
            "tt200:1:2",
            "tt200:1:3",
            percent=playback.AUTO_NEXT_THRESHOLD - 1,
        )
        self.assertEqual(decision.status, "schedule")

    def test_same_season_auto_next(self):
        self.assertEqual(self._auto_next("tt200:1:2", "tt200:1:3").status, "complete")

    def test_authoritative_final_episode_allows_cross_season_rollover(self):
        self._local_season(10)
        self.assertEqual(self._auto_next("tt200:1:10", "tt200:2:1").status, "complete")

    def test_midseason_cross_season_jump_is_rejected(self):
        self._local_season(10)
        decision = self._auto_next("tt200:1:2", "tt200:2:1")
        self.assertEqual(decision.status, "superseded")

    def test_cross_season_rollover_without_authority_is_rejected(self):
        decision = self._auto_next("tt200:1:10", "tt200:2:1")
        self.assertEqual(decision.status, "superseded")

    def test_unrelated_video_switch_supersedes(self):
        decision = self._auto_next("tt200:1:2", "tt999:1:1")
        self.assertEqual(decision.status, "superseded")

    def test_temporary_outage_recovers_and_resets_failure_budget(self):
        session_id = self.start()
        with patch.object(playback, "get_library_items", side_effect=requests.ConnectionError):
            self.assertEqual(self.observe(session_id, 60).status, "schedule")
        self.library = self.state("tt100", 1)
        self.assertEqual(self.observe(session_id, 120).reason, "baseline_captured")
        session = playback._load(
            next(value for value in self.redis.values.values() if value.startswith("{"))
        )
        self.assertEqual(session["transient_failures"], 0)

    def test_transient_failure_budget_is_bounded(self):
        session_id = self.start()
        with patch.object(playback, "get_library_items", side_effect=requests.ConnectionError):
            for attempt in range(1, playback.MAX_TRANSIENT_FAILURES + 1):
                decision = self.observe(session_id, attempt * 120)
                self.assertEqual(decision.status, "schedule")
            decision = self.observe(
                session_id, (playback.MAX_TRANSIENT_FAILURES + 1) * 120
            )
        self.assertEqual(
            (decision.status, decision.reason),
            ("terminal", "transient_budget_exhausted"),
        )

    def test_guard_failure_fails_closed(self):
        with patch.object(playback, "_client", return_value=None):
            decision = playback.start_session(
                {"id": "tt100", "type": "movie"}, self.user.id, now=self.now
            )
        self.assertEqual((decision.status, decision.reason), ("terminal", "guard_unavailable"))

    def test_disconnected_account_stops_immediately(self):
        session_id = self.start()
        account = self.user.stremio_account
        account.connection_broken = True
        account.save(update_fields=["connection_broken"])
        decision = self.observe(session_id, 60)
        self.assertEqual((decision.status, decision.reason), ("terminal", "account_disconnected"))

    def test_credential_failure_stops_immediately(self):
        session_id = self.start()
        with patch.object(
            playback.helpers, "decrypt_or_raise", side_effect=MediaImportError("bad")
        ):
            decision = self.observe(session_id, 60)
        self.assertEqual((decision.status, decision.reason), ("terminal", "credential_configuration"))

    def test_unexpected_programming_error_is_visible(self):
        session_id = self.start()
        with patch.object(playback, "get_library_items", side_effect=RuntimeError("bug")):
            with self.assertRaisesRegex(RuntimeError, "bug"):
                self.observe(session_id, 60)

    def test_duplicate_observations_claim_completion_once(self):
        session_id = self.establish_movie_progress()
        self.library = self.state(
            "tt100", 90, watched_at=self.now + timedelta(minutes=41), flagged=1
        )
        self.assertEqual(self.observe(session_id, 41 * 60).status, "complete")
        self.assertEqual(self.observe(session_id, 41 * 60).status, "duplicate")

    def test_completed_session_allows_a_genuine_replay(self):
        first = self.establish_movie_progress()
        self.library = self.state(
            "tt100", 90, watched_at=self.now + timedelta(minutes=41), flagged=1
        )
        self.assertEqual(self.observe(first, 41 * 60).status, "complete")
        replay = playback.start_session(
            {"id": "tt100", "type": "movie"},
            self.user.id,
            now=self.now + timedelta(minutes=42),
        )
        self.assertEqual(replay.status, "schedule")
        self.assertNotEqual(replay.session_id, first)

    def test_absolute_session_expiry(self):
        session_id = self.establish_movie_progress()
        decision = self.observe(session_id, 76 * 60)
        self.assertEqual(decision.status, "expired")
