import json
import logging
from collections import defaultdict
from datetime import UTC, datetime

from django.apps import apps

import app
import app.providers
from app.models import MediaTypes, Sources, Status
from app.providers.services import ProviderAPIError
from integrations import import_progress
from integrations.imports import helpers
from integrations.imports.helpers import MediaImportError, MediaImportUnexpectedError

logger = logging.getLogger(__name__)

# Priority order (highest first) used to resolve a single status when a game
# sits on more than one of Grouvee's status shelves at once.
SHELF_STATUS_PRIORITY = (
    ("Playing", Status.IN_PROGRESS.value),
    ("Played", Status.COMPLETED.value),
    ("Backlog", Status.PLANNING.value),
    ("Wish List", Status.PLANNING.value),
)


def importer(file, user, mode):
    """Import media from a Grouvee JSON export."""
    grouvee_importer = GrouveeImporter(file, user, mode)
    return grouvee_importer.import_data()


class GrouveeImporter:
    """Class to handle importing user data from a Grouvee JSON export."""

    def __init__(self, file, user, mode):
        """Initialize the importer with file, user, and mode.

        Args:
            file: Uploaded JSON file
            user: Django user object to import data for
            mode (str): Import mode ("new" or "overwrite")
        """
        self.file = file
        self.user = user
        self.mode = mode
        self.warnings = []

        self.existing_media = helpers.get_existing_media(user)
        self.to_delete = defaultdict(lambda: defaultdict(set))
        self.bulk_media = defaultdict(list)

        logger.info(
            "Initialized Grouvee importer for user %s with mode %s",
            user.username,
            mode,
        )

    def import_data(self):
        """Import all games from the Grouvee JSON export."""
        try:
            data = json.loads(self.file.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            msg = "Invalid file format. Please upload a Grouvee JSON export."
            raise MediaImportError(msg) from e

        entries = data.get("collection", [])
        unmatched_titles = []
        total = len(entries)

        for i, entry in enumerate(entries, start=1):
            import_progress.report(i, total, "Grouvee")
            try:
                self._process_entry(entry, unmatched_titles)
            except Exception as error:
                error_msg = f"Error processing entry: {entry.get('name')}"
                raise MediaImportUnexpectedError(error_msg) from error

        if unmatched_titles:
            title_list = helpers.join_with_commas_and(unmatched_titles)
            self.warnings.append(
                f"{title_list}: No IGDB ID in the Grouvee export - none imported",
            )

        helpers.cleanup_existing_media(self.to_delete, self.user)
        helpers.bulk_create_media(self.bulk_media, self.user)

        imported_counts = {
            media_type: len(media_list)
            for media_type, media_list in self.bulk_media.items()
        }

        deduplicated_messages = "\n".join(dict.fromkeys(self.warnings))
        return imported_counts, deduplicated_messages if self.warnings else None

    def _process_entry(self, entry, unmatched_titles):
        """Process a single game entry from the collection."""
        igdb_id = entry.get("igdb_id")
        if not igdb_id:
            unmatched_titles.append(entry.get("name", "Unknown"))
            return

        media_id = str(igdb_id)

        try:
            metadata = app.providers.services.get_media_metadata(
                MediaTypes.GAME.value,
                media_id,
                Sources.IGDB.value,
            )
        except ProviderAPIError as error:
            self.warnings.append(f"{entry.get('name')}: {error}")
            return

        item, _ = app.models.Item.objects.update_or_create(
            media_id=media_id,
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            defaults={
                "title": metadata["title"],
                "image": metadata["image"],
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
            return

        instance = self._create_media_instance(item, entry)
        self.bulk_media[MediaTypes.GAME.value].append(instance)

    def _determine_status(self, entry):
        """Determine media status from Grouvee's shelves, by priority."""
        shelves = entry.get("shelves", {})
        for shelf_name, status in SHELF_STATUS_PRIORITY:
            if shelf_name in shelves:
                return status
        return Status.COMPLETED.value

    def _parse_date(self, date_str):
        """Parse a Grouvee date string, treating the literal "None" as missing."""
        if not date_str or date_str == "None":
            return None
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)

    def _date_range(self, entry):
        """Return earliest start date and latest end date across play sessions."""
        starts = []
        ends = []
        for play in entry.get("dates", []):
            started = self._parse_date(play.get("date_started"))
            if started:
                starts.append(started)
            finished = self._parse_date(play.get("date_finished"))
            if finished:
                ends.append(finished)
        return (min(starts) if starts else None, max(ends) if ends else None)

    def _total_progress_minutes(self, entry):
        """Sum playtime in seconds across all play sessions, converted to minutes."""
        total_seconds = sum(
            play.get("seconds_played") or 0 for play in entry.get("dates", [])
        )
        return total_seconds // 60

    def _create_media_instance(self, item, entry):
        """Create a Game media instance with all parameters."""
        start_date, end_date = self._date_range(entry)
        rating = entry.get("rating")

        model = apps.get_model(app_label="app", model_name=MediaTypes.GAME.value)
        return model(
            item=item,
            user=self.user,
            score=rating * 2 if rating is not None else None,
            progress=self._total_progress_minutes(entry),
            status=self._determine_status(entry),
            start_date=start_date,
            end_date=end_date,
            notes=entry.get("review", ""),
        )
