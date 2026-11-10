# FORK: tests for the import/export API endpoints.
import io
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch

from django.urls import reverse
from kombu.exceptions import OperationalError as KombuOperationalError

from integrations.models import ImportRun, IntegrationToken
from integrations.upload_staging import discard_staged_upload

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

    @patch("api.fork_views_integrations.tasks.import_mal.delay")
    def test_unreachable_broker_is_a_503_naming_redis(self, mock_delay):
        """#1263. A dead broker was an unhandled 500 on username imports."""
        mock_delay.side_effect = KombuOperationalError(
            "Error -2 connecting to redis:6379. Name does not resolve."
        )
        with self.assertLogs("api.fork_views_integrations", level="ERROR"):
            response = self.call_api(
                "post",
                "api_import_dispatch",
                args=("mal",),
                payload={"username": "someone", "mode": "new"},
                headers=self.auth_headers,
            )

        self.assertEqual(response.status_code, HTTP.SERVICE_UNAVAILABLE)
        self.assertIn("cannot reach Redis", response.json()["detail"])

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
        queued = mock_delay.call_args.kwargs["file"]
        self.addCleanup(discard_staged_upload, queued)
        self.assertTrue(queued.endswith(".csv"))

    @patch("api.fork_views_integrations.tasks.import_youtube_takeout.delay")
    def test_youtube_takeout_dispatch(self, mock_delay):
        """The YouTube Takeout history takes a JSON upload."""
        mock_delay.return_value.id = "yt-task-1"
        upload = io.BytesIO(b"[]")
        upload.name = "watch-history.json"
        response = self.client.post(
            reverse("api_import_dispatch", args=("youtube-takeout",)),
            {"file": upload, "mode": "new"},
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.ACCEPTED)
        self.assertEqual(response.json()["task_id"], "yt-task-1")
        self.addCleanup(discard_staged_upload, mock_delay.call_args.kwargs["file"])

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

    def test_activity_contains_owned_runs_and_tracker_sections(self):
        run = ImportRun.objects.create(user=self.user1, source="goodreads", status="completed", created_count=3)
        ImportRun.objects.create(user=self.user2, source="anilist", status="completed", created_count=99)
        response = self.call_api("get", "api_imports_activity", headers=self.auth_headers)
        self.assertEqual(response.status_code, HTTP.OK, response.content)
        body = response.json()
        self.assertEqual([row["id"] for row in body["presentation"]["runs"]], [run.id])
        self.assertEqual(body["presentation"]["runs"][0]["created"], 3)
        self.assertEqual(body["presentation"]["runs"][0]["sourceLabel"], "Goodreads")
        self.assertFalse(body["tracker_activity"]["mal"]["connected"])
        self.assertEqual([row["slug"] for row in body["tracker_activity"]["services"]], ["tmdb", "wetrakr"])

    def test_scoped_import_reader_does_not_gain_tracker_access_or_writes(self):
        _token, raw = IntegrationToken.generate(user=self.user1, name="reader", scopes=["imports:read", "imports:write"])
        headers = {"HTTP_AUTHORIZATION": f"Bearer {raw}"}
        body = self.call_api("get", "api_imports_activity", headers=headers).json()
        self.assertNotIn("tracker_activity", body)
        response = self.call_api("post", "api_imports_activity", headers=headers,
                                 payload={"path": reverse("mal_mapping_ignore"), "values": {"item_id": 1}})
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_activity_action_rejects_arbitrary_paths(self):
        for path in ("https://example.test", "//example.test", reverse("home"), "/missing", reverse("mal_mapping_ignore") + "?x=1"):
            with self.subTest(path=path):
                response = self.call_api("post", "api_imports_activity", headers=self.auth_headers, payload={"path": path})
                self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_run_action_keeps_ownership_and_returns_handler_validation(self):
        other = ImportRun.objects.create(user=self.user2, source="goodreads", status="completed")
        response = self.call_api("post", "api_imports_activity", headers=self.auth_headers,
                                 payload={"path": reverse("rollback_import_run", args=[other.id]), "values": {}})
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)
        self.assertTrue(ImportRun.objects.filter(pk=other.pk).exists())
        invalid = self.call_api("post", "api_imports_activity", headers=self.auth_headers,
                               payload={"path": reverse("mal_mapping_ignore"), "values": {"item_id": "bad"}})
        self.assertEqual(invalid.status_code, HTTP.BAD_REQUEST)
        self.assertEqual(invalid.json()["detail"], "Choose a valid anime.")

    def test_mapping_search_uses_the_existing_get_handler(self):
        response = self.call_api("post", "api_imports_activity", headers=self.auth_headers,
                                 payload={"path": reverse("mal_mapping_search"), "values": {"q": "ab"}})
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Enter at least three characters.")


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
