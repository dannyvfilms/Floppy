"""Tests for cache-backed live playback state and request-path purity."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from app import live_playback
from app.models import MediaTypes, Sources


class ApplyPlaybackEventImageTests(TestCase):
    """Image resolution happens when webhook events are applied."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="playbackimg",
            password="pw",
        )

    def tearDown(self):
        live_playback.clear_user_playback_state(self.user.id)
        cache.clear()
        super().tearDown()

    def _apply_play(self, **overrides):
        kwargs = {
            "user_id": self.user.id,
            "event_type": "media.play",
            "playback_media_type": MediaTypes.EPISODE.value,
            "media_id": "1396",
            "source": Sources.TMDB.value,
            "rating_key": "rk-1",
            "title": "Pilot",
            "series_title": "Breaking Bad",
            "episode_title": "Pilot",
            "season_number": 1,
            "episode_number": 1,
            "view_offset_seconds": 60,
            "duration_seconds": 3000,
        }
        kwargs.update(overrides)
        live_playback.apply_playback_event(**kwargs)

    @patch("app.live_playback._resolve_landscape_image")
    def test_play_event_stores_resolved_image_in_state(self, mock_resolve):
        mock_resolve.return_value = ("http://img.example/still.jpg", "primary")

        self._apply_play()

        state = live_playback.get_user_playback_state(self.user.id)
        self.assertEqual(state["image"], "http://img.example/still.jpg")
        self.assertEqual(state["image_source"], "primary")
        self.assertIn("image_resolved_at_ts", state)
        mock_resolve.assert_called_once()

    @patch("app.live_playback._resolve_landscape_image")
    def test_matching_state_carries_image_without_reresolving(self, mock_resolve):
        mock_resolve.return_value = ("http://img.example/still.jpg", "primary")

        self._apply_play()
        self._apply_play(event_type="media.pause", view_offset_seconds=120)

        state = live_playback.get_user_playback_state(self.user.id)
        self.assertEqual(state["image"], "http://img.example/still.jpg")
        self.assertEqual(state["status"], live_playback.PLAYBACK_STATUS_PAUSED)
        mock_resolve.assert_called_once()

    @patch("app.live_playback._resolve_landscape_image")
    def test_resolution_failure_leaves_state_usable(self, mock_resolve):
        mock_resolve.side_effect = RuntimeError("provider down")

        self._apply_play()

        state = live_playback.get_user_playback_state(self.user.id)
        self.assertIsNotNone(state)
        self.assertNotIn("image", state)


class FetchEpisodeStillCacheTests(TestCase):
    """Episode still lookups are cached, including failures."""

    def tearDown(self):
        cache.clear()
        super().tearDown()

    @patch("app.providers.tmdb.episode")
    def test_failure_is_negative_cached(self, mock_episode):
        mock_episode.side_effect = RuntimeError("tmdb 404")

        first = live_playback._fetch_episode_still("1", 2, 3)
        second = live_playback._fetch_episode_still("1", 2, 3)

        self.assertEqual(first, (None, "none"))
        self.assertEqual(second, (None, "none"))
        mock_episode.assert_called_once()

    @patch("app.providers.tmdb.episode")
    def test_success_is_cached(self, mock_episode):
        mock_episode.return_value = {
            "image": "http://img.example/ep.jpg",
            "image_source": "primary",
        }

        first = live_playback._fetch_episode_still("1", 2, 3)
        second = live_playback._fetch_episode_still("1", 2, 3)

        self.assertEqual(first, ("http://img.example/ep.jpg", "primary"))
        self.assertEqual(second, first)
        mock_episode.assert_called_once()


class RequestPathPurityTests(TestCase):
    """The playback card endpoints never call metadata providers."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="purity",
            password="pw",
        )
        self.client.force_login(self.user)

    def tearDown(self):
        live_playback.clear_user_playback_state(self.user.id)
        cache.clear()
        super().tearDown()

    def _seed_episode_state_without_image(self):
        now_ts = live_playback._now_ts()
        live_playback.set_user_playback_state(
            self.user.id,
            {
                "event_type": "media.play",
                "media_type": MediaTypes.EPISODE.value,
                "media_id": "1396",
                "source": Sources.TMDB.value,
                "rating_key": "rk-1",
                "title": "Pilot",
                "series_title": "Breaking Bad",
                "episode_title": "Pilot",
                "season_number": 1,
                "episode_number": 1,
                "view_offset_seconds": 60,
                "duration_seconds": 3000,
                "started_at_ts": now_ts,
                "status": live_playback.PLAYBACK_STATUS_PLAYING,
                "updated_at_ts": now_ts,
                "expires_at_ts": now_ts + 3600,
                "pause_expires_at_ts": None,
                "scrobble_expires_at_ts": None,
            },
        )

    @patch("app.tasks.resolve_playback_image.delay")
    @patch(
        "app.providers.services.api_request",
        side_effect=AssertionError("provider called from request path"),
    )
    def test_active_playback_fragment_never_calls_providers(
        self,
        _mock_api,
        mock_fill,
    ):
        self._seed_episode_state_without_image()

        response = self.client.get(reverse("active_playback_fragment"))

        self.assertEqual(response.status_code, 200)
        mock_fill.assert_called_once_with(self.user.id)

    @patch("app.tasks.resolve_playback_image.delay")
    @patch(
        "app.providers.services.api_request",
        side_effect=AssertionError("provider called from request path"),
    )
    def test_card_uses_stored_image_without_enqueueing(self, _mock_api, mock_fill):
        self._seed_episode_state_without_image()
        state = cache.get(live_playback._cache_key(self.user.id))
        state["image"] = "http://img.example/still.jpg"
        state["image_source"] = "primary"
        live_playback.set_user_playback_state(self.user.id, state)

        card = live_playback.build_home_playback_card(self.user)

        self.assertEqual(card["image"], "http://img.example/still.jpg")
        mock_fill.assert_not_called()

    @patch("app.tasks.resolve_playback_image.delay")
    @patch(
        "app.providers.services.api_request",
        side_effect=AssertionError("provider called from request path"),
    )
    def test_fill_task_enqueue_is_guarded(self, _mock_api, mock_fill):
        self._seed_episode_state_without_image()

        live_playback.build_home_playback_card(self.user)
        live_playback.build_home_playback_card(self.user)

        mock_fill.assert_called_once_with(self.user.id)


class ResolveStateImageTaskTests(TestCase):
    """The background fill-in task resolves and persists the image."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="filltask",
            password="pw",
        )

    def tearDown(self):
        live_playback.clear_user_playback_state(self.user.id)
        cache.clear()
        super().tearDown()

    @patch("app.live_playback._resolve_landscape_image")
    def test_resolve_state_image_fills_missing_image(self, mock_resolve):
        mock_resolve.return_value = ("http://img.example/still.jpg", "primary")
        now_ts = live_playback._now_ts()
        live_playback.set_user_playback_state(
            self.user.id,
            {
                "media_type": MediaTypes.EPISODE.value,
                "media_id": "1396",
                "source": Sources.TMDB.value,
                "status": live_playback.PLAYBACK_STATUS_PLAYING,
                "updated_at_ts": now_ts,
                "expires_at_ts": now_ts + 3600,
            },
        )

        live_playback.resolve_state_image(self.user.id)

        state = live_playback.get_user_playback_state(self.user.id)
        self.assertEqual(state["image"], "http://img.example/still.jpg")

    @patch("app.live_playback._resolve_landscape_image")
    def test_resolve_state_image_noops_when_image_present(self, mock_resolve):
        now_ts = live_playback._now_ts()
        live_playback.set_user_playback_state(
            self.user.id,
            {
                "media_type": MediaTypes.EPISODE.value,
                "media_id": "1396",
                "source": Sources.TMDB.value,
                "image": "http://img.example/still.jpg",
                "status": live_playback.PLAYBACK_STATUS_PLAYING,
                "updated_at_ts": now_ts,
                "expires_at_ts": now_ts + 3600,
            },
        )

        live_playback.resolve_state_image(self.user.id)

        mock_resolve.assert_not_called()
