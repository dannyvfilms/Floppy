"""Tests for the Mylar3 comic collection sync."""

import copy
from unittest.mock import MagicMock, patch

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django_celery_beat.models import PeriodicTask

from app.models import CollectionEntry, Item, MediaTypes, Sources
from integrations import tasks
from integrations.imports import helpers, mylar
from integrations.models import CollectionSourceState, MylarInstance

# Shapes copied from Mylar3's mylar/api.py: getIndex selects comics rows with
# ComicID aliased to ``id``; getComic returns {"comic", "issues", "annuals"}
# with IssueID aliased to ``id`` and Issue_Number to ``number``.
INDEX = {
    "success": True,
    "data": [
        {"id": "4050-ignored"},
        {"id": "18166", "name": "Saga", "status": "Active"},
    ],
}
SAGA = {
    "success": True,
    "data": {
        "comic": [{"id": "18166", "name": "Saga"}],
        "issues": [
            {
                "id": "301",
                "name": "Chapter One",
                "number": "1",
                "status": "Downloaded",
                "comicName": "Saga",
                "imageURL": "https://comicvine.gamespot.com/a/uploads/saga1.jpg",
            },
            {"id": "302", "number": "2", "status": "Archived", "comicName": "Saga"},
            {"id": "303", "number": "3", "status": "Wanted", "comicName": "Saga"},
            {"id": "304", "number": "4", "status": "Skipped", "comicName": "Saga"},
        ],
        "annuals": [
            {"id": "401", "number": "1", "status": "Downloaded", "comicName": "Saga"},
        ],
    },
}
EMPTY_SERIES = {"success": True, "data": {"comic": [], "issues": [], "annuals": []}}


def _response(payload, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    return response


def _fake_mylar(url, params=None, **_kwargs):
    """Answer like a Mylar3 server holding one series, Saga."""
    if params["cmd"] == "getIndex":
        return _response(INDEX)
    if params["cmd"] == "getComic":
        return _response(SAGA if params["id"] == "18166" else EMPTY_SERIES)
    return _response({"success": True, "data": {}})


class MylarImporterTests(TestCase):
    """Cover what the sync marks as owned and how it treats failures."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="mylar-user")
        self.instance = MylarInstance.objects.create(
            user=self.user,
            base_url="https://mylar.local:8090/",
            api_key=helpers.encrypt("mylar-key"),
        )

    def _owned_issue_ids(self):
        return set(
            CollectionSourceState.objects.filter(
                user=self.user, source="mylar", source_instance_id=self.instance.id
            ).values_list("item__media_id", flat=True),
        )

    @patch("integrations.imports.mylar.requests.get", side_effect=_fake_mylar)
    def test_downloaded_and_archived_issues_become_owned(self, mock_get):
        """Only issues whose file is on disk are marked as owned."""
        counts, warnings = mylar.importer(None, self.user, "new")

        self.assertEqual(self._owned_issue_ids(), {"301", "302", "401"})
        self.assertEqual(counts["updated"], 3)
        self.assertEqual(warnings, "")
        self.assertEqual(
            CollectionEntry.objects.filter(user=self.user).count(),
            3,
        )
        issue = Item.objects.get(media_id="301")
        self.assertEqual(issue.source, Sources.COMICVINE.value)
        self.assertEqual(issue.media_type, MediaTypes.COMIC_ISSUE.value)
        self.assertEqual(issue.title, "Saga #1: Chapter One")
        self.assertEqual(
            issue.image, "https://comicvine.gamespot.com/a/uploads/saga1.jpg"
        )
        self.assertEqual(Item.objects.get(media_id="401").title, "Saga Annual #1")
        first_call = mock_get.call_args_list[0]
        self.assertEqual(first_call.args[0], "https://mylar.local:8090/api")
        self.assertEqual(first_call.kwargs["params"]["apikey"], "mylar-key")
        self.instance.refresh_from_db()
        self.assertIsNotNone(self.instance.last_sync_at)

    @patch("integrations.imports.mylar.requests.get", side_effect=_fake_mylar)
    def test_second_sync_creates_no_duplicates(self, _mock_get):
        mylar.importer(None, self.user, "new")
        mylar.importer(None, self.user, "new")

        self.assertEqual(
            Item.objects.filter(media_type=MediaTypes.COMIC_ISSUE.value).count(),
            3,
        )
        self.assertEqual(CollectionSourceState.objects.count(), 3)
        self.assertEqual(CollectionEntry.objects.count(), 3)

    def test_issue_no_longer_on_disk_stops_being_owned(self):
        """An issue that goes back to Wanted drops its synced copy on the next run."""
        with patch("integrations.imports.mylar.requests.get", side_effect=_fake_mylar):
            mylar.importer(None, self.user, "new")

        def _issue_301_wanted(url, params=None, **kwargs):
            response = _fake_mylar(url, params=params, **kwargs)
            if params["cmd"] == "getComic" and params["id"] == "18166":
                data = copy.deepcopy(SAGA)
                data["data"]["issues"][0]["status"] = "Wanted"
                response.json.return_value = data
            return response

        with patch(
            "integrations.imports.mylar.requests.get", side_effect=_issue_301_wanted
        ):
            counts, _ = mylar.importer(None, self.user, "new")

        self.assertEqual(self._owned_issue_ids(), {"302", "401"})
        self.assertEqual(counts["removed"], 1)
        self.assertFalse(
            CollectionEntry.objects.filter(user=self.user, item__media_id="301").exists()
        )

    def test_failed_sync_keeps_existing_copies(self):
        """A run that stops part way must not treat unread series as removed."""
        with patch("integrations.imports.mylar.requests.get", side_effect=_fake_mylar):
            mylar.importer(None, self.user, "new")

        def _comic_fails(url, params=None, **kwargs):
            if params["cmd"] == "getComic":
                raise requests.exceptions.ReadTimeout("read timed out")
            return _fake_mylar(url, params=params, **kwargs)

        with (
            patch("integrations.imports.mylar.requests.get", side_effect=_comic_fails),
            self.assertRaises(helpers.MediaImportError),
        ):
            mylar.importer(None, self.user, "new")

        self.assertEqual(self._owned_issue_ids(), {"301", "302", "401"})

    @patch("integrations.imports.mylar.requests.get", side_effect=_fake_mylar)
    def test_existing_issue_item_is_reused(self, _mock_get):
        """An issue already in Floppy keeps its own title and row."""
        existing = Item.objects.create(
            media_id="301",
            source=Sources.COMICVINE.value,
            media_type=MediaTypes.COMIC_ISSUE.value,
            title="Saga #1 (from Comic Vine)",
            image="",
        )

        mylar.importer(None, self.user, "new")

        existing.refresh_from_db()
        self.assertEqual(existing.title, "Saga #1 (from Comic Vine)")
        self.assertEqual(Item.objects.filter(media_id="301").count(), 1)
        self.assertTrue(
            CollectionSourceState.objects.filter(item=existing, source="mylar").exists()
        )

    @patch("integrations.imports.mylar.requests.get")
    def test_rejected_key_in_ok_response_marks_connection_broken(self, mock_get):
        """Mylar3 reports a wrong key as HTTP 200 with success false."""
        mock_get.return_value = _response(
            {"success": False, "error": {"code": 400, "message": "Incorrect API key"}}
        )

        with self.assertRaises(helpers.ConnectionAuthError):
            mylar.importer(None, self.user, "new")

        self.instance.refresh_from_db()
        self.assertTrue(self.instance.connection_broken)

    @patch("integrations.imports.mylar.requests.get")
    def test_other_mylar_error_does_not_mark_connection_broken(self, mock_get):
        mock_get.return_value = _response(
            {"success": False, "error": {"code": 400, "message": "Missing parameter: id"}}
        )

        with self.assertRaises(helpers.MediaImportError) as cm:
            mylar.importer(None, self.user, "new")

        self.assertNotIsInstance(cm.exception, helpers.ConnectionAuthError)
        self.instance.refresh_from_db()
        self.assertFalse(self.instance.connection_broken)

    @patch("integrations.imports.mylar.requests.get")
    def test_timeout_is_recorded_without_leaking_the_key(self, mock_get):
        """The key is in the query string, so the error text must not repeat it."""
        mock_get.side_effect = requests.exceptions.ConnectTimeout(
            "Max retries exceeded with url: /api?apikey=mylar-key&cmd=getIndex"
        )

        with self.assertRaises(helpers.MediaImportError) as cm:
            mylar.importer(None, self.user, "new")

        self.instance.refresh_from_db()
        self.assertFalse(self.instance.connection_broken)
        self.assertIn("Could not reach Mylar3", self.instance.last_error_message)
        self.assertNotIn("mylar-key", self.instance.last_error_message)
        self.assertNotIn("mylar-key", str(cm.exception))

    @patch("integrations.tasks._media_imports.import_media")
    def test_task_returns_failure_message_for_expected_errors(self, mock_import):
        mock_import.side_effect = helpers.MediaImportError("Could not reach Mylar3")

        result = tasks.import_mylar(user_id=self.user.id)

        self.assertEqual(result, "Mylar3 import failed: Could not reach Mylar3")


class MylarViewTests(TestCase):
    """Cover connecting, syncing and disconnecting a Mylar3 server."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="mylar-viewer")
        self.client.force_login(self.user)

    @patch("integrations.views.tasks.import_mylar.delay")
    @patch("integrations.views.MylarClient.healthcheck")
    def test_connect_creates_schedule_and_queues_initial_import(
        self, mock_healthcheck, mock_delay
    ):
        response = self.client.post(
            reverse("mylar_connect"),
            {"base_url": "https://mylar.local:8090", "api_key": "mylar-key"},
        )

        self.assertEqual(response.status_code, 302)
        instance = MylarInstance.objects.get(user=self.user)
        self.assertEqual(helpers.decrypt(instance.api_key), "mylar-key")
        task = PeriodicTask.objects.get(task="Import from Mylar3 (Recurring)")
        self.assertTrue(task.enabled)
        self.assertIn(f'"instance_id": {instance.id}', task.kwargs)
        mock_healthcheck.assert_called_once()
        mock_delay.assert_called_once_with(
            user_id=self.user.id, mode="new", instance_id=instance.id
        )

    @patch("integrations.views.tasks.import_mylar.delay")
    @patch("integrations.imports.mylar.requests.get")
    def test_connect_with_bad_key_saves_nothing(self, mock_get, mock_delay):
        mock_get.return_value = _response(
            {"success": False, "error": {"code": 400, "message": "Incorrect API key"}}
        )

        self.client.post(
            reverse("mylar_connect"),
            {"base_url": "https://mylar.local:8090", "api_key": "wrong"},
        )

        self.assertFalse(MylarInstance.objects.exists())
        self.assertFalse(
            PeriodicTask.objects.filter(task="Import from Mylar3 (Recurring)").exists()
        )
        mock_delay.assert_not_called()

    @patch("integrations.views.tasks.import_mylar.delay")
    @patch("integrations.views.MylarClient.healthcheck")
    def test_disconnect_removes_schedule_and_ownership_rows(
        self, _mock_healthcheck, _mock_delay
    ):
        self.client.post(
            reverse("mylar_connect"),
            {"base_url": "https://mylar.local:8090", "api_key": "mylar-key"},
        )
        instance = MylarInstance.objects.get(user=self.user)
        item = Item.objects.create(
            media_id="301",
            source=Sources.COMICVINE.value,
            media_type=MediaTypes.COMIC_ISSUE.value,
            title="Saga #1",
        )
        CollectionSourceState.objects.create(
            user=self.user, item=item, source="mylar", source_instance_id=instance.id
        )

        CollectionEntry.objects.create(user=self.user, item=item)

        self.client.post(reverse("mylar_disconnect"), {"instance_id": instance.id})

        self.assertFalse(CollectionEntry.objects.filter(item=item).exists())
        self.assertFalse(MylarInstance.objects.exists())
        self.assertFalse(
            PeriodicTask.objects.filter(task="Import from Mylar3 (Recurring)").exists()
        )
        self.assertFalse(CollectionSourceState.objects.filter(source="mylar").exists())

    def test_disconnect_scoped_to_owner(self):
        other = get_user_model().objects.create_user(username="someone-else")
        other_instance = MylarInstance.objects.create(
            user=other,
            base_url="https://mylar.local:8090",
            api_key=helpers.encrypt("key"),
        )

        response = self.client.post(
            reverse("mylar_disconnect"), {"instance_id": other_instance.id}
        )

        self.assertEqual(response.status_code, 404)
        self.assertTrue(MylarInstance.objects.filter(pk=other_instance.id).exists())

    def test_import_page_shows_mylar(self):
        response = self.client.get(reverse("import_data"))

        self.assertContains(response, "Import owned comics from Mylar3.")
        self.assertContains(response, reverse("mylar_connect"))
