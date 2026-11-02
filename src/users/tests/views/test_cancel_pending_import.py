from unittest.mock import MagicMock, patch

from celery import Task
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django_celery_results.models import TaskResult

import integrations.tasks
from config.celery import FloppyTask, app
from integrations import koito_sync
from integrations.models import (
    ImportRun,
    KoitoAccount,
    LastFMAccount,
    LastFMHistoryImportStatus,
)


@patch("users.models.AsyncResult")
class CancelPendingImportTests(TestCase):
    """Tests for the cancel_pending_import view."""

    def setUp(self):
        """Create two users and log the first one in."""
        self.credentials = {"username": "testuser", "password": "testpass123"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)
        self.other_user = get_user_model().objects.create_user(
            username="otheruser",
            password="testpass123",
        )

    def _queue(self, user, task_id="queued-1", name="Import from Trakt"):
        return TaskResult.objects.create(
            task_id=task_id,
            task_name=name,
            task_kwargs=f'{{"user_id": {user.id}}}',
            status="PENDING",
        )

    def _backend_status(self, mock_async_result, status="PENDING"):
        mock_async_result.return_value = MagicMock(
            status=status,
            result=None,
            traceback=None,
            date_done=None,
        )

    def _post(self, task_id):
        return self.client.post(reverse("cancel_pending_import", args=[task_id]))

    @patch("config.celery.app.control.revoke")
    def test_cancel_revokes_queued_task_without_terminating(
        self, mock_revoke, mock_async_result
    ):
        """A queued import is revoked (not terminated) and marked REVOKED."""
        self._backend_status(mock_async_result)
        row = self._queue(self.user)

        response = self._post("queued-1")

        self.assertRedirects(response, reverse("import_data"), fetch_redirect_response=False)
        mock_revoke.assert_called_once_with("queued-1", terminate=False)
        row.refresh_from_db()
        self.assertEqual(row.status, "REVOKED")
        self.assertIsNotNone(row.date_done)
        messages = list(get_messages(response.wsgi_request))
        self.assertIn("Import cancelled", str(messages[0]))

    @patch("config.celery.app.control.revoke")
    def test_cancel_ignores_another_users_task(self, mock_revoke, mock_async_result):
        """A user cannot cancel a queued import that belongs to someone else."""
        self._backend_status(mock_async_result)
        row = self._queue(self.other_user)

        response = self._post("queued-1")

        self.assertRedirects(response, reverse("import_data"), fetch_redirect_response=False)
        mock_revoke.assert_not_called()
        row.refresh_from_db()
        self.assertEqual(row.status, "PENDING")

    @patch("config.celery.app.control.revoke")
    def test_cancel_refuses_task_that_already_started(
        self, mock_revoke, mock_async_result
    ):
        """A task the backend reports as started is left to the running-import cancel."""
        self._backend_status(mock_async_result, status="STARTED")
        row = self._queue(self.user)

        response = self._post("queued-1")

        mock_revoke.assert_not_called()
        row.refresh_from_db()
        self.assertEqual(row.status, "STARTED")
        messages = list(get_messages(response.wsgi_request))
        self.assertIn("no longer queued", str(messages[0]))

    @patch("celery.result.AsyncResult")
    @patch("config.celery.app.control.revoke")
    def test_cancel_terminates_task_that_started_during_the_click(
        self, mock_revoke, mock_backend, mock_async_result
    ):
        """A worker that started after the page loaded is stopped like a running import."""
        self._backend_status(mock_async_result)
        mock_backend.return_value = MagicMock(status="STARTED")
        self._queue(self.user)
        run = ImportRun.objects.create(
            user=self.user,
            source="trakt",
            status=ImportRun.Status.RUNNING,
            task_id="queued-1",
        )

        self._post("queued-1")

        mock_revoke.assert_called_once_with("queued-1", terminate=True)
        run.refresh_from_db()
        self.assertEqual(run.status, ImportRun.Status.CANCELLED)

    @patch("config.celery.app.control.revoke")
    def test_cancel_resets_queued_lastfm_history_status(
        self, mock_revoke, mock_async_result
    ):
        """Cancelling a queued Last.fm backfill frees the account to start again."""
        self._backend_status(mock_async_result)
        account = LastFMAccount.objects.create(
            user=self.user,
            lastfm_username="listener",
            history_import_status=LastFMHistoryImportStatus.QUEUED,
        )
        run = ImportRun.objects.create(
            user=self.user,
            source="lastfm",
            status=ImportRun.Status.RUNNING,
            task_id="earlier-chunk",
        )
        self._queue(self.user, name="Import from Last.fm History")

        self._post("queued-1")

        run.refresh_from_db()
        self.assertEqual(run.status, ImportRun.Status.CANCELLED)
        self.assertTrue(run.cancel_requested)
        self.assertIsNotNone(run.finished_at)
        account.refresh_from_db()
        self.assertEqual(account.history_import_status, LastFMHistoryImportStatus.FAILED)
        self.assertTrue(account.history_import_can_start)
        self.assertEqual(account.history_import_last_error_message, "Cancelled by user.")

    @patch("config.celery.app.control.revoke")
    def test_cancel_running_koito_import_resets_status_and_lock(
        self, mock_revoke, mock_async_result
    ):
        """Cancelling a running Koito backfill clears the status and its lock."""
        account = KoitoAccount.objects.create(
            user=self.user,
            base_url="https://koito.example",
            api_key="x",
            history_import_status=LastFMHistoryImportStatus.RUNNING,
        )
        lock_key = koito_sync.get_koito_history_import_lock_key(self.user.id)
        cache.set(lock_key, {"started_at": "2026-01-01T00:00:00+00:00"})
        run = ImportRun.objects.create(
            user=self.user,
            source="koito",
            status=ImportRun.Status.RUNNING,
            task_id="running-1",
        )

        self.client.post(reverse("cancel_import_run", args=[run.id]))

        account.refresh_from_db()
        self.assertEqual(account.history_import_status, LastFMHistoryImportStatus.FAILED)
        self.assertIsNone(cache.get(lock_key))

    def test_activity_shows_cancel_button_only_on_pending_rows(self, mock_async_result):
        """The history panel offers Cancel for queued imports and not finished ones."""
        self._backend_status(mock_async_result)
        self._queue(self.user, task_id="queued-1")
        TaskResult.objects.create(
            task_id="done-1",
            task_name="Import from Trakt",
            task_kwargs=f'{{"user_id": {self.user.id}}}',
            status="SUCCESS",
            result='"Imported 1 movie."',
        )

        response = self.client.get(reverse("import_data_activity"))

        self.assertContains(response, reverse("cancel_pending_import", args=["queued-1"]))
        self.assertNotContains(response, reverse("cancel_pending_import", args=["done-1"]))


class FloppyTaskCancelGuardTests(TestCase):
    """A task cancelled while queued must not run, whichever importer it is."""

    def setUp(self):
        """Create a user and make sure the app has loaded its task modules."""
        app.loader.import_default_modules()
        self.user = get_user_model().objects.create_user(
            username="guarduser",
            password="testpass123",
        )

    def _apply(self, task_name, status):
        TaskResult.objects.create(
            task_id="guard-1",
            task_name=task_name,
            task_kwargs=f'{{"user_id": {self.user.id}}}',
            status=status,
        )
        with patch.object(Task, "__call__", return_value="ran") as run:
            return run, app.tasks[task_name].apply(task_id="guard-1")

    def test_revoked_task_is_ignored_for_every_kind_of_import(self):
        """The task body never runs and its row stays REVOKED, not SUCCESS."""
        for name in (
            "Import from Trakt",
            "Import from Last.fm History",
            "Import from Koito History",
            "Sync Plex Watchlist",
        ):
            with self.subTest(task=name):
                TaskResult.objects.all().delete()
                self.assertIsInstance(app.tasks[name], FloppyTask)

                run, result = self._apply(name, "REVOKED")

                run.assert_not_called()
                self.assertEqual(result.state, "IGNORED")
                self.assertEqual(TaskResult.objects.get().status, "REVOKED")

    def test_pending_task_still_runs(self):
        """An ordinary queued task is unaffected by the guard."""
        run, result = self._apply("Import from Trakt", "PENDING")

        run.assert_called_once()
        self.assertEqual(result.state, "SUCCESS")
