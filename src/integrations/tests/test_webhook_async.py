"""Tests for asynchronous webhook processing.

Webhook views validate the request shape synchronously, then enqueue
integrations.tasks.process_webhook so external API lookups and DB writes
never block a web worker.
"""

import json
from datetime import timedelta
from unittest.mock import call, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone
from simple_history.models import HistoricalRecords

from app import live_playback
from app.models import Item, MediaTypes, PlaybackProgress, Sources
from integrations import tasks
from integrations.models import JellyfinAccount, PlexAccount, PlexWebhookShare
from integrations.webhooks.jellyfin import JellyfinWebhookProcessor
from integrations.webhooks.plex import PlexWebhookProcessor


class WebhookViewEnqueueTests(TestCase):
    """Webhook views enqueue the processing task instead of running inline."""

    def setUp(self):
        """Create a user and client."""
        self.client = Client()
        self.user = get_user_model().objects.create_user(
            username="webhookuser",
            password="12345",
            token="hook-token",
        )

    @patch("integrations.tasks.process_webhook.delay")
    def test_jellyfin_enqueues_task(self, mock_delay):
        """A valid Jellyfin payload is enqueued with the parsed payload."""
        url = reverse("jellyfin_webhook", kwargs={"token": "hook-token"})
        payload = {"Event": "Stop", "Item": {"Type": "Episode"}}
        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        mock_delay.assert_called_once_with("jellyfin", payload, self.user.id)

    @patch("integrations.tasks.process_webhook.delay")
    def test_plex_enqueues_task(self, mock_delay):
        """A valid Plex payload is enqueued with the parsed payload."""
        url = reverse("plex_webhook", kwargs={"token": "hook-token"})
        payload = {"event": "media.scrobble"}
        response = self.client.post(url, data={"payload": json.dumps(payload)})
        self.assertEqual(response.status_code, 200)
        mock_delay.assert_called_once_with("plex", payload, self.user.id)

    @patch("integrations.tasks.process_webhook.delay")
    def test_plex_enqueues_enabled_shared_recipient(self, mock_delay):
        """A matching enabled share receives the same Plex payload."""
        recipient = get_user_model().objects.create_user(username="recipient")
        PlexAccount.objects.create(
            user=self.user,
            plex_token="owner-plex-token",
            plex_username="webhookuser",
        )
        share = PlexWebhookShare.objects.create(
            owner=self.user,
            recipient=recipient,
            plex_username="PlexFriend",
            recipient_enabled=True,
            allowed_libraries=["machine-a::1"],
        )
        url = reverse("plex_webhook", kwargs={"token": "hook-token"})
        payload = {
            "event": "media.scrobble",
            "Account": {"title": "plexfriend"},
        }

        response = self.client.post(url, data={"payload": json.dumps(payload)})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            mock_delay.call_args_list,
            [
                call("plex", payload, self.user.id),
                call("plex", payload, recipient.id, share_id=share.id),
            ],
        )

    @patch("integrations.tasks.process_webhook.delay")
    def test_plex_does_not_enqueue_disabled_or_unmatched_shares(self, mock_delay):
        """Disabled and differently named shares do not receive events."""
        recipient = get_user_model().objects.create_user(username="recipient")
        PlexWebhookShare.objects.create(
            owner=self.user,
            recipient=recipient,
            plex_username="someone-else",
            recipient_enabled=True,
        )
        disabled_recipient = get_user_model().objects.create_user(
            username="disabled-recipient",
        )
        PlexWebhookShare.objects.create(
            owner=self.user,
            recipient=disabled_recipient,
            plex_username="testuser",
            recipient_enabled=False,
        )
        url = reverse("plex_webhook", kwargs={"token": "hook-token"})
        payload = {
            "event": "media.scrobble",
            "Account": {"title": "testuser"},
        }

        response = self.client.post(url, data={"payload": json.dumps(payload)})

        self.assertEqual(response.status_code, 200)
        mock_delay.assert_called_once_with("plex", payload, self.user.id)

    @patch("integrations.tasks.process_webhook.delay")
    def test_emby_enqueues_task(self, mock_delay):
        """A valid Emby payload is enqueued with the parsed payload."""
        url = reverse("emby_webhook", kwargs={"token": "hook-token"})
        payload = {"Event": "playback.stop"}
        response = self.client.post(url, data={"data": json.dumps(payload)})
        self.assertEqual(response.status_code, 200)
        mock_delay.assert_called_once_with("emby", payload, self.user.id)

    @patch("integrations.tasks.process_webhook.delay")
    def test_seerr_enqueues_task(self, mock_delay):
        """A valid Seerr payload is enqueued with the parsed payload."""
        # kept: unrenamed URL name (see plan)
        url = reverse("jellyseerr_webhook", kwargs={"token": "hook-token"})
        payload = {"notification_type": "MEDIA_APPROVED"}
        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        mock_delay.assert_called_once_with("seerr", payload, self.user.id)

    @patch("integrations.tasks.process_webhook.delay")
    def test_invalid_token_does_not_enqueue(self, mock_delay):
        """An invalid token returns 401 without touching the queue."""
        url = reverse("plex_webhook", kwargs={"token": "wrong-token"})
        response = self.client.post(url, data={"payload": "{}"})
        self.assertEqual(response.status_code, 401)
        mock_delay.assert_not_called()

    @patch("integrations.tasks.process_webhook.delay")
    def test_missing_plex_payload_does_not_enqueue(self, mock_delay):
        """A missing Plex payload returns 400, marks the error, no enqueue."""
        url = reverse("plex_webhook", kwargs={"token": "hook-token"})
        response = self.client.post(url, data={})
        self.assertEqual(response.status_code, 400)
        mock_delay.assert_not_called()
        self.user.refresh_from_db()
        self.assertIn("Missing payload", self.user.plex_webhook_last_error or "")


class ProcessWebhookTaskTests(TestCase):
    """Behavior of the process_webhook task itself."""

    def setUp(self):
        """Create a user."""
        self.user = get_user_model().objects.create_user(
            username="taskuser",
            password="12345",
            token="task-token",
        )

    @patch("integrations.webhooks.plex.PlexWebhookProcessor.process_payload")
    def test_plex_success_marks_received(self, mock_process):
        """A successful Plex run records the webhook as received."""
        tasks.process_webhook("plex", {"event": "media.scrobble"}, self.user.id)
        mock_process.assert_called_once()
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.plex_webhook_last_received_at)

    @patch("integrations.webhooks.plex.PlexWebhookProcessor.process_payload")
    def test_shared_plex_task_uses_owner_account_and_recipient(self, mock_process):
        """Shared processing attributes data to the recipient without sharing tokens."""
        recipient = get_user_model().objects.create_user(username="recipient")
        account = PlexAccount.objects.create(
            user=self.user,
            plex_token="owner-plex-token",
            plex_username="taskuser",
        )
        share = PlexWebhookShare.objects.create(
            owner=self.user,
            recipient=recipient,
            plex_username="plex-friend",
            allowed_libraries=["machine-a::1"],
            recipient_enabled=True,
        )
        payload = {"event": "media.scrobble"}

        tasks.process_webhook(
            "plex",
            payload,
            recipient.id,
            share_id=share.id,
        )

        mock_process.assert_called_once_with(
            payload,
            recipient,
            source_account=account,
            source_username="plex-friend",
            source_libraries=["machine-a::1"],
        )
        recipient.refresh_from_db()
        self.assertIsNone(recipient.plex_webhook_last_received_at)

    @patch("integrations.webhooks.plex.PlexWebhookProcessor.process_payload")
    def test_revoked_shared_plex_task_is_skipped(self, mock_process):
        """A queued task does nothing after the recipient disables the share."""
        recipient = get_user_model().objects.create_user(username="recipient")
        PlexAccount.objects.create(
            user=self.user,
            plex_token="owner-plex-token",
            plex_username="taskuser",
        )
        share = PlexWebhookShare.objects.create(
            owner=self.user,
            recipient=recipient,
            plex_username="plex-friend",
            recipient_enabled=False,
        )

        tasks.process_webhook("plex", {"event": "media.scrobble"}, recipient.id, share_id=share.id)

        mock_process.assert_not_called()

    @patch("integrations.webhooks.plex.PlexWebhookProcessor.process_payload")
    def test_plex_failure_marks_error_and_reraises(self, mock_process):
        """A failing Plex run marks the error for the user and re-raises."""
        mock_process.side_effect = ValueError("boom")
        with self.assertRaises(ValueError):
            tasks.process_webhook("plex", {"event": "media.scrobble"}, self.user.id)
        self.user.refresh_from_db()
        self.assertIn("processing failed", self.user.plex_webhook_last_error or "")

    @patch("integrations.webhooks.jellyfin.JellyfinWebhookProcessor.process_payload")
    def test_history_user_context_set_during_processing(self, mock_process):
        """History rows created during processing are attributed to the user."""
        seen = {}

        def capture_context(_payload, _user):
            request = getattr(HistoricalRecords.context, "request", None)
            seen["user"] = getattr(request, "user", None)

        mock_process.side_effect = capture_context
        tasks.process_webhook("jellyfin", {"Event": "Stop"}, self.user.id)
        self.assertEqual(seen["user"], self.user)
        self.assertFalse(hasattr(HistoricalRecords.context, "request"))

    def test_missing_user_logs_and_returns(self):
        """A deleted user is logged and skipped without raising."""
        missing_id = self.user.id + 999
        with self.assertLogs("integrations.tasks", level="WARNING") as logs:
            tasks.process_webhook("jellyfin", {"Event": "Stop"}, missing_id)
        self.assertIn("missing user", logs.output[0])

    @patch("integrations.tasks.push_jellyfin_watched.delay")
    @patch("integrations.webhooks.jellyfin.JellyfinWebhookProcessor.process_payload")
    def test_jellyfin_instant_push_when_enabled(self, _mock_process, mock_push_delay):
        """A Jellyfin webhook should queue a push-back when instant push is enabled."""
        JellyfinAccount.objects.create(
            user=self.user,
            base_url="https://jellyfin.local:8096",
            api_key="encrypted",
            jellyfin_user_id="jf-1",
            instant_push_enabled=True,
        )

        tasks.process_webhook("jellyfin", {"Event": "Stop"}, self.user.id)

        mock_push_delay.assert_called_once_with(user_id=self.user.id)

    @patch("integrations.tasks.push_jellyfin_watched.delay")
    @patch("integrations.webhooks.jellyfin.JellyfinWebhookProcessor.process_payload")
    def test_jellyfin_instant_push_skipped_when_disabled(
        self,
        _mock_process,
        mock_push_delay,
    ):
        """No push-back should be queued when instant push is not enabled."""
        JellyfinAccount.objects.create(
            user=self.user,
            base_url="https://jellyfin.local:8096",
            api_key="encrypted",
            jellyfin_user_id="jf-1",
            instant_push_enabled=False,
        )

        tasks.process_webhook("jellyfin", {"Event": "Stop"}, self.user.id)

        mock_push_delay.assert_not_called()

    @patch("integrations.tasks.push_jellyfin_watched.delay")
    @patch("integrations.webhooks.jellyfin.JellyfinWebhookProcessor.process_payload")
    def test_jellyfin_instant_push_skipped_without_account(
        self,
        _mock_process,
        mock_push_delay,
    ):
        """No push-back should be queued when Jellyfin isn't connected."""
        tasks.process_webhook("jellyfin", {"Event": "Stop"}, self.user.id)

        mock_push_delay.assert_not_called()


class WebhookPlaybackProgressTests(TestCase):
    """Webhook playback events persist a durable resume position.

    Exercised through app.live_playback.apply_playback_event, which the
    Plex, Jellyfin and Emby processors all delegate to.
    """

    def setUp(self):
        """Create a user and the items webhook events resolve to."""
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="playbackuser",
            password="12345",
        )
        self.movie_item = Item.objects.create(
            media_id="701",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Matrix",
        )
        self.episode_item = Item.objects.create(
            media_id="103516",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Episode Four",
            season_number=4,
            episode_number=4,
        )

    def _apply(self, event_type, **overrides):
        kwargs = {
            "user_id": self.user.id,
            "event_type": event_type,
            "playback_media_type": MediaTypes.MOVIE.value,
            "media_id": "701",
            "source": Sources.TMDB.value,
            "rating_key": "rk-1",
            "title": "The Matrix",
            "view_offset_seconds": 1380,
            "duration_seconds": 8160,
            "store_progress": True,
        }
        kwargs.update(overrides)
        live_playback.apply_playback_event(**kwargs)

    @patch("app.live_playback._attach_resolved_image")
    def test_pause_stores_position(self, _mock_image):
        """A pause part-way through a movie is written to the store."""
        self._apply("media.pause")

        progress = PlaybackProgress.objects.get(
            user=self.user,
            item=self.movie_item,
        )
        self.assertEqual(progress.position_seconds, 1380)
        self.assertEqual(progress.duration_seconds, 8160)
        self.assertFalse(progress.completed)

    @patch("app.live_playback._attach_resolved_image")
    def test_stop_stores_episode_position(self, _mock_image):
        """Stopping an episode records its own position, not the show's."""
        self._apply(
            "media.play",
            playback_media_type=MediaTypes.EPISODE.value,
            media_id="103516",
            season_number=4,
            episode_number=4,
            view_offset_seconds=60,
        )
        self._apply(
            "media.stop",
            playback_media_type=MediaTypes.EPISODE.value,
            media_id="103516",
            season_number=4,
            episode_number=4,
            view_offset_seconds=1500,
        )

        progress = PlaybackProgress.objects.get(user=self.user)
        self.assertEqual(progress.item, self.episode_item)
        self.assertEqual(progress.position_seconds, 1500)
        self.assertFalse(progress.completed)

    @patch("app.live_playback._attach_resolved_image")
    def test_scrobble_marks_completed(self, _mock_image):
        """The media server's own completion mark sets completed."""
        self._apply("media.scrobble", view_offset_seconds=8000)

        progress = PlaybackProgress.objects.get(user=self.user)
        self.assertEqual(progress.position_seconds, 8000)
        self.assertTrue(progress.completed)

    @patch("app.live_playback._attach_resolved_image")
    def test_play_does_not_store_position(self, _mock_image):
        """Play events are ignored: their offset is usually a reset to 0."""
        self._apply("media.play", view_offset_seconds=0)

        self.assertFalse(PlaybackProgress.objects.exists())

    @patch("app.live_playback._attach_resolved_image")
    def test_resume_after_seek_stores_new_position(self, _mock_image):
        """Plex reports a seek as a resume carrying the new offset."""
        self._apply("media.pause", view_offset_seconds=600)
        self._apply("media.resume", view_offset_seconds=4800)

        progress = PlaybackProgress.objects.get(user=self.user)
        self.assertEqual(progress.position_seconds, 4800)

    @patch("app.live_playback._attach_resolved_image")
    def test_resume_without_offset_keeps_stored_position(self, _mock_image):
        """A resume that reports no position must not zero the stored one."""
        self._apply("media.pause", view_offset_seconds=600)
        cache.clear()
        self._apply("media.resume", view_offset_seconds=None)

        progress = PlaybackProgress.objects.get(user=self.user)
        self.assertEqual(progress.position_seconds, 600)

    @patch("app.live_playback._attach_resolved_image")
    def test_position_is_updated_not_duplicated(self, _mock_image):
        """Repeated pauses overwrite the single row for that item."""
        self._apply("media.pause", view_offset_seconds=600)
        self._apply("media.pause", view_offset_seconds=1800)

        self.assertEqual(PlaybackProgress.objects.count(), 1)
        progress = PlaybackProgress.objects.get(user=self.user)
        self.assertEqual(progress.position_seconds, 1800)

    @patch("app.live_playback._attach_resolved_image")
    def test_unknown_item_is_skipped(self, _mock_image):
        """An event for media that isn't in the library writes nothing."""
        self._apply("media.pause", media_id="999999")

        self.assertFalse(PlaybackProgress.objects.exists())

    @patch("app.live_playback._attach_resolved_image")
    def test_episode_without_episode_item_is_skipped(self, _mock_image):
        """A show-level fallback match must not be stored as a position."""
        Item.objects.create(
            media_id="555",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Unwatched Show",
        )

        self._apply(
            "media.pause",
            playback_media_type=MediaTypes.EPISODE.value,
            media_id="555",
            season_number=1,
            episode_number=1,
        )

        self.assertFalse(PlaybackProgress.objects.exists())

    @patch("app.live_playback._attach_resolved_image")
    def test_scrobble_api_path_does_not_double_write(self, _mock_image):
        """Without store_progress the cache is updated but nothing persisted."""
        self._apply("media.pause", store_progress=False)

        self.assertFalse(PlaybackProgress.objects.exists())

    @patch("app.live_playback._attach_resolved_image")
    def test_write_failure_does_not_break_the_webhook(self, _mock_image):
        """A failing progress write is swallowed; the cache still updates."""
        with patch(
            "api.fork_views_playback.upsert_playback_progress",
            side_effect=OSError("db gone"),
        ):
            self._apply("media.pause")

        self.assertFalse(PlaybackProgress.objects.exists())
        self.assertIsNotNone(live_playback.get_user_playback_state(self.user.id))

    @patch("app.live_playback._attach_resolved_image")
    def test_stop_after_scrobble_keeps_completed(self, _mock_image):
        """Plex sends stop right after scrobble; that must not un-complete."""
        self._apply("media.scrobble", view_offset_seconds=8100)
        self._apply("media.stop", view_offset_seconds=8160)

        progress = PlaybackProgress.objects.get(user=self.user)
        self.assertTrue(progress.completed)
        self.assertEqual(progress.position_seconds, 8160)

    @patch("app.live_playback._attach_resolved_image")
    def test_stop_stores_position_with_cold_cache(self, _mock_image):
        """A stop must persist even when no card state is cached."""
        cache.clear()

        self._apply("media.stop", view_offset_seconds=2400)

        progress = PlaybackProgress.objects.get(user=self.user)
        self.assertEqual(progress.position_seconds, 2400)

    @patch("app.live_playback._attach_resolved_image")
    def test_event_without_offset_keeps_stored_position(self, _mock_image):
        """A missing offset means "no position", not position zero."""
        self._apply("media.pause", view_offset_seconds=1200)
        cache.clear()  # no cached offset to fall back on
        self._apply("media.pause", view_offset_seconds=None)

        progress = PlaybackProgress.objects.get(user=self.user)
        self.assertEqual(progress.position_seconds, 1200)

    @patch("app.live_playback._attach_resolved_image")
    def test_scrobble_without_offset_marks_completed(self, _mock_image):
        """Plex scrobbles carry no offset; they must still complete."""
        self._apply("media.pause", view_offset_seconds=5000)
        self._apply("media.scrobble", view_offset_seconds=None)

        progress = PlaybackProgress.objects.get(user=self.user)
        self.assertTrue(progress.completed)
        self.assertEqual(progress.position_seconds, 5000)

    @patch("app.live_playback._attach_resolved_image")
    def test_rewatch_from_the_start_clears_completion(self, _mock_image):
        """Restarting a finished title must clear its completion mark."""
        self._apply("media.scrobble", view_offset_seconds=8100)

        self._apply("media.pause", view_offset_seconds=120)

        progress = PlaybackProgress.objects.get(user=self.user)
        self.assertFalse(progress.completed)
        self.assertEqual(progress.position_seconds, 120)

    @patch("app.live_playback._attach_resolved_image")
    def test_stop_long_after_scrobble_keeps_completed(self, _mock_image):
        """Elapsed time must not decide whether a completion survives.

        Plex scrobbles at ~90%, so on a long film the trailing stop can
        arrive far later in wall-clock terms while still being at the end
        of the title.
        """
        self._apply("media.scrobble", view_offset_seconds=7300)
        # queryset update() bypasses auto_now, so the row really ages.
        PlaybackProgress.objects.filter(user=self.user).update(
            updated_at=timezone.now() - timedelta(minutes=30),
        )

        self._apply("media.stop", view_offset_seconds=8160)

        progress = PlaybackProgress.objects.get(user=self.user)
        self.assertTrue(progress.completed)

    @patch("app.live_playback._attach_resolved_image")
    def test_stop_with_foreign_rating_key_writes_nothing(self, _mock_image):
        """Identifiers are only reused when the rating key matches."""
        self._apply("media.pause", view_offset_seconds=600)
        self.assertEqual(PlaybackProgress.objects.count(), 1)

        self._apply(
            "media.stop",
            media_id=None,
            rating_key="some-other-playback",
            view_offset_seconds=4200,
        )

        progress = PlaybackProgress.objects.get(user=self.user)
        self.assertEqual(progress.position_seconds, 600)

    @patch("app.live_playback._attach_resolved_image")
    def test_stop_without_identifiers_writes_nothing(self, _mock_image):
        """A stop that identifies nothing must not adopt a cached title."""
        self._apply("media.pause", view_offset_seconds=600)
        self.assertEqual(PlaybackProgress.objects.count(), 1)

        self._apply(
            "media.stop",
            media_id=None,
            rating_key=None,
            view_offset_seconds=4200,
        )

        progress = PlaybackProgress.objects.get(user=self.user)
        self.assertEqual(progress.position_seconds, 600)


class JellyfinWebhookProgressTests(TestCase):
    """The Jellyfin processor stores positions end to end."""

    def setUp(self):
        """Create a user and the movie the payload resolves to."""
        cache.clear()
        self.user = get_user_model().objects.create_user(username="jellyfinuser")
        self.item = Item.objects.create(
            media_id="701",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Matrix",
        )

    @patch("app.live_playback._attach_resolved_image")
    def test_stop_payload_stores_position(self, _mock_image):
        """A Jellyfin stop payload persists the position from its ticks."""
        processor = JellyfinWebhookProcessor()
        processor._update_live_playback_state(
            {
                "Event": "Stop",
                "Item": {
                    "Id": "jf-1",
                    "Name": "The Matrix",
                    "RunTimeTicks": 81_600_000_000,  # 8160s
                    "PlaybackPositionTicks": 13_800_000_000,  # 1380s
                },
            },
            self.user,
            {"tmdb_id": "701"},
            MediaTypes.MOVIE.value,
        )

        progress = PlaybackProgress.objects.get(user=self.user, item=self.item)
        self.assertEqual(progress.position_seconds, 1380)
        self.assertEqual(progress.duration_seconds, 8160)


class PlexWebhookProgressTests(TestCase):
    """The Plex processor stores episode positions end to end.

    Plex only resolves the show id on play/resume/scrobble, so a pause or
    stop has to recover it from the cached state of the same playback.
    """

    def setUp(self):
        """Create a user and the episode the payload resolves to.

        Plex resolves episodes to the *show* TMDB id, so the episode Item
        is keyed on that id rather than an episode-level one.
        """
        cache.clear()
        self.user = get_user_model().objects.create_user(username="plexuser")
        self.episode_item = Item.objects.create(
            media_id="1416",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Episode Four",
            season_number=4,
            episode_number=4,
        )

    def _payload(self, event, offset_ms):
        return {
            "event": event,
            "Metadata": {
                "ratingKey": "plex-rk-1",
                "type": "episode",
                "title": "Episode Four",
                "grandparentTitle": "Some Show",
                "parentIndex": 4,
                "index": 4,
                "viewOffset": offset_ms,
                "duration": 2_700_000,
            },
        }

    @patch(
        "integrations.webhooks.plex.PlexWebhookProcessor._find_tv_media_id",
        return_value=("1416", None, None),
    )
    @patch("app.live_playback._attach_resolved_image")
    def test_episode_pause_stores_position_after_play(self, _mock_image, _mock_find):
        """Play resolves the show id; the following pause reuses it."""
        processor = PlexWebhookProcessor()
        # Play: Plex resolves the show-level id from the payload ids.
        processor._update_live_playback_state(
            self._payload("media.play", 30_000),
            self.user,
            {"tmdb_id": "1416", "tvdb_id": None, "imdb_id": None},
            MediaTypes.EPISODE.value,
        )
        # Pause: the processor deliberately leaves media_id unresolved.
        processor._update_live_playback_state(
            self._payload("media.pause", 1_500_000),
            self.user,
            {"tmdb_id": None, "tvdb_id": None, "imdb_id": None},
            MediaTypes.EPISODE.value,
        )

        progress = PlaybackProgress.objects.get(user=self.user)
        self.assertEqual(progress.item, self.episode_item)
        self.assertEqual(progress.position_seconds, 1500)


class WebhookTaskRoutingTests(SimpleTestCase):
    """Webhook processing must never wait behind imports or backfills."""

    def test_webhook_task_routes_to_interactive_queue_at_top_priority(self):
        """The task runs on the interactive worker with interactive priority."""
        route = settings.CELERY_TASK_ROUTES[tasks.process_webhook.name]
        self.assertEqual(route["queue"], "interactive")
        self.assertEqual(
            route["priority"],
            settings.CELERY_TASK_PRIORITY_INTERACTIVE,
        )

    def test_stremio_task_has_bounded_limits_and_interactive_route(self):
        """Stremio playback cannot occupy the worker indefinitely."""
        route = settings.CELERY_TASK_ROUTES[tasks.process_stremio_webhook.name]
        self.assertEqual(route["queue"], "interactive")
        self.assertEqual(
            route["priority"],
            settings.CELERY_TASK_PRIORITY_INTERACTIVE,
        )
        self.assertEqual(tasks.process_stremio_webhook.soft_time_limit, 90)
        self.assertEqual(tasks.process_stremio_webhook.time_limit, 120)
