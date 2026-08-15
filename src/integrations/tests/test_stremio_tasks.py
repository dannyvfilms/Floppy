from unittest.mock import patch

from django.test import SimpleTestCase

from app import cache_safety
from integrations.tasks import _media_imports


class StremioImportTaskTests(SimpleTestCase):
    """Verify per-user import serialization without touching provider APIs."""

    @patch.object(_media_imports.cache_safety, "acquire_lock", return_value=False)
    def test_manual_import_skips_when_user_lock_is_held(self, mock_acquire):
        """A second manual import does not overlap the first one."""
        result = _media_imports.import_stremio(42, "new")

        self.assertEqual(result, "Skipped: Stremio import already in progress")
        mock_acquire.assert_called_once_with(
            "stremio_import_lock_42",
            timeout=_media_imports.STREMIO_IMPORT_TIME_LIMIT,
            on_error=cache_safety.ON_ERROR_PROCEED,
            value=mock_acquire.call_args.kwargs["value"],
        )

    @patch.object(_media_imports.cache_safety, "release_lock")
    @patch.object(_media_imports.cache_safety, "acquire_lock", return_value=True)
    @patch.object(_media_imports, "import_media", return_value="imported")
    def test_manual_import_releases_lock_after_import(
        self,
        mock_import,
        mock_acquire,
        mock_release,
    ):
        """The lock is released even when import work is mocked as successful."""
        result = _media_imports.import_stremio(42, "overwrite")

        self.assertEqual(result, "imported")
        mock_import.assert_called_once_with(
            _media_imports.stremio.importer,
            None,
            42,
            "overwrite",
        )
        mock_acquire.assert_called_once()
        mock_release.assert_called_once_with("stremio_import_lock_42")
