"""Checkpoints over the change feed, and the compaction they gate."""

import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from app.models import Item
from app.models.choices import MediaTypes, Sources
from app.models.watch_state import WatchStateChange
from integrations.models import SyncBindingStatus, SyncCheckpoint, SyncClientKind
from integrations.state.checkpoints import (
    compaction_watermark,
    record_applied_position,
)
from integrations.state.identity import get_or_create_binding
from integrations.tasks._change_log import compact_watch_state_changes


class CheckpointRecordingTests(TestCase):
    """A checkpoint records what a binding proved it applied."""

    def setUp(self):
        """Create a user with one binding."""
        self.user = get_user_model().objects.create_user(username="cp")
        self.binding, _ = get_or_create_binding(
            self.user,
            SyncClientKind.GENERIC.value,
            instance_key="tv",
            profile_key="me",
        )

    def test_first_position_creates_a_checkpoint(self):
        """Nothing wrote SyncCheckpoint before; now something does."""
        record_applied_position(self.binding, 12)

        checkpoint = SyncCheckpoint.objects.get(binding=self.binding)
        self.assertEqual(checkpoint.last_sequence, 12)
        self.assertEqual(checkpoint.cursor, "12")

    def test_position_advances(self):
        """A later pull moves the checkpoint forward."""
        record_applied_position(self.binding, 12)
        record_applied_position(self.binding, 30)

        self.assertEqual(
            SyncCheckpoint.objects.get(binding=self.binding).last_sequence,
            30,
        )

    def test_position_never_moves_backwards(self):
        """A replayed or out-of-order pull cannot re-expose compacted changes."""
        record_applied_position(self.binding, 30)
        record_applied_position(self.binding, 5)

        self.assertEqual(
            SyncCheckpoint.objects.get(binding=self.binding).last_sequence,
            30,
        )


class WatermarkTests(TestCase):
    """The watermark is the lowest position any live binding has reached."""

    def setUp(self):
        """Create a user with two bindings."""
        self.user = get_user_model().objects.create_user(username="wm")
        self.tv, _ = get_or_create_binding(
            self.user,
            SyncClientKind.GENERIC.value,
            instance_key="tv",
            profile_key="me",
        )
        self.phone, _ = get_or_create_binding(
            self.user,
            SyncClientKind.GENERIC.value,
            instance_key="phone",
            profile_key="me",
        )

    def test_no_bindings_means_no_watermark(self):
        """With nobody listening, checkpoints decide nothing."""
        other = get_user_model().objects.create_user(username="nobody")
        self.assertIsNone(compaction_watermark(other))

    def test_a_binding_that_applied_nothing_blocks_compaction(self):
        """Every change is still owed to a binding at position zero."""
        record_applied_position(self.tv, 50)

        self.assertIsNone(compaction_watermark(self.user))

    def test_watermark_is_the_slowest_binding(self):
        """The furthest-behind device decides what may be deleted."""
        record_applied_position(self.tv, 50)
        record_applied_position(self.phone, 10)

        self.assertEqual(compaction_watermark(self.user), 10)

    def test_a_stale_binding_stops_pinning_the_log(self):
        """A device that stopped checking in must re-snapshot, not hold the log."""
        record_applied_position(self.tv, 50)
        record_applied_position(self.phone, 10)
        SyncCheckpoint.objects.filter(binding=self.phone).update(
            updated_at=timezone.now() - timedelta(days=90),
        )

        watermark = compaction_watermark(
            self.user,
            stale_before=timezone.now() - timedelta(days=30),
        )

        self.assertEqual(watermark, 50)


class ChangeLogCompactionTests(TestCase):
    """Compaction respects both retention and the watermark."""

    def setUp(self):
        """Create a user, a binding, and an item to hang changes off."""
        self.user = get_user_model().objects.create_user(username="compact")
        self.binding, _ = get_or_create_binding(
            self.user,
            SyncClientKind.GENERIC.value,
            instance_key="tv",
            profile_key="me",
        )
        self.binding.status = SyncBindingStatus.ACTIVE.value
        self.binding.save(update_fields=["status"])
        self.item, _ = Item.objects.get_or_create(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={"title": "The Matrix"},
        )

    def make_change(self, sequence, age_days):
        """Create one aged change at ``sequence``."""
        change = WatchStateChange.objects.create(
            user=self.user,
            item=self.item,
            sequence=sequence,
            revision=sequence,
            kind="upsert",
            watched=True,
            play_count=1,
            correlation_id=uuid.uuid4(),
        )
        WatchStateChange.objects.filter(pk=change.pk).update(
            created_at=timezone.now() - timedelta(days=age_days),
        )
        return change

    def test_applied_and_aged_changes_are_deleted(self):
        """Past retention and below the watermark, a change may go."""
        self.make_change(1, 90)
        self.make_change(2, 90)
        record_applied_position(self.binding, 2)

        deleted = compact_watch_state_changes(retention_days=30)

        self.assertEqual(deleted, 2)
        self.assertEqual(WatchStateChange.objects.count(), 0)

    def test_unapplied_changes_survive_retention(self):
        """Age alone never deletes a change a live binding still needs."""
        self.make_change(1, 90)
        self.make_change(2, 90)
        record_applied_position(self.binding, 1)

        compact_watch_state_changes(retention_days=30)

        remaining = set(
            WatchStateChange.objects.values_list("sequence", flat=True),
        )
        self.assertEqual(remaining, {2})

    def test_recent_changes_survive_the_watermark(self):
        """Applied but still inside retention stays; a late client may re-read."""
        self.make_change(1, 1)
        record_applied_position(self.binding, 1)

        deleted = compact_watch_state_changes(retention_days=30)

        self.assertEqual(deleted, 0)
        self.assertEqual(WatchStateChange.objects.count(), 1)

    def test_a_binding_with_no_checkpoint_blocks_everything(self):
        """Fail closed: an unproven binding keeps the whole log."""
        self.make_change(1, 90)

        deleted = compact_watch_state_changes(retention_days=30)

        self.assertEqual(deleted, 0)
        self.assertEqual(WatchStateChange.objects.count(), 1)
