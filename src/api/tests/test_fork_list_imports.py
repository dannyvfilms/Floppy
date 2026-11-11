# FORK: tests for the JSON list import and CSV export endpoints.
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from integrations.models import IntegrationToken, MDBListAccount, TraktAccount
from lists.models import CustomList

from .base import FloppyApiTestCase


class ListImportApiTests(FloppyApiTestCase):
    """Imports reuse the web tasks; exports return CSV text."""

    def test_import_token_cannot_manage_provider_credentials(self):
        """Import permission cannot change the account's provider connections."""
        _, raw = IntegrationToken.generate(
            user=self.user1, name="importer", scopes=["imports:write"],
        )
        MDBListAccount.objects.create(user=self.user1, api_key="original")
        for route, body in (
            ("api_list_import_trakt", {"action": "credentials", "client_id": "other"}),
            ("api_list_import_mdblist", {"action": "disconnect"}),
            ("api_list_import_mdblist", {"action": "connect", "api_key": "other"}),
        ):
            with self.subTest(route=route, action=body["action"]):
                response = self.call_api(
                    "post", route, payload=body, headers={"HTTP_X_API_KEY": raw},
                )
                self.assertEqual(response.status_code, HTTP.FORBIDDEN)
        self.assertFalse(TraktAccount.objects.filter(user=self.user1).exists())
        self.assertEqual(MDBListAccount.objects.get(user=self.user1).api_key, "original")

    @patch("api.fork_views_list_imports.MAX_CSV_BYTES", 4)
    @patch("api.fork_views_list_imports.stage_uploaded_file")
    def test_large_multipart_csv_is_not_staged(self, stage):
        """The CSV size limit also applies to the multipart picker."""
        response = self.client.post(
            reverse("api_list_import_csv"),
            {"csv_file": SimpleUploadedFile("list.csv", b"name,id\nA,1\n")},
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        stage.assert_not_called()

    def test_status_reports_nothing_connected(self):
        """A new account has no Trakt credentials and no MDBList."""
        payload = self.call_api(
            "get",
            "api_list_import_status",
            headers=self.auth_headers,
        ).json()
        self.assertFalse(payload["trakt"]["has_credentials"])
        self.assertFalse(payload["mdblist"]["connected"])
        self.assertEqual(payload["mdblist"]["default_frequency"], "24h")
        self.assertEqual(
            payload["mdblist"]["frequency_choices"],
            [{"value": value, "label": label} for value, label in MDBListAccount.SYNC_FREQUENCY_CHOICES],
        )

    @patch("api.fork_views_list_imports.list_tasks.import_mdblist_lists_task")
    @patch("api.fork_views_list_imports._ensure_mdblist_schedule")
    @patch("api.fork_views_list_imports.mdblist_imports.validate_api_key")
    def test_mdblist_connect_saves_selected_frequency(self, validate, schedule, task):
        """The selected server-provided frequency reaches the saved schedule."""
        response = self.call_api(
            "post", "api_list_import_mdblist",
            payload={"action": "connect", "api_key": "test-key", "sync_frequency": "6h"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.ACCEPTED)
        account = MDBListAccount.objects.get(user=self.user1)
        self.assertEqual(account.sync_frequency, "6h")
        validate.assert_called_once_with("test-key")
        schedule.assert_called_once_with(self.user1, account)
        task.delay.assert_called_once_with(self.user1.id)

    @patch("api.fork_views_list_imports.enqueue_staged_task")
    @patch("api.fork_views_list_imports.stage_uploaded_file", return_value="/tmp/x.csv")  # noqa: S108
    def test_csv_text_is_staged_and_queued(self, _stage, enqueue):
        """Pasted or read CSV text queues the same task as the web upload."""
        response = self.call_api(
            "post",
            "api_list_import_csv",
            payload={"text": "name,media_id\nA,1\n"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.ACCEPTED)
        self.assertEqual(enqueue.call_args.args[1], self.user1.id)
        self.assertEqual(enqueue.call_args.args[3], "new")

    def test_csv_without_file_is_rejected(self):
        """An empty body is a 400, not a queued task."""
        response = self.call_api(
            "post",
            "api_list_import_csv",
            payload={"text": "  "},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_mdblist_import_needs_a_connected_account(self):
        """Importing by reference without an account is refused."""
        response = self.call_api(
            "post",
            "api_list_import_mdblist",
            payload={"action": "import", "list_reference": "abc"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    @patch("api.fork_views_list_imports.list_tasks.import_mdblist_list_by_reference_task")
    def test_mdblist_import_queues_task(self, task):
        """A connected account imports one list by reference."""
        MDBListAccount.objects.create(user=self.user1, api_key="x")
        response = self.call_api(
            "post",
            "api_list_import_mdblist",
            payload={"action": "import", "list_reference": "abc"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.ACCEPTED)
        task.delay.assert_called_once_with(self.user1.id, "abc")

    def test_trakt_start_needs_credentials(self):
        """Starting the device flow before saving a client id is refused."""
        response = self.call_api(
            "post",
            "api_list_import_trakt",
            payload={"action": "start"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_trakt_errors_return_the_written_message(self):
        """A Trakt refusal answers with the importer's own text."""
        from integrations.imports.helpers import MediaImportError

        self.call_api(
            "post",
            "api_list_import_trakt",
            payload={"action": "credentials", "client_id": "cid"},
            headers=self.auth_headers,
        )
        with patch(
            "api.fork_views_list_imports.trakt_imports.request_device_code",
            side_effect=MediaImportError("Could not start Trakt authorization."),
        ):
            response = self.call_api(
                "post",
                "api_list_import_trakt",
                payload={"action": "start"},
                headers=self.auth_headers,
            )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Could not start Trakt authorization.")

    @patch(
        "api.fork_views_list_imports.trakt_imports.request_device_code",
        return_value={
            "device_code": "dev",
            "user_code": "ABCD",
            "verification_url": "https://trakt.tv/activate",
            "interval": 5,
            "expires_in": 600,
        },
    )
    @patch(
        "api.fork_views_list_imports.trakt_imports.poll_device_token",
        side_effect=[None, {"access_token": "tok"}],
    )
    @patch("api.fork_views_list_imports.list_tasks.import_trakt_lists_task")
    def test_trakt_device_flow(self, task, _poll, _start):
        """Credentials, device code, pending poll, then the queued import."""
        self.call_api(
            "post",
            "api_list_import_trakt",
            payload={"action": "credentials", "client_id": "cid"},
            headers=self.auth_headers,
        )
        started = self.call_api(
            "post",
            "api_list_import_trakt",
            payload={"action": "start"},
            headers=self.auth_headers,
        ).json()
        self.assertEqual(started["user_code"], "ABCD")
        pending = self.call_api(
            "post",
            "api_list_import_trakt",
            payload={"action": "poll"},
            headers=self.auth_headers,
        )
        self.assertEqual(pending.json()["status"], "pending")
        done = self.call_api(
            "post",
            "api_list_import_trakt",
            payload={"action": "poll"},
            headers=self.auth_headers,
        )
        self.assertEqual(done.status_code, HTTP.ACCEPTED)
        task.delay.assert_called_once()

    def test_export_returns_csv_for_viewers_only(self):
        """The owner gets the CSV; another user gets a 404."""
        custom_list = CustomList.objects.create(name="Night Picks", owner=self.user1)
        owner = self.call_api(
            "get",
            "api_list_export_csv",
            args=(custom_list.id,),
            headers=self.auth_headers,
        )
        self.assertEqual(owner.status_code, HTTP.OK)
        self.assertEqual(owner.json()["filename"], "night-picks.csv")
        other = self.call_api(
            "get",
            "api_list_export_csv",
            args=(custom_list.id,),
            headers=self.auth_headers2,
        )
        self.assertEqual(other.status_code, HTTP.NOT_FOUND)
