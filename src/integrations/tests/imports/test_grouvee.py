from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import (
    Game,
    Status,
)
from integrations.imports import (
    grouvee,
)

mock_path = Path(__file__).resolve().parent.parent / "mock_data"

GAME_METADATA = {
    "1227": {"title": "Dragon Warrior I & II", "image": ""},
    "128167": {"title": "RoboCop: Rogue City", "image": ""},
    "5001": {"title": "Retro Backlog Game", "image": ""},
}


def _fake_get_media_metadata(media_type, media_id, source):
    return GAME_METADATA[media_id]


class ImportGrouvee(TestCase):
    """Test importing media from a Grouvee JSON export."""

    def setUp(self):
        """Create user and import the mock Grouvee export."""
        self.metadata_patcher = patch(
            "app.providers.services.get_media_metadata",
            side_effect=_fake_get_media_metadata,
        )
        self.mock_metadata = self.metadata_patcher.start()
        self.addCleanup(self.metadata_patcher.stop)

        self.credentials = {"username": "test", "password": "***"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        with Path(mock_path / "import_grouvee.json").open("rb") as file:
            self.imported_counts, self.warnings = grouvee.importer(
                file,
                self.user,
                "new",
            )

    def test_import_counts(self):
        """Games with an IGDB ID are imported; the unmatched one is skipped."""
        self.assertEqual(Game.objects.filter(user=self.user).count(), 3)

    def test_missing_igdb_id_warning(self):
        """A game without an igdb_id produces a warning and is not imported."""
        self.assertIsNotNone(self.warnings)
        self.assertIn("No IGDB Match Game", self.warnings)
        self.assertFalse(
            Game.objects.filter(user=self.user, item__media_id="9999").exists(),
        )

    def test_played_shelf_maps_to_completed(self):
        """A game only on the Played shelf is marked Completed."""
        game = Game.objects.get(user=self.user, item__media_id="1227")
        self.assertEqual(game.status, Status.COMPLETED.value)
        self.assertEqual(game.score, 6)
        self.assertEqual(game.progress, 60)

    def test_playing_shelf_maps_to_in_progress(self):
        """A game on the Playing shelf is marked In Progress."""
        game = Game.objects.get(user=self.user, item__media_id="128167")
        self.assertEqual(game.status, Status.IN_PROGRESS.value)
        self.assertIsNone(game.score)

    def test_backlog_shelf_ignores_custom_shelf(self):
        """A game on Backlog plus a custom shelf is marked Planning."""
        game = Game.objects.get(user=self.user, item__media_id="5001")
        self.assertEqual(game.status, Status.PLANNING.value)

    def test_overwrite_mode_replaces_existing(self):
        """Re-importing in overwrite mode replaces existing games."""
        with Path(mock_path / "import_grouvee.json").open("rb") as file:
            grouvee.importer(file, self.user, "overwrite")

        self.assertEqual(Game.objects.filter(user=self.user).count(), 3)

    def test_new_mode_skips_existing(self):
        """Re-importing in new mode does not duplicate existing games."""
        with Path(mock_path / "import_grouvee.json").open("rb") as file:
            imported_counts, _ = grouvee.importer(file, self.user, "new")

        self.assertNotIn("game", imported_counts)
        self.assertEqual(Game.objects.filter(user=self.user).count(), 3)
