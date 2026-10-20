from datetime import timedelta
from unittest.mock import patch

from celery.exceptions import SoftTimeLimitExceeded
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from app import backfill_queue
from app.models import Item, MediaTypes, Movie, Sources, Status
from app.tasks import cleanup_task_results
from integrations.imports import helpers
from integrations.models import ImportRun
from integrations.tasks._import_helpers import close_abandoned_import_runs
from integrations.tasks._media_imports import import_media


def _fake_trakt_importer(identifier, user, mode, username=None):
    """Stand in for a real importer: stages one Movie via bulk_create_media."""
    item = Item.objects.create(
        media_id="prov-movie",
        source=Sources.TMDB.value,
        media_type=MediaTypes.MOVIE.value,
        title="Provenance Movie",
    )
    movie = Movie(item=item, user=user, status=Status.COMPLETED.value)
    helpers.bulk_create_media({MediaTypes.MOVIE.value: [movie]}, user)
    return {MediaTypes.MOVIE.value: 1}, []


# Give the stub the same module identity import_media derives "source" from,
# without actually living in integrations.imports.trakt.
_fake_trakt_importer.__module__ = "integrations.imports.trakt"


def _fake_failing_importer(identifier, user, mode, username=None):
    msg = "boom"
    raise helpers.MediaImportError(msg)


class ImportRunProvenanceTests(TestCase):
    """Tests for ImportRun creation and row tagging in import_media()."""

    def setUp(self):
        """Set up a test user."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

    def test_import_media_creates_completed_run_and_tags_rows(self):
        """A successful import creates an ImportRun and tags the rows it made."""
        import_media(_fake_trakt_importer, None, self.user.id, "new")

        run = ImportRun.objects.get(user=self.user)
        self.assertEqual(run.source, "trakt")
        self.assertEqual(run.status, ImportRun.Status.COMPLETED)
        self.assertEqual(run.created_count, 1)
        self.assertIsNotNone(run.finished_at)

        movie = Movie.objects.get(user=self.user)
        self.assertEqual(movie.import_run_id, run.id)

    def test_import_media_marks_run_failed_on_exception(self):
        """A raised MediaImportError still finalizes the run as failed."""
        with self.assertRaises(helpers.MediaImportError):
            import_media(_fake_failing_importer, None, self.user.id, "new")

        run = ImportRun.objects.get(user=self.user)
        self.assertEqual(run.status, ImportRun.Status.FAILED)
        self.assertIsNotNone(run.finished_at)

    @override_settings(TESTING=False)
    @patch("app.tasks_genre.populate_genre_backfill_queue.apply_async")
    @patch("app.tasks_credits.populate_credits_backfill_queue.apply_async")
    @patch("app.tasks_runtime.populate_runtime_backfill_queue.apply_async")
    def test_import_boundary_defers_production_enrichment_and_cleans_up_on_failure(
        self, runtime_drain, credits_drain, genre_drain
    ):
        from app.tasks_credits import (
            CREDITS_BACKFILL_ITEMS_QUEUE_KEY,
            CREDITS_BACKFILL_ITEMS_SCHEDULED_KEY,
        )
        from app.tasks_genre import (
            GENRE_BACKFILL_ITEMS_QUEUE_KEY,
            GENRE_BACKFILL_ITEMS_SCHEDULED_KEY,
        )
        from app.tasks_runtime import (
            RUNTIME_BACKFILL_ITEMS_QUEUE_KEY,
            RUNTIME_BACKFILL_ITEMS_SCHEDULED_KEY,
        )

        queue_pairs = (
            (RUNTIME_BACKFILL_ITEMS_QUEUE_KEY, RUNTIME_BACKFILL_ITEMS_SCHEDULED_KEY),
            (GENRE_BACKFILL_ITEMS_QUEUE_KEY, GENRE_BACKFILL_ITEMS_SCHEDULED_KEY),
            (CREDITS_BACKFILL_ITEMS_QUEUE_KEY, CREDITS_BACKFILL_ITEMS_SCHEDULED_KEY),
        )
        drains = (runtime_drain, credits_drain, genre_drain)
        for pair in queue_pairs:
            self.addCleanup(backfill_queue.clear, *pair)
        for fail in (False, True):
            with self.subTest(fail=fail):
                for pair in queue_pairs:
                    backfill_queue.clear(*pair)
                for drain in drains:
                    drain.reset_mock()

                def importer(*args, fail=fail):
                    with self.captureOnCommitCallbacks(execute=True):
                        item = Item.objects.create(
                            media_id=f"boundary-{fail}",
                            source=Sources.TMDB.value,
                            media_type=MediaTypes.TV.value,
                            title="Import boundary show",
                        )
                    for queue_key, _ in queue_pairs:
                        self.assertEqual(backfill_queue.members(queue_key), {item.pk})
                    for drain in drains:
                        drain.assert_not_called()
                    if fail:
                        raise helpers.MediaImportError("failed after Item creation")
                    return {"created": 0}, []

                if fail:
                    with self.assertRaisesMessage(
                        helpers.MediaImportError, "failed after Item creation"
                    ):
                        import_media(importer, None, self.user.id, "new")
                else:
                    import_media(importer, None, self.user.id, "new")
                for drain in drains:
                    drain.assert_called_once_with(countdown=10, kwargs={})
                run = ImportRun.objects.filter(user=self.user).latest("id")
                self.assertEqual(
                    run.status,
                    ImportRun.Status.FAILED if fail else ImportRun.Status.COMPLETED,
                )
                self.assertIsNotNone(run.finished_at)
                self.assertIsNone(backfill_queue._deferred_drains.get())

    @patch("app.statistics_cache.invalidate_all_statistics_days")
    @patch("app.history_cache.invalidate_history_cache")
    @patch("events.tasks.reload_calendar.delay")
    def test_unchanged_import_preserves_caches(self, calendar, invalidate, refresh):
        def importer(*args):
            # Older importers report per-media counts and may only return a
            # skipped metric when every source row already exists.
            return {
                "skipped": 12,
                "failed": 2,
                "rejected": 3,
                "skipped_ignored": 1,
                "skipped_numbering_mismatch": 1,
            }, []

        import_media(importer, None, self.user.id, "new")
        calendar.assert_not_called()
        invalidate.assert_not_called()
        refresh.assert_not_called()
        run = ImportRun.objects.get(user=self.user)
        self.assertEqual(run.status, ImportRun.Status.COMPLETED)
        self.assertEqual(run.skipped_count, 12)
        self.assertEqual(run.failed_count, 2)

    @patch("app.statistics_cache.invalidate_all_statistics_days")
    @patch("app.history_cache.invalidate_history_cache")
    @patch("events.tasks.reload_calendar.delay")
    def test_updated_import_refreshes_caches(self, calendar, invalidate, refresh):
        def importer(*args):
            return {"created": 0, "updated": 1, "skipped": 12}, []

        import_media(importer, None, self.user.id, "overwrite")
        calendar.assert_called_once_with()
        invalidate.assert_called_once_with(self.user.id, force=True)
        refresh.assert_called_once_with(self.user.id, reason="media_import")

    def test_bulk_create_media_leaves_import_run_null_outside_tracking(self):
        """Calling bulk_create_media directly (no import_media wrapper) tags nothing."""
        item = Item.objects.create(
            media_id="prov-movie-2",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Untracked Movie",
        )
        movie = Movie(item=item, user=self.user, status=Status.COMPLETED.value)
        helpers.bulk_create_media({MediaTypes.MOVIE.value: [movie]}, self.user)

        row = Movie.objects.get(item=item, user=self.user)
        self.assertIsNone(row.import_run_id)


def _importer_cancelled_mid_run(identifier, user, mode, username=None):
    """A user cancel marks the run CANCELLED, then the task is terminated."""
    ImportRun.objects.filter(user=user).update(status=ImportRun.Status.CANCELLED)
    raise SystemExit


class ImportRunTerminalRecordTests(TestCase):
    """An import always leaves a terminal record, even when it is cut short."""

    def setUp(self):
        """Set up a test user."""
        self.user = get_user_model().objects.create_user(
            username="test",
            password="12345",
        )

    def test_a_soft_time_limit_leaves_a_failed_run(self):
        def importer(identifier, user, mode, username=None):
            raise SoftTimeLimitExceeded

        with self.assertRaises(SoftTimeLimitExceeded):
            import_media(importer, None, self.user.id, "new")

        run = ImportRun.objects.get(user=self.user)
        self.assertEqual(run.status, ImportRun.Status.FAILED)
        self.assertIsNotNone(run.finished_at)

    def test_a_worker_shutdown_leaves_a_failed_run(self):
        def importer(identifier, user, mode, username=None):
            raise SystemExit

        with self.assertRaises(SystemExit):
            import_media(importer, None, self.user.id, "new")

        self.assertEqual(
            ImportRun.objects.get(user=self.user).status,
            ImportRun.Status.FAILED,
        )

    def test_a_cancelled_run_stays_cancelled_when_its_task_is_terminated(self):
        with self.assertRaises(SystemExit):
            import_media(_importer_cancelled_mid_run, None, self.user.id, "new")

        self.assertEqual(
            ImportRun.objects.get(user=self.user).status,
            ImportRun.Status.CANCELLED,
        )


@override_settings(CELERY_TASK_TIME_LIMIT=1800)
class CloseAbandonedImportRunsTests(TestCase):
    """A run whose task was killed is closed once it cannot still be alive."""

    def setUp(self):
        """Set up a test user."""
        self.user = get_user_model().objects.create_user(
            username="test",
            password="12345",
        )

    def _run(self, source="trakt_export", age=timedelta(hours=1), **fields):
        run = ImportRun.objects.create(user=self.user, source=source, **fields)
        ImportRun.objects.filter(pk=run.pk).update(
            started_at=timezone.now() - age,
        )
        return run

    def test_a_run_past_the_time_limit_is_marked_failed(self):
        stale = self._run()

        self.assertEqual(close_abandoned_import_runs(), 1)

        stale.refresh_from_db()
        self.assertEqual(stale.status, ImportRun.Status.FAILED)
        self.assertIsNotNone(stale.finished_at)

    def test_a_run_inside_the_time_limit_is_left_alone(self):
        running = self._run(age=timedelta(minutes=20))

        self.assertEqual(close_abandoned_import_runs(), 0)

        running.refresh_from_db()
        self.assertEqual(running.status, ImportRun.Status.RUNNING)

    def test_self_rescheduling_backfills_are_left_alone(self):
        runs = [self._run(source=source) for source in ("lastfm", "koito")]

        self.assertEqual(close_abandoned_import_runs(), 0)

        for run in runs:
            run.refresh_from_db()
            self.assertEqual(run.status, ImportRun.Status.RUNNING)

    def test_finished_runs_keep_their_status(self):
        done = self._run(status=ImportRun.Status.COMPLETED)

        self.assertEqual(close_abandoned_import_runs(), 0)

        done.refresh_from_db()
        self.assertEqual(done.status, ImportRun.Status.COMPLETED)

    @override_settings(CELERY_TASK_TIME_LIMIT=60)
    def test_a_lowered_global_limit_does_not_close_a_live_stremio_import(self):
        stremio = self._run(source="stremio", age=timedelta(minutes=20))
        stale = self._run(source="stremio", age=timedelta(minutes=40))

        self.assertEqual(close_abandoned_import_runs(), 1)

        stremio.refresh_from_db()
        stale.refresh_from_db()
        self.assertEqual(stremio.status, ImportRun.Status.RUNNING)
        self.assertEqual(stale.status, ImportRun.Status.FAILED)

    @override_settings(CELERY_TASK_TIME_LIMIT=0)
    def test_nothing_is_closed_when_tasks_have_no_time_limit(self):
        self._run(age=timedelta(days=2))

        self.assertEqual(close_abandoned_import_runs(), 0)

    def test_cleanup_task_results_closes_them_too(self):
        stale = self._run()

        cleanup_task_results.run(batch_size=10)

        stale.refresh_from_db()
        self.assertEqual(stale.status, ImportRun.Status.FAILED)
