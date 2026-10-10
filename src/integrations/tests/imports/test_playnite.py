import io
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import Game, Sources, Status
from integrations.imports import playnite
from integrations.imports.helpers import MediaImportError


class PlayniteImporterTests(TestCase):
    """Test importing Playnite library CSV backups."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="playnite-user")
        self.search_patcher = patch("app.providers.services.search")
        self.mock_search = self.search_patcher.start()
        self.addCleanup(self.search_patcher.stop)
        self.mock_search.side_effect = self._search

    @staticmethod
    def _search(_media_type, title, _page, **_kwargs):
        if title == "Unmatched Game":
            return {"results": []}
        return {
            "results": [
                {
                    "media_id": "42",
                    "title": "Matched Game",
                    "image": "cover.jpg",
                },
            ],
        }

    def test_imports_hours_status_and_deduplicates_titles(self):
        csv_data = (
            "Name,CompletionStatus,TimePlayedHours\n"
            "Matched Game,Played,1.5\n"
            "Matched Game,Completed,0.25\n"
            "Planning Game,Plan to Play,0\n"
            "Skipped Game,Not Played,0\n"
            "Unmatched Game,Played,2\n"
        )

        counts, warnings = playnite.importer(
            io.BytesIO(csv_data.encode()),
            self.user,
            "new",
        )

        self.assertEqual(counts["game"], 2)
        matched = Game.objects.get(user=self.user, item__media_id="42")
        self.assertEqual(matched.progress, 90)
        self.assertEqual(matched.status, Status.COMPLETED.value)
        self.assertEqual(
            warnings,
            f"Unmatched Game: Couldn't find a match in {Sources.IGDB.label}; "
            "none imported",
        )

    def test_supports_time_played_seconds_and_bom(self):
        csv_data = "\ufeffName,Completion Status,Time Played\nMatched Game,Beaten,61\n"

        playnite.importer(io.BytesIO(csv_data.encode()), self.user, "new")

        matched = Game.objects.get(user=self.user, item__media_id="42")
        self.assertEqual(matched.progress, 1)
        self.assertEqual(matched.status, Status.COMPLETED.value)

    def test_rejects_csv_without_playtime_column(self):
        csv_data = "Name,Completion Status\nMatched Game,Played\n"

        with self.assertRaises(MediaImportError):
            playnite.importer(io.BytesIO(csv_data.encode()), self.user, "new")
