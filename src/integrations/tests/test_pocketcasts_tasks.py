from unittest.mock import patch

from django.test import SimpleTestCase

from integrations.tasks import _media_imports


class PocketCastsRecurringTaskTests(SimpleTestCase):
    """Queued copies of the recurring poll must not each run a full import."""

    @patch.object(_media_imports, "import_media")
    @patch.object(_media_imports.cache_safety, "acquire_lock")
    def test_recent_run_skips_before_taking_the_import_lock(
        self, mock_acquire, mock_import
    ):
        mock_acquire.return_value = False

        result = _media_imports.import_pocketcasts_history(7)

        self.assertEqual(result, "Skipped: recent import")
        mock_import.assert_not_called()
        mock_acquire.assert_called_once()
        self.assertEqual(
            mock_acquire.call_args.args[0], "pocketcasts_recurring_cooldown_7"
        )

    @patch.object(_media_imports.cache_safety, "release_lock")
    @patch.object(_media_imports, "import_media", return_value="imported")
    @patch.object(_media_imports.cache_safety, "acquire_lock", return_value=True)
    def test_first_copy_imports_and_releases_only_the_lock(
        self, mock_acquire, mock_import, mock_release
    ):
        self.assertEqual(_media_imports.import_pocketcasts_history(7), "imported")

        mock_release.assert_called_once_with("pocketcasts_import_lock_7")

    @patch.object(_media_imports, "import_media")
    @patch.object(_media_imports.cache_safety, "acquire_lock", return_value=True)
    def test_manual_import_ignores_the_cooldown(self, mock_acquire, mock_import):
        _media_imports.import_pocketcasts(7)

        keys = [call.args[0] for call in mock_acquire.call_args_list]
        self.assertEqual(keys, ["pocketcasts_import_lock_7"])
