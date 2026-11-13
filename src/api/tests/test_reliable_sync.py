"""The bootstrap/snapshot/replay contract, including its failure boundaries."""

import io
from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection, transaction
from django.test import tag
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from app import reconcile_state
from app.models import (
    Item,
    Movie,
    PlaybackProgress,
    ProgressChange,
    Status,
    WatchState,
    WatchStateChange,
    WatchStateSequence,
)
from app.tasks_watch_state import REPAIR_KEY, REPAIR_VERSION
from integrations.models import IntegrationToken
from integrations.state.identity import (
    activate_binding,
    deactivate_binding,
    get_or_create_binding,
)
from integrations.tasks._change_log import compact_watch_state_changes

from .base import FloppyApiTestCase

BOOTSTRAP = "/api/v1/sync/bootstrap/"
SNAPSHOT = "/api/v1/sync/snapshot/"


class ReliableSyncTests(FloppyApiTestCase):
    """Use real source writes and authenticated requests, not hand-made events."""

    def setUp(self):
        """Prepare repaired canonical state, as the existing worker would."""
        super().setUp()
        reconcile_state.get_state(f"{REPAIR_KEY}_user_{self.user1.pk}", REPAIR_VERSION)
        reconcile_state.mark_complete(
            f"{REPAIR_KEY}_user_{self.user1.pk}", REPAIR_VERSION
        )
        self.item = Item.objects.create(
            media_type="movie", source="tmdb", media_id="9900901", title="Sync film"
        )

    def bootstrap(self, headers=None):
        """Start a separate client's baseline."""
        response = self.client.post(BOOTSTRAP, **(headers or self.auth_headers))
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def feed(self, context, resource="watched", cursor=None, **params):
        """Read a strict page using the returned context."""
        return self.client.get(
            f"/api/v1/sync/{'changes' if resource == 'watched' else 'progress-changes'}/",
            {
                "contract": 2,
                "context": context["context"],
                "cursor": context["cursors"][resource] if cursor is None else cursor,
                **params,
            },
            **self.auth_headers,
        )

    def snapshot(self, context, resource="watched", **params):
        """Continue the same stateless snapshot after interruption."""
        return self.client.get(
            SNAPSHOT,
            {"context": context["context"], "resource": resource, **params},
            **self.auth_headers,
        )

    def test_initialization_is_explicit(self):
        """An unfinished repair cannot become a successful empty baseline."""
        from app.models import BackfillReconcileState

        BackfillReconcileState.objects.filter(
            key=f"{REPAIR_KEY}_user_{self.user1.pk}"
        ).delete()
        with patch("api.fork_views_sync.backfill_watch_state.delay") as enqueue:
            response = self.client.post(BOOTSTRAP, **self.auth_headers)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "sync_initializing")
        enqueue.assert_called_once_with(user_id=self.user1.pk, only_if_pending=True)

    def test_quiet_bulk_writes_require_repair_before_first_bootstrap(self):
        """Preserve legacy bulk behavior without publishing its stale baseline."""
        from app.tasks_watch_state import backfill_watch_state

        Movie.objects.bulk_create(
            [Movie(user=self.user1, item=self.item, status=Status.COMPLETED.value)]
        )
        with patch("api.fork_views_sync.backfill_watch_state.delay"):
            response = self.client.post(BOOTSTRAP, **self.auth_headers)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "sync_initializing")
        backfill_watch_state(user_id=self.user1.pk)
        context = self.bootstrap()
        self.assertTrue(
            any(
                row["item_id"] == self.item.pk and row["watched"]
                for row in self.snapshot(context).data["results"]
            )
        )
        self.assertFalse(WatchStateChange.objects.filter(user=self.user1).exists())

    def test_duplicate_initialization_jobs_skip_completed_work(self):
        """Polling during repair cannot turn queued retries into repeated full scans."""
        from app.tasks_watch_state import backfill_watch_state

        Movie.objects.bulk_create(
            [Movie(user=self.user1, item=self.item, status=Status.COMPLETED.value)]
        )
        backfill_watch_state(user_id=self.user1.pk, only_if_pending=True)
        with patch("app.tasks_watch_state.backfill_user_watch_state") as scan:
            backfill_watch_state(user_id=self.user1.pk, only_if_pending=True)
        scan.assert_not_called()
        self.assertEqual(
            self.client.post(BOOTSTRAP, **self.auth_headers).status_code, 200
        )

    def test_baseline_repair_does_not_queue_legacy_provider_writes(self):
        """Canonical episode backfill is not an outbound MyAnimeList decision."""
        from app.tasks_watch_state import backfill_watch_state

        with patch("integrations.mal_sync.queue_grouped_sync") as enqueue:
            backfill_watch_state(user_id=self.user1.pk)
        enqueue.assert_not_called()
        self.assertFalse(WatchStateChange.objects.filter(user=self.user1).exists())

    def _assert_raced_repair(self, *, global_repair=False):
        """A change to an already-repaired item requires another repair pass."""
        from app.models import BackfillReconcileState
        from app.tasks_watch_state import (
            backfill_watch_state,
            project_watch_state,
            repair_watch_state,
        )

        Movie.objects.bulk_create(
            [Movie(user=self.user1, item=self.item, status=Status.COMPLETED.value)]
        )
        changed = False

        def project_then_change(user, item, **kwargs):
            nonlocal changed
            result = project_watch_state(user, item, **kwargs)
            if item.pk == self.item.pk and not changed:
                changed = True
                Movie.objects.filter(user=user, item=item).update(
                    status=Status.PLANNING.value
                )
            return result

        with patch(
            "app.tasks_watch_state.project_watch_state", side_effect=project_then_change
        ):
            if global_repair:
                self.assertFalse(repair_watch_state(time_budget=60))
            else:
                backfill_watch_state(user_id=self.user1.pk)
        self.assertIsNone(
            BackfillReconcileState.objects.get(
                key=f"{REPAIR_KEY}_user_{self.user1.pk}"
            ).completed_at
        )
        with patch("api.fork_views_sync.backfill_watch_state.delay"):
            self.assertEqual(
                self.client.post(BOOTSTRAP, **self.auth_headers).status_code, 409
            )
        backfill_watch_state(user_id=self.user1.pk)
        context = self.bootstrap()
        row = next(
            row
            for row in self.snapshot(context).data["results"]
            if row["item_id"] == self.item.pk
        )
        self.assertFalse(row["watched"])

    def test_repair_cannot_publish_ready_after_a_concurrent_quiet_bulk_write(self):
        """Keep a manually repaired baseline pending when a visited item changes."""
        self._assert_raced_repair()

    def test_budgeted_repair_cannot_overwrite_quiet_write_invalidation(self):
        """Keep the durable restart cursor at zero when an earlier item changed."""
        self._assert_raced_repair(global_repair=True)

    def test_api_key_bootstrap_and_web_unwatch(self):
        """Umbrella's cursor-zero reproduction is explicit and subsequent writes arrive."""
        movie = Movie.objects.create(
            user=self.user1, item=self.item, status=Status.COMPLETED.value
        )
        legacy = self.client.get("/api/v1/sync/changes/", **self.auth_headers)
        self.assertEqual(legacy.data["results"], [])
        self.assertFalse(legacy.data["recording_enabled"])
        context = self.bootstrap()
        self.client.force_login(self.user1)
        response = self.client.post(
            reverse("media_save"),
            {
                "instance_id": movie.pk,
                "media_id": self.item.media_id,
                "source": "tmdb",
                "media_type": "movie",
                "status": Status.PLANNING.value,
                "progress": 0,
                "repeats": 0,
                "notes": "",
            },
        )
        self.assertIn(response.status_code, (200, 302))
        response = self.feed(context)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["results"][-1]["watched"])
        self.assertEqual(self.feed(context, cursor=0).data["code"], "cursor_expired")

    def test_legacy_client_survives_another_clients_bootstrap(self):
        """Activation fences are strict-only, not physical legacy history loss."""
        binding, _ = get_or_create_binding(self.user1, "generic")
        activate_binding(binding, capabilities=["watched.read"], directions=["inbound"])
        movie = Movie.objects.create(
            user=self.user1, item=self.item, status=Status.COMPLETED.value
        )
        first = self.client.get("/api/v1/sync/changes/", **self.auth_headers)
        cursor = first.data["next_cursor"]
        self.bootstrap()
        movie.status = Status.PLANNING.value
        movie.save()
        response = self.client.get(
            "/api/v1/sync/changes/", {"cursor": cursor}, **self.auth_headers
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["results"][-1]["watched"])
        deactivate_binding(binding)
        self.assertTrue(
            WatchStateSequence.objects.get(user=self.user1).api_feed_enabled
        )

    def test_progress_clear_and_sparse_shared_sequences(self):
        """A resource's first sequence need not be adjacent to its cursor."""
        context = self.bootstrap()
        movie = Movie.objects.create(
            user=self.user1, item=self.item, status=Status.COMPLETED.value
        )
        movie.status = Status.PLANNING.value
        movie.save()
        progress = PlaybackProgress.objects.create(
            user=self.user1, item=self.item, position_seconds=42
        )
        response = self.feed(context, "progress")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"][-1]["position_seconds"], 42)
        progress.delete()
        self.assertEqual(
            self.feed(context, "progress").data["results"][-1]["kind"], "delete"
        )

    def test_episode_identity_drop_and_repeat_are_actionable(self):
        """An episode remains identifiable through unwatch, repeat and resume."""
        from app.models import Episode

        episode = self.episode_medias[0]
        context = self.bootstrap()
        episode.status = Status.DROPPED.value
        episode.save()
        row = self.feed(context).data["results"][-1]
        self.assertFalse(row["watched"])
        self.assertEqual(row["season_number"], episode.item.season_number)
        self.assertEqual(row["episode_number"], episode.item.episode_number)
        Episode.objects.create(
            item=episode.item,
            related_season=episode.related_season,
            status=Status.COMPLETED.value,
        )
        self.assertTrue(self.feed(context).data["results"][-1]["watched"])
        PlaybackProgress.objects.create(
            user=self.user1, item=episode.item, position_seconds=123
        )
        progress = self.feed(context, "progress").data["results"][-1]
        self.assertEqual(progress["episode_number"], episode.item.episode_number)
        snapshot = self.snapshot(context, "progress").data["results"]
        self.assertTrue(
            any(
                row["item_id"] == episode.item_id and row["position_seconds"] == 123
                for row in snapshot
            )
        )

    def test_duplicate_pages_and_independent_bootstrap(self):
        """Another bootstrap never rotates generation or expires an existing client."""
        first = self.bootstrap()
        Movie.objects.create(
            user=self.user1, item=self.item, status=Status.COMPLETED.value
        )
        second = self.bootstrap()
        self.assertEqual(first["generation"], second["generation"])
        original = self.feed(first).data
        self.assertEqual(original, self.feed(first).data)
        self.assertEqual(len(original["results"]), 1)
        self.assertEqual(self.feed(second).data["results"], [])

    def test_snapshot_keyset_and_replay_after_restart(self):
        """Removal, update and insertion cannot shift an unchanged row past pagination."""
        for n in range(3):
            item = Item.objects.create(
                media_type="movie",
                source="tmdb",
                media_id=str(9900910 + n),
                title="Baseline",
            )
            Movie.objects.create(
                user=self.user1, item=item, status=Status.COMPLETED.value
            )
        context = self.bootstrap()
        first = self.snapshot(context, limit=1)
        self.assertTrue(first.data["has_more"])
        first_id = first.data["results"][0]["item_id"]
        Movie.objects.filter(user=self.user1, item_id=first_id).delete()
        late_item = Item.objects.create(
            media_type="movie", source="tmdb", media_id="9900999", title="Late"
        )
        Movie.objects.create(
            user=self.user1, item=late_item, status=Status.COMPLETED.value
        )
        # Lose all process-local client/view objects: context survives via signing
        # and database state, without an in-memory snapshot session.
        from rest_framework.test import APIClient

        self.client = APIClient()
        after = first.data["after"]
        ids = {first_id}
        while after:
            page = self.snapshot(context, limit=1, after=after)
            self.assertEqual(page.status_code, 200, page.data)
            ids.update(row["item_id"] for row in page.data["results"])
            after = page.data["after"]
        self.assertNotIn(late_item.pk, ids)
        changes = self.feed(context).data["results"]
        self.assertTrue(
            any(row["item_id"] == first_id and not row["watched"] for row in changes)
        )
        self.assertTrue(
            any(row["item_id"] == late_item.pk and row["watched"] for row in changes)
        )
        self.assertGreaterEqual(len(ids), 3)

    def test_retention_and_empty_logs_keep_validity(self):
        """Both resources expire explicitly even after every event is removed."""
        context = self.bootstrap()
        Movie.objects.create(
            user=self.user1, item=self.item, status=Status.COMPLETED.value
        )
        PlaybackProgress.objects.create(
            user=self.user1, item=self.item, position_seconds=30
        )
        for model in (WatchStateChange, ProgressChange):
            model.objects.filter(user=self.user1).update(
                created_at=timezone.now() - timedelta(days=31)
            )
        compact_watch_state_changes()
        for resource in ("watched", "progress"):
            response = self.feed(context, resource)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.data["code"], "cursor_expired")
        self.assertFalse(ProgressChange.objects.filter(user=self.user1).exists())
        self.assertFalse(WatchStateChange.objects.filter(user=self.user1).exists())

    def test_validation_precedes_checkpoint(self):
        """Untrusted context or position never advances a connection's proof."""
        context = self.bootstrap()
        binding, _ = get_or_create_binding(self.user1, "generic")
        for params in (
            {"cursor": -1},
            {"cursor": "x"},
            {"limit": 0},
            {"limit": 501},
            {"contract": "3"},
        ):
            self.assertEqual(
                self.feed(context, connection=binding.origin_key, **params).status_code,
                400,
            )
        self.assertEqual(
            self.feed(context, cursor=10**9).data["code"], "cursor_invalid"
        )
        self.assertFalse(binding.checkpoints.exists())
        cross_user = self.client.get(context["feeds"]["watched"], **self.auth_headers2)
        self.assertEqual(cross_user.status_code, 400)

    def test_generation_reset_and_destructive_delete(self):
        """Administrative invalidation and lost identity force a new baseline."""
        context = self.bootstrap()
        Movie.objects.create(
            user=self.user1, item=self.item, status=Status.COMPLETED.value
        )
        row = WatchStateSequence.objects.get(user=self.user1)
        call_command(
            "invalidate_sync_contexts", user_id=self.user1.pk, stdout=io.StringIO()
        )
        self.assertEqual(self.feed(context).data["code"], "sync_reset_required")
        row.refresh_from_db()
        self.assertTrue(row.api_feed_enabled)
        newer = self.bootstrap()
        self.item.delete()
        self.assertEqual(self.feed(newer).data["code"], "sync_reset_required")

    def test_reset_command_requires_explicit_selection(self):
        """Administrative reset cannot accidentally select an implicit population."""
        from django.core.management.base import CommandError

        for arguments in (
            (),
            ("--all-users", "--user-id", str(self.user1.pk)),
            ("--user-id", "999999"),
        ):
            with self.subTest(arguments=arguments), self.assertRaises(CommandError):
                call_command(
                    "invalidate_sync_contexts",
                    *arguments,
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                )

    def test_relational_catalog_delete_does_not_append_orphan_events(self):
        """Deleting children cannot change which root Item rows are being removed."""
        context = self.bootstrap()
        Movie.objects.create(
            user=self.user1, item=self.item, status=Status.COMPLETED.value
        )
        Item.objects.filter(movie__user=self.user1, pk=self.item.pk).delete()
        self.assertFalse(Item.objects.filter(pk=self.item.pk).exists())
        self.assertFalse(
            WatchStateChange.objects.filter(
                user=self.user1, item_id=self.item.pk
            ).exists()
        )
        self.assertEqual(self.feed(context).data["code"], "sync_reset_required")

    def test_account_cascade_does_not_recreate_an_allocator(self):
        """Deleting an older account with no allocator leaves no protocol rows."""
        self.bootstrap()
        Movie.objects.create(
            user=self.user1, item=self.item, status=Status.COMPLETED.value
        )
        PlaybackProgress.objects.create(
            user=self.user1, item=self.item, position_seconds=30
        )
        user_id = self.user1.pk
        WatchStateSequence.objects.filter(user_id=user_id).delete()
        from app.signals import deleting_account

        with deleting_account():
            self.user1.__class__.objects.filter(pk=user_id).delete()
        self.assertFalse(WatchStateSequence.objects.filter(user_id=user_id).exists())
        self.assertFalse(WatchStateChange.objects.filter(user_id=user_id).exists())
        self.assertFalse(ProgressChange.objects.filter(user_id=user_id).exists())

    def test_snapshot_continuations_are_resource_and_context_bound(self):
        """A progress page cannot skip watched rows or cross bootstrap boundaries."""
        first = self.bootstrap()
        for item in self.items_by_type["movie"][:2]:
            PlaybackProgress.objects.create(
                user=self.user1, item=item, position_seconds=30
            )
        progress = self.snapshot(first, resource="progress", limit=1)
        self.assertTrue(progress.data["has_more"])
        token = progress.data["after"]
        self.assertEqual(
            self.snapshot(first, resource="watched", after=token).status_code, 400
        )
        newer = self.bootstrap()
        self.assertEqual(
            self.snapshot(newer, resource="progress", after=token).status_code, 400
        )

    def test_last_page_high_water_and_limited_pagination(self):
        """Lookahead distinguishes an exact final page and covers unrelated sequences."""
        context = self.bootstrap()
        movie = Movie.objects.create(
            user=self.user1, item=self.item, status=Status.COMPLETED.value
        )
        movie.status = Status.PLANNING.value
        movie.save()
        PlaybackProgress.objects.create(
            user=self.user1, item=self.item, position_seconds=10
        )
        first = self.feed(context, limit=1).data
        self.assertTrue(first["has_more"])
        last = self.feed(context, cursor=first["next_cursor"], limit=1).data
        self.assertFalse(last["has_more"])
        self.assertEqual(last["next_cursor"], last["high_water"])
        self.assertGreater(last["next_cursor"], last["results"][-1]["sequence"])
        empty = self.feed(context, cursor=last["next_cursor"]).data
        self.assertEqual(empty["results"], [])
        self.assertTrue(empty["complete"])

    def test_source_event_rollback_is_atomic(self):
        """A failed projection cannot commit a source change without its event."""
        context = self.bootstrap()
        with patch(
            "app.services.watch_state.WatchStateChange.objects.create",
            side_effect=RuntimeError,
        ):
            with self.assertRaises(RuntimeError), transaction.atomic():
                Movie.objects.create(
                    user=self.user1, item=self.item, status=Status.COMPLETED.value
                )
        self.assertFalse(Movie.objects.filter(user=self.user1, item=self.item).exists())
        self.assertEqual(self.feed(context).data["results"], [])

    def test_bulk_writes_and_quiet_repair(self):
        """Bulk changes publish, while a quiet baseline correction invalidates."""
        from app.services.watch_state import project_watch_state

        context = self.bootstrap()
        Movie.objects.bulk_create(
            [Movie(user=self.user1, item=self.item, status=Status.COMPLETED.value)]
        )
        self.assertTrue(self.feed(context).data["results"][-1]["watched"])
        Movie.objects.filter(user=self.user1, item=self.item).update(
            status=Status.PLANNING.value
        )
        self.assertFalse(self.feed(context).data["results"][-1]["watched"])
        WatchState.objects.filter(user=self.user1, item=self.item).update(
            watched=True, state_digest="incorrect"
        )
        project_watch_state(self.user1, self.item, record_changes=False)
        self.assertEqual(self.feed(context).data["code"], "sync_reset_required")

    def test_missing_bootstrap_and_scope(self):
        """A version parameter is not an authorization or bootstrap substitute."""
        response = self.client.get(
            "/api/v1/sync/changes/", {"contract": 2}, **self.auth_headers
        )
        self.assertEqual(response.data["code"], "sync_not_initialized")
        token, secret = IntegrationToken.generate(
            user=self.user1, name="No sync", scopes=["catalog:read"]
        )
        self.assertEqual(
            self.client.post(
                BOOTSTRAP, HTTP_AUTHORIZATION=f"Bearer {secret}"
            ).status_code,
            403,
        )

    def test_oauth_device_bootstrap_and_revocation(self):
        """An approved device uses the same contract without a provider binding."""
        from integrations.oauth_models import OAUTH_DEVICE_CODE_GRANT, OAuthClient

        oauth = OAuthClient.register_public_client(
            name="Sync device", allowed_scopes=["sync:read"]
        )
        device = self.client.post(
            reverse("oauth_device_authorization"),
            {"client_id": oauth.client_id, "scope": "sync:read"},
        ).json()
        self.client.force_login(self.user1)
        self.assertEqual(
            self.client.post(
                reverse("oauth_device"),
                {"user_code": device["user_code"], "action": "approve"},
            ).status_code,
            200,
        )
        response = self.client.post(
            reverse("oauth_token"),
            {
                "client_id": oauth.client_id,
                "grant_type": OAUTH_DEVICE_CODE_GRANT,
                "device_code": device["device_code"],
            },
        )
        self.assertEqual(response.status_code, 200, response.json())
        self.client.logout()
        headers = {"HTTP_AUTHORIZATION": f"Bearer {response.json()['access_token']}"}
        context = self.bootstrap(headers)
        self.assertFalse(self.user1.sync_bindings.exists())
        self.assertEqual(
            self.client.get(context["feeds"]["watched"], **headers).status_code, 200
        )
        IntegrationToken.objects.filter(
            user=self.user1, client_identifier=oauth.client_id
        ).update(revoked_at=timezone.now())
        self.assertIn(
            self.client.get(context["feeds"]["watched"], **headers).status_code,
            (401, 403),
        )
        self.assertTrue(
            WatchStateSequence.objects.get(user=self.user1).api_feed_enabled
        )

    def test_identity_rewrite_invalidates_context(self):
        """Both direct and bulk identity changes invalidate prior matching keys."""
        Movie.objects.create(
            user=self.user1, item=self.item, status=Status.COMPLETED.value
        )
        context = self.bootstrap()
        self.item.media_id = "9912345"
        self.item.save(update_fields=["media_id"])
        self.assertEqual(self.feed(context).data["code"], "sync_reset_required")
        newer = self.bootstrap()
        Item.objects.filter(pk=self.item.pk).update(media_id="9912346")
        self.assertEqual(self.feed(newer).data["code"], "sync_reset_required")

    @tag("slow", "benchmark")
    def test_28000_item_snapshot_is_bounded(self):
        """Read one page without hydrating the full library or large artwork JSON."""
        import tracemalloc

        items = Item.objects.bulk_create(
            [
                Item(
                    media_type="movie",
                    source="tmdb",
                    media_id=str(10000000 + n),
                    title="Large library",
                    watch_providers={"padding": "x" * 10000},
                )
                for n in range(28000)
            ],
            batch_size=500,
        )
        WatchState.objects.bulk_create(
            [WatchState(user=self.user1, item=item, watched=True) for item in items],
            batch_size=500,
        )
        context = self.bootstrap()
        tracemalloc.start()
        try:
            with CaptureQueriesContext(connection) as queries:
                response = self.snapshot(context, limit=500)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 500)
        self.assertLess(peak, 12 * 1024 * 1024)
        self.assertLessEqual(len(queries), 15)
        self.assertFalse(any('"watch_providers"' in query["sql"] for query in queries))
