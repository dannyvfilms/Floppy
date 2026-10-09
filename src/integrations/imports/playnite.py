"""Import Playnite library CSV backups as Floppy game media."""

import csv
import io
import logging
import re
from collections import defaultdict

from django.db.models import F

import app
import app.providers
from app.models import MediaTypes, Sources, Status
from integrations import import_progress
from integrations.imports import helpers
from integrations.imports.helpers import MediaImportError, MediaImportUnexpectedError
from integrations.models import ImportRun

logger = logging.getLogger(__name__)

STATUS_MAP = {
    "played": Status.IN_PROGRESS.value,
    "beaten": Status.COMPLETED.value,
    "completed": Status.COMPLETED.value,
    "abandoned": Status.DROPPED.value,
    "on hold": Status.PAUSED.value,
    "plan to play": Status.PLANNING.value,
}
STATUS_PRIORITY = {
    Status.PLANNING.value: 1,
    Status.PAUSED.value: 2,
    Status.IN_PROGRESS.value: 3,
    Status.DROPPED.value: 4,
    Status.COMPLETED.value: 5,
}


def importer(file, user, mode):
    """Import games from a Playnite library CSV backup."""
    return PlayniteImporter(file, user, mode).import_data()


class PlayniteImporter:
    """Import Playnite's supported library CSV variants."""

    def __init__(self, file, user, mode):
        """Store the uploaded file and import settings."""
        self.file = file
        self.user = user
        self.mode = mode
        self.warnings = []
        self.existing_media = helpers.get_existing_media(user)
        self.to_delete = defaultdict(lambda: defaultdict(set))
        self.bulk_media = defaultdict(list)
        self.run_counts = {"created": 0, "skipped": 0, "failed": 0}

    def import_data(self):
        """Parse, match, and bulk-create the Playnite library."""
        rows = self._read_rows()
        games = self._consolidate(rows)
        unmatched = []

        for index, game in enumerate(games.values(), start=1):
            import_progress.report(index, len(games), "Playnite")
            try:
                self._process_game(game, unmatched)
            except Exception as error:
                self._increment_run_count("failed")
                message = f"Error processing Playnite entry: {game['name']}"
                raise MediaImportUnexpectedError(message) from error

        if unmatched:
            self.warnings.append(
                f"{helpers.join_with_commas_and(unmatched)}: "
                f"Couldn't find a match in {Sources.IGDB.label}; none imported",
            )

        helpers.cleanup_existing_media(self.to_delete, self.user)
        helpers.bulk_create_media(self.bulk_media, self.user)
        imported_counts = {
            media_type: len(media_list)
            for media_type, media_list in self.bulk_media.items()
        }
        imported_counts.update(self.run_counts)
        warning_text = "\n".join(dict.fromkeys(self.warnings))
        return imported_counts, warning_text or None

    def _read_rows(self):
        """Read Playnite CSV rows and validate its required columns."""
        try:
            raw = self.file.read().decode("utf-8-sig")
        except UnicodeDecodeError as error:
            message = "Invalid Playnite CSV file."
            raise MediaImportError(message) from error

        reader = csv.DictReader(io.StringIO(raw))
        headers = set(reader.fieldnames or ())
        if "Name" not in headers:
            message = "Playnite CSV must contain a Name column."
            raise MediaImportError(message)
        if not ({"TimePlayedHours", "Time Played"} & headers):
            message = "Playnite CSV must contain TimePlayedHours or Time Played."
            raise MediaImportError(message)
        return list(reader)

    def _consolidate(self, rows):
        """Merge duplicate store entries while preserving useful status data."""
        games = {}
        for row in rows:
            name = (row.get("Name") or "").strip()
            if not name:
                continue
            seconds = self._seconds(row)
            status = STATUS_MAP.get(self._status(row))
            if seconds == 0 and status != Status.PLANNING.value:
                continue
            key = self._normalize(name)
            game = games.setdefault(
                key,
                {"name": name, "seconds": 0, "status": None},
            )
            game["seconds"] = max(game["seconds"], seconds)
            if STATUS_PRIORITY.get(status, 0) > STATUS_PRIORITY.get(
                game["status"],
                0,
            ):
                game["status"] = status
        return games

    def _process_game(self, game, unmatched):
        """Resolve one consolidated Playnite title and stage its media row."""
        results = app.providers.services.search(
            MediaTypes.GAME.value,
            game["name"],
            1,
            user=self.user,
        ).get("results", [])
        if not results:
            unmatched.append(game["name"])
            self._increment_run_count("skipped")
            return

        match = results[0]
        media_id = str(match["media_id"])
        item, _ = app.models.Item.objects.update_or_create(
            media_id=media_id,
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            defaults={
                "title": match["title"],
                "image": match.get("image", ""),
            },
        )
        if not helpers.should_process_media(
            self.existing_media,
            self.to_delete,
            MediaTypes.GAME.value,
            Sources.IGDB.value,
            media_id,
            self.mode,
        ):
            self._increment_run_count("skipped")
            return

        model = app.models.Game
        self.bulk_media[MediaTypes.GAME.value].append(
            model(
                item=item,
                user=self.user,
                status=game["status"] or Status.PLANNING.value,
                progress=self._minutes(game["seconds"]),
            ),
        )
        self._increment_run_count("created")

    def _increment_run_count(self, field):
        """Update live ImportRun counters while Playnite is being processed."""
        self.run_counts[field] += 1
        import_run_id = import_progress.get_current_import_run_id()
        if import_run_id is not None:
            ImportRun.objects.filter(id=import_run_id).update(
                **{f"{field}_count": F(f"{field}_count") + 1},
            )

    @staticmethod
    def _status(row):
        return (
            row.get("Completion Status", row.get("CompletionStatus", ""))
            or ""
        ).strip().lower()

    @staticmethod
    def _seconds(row):
        if "TimePlayedHours" in row:
            value = (row.get("TimePlayedHours") or "0").strip().replace(",", ".")
            try:
                return max(0, round(float(value or 0) * 3600))
            except ValueError as error:
                message = "Playnite playtime is invalid."
                raise MediaImportError(message) from error
        value = (row.get("Time Played") or "0").strip()
        try:
            return max(0, int(value or 0))
        except ValueError as error:
            message = "Playnite playtime is invalid."
            raise MediaImportError(message) from error

    @staticmethod
    def _minutes(seconds):
        return max(1, round(seconds / 60)) if seconds > 0 else 0

    @staticmethod
    def _normalize(name):
        normalized = re.sub(r"[\W_]+", " ", name.casefold()).strip()
        return " ".join(normalized.split())
