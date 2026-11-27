"""Commit and replay controls for database-only integration callbacks."""

import time
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus as HTTP  # noqa: N814
from queue import Queue
from threading import Event
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import connection, connections
from django.test import TransactionTestCase
from rest_framework.response import Response

from integrations.delivery import get_or_record_atomic_receipt
from integrations.models import IntegrationEventReceipt


class AtomicDeliveryReceiptTests(TransactionTestCase):
    """Exercise the real receipt model with synthetic durable effects."""

    def setUp(self):
        """Create a receipt owner."""
        self.user = get_user_model().objects.create_user(username="receipt-probe")

    def record(self, callback, *, key="watch-1", payload=None, user=None):
        """Call the atomic gateway for a synthetic viewing."""
        return get_or_record_atomic_receipt(
            user=user or self.user,
            client_event_id=key,
            payload=payload or {"action": "stop"},
            execute_fn=callback,
        )

    @staticmethod
    def write(name, status=HTTP.OK):
        """Write a fixture row in the transaction shared with the receipt."""
        Group.objects.create(name=f"receipt-probe-{name}")
        return Response({"detail": name}, status=status)

    def forbidden_callback(self):
        """A replay or conflict must never rerun the callback."""
        self.fail("Replayed event ran its callback")

    def test_transient_response_rolls_back_and_can_retry(self):
        """An unsuccessful server response leaves neither record committed."""
        response, replayed = self.record(
            lambda: self.write("transient", HTTP.SERVICE_UNAVAILABLE)
        )
        self.assertEqual(response.status_code, HTTP.SERVICE_UNAVAILABLE)
        self.assertFalse(replayed)
        self.assertFalse(Group.objects.filter(name="receipt-probe-transient").exists())
        self.assertFalse(
            IntegrationEventReceipt.objects.filter(user=self.user).exists()
        )

        response, replayed = self.record(lambda: self.write("recovered"))
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertFalse(replayed)
        self.assertEqual(
            IntegrationEventReceipt.objects.get(user=self.user).response_body,
            {"detail": "recovered"},
        )

    def test_exception_rolls_back_the_callback_and_the_claim(self):
        """A write followed by a raised exception leaves no orphan state."""

        def fail_after_write():
            self.write("exception")
            msg = "synthetic database-phase interruption"
            raise RuntimeError(msg)

        with self.assertRaisesRegex(RuntimeError, "database-phase interruption"):
            self.record(fail_after_write)
        self.assertFalse(Group.objects.filter(name="receipt-probe-exception").exists())
        self.assertFalse(
            IntegrationEventReceipt.objects.filter(user=self.user).exists()
        )

    def test_terminal_response_replays_and_changed_payload_conflicts(self):
        """Keep terminal non-5xx snapshots and the existing conflict shape."""
        self.record(
            lambda: Response({"code": "MEDIA_NOT_FOUND"}, status=HTTP.NOT_FOUND)
        )
        response, replayed = self.record(self.forbidden_callback)
        self.assertTrue(replayed)
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)
        self.assertEqual(response.data, {"code": "MEDIA_NOT_FOUND"})

        response, replayed = self.record(
            self.forbidden_callback, payload={"action": "start"}
        )
        self.assertFalse(replayed)
        self.assertEqual(response.status_code, HTTP.CONFLICT)
        self.assertEqual(response.data["error"]["code"], "idempotency_conflict")

    def test_distinct_viewing_keys_and_accounts_are_independent(self):
        """Each genuine viewing reaches the callback under its own key."""
        first = {"action": "stop", "played_at": "2026-01-01T10:00:00Z"}
        second = {"action": "stop", "played_at": "2026-01-01T10:05:00Z"}
        other = get_user_model().objects.create_user(username="receipt-probe-other")
        self.record(lambda: self.write("first"), payload=first)
        self.record(lambda: self.write("second"), key="watch-2", payload=second)
        self.record(lambda: self.write("other"), user=other, payload=second)

        self.assertEqual(
            Group.objects.filter(name__startswith="receipt-probe-").count(), 3
        )
        self.assertEqual(
            IntegrationEventReceipt.objects.filter(user=self.user).count(), 2
        )
        self.assertEqual(IntegrationEventReceipt.objects.filter(user=other).count(), 1)

    @skipUnless(
        connection.vendor == "postgresql", "Requires PostgreSQL lock observation"
    )
    def test_competing_identical_receipt_waits_and_replays_after_commit(self):
        """Prove the unique key blocks a second connection before its callback."""
        writer_ready = Queue()
        replay_ready = Queue()
        release_writer = Event()

        def backend_pid():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                return cursor.fetchone()[0]

        def first_callback():
            response = self.write("concurrent")
            writer_ready.put(backend_pid())
            if not release_writer.wait(timeout=15):
                msg = "Fixture writer was never released"
                raise TimeoutError(msg)
            return response

        def write_receipt():
            try:
                return self.record(first_callback)
            finally:
                connections.close_all()

        def replay_receipt():
            try:
                replay_ready.put(backend_pid())
                return self.record(self.forbidden_callback)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            writer = executor.submit(write_receipt)
            writer_pid = writer_ready.get(timeout=10)
            reader = executor.submit(replay_receipt)
            try:
                reader_pid = replay_ready.get(timeout=10)
                deadline = time.monotonic() + 10
                while True:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_blocking_pids(%s)", [reader_pid])
                        blockers = cursor.fetchone()[0]
                    if writer_pid in blockers:
                        break
                    if time.monotonic() >= deadline:
                        self.fail(
                            "Duplicate receipt did not wait for the original transaction"
                        )
                    time.sleep(0.01)
                self.assertFalse(
                    IntegrationEventReceipt.objects.filter(user=self.user).exists()
                )
            finally:
                release_writer.set()

            original, was_replay = writer.result(timeout=15)
            replay, is_replay = reader.result(timeout=15)

        self.assertFalse(was_replay)
        self.assertTrue(is_replay)
        self.assertEqual(
            (replay.status_code, replay.data), (original.status_code, original.data)
        )
        self.assertEqual(
            IntegrationEventReceipt.objects.filter(user=self.user).count(), 1
        )
        self.assertEqual(
            Group.objects.filter(name="receipt-probe-concurrent").count(), 1
        )
