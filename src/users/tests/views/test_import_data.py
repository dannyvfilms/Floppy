from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string
from django_celery_results.models import TaskResult

from integrations.models import LastFMAccount, LastFMHistoryImportStatus, PlexAccount
from integrations.plex import PlexAuthError


class ImportDataViewTests(TestCase):
    """Tests for the import data settings view."""

    def setUp(self):
        """Create user for the tests."""
        self.credentials = {"username": "importuser", "password": "testpass123"}
        self.plex_token = get_random_string(16)
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    def test_import_data_ignores_structured_recurring_wrapper_results(self):
        """Recurring wrapper payloads should not break the import page."""
        TaskResult.objects.create(
            task_id="task-recurring",
            task_name="Import from Audiobookshelf (Recurring)",
            task_kwargs=(f'{{"user_id": {self.user.id}}}'),
            status="SUCCESS",
            date_done=timezone.now(),
            result='["child-task-id", null]',
        )

        response = self.client.get(reverse("import_data"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "users/import_data.html")

    @patch("users.models.User.get_import_tasks")
    def test_import_data_defers_import_activity_loading(self, mock_get_import_tasks):
        """The initial page should not block on import activity queries."""
        response = self.client.get(reverse("import_data"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("import_data_activity"))
        mock_get_import_tasks.assert_not_called()

    def test_import_data_activity_renders_history_and_schedules(self):
        """The async activity panel should still render import status details."""
        TaskResult.objects.create(
            task_id="task-recurring",
            task_name="Import from Audiobookshelf (Recurring)",
            task_kwargs=(f'{{"user_id": {self.user.id}}}'),
            status="SUCCESS",
            date_done=timezone.now(),
            result='["child-task-id", null]',
        )

        response = self.client.get(
            reverse("import_data_activity"),
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "users/components/import_activity.html")
        self.assertContains(response, "Active Periodic Imports")
        self.assertContains(response, "Import History")

    def test_import_data_activity_lists_media_by_import_source(self):
        """Media is grouped by media type and import source."""
        from app.models import Item, MediaTypes, Movie, Sources, Status
        from integrations.models import ImportRun

        trakt_runs = [
            ImportRun.objects.create(user=self.user, source="trakt"),
            ImportRun.objects.create(user=self.user, source="trakt"),
        ]
        for index, run in enumerate(trakt_runs):
            item = Item.objects.create(
                media_id=f"bulk-delete-movie-{index}",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title=f"Bulk Delete Movie {index}",
            )
            Movie.objects.create(
                item=item,
                user=self.user,
                status=Status.COMPLETED.value,
                import_run=run,
            )

        simkl_run = ImportRun.objects.create(user=self.user, source="simkl")
        simkl_item = Item.objects.create(
            media_id="bulk-delete-movie-simkl",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Bulk Delete Movie from Simkl",
        )
        Movie.objects.create(
            item=simkl_item,
            user=self.user,
            status=Status.COMPLETED.value,
            import_run=simkl_run,
        )

        response = self.client.get(
            reverse("import_data_activity"),
            HTTP_HX_REQUEST="true",
        )

        self.assertContains(response, "Imported Media by Source")
        self.assertContains(response, "Movie · 2 items")
        self.assertContains(response, "Movie · 1 item")
        self.assertEqual(response.content.decode().count("Movie · 2 items"), 1)
        self.assertContains(
            response,
            reverse("bulk_delete_by_import_source", args=["movie", "trakt"]),
        )
        self.assertContains(
            response,
            reverse("bulk_delete_by_import_source", args=["movie", "simkl"]),
        )

    def test_import_data_activity_media_summary_query_count_is_flat(self):
        """Media summary should not issue one COUNT query per import source (N+1 guard)."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from app.models import Item, MediaTypes, Movie, Sources, Status
        from integrations.models import ImportRun

        for index, source in enumerate(["trakt", "simkl", "plex", "lastfm", "yamtrack"]):
            run = ImportRun.objects.create(user=self.user, source=source)
            item = Item.objects.create(
                media_id=f"n1-guard-movie-{index}",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title=f"N+1 Guard Movie {index}",
            )
            Movie.objects.create(
                item=item,
                user=self.user,
                status=Status.COMPLETED.value,
                import_run=run,
            )

        with CaptureQueriesContext(connection) as few_sources:
            self.client.get(reverse("import_data_activity"), HTTP_HX_REQUEST="true")

        extra_run = ImportRun.objects.create(user=self.user, source="steam")
        extra_item = Item.objects.create(
            media_id="n1-guard-movie-extra",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="N+1 Guard Movie Extra",
        )
        Movie.objects.create(
            item=extra_item,
            user=self.user,
            status=Status.COMPLETED.value,
            import_run=extra_run,
        )

        with CaptureQueriesContext(connection) as more_sources:
            self.client.get(reverse("import_data_activity"), HTTP_HX_REQUEST="true")

        self.assertEqual(len(few_sources.captured_queries), len(more_sources.captured_queries))

    def test_import_data_shows_lastfm_history_status_and_action(self):
        """Last.fm card should render history backfill status and rerun controls."""
        LastFMAccount.objects.create(
            user=self.user,
            lastfm_username="listener",
            last_fetch_timestamp_uts=1700000000,
            history_import_status=LastFMHistoryImportStatus.FAILED,
            history_import_total_pages=6,
            history_import_next_page=2,
            history_import_last_error_message="Temporary Last.fm error",
        )

        response = self.client.get(reverse("import_data"))

        self.assertContains(response, "Full history import:")
        self.assertContains(response, "Failed")
        self.assertContains(response, "Page 2 of 6")
        self.assertContains(response, "Reimport full history")

    @override_settings(
        TRAKT_API="test-client-id", TRAKT_API_SECRET="test-client-secret"
    )
    def test_import_data_renders_trakt_profile_dropdown_when_configured(self):
        """With TRAKT_API/SECRET set, the Trakt card offers the public/private dropdown."""
        response = self.client.get(reverse("import_data"))

        self.assertContains(
            response, "x-data=\"{ traktProfileType: 'public' }\"", html=False
        )
        self.assertContains(
            response,
            '<label class="block text-sm text-[var(--color-text-secondary)] mb-2">Profile</label>',
            html=False,
        )
        self.assertContains(
            response, '<option value="public">Public profile</option>', html=False
        )
        self.assertContains(
            response,
            '<option value="private">Private profile (OAuth)</option>',
            html=False,
        )

    @override_settings(TRAKT_API="", TRAKT_API_SECRET="")
    def test_import_data_hides_trakt_public_private_when_unconfigured(self):
        """Without TRAKT_API/SECRET, only the data-export fallback should render."""
        response = self.client.get(reverse("import_data"))

        self.assertContains(
            response, "x-data=\"{ traktProfileType: 'csv' }\"", html=False
        )
        self.assertNotContains(
            response, '<option value="public">Public profile</option>', html=False
        )
        self.assertNotContains(
            response,
            '<option value="private">Private profile (OAuth)</option>',
            html=False,
        )
        self.assertContains(response, "Select Export File", html=False)

    def test_import_data_renders_trakt_export_upload(self):
        """The Trakt card should offer a data-export file upload fallback."""
        response = self.client.get(reverse("import_data"))

        self.assertContains(response, reverse("import_trakt_export_file"))
        self.assertContains(response, "trakt_export")
        self.assertContains(response, ".zip,.json,.csv")
        self.assertContains(response, "Select Export File")

    @patch("users.views.plex.list_sections")
    @patch("users.views.plex.fetch_account")
    def test_import_data_skips_live_plex_checks_during_initial_render(
        self,
        mock_fetch_account,
        mock_list_sections,
    ):
        """The import page should render from cached Plex state."""
        PlexAccount.objects.create(
            user=self.user,
            plex_token=self.plex_token,
            plex_username="listener",
        )

        response = self.client.get(reverse("import_data"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Checking")
        mock_fetch_account.assert_not_called()
        mock_list_sections.assert_not_called()

    @patch(
        "users.views.plex.fetch_account",
        return_value={"username": "updated-listener"},
    )
    def test_import_data_plex_status_verifies_connection_lazily(
        self,
        mock_fetch_account,
    ):
        """The lazy status endpoint should verify the token."""
        PlexAccount.objects.create(
            user=self.user,
            plex_token=self.plex_token,
            plex_username="listener",
        )

        response = self.client.get(reverse("import_data_plex_status"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "state": "connected",
                "error": "",
            },
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.plex_account.plex_username, "updated-listener")
        mock_fetch_account.assert_called_once_with(self.plex_token)

    @patch("users.views.plex.fetch_account", side_effect=PlexAuthError("bad token"))
    def test_import_data_plex_status_returns_error_state_for_invalid_token(
        self,
        _mock_fetch_account,
    ):
        """The lazy Plex status endpoint should surface invalid-token failures."""
        PlexAccount.objects.create(
            user=self.user,
            plex_token=self.plex_token,
            plex_username="listener",
        )

        response = self.client.get(reverse("import_data_plex_status"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "state": "error",
                "error": "Plex token expired or revoked. Please reconnect.",
            },
        )

    @patch(
        "users.views.plex.list_sections",
        return_value=[
            {
                "machine_identifier": "server-1",
                "id": "12",
                "title": "Movies",
                "server_name": "Living Room",
                "type": "movie",
            },
        ],
    )
    def test_import_data_plex_sections_refreshes_libraries_lazily(
        self,
        mock_list_sections,
    ):
        """The lazy libraries endpoint should refresh cached sections."""
        PlexAccount.objects.create(
            user=self.user,
            plex_token=self.plex_token,
            plex_username="listener",
        )

        response = self.client.get(reverse("import_data_plex_sections"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "sections": [
                    {
                        "machine_identifier": "server-1",
                        "id": "12",
                        "title": "Movies",
                        "server_name": "Living Room",
                        "type": "movie",
                        # Added so the import form can offer (and pre-select)
                        # audiobook routing for a music library.
                        "is_music": False,
                        "audiobook_hint": False,
                        "content_kind": "auto",
                    },
                ],
                "error": "",
            },
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.plex_account.sections[0]["title"], "Movies")
        self.assertIsNotNone(self.user.plex_account.sections_refreshed_at)
        mock_list_sections.assert_called_once_with(self.plex_token)

    def test_arr_cards_show_connected_only_for_a_working_instance(self):
        """The Radarr/Sonarr/Mylar3 cards read their instance lists, not an account."""
        from integrations.imports.helpers import encrypt
        from integrations.models import MylarInstance, RadarrInstance, SonarrInstance

        RadarrInstance.objects.create(
            user=self.user, base_url="https://radarr.local", api_key=encrypt("k")
        )
        SonarrInstance.objects.create(
            user=self.user,
            base_url="https://sonarr.local",
            api_key=encrypt("k"),
            connection_broken=True,
        )
        MylarInstance.objects.create(
            user=self.user, base_url="https://mylar.local", api_key=encrypt("k")
        )

        response = self.client.get(reverse("import_data"))

        self.assertTrue(response.context["radarr_connected"])
        self.assertFalse(response.context["sonarr_connected"])
        self.assertTrue(response.context["mylar_connected"])
