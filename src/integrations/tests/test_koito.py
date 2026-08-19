# FORK: tests for the receive-only Koito listening-history integration.
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db.utils import OperationalError
from django.test import TestCase
from django.urls import reverse
from django_celery_beat.models import CrontabSchedule, PeriodicTask

from app.models import Music
from app.services import music_scrobble
from integrations import koito_api, koito_sync, tasks
from integrations.imports import helpers
from integrations.models import ImportRun, KoitoAccount, LastFMHistoryImportStatus
from integrations.webhooks.koito import KoitoScrobbleProcessor

API_KEY = "koito-secret-key"
BASE_URL = "https://koito.example.com"


def _listen(
    time="2026-07-01T12:00:00Z",
    track_id=1,
    title="Roygbiv",
    artist="Boards of Canada",
):
    """Build a Koito /listens item."""
    return {
        "time": time,
        "track": {
            "id": track_id,
            "title": title,
            "artists": [{"id": 9, "name": artist}],
        },
    }


def _page(items, *, has_next=False, page=1, total=None):
    """Build a Koito paginated response."""
    return {
        "items": items,
        "total_record_count": len(items) if total is None else total,
        "items_per_page": 500,
        "has_next_page": has_next,
        "current_page": page,
    }


class KoitoTestCase(TestCase):
    """Shared setup: a connected account and no MusicBrainz network calls."""

    def setUp(self):
        """Create a music-enabled user with a connected Koito account."""
        cache.clear()
        self.user = get_user_model().objects.create_user(username="koito-user")
        self.user.music_enabled = True
        self.user.save()
        self.account = KoitoAccount.objects.create(
            user=self.user,
            base_url=BASE_URL,
            api_key=helpers.encrypt(API_KEY),
        )

        for name in ("search", "search_artists"):
            patcher = patch(
                f"app.services.music_scrobble.musicbrainz.{name}",
                return_value={"results": [], "total_results": 0},
            )
            patcher.start()
            self.addCleanup(patcher.stop)

        # Fixtures carry MusicBrainz ids, which would otherwise send the
        # enrichment path out to the real MusicBrainz API during tests.
        for name in ("recording", "get_release", "get_release_for_group", "get_artist"):
            patcher = patch(
                f"app.services.music_scrobble.musicbrainz.{name}",
                return_value={},
            )
            patcher.start()
            self.addCleanup(patcher.stop)

        for name in (
            "sync_artist_discography",
            "prefetch_album_covers",
            "refresh_album_cover_art",
            "get_artist_hero_image",
        ):
            patcher = patch(
                f"app.services.music_scrobble.{name}",
                return_value=None,
            )
            patcher.start()
            self.addCleanup(patcher.stop)

        # Celery runs eagerly under test settings, so the post-import
        # enrichment tasks would otherwise call MusicBrainz for real.
        for name in ("enrich_music_library_task", "enrich_albums_task"):
            patcher = patch(f"app.tasks.{name}.delay", return_value=None)
            patcher.start()
            self.addCleanup(patcher.stop)


class KoitoCredentialTests(TestCase):
    """Credentials are entered in the UI and stored encrypted."""

    def setUp(self):
        """Create an authenticated user for Koito view requests."""
        cache.clear()
        self.user = get_user_model().objects.create_user(username="koito-connect")
        self.user.music_enabled = True
        self.user.save()
        self.client.force_login(self.user)

    @patch("integrations.views.tasks.import_koito_history.delay")
    @patch("integrations.views.tasks.poll_koito_for_user.delay")
    @patch("integrations.views.koito_api.validate_connection", return_value=True)
    def test_connect_stores_encrypted_key_and_schedules_poll(
        self,
        mock_validate,
        mock_poll,
        mock_history,
    ):
        """Connecting encrypts the key and creates a per-user poll schedule."""
        response = self.client.post(
            reverse("koito_connect"),
            {"base_url": BASE_URL, "api_key": API_KEY},
        )

        self.assertEqual(response.status_code, 302)
        account = KoitoAccount.objects.get(user=self.user)

        # The plaintext key must never hit the database.
        self.assertNotEqual(account.api_key, API_KEY)
        self.assertNotIn(API_KEY, account.api_key)
        self.assertEqual(helpers.decrypt(account.api_key), API_KEY)

        self.assertEqual(account.base_url, BASE_URL)
        self.assertIsNotNone(account.last_fetch_timestamp_uts)
        mock_poll.assert_called_once()
        mock_history.assert_called_once()
        self.assertTrue(
            PeriodicTask.objects.filter(
                task=tasks.KOITO_POLL_TASK_NAME,
                kwargs__contains=f'"user_id": {self.user.id}',
                enabled=True,
            ).exists(),
        )

    @patch("integrations.views.koito_api.validate_connection", return_value=True)
    def test_connect_requires_both_fields(self, mock_validate):
        """A missing URL or key is rejected before any account is created."""
        response = self.client.post(reverse("koito_connect"), {"base_url": BASE_URL})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(KoitoAccount.objects.filter(user=self.user).exists())
        mock_validate.assert_not_called()

    @patch(
        "integrations.views.koito_api.validate_connection",
        side_effect=koito_api.KoitoAuthError("Koito rejected the API key."),
    )
    def test_connect_rejects_bad_credentials(self, mock_validate):
        """An invalid key does not create an account."""
        response = self.client.post(
            reverse("koito_connect"),
            {"base_url": BASE_URL, "api_key": "wrong"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(KoitoAccount.objects.filter(user=self.user).exists())

    @patch("integrations.views.koito_api.validate_connection", return_value=True)
    def test_api_key_is_never_rendered_to_the_page(self, mock_validate):
        """The stored key must not appear in the Import Data page."""
        KoitoAccount.objects.create(
            user=self.user,
            base_url=BASE_URL,
            api_key=helpers.encrypt(API_KEY),
        )
        response = self.client.get(reverse("import_data"))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertNotIn(API_KEY, body)
        self.assertIn(BASE_URL, body)

    def test_connect_form_renders_when_disconnected(self):
        """The Koito modal offers URL + API key inputs before connecting."""
        response = self.client.get(reverse("import_data"))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("activeModal === 'koito'", body)
        self.assertIn(reverse("koito_connect"), body)
        self.assertIn('name="base_url"', body)
        self.assertIn('name="api_key"', body)

    def test_disconnect_removes_account_and_schedule(self):
        """Disconnecting deletes both the account and its periodic task."""
        KoitoAccount.objects.create(
            user=self.user,
            base_url=BASE_URL,
            api_key=helpers.encrypt(API_KEY),
        )
        crontab, _ = CrontabSchedule.objects.get_or_create(
            minute="*/15",
            hour="*",
            day_of_week="*",
            day_of_month="*",
            month_of_year="*",
        )
        PeriodicTask.objects.create(
            name=f"Poll Koito for {self.user.username} (every 15 minutes)",
            task=tasks.KOITO_POLL_TASK_NAME,
            kwargs=f'{{"user_id": {self.user.id}}}',
            crontab=crontab,
        )

        self.client.post(reverse("koito_disconnect"))

        self.assertFalse(KoitoAccount.objects.filter(user=self.user).exists())
        self.assertFalse(
            PeriodicTask.objects.filter(
                task=tasks.KOITO_POLL_TASK_NAME,
                kwargs__contains=f'"user_id": {self.user.id}',
            ).exists(),
        )


class KoitoSyncTests(KoitoTestCase):
    """Incremental polling and cursor semantics."""

    @patch("integrations.koito_api.get_track", return_value={})
    @patch("integrations.koito_api.get_listens")
    def test_poll_records_listens_and_advances_cursor(self, mock_listens, mock_track):
        """A complete window records listens and moves the cursor forward."""
        mock_listens.return_value = _page([_listen()])

        result = tasks._run_incremental_koito_sync(self.account)

        self.assertEqual(result["status"], "success")
        self.assertEqual(Music.objects.filter(user=self.user).count(), 1)

        self.account.refresh_from_db()
        expected = koito_api.listen_timestamp_uts(_listen())
        self.assertEqual(self.account.last_fetch_timestamp_uts, expected)
        self.assertEqual(self.account.failure_count, 0)

    @patch("integrations.koito_api.get_track", return_value={})
    @patch("integrations.koito_api.get_listens")
    def test_partial_window_does_not_advance_cursor(self, mock_listens, mock_track):
        """An interrupted window keeps the cursor so it is retried."""
        self.account.last_fetch_timestamp_uts = 1000
        self.account.save()

        mock_listens.side_effect = [
            _page([_listen()], has_next=True, total=2),
            koito_api.KoitoAPIError("boom"),
        ]

        result = tasks._run_incremental_koito_sync(self.account)

        self.assertEqual(result["status"], "partial")
        self.account.refresh_from_db()
        self.assertEqual(self.account.last_fetch_timestamp_uts, 1000)
        self.assertEqual(self.account.failure_count, 1)

    @patch("integrations.koito_api.get_listens")
    def test_undecryptable_key_reports_friendly_error(self, mock_listens):
        """A key encrypted under an old SECRET_KEY asks the user to reconnect."""
        self.account.api_key = "not-a-valid-fernet-token"
        self.account.save()

        result = tasks._run_incremental_koito_sync(self.account)

        self.assertEqual(result["status"], "error")
        mock_listens.assert_not_called()
        self.account.refresh_from_db()
        self.assertIn("reconnect", self.account.last_error_message.lower())

    @patch("integrations.koito_api.get_listens")
    def test_auth_error_marks_connection_broken(self, mock_listens):
        """A rejected key marks the account broken so polling backs off."""
        mock_listens.side_effect = koito_api.KoitoAuthError("bad key")

        result = tasks._run_incremental_koito_sync(self.account)

        self.assertEqual(result["status"], "error")
        self.account.refresh_from_db()
        self.assertTrue(self.account.connection_broken)

    @patch("integrations.koito_api.get_track", return_value={})
    @patch("integrations.koito_api.get_listens")
    def test_music_disabled_skips_sync(self, mock_listens, mock_track):
        """Users with music tracking off are skipped without any API call."""
        self.user.music_enabled = False
        self.user.save()
        self.account.refresh_from_db()

        result = tasks._run_incremental_koito_sync(self.account)

        self.assertEqual(result["status"], "skipped")
        mock_listens.assert_not_called()

    @patch("integrations.koito_api.get_track", return_value={})
    @patch("integrations.koito_api.get_listens")
    def test_repeated_poll_does_not_duplicate_listens(self, mock_listens, mock_track):
        """Overlapping windows do not double-count the same listen."""
        mock_listens.return_value = _page([_listen()])

        tasks._run_incremental_koito_sync(self.account)
        tasks._run_incremental_koito_sync(self.account)

        self.assertEqual(Music.objects.filter(user=self.user).count(), 1)
        entry = Music.objects.get(user=self.user)
        self.assertEqual(entry.progress, 1)


class KoitoHydrationTests(KoitoTestCase):
    """Track metadata is hydrated once per distinct track id."""

    @patch("integrations.koito_api.get_album")
    @patch("integrations.koito_api.get_track")
    def test_track_hydration_is_cached_across_listens(self, mock_track, mock_album):
        """Repeated track ids trigger a single /track/{id} lookup."""
        mock_track.return_value = {
            "musicbrainz_id": "rec-1",
            "duration": 210,
            "album_id": 5,
        }
        mock_album.return_value = {
            "title": "Music Has the Right to Children",
            "musicbrainz_id": "rel-1",
        }

        processor = KoitoScrobbleProcessor(
            BASE_URL,
            API_KEY,
            account_id=self.account.id,
        )
        listens = [
            _listen(time="2026-07-01T12:00:00Z", track_id=1),
            _listen(time="2026-07-01T12:05:00Z", track_id=1),
            _listen(time="2026-07-01T12:10:00Z", track_id=1),
        ]
        processor.process_listens(listens, self.user)

        self.assertEqual(mock_track.call_count, 1)
        self.assertEqual(Music.objects.filter(user=self.user).count(), 1)

    @patch("integrations.koito_api.get_album")
    @patch("integrations.koito_api.get_track")
    def test_hydrated_metadata_reaches_the_playback_event(self, mock_track, mock_album):
        """MBIDs, duration and album title from hydration are applied."""
        mock_track.return_value = {
            "musicbrainz_id": "rec-1",
            "duration": 210,
            "album_id": 5,
        }
        mock_album.return_value = {"title": "Geogaddi", "musicbrainz_id": "rel-1"}

        processor = KoitoScrobbleProcessor(
            BASE_URL,
            API_KEY,
            account_id=self.account.id,
        )
        with patch(
            "integrations.webhooks.koito.music_scrobble.record_music_playback",
        ) as mock_record:
            mock_record.return_value = None
            processor.process_listen(_listen(), self.user)

        event = mock_record.call_args.args[0]
        self.assertEqual(event.album_title, "Geogaddi")
        self.assertEqual(event.duration_ms, 210000)
        self.assertEqual(event.external_ids["musicbrainz_recording"], "rec-1")
        self.assertEqual(event.external_ids["musicbrainz_release"], "rel-1")

    @patch(
        "integrations.koito_api.get_track",
        side_effect=koito_api.KoitoAPIError("track lookup failed"),
    )
    def test_listen_still_records_when_hydration_fails(self, mock_track):
        """A failed track lookup degrades matching but does not drop the listen."""
        processor = KoitoScrobbleProcessor(
            BASE_URL,
            API_KEY,
            account_id=self.account.id,
        )
        processor.process_listen(_listen(), self.user)

        self.assertEqual(Music.objects.filter(user=self.user).count(), 1)

    @patch("integrations.koito_api.get_album")
    @patch("integrations.koito_api.get_track")
    def test_listen_recording_retries_on_database_lock(self, mock_track, mock_album):
        """A transient 'database is locked' error should be retried, not dropped."""
        mock_track.return_value = {
            "musicbrainz_id": "rec-1",
            "duration": 210,
            "album_id": 5,
        }
        mock_album.return_value = {"title": "Geogaddi", "musicbrainz_id": "rel-1"}

        processor = KoitoScrobbleProcessor(
            BASE_URL,
            API_KEY,
            account_id=self.account.id,
        )
        real_record = music_scrobble.record_music_playback
        call_count = {"n": 0}

        def flaky_record(event):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise OperationalError("database is locked")
            return real_record(event)

        with patch(
            "integrations.webhooks.koito.music_scrobble.record_music_playback",
            side_effect=flaky_record,
        ):
            processor.process_listen(_listen(), self.user)

        self.assertEqual(call_count["n"], 2)
        self.assertEqual(Music.objects.filter(user=self.user).count(), 1)


class KoitoExportTests(KoitoTestCase):
    """The export endpoint drives the full-history backfill."""

    EXPORT = {
        "version": "1",
        "user": "koito-user",
        "listens": [
            {
                "listened_at": "2026-06-01T08:00:00Z",
                "client": "multi-scrobbler",
                "track": {
                    "mbid": "rec-1",
                    "duration": 195,
                    "aliases": [
                        {"alias": "Roygbiv", "is_primary": True},
                        {"alias": "ROYGBIV", "is_primary": False},
                    ],
                },
                "album": {
                    "mbid": "rel-1",
                    "aliases": [
                        {
                            "alias": "Music Has the Right to Children",
                            "is_primary": True,
                        },
                    ],
                },
                "artists": [
                    {
                        "mbid": "art-1",
                        "is_primary": True,
                        "aliases": [{"alias": "Boards of Canada", "is_primary": True}],
                    },
                ],
            },
        ],
    }

    def test_export_maps_aliases_and_mbids(self):
        """Export entries are normalised via their primary aliases."""
        listens = koito_sync.export_to_listens(self.EXPORT)

        self.assertEqual(len(listens), 1)
        listen = listens[0]
        self.assertEqual(listen["track"]["title"], "Roygbiv")
        self.assertEqual(listen["track"]["artists"][0]["name"], "Boards of Canada")
        details = listen["_details"]
        self.assertEqual(details["album_title"], "Music Has the Right to Children")
        self.assertEqual(details["musicbrainz_recording"], "rec-1")
        self.assertEqual(details["musicbrainz_release"], "rel-1")
        self.assertEqual(details["musicbrainz_artist"], "art-1")
        self.assertEqual(details["duration_ms"], 195000)

    @patch("integrations.koito_api.get_track")
    @patch("integrations.koito_api.get_export")
    def test_history_import_records_listens_without_hydration(
        self,
        mock_export,
        mock_track,
    ):
        """The export is pre-hydrated, so no per-track lookups are made."""
        mock_export.return_value = self.EXPORT

        tasks.import_koito_history(user_id=self.user.id)

        self.assertEqual(Music.objects.filter(user=self.user).count(), 1)
        mock_track.assert_not_called()

        self.account.refresh_from_db()
        self.assertEqual(
            self.account.history_import_status,
            LastFMHistoryImportStatus.COMPLETED,
        )
        self.assertIsNotNone(self.account.history_import_completed_at)

        run = ImportRun.objects.get(user=self.user, source="koito")
        self.assertEqual(run.status, ImportRun.Status.COMPLETED)
        self.assertEqual(run.created_count, 1)
        self.assertIsNotNone(run.finished_at)
        music = Music.objects.get(user=self.user)
        self.assertEqual(music.import_run_id, run.id)

    @patch(
        "integrations.koito_api.get_export",
        side_effect=koito_api.KoitoAuthError("bad key"),
    )
    def test_history_import_failure_marks_status_and_releases_lock(self, mock_export):
        """A failed export marks the import failed and frees the lock."""
        with self.assertRaises(koito_api.KoitoAuthError):
            tasks.import_koito_history(user_id=self.user.id)

        self.account.refresh_from_db()
        self.assertEqual(
            self.account.history_import_status,
            LastFMHistoryImportStatus.FAILED,
        )
        self.assertTrue(self.account.connection_broken)
        # Lock released, so a retry is possible.
        lock_key = koito_sync.get_koito_history_import_lock_key(self.user.id)
        self.assertIsNone(cache.get(lock_key))

        run = ImportRun.objects.get(user=self.user, source="koito")
        self.assertEqual(run.status, ImportRun.Status.FAILED)
        self.assertIsNotNone(run.finished_at)

    @patch("integrations.koito_api.get_album")
    @patch("integrations.koito_api.get_track")
    @patch("integrations.koito_api.get_listens")
    @patch("integrations.koito_api.get_export")
    def test_export_and_poll_do_not_duplicate_the_same_listen(
        self,
        mock_export,
        mock_listens,
        mock_track,
        mock_album,
    ):
        """A listen present in both the export and a poll is recorded once."""
        mock_export.return_value = self.EXPORT
        mock_listens.return_value = _page(
            [_listen(time="2026-06-01T08:00:00Z", track_id=1)],
        )
        # Hydration resolves the same album the export carries, which is what
        # lets the duplicate check match across the two ingest paths.
        mock_track.return_value = {
            "musicbrainz_id": "rec-1",
            "duration": 195,
            "album_id": 5,
        }
        mock_album.return_value = {
            "title": "Music Has the Right to Children",
            "musicbrainz_id": "rel-1",
        }

        tasks.import_koito_history(user_id=self.user.id)
        tasks._run_incremental_koito_sync(self.account)

        self.assertEqual(Music.objects.filter(user=self.user).count(), 1)


class KoitoReceiveOnlyTests(KoitoTestCase):
    """Floppy must never write to Koito."""

    @patch("integrations.koito_api.get_album", return_value={})
    @patch("integrations.koito_api.get_track", return_value={})
    @patch("integrations.koito_api.get_export")
    @patch("integrations.koito_api.get_listens")
    @patch("integrations.koito_api.requests.get")
    def test_no_write_verbs_are_available_or_used(
        self,
        mock_get,
        mock_listens,
        mock_export,
        mock_track,
        mock_album,
    ):
        """The client module exposes no POST/PUT/PATCH/DELETE calls."""
        import inspect

        source = inspect.getsource(koito_api)
        write_verbs = (
            "requests.post",
            "requests.put",
            "requests.patch",
            "requests.delete",
        )
        for verb in write_verbs:
            self.assertNotIn(verb, source)

        # And a full poll cycle only ever issues GETs.
        mock_listens.return_value = _page([_listen()])
        tasks._run_incremental_koito_sync(self.account)
        for call in mock_get.call_args_list:
            self.assertTrue(str(call).startswith("call("))
