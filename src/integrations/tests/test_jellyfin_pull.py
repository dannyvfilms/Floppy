from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from integrations.imports.helpers import MediaImportError
from integrations.jellyfin_client import JellyfinAuthError, JellyfinClientError
from integrations.models import ImportRun, JellyfinAccount
from integrations.tasks._jellyfin_pull import pull_jellyfin_history


class PullJellyfinHistoryTaskTests(TestCase):
    """Cover tier selection and cursor handling in the automatic pull task."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="pull-task-user")
        self.account = JellyfinAccount.objects.create(
            user=self.user,
            base_url="https://jellyfin.example",
            api_key="encrypted",
            jellyfin_user_id="jf-user",
        )

    @patch(
        "integrations.imports.jellyfin_playback_reporting.decrypt_or_raise",
        return_value="api-key",
    )
    @patch(
        "integrations.tasks._jellyfin_pull.decrypt_or_raise",
        return_value="api-key",
    )
    @patch("integrations.jellyfin_client.JellyfinClient.iter_library_items")
    @patch("integrations.jellyfin_client.JellyfinClient.fetch_playback_activity")
    @patch("integrations.jellyfin_client.JellyfinClient.probe_playback_reporting")
    def test_uses_playback_reporting_tier_when_available(
        self,
        mock_probe,
        mock_fetch,
        mock_library,
        mock_decrypt_task,
        mock_decrypt_importer,
    ):
        mock_probe.return_value = True
        mock_fetch.return_value = []
        mock_library.return_value = []

        pull_jellyfin_history(self.user.id)

        self.account.refresh_from_db()
        self.assertTrue(self.account.playback_reporting_available)
        self.assertEqual(self.account.playback_reporting_last_rowid, 0)
        self.assertIsNotNone(self.account.last_pull_at)
        mock_fetch.assert_called_once_with(0, 2000)

    @patch(
        "integrations.imports.jellyfin_playback_reporting.decrypt_or_raise",
        return_value="api-key",
    )
    @patch(
        "integrations.tasks._jellyfin_pull.decrypt_or_raise",
        return_value="api-key",
    )
    @patch("integrations.jellyfin_client.JellyfinClient.iter_library_items")
    @patch("integrations.jellyfin_client.JellyfinClient.fetch_playback_activity")
    @patch("integrations.jellyfin_client.JellyfinClient.probe_playback_reporting")
    def test_reprobes_after_a_prior_unavailable_result(
        self,
        mock_probe,
        mock_fetch,
        mock_library,
        mock_decrypt_task,
        mock_decrypt_importer,
    ):
        """A stale False result must not permanently lock the account into tier 2."""
        self.account.playback_reporting_available = False
        self.account.save(update_fields=["playback_reporting_available"])
        mock_probe.return_value = True
        mock_fetch.return_value = []
        mock_library.return_value = []

        pull_jellyfin_history(self.user.id)

        mock_probe.assert_called_once()
        self.account.refresh_from_db()
        self.assertTrue(self.account.playback_reporting_available)

    @patch(
        "integrations.imports.jellyfin_playback_reporting.decrypt_or_raise",
        return_value="api-key",
    )
    @patch(
        "integrations.tasks._jellyfin_pull.decrypt_or_raise",
        return_value="api-key",
    )
    @patch("integrations.jellyfin_client.JellyfinClient.iter_library_items")
    @patch("integrations.jellyfin_client.JellyfinClient.fetch_playback_activity")
    @patch("integrations.jellyfin_client.JellyfinClient.probe_playback_reporting")
    def test_falls_back_to_library_backfill_when_fetch_fails_after_probe(
        self,
        mock_probe,
        mock_fetch,
        mock_library,
        mock_decrypt_task,
        mock_decrypt_importer,
    ):
        """A broken plugin can pass the probe but 500 on the actual query.

        That must not mark the connection broken -- it should fall back to
        the library backfill tier like any other "unavailable" result.
        """
        mock_probe.return_value = True
        mock_fetch.side_effect = JellyfinClientError(
            "Jellyfin request failed (500) for /user_usage_stats/submit_custom_query"
        )
        mock_library.return_value = []

        pull_jellyfin_history(self.user.id)

        mock_library.assert_called_once()
        self.account.refresh_from_db()
        self.assertFalse(self.account.connection_broken)
        self.assertFalse(self.account.playback_reporting_available)
        self.assertEqual(self.account.last_pull_error_message, "")

    @patch("integrations.tasks._jellyfin_pull.events.tasks.reload_calendar.delay")
    @patch(
        "integrations.imports.jellyfin_playback_reporting.decrypt_or_raise",
        return_value="api-key",
    )
    @patch(
        "integrations.tasks._jellyfin_pull.decrypt_or_raise",
        return_value="api-key",
    )
    @patch("integrations.jellyfin_client.JellyfinClient.iter_library_items")
    @patch("integrations.jellyfin_client.JellyfinClient.probe_playback_reporting")
    def test_library_backfill_triggers_one_catchup_reload_when_items_imported(
        self,
        mock_probe,
        mock_library,
        mock_decrypt_task,
        mock_decrypt_importer,
        mock_reload_calendar,
    ):
        from app.models import Item, MediaTypes, Movie, Status

        item = Item.objects.create(
            media_id="123",
            source="tmdb",
            media_type=MediaTypes.MOVIE.value,
            title="Movie",
            image="",
        )
        Movie.objects.create(
            item=item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
            score=None,
            notes="",
        )
        mock_probe.return_value = False
        mock_library.return_value = [
            {
                "Id": "jf-item",
                "Type": "Movie",
                "ProviderIds": {"Tmdb": "123"},
                "UserData": {"Played": True, "LastPlayedDate": "2024-01-02T03:04:05Z"},
            },
        ]

        pull_jellyfin_history(self.user.id)

        mock_reload_calendar.assert_called_once()

    @patch(
        "integrations.imports.jellyfin_playback_reporting.decrypt_or_raise",
        return_value="api-key",
    )
    @patch(
        "integrations.tasks._jellyfin_pull.decrypt_or_raise",
        return_value="api-key",
    )
    @patch("integrations.jellyfin_client.JellyfinClient.iter_library_items")
    @patch("integrations.jellyfin_client.JellyfinClient.probe_playback_reporting")
    def test_falls_back_to_library_backfill_when_unavailable(
        self,
        mock_probe,
        mock_library,
        mock_decrypt_task,
        mock_decrypt_importer,
    ):
        mock_probe.return_value = False
        mock_library.return_value = []

        message = pull_jellyfin_history(self.user.id)

        self.account.refresh_from_db()
        self.assertFalse(self.account.playback_reporting_available)
        self.assertIsNotNone(self.account.library_backfill_completed_at)
        self.assertIn("current watched state", message)

    @patch(
        "integrations.imports.jellyfin_playback_reporting.decrypt_or_raise",
        return_value="api-key",
    )
    @patch(
        "integrations.tasks._jellyfin_pull.decrypt_or_raise",
        return_value="api-key",
    )
    @patch("integrations.jellyfin_client.JellyfinClient.iter_library_items")
    @patch("integrations.jellyfin_client.JellyfinClient.fetch_max_playback_activity_rowid")
    @patch("integrations.jellyfin_client.JellyfinClient.fetch_playback_activity")
    @patch("integrations.jellyfin_client.JellyfinClient.probe_playback_reporting")
    def test_skips_full_backfill_after_prior_manual_import(
        self,
        mock_probe,
        mock_fetch,
        mock_max_rowid,
        mock_library,
        mock_decrypt_task,
        mock_decrypt_importer,
    ):
        """A prior manual TSV import means the first API pull starts fresh, not from 0."""
        ImportRun.objects.create(
            user=self.user,
            source="jellyfin_playback_reporting",
            status=ImportRun.Status.COMPLETED,
        )
        mock_probe.return_value = True
        mock_max_rowid.return_value = 42
        mock_fetch.return_value = []
        mock_library.return_value = []

        pull_jellyfin_history(self.user.id)

        mock_max_rowid.assert_called_once()
        mock_fetch.assert_called_once_with(42, 2000)

    @patch(
        "integrations.imports.jellyfin_playback_reporting.decrypt_or_raise",
        return_value="api-key",
    )
    @patch(
        "integrations.tasks._jellyfin_pull.decrypt_or_raise",
        return_value="api-key",
    )
    @patch("integrations.jellyfin_client.JellyfinClient.probe_playback_reporting")
    def test_auth_error_marks_connection_broken(
        self,
        mock_probe,
        mock_decrypt_task,
        mock_decrypt_importer,
    ):
        from integrations.jellyfin_client import JellyfinAuthError

        mock_probe.side_effect = JellyfinAuthError("bad key")

        with self.assertRaises(JellyfinAuthError):
            pull_jellyfin_history(self.user.id)

        self.account.refresh_from_db()
        self.assertTrue(self.account.connection_broken)
        self.assertIn("bad key", self.account.last_pull_error_message)


@patch(
    "integrations.imports.jellyfin_playback_reporting.decrypt_or_raise",
    return_value="api-key",
)
@patch("integrations.tasks._jellyfin_pull.decrypt_or_raise", return_value="api-key")
class PullJellyfinConnectionHealthTests(TestCase):
    """A transient pull failure must never latch ``connection_broken`` (#1267)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="pull-health-user")
        self.account = JellyfinAccount.objects.create(
            user=self.user,
            base_url="https://jellyfin.example",
            api_key="encrypted",
            jellyfin_user_id="jf-user",
        )

    @patch("integrations.jellyfin_client.JellyfinClient.iter_library_items")
    @patch(
        "integrations.jellyfin_client.JellyfinClient.probe_playback_reporting",
        return_value=False,
    )
    def test_timeout_records_error_without_marking_broken(
        self,
        mock_probe,
        mock_library,
        *mocks,
    ):
        mock_library.side_effect = JellyfinClientError("Read timed out")

        with self.assertRaises(MediaImportError):
            pull_jellyfin_history(self.user.id)

        self.account.refresh_from_db()
        self.assertFalse(self.account.connection_broken)
        self.assertIn("Read timed out", self.account.last_pull_error_message)

    @patch("integrations.jellyfin_client.JellyfinClient.iter_library_items")
    @patch(
        "integrations.jellyfin_client.JellyfinClient.probe_playback_reporting",
        return_value=False,
    )
    @patch("integrations.jellyfin_client.JellyfinClient.healthcheck")
    def test_broken_account_heals_when_probe_succeeds(
        self,
        mock_health,
        mock_probe,
        mock_library,
        *mocks,
    ):
        self.account.connection_broken = True
        self.account.save(update_fields=["connection_broken"])
        mock_health.return_value = {"Id": "server"}
        mock_library.return_value = []

        pull_jellyfin_history(self.user.id)

        self.account.refresh_from_db()
        self.assertFalse(self.account.connection_broken)
        self.assertIsNotNone(self.account.last_pull_at)

    @patch("integrations.jellyfin_client.JellyfinClient.iter_library_items")
    @patch("integrations.jellyfin_client.JellyfinClient.healthcheck")
    def test_broken_account_stays_broken_when_probe_is_rejected(
        self,
        mock_health,
        mock_library,
        *mocks,
    ):
        self.account.connection_broken = True
        self.account.save(update_fields=["connection_broken"])
        mock_health.side_effect = JellyfinAuthError("bad key")

        pull_jellyfin_history(self.user.id)

        mock_library.assert_not_called()
        self.account.refresh_from_db()
        self.assertTrue(self.account.connection_broken)
