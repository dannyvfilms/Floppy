"""Outbound delivery: exactly once, never to the sender, never blind on retry.

The failure this file mostly guards against is a duplicate write. Floppy models
a repeat as an extra row and providers model it as a scalar, so a write issued
twice is not idempotent at the product level even when the HTTP call is — it
can become a play the user never had.
"""

import datetime
import logging
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import (
    Item,
    MediaTypes,
    Sources,
    WatchStateOrigin,
)
from app.services.watch_state import record_state_change
from integrations.models import (
    CAPABILITY_WATCHED_PUSH_PLAYED,
    CAPABILITY_WATCHED_PUSH_UNPLAYED,
    CAPABILITY_WATCHED_READ,
    OutboundDeliveryStatus,
    OutboundStateDelivery,
    SyncClientKind,
    SyncDirection,
    UnresolvedExternalReference,
)
from integrations.state import outbound
from integrations.state.adapters.base import (
    RemoteState,
    TerminalAdapterError,
    TransientAdapterError,
)
from integrations.state.identity import activate_binding, get_or_create_binding


def setUpModule():
    """Silence log noise for this module only."""
    logging.disable(logging.DEBUG)


def tearDownModule():
    """Restore logging so other modules' assertLogs still see records."""
    logging.disable(logging.NOTSET)


def _dt(day):
    return datetime.datetime(2026, 5, day, 12, tzinfo=datetime.UTC)


class FakeAdapter:
    """An adapter that records what the engine asked it to do."""

    CAPABILITIES = frozenset(
        {
            CAPABILITY_WATCHED_READ,
            CAPABILITY_WATCHED_PUSH_PLAYED,
            CAPABILITY_WATCHED_PUSH_UNPLAYED,
        },
    )

    def __init__(self, *, external_id="jf-1", remote=None, write_error=None):
        """Configure the fake's responses."""
        self.external_id = external_id
        self.remote = remote
        self.write_error = write_error
        self.writes = []
        self.reads = 0

    def resolve_external_id(self, item):
        """Return the configured id."""
        return self.external_id

    def read_state(self, external_id):
        """Return the configured remote state."""
        self.reads += 1
        return self.remote

    def write_watched(self, external_id, *, watched):
        """Record the write, or raise the configured error."""
        self.writes.append((external_id, watched))
        if self.write_error is not None:
            raise self.write_error
        self.remote = RemoteState(watched=watched, play_count=1 if watched else 0)


class OutboundTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="owner")
        self.item, _ = Item.objects.get_or_create(
            media_id="3000",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={"title": "Film"},
        )
        self.binding, _ = get_or_create_binding(
            self.user,
            SyncClientKind.JELLYFIN.value,
            instance_key="server-1",
            profile_key="user-1",
        )
        activate_binding(
            self.binding,
            capabilities=[
                CAPABILITY_WATCHED_READ,
                CAPABILITY_WATCHED_PUSH_PLAYED,
                CAPABILITY_WATCHED_PUSH_UNPLAYED,
            ],
            directions=[SyncDirection.OUTBOUND.value],
        )
        self.adapter = FakeAdapter()
        patcher = patch.object(
            outbound,
            "get_adapter",
            return_value=self.adapter,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _change(self, *, watched=True, play_count=1, day=1, origin_key="local"):
        return record_state_change(
            self.user,
            self.item,
            watched=watched,
            play_count=play_count,
            watched_at=_dt(day),
            origin_kind=WatchStateOrigin.LOCAL_UI.value,
            origin_key=origin_key,
        ).change


class EnqueueTests(OutboundTestCase):
    def test_a_local_change_creates_a_delivery(self):
        self._change()

        delivery = OutboundStateDelivery.objects.get(binding=self.binding)
        self.assertEqual(delivery.status, OutboundDeliveryStatus.PENDING.value)
        self.assertTrue(delivery.intent)
        self.assertEqual(delivery.item_id, self.item.pk)

    def test_a_change_is_never_sent_back_to_the_provider_that_caused_it(self):
        """The own-origin skip. Without it, A tells us and we tell A."""
        self._change(origin_key=self.binding.origin_key)

        self.assertFalse(OutboundStateDelivery.objects.exists())

    def test_no_delivery_without_the_outbound_capability(self):
        activate_binding(
            self.binding,
            capabilities=[CAPABILITY_WATCHED_READ],
            directions=[SyncDirection.OUTBOUND.value],
        )

        self._change()

        self.assertFalse(OutboundStateDelivery.objects.exists())

    def test_an_unwatch_needs_its_own_capability(self):
        activate_binding(
            self.binding,
            capabilities=[CAPABILITY_WATCHED_PUSH_PLAYED],
            directions=[SyncDirection.OUTBOUND.value],
        )
        self._change(watched=True)
        OutboundStateDelivery.objects.all().delete()

        self._change(watched=False, play_count=0)

        self.assertFalse(OutboundStateDelivery.objects.exists())

    def test_rapid_changes_coalesce_to_the_latest(self):
        self._change(play_count=1, day=1)
        self._change(play_count=2, day=2)
        self._change(play_count=3, day=3)

        pending = OutboundStateDelivery.objects.filter(
            status=OutboundDeliveryStatus.PENDING.value,
        )
        self.assertEqual(pending.count(), 1)
        superseded = OutboundStateDelivery.objects.filter(
            status=OutboundDeliveryStatus.SUPERSEDED.value,
        )
        self.assertEqual(superseded.count(), 2)


class DeliveryTests(OutboundTestCase):
    def test_a_delivery_writes_once_and_reads_back(self):
        self._change()
        delivery = OutboundStateDelivery.objects.get()

        outbound.run_delivery(delivery.pk)

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, OutboundDeliveryStatus.DELIVERED.value)
        self.assertEqual(self.adapter.writes, [("jf-1", True)])
        self.assertTrue(delivery.readback_digest)
        self.assertIsNotNone(delivery.delivered_at)

    def test_a_claimed_delivery_cannot_be_claimed_twice(self):
        self._change()
        delivery = OutboundStateDelivery.objects.get()

        first = outbound.claim(delivery.pk)
        second = outbound.claim(delivery.pk)

        self.assertIsNotNone(first)
        self.assertIsNone(second, "two workers must not both take one delivery")

    def test_a_write_that_timed_out_but_applied_is_not_written_again(self):
        """The retry-by-read-first rule.

        A write can succeed and then the connection drop. Re-issuing blindly is
        exactly how a timeout becomes a phantom second play.
        """
        self._change()
        delivery = OutboundStateDelivery.objects.get()
        self.adapter.write_error = TransientAdapterError("connection reset")

        outbound.run_delivery(delivery.pk)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, OutboundDeliveryStatus.PENDING.value)
        self.assertEqual(len(self.adapter.writes), 1)

        # The write had in fact applied on the provider.
        self.adapter.write_error = None
        self.adapter.remote = RemoteState(watched=True, play_count=1)
        delivery.next_attempt_at = None
        delivery.save(update_fields=["next_attempt_at"])

        outbound.run_delivery(delivery.pk)

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, OutboundDeliveryStatus.DELIVERED.value)
        self.assertEqual(
            len(self.adapter.writes),
            1,
            "the second attempt must read, not write again",
        )

    def test_a_transient_failure_is_rescheduled_with_backoff(self):
        self._change()
        delivery = OutboundStateDelivery.objects.get()
        self.adapter.write_error = TransientAdapterError("503")

        outbound.run_delivery(delivery.pk)

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, OutboundDeliveryStatus.PENDING.value)
        self.assertIsNotNone(delivery.next_attempt_at)
        self.assertEqual(delivery.attempts, 1)

    def test_a_terminal_failure_is_not_retried(self):
        self._change()
        delivery = OutboundStateDelivery.objects.get()
        self.adapter.write_error = TerminalAdapterError("bad credentials")

        outbound.run_delivery(delivery.pk)

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, OutboundDeliveryStatus.FAILED.value)
        self.assertIsNone(delivery.next_attempt_at)

    def test_repeated_transient_failures_eventually_give_up(self):
        self._change()
        delivery = OutboundStateDelivery.objects.get()
        self.adapter.write_error = TransientAdapterError("503")

        for _ in range(outbound.MAX_ATTEMPTS + 1):
            delivery.refresh_from_db()
            if delivery.status != OutboundDeliveryStatus.PENDING.value:
                break
            delivery.next_attempt_at = None
            delivery.save(update_fields=["next_attempt_at"])
            outbound.run_delivery(delivery.pk)

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, OutboundDeliveryStatus.FAILED.value)

    def test_an_unresolvable_item_is_recorded_and_not_retried(self):
        self._change()
        delivery = OutboundStateDelivery.objects.get()
        self.adapter.external_id = None

        outbound.run_delivery(delivery.pk)

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, OutboundDeliveryStatus.SKIPPED.value)
        self.assertEqual(self.adapter.writes, [])
        self.assertEqual(UnresolvedExternalReference.objects.count(), 1)

    def test_a_repeated_unresolvable_item_counts_rather_than_accumulates(self):
        self.adapter.external_id = None
        self._change(play_count=1, day=1)
        outbound.run_delivery(OutboundStateDelivery.objects.first().pk)
        self._change(play_count=2, day=2)
        pending = OutboundStateDelivery.objects.filter(
            status=OutboundDeliveryStatus.PENDING.value,
        ).first()
        outbound.run_delivery(pending.pk)

        reference = UnresolvedExternalReference.objects.get()
        self.assertEqual(reference.occurrence_count, 2)

    def test_a_binding_disabled_mid_flight_writes_nothing(self):
        self._change()
        delivery = OutboundStateDelivery.objects.get()
        self.binding.kill_switch = True
        self.binding.save(update_fields=["kill_switch"])

        outbound.run_delivery(delivery.pk)

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, OutboundDeliveryStatus.SKIPPED.value)
        self.assertEqual(self.adapter.writes, [])


class SweepTests(OutboundTestCase):
    def test_the_sweep_picks_up_a_delivery_whose_kick_was_lost(self):
        from integrations.tasks import sweep_watched_state_deliveries

        self._change()
        delivery = OutboundStateDelivery.objects.get()

        swept = sweep_watched_state_deliveries()

        delivery.refresh_from_db()
        self.assertEqual(swept, 1)
        self.assertEqual(delivery.status, OutboundDeliveryStatus.DELIVERED.value)

    def test_the_sweep_leaves_a_backed_off_delivery_alone(self):
        from django.utils import timezone

        from integrations.tasks import sweep_watched_state_deliveries

        self._change()
        delivery = OutboundStateDelivery.objects.get()
        delivery.next_attempt_at = timezone.now() + timezone.timedelta(hours=1)
        delivery.save(update_fields=["next_attempt_at"])

        swept = sweep_watched_state_deliveries()

        self.assertEqual(swept, 0)
        self.assertEqual(self.adapter.writes, [])
