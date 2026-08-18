from unittest.mock import patch

from django.test import SimpleTestCase

from app import cache_safety
from integrations.stremio_playback import PlaybackDecision
from integrations.tasks import _media_imports, _webhook


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


class StremioPlaybackTaskTests(SimpleTestCase):
    """Keep Celery concerns separate from playback state decisions."""

    @patch.object(_webhook.verify_stremio_playback, "apply_async")
    @patch.object(_webhook, "_process_webhook")
    @patch("integrations.stremio_playback.start_session")
    def test_start_schedules_only_a_new_guarded_session(
        self, mock_start, mock_process, mock_apply
    ):
        mock_start.return_value = PlaybackDecision("schedule", "session-1", 60)

        _webhook.process_stremio_webhook.run(
            {"id": "tt1", "type": "movie"}, 42
        )

        mock_process.assert_called_once()
        mock_apply.assert_called_once_with(
            args=["session-1"], countdown=60, queue="interactive"
        )

    @patch.object(_webhook.verify_stremio_playback, "apply_async")
    @patch.object(_webhook, "_process_webhook")
    @patch("integrations.stremio_playback.start_session")
    def test_duplicate_start_does_not_schedule_another_verifier(
        self, mock_start, _mock_process, mock_apply
    ):
        mock_start.return_value = PlaybackDecision("duplicate", "session-1")

        _webhook.process_stremio_webhook.run(
            {"id": "tt1", "type": "movie"}, 42
        )

        mock_apply.assert_not_called()

    @patch.object(_webhook.verify_stremio_playback, "apply_async")
    @patch("integrations.stremio_playback.observe_session")
    def test_observer_schedules_a_fresh_task_without_celery_retry(
        self, mock_observe, mock_apply
    ):
        mock_observe.return_value = PlaybackDecision("schedule", "session-1", 90)

        _webhook.verify_stremio_playback.run("session-1")

        mock_apply.assert_called_once_with(
            args=["session-1"], countdown=90, queue="interactive"
        )

    @patch.object(_webhook, "_process_webhook")
    @patch("integrations.stremio_playback.observe_session")
    def test_only_completion_claim_winner_dispatches_movie_or_tv_activity(
        self, mock_observe, mock_process
    ):
        for media_type in ("movie", "series"):
            with self.subTest(media_type=media_type):
                payload = {
                    "id": "tt1" if media_type == "movie" else "tt1:1:1",
                    "type": media_type,
                    "viewedAt": 1,
                    "_floppy_verified_completion": True,
                }
                mock_observe.side_effect = [
                    PlaybackDecision(
                        "complete", "session-1", payload=payload, user_id=42
                    ),
                    PlaybackDecision(
                        "duplicate", "session-1", reason="completion_already_claimed"
                    ),
                ]

                _webhook.verify_stremio_playback.run("session-1")
                _webhook.verify_stremio_playback.run("session-1")

        self.assertEqual(mock_process.call_count, 2)
