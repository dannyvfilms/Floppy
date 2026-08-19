# FORK: tests for the import/export API endpoints.
import io
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch

from django.urls import reverse

from .base import FloppyApiTestCase


class ImportDispatchTests(FloppyApiTestCase):
    """POST /imports/{service}."""

    @patch("api.fork_views_integrations.tasks.import_mal.delay")
    def test_username_import_dispatch(self, mock_delay):
        """Username services queue their task with the user's id."""
        mock_delay.return_value.id = "mal-task-1"
        response = self.call_api(
            "post",
            "api_import_dispatch",
            args=("mal",),
            payload={"username": "someone", "mode": "new"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.ACCEPTED)
        self.assertEqual(response.json()["task_id"], "mal-task-1")
        kwargs = mock_delay.call_args.kwargs
        self.assertEqual(kwargs["user_id"], self.user1.id)
        self.assertEqual(kwargs["mode"], "new")

    def test_username_missing_rejected(self):
        """Missing usernames return 400."""
        response = self.call_api(
            "post",
            "api_import_dispatch",
            args=("steam",),
            payload={"mode": "new"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_invalid_mode_rejected(self):
        """Modes outside ImportModeChoices return 400."""
        response = self.call_api(
            "post",
            "api_import_dispatch",
            args=("mal",),
            payload={"username": "x", "mode": "bogus"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_unknown_service_lists_options(self):
        """Unknown services 404 with the service catalog."""
        response = self.call_api(
            "post",
            "api_import_dispatch",
            args=("nonexistent",),
            payload={},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)
        self.assertIn("yamtrack", response.json()["services"])

    @patch("api.fork_views_integrations.tasks.import_yamtrack.delay")
    def test_file_import_dispatch(self, mock_delay):
        """File services accept a multipart upload."""
        mock_delay.return_value.id = "csv-task-1"
        upload = io.BytesIO(b"media_id,source\n1,tmdb\n")
        upload.name = "backup.csv"
        response = self.client.post(
            reverse("api_import_dispatch", args=("yamtrack",)),
            {"file": upload, "mode": "new"},
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.ACCEPTED)
        self.assertEqual(response.json()["task_id"], "csv-task-1")
        self.assertIn("file", mock_delay.call_args.kwargs)

    def test_file_missing_rejected(self):
        """File services without an upload return 400."""
        response = self.call_api(
            "post",
            "api_import_dispatch",
            args=("goodreads",),
            payload={"mode": "new"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)


class ImportActivityTests(FloppyApiTestCase):
    """GET /imports/activity."""

    def test_activity_returns_results(self):
        """The activity endpoint returns a result list."""
        response = self.call_api(
            "get",
            "api_imports_activity",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertIn("results", response.json())


class ExportTests(FloppyApiTestCase):
    """GET /export/csv and /export/template."""

    def test_export_csv_streams_library(self):
        """The CSV export contains tracked titles."""
        response = self.call_api("get", "api_export_csv", headers=self.auth_headers)
        self.assertEqual(response.status_code, HTTP.OK)
        content = b"".join(response.streaming_content).decode()
        self.assertIn("Movie 1", content)

    def test_export_media_type_filter(self):
        """media_types restricts the exported rows."""
        response = self.call_api(
            "get",
            "api_export_csv",
            params={"media_types": "game", "include_lists": "0"},
            headers=self.auth_headers,
        )
        content = b"".join(response.streaming_content).decode()
        self.assertIn("Game 1", content)
        self.assertNotIn("Movie 1", content)

    def test_export_template(self):
        """The template CSV downloads."""
        response = self.call_api(
            "get",
            "api_export_template",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertIn("text/csv", response["Content-Type"])
