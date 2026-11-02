import json
import logging
import pickle
import sqlite3
from collections import defaultdict
from contextlib import closing
from csv import DictReader
from decimal import Decimal
from io import TextIOWrapper
from pathlib import Path
from tempfile import TemporaryDirectory, TemporaryFile

from django.apps import apps
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

import app
import app.providers
from app.models import MediaTypes, Sources, Status
from app.providers.services import ProviderAPIError
from integrations import import_progress
from integrations.imports import helpers
from integrations.imports.helpers import MediaImportError, MediaImportUnexpectedError

logger = logging.getLogger(__name__)

# Mapping of IMDB title types to media types
IMDB_TYPE_MAPPING = {
    "Movie": MediaTypes.MOVIE,
    "TV Series": MediaTypes.TV,
    "Short": MediaTypes.MOVIE,
    "TV Mini Series": MediaTypes.TV,
    "TV Movie": MediaTypes.MOVIE,
    "TV Special": MediaTypes.MOVIE,
    "Video": MediaTypes.MOVIE,
}

# IMDB title types we don't support
UNSUPPORTED_TYPES = {
    "TV Episode",
    "TV Short",
    "Video Game",
    "Music Video",
    "Podcast Series",
    "Podcast Episode",
}


def importer(file, user, mode):
    """Import media from IMDB CSV file."""
    imdb_importer = IMDBImporter(file, user, mode)
    return imdb_importer.import_data()


class IMDBImporter:
    """Class to handle importing user data from IMDB CSV."""

    def __init__(self, file, user, mode):
        """Initialize the importer with file, user, and mode.

        Args:
            file: Uploaded CSV file
            user: Django user object to import data for
            mode (str): Import mode ("new" or "overwrite")
        """
        self.file = file
        self.user = user
        self.mode = mode
        self.warnings = []

        # Track bulk creation lists for each media type
        self.bulk_media = defaultdict(list)

        logger.info(
            "Initialized IMDB importer for user %s with mode %s",
            user.username,
            mode,
        )

    def import_data(self):
        """Import all user data from CSV."""
        with TemporaryDirectory(prefix="floppy-imdb-") as directory:  # noqa: SIM117
            with closing(sqlite3.connect(Path(directory) / "rows.sqlite3")) as staging:
                staging.execute(
                    "CREATE TABLE rows (media_id INTEGER, title TEXT, row TEXT, data TEXT)"
                )
                staging.execute("CREATE INDEX media_id_idx ON rows(media_id)")
                wrapper = TextIOWrapper(self.file, encoding="utf-8", newline="")
                try:
                    for row in DictReader(wrapper):
                        try:
                            data = self._process_first_pass(row)
                        except Exception as error:
                            msg = f"Error processing entry: {row}"
                            raise MediaImportUnexpectedError(msg) from error
                        staging.execute(
                            "INSERT INTO rows VALUES (?, ?, ?, ?)",
                            (
                                data["media_id"] if data else None,
                                row.get("Title", "").strip(),
                                json.dumps(row),
                                json.dumps(data),
                            ),
                        )
                except UnicodeDecodeError as error:
                    msg = "Invalid file format. Please upload a CSV file."
                    raise MediaImportError(msg) from error
                finally:
                    wrapper.detach()
                total = staging.execute("SELECT COUNT(*) FROM rows").fetchone()[0]
                # Validate every input row before updating any existing ratings.
                with TemporaryFile() as instances:
                    for index, (raw, data, count) in enumerate(
                        staging.execute(
                            "SELECT r.row, r.data, counts.n FROM rows r "
                            "LEFT JOIN (SELECT media_id, COUNT(*) n FROM rows GROUP BY media_id) counts "
                            "ON counts.media_id=r.media_id ORDER BY r.rowid",
                        ),
                        start=1,
                    ):
                        import_progress.report(index, total, "IMDB")
                        if count != 1:
                            continue
                        row = json.loads(raw)
                        try:
                            self._process_second_pass(row, json.loads(data))
                        except Exception as error:
                            msg = f"Error processing entry: {row}"
                            raise MediaImportUnexpectedError(msg) from error
                        for media_type, batch in self.bulk_media.items():
                            for instance in batch:
                                pickle.dump((media_type, instance), instances)
                        self.bulk_media.clear()
                    for (media_id,) in staging.execute(
                        "SELECT media_id FROM rows WHERE media_id IS NOT NULL GROUP BY media_id HAVING COUNT(*) > 1 ORDER BY MIN(rowid)",
                    ):
                        titles = [
                            row[0]
                            for row in staging.execute(
                                "SELECT title FROM rows WHERE media_id=? ORDER BY rowid",
                                (media_id,),
                            )
                        ]
                        self._add_duplicate_warnings(
                            {media_id: len(titles)}, {media_id: titles}
                        )
                    counts = defaultdict(int)
                    instances.seek(0)
                    with transaction.atomic():
                        while True:
                            try:
                                # Only instances written above are deserialized.
                                media_type, instance = pickle.load(instances)  # noqa: S301
                            except EOFError:
                                break
                            self.bulk_media[media_type].append(instance)
                            counts[media_type] += 1
                            if sum(map(len, self.bulk_media.values())) >= 250:  # noqa: PLR2004
                                self._flush()
                        self._flush()
        messages = "\n".join(dict.fromkeys(self.warnings))
        return dict(counts), messages if self.warnings else None

    def _flush(self):
        """Persist one bounded batch without replacing existing watch history."""
        if self.mode == "overwrite":
            self._update_existing_ratings()
        helpers.bulk_create_media(self.bulk_media, self.user)
        self.bulk_media.clear()

    def _update_existing_ratings(self):
        """Update only scores on existing titles, keeping all tracking rows.

        A film can have several watch rows. Prefer its existing statusless
        rating row when available, otherwise the newest tracking row.
        Unrated IMDb rows do not remove a previously recorded score or status.
        """
        for media_type, batch in self.bulk_media.items():
            if not batch:
                continue

            model = apps.get_model(app_label="app", model_name=media_type)
            existing_by_item = {}
            existing_rows = model.objects.filter(
                user=self.user,
                item_id__in={instance.item_id for instance in batch},
            ).order_by("-created_at", "-pk")
            for current in existing_rows:
                previous = existing_by_item.get(current.item_id)
                if previous is None or (
                    current.status is None and previous.status is not None
                ):
                    existing_by_item[current.item_id] = current

            to_create = []
            for instance in batch:
                current = existing_by_item.get(instance.item_id)
                if current is None:
                    to_create.append(instance)
                    continue
                if instance.score is None:
                    continue
                score = Decimal(str(instance.score))
                if current.score != score:
                    current.score = score
                    current._history_date = instance._history_date
                    current._change_reason = "IMDb rating import"
                    current.save(update_fields=["score", "scored_at"])

            self.bulk_media[media_type] = to_create

    def _process_first_pass(self, row):
        """First pass to identify duplicate entries and validate data."""
        imdb_id = self._extract_imdb_id(row)

        title = row.get("Title", "").strip()

        if not imdb_id:
            self.warnings.append(f"{title}: Invalid or missing IMDB ID")
            return None

        title_type = row.get("Title Type", "").strip()

        if not self._is_supported_type(title_type):
            if title_type in UNSUPPORTED_TYPES:
                self.warnings.append(
                    f"{title}: Unsupported title type '{title_type}' - skipped",
                )
            else:
                self.warnings.append(
                    f"{title}: Unknown title type '{title_type}' - skipped",
                )
            return None

        tmdb_data = self._lookup_in_tmdb(imdb_id, title_type)

        if not tmdb_data:
            self.warnings.append(
                f"{title}: Couldn't find a match in {Sources.TMDB.label}",
            )
            return None

        return tmdb_data

    def _process_second_pass(self, row, tmdb_data):
        """Validate an already resolved, unique entry for disk staging."""
        media_id = tmdb_data["media_id"]
        title_type = row.get("Title Type", "").strip()

        media_type = IMDB_TYPE_MAPPING[title_type]

        model = apps.get_model(app_label="app", model_name=media_type)
        if (
            self.mode == "new"
            and model.objects.filter(
                user=self.user,
                item__source=Sources.TMDB.value,
                item__media_id=str(media_id),
            ).exists()
        ):
            return

        item, _ = self._create_or_update_item(tmdb_data, media_type)
        instance = self._create_media_instance(item, row, media_type)
        self.bulk_media[media_type].append(instance)

    def _add_duplicate_warnings(self, media_id_counts, media_id_titles):
        """Add warnings for duplicate entries."""
        for media_id, count in media_id_counts.items():
            if count > 1:
                titles = media_id_titles[media_id]
                title_list = helpers.join_with_commas_and(titles)
                self.warnings.append(
                    f"{title_list}: They were matched to the same TMDB ID {media_id} "
                    "- none imported",
                )

    def _extract_imdb_id(self, row):
        """Extract and clean IMDB ID from row."""
        imdb_id: str = row.get("Const", "").strip()

        if not imdb_id:
            return None

        if imdb_id.startswith("tt"):
            return imdb_id

        # Add 'tt' prefix if not present, TMDB find expects it
        if imdb_id.isdigit():
            return f"tt{imdb_id}"

        return None

    def _is_supported_type(self, title_type):
        """Check if the title type is supported."""
        return title_type in IMDB_TYPE_MAPPING

    def _lookup_in_tmdb(self, imdb_id, title_type):
        """Look up media in TMDB using IMDB ID."""
        try:
            response = app.providers.tmdb.find(imdb_id, "imdb_id")
        except ProviderAPIError as e:
            logger.warning("Error looking up IMDB ID %s in TMDB: %s", imdb_id, e)
            return None

        media_type = IMDB_TYPE_MAPPING.get(title_type, "")

        if media_type == MediaTypes.MOVIE.value and response.get("movie_results"):
            movie = response["movie_results"][0]
            return {
                "media_id": movie["id"],
                "title": movie["title"],
                "image": app.providers.tmdb.get_image_url(movie["poster_path"]),
                "media_type": MediaTypes.MOVIE.value,
            }

        if media_type == MediaTypes.TV.value and response.get("tv_results"):
            tv_show = response["tv_results"][0]
            return {
                "media_id": tv_show["id"],
                "title": tv_show["name"],
                "image": app.providers.tmdb.get_image_url(tv_show["poster_path"]),
                "media_type": MediaTypes.TV.value,
            }

        return None

    def _create_or_update_item(self, tmdb_data, media_type):
        """Create or update the item in database."""
        return app.models.Item.objects.update_or_create(
            media_id=tmdb_data["media_id"],
            source=Sources.TMDB.value,
            media_type=media_type,
            defaults={
                "title": tmdb_data["title"],
                "image": tmdb_data["image"],
            },
        )

    def _create_media_instance(self, item, row, media_type):
        """Create media instance with all parameters."""
        model = apps.get_model(app_label="app", model_name=media_type)

        # Parse user rating (0-10 scale)
        rating = self._parse_rating(row.get("Your Rating", ""))

        # A rating never establishes a watch or completion date.
        # Preserve the existing watchlist behaviour for unrated entries.
        status = None if rating is not None else Status.PLANNING.value

        params = {
            "item": item,
            "user": self.user,
            "score": rating,
            "status": status,
        }

        # Parse dates
        date_created = self._parse_date(row.get("Created", ""))
        date_modified = self._parse_date(row.get("Modified", ""))
        date_rated = self._parse_date(row.get("Date Rated", ""))

        # filter out None dates
        dates = [date_created, date_modified, date_rated]
        most_recent_date = max((date for date in dates if date), default=None)

        instance = model(**params)
        instance._history_date = most_recent_date or timezone.now()

        return instance

    def _parse_rating(self, rating_str):
        """Parse user rating from string to decimal."""
        if not rating_str or rating_str.strip() == "":
            return None

        try:
            rating = float(rating_str.strip())
            # IMDB ratings are 1-10, ensure it's in valid range
            min_rating = 1
            max_rating = 10
            if min_rating <= rating <= max_rating:
                return rating
        except (ValueError, TypeError):
            pass

        return None

    def _parse_date(self, date_str):
        """
        Parse date string into datetime object.

        IMDB exports dates in YYYY-MM-DD format.
        """
        date_str = date_str.strip()

        if not date_str:
            return None

        date = parse_datetime(date_str)

        if not date:
            logger.warning("Could not parse date: %s", date_str)
            return None

        return date.replace(
            hour=0,
            minute=0,
            second=0,
            tzinfo=timezone.get_current_timezone(),
        )
