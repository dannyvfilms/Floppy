from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from integrations.imports.helpers import encrypt
from integrations.models import JellyfinAccount
from integrations.tasks._webhook import _queue_jellyfin_instant_push

PUSH = "integrations.tasks._media_imports.push_jellyfin_watched.apply_async"


class JellyfinInstantPushTests(TestCase):
    """Webhook-triggered pushes are narrowed and coalesced (#1267)."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username="jf-instant-user")
        self.account = JellyfinAccount.objects.create(
            user=self.user,
            base_url="https://jellyfin.local:8096",
            api_key=encrypt("api-key"),
            jellyfin_user_id="jf-user-1",
            instant_push_enabled=True,
        )

    @patch(PUSH)
    def test_playback_events_queue_nothing(self, mock_push):
        for event in ("Play", "Pause", "PlaybackProgress", None):
            _queue_jellyfin_instant_push(self.user, {"Event": event})

        mock_push.assert_not_called()

    @patch(PUSH)
    def test_burst_of_stop_events_queues_one_delayed_push(self, mock_push):
        for _ in range(50):
            _queue_jellyfin_instant_push(self.user, {"Event": "Stop"})

        mock_push.assert_called_once()
        self.assertGreater(mock_push.call_args.kwargs["countdown"], 0)

    @patch("integrations.tasks._media_imports.JellyfinPushSyncService.sync")
    @patch(PUSH)
    def test_push_start_lets_the_next_event_queue_again(self, mock_push, mock_sync):
        from integrations.tasks._media_imports import push_jellyfin_watched

        mock_sync.return_value = ({}, "")
        _queue_jellyfin_instant_push(self.user, {"Event": "Stop"})
        push_jellyfin_watched(user_id=self.user.id)
        _queue_jellyfin_instant_push(self.user, {"Event": "MarkPlayed"})

        self.assertEqual(mock_push.call_count, 2)

    @patch(PUSH)
    def test_disabled_instant_push_queues_nothing(self, mock_push):
        self.account.instant_push_enabled = False
        self.account.save(update_fields=["instant_push_enabled"])

        _queue_jellyfin_instant_push(self.user, {"Event": "Stop"})

        mock_push.assert_not_called()
