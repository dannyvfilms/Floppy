"""Tests for the Kapowarr comic collection sync."""

import copy
from unittest.mock import MagicMock, patch

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django_celery_beat.models import PeriodicTask

from app.models import CollectionEntry, Item, MediaTypes, Sources
from integrations import tasks
from integrations.imports import helpers, kapowarr
from integrations.models import CollectionSourceState, KapowarrInstance

# Shapes copied from Kapowarr's frontend/api.py (every answer is
# {"error", "result"}), Library.get_public_volumes (volume rows with
# ``issues_downloaded``) and IssueData in backend/base/definitions.py.
VOLUMES = {
    "error": None,
    "result": [
        {"id": 1, "comicvine_id": 18166, "title": "Saga", "issues_downloaded": 2},
        {"id": 2, "comicvine_id": 99, "title": "Nothing Yet", "issues_downloaded": 0},
    ],
}
SAGA = {
    "error": None,
    "result": {
        "id": 1,
        "comicvine_id": 18166,
        "title": "Saga",
        "issues": [
            {
                "id": 11,
                "comicvine_id": 301,
                "issue_number": "1",
                "title": "Chapter One",
                "monitored": True,
                "files": [{"id": 5, "filepath": "/comics/Saga/Saga 001.cbz"}],
            },
            {
                "id": 12,
                "comicvine_id": 302,
                "issue_number": "2",
                "title": None,
                "monitored": True,
                "files": [{"id": 6, "filepath": "/comics/Saga/Saga 002.cbz"}],
            },
            {
                "id": 13,
                "comicvine_id": 303,
                "issue_number": "3",
                "title": None,
                "monitored": True,
                "files": [],
            },
        ],
    },
}


def _response(payload, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    return response


def _fake_kapowarr(url, params=None, timeout=None, allow_redirects=False):
    """Answer like a Kapowarr server holding one series, Saga."""
    if url.endswith("/api/volumes"):
        return _response(VOLUMES)
    if url.endswith("/api/volumes/1"):
        return _response(SAGA)
    return _response({"error": None, "result": {}})


class KapowarrImporterTests(TestCase):
    """Cover what the sync marks as owned and how it treats failures."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="kapowarr-user")
        self.instance = KapowarrInstance.objects.create(
            user=self.user,
            base_url="https://kapowarr.local:5656/",
            api_key=helpers.encrypt("kapowarr-key"),
        )

    def _owned_issue_ids(self):
        return set(
            CollectionSourceState.objects.filter(
                user=self.user, source="kapowarr", source_instance_id=self.instance.id
            ).values_list("item__media_id", flat=True),
        )

    @patch("integrations.imports.kapowarr.requests.get", side_effect=_fake_kapowarr)
    def test_issues_with_files_become_owned(self, mock_get):
        """Only issues Kapowarr has a file for are marked as owned."""
        counts, warnings = kapowarr.importer(None, self.user, "new")

        self.assertEqual(self._owned_issue_ids(), {"301", "302"})
        self.assertEqual(counts["updated"], 2)
        self.assertEqual(warnings, "")
        self.assertEqual(CollectionEntry.objects.filter(user=self.user).count(), 2)
        issue = Item.objects.get(media_id="301")
        self.assertEqual(issue.source, Sources.COMICVINE.value)
        self.assertEqual(issue.media_type, MediaTypes.COMIC_ISSUE.value)
        self.assertEqual(issue.title, "Saga #1: Chapter One")
        self.assertEqual(Item.objects.get(media_id="302").title, "Saga #2")
        first_call = mock_get.call_args_list[0]
        self.assertEqual(first_call.args[0], "https://kapowarr.local:5656/api/volumes")
        self.assertEqual(first_call.kwargs["params"]["api_key"], "kapowarr-key")
        # The empty volume is skipped from the list, without a detail request.
        requested = [call.args[0] for call in mock_get.call_args_list]
        self.assertNotIn("https://kapowarr.local:5656/api/volumes/2", requested)
        self.instance.refresh_from_db()
        self.assertIsNotNone(self.instance.last_sync_at)

    @patch("integrations.imports.kapowarr.requests.get", side_effect=_fake_kapowarr)
    def test_second_sync_creates_no_duplicates(self, _mock_get):
        kapowarr.importer(None, self.user, "new")
        kapowarr.importer(None, self.user, "new")

        self.assertEqual(
            Item.objects.filter(media_type=MediaTypes.COMIC_ISSUE.value).count(), 2
        )
        self.assertEqual(CollectionSourceState.objects.count(), 2)
        self.assertEqual(CollectionEntry.objects.count(), 2)

    def test_issue_whose_file_is_gone_stops_being_owned(self):
        with patch(
            "integrations.imports.kapowarr.requests.get", side_effect=_fake_kapowarr
        ):
            kapowarr.importer(None, self.user, "new")

        def _issue_301_deleted(url, params=None, timeout=None, allow_redirects=False):
            response = _fake_kapowarr(url, params=params, timeout=timeout)
            if url.endswith("/api/volumes/1"):
                data = copy.deepcopy(SAGA)
                data["result"]["issues"][0]["files"] = []
                response.json.return_value = data
            return response

        with patch(
            "integrations.imports.kapowarr.requests.get",
            side_effect=_issue_301_deleted,
        ):
            counts, _ = kapowarr.importer(None, self.user, "new")

        self.assertEqual(self._owned_issue_ids(), {"302"})
        self.assertEqual(counts["removed"], 1)

    def test_failed_sync_keeps_existing_copies(self):
        with patch(
            "integrations.imports.kapowarr.requests.get", side_effect=_fake_kapowarr
        ):
            kapowarr.importer(None, self.user, "new")

        def _volume_fails(url, params=None, timeout=None, allow_redirects=False):
            if url.endswith("/api/volumes/1"):
                raise requests.exceptions.ReadTimeout("read timed out")
            return _fake_kapowarr(url, params=params, timeout=timeout)

        with (
            patch(
                "integrations.imports.kapowarr.requests.get", side_effect=_volume_fails
            ),
            self.assertRaises(helpers.MediaImportError),
        ):
            kapowarr.importer(None, self.user, "new")

        self.assertEqual(self._owned_issue_ids(), {"301", "302"})

    def test_kapowarr_and_mylar_copies_stay_separate(self):
        """A Kapowarr sync never removes the copies another source owns."""
        item = Item.objects.create(
            media_id="999",
            source=Sources.COMICVINE.value,
            media_type=MediaTypes.COMIC_ISSUE.value,
            title="Owned via Mylar3",
        )
        CollectionSourceState.objects.create(
            user=self.user, item=item, source="mylar", source_instance_id=1
        )

        with patch(
            "integrations.imports.kapowarr.requests.get", side_effect=_fake_kapowarr
        ):
            kapowarr.importer(None, self.user, "new")

        self.assertTrue(
            CollectionSourceState.objects.filter(item=item, source="mylar").exists()
        )

    @patch("integrations.imports.kapowarr.requests.get")
    def test_rejected_key_marks_connection_broken(self, mock_get):
        """Kapowarr answers a wrong key with 401 and ApiKeyInvalid."""
        mock_get.return_value = _response(
            {"error": "ApiKeyInvalid", "result": {}}, status_code=401
        )

        with self.assertRaises(helpers.ConnectionAuthError):
            kapowarr.importer(None, self.user, "new")

        self.instance.refresh_from_db()
        self.assertTrue(self.instance.connection_broken)

    @patch("integrations.imports.kapowarr.requests.get")
    def test_timeout_is_recorded_without_leaking_the_key(self, mock_get):
        mock_get.side_effect = requests.exceptions.ConnectTimeout(
            "Max retries exceeded with url: /api/volumes?api_key=kapowarr-key"
        )

        with self.assertRaises(helpers.MediaImportError) as cm:
            kapowarr.importer(None, self.user, "new")

        self.instance.refresh_from_db()
        self.assertFalse(self.instance.connection_broken)
        self.assertIn("Could not reach Kapowarr", self.instance.last_error_message)
        self.assertNotIn("kapowarr-key", self.instance.last_error_message)
        self.assertNotIn("kapowarr-key", str(cm.exception))

    @patch("integrations.tasks._media_imports.import_media")
    def test_task_returns_failure_message_for_expected_errors(self, mock_import):
        mock_import.side_effect = helpers.MediaImportError("Could not reach Kapowarr")

        result = tasks.import_kapowarr(user_id=self.user.id)

        self.assertEqual(result, "Kapowarr import failed: Could not reach Kapowarr")


class KapowarrViewTests(TestCase):
    """Cover connecting, syncing and disconnecting a Kapowarr server."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="kapowarr-viewer")
        self.client.force_login(self.user)

    @patch("integrations.views.tasks.import_kapowarr.delay")
    @patch("integrations.views.KapowarrClient.healthcheck")
    def test_connect_creates_schedule_and_queues_initial_import(
        self, mock_healthcheck, mock_delay
    ):
        response = self.client.post(
            reverse("kapowarr_connect"),
            {"base_url": "https://kapowarr.local:5656", "api_key": "kapowarr-key"},
        )

        self.assertEqual(response.status_code, 302)
        instance = KapowarrInstance.objects.get(user=self.user)
        self.assertEqual(helpers.decrypt(instance.api_key), "kapowarr-key")
        task = PeriodicTask.objects.get(task="Import from Kapowarr (Recurring)")
        self.assertTrue(task.enabled)
        self.assertIn(f'"instance_id": {instance.id}', task.kwargs)
        mock_healthcheck.assert_called_once()
        mock_delay.assert_called_once_with(
            user_id=self.user.id, mode="new", instance_id=instance.id
        )

    @patch("integrations.views.tasks.import_kapowarr.delay")
    @patch("integrations.imports.kapowarr.requests.get")
    def test_connect_with_bad_key_saves_nothing(self, mock_get, mock_delay):
        mock_get.return_value = _response(
            {"error": "ApiKeyInvalid", "result": {}}, status_code=401
        )

        self.client.post(
            reverse("kapowarr_connect"),
            {"base_url": "https://kapowarr.local:5656", "api_key": "wrong"},
        )

        self.assertFalse(KapowarrInstance.objects.exists())
        self.assertFalse(
            PeriodicTask.objects.filter(
                task="Import from Kapowarr (Recurring)"
            ).exists()
        )
        mock_delay.assert_not_called()

    @patch("integrations.views.tasks.import_kapowarr.delay")
    @patch("integrations.views.KapowarrClient.healthcheck")
    def test_disconnect_removes_schedule_and_ownership_rows(
        self, _mock_healthcheck, _mock_delay
    ):
        self.client.post(
            reverse("kapowarr_connect"),
            {"base_url": "https://kapowarr.local:5656", "api_key": "kapowarr-key"},
        )
        instance = KapowarrInstance.objects.get(user=self.user)
        item = Item.objects.create(
            media_id="301",
            source=Sources.COMICVINE.value,
            media_type=MediaTypes.COMIC_ISSUE.value,
            title="Saga #1",
        )
        CollectionSourceState.objects.create(
            user=self.user, item=item, source="kapowarr", source_instance_id=instance.id
        )
        CollectionEntry.objects.create(user=self.user, item=item)

        self.client.post(reverse("kapowarr_disconnect"), {"instance_id": instance.id})

        self.assertFalse(CollectionEntry.objects.filter(item=item).exists())
        self.assertFalse(KapowarrInstance.objects.exists())
        self.assertFalse(
            PeriodicTask.objects.filter(
                task="Import from Kapowarr (Recurring)"
            ).exists()
        )

    def test_disconnect_scoped_to_owner(self):
        other = get_user_model().objects.create_user(username="someone-else")
        other_instance = KapowarrInstance.objects.create(
            user=other,
            base_url="https://kapowarr.local:5656",
            api_key=helpers.encrypt("key"),
        )

        response = self.client.post(
            reverse("kapowarr_disconnect"), {"instance_id": other_instance.id}
        )

        self.assertEqual(response.status_code, 404)
        self.assertTrue(KapowarrInstance.objects.filter(pk=other_instance.id).exists())

    def test_import_page_shows_kapowarr(self):
        response = self.client.get(reverse("import_data"))

        self.assertContains(response, "Import owned comics from Kapowarr.")
        self.assertContains(response, reverse("kapowarr_connect"))
