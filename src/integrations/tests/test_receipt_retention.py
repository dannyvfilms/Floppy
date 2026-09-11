"""Binding-scoped idempotency receipts and their retention."""

from datetime import timedelta
from http import HTTPStatus as HTTP  # noqa: N814

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.response import Response

from integrations.delivery import get_or_record_receipt
from integrations.models import IntegrationEventReceipt, SyncClientKind
from integrations.state.identity import get_or_create_binding
from integrations.tasks._receipts import compact_integration_event_receipts


def ok(body=None):
    """Return a callable producing a 200 response."""
    return lambda: Response(body if body is not None else {"ok": True})


class BindingScopedReceiptTests(TestCase):
    """One client event id per binding, not per user."""

    def setUp(self):
        """Create a user with two bound devices."""
        self.user = get_user_model().objects.create_user(username="receipts")
        self.tv, _ = get_or_create_binding(
            self.user,
            SyncClientKind.GENERIC.value,
            instance_key="living-room",
            profile_key="me",
        )
        self.phone, _ = get_or_create_binding(
            self.user,
            SyncClientKind.GENERIC.value,
            instance_key="phone",
            profile_key="me",
        )

    def test_two_devices_may_reuse_one_event_id(self):
        """A per-install counter on two devices is not an idempotency conflict."""
        first, first_replay = get_or_record_receipt(
            user=self.user,
            client_event_id="1",
            payload={"position": 10},
            execute_fn=ok(),
            binding=self.tv,
        )
        second, second_replay = get_or_record_receipt(
            user=self.user,
            client_event_id="1",
            payload={"position": 900},
            execute_fn=ok(),
            binding=self.phone,
        )

        self.assertEqual(first.status_code, HTTP.OK)
        self.assertFalse(first_replay)
        self.assertEqual(second.status_code, HTTP.OK)
        self.assertFalse(second_replay)
        self.assertEqual(IntegrationEventReceipt.objects.count(), 2)

    def test_same_binding_same_payload_replays(self):
        """A retry from one device returns the prior result."""
        get_or_record_receipt(
            user=self.user,
            client_event_id="7",
            payload={"position": 10},
            execute_fn=ok({"created": 1}),
            binding=self.tv,
        )
        response, replay = get_or_record_receipt(
            user=self.user,
            client_event_id="7",
            payload={"position": 10},
            execute_fn=ok({"created": 2}),
            binding=self.tv,
        )

        self.assertTrue(replay)
        self.assertEqual(response.data, {"created": 1})
        self.assertEqual(IntegrationEventReceipt.objects.count(), 1)

    def test_same_binding_changed_payload_conflicts(self):
        """Reusing an event id with a different payload is still a conflict."""
        get_or_record_receipt(
            user=self.user,
            client_event_id="7",
            payload={"position": 10},
            execute_fn=ok(),
            binding=self.tv,
        )
        response, replay = get_or_record_receipt(
            user=self.user,
            client_event_id="7",
            payload={"position": 11},
            execute_fn=ok(),
            binding=self.tv,
        )

        self.assertFalse(replay)
        self.assertEqual(response.status_code, HTTP.CONFLICT)
        self.assertEqual(
            response.data["error"]["code"],
            "idempotency_conflict",
        )

    def test_unbound_requests_still_deduplicate_per_user(self):
        """A credential with no binding keeps the old user-scoped behaviour."""
        get_or_record_receipt(
            user=self.user,
            client_event_id="9",
            payload={"a": 1},
            execute_fn=ok({"n": 1}),
        )
        response, replay = get_or_record_receipt(
            user=self.user,
            client_event_id="9",
            payload={"a": 1},
            execute_fn=ok({"n": 2}),
        )

        self.assertTrue(replay)
        self.assertEqual(response.data, {"n": 1})

    def test_bound_and_unbound_do_not_collide(self):
        """A bound event id does not shadow the unbound one, or vice versa."""
        get_or_record_receipt(
            user=self.user,
            client_event_id="5",
            payload={"a": 1},
            execute_fn=ok(),
        )
        _, replay = get_or_record_receipt(
            user=self.user,
            client_event_id="5",
            payload={"a": 2},
            execute_fn=ok(),
            binding=self.tv,
        )

        self.assertFalse(replay)
        self.assertEqual(IntegrationEventReceipt.objects.count(), 2)

    def test_another_user_is_isolated(self):
        """Event ids are not a cross-user handle."""
        other = get_user_model().objects.create_user(username="other")
        get_or_record_receipt(
            user=self.user,
            client_event_id="3",
            payload={"a": 1},
            execute_fn=ok({"mine": True}),
        )
        response, replay = get_or_record_receipt(
            user=other,
            client_event_id="3",
            payload={"a": 1},
            execute_fn=ok({"mine": False}),
        )

        self.assertFalse(replay)
        self.assertEqual(response.data, {"mine": False})


class ReceiptCompactionTests(TestCase):
    """Retention deletes old receipts and keeps the count."""

    def setUp(self):
        """Create a user."""
        self.user = get_user_model().objects.create_user(username="compaction")

    def make(self, event_id, age_days):
        """Create a receipt aged by ``age_days``."""
        receipt = IntegrationEventReceipt.objects.create(
            user=self.user,
            client_event_id=event_id,
            payload_digest="d",
            response_status_code=200,
            response_body={},
        )
        IntegrationEventReceipt.objects.filter(pk=receipt.pk).update(
            created_at=timezone.now() - timedelta(days=age_days),
        )
        return receipt

    def test_expired_receipts_are_deleted(self):
        """Receipts past the window go."""
        self.make("old", 30)
        self.make("older", 60)

        deleted = compact_integration_event_receipts(retention_days=14)

        self.assertEqual(deleted, 2)
        self.assertEqual(IntegrationEventReceipt.objects.count(), 0)

    def test_live_receipts_are_kept(self):
        """A receipt inside the window is still replayable."""
        self.make("fresh", 1)

        deleted = compact_integration_event_receipts(retention_days=14)

        self.assertEqual(deleted, 0)
        self.assertEqual(IntegrationEventReceipt.objects.count(), 1)

    def test_compaction_is_batched(self):
        """More rows than one batch still clear, without one huge delete."""
        for index in range(12):
            self.make(f"e{index}", 30)

        deleted = compact_integration_event_receipts(
            retention_days=14,
            batch_size=5,
        )

        self.assertEqual(deleted, 12)
        self.assertEqual(IntegrationEventReceipt.objects.count(), 0)

    def test_deleted_count_is_returned_for_metrics(self):
        """The count outlives the rows it describes."""
        self.make("old", 30)
        self.make("fresh", 1)

        self.assertEqual(compact_integration_event_receipts(retention_days=14), 1)
