"""What the connections surface tells a user about a sync that is not working."""

from http import HTTPStatus as HTTP  # noqa: N814

from app.models import Item
from app.models.choices import MediaTypes, Sources
from app.models.watch_state import WatchStateSequence
from app.services.progress_changes import record_progress_change
from integrations.models import SyncClientKind
from integrations.state.checkpoints import record_applied_position
from integrations.state.identity import get_or_create_binding

from .base import FloppyApiTestCase

CONNECTIONS = "/api/v1/sync/connections/"


class SyncDiagnosticsTests(FloppyApiTestCase):
    """Connections report position, lag, and failures, not just status."""

    def setUp(self):
        """Create a binding with progress changes behind it."""
        super().setUp()
        self.binding, _ = get_or_create_binding(
            self.user1,
            SyncClientKind.GENERIC.value,
            instance_key="tv",
            profile_key="me",
        )
        self.item, _ = Item.objects.get_or_create(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={"title": "The Matrix"},
        )
        WatchStateSequence.objects.update_or_create(
            user=self.user1,
            defaults={"emit_changes": True},
        )

    def connection(self):
        """Return this user's single connection payload."""
        response = self.client.get(CONNECTIONS, **self.auth_headers)
        self.assertEqual(response.status_code, HTTP.OK)
        return response.data["results"][0]

    def test_origin_key_is_exposed(self):
        """Without it a client cannot name itself, so it can never checkpoint."""
        self.assertEqual(self.connection()["origin_key"], self.binding.origin_key)

    def test_failed_deliveries_are_counted_separately(self):
        """A failed write must not read as still in progress."""
        payload = self.connection()

        self.assertIn("failed_deliveries", payload)
        self.assertIn("pending_deliveries", payload)
        self.assertEqual(payload["failed_deliveries"], 0)

    def test_unresolved_references_are_reported(self):
        """Items the sync could not identify are surfaced, not swallowed."""
        self.assertEqual(self.connection()["unresolved_references"], 0)

    def test_a_connection_with_no_checkpoint_reports_none(self):
        """A connection that has applied nothing has no position to report."""
        self.assertEqual(self.connection()["checkpoints"], [])

    def test_lag_is_reported_against_the_newest_change(self):
        """The number a user acts on is how far behind the device is."""
        changes = [
            record_progress_change(self.user1, self.item, position_seconds=n)
            for n in range(1, 6)
        ]
        record_applied_position(
            self.binding,
            changes[1].sequence,
            resource="progress",
        )

        checkpoints = self.connection()["checkpoints"]

        progress = next(c for c in checkpoints if c["resource"] == "progress")
        self.assertEqual(progress["last_sequence"], changes[1].sequence)
        self.assertEqual(
            progress["behind_by"],
            changes[-1].sequence - changes[1].sequence,
        )

    def test_a_caught_up_connection_reports_zero_lag(self):
        """Caught up is stated, not implied by absence."""
        changes = [
            record_progress_change(self.user1, self.item, position_seconds=n)
            for n in range(1, 4)
        ]
        record_applied_position(
            self.binding,
            changes[-1].sequence,
            resource="progress",
        )

        progress = next(
            c for c in self.connection()["checkpoints"] if c["resource"] == "progress"
        )
        self.assertEqual(progress["behind_by"], 0)

    def test_another_user_sees_no_connections(self):
        """Connections are per user."""
        response = self.client.get(CONNECTIONS, **self.auth_headers2)

        self.assertEqual(response.data["results"], [])
