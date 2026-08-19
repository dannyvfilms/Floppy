from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from integrations.models import ImportRun


class CancelImportRunTests(TestCase):
    """Tests for the cancel_import_run view."""

    def setUp(self):
        """Create user and test data for the tests."""
        self.credentials = {"username": "testuser", "password": "testpass123"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        self.other_credentials = {"username": "otheruser", "password": "testpass123"}
        self.other_user = get_user_model().objects.create_user(**self.other_credentials)

    @patch("config.celery.app.control.revoke")
    def test_cancel_revokes_task_and_marks_run_cancelled(self, mock_revoke):
        """Cancelling a running import revokes its task and updates status."""
        run = ImportRun.objects.create(
            user=self.user,
            source="trakt",
            status=ImportRun.Status.RUNNING,
            task_id="abc-123",
        )

        response = self.client.post(
            reverse("cancel_import_run", args=[run.id]),
        )

        self.assertRedirects(response, reverse("import_data"))
        mock_revoke.assert_called_once_with("abc-123", terminate=True)

        run.refresh_from_db()
        self.assertEqual(run.status, ImportRun.Status.CANCELLED)
        self.assertTrue(run.cancel_requested)
        self.assertIsNotNone(run.finished_at)

        messages = list(get_messages(response.wsgi_request))
        self.assertIn("Import cancelled", str(messages[0]))

    @patch("config.celery.app.control.revoke")
    def test_cancel_refuses_when_not_running(self, mock_revoke):
        """A non-running import cannot be cancelled."""
        run = ImportRun.objects.create(
            user=self.user,
            source="trakt",
            status=ImportRun.Status.COMPLETED,
            task_id="abc-123",
        )

        response = self.client.post(
            reverse("cancel_import_run", args=[run.id]),
        )

        self.assertRedirects(response, reverse("import_data"))
        mock_revoke.assert_not_called()
        run.refresh_from_db()
        self.assertEqual(run.status, ImportRun.Status.COMPLETED)

        messages = list(get_messages(response.wsgi_request))
        self.assertIn("not running", str(messages[0]))

    @patch("config.celery.app.control.revoke")
    def test_cancel_is_scoped_to_the_requesting_user(self, mock_revoke):
        """A user cannot cancel another user's import run."""
        run = ImportRun.objects.create(
            user=self.other_user,
            source="trakt",
            status=ImportRun.Status.RUNNING,
            task_id="abc-123",
        )

        response = self.client.post(
            reverse("cancel_import_run", args=[run.id]),
        )

        self.assertEqual(response.status_code, 404)
        mock_revoke.assert_not_called()
        run.refresh_from_db()
        self.assertEqual(run.status, ImportRun.Status.RUNNING)
