"""Tests for asynchronous webhook processing.

Webhook views validate the request shape synchronously, then enqueue
integrations.tasks.process_webhook so external API lookups and DB writes
never block a web worker.
"""

import json
from contextlib import suppress
from datetime import timedelta
from unittest.mock import ANY, call, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from simple_history.models import HistoricalRecords

from app.providers import credentials
from integrations import tasks
from integrations.models import JellyfinAccount, PlexAccount, PlexWebhookShare


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
    def test_inactive_user_webhooks_are_not_enqueued(self, mock_delay):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        for provider in ("jellyfin", "plex", "emby", "jellyseerr", "kodi"):
            with self.subTest(provider=provider):
                response = self.client.post(
                    reverse(f"{provider}_webhook", kwargs={"token": self.user.token}),
                    data="{}",
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 401)
        mock_delay.assert_not_called()

    @patch("integrations.tasks.process_webhook.delay")
    def test_malformed_json_does_not_enqueue(self, mock_delay):
        for provider in ("jellyfin", "emby"):
            with self.subTest(provider=provider):
                url = reverse(f"{provider}_webhook", kwargs={"token": self.user.token})
                response = (
                    self.client.post(url, data={"data": "{"})
                    if provider == "emby"
                    else self.client.post(
                        url, data="{", content_type="application/json"
                    )
                )
                self.assertEqual(response.status_code, 400)
        mock_delay.assert_not_called()

    @patch("integrations.tasks.process_webhook.delay")
    def test_non_object_payloads_do_not_enqueue(self, mock_delay):
        for provider in ("jellyfin", "emby"):
            for payload in ("null", "[]", '"text"'):
                with self.subTest(provider=provider, payload=payload):
                    url = reverse(
                        f"{provider}_webhook", kwargs={"token": self.user.token}
                    )
                    response = (
                        self.client.post(url, data={"data": payload})
                        if provider == "emby"
                        else self.client.post(
                            url, data=payload, content_type="application/json"
                        )
                    )
                    self.assertEqual(response.status_code, 400)
        mock_delay.assert_not_called()

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
        mock_delay.assert_called_once_with(
            "jellyfin",
            payload,
            self.user.id,
            received_at=ANY,
            event_id=ANY,
        )

    @patch("integrations.tasks.process_webhook.delay")
    def test_plex_enqueues_task(self, mock_delay):
        """A valid Plex payload is enqueued with the parsed payload."""
        url = reverse("plex_webhook", kwargs={"token": "hook-token"})
        payload = {"event": "media.scrobble"}
        response = self.client.post(url, data={"payload": json.dumps(payload)})
        self.assertEqual(response.status_code, 200)
        mock_delay.assert_called_once_with(
            "plex",
            payload,
            self.user.id,
            received_at=ANY,
            event_id=ANY,
        )

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
                call(
                    "plex",
                    payload,
                    self.user.id,
                    received_at=ANY,
                    event_id=ANY,
                ),
                call(
                    "plex",
                    payload,
                    recipient.id,
                    share_id=share.id,
                    received_at=ANY,
                    event_id=ANY,
                ),
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
        mock_delay.assert_called_once_with(
            "plex",
            payload,
            self.user.id,
            received_at=ANY,
            event_id=ANY,
        )

    @patch("integrations.tasks.process_webhook.delay")
    def test_emby_enqueues_task(self, mock_delay):
        """A valid Emby payload is enqueued with the parsed payload."""
        url = reverse("emby_webhook", kwargs={"token": "hook-token"})
        payload = {"Event": "playback.stop"}
        response = self.client.post(url, data={"data": json.dumps(payload)})
        self.assertEqual(response.status_code, 200)
        mock_delay.assert_called_once_with(
            "emby",
            payload,
            self.user.id,
            received_at=ANY,
            event_id=ANY,
        )

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
    def test_user_deactivated_after_enqueue_is_not_processed(self, mock_process):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        tasks.process_webhook("plex", {"event": "media.scrobble"}, self.user.id)
        mock_process.assert_not_called()

    @patch("integrations.webhooks.plex.PlexWebhookProcessor.process_payload")
    def test_plex_success_marks_received(self, mock_process):
        """A successful Plex run records the webhook as received."""
        tasks.process_webhook("plex", {"event": "media.scrobble"}, self.user.id)
        mock_process.assert_called_once()
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.plex_webhook_last_received_at)

    @patch("integrations.webhooks.plex.PlexWebhookProcessor.process_payload")
    def test_webhook_logs_queue_delay_and_structured_outcome(self, mock_process):
        """Receipt, worker start and finish share one event id and outcome."""
        mock_process.return_value = None
        received_at = (timezone.now() - timedelta(seconds=2)).isoformat()

        with self.assertLogs("integrations.tasks", level="INFO") as logs:
            tasks.process_webhook(
                "plex",
                {"event": "media.scrobble", "Metadata": {"ratingKey": "42"}},
                self.user.id,
                received_at=received_at,
                event_id="abc123",
            )

        output = "\n".join(logs.output)
        self.assertIn("webhook_started event_id=abc123 provider=plex", output)
        self.assertIn("rating_key=42", output)
        self.assertIn("queue_delay_ms=", output)
        self.assertIn("queue_delay_bucket=", output)
        self.assertIn("webhook_finished event_id=abc123", output)
        self.assertIn("outcome=skipped", output)
        self.assertIn("elapsed_ms=", output)

    @patch("integrations.webhooks.plex.PlexWebhookProcessor.process_payload")
    def test_slow_queue_wait_logs_a_warning(self, mock_process):
        """A queue wait past the threshold is called out, not just recorded."""
        mock_process.return_value = None
        received_at = (timezone.now() - timedelta(seconds=30)).isoformat()

        with self.assertLogs("integrations.tasks", level="WARNING") as logs:
            tasks.process_webhook(
                "plex",
                {"event": "media.scrobble"},
                self.user.id,
                received_at=received_at,
                event_id="slow1",
            )

        self.assertIn("webhook_slow_queue event_id=slow1", "\n".join(logs.output))

    @patch("integrations.webhooks.plex.PlexWebhookProcessor.process_payload")
    def test_plex_payload_log_omits_identity_and_activity_values(self, _mock_process):
        """Worker diagnostics retain structure without copying private values."""
        payload = {
            "event": "media.play",
            "Account": {"id": 1234, "thumb": "https://plex.tv/a", "title": "alice"},
            "Server": {"title": "Home", "uuid": "server-abc"},
            "Player": {"local": False, "publicAddress": "203.0.113.9"},
            "Metadata": {"title": "Jumanji", "librarySectionTitle": "Movies"},
        }

        with self.assertLogs("integrations.tasks", level="INFO") as logs:
            tasks.process_webhook("plex", payload, self.user.id)

        output = "\n".join(logs.output)
        for value in ("alice", "203.0.113.9", "server-abc", "Movies", "Jumanji"):
            with self.subTest(value=value):
                self.assertNotIn(value, output)
        self.assertIn("Metadata", output)
        self.assertIn("provider=plex", output)

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

        tasks.process_webhook(
            "plex", {"event": "media.scrobble"}, recipient.id, share_id=share.id
        )

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

    @override_settings(TMDB_API="")
    @patch("integrations.webhooks.jellyfin.JellyfinWebhookProcessor.process_payload")
    def test_processing_resolves_the_users_personal_tmdb_key(self, mock_process):
        """Metadata lookups use the user's own key, as imports do (#1488)."""
        credentials.set_user("tmdb", self.user, {"api_key": "personal-tmdb"})
        seen = {}

        def capture_key(_payload, _user):
            seen["api_key"] = credentials.get("tmdb", "api_key")

        mock_process.side_effect = capture_key
        tasks.process_webhook("jellyfin", {"Event": "Stop"}, self.user.id)

        self.assertEqual(seen["api_key"], "personal-tmdb")
        self.assertIsNone(credentials.active_user())

    @override_settings(TMDB_API="")
    @patch("integrations.webhooks.plex.PlexWebhookProcessor.process_payload")
    def test_shared_plex_task_resolves_the_recipients_personal_key(
        self,
        mock_process,
    ):
        """A shared play is tracked for the recipient, so their key applies."""
        recipient = get_user_model().objects.create_user(username="recipient")
        credentials.set_user("tmdb", self.user, {"api_key": "owner-tmdb"})
        credentials.set_user("tmdb", recipient, {"api_key": "recipient-tmdb"})
        PlexAccount.objects.create(
            user=self.user,
            plex_token="owner-plex-token",
            plex_username="taskuser",
        )
        share = PlexWebhookShare.objects.create(
            owner=self.user,
            recipient=recipient,
            plex_username="plex-friend",
            recipient_enabled=True,
        )
        seen = {}

        def capture_key(_payload, _user, **_kwargs):
            seen["api_key"] = credentials.get("tmdb", "api_key")

        mock_process.side_effect = capture_key
        tasks.process_webhook(
            "plex", {"event": "media.scrobble"}, recipient.id, share_id=share.id
        )

        self.assertEqual(seen["api_key"], "recipient-tmdb")

    @patch("integrations.webhooks.plex.PlexWebhookProcessor.process_payload")
    def test_credential_scope_resets_after_a_failure(self, mock_process):
        """A failing run does not leave its user published for the next task."""
        seen = {}

        def fail_in_scope(_payload, _user):
            seen["user"] = credentials.active_user()
            raise ValueError("boom")

        mock_process.side_effect = fail_in_scope
        with self.assertRaises(ValueError):
            tasks.process_webhook("plex", {"event": "media.scrobble"}, self.user.id)

        self.assertEqual(seen["user"], self.user)
        self.assertIsNone(credentials.active_user())

    @patch("integrations.webhooks.jellyfin.JellyfinWebhookProcessor.process_payload")
    def test_credential_scope_restores_an_outer_user(self, mock_process):
        """An eager task inside another user's scope hands that scope back."""
        outer = get_user_model().objects.create_user(username="outer")
        for side_effect in (None, ValueError("boom")):
            with self.subTest(fails=side_effect is not None):
                mock_process.side_effect = side_effect
                with credentials.current_user_scope(outer):
                    with suppress(ValueError):
                        tasks.process_webhook(
                            "jellyfin", {"Event": "Stop"}, self.user.id
                        )
                    self.assertEqual(credentials.active_user(), outer)

    @override_settings(TMDB_API="")
    @patch("integrations.webhooks.jellyfin.JellyfinWebhookProcessor.process_payload")
    def test_sequential_webhooks_resolve_each_users_own_key(self, mock_process):
        """One user's key does not carry over into the next user's webhook."""
        other = get_user_model().objects.create_user(username="other")
        credentials.set_user("tmdb", self.user, {"api_key": "first-tmdb"})
        credentials.set_user("tmdb", other, {"api_key": "second-tmdb"})
        seen = []
        mock_process.side_effect = lambda _payload, _user: seen.append(
            credentials.get("tmdb", "api_key")
        )

        tasks.process_webhook("jellyfin", {"Event": "Stop"}, self.user.id)
        tasks.process_webhook("jellyfin", {"Event": "Stop"}, other.id)

        self.assertEqual(seen, ["first-tmdb", "second-tmdb"])

    def test_missing_user_logs_and_returns(self):
        """A deleted user is logged and skipped without raising."""
        missing_id = self.user.id + 999
        with self.assertLogs("integrations.tasks", level="WARNING") as logs:
            tasks.process_webhook("jellyfin", {"Event": "Stop"}, missing_id)
        self.assertIn("missing user", logs.output[0])

    @patch("integrations.tasks.push_jellyfin_watched.apply_async")
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

        cache.clear()
        tasks.process_webhook("jellyfin", {"Event": "Stop"}, self.user.id)

        mock_push_delay.assert_called_once()
        self.assertEqual(
            mock_push_delay.call_args.kwargs["kwargs"],
            {"user_id": self.user.id},
        )

    @patch("integrations.tasks.push_jellyfin_watched.apply_async")
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

    @patch("integrations.tasks.push_jellyfin_watched.apply_async")
    @patch("integrations.webhooks.jellyfin.JellyfinWebhookProcessor.process_payload")
    def test_jellyfin_instant_push_skipped_without_account(
        self,
        _mock_process,
        mock_push_delay,
    ):
        """No push-back should be queued when Jellyfin isn't connected."""
        tasks.process_webhook("jellyfin", {"Event": "Stop"}, self.user.id)

        mock_push_delay.assert_not_called()


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
