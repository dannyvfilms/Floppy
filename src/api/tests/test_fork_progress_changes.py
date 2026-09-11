"""Ordered resume-progress changes and their feed."""

from http import HTTPStatus as HTTP  # noqa: N814

from app.models import Item, ProgressChange
from app.models.choices import MediaTypes, Sources
from app.models.watch_state import WatchStateSequence
from app.services.progress_changes import (
    record_progress_change,
    record_progress_deletion,
)
from integrations.models import SyncCheckpoint, SyncClientKind
from integrations.state.identity import get_or_create_binding

from .base import FloppyApiTestCase

FEED = "/api/v1/sync/progress-changes/"
PROGRESS = "/api/v1/playback/progress/"


class ProgressChangeRecordingTests(FloppyApiTestCase):
    """Writes to progress produce ordered changes, deletes produce tombstones."""

    def setUp(self):
        """Enable change emission for the user."""
        super().setUp()
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

    def test_nothing_is_recorded_when_emission_is_off(self):
        """A library with no synchronizing connection writes no change rows."""
        WatchStateSequence.objects.filter(user=self.user1).update(emit_changes=False)

        self.assertIsNone(
            record_progress_change(self.user1, self.item, position_seconds=30),
        )
        self.assertEqual(ProgressChange.objects.count(), 0)

    def test_an_upsert_is_recorded_in_server_order(self):
        """Sequences increase with commit order."""
        first = record_progress_change(self.user1, self.item, position_seconds=30)
        second = record_progress_change(self.user1, self.item, position_seconds=90)

        self.assertLess(first.sequence, second.sequence)
        self.assertEqual(second.position_seconds, 90)

    def test_a_delete_is_an_explicit_tombstone(self):
        """A cleared position is recorded, not merely absent."""
        record_progress_change(self.user1, self.item, position_seconds=30)
        tombstone = record_progress_deletion(self.user1, self.item)

        self.assertEqual(tombstone.kind, "delete")
        self.assertEqual(ProgressChange.objects.count(), 2)

    def test_the_api_write_path_records_a_change(self):
        """Writing progress through the API produces a change row."""
        response = self.call_api(
            "put",
            "api_playback_progress",
            payload={
                "media_type": "movie",
                "ids": {"tmdb": "701"},
                "position_seconds": 120,
            },
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertTrue(ProgressChange.objects.filter(user=self.user1).exists())


class ProgressChangeFeedTests(FloppyApiTestCase):
    """The feed pages in server order and reports its retained range."""

    def setUp(self):
        """Create changes to read back."""
        super().setUp()
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
        self.changes = [
            record_progress_change(self.user1, self.item, position_seconds=n * 10)
            for n in range(1, 6)
        ]

    def test_feed_returns_changes_after_the_cursor(self):
        """A cursor excludes everything at or below it."""
        response = self.client.get(
            f"{FEED}?cursor={self.changes[1].sequence}",
            **self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.OK)
        sequences = [row["sequence"] for row in response.data["results"]]
        self.assertEqual(sequences, [c.sequence for c in self.changes[2:]])

    def test_feed_reports_its_retained_range(self):
        """A client can tell whether its cursor is still inside the log."""
        response = self.client.get(FEED, **self.auth_headers)

        self.assertEqual(response.data["oldest_sequence"], self.changes[0].sequence)
        self.assertEqual(response.data["newest_sequence"], self.changes[-1].sequence)

    def test_a_compacted_cursor_is_refused(self):
        """Serving the tail would look like catch-up while dropping the middle."""
        ProgressChange.objects.filter(
            sequence__lte=self.changes[2].sequence,
        ).delete()

        response = self.client.get(
            f"{FEED}?cursor={self.changes[0].sequence}",
            **self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.CONFLICT)
        self.assertEqual(response.data["code"], "cursor_expired")

    def test_a_pull_records_the_checkpoint_for_a_named_connection(self):
        """Asking for changes after N proves the client applied through N."""
        binding, _ = get_or_create_binding(
            self.user1,
            SyncClientKind.GENERIC.value,
            instance_key="tv",
            profile_key="me",
        )

        self.client.get(
            f"{FEED}?cursor={self.changes[2].sequence}"
            f"&connection={binding.origin_key}",
            **self.auth_headers,
        )

        checkpoint = SyncCheckpoint.objects.get(binding=binding, resource="progress")
        self.assertEqual(checkpoint.last_sequence, self.changes[2].sequence)

    def test_an_unnamed_pull_records_nothing(self):
        """Without a connection there is no position to trust."""
        self.client.get(f"{FEED}?cursor=1", **self.auth_headers)

        self.assertEqual(SyncCheckpoint.objects.count(), 0)

    def test_a_bad_cursor_is_rejected(self):
        """A non-integer cursor is a client error, not a 500."""
        response = self.client.get(f"{FEED}?cursor=abc", **self.auth_headers)

        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_another_user_sees_none_of_it(self):
        """Change feeds are per user."""
        response = self.client.get(FEED, **self.auth_headers2)

        self.assertEqual(response.data["results"], [])
