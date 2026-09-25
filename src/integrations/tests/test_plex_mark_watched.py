import json
import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django_celery_beat.models import PeriodicTask

from app.models import Movie
from integrations import tasks
from integrations.imports import plex
from integrations.imports.helpers import MediaImportError
from integrations.imports.plex import PlexHistoryImporter
from integrations.models import PlexAccount

CHECKPOINT_TS = 1700000000


def setUpModule():
    """Silence importer log noise for this module only."""
    logging.getLogger("integrations.imports.plex").setLevel(logging.CRITICAL)


def tearDownModule():
    """Restore the importer logger level for other modules."""
    logging.getLogger("integrations.imports.plex").setLevel(logging.NOTSET)


def _movie_entry(tmdb_id, viewed_at):
    return {
        "type": "movie",
        "title": f"Movie {tmdb_id}",
        "guid": f"tmdb://{tmdb_id}",
        "viewedAt": viewed_at,
        "accountID": "1",
        "ratingKey": f"rk{tmdb_id}",
        "key": f"/library/metadata/rk{tmdb_id}",
    }


def _movie_metadata(media_type, media_id, source=None, **_kwargs):
    return {
        "title": f"Movie {media_id}",
        "media_id": media_id,
        "media_type": "movie",
        "max_progress": 1,
        "image": "/p.jpg",
        "details": {"release_date": "2021-12-24", "runtime": "1h 30m"},
    }


@patch("integrations.imports.plex.PlexHistoryImporter._import_ratings_from_library")
@patch("integrations.imports.plex.plex_api.list_users", return_value=[])
@patch("integrations.imports.plex.services.get_media_metadata", _movie_metadata)
@patch("integrations.imports.plex.plex_api.fetch_history")
@patch(
    "integrations.imports.plex.plex_api.list_resources",
    return_value=[
        {"machine_identifier": "machine", "connections": [{"uri": "http://plex"}]}
    ],
)
class PlexMarkWatchedImporterTests(TestCase):
    """The poll only imports Plex history newer than its checkpoint."""

    def setUp(self):
        """Connect a Plex account whose checkpoint sits an hour ago."""
        self.user = get_user_model().objects.create_user(username="plexuser")
        self.user.plex_usernames = "plexuser"
        self.user.save(update_fields=["plex_usernames"])
        self.checkpoint = timezone.now().replace(microsecond=0) - timedelta(hours=1)
        self.checkpoint_ts = int(self.checkpoint.timestamp())
        self.account = PlexAccount.objects.create(
            user=self.user,
            plex_token="token",
            plex_username="plexuser",
            plex_account_id="1",
            sections=[
                {"id": "1", "machine_identifier": "machine", "type": "movie"},
                {"id": "2", "machine_identifier": "machine", "type": "movie"},
            ],
            mark_watched_checkpoint=self.checkpoint,
        )

    def _set_checkpoint(self, value):
        PlexAccount.objects.filter(pk=self.account.pk).update(
            mark_watched_checkpoint=value,
        )

    def _poll(self):
        before = timezone.now()
        # Load the user fresh, as the Celery task does, so the account's
        # stored checkpoint is the one read.
        user = get_user_model().objects.get(pk=self.user.pk)
        plex.mark_watched_importer(["all"], user, "new")
        after = timezone.now()
        self.account.refresh_from_db()
        return before, after

    def test_imports_only_entries_after_checkpoint(self, _res, mock_fetch, *_):
        """A manual mark after the checkpoint lands; older history does not."""
        mock_fetch.return_value = (
            [
                _movie_entry("200", self.checkpoint_ts + 60),
                _movie_entry("100", self.checkpoint_ts - 60),
            ],
            2,
        )

        self._poll()

        movies = Movie.objects.filter(user=self.user)
        self.assertEqual(list(movies.values_list("item__media_id", flat=True)), ["200"])

    def test_checkpoint_trails_poll_start_not_newest_entry(self, _res, mock_fetch, *_):
        """The checkpoint never jumps to the newest entry seen.

        Libraries are read in turn, so a mark landing on an already-read
        library mid-poll must still be newer than the checkpoint next time.
        """
        mock_fetch.side_effect = [
            ([], 0),  # library 1: nothing yet
            ([_movie_entry("200", int(timezone.now().timestamp()))], 1),
        ]

        before, after = self._poll()

        self.assertEqual(mock_fetch.call_count, 2)
        checkpoint = self.account.mark_watched_checkpoint
        self.assertGreaterEqual(checkpoint, before - plex.MARK_WATCHED_OVERLAP)
        self.assertLessEqual(checkpoint, after - plex.MARK_WATCHED_OVERLAP)

    def test_failed_entry_holds_checkpoint_for_retry(self, _res, mock_fetch, *_):
        """An entry that failed to import is read again on the next poll."""
        failed_ts = self.checkpoint_ts + 120
        mock_fetch.return_value = (
            [
                _movie_entry("300", failed_ts),
                _movie_entry("200", self.checkpoint_ts + 60),
            ],
            2,
        )
        original = PlexHistoryImporter._process_entry

        def fail_300(importer, entry, *args, **kwargs):
            if entry.get("ratingKey") == "rk300":
                msg = "Plex metadata request timed out"
                raise MediaImportError(msg)
            return original(importer, entry, *args, **kwargs)

        with patch.object(
            PlexHistoryImporter, "_process_entry", autospec=True, side_effect=fail_300
        ):
            self._poll()

        self.assertEqual(
            self.account.mark_watched_checkpoint,
            datetime.fromtimestamp(failed_ts - 1, tz=UTC),
        )

    def test_old_failure_stops_holding_checkpoint(self, _res, mock_fetch, *_):
        """A failure older than the retry window cannot pin the checkpoint."""
        old = self.checkpoint - timedelta(days=2)
        self._set_checkpoint(old)
        mock_fetch.return_value = (
            [_movie_entry("300", int(old.timestamp()) + 60)],
            1,
        )

        with patch.object(
            PlexHistoryImporter,
            "_process_entry",
            side_effect=MediaImportError("Could not match"),
        ):
            before, after = self._poll()

        checkpoint = self.account.mark_watched_checkpoint
        self.assertGreaterEqual(checkpoint, before - plex.MARK_WATCHED_RETRY_WINDOW)
        self.assertLessEqual(checkpoint, after - plex.MARK_WATCHED_RETRY_WINDOW)

    def test_checkpoint_never_moves_before_enable_time(self, _res, mock_fetch, *_):
        """A poll right after enabling does not re-read history from before it."""
        recent = timezone.now() - timedelta(minutes=2)
        self._set_checkpoint(recent)
        mock_fetch.return_value = ([], 0)

        self._poll()

        self.assertEqual(self.account.mark_watched_checkpoint, recent)

    def test_stops_paging_at_checkpoint(self, _res, mock_fetch, *_):
        """Reaching an entry at or before the checkpoint ends the fetch."""
        self.account.sections = self.account.sections[:1]
        self.account.save(update_fields=["sections"])
        mock_fetch.return_value = ([_movie_entry("100", self.checkpoint_ts)], 5000)

        self._poll()

        self.assertEqual(mock_fetch.call_count, 1)
        self.assertFalse(Movie.objects.filter(user=self.user).exists())

    def test_skips_library_ratings_pass(self, _res, mock_fetch, _users, mock_ratings):
        """The poll never walks every library item for ratings."""
        mock_fetch.return_value = ([], 0)

        self._poll()

        mock_ratings.assert_not_called()

    def test_replayed_entry_is_not_a_second_play(self, _res, mock_fetch, *_):
        """An entry already recorded (by a webhook or an earlier poll) is skipped."""
        mock_fetch.return_value = ([_movie_entry("200", self.checkpoint_ts + 60)], 1)

        self._poll()
        self._set_checkpoint(self.checkpoint)
        self._poll()

        self.assertEqual(Movie.objects.filter(user=self.user).count(), 1)


class PlexMarkWatchedScheduleTests(TestCase):
    """Turning the sync on and off manages one periodic task."""

    def setUp(self):
        """Connect a Plex account and log in."""
        self.credentials = {"username": "plexuser", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    def _connect(self):
        return PlexAccount.objects.create(
            user=self.user, plex_token="token", plex_username="plexuser"
        )

    def _tasks(self):
        return PeriodicTask.objects.filter(task=plex.MARK_WATCHED_TASK_NAME)

    def test_enable_creates_task_and_starts_checkpoint_now(self):
        """Enabling schedules the poll and never replays older history."""
        account = self._connect()

        response = self.client.post(
            reverse("update_plex_mark_watched"),
            {"plex_mark_watched_enabled": "on"},
        )

        self.assertRedirects(
            response, reverse("integrations"), fetch_redirect_response=False
        )
        account.refresh_from_db()
        self.assertTrue(account.mark_watched_sync_enabled)
        self.assertIsNotNone(account.mark_watched_checkpoint)
        task = self._tasks().get()
        self.assertEqual(json.loads(task.kwargs), {"user_id": self.user.id})
        self.assertEqual(task.interval.every, plex.MARK_WATCHED_INTERVAL_MINUTES)

    def test_saving_again_keeps_checkpoint_and_one_task(self):
        """Re-saving while enabled does not skip marks made since the last poll."""
        account = self._connect()
        plex.set_mark_watched_sync(account, enabled=True)
        checkpoint = datetime.fromtimestamp(CHECKPOINT_TS, tz=UTC)
        PlexAccount.objects.filter(pk=account.pk).update(
            mark_watched_checkpoint=checkpoint,
        )

        self.client.post(
            reverse("update_plex_mark_watched"),
            {"plex_mark_watched_enabled": "on"},
        )

        account.refresh_from_db()
        self.assertEqual(account.mark_watched_checkpoint, checkpoint)
        self.assertEqual(self._tasks().count(), 1)

    def test_disable_deletes_task(self):
        """Unticking removes the schedule."""
        account = self._connect()
        plex.set_mark_watched_sync(account, enabled=True)

        self.client.post(reverse("update_plex_mark_watched"), {})

        account.refresh_from_db()
        self.assertFalse(account.mark_watched_sync_enabled)
        self.assertFalse(self._tasks().exists())

    def test_disconnect_deletes_task(self):
        """Disconnecting Plex leaves no poll behind."""
        account = self._connect()
        plex.set_mark_watched_sync(account, enabled=True)

        self.client.post(reverse("plex_disconnect"))

        self.assertFalse(self._tasks().exists())

    def test_requires_plex_connection(self):
        """Without a Plex account nothing is scheduled."""
        response = self.client.post(
            reverse("update_plex_mark_watched"),
            {"plex_mark_watched_enabled": "on"},
        )

        self.assertRedirects(
            response, reverse("integrations"), fetch_redirect_response=False
        )
        self.assertFalse(self._tasks().exists())
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertIn("Connect Plex before changing this setting.", messages)

    @patch("integrations.imports.plex.mark_watched_importer")
    def test_task_skips_when_disabled(self, mock_importer):
        """A leftover task for a disabled account does nothing."""
        self._connect()

        result = tasks.sync_plex_mark_watched(user_id=self.user.id)

        self.assertIn("Skipped", result)
        mock_importer.assert_not_called()
