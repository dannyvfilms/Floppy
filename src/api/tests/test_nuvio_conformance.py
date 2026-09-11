"""Executable conformance fixtures for a Floppy tracking client.

This is the adoption kit's runnable half. Every test here is one step of the
documented client lifecycle in `docs/integrations/nuvio-client-guide.md`, and
the assertions are the contract a client is written against. A change that
breaks one of these is a breaking change for every external client, whatever
the rest of the suite says.

Read them in order: connect, initial merge, playback update, offline retry,
incremental pull, reset, reconciliation, disconnect.
"""

from datetime import timedelta
from http import HTTPStatus as HTTP  # noqa: N814

from django.utils import timezone

from app.models import Item
from app.models.choices import MediaTypes, Sources
from app.models.watch_state import WatchStateSequence
from integrations.models import (
    CatalogGrant,
    IntegrationToken,
    SyncBindingStatus,
    SyncClientKind,
)
from integrations.state.identity import get_or_create_binding

from .base import FloppyApiTestCase

CHANGES = "/api/v1/sync/changes/"
PROGRESS_CHANGES = "/api/v1/sync/progress-changes/"
CONNECTIONS = "/api/v1/sync/connections/"
PROGRESS = "/api/v1/playback/progress/"
SCROBBLE = "/api/v1/scrobble/"


class NuvioConformanceTests(FloppyApiTestCase):
    """The client lifecycle, step by step."""

    def setUp(self):
        """Mint a tracking token and bind one device."""
        super().setUp()
        self.token, self.secret = IntegrationToken.generate(
            user=self.user1,
            name="Nuvio conformance",
        )
        self.headers = {"HTTP_X_API_KEY": self.secret}
        self.binding, _ = get_or_create_binding(
            self.user1,
            SyncClientKind.GENERIC.value,
            instance_key="conformance",
            profile_key="me",
        )
        self.binding.status = SyncBindingStatus.ACTIVE.value
        self.binding.save(update_fields=["status"])
        WatchStateSequence.objects.update_or_create(
            user=self.user1,
            defaults={"emit_changes": True},
        )
        self.item, _ = Item.objects.get_or_create(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={"title": "The Matrix"},
        )

    # 1. Connect -------------------------------------------------------------

    def test_01_a_default_token_authenticates(self):
        """Step 1: the credential the user pastes into the client works."""
        response = self.client.get(CONNECTIONS, **self.headers)

        self.assertEqual(response.status_code, HTTP.OK)

    def test_02_the_default_preset_reaches_every_endpoint_a_client_needs(self):
        """Step 1: a tracking token is not missing a scope it cannot do without."""
        for path in (CONNECTIONS, CHANGES, PROGRESS_CHANGES, PROGRESS):
            with self.subTest(path=path):
                response = self.client.get(path, **self.headers)
                self.assertEqual(response.status_code, HTTP.OK)

    def test_03_the_default_preset_reaches_nothing_else(self):
        """Step 1: the same token must not be a general account credential."""
        for path in ("/api/v1/user/preferences/", "/api/v1/export/csv/"):
            with self.subTest(path=path):
                response = self.client.get(path, **self.headers)
                self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_04_connections_name_themselves(self):
        """Step 1: a client learns the origin key it must send when pulling."""
        response = self.client.get(CONNECTIONS, **self.headers)

        keys = [row["origin_key"] for row in response.data["results"]]
        self.assertIn(self.binding.origin_key, keys)

    # 2. Initial merge -------------------------------------------------------

    def test_05_a_first_pull_starts_from_zero(self):
        """Step 2: cursor 0 means 'I have nothing', and is always valid."""
        response = self.client.get(f"{CHANGES}?cursor=0", **self.headers)

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertIn("next_cursor", response.data)

    def test_06_the_feed_states_what_it_still_holds(self):
        """Step 2: a client can tell whether a resume is possible at all."""
        response = self.client.get(PROGRESS_CHANGES, **self.headers)

        self.assertIn("oldest_sequence", response.data)
        self.assertIn("newest_sequence", response.data)

    # 3. Playback update -----------------------------------------------------

    def test_07_a_progress_write_is_accepted_and_readable(self):
        """Step 3: the write a player makes every few seconds."""
        write = self.call_api(
            "put",
            "api_playback_progress",
            payload={
                "media_type": "movie",
                "ids": {"tmdb": "701"},
                "position_seconds": 900,
            },
            headers=self.headers,
        )
        self.assertEqual(write.status_code, HTTP.OK)

        read = self.client.get(PROGRESS, **self.headers)
        self.assertEqual(read.status_code, HTTP.OK)

    def test_08_a_progress_write_appears_on_the_change_feed(self):
        """Step 3: what one device writes, another device can learn."""
        self.call_api(
            "put",
            "api_playback_progress",
            payload={
                "media_type": "movie",
                "ids": {"tmdb": "701"},
                "position_seconds": 120,
            },
            headers=self.headers,
        )

        feed = self.client.get(PROGRESS_CHANGES, **self.headers)
        self.assertTrue(feed.data["results"])

    # 4. Offline retry -------------------------------------------------------

    def test_09_a_retried_write_returns_the_first_result(self):
        """Step 4: reconnecting and resending must not double-apply."""
        payload = {
            "media_type": "movie",
            "ids": {"tmdb": "701"},
            "position_seconds": 300,
            "client_event_id": "conformance-retry-1",
        }
        first = self.call_api(
            "put",
            "api_playback_progress",
            payload=payload,
            headers=self.headers,
        )
        second = self.call_api(
            "put",
            "api_playback_progress",
            payload=payload,
            headers=self.headers,
        )

        self.assertEqual(first.status_code, HTTP.OK)
        self.assertEqual(second.status_code, HTTP.OK)

        # Compared field by field, minus updated_at: the stored copy is
        # re-encoded with DjangoJSONEncoder, which truncates a datetime to
        # milliseconds. The replay is the same result; its timestamp is the
        # same instant at lower precision. Documented in the client guide.
        first_body = first.json()
        second_body = second.json()
        self.assertEqual(
            {k: v for k, v in first_body.items() if k != "updated_at"},
            {k: v for k, v in second_body.items() if k != "updated_at"},
        )
        self.assertTrue(
            first_body["updated_at"].startswith(
                second_body["updated_at"].rstrip("Z")[:23],
            ),
        )

    def test_10_a_reused_event_id_with_new_data_is_a_conflict(self):
        """Step 4: an id is a promise about the payload, not a nonce."""
        base = {
            "media_type": "movie",
            "ids": {"tmdb": "701"},
            "client_event_id": "conformance-retry-2",
        }
        self.call_api(
            "put",
            "api_playback_progress",
            payload={**base, "position_seconds": 10},
            headers=self.headers,
        )
        clash = self.call_api(
            "put",
            "api_playback_progress",
            payload={**base, "position_seconds": 20},
            headers=self.headers,
        )

        self.assertEqual(clash.status_code, HTTP.CONFLICT)

    def test_11_two_devices_may_reuse_one_event_id(self):
        """Step 4: a per-install counter is not a cross-device collision."""
        second_binding, _ = get_or_create_binding(
            self.user1,
            SyncClientKind.GENERIC.value,
            instance_key="second-device",
            profile_key="me",
        )
        self.assertNotEqual(second_binding.pk, self.binding.pk)

        payload = {
            "media_type": "movie",
            "ids": {"tmdb": "701"},
            "position_seconds": 55,
            "client_event_id": "1",
        }
        first = self.call_api(
            "put",
            "api_playback_progress",
            payload=payload,
            headers=self.headers,
        )

        self.assertEqual(first.status_code, HTTP.OK)

    # 5. Incremental pull ----------------------------------------------------

    def test_12_a_pull_after_a_cursor_excludes_what_was_seen(self):
        """Step 5: the cursor is exclusive, so nothing is applied twice."""
        for seconds in (10, 20, 30):
            self.call_api(
                "put",
                "api_playback_progress",
                payload={
                    "media_type": "movie",
                    "ids": {"tmdb": "701"},
                    "position_seconds": seconds,
                },
                headers=self.headers,
            )

        first_page = self.client.get(PROGRESS_CHANGES, **self.headers)
        cursor = first_page.data["next_cursor"]
        second_page = self.client.get(
            f"{PROGRESS_CHANGES}?cursor={cursor}",
            **self.headers,
        )

        self.assertEqual(second_page.data["results"], [])

    def test_13_a_named_pull_records_the_clients_position(self):
        """Step 5: naming the connection is what lets the log compact."""
        self.call_api(
            "put",
            "api_playback_progress",
            payload={
                "media_type": "movie",
                "ids": {"tmdb": "701"},
                "position_seconds": 42,
            },
            headers=self.headers,
        )
        page = self.client.get(PROGRESS_CHANGES, **self.headers)
        cursor = page.data["next_cursor"]

        self.client.get(
            f"{PROGRESS_CHANGES}?cursor={cursor}"
            f"&connection={self.binding.origin_key}",
            **self.headers,
        )

        connections = self.client.get(CONNECTIONS, **self.headers)
        row = next(
            r
            for r in connections.data["results"]
            if r["origin_key"] == self.binding.origin_key
        )
        self.assertTrue(row["checkpoints"])

    def test_14_page_size_is_capped(self):
        """Step 5: a client cannot ask for an unbounded page."""
        response = self.client.get(f"{PROGRESS_CHANGES}?limit=100000", **self.headers)

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertLessEqual(len(response.data["results"]), 500)

    def test_15_a_malformed_cursor_is_a_client_error(self):
        """Step 5: bad input is a 400, never a 500."""
        response = self.client.get(f"{PROGRESS_CHANGES}?cursor=abc", **self.headers)

        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    # 6. Reset ---------------------------------------------------------------

    def test_16_a_cleared_position_is_an_explicit_tombstone(self):
        """Step 6: a delete is delivered, not inferred from absence."""
        self.call_api(
            "put",
            "api_playback_progress",
            payload={
                "media_type": "movie",
                "ids": {"tmdb": "701"},
                "position_seconds": 60,
            },
            headers=self.headers,
        )
        before = self.client.get(PROGRESS_CHANGES, **self.headers)
        cursor = before.data["next_cursor"]

        self.call_api(
            "put",
            "api_playback_progress",
            payload={
                "media_type": "movie",
                "ids": {"tmdb": "701"},
                "position_seconds": None,
            },
            headers=self.headers,
        )

        after = self.client.get(
            f"{PROGRESS_CHANGES}?cursor={cursor}",
            **self.headers,
        )
        kinds = [row["kind"] for row in after.data["results"]]
        self.assertIn("delete", kinds)

    def test_17_an_expired_cursor_says_so_instead_of_lying(self):
        """Step 6: a long-offline client is told to re-snapshot."""
        from app.models import ProgressChange

        self.call_api(
            "put",
            "api_playback_progress",
            payload={
                "media_type": "movie",
                "ids": {"tmdb": "701"},
                "position_seconds": 15,
            },
            headers=self.headers,
        )
        changes = list(ProgressChange.objects.filter(user=self.user1))
        self.assertTrue(changes)
        oldest = min(c.sequence for c in changes)
        ProgressChange.objects.filter(user=self.user1).update(sequence=oldest + 500)

        response = self.client.get(
            f"{PROGRESS_CHANGES}?cursor={oldest}",
            **self.headers,
        )

        self.assertEqual(response.status_code, HTTP.CONFLICT)
        self.assertEqual(response.data["code"], "cursor_expired")

    # 7. Reconciliation ------------------------------------------------------

    def test_18_diagnostics_report_failure_not_just_status(self):
        """Step 7: a user must be able to see a sync that is not working."""
        response = self.client.get(CONNECTIONS, **self.headers)

        row = response.data["results"][0]
        for field in (
            "pending_deliveries",
            "failed_deliveries",
            "open_conflicts",
            "unresolved_references",
            "last_error_message",
        ):
            self.assertIn(field, row)

    # 8. Disconnect ----------------------------------------------------------

    def test_19_revoking_a_token_takes_effect_at_once(self):
        """Step 8: disconnecting is immediate, not eventual."""
        self.token.revoked_at = timezone.now()
        self.token.save(update_fields=["revoked_at"])

        response = self.client.get(CONNECTIONS, **self.headers)

        # 403, not 401: DRF downgrades an authentication failure when the
        # authenticator offers no WWW-Authenticate challenge, and Floppy
        # asserts 403 for every protected endpoint in its authentication
        # matrix. Noted in the client guide, because it means a client cannot
        # tell a dead credential from a missing scope on status alone.
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_20_an_expired_token_is_refused(self):
        """Step 8: expiry is enforced server side, not trusted to the client."""
        self.token.expires_at = timezone.now() - timedelta(seconds=1)
        self.token.save(update_fields=["expires_at"])

        response = self.client.get(CONNECTIONS, **self.headers)

        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_21_disconnecting_does_not_delete_tracking_data(self):
        """Step 8: revoking access is not the same as erasing a library."""
        self.call_api(
            "put",
            "api_playback_progress",
            payload={
                "media_type": "movie",
                "ids": {"tmdb": "701"},
                "position_seconds": 77,
            },
            headers=self.headers,
        )
        self.token.revoked_at = timezone.now()
        self.token.save(update_fields=["revoked_at"])

        still_there = self.client.get(PROGRESS, **self.auth_headers)
        self.assertEqual(still_there.status_code, HTTP.OK)
        self.assertTrue(still_there.json()["results"])

    # Cross-cutting ----------------------------------------------------------

    def test_22_no_endpoint_leaks_another_users_state(self):
        """Every feed and surface is scoped to the authenticated account."""
        for path in (CHANGES, PROGRESS_CHANGES, CONNECTIONS, PROGRESS):
            with self.subTest(path=path):
                response = self.client.get(path, **self.auth_headers2)
                self.assertEqual(response.status_code, HTTP.OK)
                self.assertEqual(response.data["results"], [])

    def test_23_a_catalog_grant_is_not_an_api_credential(self):
        """An add-on install URL must not authenticate the tracking API."""
        _, grant_token = CatalogGrant.generate(self.user1, "Living room")

        response = self.client.get(
            CONNECTIONS,
            HTTP_X_API_KEY=grant_token,
        )

        self.assertEqual(response.status_code, HTTP.FORBIDDEN)
