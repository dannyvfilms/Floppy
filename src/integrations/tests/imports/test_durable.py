"""Crash boundaries and provenance of durable import transactions."""

from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from app.models import (
    TV,
    DeletedMedia,
    Episode,
    Item,
    Movie,
    Season,
    Status,
    WatchState,
)
from integrations import import_progress
from integrations.import_scope import ImportOverwriteConflictError
from integrations.imports import durable, helpers
from integrations.models import ImportChunkReceipt, ImportRun


@override_settings(TRAKT_IMPORT_CHUNK_ROWS=2)
class DurableImportTests(TransactionTestCase):
    """Receipts commit atomically with each ordered media/history batch."""

    def setUp(self):
        """Prepare three watches without live provider access."""
        self.user = get_user_model().objects.create_user(username="durable")
        self.run = ImportRun.objects.create(user=self.user, source="trakt")
        self.owner = durable.claim(self.run)
        item = Item.objects.bulk_create([Item(media_id="durable", source="tmdb", media_type="movie", title="Movie")])[0]
        rows = [Movie(item=item, user=self.user, status=Status.COMPLETED) for _ in range(3)]
        durable.stage(self.run, self.owner, {"movie": rows}, [], {"mode": "new"})

    def persist(self):
        """Use the same ambient history attribution as the task boundary."""
        with import_progress.tracking(None, self.run.pk):
            return durable.persist(self.run, self.owner, self.user)

    def test_chunk_receipts_and_provenance(self):
        self.persist()
        self.assertEqual(Movie.objects.count(), 3)
        self.assertEqual(Movie.history.count(), 3)
        self.assertEqual(set(Movie.objects.values_list("import_run_id", flat=True)), {self.run.pk})
        self.assertEqual(set(Movie.history.values_list("history_user_id", flat=True)), {self.user.pk})
        self.assertEqual(list(ImportChunkReceipt.objects.order_by("start").values_list("rows_persisted", flat=True)), [2, 1])
        self.assertTrue(all(r.metrics["chunk_rows"] <= 2 for r in self.run.chunk_receipts.all()))

    def test_failure_before_receipt_rolls_back_data_history_and_cursor(self):
        with patch.object(ImportChunkReceipt.objects, "create", side_effect=RuntimeError("crash")), self.assertRaises(RuntimeError):
            self.persist()
        self.run.refresh_from_db()
        self.assertEqual(self.run.commit_cursor, 0)
        self.assertEqual(Movie.objects.count(), 0)
        self.assertEqual(Movie.history.count(), 0)
        self.persist()
        self.assertEqual(Movie.objects.count(), 3)

    def test_failure_after_commit_resumes_without_duplicate_watches(self):
        with patch("app.statistics_sync.mark_aggregate", side_effect=RuntimeError("crash")), self.assertRaises(RuntimeError):
            self.persist()
        durable.release(self.run, self.owner)
        self.owner = durable.claim(self.run)
        self.assertEqual(self.run.commit_cursor, 2)
        self.persist()
        self.assertEqual(Movie.objects.count(), 3)
        self.assertEqual(Movie.history.count(), 3)

    def test_stale_fence_cannot_write(self):
        durable.release(self.run, self.owner)
        durable.claim(self.run)
        with self.assertRaises(helpers.MediaImportError):
            self.persist()
        self.assertEqual(Movie.objects.count(), 0)

    def test_cancellation_keeps_committed_prefix(self):
        with patch("app.statistics_sync.mark_aggregate", side_effect=RuntimeError("crash")), self.assertRaises(RuntimeError):
            self.persist()
        ImportRun.objects.filter(pk=self.run.pk).update(cancel_requested=True)
        with self.assertRaises(helpers.MediaImportError):
            self.persist()
        self.assertEqual(Movie.objects.count(), 2)

    def test_tracking_row_written_after_staging_is_reused(self):
        """A row stored between staging and persist must not fail the chunk (#1518)."""
        item = Item.objects.create(
            media_id="raced-show",
            source="tmdb",
            media_type="tv",
            title="Raced Show",
        )
        queued = TV(item=item, user=self.user, status=Status.IN_PROGRESS)
        durable.stage(self.run, self.owner, {"tv": [queued]}, [], {"mode": "new"})
        stored = TV.objects.create(
            item=item,
            user=self.user,
            status=Status.COMPLETED,
        )

        self.persist()

        self.assertEqual(TV.objects.filter(user=self.user, item=item).count(), 1)
        self.assertEqual(
            TV.objects.get(user=self.user, item=item).status,
            Status.COMPLETED.value,
        )
        self.run.refresh_from_db()
        self.assertEqual(self.run.commit_cursor, 1)
        self.assertEqual(
            self.run.prepared_entries.get().persisted_pk,
            stored.pk,
        )

    def test_exact_watch_and_history_timestamp_survives_staging(self):
        """JSON storage must not round away replay-identity microseconds."""
        watched = timezone.now().replace(microsecond=123456)
        row = Movie(item=Item.objects.first(), user=self.user, status=Status.COMPLETED, end_date=watched)
        row._history_date = watched
        durable.stage(self.run, self.owner, {"movie": [row]}, [], {"mode": "new"})
        self.persist()
        self.assertEqual(Movie.objects.get().end_date, watched)
        self.assertEqual(Movie.history.get().history_date, watched)

    def test_retained_manifest_detects_changed_or_missing_segment(self):
        """A resume cannot silently accept a different staged prefix."""
        durable.verify_prepared(self.run)
        self.run.prepared_entries.filter(ordinal=1).update(digest="changed")
        with self.assertRaisesMessage(helpers.MediaImportError, "segment changed"):
            durable.verify_prepared(self.run)

    def test_expired_owner_is_fenced_when_another_worker_claims(self):
        """A killed worker cannot regain its old fence after lease takeover."""
        ImportRun.objects.filter(pk=self.run.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        replacement = ImportRun.objects.get(pk=self.run.pk)
        durable.claim(replacement)
        with self.assertRaises(helpers.MediaImportError):
            self.persist()
        self.assertEqual(Movie.objects.count(), 0)

    def test_stale_in_memory_cursor_replays_receipt_without_writing_twice(self):
        """A duplicate invocation reads the committed database cursor."""
        self.persist()
        self.run.commit_cursor = 0
        self.persist()
        self.assertEqual(Movie.objects.count(), 3)
        self.assertEqual(Movie.history.count(), 3)

    def test_outbox_failure_retains_pending_work_and_duplicate_delivery_is_safe(self):
        """Broker failure never acknowledges the durable publication intent."""
        self.persist()
        durable.release(self.run, self.owner)
        with (patch("app.history_cache.invalidate_history_cache"),
              patch("app.statistics_cache.invalidate_all_statistics_days"),
              patch("events.tasks.reload_calendar.delay", side_effect=OSError("broker"))):
            with self.assertRaises(OSError):
                durable.publish_pending(self.run)
        self.assertEqual(self.run.chunk_receipts.filter(publication_pending=True).count(), 2)
        with (patch("app.history_cache.invalidate_history_cache"),
              patch("app.statistics_cache.invalidate_all_statistics_days"),
              patch("events.tasks.reload_calendar.delay") as publish):
            self.assertTrue(durable.publish_pending(self.run))
            self.assertFalse(durable.publish_pending(self.run))
            self.assertEqual(publish.call_count, 1)

    def test_task_retry_resumes_original_run_and_provenance(self):
        """Fresh parser eligibility never replaces a partially committed plan."""
        from integrations.imports import trakt
        from integrations.tasks._media_imports import import_media

        durable.release(self.run, self.owner)
        ImportRun.objects.filter(pk=self.run.pk).update(status=ImportRun.Status.COMPLETED)
        item = Item.objects.first()

        def invoke(_identifier, user, mode, username=None):
            importer = SimpleNamespace(
                user=user, mode=mode, username=username, warnings=[], tv_completion_dates={},
                bulk_media={"movie": [Movie(item=item, user=user, status=Status.COMPLETED) for _ in range(3)]},
                to_delete={}, completed_seasons=[], completed_tvs=[], dropped_tvs=[],
            )
            return durable.run_import(importer, prepare_input=False)

        invoke.__module__ = "integrations.imports.trakt"
        with patch.object(trakt, "importer", invoke), patch.object(durable, "publish_pending"):
            from app import statistics_sync

            mark = statistics_sync.mark_aggregate

            def fail_after_chunk(user_id, *, reason, **kwargs):
                if reason == "import_chunk":
                    raise RuntimeError("crash")
                return mark(user_id, reason=reason, **kwargs)

            with patch("app.statistics_sync.mark_aggregate", side_effect=fail_after_chunk), self.assertRaises(RuntimeError):
                import_media(invoke, None, self.user.pk, "new", "public")
            failed = ImportRun.objects.get(status=ImportRun.Status.FAILED)
            self.assertEqual(Movie.objects.count(), 2)
            self.assertEqual(failed.commit_cursor, 2)
            import_media(invoke, None, self.user.pk, "new", "public")
        failed.refresh_from_db()
        self.assertEqual(failed.status, ImportRun.Status.COMPLETED)
        self.assertEqual(Movie.objects.count(), 3)
        self.assertEqual(set(Movie.objects.values_list("import_run_id", flat=True)), {failed.pk})

    def test_overwrite_delete_receipt_rolls_back_then_preserves_replacements(self):
        """Deletion retry uses original PKs and cannot sweep replacement rows."""
        original = Movie.objects.bulk_create([Movie(item=Item.objects.first(), user=self.user, status=Status.PLANNING)])[0]
        scopes = {"movie": {"tmdb": [original.item.media_id]}}
        with import_progress.tracking(None, self.run.pk):
            durable.snapshot_overwrite(self.run, self.owner, scopes, self.user)
            durable.stage(self.run, self.owner, {"movie": []}, [], {"mode": "overwrite", "overwrite_scopes": scopes})
            with patch.object(ImportChunkReceipt.objects, "create", side_effect=RuntimeError("crash")), self.assertRaises(RuntimeError):
                durable.delete_overwrite(self.run, self.owner)
            self.assertTrue(Movie.objects.filter(pk=original.pk).exists())
            self.assertFalse(self.run.overwrite_targets.get().deleted)
            durable.delete_overwrite(self.run, self.owner)
            replacement = Movie.objects.bulk_create([Movie(item=original.item, user=self.user)])[0]
            durable.delete_overwrite(self.run, self.owner)
        self.assertTrue(Movie.objects.filter(pk=replacement.pk).exists())
        receipt = self.run.chunk_receipts.get(phase="delete")
        self.assertTrue(receipt.metrics["commit_observed"])

    def test_overwrite_delete_does_not_tombstone_the_replaced_row(self):
        """Replacing a title is the import's doing, not the user deleting it."""
        original = Movie.objects.bulk_create([Movie(item=Item.objects.first(), user=self.user, status=Status.PLANNING)])[0]
        scopes = {"movie": {"tmdb": [original.item.media_id]}}
        with import_progress.tracking(None, self.run.pk):
            durable.snapshot_overwrite(self.run, self.owner, scopes, self.user)
            durable.stage(self.run, self.owner, {"movie": []}, [], {"mode": "overwrite", "overwrite_scopes": scopes})
            durable.delete_overwrite(self.run, self.owner)
        self.assertFalse(Movie.objects.filter(pk=original.pk).exists())
        self.assertFalse(DeletedMedia.objects.filter(user=self.user).exists())

    def test_overwrite_scope_fences_orm_and_bulk_writes_but_not_other_titles(self):
        """Cooperating writers reject a replacement scope before mutation."""
        item = Item.objects.first()
        existing = Movie.objects.bulk_create([Movie(item=item, user=self.user)])[0]
        scopes = {"movie": {"tmdb": [item.media_id]}}
        durable.stage(self.run, self.owner, {"movie": []}, [], {"mode": "overwrite", "overwrite_scopes": scopes})
        with self.assertRaises(ImportOverwriteConflictError):
            Movie.objects.bulk_create([Movie(item=item, user=self.user)])
        with self.assertRaises(ImportOverwriteConflictError):
            Movie.objects.filter(pk=existing.pk).update(notes="edit")
        with self.assertRaises(ImportOverwriteConflictError):
            Movie.objects.filter(pk=existing.pk).delete()
        with self.assertRaises(ImportOverwriteConflictError):
            existing.save()
        other = Item.objects.bulk_create([Item(media_id="other", source="tmdb", media_type="movie", title="Other")])[0]
        Movie.objects.bulk_create([Movie(item=other, user=self.user)])
        self.assertEqual(Movie.objects.count(), 2)

    def test_overwrite_fingerprint_refuses_uncooperative_edit(self):
        """Even a writer bypassing guards cannot make replay delete an edit."""
        row = Movie.objects.bulk_create([Movie(item=Item.objects.first(), user=self.user)])[0]
        with import_progress.tracking(None, self.run.pk):
            durable.snapshot_overwrite(self.run, self.owner, {"movie": {"tmdb": [row.item.media_id]}}, self.user)
            Movie._base_manager.filter(pk=row.pk).update(notes="changed")
            with self.assertRaisesMessage(helpers.MediaImportError, "target changed"):
                durable.delete_overwrite(self.run, self.owner)
        self.assertEqual(Movie.objects.get(pk=row.pk).notes, "changed")

    @override_settings(TRAKT_IMPORT_STAGING_BYTES=1)
    def test_staging_quota_cannot_commit_watch_rows(self):
        """An oversized unsealed input does not become a partial success."""
        with self.assertRaisesMessage(helpers.MediaImportError, "staging quota"):
            durable.stage(self.run, self.owner, {"movie": [Movie(item=Item.objects.first(), user=self.user)]}, [], {"mode": "new"})
        self.assertEqual(Movie.objects.count(), 0)

    def test_only_first_completed_identity_normalizes_plans_across_chunks(self):
        """Boundaries cannot repeat the original first-watch planning merge."""
        from app.services.completion import normalize_completed_entries

        plan = Movie.objects.bulk_create([Movie(
            item=Item.objects.first(), user=self.user, status=Status.PLANNING, notes="planned", score=7,
        )])[0]
        with patch("app.services.completion.normalize_completed_entries", wraps=normalize_completed_entries) as normalize:
            self.persist()
        self.assertEqual(sum(bool(call.args[0]) for call in normalize.call_args_list), 1)
        self.assertFalse(Movie.objects.filter(pk=plan.pk).exists())
        rows = list(Movie.objects.order_by("pk"))
        self.assertEqual([row.notes for row in rows], ["planned", "", ""])
        self.assertEqual([row.score for row in rows], [7, None, None])

    def test_resume_does_not_consume_a_plan_created_after_first_watch_committed(self):
        """A new foreground rewatch plan is outside the original decision."""
        with patch("app.statistics_sync.mark_aggregate", side_effect=RuntimeError("crash")), self.assertRaises(RuntimeError):
            self.persist()
        plan = Movie.objects.bulk_create([Movie(
            item=Item.objects.first(), user=self.user, status=Status.PLANNING, notes="new rewatch plan",
        )])[0]
        durable.release(self.run, self.owner)
        self.owner = durable.claim(self.run)
        self.persist()
        self.assertTrue(Movie.objects.filter(pk=plan.pk).exists())
        self.assertEqual(Movie.objects.filter(status=Status.COMPLETED).count(), 3)

    @override_settings(TRAKT_IMPORT_CHUNK_ROWS=4)
    def test_chunk_size_recovers_after_transient_slow_commit(self):
        """Eight fast full chunks grow back within the configured hard ceiling."""
        rows = [Movie(item=Item.objects.first(), user=self.user, status=Status.COMPLETED) for _ in range(28)]
        durable.stage(self.run, self.owner, {"movie": rows}, [], {"mode": "new"})
        real_measure = durable.measure_transaction
        calls = 0

        @contextmanager
        def measurement(metrics):
            nonlocal calls
            with real_measure(metrics):
                yield
            calls += 1
            metrics["after_first_write_ms"] = 200 if calls == 1 else 1

        with patch.object(durable, "measure_transaction", measurement):
            self.persist()
        sizes = [receipt.metrics["chunk_rows"] for receipt in self.run.chunk_receipts.order_by("start")]
        self.assertEqual(sizes, [4, *([2] * 8), 4, 4])
        self.assertEqual(Movie.objects.count(), 28)

    def test_terminal_staging_expires_but_small_receipts_remain(self):
        """Housekeeping never deletes the audit row or media provenance owner."""
        durable.release(self.run, self.owner)
        receipt = ImportChunkReceipt.objects.create(run=self.run, start=0, end=1, digest="audit", fence=self.run.fence, publication_pending=False)
        ImportRun.objects.filter(pk=self.run.pk).update(status=ImportRun.Status.COMPLETED, finished_at=timezone.now() - timedelta(days=8))
        durable.recover_outboxes()
        self.run.refresh_from_db()
        self.assertEqual(self.run.phase, "expired")
        self.assertFalse(self.run.prepared_entries.exists())
        self.assertTrue(ImportChunkReceipt.objects.filter(pk=receipt.pk).exists())

    def test_failed_sealed_prefix_is_not_expired_automatically(self):
        """An abandoned worker still has retained input for an authorized retry."""
        durable.release(self.run, self.owner)
        ImportRun.objects.filter(pk=self.run.pk).update(status=ImportRun.Status.FAILED, finished_at=timezone.now() - timedelta(days=8))
        durable.recover_outboxes()
        self.assertEqual(self.run.prepared_entries.count(), 3)

    def test_terminal_cleanup_takes_over_expired_lease_but_not_live_owner(self):
        """A killed terminal worker cannot strand staging or defeat fencing."""
        ImportRun.objects.filter(pk=self.run.pk).update(
            status=ImportRun.Status.CANCELLED, finished_at=timezone.now() - timedelta(days=8),
        )
        durable.recover_outboxes()
        self.assertEqual(self.run.prepared_entries.count(), 3)
        old_fence = self.run.fence
        ImportRun.objects.filter(pk=self.run.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        durable.recover_outboxes()
        self.run.refresh_from_db()
        self.assertEqual(self.run.phase, "expired")
        self.assertGreater(self.run.fence, old_fence)
        self.assertFalse(self.run.prepared_entries.exists())
        self.assertIsNone(self.run.lease_expires_at)

    def test_overwrite_history_is_deleted_in_bounded_receipted_chunks(self):
        """Signal-driven history deletion cannot hide a large parent cascade."""
        row = Movie.objects.create(item=Item.objects.first(), user=self.user)
        for number in range(5):
            row.notes = str(number)
            row.save()
        self.assertEqual(Movie.history.filter(id=row.pk).count(), 6)
        with import_progress.tracking(None, self.run.pk):
            durable.snapshot_overwrite(self.run, self.owner, {"movie": {"tmdb": [row.item.media_id]}}, self.user)
            durable.delete_overwrite(self.run, self.owner)
        self.assertFalse(Movie.objects.filter(pk=row.pk).exists())
        self.assertFalse(Movie.history.filter(id=row.pk).exists())
        receipts = self.run.chunk_receipts.filter(phase="delete")
        self.assertEqual(sum(receipt.metrics["rows_deleted"] for receipt in receipts), 7)
        self.assertTrue(all(receipt.metrics["chunk_rows"] <= 2 for receipt in receipts))

    def test_overwrite_refuses_history_added_after_snapshot(self):
        """Uncooperative historical writes are retained rather than swept away."""
        row = Movie.objects.create(item=Item.objects.first(), user=self.user)
        with import_progress.tracking(None, self.run.pk):
            durable.snapshot_overwrite(self.run, self.owner, {"movie": {"tmdb": [row.item.media_id]}}, self.user)
            row.save()
            with self.assertRaisesMessage(helpers.MediaImportError, "new history records"):
                durable.delete_overwrite(self.run, self.owner)
        self.assertTrue(Movie.objects.filter(pk=row.pk).exists())
        self.assertEqual(Movie.history.filter(id=row.pk).count(), 1)

    def test_failed_append_discards_only_unsealed_suffix_on_retry(self):
        """Follow-up preparation cannot replace the committed main manifest."""
        self.persist()
        original_digest = self.run.prepared_digest
        rows = [Movie(item=Item.objects.first(), user=self.user, status=Status.COMPLETED) for _ in range(3)]
        create = durable.PreparedImportEntry.objects.bulk_create
        calls = 0

        def crash_after_first_batch(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("seal crash")
            return create(*args, **kwargs)

        with patch.object(durable.PreparedImportEntry.objects, "bulk_create", side_effect=crash_after_first_batch), self.assertRaises(RuntimeError):
            durable.stage(self.run, self.owner, {"movie": rows}, [], {}, append=True, operation_prefix="backfill_")
        self.run.refresh_from_db()
        self.assertEqual(self.run.prepared_digest, original_digest)
        self.assertEqual(self.run.prepared_entries.count(), 5)
        durable.verify_prepared(self.run)
        durable.stage(self.run, self.owner, {"movie": rows}, [], {}, append=True, operation_prefix="backfill_")
        self.persist()
        self.assertEqual(Movie.objects.count(), 6)
        self.assertEqual(list(self.run.prepared_entries.values_list("ordinal", flat=True)), list(range(6)))

    def test_backfill_and_fanout_episodes_project_watched_state(self):
        """Episodes a Completed show expands into are watched, like any import."""
        self.persist()
        tv_item, season_item, *episode_items = Item.objects.bulk_create([
            Item(media_id="show", source="tmdb", media_type="tv", title="Show"),
            Item(media_id="show", source="tmdb", media_type="season", title="Show", season_number=1),
            Item(media_id="show", source="tmdb", media_type="episode", title="One", season_number=1, episode_number=1),
            Item(media_id="show", source="tmdb", media_type="episode", title="Two", season_number=1, episode_number=2),
        ])
        tv = TV.objects.bulk_create([TV(item=tv_item, user=self.user)])[0]
        season = Season.objects.bulk_create([Season(item=season_item, user=self.user, related_tv=tv)])[0]
        for prefix, item in zip(("backfill_", "fanout_"), episode_items, strict=True):
            episode = Episode(item=item, related_season=season, status=Status.COMPLETED, end_date=timezone.now())
            durable.stage(self.run, self.owner, {"episode": [episode]}, [], {}, append=True, operation_prefix=prefix)
            self.persist()

        self.assertEqual(
            set(WatchState.objects.filter(user=self.user, watched=True).values_list("item_id", flat=True)),
            {Item.objects.get(media_id="durable").pk, *(item.pk for item in episode_items)},
        )

    def test_prepared_episode_keeps_exact_archived_parent_identity(self):
        """Hydration must not remap a prepared episode to another active order."""
        tv_item, season_item, episode_item = Item.objects.bulk_create([
            Item(media_id="show", source="tmdb", media_type="tv", title="Show"),
            Item(media_id="show", source="tmdb", media_type="season", title="Show", season_number=1),
            Item(media_id="show", source="tmdb", media_type="episode", title="Episode", season_number=1, episode_number=1),
        ])
        tv = TV.objects.bulk_create([TV(item=tv_item, user=self.user)])[0]
        season = Season.all_objects.bulk_create([Season(item=season_item, user=self.user, related_tv=tv, order_archived=True)])[0]
        episode = Episode(item=episode_item, related_season=season, status=Status.COMPLETED, end_date=timezone.now())
        durable.stage(self.run, self.owner, {"episode": [episode]}, [], {"mode": "new"})
        self.persist()
        self.assertEqual(Episode.all_objects.get().related_season_id, season.pk)
        self.assertEqual(Episode.history.count(), 1)
