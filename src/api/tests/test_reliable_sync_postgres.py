"""Real PostgreSQL commit-order proofs for reliable synchronization."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from app import reconcile_state
from app.models import Item, Movie, Status
from app.services.sync_lock import state_transaction
from app.tasks_watch_state import REPAIR_KEY, REPAIR_VERSION


@skipUnless(connection.vendor == "postgresql", "Requires real PostgreSQL row locks")
class ReliableSyncCommitOrderTests(TransactionTestCase):
    """Observe actual blocked backends before allowing a writer to finish."""

    def setUp(self):
        """Prepare source data and a completed canonical repair."""
        self.user = get_user_model().objects.create_user(username="sync-lock-owner")
        self.item = Item.objects.create(
            media_type="movie", source="tmdb", media_id="993001", title="Commit barrier"
        )
        reconcile_state.get_state(f"{REPAIR_KEY}_user_{self.user.pk}", REPAIR_VERSION)
        reconcile_state.mark_complete(
            f"{REPAIR_KEY}_user_{self.user.pk}", REPAIR_VERSION
        )
        self.headers = {"HTTP_X_API_KEY": self.user.token}
        self.client = APIClient()
        self.metadata = patch(
            "app.providers.services.get_media_metadata",
            return_value={"max_progress": None},
        )
        self.metadata.start()
        self.addCleanup(self.metadata.stop)

    def bootstrap(self):
        """Create a baseline through the real HTTP view."""
        response = self.client.post("/api/v1/sync/bootstrap/", **self.headers)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def request_after_barrier(self, barrier, backend, path, *, post=False):
        """Open an independent connection and announce its PostgreSQL backend."""
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                backend.append(cursor.fetchone()[0])
            barrier.wait(timeout=15)
            client = APIClient()
            response = (
                client.post(path, **self.headers)
                if post
                else client.get(path, **self.headers)
            )
            return response.status_code, response.data
        finally:
            connections.close_all()

    def assert_backend_waiting_on_writer(self, backend):
        """Prove lock contention rather than relying on thread scheduling delays."""
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_blocking_pids(%s)", [backend])
                blockers = cursor.fetchone()[0]
                cursor.execute("SELECT pg_backend_pid()")
                own_backend = cursor.fetchone()[0]
            if own_backend in blockers:
                return
        self.fail("Reader never blocked on the uncommitted writer's sequence lock")

    def test_bootstrap_waits_for_allocated_uncommitted_event(self):
        """Bootstrap includes a prior committed event, never an invisible watermark."""
        # Enable emission so the writer allocates an event even before bootstrap.
        from app.models import WatchStateSequence

        WatchStateSequence.objects.create(user=self.user, emit_changes=True)
        barrier = threading.Barrier(2)
        backend = []
        with ThreadPoolExecutor(max_workers=1) as executor:
            with state_transaction(self.user.pk):
                Movie.objects.create(
                    user=self.user, item=self.item, status=Status.COMPLETED.value
                )
                future = executor.submit(
                    self.request_after_barrier,
                    barrier,
                    backend,
                    "/api/v1/sync/bootstrap/",
                    post=True,
                )
                barrier.wait(timeout=15)
                self.assert_backend_waiting_on_writer(backend[0])
            status, context = future.result(timeout=15)
        self.assertEqual(status, 200)
        snapshot = self.client.get(context["snapshots"]["watched"], **self.headers)
        self.assertTrue(snapshot.data["results"][0]["watched"])

    def test_feed_waits_for_commit_and_cannot_skip_event(self):
        """A feed cannot advance beyond an allocated but invisible event."""
        context = self.bootstrap()
        barrier = threading.Barrier(2)
        backend = []
        with ThreadPoolExecutor(max_workers=1) as executor:
            with state_transaction(self.user.pk):
                Movie.objects.create(
                    user=self.user, item=self.item, status=Status.COMPLETED.value
                )
                future = executor.submit(
                    self.request_after_barrier,
                    barrier,
                    backend,
                    context["feeds"]["watched"],
                )
                barrier.wait(timeout=15)
                self.assert_backend_waiting_on_writer(backend[0])
            status, page = future.result(timeout=15)
        self.assertEqual(status, 200)
        self.assertTrue(page["results"][0]["watched"])
        self.assertEqual(page["next_cursor"], page["results"][-1]["sequence"])

    def test_first_activation_waits_for_a_previously_quiet_writer(self):
        """A write beginning before enablement is in the baseline or replay."""
        barrier = threading.Barrier(2)
        backend = []
        with ThreadPoolExecutor(max_workers=1) as executor:
            with state_transaction(self.user.pk):
                Movie.objects.create(
                    user=self.user, item=self.item, status=Status.COMPLETED.value
                )
                starter = executor.submit(
                    self.request_after_barrier,
                    barrier,
                    backend,
                    "/api/v1/sync/bootstrap/",
                    post=True,
                )
                barrier.wait(timeout=15)
                self.assert_backend_waiting_on_writer(backend[0])
            status, context = starter.result(timeout=15)
        self.assertEqual(status, 200)
        page = self.client.get(context["snapshots"]["watched"], **self.headers)
        self.assertTrue(page.data["results"][0]["watched"])
        self.assertEqual(
            self.client.get(context["feeds"]["watched"], **self.headers).data[
                "results"
            ],
            [],
        )

    def test_snapshot_continues_after_connection_restart(self):
        """Continuation relies on signed and durable state, not a live session."""
        from urllib.parse import urlencode

        second = Item.objects.create(
            media_type="movie", source="tmdb", media_id="993002", title="Second"
        )
        for item in (self.item, second):
            Movie.objects.create(
                user=self.user, item=item, status=Status.COMPLETED.value
            )
        context = self.bootstrap()
        first = self.client.get(
            context["snapshots"]["watched"] + "&limit=1", **self.headers
        )
        self.assertTrue(first.data["has_more"])
        continuation = first.data["after"]
        connections.close_all()
        client = APIClient()
        following = client.get(
            context["snapshots"]["watched"] + "&" + urlencode({"after": continuation}),
            **self.headers,
        )
        self.assertEqual(following.status_code, 200)
        self.assertEqual(following.data["results"][0]["item_id"], second.pk)

    def test_quiet_bulk_write_cannot_race_a_ready_bootstrap(self):
        """First activation rechecks baseline readiness under the commit barrier."""
        barrier = threading.Barrier(2)
        backend = []
        with ThreadPoolExecutor(max_workers=1) as executor:
            with state_transaction(self.user.pk):
                Movie.objects.bulk_create(
                    [
                        Movie(
                            user=self.user,
                            item=self.item,
                            status=Status.COMPLETED.value,
                        )
                    ]
                )
                starter = executor.submit(
                    self.request_after_barrier,
                    barrier,
                    backend,
                    "/api/v1/sync/bootstrap/",
                    post=True,
                )
                barrier.wait(timeout=15)
                self.assert_backend_waiting_on_writer(backend[0])
            status, response = starter.result(timeout=15)
        self.assertEqual(status, 409)
        self.assertEqual(response["code"], "sync_initializing")
        # The eager test worker completed repair; a real worker does this on
        # the default queue while the client retries initialization.
        context = self.bootstrap()
        snapshot = self.client.get(context["snapshots"]["watched"], **self.headers)
        self.assertTrue(snapshot.data["results"][0]["watched"])

    def test_feed_waits_for_rollback_without_publishing_its_sequence(self):
        """Rollback removes both source state and allocated event position."""
        context = self.bootstrap()
        barrier = threading.Barrier(2)
        backend = []
        with ThreadPoolExecutor(max_workers=1) as executor:
            with state_transaction(self.user.pk):
                Movie.objects.create(
                    user=self.user, item=self.item, status=Status.COMPLETED.value
                )
                future = executor.submit(
                    self.request_after_barrier,
                    barrier,
                    backend,
                    context["feeds"]["watched"],
                )
                barrier.wait(timeout=15)
                self.assert_backend_waiting_on_writer(backend[0])
                transaction.set_rollback(True)
            status, page = future.result(timeout=15)
        self.assertEqual(status, 200)
        self.assertEqual(page["results"], [])
        self.assertEqual(page["next_cursor"], context["cursors"]["watched"])
        self.assertFalse(Movie.objects.filter(user=self.user).exists())

    def test_simultaneous_bootstrap_preserves_first_context(self):
        """Two clients start together without rotating or resetting one another."""
        barrier = threading.Barrier(3)
        backend = []
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    self.request_after_barrier,
                    barrier,
                    backend,
                    "/api/v1/sync/bootstrap/",
                    post=True,
                )
                for _ in range(2)
            ]
            barrier.wait(timeout=15)
            results = [future.result(timeout=15) for future in futures]
        self.assertTrue(all(status == 200 for status, _ in results), results)
        first, second = [payload for _, payload in results]
        self.assertEqual(first["generation"], second["generation"])
        for context in (first, second):
            self.assertEqual(
                self.client.get(
                    context["feeds"]["watched"], **self.headers
                ).status_code,
                200,
            )

    def test_bootstrap_while_another_client_consumes(self):
        """Concurrent bootstrap and consumption preserve the existing baseline."""
        context = self.bootstrap()
        Movie.objects.create(
            user=self.user, item=self.item, status=Status.COMPLETED.value
        )
        barrier = threading.Barrier(3)
        backend = []
        with ThreadPoolExecutor(max_workers=2) as executor:
            reader = executor.submit(
                self.request_after_barrier,
                barrier,
                backend,
                context["feeds"]["watched"],
            )
            starter = executor.submit(
                self.request_after_barrier,
                barrier,
                backend,
                "/api/v1/sync/bootstrap/",
                post=True,
            )
            barrier.wait(timeout=15)
            read_status, page = reader.result(timeout=15)
            start_status, newer = starter.result(timeout=15)
        self.assertEqual((read_status, start_status), (200, 200))
        self.assertEqual(newer["generation"], context["generation"])
        self.assertTrue(page["results"][0]["watched"])
        self.assertEqual(
            self.client.get(context["feeds"]["watched"], **self.headers).status_code,
            200,
        )

    def test_compaction_cannot_race_into_an_empty_success(self):
        """The reader sees expiration after pruning, never a missing successful page."""
        from datetime import timedelta

        from django.utils import timezone

        from app.models import WatchStateChange
        from integrations.tasks._change_log import compact_watch_state_changes

        context = self.bootstrap()
        Movie.objects.create(
            user=self.user, item=self.item, status=Status.COMPLETED.value
        )
        WatchStateChange.objects.filter(user=self.user).update(
            created_at=timezone.now() - timedelta(days=31)
        )
        barrier = threading.Barrier(2)
        backend = []
        with ThreadPoolExecutor(max_workers=1) as executor:
            with state_transaction(self.user.pk):
                compact_watch_state_changes()
                reader = executor.submit(
                    self.request_after_barrier,
                    barrier,
                    backend,
                    context["feeds"]["watched"],
                )
                barrier.wait(timeout=15)
                self.assert_backend_waiting_on_writer(backend[0])
            status, page = reader.result(timeout=15)
        self.assertEqual(status, 409)
        self.assertEqual(page["code"], "cursor_expired")
