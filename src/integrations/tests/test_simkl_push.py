"""Sending plays to SIMKL: the API client, the device login, the adapter, the card.

SIMKL's replies below are fixtures built from its AUTH V2 and sync documentation
(api.simkl.org). The shapes of ``not_found`` entries are the least certain
part, so the tests pin what Floppy does with them: a title SIMKL did not match is
reported as failed, and a reply it cannot read is never counted as delivered.
"""

import datetime
import logging
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from app.models import Item, MediaTypes, Movie, Sources, Status
from app.services.watch_state import importing_watch_state
from integrations import simkl_api
from integrations.imports.helpers import decrypt, encrypt
from integrations.models import (
    CAPABILITY_PLAY_PUSH,
    OutboundStateDelivery,
    SimklAccount,
    SyncBinding,
    SyncClientKind,
    SyncDirection,
)
from integrations.state.adapters.base import (
    BATCH_DELIVERED,
    BATCH_FAILED,
    BATCH_RETRY,
    BATCH_SKIPPED,
    BatchItem,
    TerminalAdapterError,
    TransientAdapterError,
)
from integrations.state.adapters.simkl import (
    UNDATED_WATCHED_AT,
    SimklAdapter,
    build_adapter,
)
from integrations.state.identity import activate_binding, get_or_create_binding
from integrations.state.references import tmdb_reference
from integrations.tasks._simkl_export import export_simkl_library

REQUEST = "integrations.simkl_api.requests.request"


def setUpModule():
    """Silence log noise for this module only."""
    logging.disable(logging.DEBUG)


def tearDownModule():
    """Restore logging so other modules' assertLogs still see records."""
    logging.disable(logging.NOTSET)


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None):
        """Stand in for a requests response."""
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.content = b"" if body is None else b"x"

    def json(self):
        """Return the body, or fail like a reply that is not JSON."""
        if self._body is None:
            raise ValueError("no body")
        return self._body


def _play(delivery_id, external_id, watched_at="2026-10-18T20:15:00+00:00"):
    return BatchItem(
        delivery_id=delivery_id,
        operation="play",
        item=None,
        external_id=external_id,
        payload={"watched_at": watched_at},
        rating=None,
    )


class SimklTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username="owner")
        self.account = SimklAccount.objects.create(
            user=self.user,
            profile_key="profile-1",
            client_id="client-id",
            access_token=encrypt("access-1"),
            refresh_token=encrypt("refresh-1"),
            access_expires_at=timezone.now() + datetime.timedelta(days=1),
            scope="media:read media:write",
        )


class ErrorReadingTests(TestCase):
    def test_the_named_wait_is_used(self):
        response = FakeResponse(429, {}, {"Retry-After": "42"})

        self.assertEqual(simkl_api.retry_after(response), 42)

    def test_a_spent_daily_quota_waits_for_midnight_in_new_york(self):
        # 03:00 UTC is 23:00 the evening before in New York (EDT, UTC-4).
        now = datetime.datetime(2026, 7, 1, 3, tzinfo=datetime.UTC)
        response = FakeResponse(429, {}, {"X-RateLimit-Remaining": "0"})

        self.assertEqual(simkl_api.retry_after(response, now), 3600)

    def test_a_429_is_retried_after_the_wait_simkl_named(self):
        with self.assertRaises(TransientAdapterError) as caught:
            simkl_api.raise_for_status(
                FakeResponse(429, {"error": "quota"}, {"Retry-After": "90"}),
            )

        self.assertEqual(caught.exception.retry_after, 90)

    def test_a_write_made_during_another_sync_waits_for_the_lock(self):
        with self.assertRaises(TransientAdapterError) as caught:
            simkl_api.raise_for_status(FakeResponse(400, {"error": "rate_limit"}))

        self.assertEqual(
            caught.exception.retry_after,
            simkl_api.WRITE_LOCK_SECONDS,
        )

    def test_a_server_error_is_transient_and_a_401_needs_a_reconnect(self):
        with self.assertRaises(TransientAdapterError):
            simkl_api.raise_for_status(FakeResponse(503, {}))
        with self.assertRaises(simkl_api.SimklAuthError):
            simkl_api.raise_for_status(FakeResponse(401, {"error": "invalid"}))

    def test_another_client_error_is_terminal_and_not_an_auth_failure(self):
        with self.assertRaises(TerminalAdapterError) as caught:
            simkl_api.raise_for_status(FakeResponse(422, {"error": "bad_body"}))

        self.assertNotIsInstance(caught.exception, simkl_api.SimklAuthError)


class DeviceFlowTests(TestCase):
    def test_the_code_asks_for_read_and_write_and_sends_no_secret(self):
        reply = FakeResponse(
            200,
            {
                "device_code": "dev-1",
                "user_code": "BDWP-HQPK",
                "verification_uri": "https://simkl.com/pin",
                "verification_uri_complete": "https://simkl.com/pin?user_code=BDWP-HQPK",
                "expires_in": 900,
                "interval": 5,
            },
        )
        with patch(REQUEST, return_value=reply) as call:
            flow = simkl_api.start_device_flow("client-id")

        sent = call.call_args.kwargs["data"]
        self.assertEqual(sent["scope"], "media:read media:write")
        self.assertNotIn("client_secret", sent)
        self.assertEqual(
            flow["verification_url"],
            "https://simkl.com/pin?user_code=BDWP-HQPK",
        )
        self.assertEqual(flow["expires_in"], 900)

    def test_an_older_app_is_told_why_it_cannot_use_device_login(self):
        with (
            patch(REQUEST, return_value=FakeResponse(401, {"error": "invalid_client"})),
            self.assertRaisesMessage(simkl_api.DeviceFlowError, "AUTH V2"),
        ):
            simkl_api.start_device_flow("client-id")

    def test_polling_distinguishes_waiting_slowing_and_expired(self):
        def poll(status, body):
            with patch(REQUEST, return_value=FakeResponse(status, body)):
                return simkl_api.poll_device_flow("client-id", "dev-1")

        self.assertEqual(
            poll(400, {"error": "authorization_pending"}),
            ("pending", None),
        )
        self.assertEqual(
            poll(400, {"error": "slow_down"}),
            ("pending", {"interval": 5}),
        )
        state, _message = poll(400, {"error": "expired_token"})
        self.assertEqual(state, "failed")
        state, _message = poll(401, {"error": "invalid_client"})
        self.assertEqual(state, "failed")

    def test_an_approval_that_was_downgraded_to_read_only_is_refused(self):
        tokens = {"access_token": "a", "refresh_token": "r", "scope": "media:read"}
        with patch(REQUEST, return_value=FakeResponse(200, tokens)):
            state, message = simkl_api.poll_device_flow("client-id", "dev-1")

        self.assertEqual(state, "failed")
        self.assertIn("only allowed reading", message)

    def test_an_approval_with_write_is_accepted(self):
        tokens = {
            "access_token": "a",
            "refresh_token": "r",
            "scope": "media:read media:write",
        }
        with patch(REQUEST, return_value=FakeResponse(200, tokens)):
            state, payload = simkl_api.poll_device_flow("client-id", "dev-1")

        self.assertEqual((state, payload), ("approved", tokens))

    def test_token_fields_encrypt_and_keep_the_scope(self):
        now = datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC)
        fields = simkl_api.token_fields(
            {"access_token": "a", "refresh_token": "r", "scope": "media:write"},
            now,
        )

        self.assertEqual(decrypt(fields["access_token"]), "a")
        self.assertEqual(fields["access_expires_at"], now + datetime.timedelta(days=7))
        self.assertEqual(fields["scope"], "media:write")


class ClientTests(SimklTestCase):
    def test_a_call_names_the_app_and_uses_the_bearer_token(self):
        with patch(REQUEST, return_value=FakeResponse(200, {"added": {}})) as call:
            simkl_api.SimklClient(self.account).request(
                "POST",
                "/sync/history",
                json={},
            )

        kwargs = call.call_args.kwargs
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer access-1")
        self.assertEqual(kwargs["params"]["client_id"], "client-id")
        self.assertEqual(kwargs["params"]["app-name"], "floppy")
        # An individual play never fills in earlier episodes.
        self.assertEqual(kwargs["params"]["skip_auto_watching"], "yes")

    def test_a_stale_token_is_refreshed_once_and_the_refresh_token_is_kept(self):
        self.account.access_expires_at = timezone.now() - datetime.timedelta(minutes=1)
        self.account.save()
        refreshed = FakeResponse(
            200,
            {"access_token": "access-2", "refresh_token": "refresh-1"},
        )
        with patch(
            REQUEST,
            side_effect=[refreshed, FakeResponse(200, {"added": {}})],
        ) as call:
            simkl_api.SimklClient(self.account).request("POST", "/sync/history")

        self.assertEqual(call.call_count, 2)
        self.account.refresh_from_db()
        self.assertEqual(decrypt(self.account.access_token), "access-2")
        self.assertEqual(decrypt(self.account.refresh_token), "refresh-1")
        self.assertEqual(self.account.scope, "media:read media:write")
        self.assertEqual(
            call.call_args_list[1].kwargs["headers"]["Authorization"],
            "Bearer access-2",
        )

    def test_a_refresh_another_worker_already_did_is_not_repeated(self):
        stale = self.account.access_token
        SimklAccount.objects.filter(pk=self.account.pk).update(
            access_token=encrypt("access-2"),
        )
        client = simkl_api.SimklClient(self.account)
        self.account.access_token = stale
        with patch(REQUEST) as call:
            client.refresh(force=True)

        call.assert_not_called()

    def test_a_refresh_simkl_rejects_marks_the_connection_broken(self):
        self.account.access_expires_at = timezone.now() - datetime.timedelta(minutes=1)
        self.account.save()
        with (
            patch(REQUEST, return_value=FakeResponse(400, {"error": "invalid_grant"})),
            self.assertRaises(simkl_api.SimklAuthError),
        ):
            simkl_api.SimklClient(self.account).request("POST", "/sync/history")

        self.account.refresh_from_db()
        self.assertTrue(self.account.connection_broken)

    def test_a_timeout_records_the_error_without_breaking_the_connection(self):
        import requests

        with (
            patch(REQUEST, side_effect=requests.Timeout("slow")),
            self.assertRaises(TransientAdapterError),
        ):
            simkl_api.SimklClient(self.account).request("POST", "/sync/history")

        self.account.refresh_from_db()
        self.assertFalse(self.account.connection_broken)
        self.assertTrue(self.account.last_error_message)


class ReferenceTests(TestCase):
    def _item(self, **fields):
        defaults = {"source": Sources.TMDB.value, "title": "T", "media_id": "155"}
        return Item(**{**defaults, **fields})

    def test_movies_and_episodes_resolve_but_a_whole_show_does_not(self):
        adapter = SimklAdapter(SimklAccount())

        self.assertEqual(
            adapter.resolve_external_id(self._item(media_type="movie")),
            "movie:155",
        )
        self.assertEqual(
            adapter.resolve_external_id(
                self._item(
                    media_id="1399",
                    media_type="episode",
                    season_number=1,
                    episode_number=2,
                ),
            ),
            "episode:1399:1:2",
        )
        self.assertIsNone(
            adapter.resolve_external_id(
                self._item(media_id="1399", media_type="tv"),
            ),
        )

    def test_an_item_from_another_source_is_never_guessed(self):
        item = self._item(source=Sources.MAL.value, media_type="movie")

        self.assertIsNone(tmdb_reference(item))


class AdapterTests(SimklTestCase):
    def _send(self, items, reply, status=200):
        with patch(REQUEST, return_value=FakeResponse(status, reply)) as call:
            results = SimklAdapter(self.account).write_batch(
                items,
                idempotency_key="batch-1",
            )
        return results, call

    def test_the_adapter_declines_imports_and_only_sends_plays(self):
        self.assertFalse(SimklAdapter.ACCEPTS_IMPORTED_CHANGES)
        self.assertEqual(SimklAdapter.CAPABILITIES, frozenset({CAPABILITY_PLAY_PUSH}))
        self.assertLessEqual(SimklAdapter.BATCH_SIZE, 20000)

    def test_a_movie_play_carries_its_real_date(self):
        results, call = self._send(
            [_play(1, "movie:155")],
            {"added": {"movies": 1}, "not_found": {"movies": [], "shows": []}},
        )

        self.assertEqual(
            call.call_args.kwargs["json"]["movies"],
            [{"ids": {"tmdb": 155}, "watched_at": "2026-10-18T20:15:00+00:00"}],
        )
        self.assertEqual(
            call.call_args.args[:2], ("POST", "https://api.simkl.com/sync/history")
        )
        self.assertEqual([r.outcome for r in results], [BATCH_DELIVERED])

    def test_episodes_are_always_named_and_never_a_whole_show_or_season(self):
        _results, call = self._send(
            [
                _play(1, "episode:1399:1:1", "2026-10-18T20:00:00+00:00"),
                _play(2, "episode:1399:1:2", "2026-10-18T21:00:00+00:00"),
                _play(3, "episode:1399:2:1", "2026-10-19T20:00:00+00:00"),
            ],
            {"added": {"episodes": 3}},
        )

        shows = call.call_args.kwargs["json"]["shows"]
        self.assertEqual(len(shows), 1)
        self.assertEqual(shows[0]["ids"], {"tmdb": 1399})
        seasons = {s["number"]: s["episodes"] for s in shows[0]["seasons"]}
        self.assertEqual([e["number"] for e in seasons[1]], [1, 2])
        self.assertEqual(seasons[2][0]["watched_at"], "2026-10-19T20:00:00+00:00")
        for season in shows[0]["seasons"]:
            self.assertTrue(season["episodes"])

    def test_an_undated_play_is_left_out_unless_the_user_chose_to_send_it(self):
        item = _play(1, "movie:155", None)
        results, call = self._send([item], {"added": {}})

        self.assertEqual(results[0].outcome, BATCH_SKIPPED)
        call.assert_not_called()

        self.account.send_undated = True
        results, call = self._send([item], {"added": {"movies": 1}})

        self.assertEqual(
            call.call_args.kwargs["json"]["movies"][0]["watched_at"],
            UNDATED_WATCHED_AT,
        )
        self.assertEqual(results[0].outcome, BATCH_DELIVERED)

    def test_titles_simkl_could_not_match_are_reported_not_counted_as_sent(self):
        results, _call = self._send(
            [
                _play(1, "movie:155"),
                _play(2, "movie:156"),
                _play(3, "episode:1399:1:1"),
                _play(4, "episode:1400:1:1"),
            ],
            {
                "added": {"movies": 1, "episodes": 1},
                "not_found": {
                    "movies": [{"ids": {"tmdb": 156}}],
                    "shows": [
                        {
                            "ids": {"tmdb": 1400},
                            "seasons": [{"number": 1, "episodes": [{"number": 1}]}],
                        },
                    ],
                },
            },
        )

        self.assertEqual(
            [r.outcome for r in results],
            [BATCH_DELIVERED, BATCH_FAILED, BATCH_DELIVERED, BATCH_FAILED],
        )
        self.assertIn("could not find", results[1].error)

    def test_a_whole_show_not_found_fails_each_of_its_episodes(self):
        results, _call = self._send(
            [_play(1, "episode:1399:1:1"), _play(2, "episode:1399:1:2")],
            {"added": {}, "not_found": {"shows": [{"ids": {"tmdb": 1399}}]}},
        )

        self.assertEqual([r.outcome for r in results], [BATCH_FAILED, BATCH_FAILED])

    def test_a_reply_it_cannot_read_is_retried_never_counted_as_delivered(self):
        results, _call = self._send([_play(1, "movie:155")], {"unexpected": True})

        self.assertEqual(results[0].outcome, BATCH_RETRY)

    def test_statuses_ratings_and_removals_are_never_sent(self):
        def item(delivery_id, operation, payload, rating=None):
            return BatchItem(
                delivery_id=delivery_id,
                operation=operation,
                item=None,
                external_id="movie:155",
                payload=payload,
                rating=rating,
            )

        items = [
            item(1, "status", {"status": "planning"}),
            item(2, "rating", {}, rating=8),
            item(3, "play_remove", {}),
        ]
        results, call = self._send(items, {"added": {}})

        self.assertEqual({r.outcome for r in results}, {BATCH_SKIPPED})
        call.assert_not_called()

    def test_the_write_lock_retries_the_whole_request_after_it_clears(self):
        with (
            patch(REQUEST, return_value=FakeResponse(400, {"error": "rate_limit"})),
            self.assertRaises(TransientAdapterError) as caught,
        ):
            SimklAdapter(self.account).write_batch(
                [_play(1, "movie:155")],
                idempotency_key="batch-1",
            )

        self.assertEqual(caught.exception.retry_after, simkl_api.WRITE_LOCK_SECONDS)

    def test_only_a_connected_account_yields_an_adapter(self):
        binding, _ = get_or_create_binding(
            self.user,
            SyncClientKind.SIMKL.value,
            instance_key="simkl.com",
            profile_key="profile-1",
        )
        self.assertIsInstance(build_adapter(binding), SimklAdapter)

        self.account.refresh_token = ""
        self.account.save()
        self.assertIsNone(build_adapter(binding))


@override_settings(SIMKL_ID="app-client")
class ConnectViewTests(TestCase):
    """The card's buttons: connect, wait for approval, change settings, disconnect."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username="owner")
        self.client.force_login(self.user)

    def _flow(self):
        return {
            "device_code": "dev-1",
            "user_code": "BDWP-HQPK",
            "verification_url": "https://simkl.com/pin?user_code=BDWP-HQPK",
            "interval": 5,
            "expires_in": 900,
        }

    def _start(self):
        with (
            patch(
                "integrations.simkl_views.simkl_api.client_id_for",
                return_value="app-client",
            ),
            patch(
                "integrations.simkl_views.simkl_api.start_device_flow",
                return_value=self._flow(),
            ),
        ):
            return self.client.post(reverse("simkl_connect"))

    def _approve(self):
        tokens = {
            "access_token": "access-1",
            "refresh_token": "refresh-1",
            "expires_in": 3600,
            "scope": "media:read media:write",
        }
        with patch(
            "integrations.simkl_views.simkl_api.poll_device_flow",
            return_value=("approved", tokens),
        ):
            return self.client.post(reverse("simkl_poll"))

    def _connect(self):
        self._start()
        self._approve()
        return SimklAccount.objects.get(user=self.user)

    def test_connecting_without_a_client_id_says_where_to_add_one(self):
        with patch(
            "integrations.simkl_views.simkl_api.client_id_for",
            return_value="",
        ):
            response = self.client.post(reverse("simkl_connect"), follow=True)

        self.assertContains(response, "SIMKL needs your own Client ID")
        self.assertFalse(SimklAccount.objects.exists())

    def test_starting_stores_a_pending_login_with_an_encrypted_code(self):
        self._start()

        account = SimklAccount.objects.get(user=self.user)
        self.assertTrue(account.is_pending)
        self.assertEqual(account.user_code, "BDWP-HQPK")
        self.assertNotIn("dev-1", account.device_code)
        self.assertEqual(decrypt(account.device_code), "dev-1")

    def test_approval_connects_and_creates_a_binding_that_sends_nothing_yet(self):
        account = self._connect()

        self.assertTrue(account.is_connected)
        self.assertEqual(account.scope, "media:read media:write")
        binding = SyncBinding.objects.get(
            user=self.user,
            client_kind=SyncClientKind.SIMKL.value,
        )
        self.assertFalse(
            binding.allows(SyncDirection.OUTBOUND.value, CAPABILITY_PLAY_PUSH)
        )

    def test_a_declined_scope_is_reported_and_connects_nothing(self):
        self._start()
        with patch(
            "integrations.simkl_views.simkl_api.poll_device_flow",
            return_value=("failed", "SIMKL only allowed reading."),
        ):
            response = self.client.post(reverse("simkl_poll"))

        self.assertEqual(
            response.json()["state"] if response.status_code == 200 else "", "failed"
        )
        self.assertFalse(SimklAccount.objects.exists())

    def test_settings_switch_plays_and_undated_on_and_off(self):
        account = self._connect()

        self.client.post(
            reverse("simkl_settings"),
            {"plays": "on", "send_undated": "on", "schedule": "live"},
        )
        account.refresh_from_db()
        binding = SyncBinding.objects.get(user=self.user, client_kind="simkl")
        self.assertTrue(account.send_undated)
        self.assertTrue(
            binding.allows(SyncDirection.OUTBOUND.value, CAPABILITY_PLAY_PUSH)
        )

        self.client.post(reverse("simkl_settings"), {"schedule": "live"})
        account.refresh_from_db()
        binding.refresh_from_db()
        self.assertFalse(account.send_undated)
        self.assertFalse(
            binding.allows(SyncDirection.OUTBOUND.value, CAPABILITY_PLAY_PUSH)
        )

    def test_exporting_needs_sync_switched_on_first(self):
        self._connect()

        with patch("integrations.tasks.export_simkl_library.delay") as task:
            self.client.post(reverse("simkl_export"))
            task.assert_not_called()

            self.client.post(reverse("simkl_settings"), {"plays": "on"})
            self.client.post(reverse("simkl_export"))
            task.assert_called_once_with(self.user.pk)

    def test_disconnecting_stops_sync_removes_the_login_and_revokes_it(self):
        self._connect()
        self.client.post(reverse("simkl_settings"), {"plays": "on"})

        with patch("integrations.simkl_views.simkl_api.logout") as logout:
            self.client.post(reverse("simkl_disconnect"))

        self.assertFalse(SimklAccount.objects.exists())
        logout.assert_called_once_with("app-client", "access-1", "refresh-1")
        binding = SyncBinding.objects.get(user=self.user, client_kind="simkl")
        self.assertFalse(
            binding.allows(SyncDirection.OUTBOUND.value, CAPABILITY_PLAY_PUSH)
        )

    def test_the_card_renders_for_each_state(self):
        url = reverse("provider_detail", args=["simkl"])
        for tab in ("connection", "sync", "activity"):
            self.assertEqual(self.client.get(f"{url}?tab={tab}").status_code, 200)

        self._start()
        self.assertContains(self.client.get(f"{url}?tab=connection"), "BDWP-HQPK")

        self._approve()
        response = self.client.get(f"{url}?tab=sync")
        self.assertContains(response, "Send plays with no date")
        self.assertNotContains(response, "Send Planning")

    def test_wetrakr_still_renders_its_own_options(self):
        url = reverse("provider_detail", args=["wetrakr"])

        for tab in ("connection", "sync", "activity"):
            self.assertEqual(self.client.get(f"{url}?tab={tab}").status_code, 200)


class ExportTests(SimklTestCase):
    def setUp(self):
        super().setUp()
        self.binding, _ = get_or_create_binding(
            self.user,
            SyncClientKind.SIMKL.value,
            instance_key="simkl.com",
            profile_key="profile-1",
        )
        activate_binding(
            self.binding,
            capabilities=[CAPABILITY_PLAY_PUSH],
            directions=[SyncDirection.OUTBOUND.value],
        )
        self.film = Item.objects.create(
            media_id="155",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Film",
        )
        self.undated = Item.objects.create(
            media_id="156",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Undated",
        )

    def _movie(self, item, end_date=None):
        with importing_watch_state():
            return Movie.objects.create(
                item=item,
                user=self.user,
                status=Status.COMPLETED.value,
                end_date=end_date,
            )

    def _export(self):
        with patch("integrations.state.outbound.kick_flush"):
            return export_simkl_library(self.user.pk)

    def test_dated_plays_are_queued_with_their_date_and_only_once(self):
        when = datetime.datetime(2026, 10, 1, 19, 0, tzinfo=datetime.UTC)
        self._movie(self.film, when)

        self.assertEqual(self._export(), 1)
        self.assertEqual(self._export(), 0)

        delivery = OutboundStateDelivery.objects.get(operation="play")
        self.assertEqual(delivery.payload["watched_at"], when.isoformat())

    def test_undated_plays_are_left_out_by_default(self):
        self._movie(self.undated)

        self.assertEqual(self._export(), 0)

    def test_undated_plays_are_queued_without_a_date_when_the_user_chose_to(self):
        self.account.send_undated = True
        self.account.save()
        self._movie(self.undated)

        self.assertEqual(self._export(), 1)

        delivery = OutboundStateDelivery.objects.get(operation="play")
        self.assertIsNone(delivery.payload["watched_at"])
        self.assertEqual(self._export(), 0)

    def test_statuses_and_ratings_are_never_queued(self):
        self._movie(self.film, datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC))

        self._export()

        self.assertEqual(
            set(OutboundStateDelivery.objects.values_list("operation", flat=True)),
            {"play"},
        )

    def test_a_user_without_a_binding_exports_nothing(self):
        self.binding.delete()

        self.assertEqual(export_simkl_library(self.user.pk), 0)
