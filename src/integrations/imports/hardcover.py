import logging
from collections import defaultdict
from csv import DictReader
from datetime import datetime

from django.apps import apps
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

import app
from app.models import MediaTypes, Sources, Status
from app.providers import hardcover as hardcover_provider
from app.providers import services
from app.services.synced_status import keep_held_status
from integrations import import_progress
from integrations.imports import helpers
from integrations.imports.helpers import MediaImportError, MediaImportUnexpectedError

logger = logging.getLogger(__name__)

RATING_HALF_SCALE_MAX = 5
ENTRY_SOURCE = "hardcover"
# Hardcover's user_books.status_id; 6 (Ignored) is deliberately not tracked.
STATUS_BY_ID = {
    1: Status.PLANNING.value,
    2: Status.IN_PROGRESS.value,
    3: Status.COMPLETED.value,
    4: Status.PAUSED.value,
    5: Status.DROPPED.value,
}


def importer(file, user, mode):
    """Import media from CSV file using the class-based importer."""
    csv_importer = HardcoverImporter(file, user, mode)
    return csv_importer.import_data()


def sync_importer(identifier, user, mode):
    """Sync the user's Hardcover library through Hardcover's official API."""
    return HardcoverAccountSync(user, mode).import_data()


class HardcoverImporter:
    """Class to handle importing Hardcover data from CSV files."""

    def __init__(self, file, user, mode):
        """Initialize the importer with file, user, and mode."""
        self.file = file
        self.user = user
        self.mode = mode
        self.warnings = []

        # Track existing media for "new" mode
        self.existing_media = helpers.get_existing_media(user)

        # Track media IDs to delete in overwrite mode
        self.to_delete = defaultdict(lambda: defaultdict(set))

        # Track bulk creation lists for each media type
        self.bulk_media = defaultdict(list)

        logger.info(
            "Initialized Hardcover CSV importer for user %s with mode %s",
            user.username,
            mode,
        )

    def import_data(self):
        """Import all Hardcover data from the CSV file."""
        try:
            decoded_file = self.file.read().decode("utf-8").splitlines()
        except UnicodeDecodeError as e:
            msg = "Invalid file format. Please upload a CSV file."
            raise MediaImportError(msg) from e

        rows = list(DictReader(decoded_file))
        total = len(rows)

        for i, row in enumerate(rows, start=1):
            import_progress.report(i, total, "Hardcover")
            try:
                self._process_row(row)
            except services.ProviderAPIError:
                error_msg = f"Error processing entry with ID {row.get('Hardcover Book ID', '')} "
                self.warnings.append(error_msg)
                continue
            except Exception as error:
                error_msg = f"Error processing entry: {row}"
                raise MediaImportUnexpectedError(error_msg) from error

        helpers.cleanup_existing_media(self.to_delete, self.user)
        helpers.bulk_create_media(self.bulk_media, self.user)

        imported_counts = {
            media_type: len(media_list)
            for media_type, media_list in self.bulk_media.items()
        }

        deduplicated_messages = "\n".join(dict.fromkeys(self.warnings))
        return imported_counts, deduplicated_messages

    def _process_row(self, row):
        """Process a single row from the CSV file."""
        default_source = Sources.HARDCOVER
        book = self._resolve_book(row, default_source)

        if not book:
            title = row.get("Title") or "Unknown title"
            self.warnings.append(
                f"{title}: Couldn't find this book via Hardcover ID, ISBN13, or title in "
                f"{default_source.label}",
            )
            return

        media_id = str(book["media_id"])

        item, _ = self._create_or_update_item(book)

        # Check if we should process this entry based on mode
        if not helpers.should_process_media(
            self.existing_media,
            self.to_delete,
            MediaTypes.BOOK.value,
            default_source.value,
            media_id,
            self.mode,
        ):
            return

        instance = self._create_media_instance(item, row)
        self.bulk_media[MediaTypes.BOOK.value].append(instance)

    def _resolve_book(self, row, source):
        """Resolve a book entry using Hardcover ID, ISBN, or title search."""
        hardcover_book_id = (row.get("Hardcover Book ID") or "").strip()
        if hardcover_book_id.isdigit():
            try:
                metadata = services.get_media_metadata(
                    MediaTypes.BOOK.value,
                    hardcover_book_id,
                    source.value,
                )
                return {
                    "media_id": metadata["media_id"],
                    "title": metadata["title"],
                    "image": metadata["image"],
                }
            except services.ProviderAPIError:
                logger.warning(
                    "Hardcover book lookup failed for ID %s, falling back to search",
                    hardcover_book_id,
                )

        isbn = self._normalize_isbn(row.get("ISBN 13"))
        if isbn:
            results = services.search(
                MediaTypes.BOOK.value,
                isbn,
                1,
                source.value,
            ).get(
                "results",
                [],
            )
            if results:
                return results[0]

        title = (row.get("Title") or "").strip()
        author = (row.get("Author") or "").strip()
        if title:
            query = f"{title} {author}".strip() if author else title
            results = services.search(
                MediaTypes.BOOK.value,
                query,
                1,
                source.value,
            ).get(
                "results",
                [],
            )
            if results:
                return results[0]

        return None

    def _normalize_isbn(self, value):
        """Normalize ISBN values from CSV."""
        if not value:
            return ""
        isbn = str(value).strip()
        if not isbn:
            return ""
        if isbn.startswith("="):
            isbn = isbn.lstrip("=")
        return isbn.strip("\"' ").replace("-", "")

    def _create_or_update_item(self, book):
        """Create or update the item in database."""
        media_type = MediaTypes.BOOK.value
        return app.models.Item.objects.update_or_create(
            media_id=book["media_id"],
            source=Sources.HARDCOVER.value,
            media_type=media_type,
            defaults={
                **app.models.Item.title_fields_from_metadata(
                    book,
                    fallback_title=book["title"],
                ),
                "image": book["image"],
            },
        )

    def _determine_status(self, raw_status):
        """Map Hardcover status strings to Status values."""
        status_value = (raw_status or "").strip().lower()

        status_mapping = {
            "want to read": Status.PLANNING.value,
            "currently reading": Status.IN_PROGRESS.value,
            "read": Status.COMPLETED.value,
            "paused": Status.PAUSED.value,
            "did not finish": Status.DROPPED.value,
        }

        return status_mapping.get(status_value, Status.PLANNING.value)

    def _parse_hardcover_date(self, date_str):
        """Parse Hardcover date string (YYYY-MM-DD or list) into datetime."""
        if not date_str:
            return None

        parts = [part.strip() for part in str(date_str).split(",") if part.strip()]
        if not parts:
            return None

        parsed = parse_date(parts[-1])
        if not parsed:
            return None

        return datetime.combine(parsed, datetime.min.time()).replace(
            tzinfo=timezone.get_current_timezone(),
        )

    def _parse_rating(self, rating_str):
        """Parse rating into 0-10 scale."""
        if rating_str is None:
            return None
        rating_str = str(rating_str).strip()
        if rating_str == "":
            return None
        try:
            rating = float(rating_str)
        except (ValueError, TypeError):
            return None

        if rating <= 0:
            return None
        if rating <= RATING_HALF_SCALE_MAX:
            return round(rating * 2, 1)
        return min(rating, 10)

    def _create_media_instance(self, item, row):
        """Create media instance with all parameters."""
        model = apps.get_model(app_label="app", model_name=MediaTypes.BOOK.value)
        book_status = self._determine_status(row.get("Status"))

        pages = (row.get("Pages") or "").strip()
        if pages.isdigit() and book_status == Status.COMPLETED.value:
            book_progress = int(pages)
        else:
            book_progress = 0

        date_added = self._parse_hardcover_date(row.get("Date Added"))
        date_started = self._parse_hardcover_date(row.get("Date Started"))
        date_finished = self._parse_hardcover_date(row.get("Date Finished"))

        notes = (row.get("Private Notes") or "").strip()
        if not notes:
            notes = (row.get("Review") or "").strip()

        dates = [date_added, date_started, date_finished]
        most_recent_date = max((date for date in dates if date), default=None)

        instance = model(
            item=item,
            user=self.user,
            score=self._parse_rating(row.get("Rating")),
            progress=book_progress,
            status=book_status,
            start_date=date_started,
            end_date=date_finished,
            notes=notes,
        )
        instance._history_date = most_recent_date or timezone.now()

        return instance


class HardcoverAccountSync(HardcoverImporter):
    """Keep books in step with the user's Hardcover library (official API).

    Books Floppy doesn't track yet are always added. Books it already tracks
    change only in "overwrite" mode, where Hardcover wins for status, rating,
    dates and progress, except that a Paused, Dropped or Completed status chosen
    in Floppy stays until Hardcover shows later activity (``keep_held_status``).
    Notes are only written when an entry is first created. Nothing is deleted.
    """

    def __init__(self, user, mode="new"):
        """Initialize the sync for one user and import mode."""
        super().__init__(None, user, mode)

    def import_data(self):
        """Fetch the Hardcover library and write every changed entry."""
        try:
            entries = hardcover_provider.fetch_user_books(self.user)
        except services.ProviderAPIError as error:
            msg = f"Could not read your Hardcover library: {error}"
            raise MediaImportError(msg) from error

        counts = defaultdict(int)
        total = len(entries)
        for i, entry in enumerate(entries, start=1):
            import_progress.report(i, total, "Hardcover")
            try:
                self._sync_entry(entry, counts)
            except services.ProviderAPIError:
                self.warnings.append(
                    f"Couldn't load Hardcover book {entry.get('book_id')}",
                )
                counts["skipped"] += 1
        return dict(counts), "\n".join(dict.fromkeys(self.warnings))

    def _sync_entry(self, entry, counts):
        """Write one Hardcover library entry, counting the outcome."""
        status = STATUS_BY_ID.get(entry.get("status_id"))
        book_id = entry.get("book_id")
        if status is None or not book_id:
            return

        item = self._item_for(str(book_id))
        if item is None:
            self.warnings.append(f"Couldn't load Hardcover book {book_id}")
            counts["skipped"] += 1
            return

        model = app.models.Book
        existing = model.objects.filter(user=self.user, item=item).first()
        if existing and self.mode != "overwrite":
            counts["unchanged"] += 1
            return
        defaults = keep_held_status(
            existing,
            self._entry_defaults(entry, status, existing),
            parse_datetime(entry.get("updated_at") or ""),
        )
        if existing and all(
            getattr(existing, field) == value for field, value in defaults.items()
        ):
            counts["unchanged"] += 1
            return

        notes = (entry.get("review_raw") or entry.get("private_notes") or "").strip()
        model.objects.update_or_create(
            user=self.user,
            item=item,
            defaults=defaults,
            create_defaults={**defaults, "notes": notes, "entry_source": ENTRY_SOURCE},
        )
        counts[MediaTypes.BOOK.value] += 1
        counts["updated" if existing else "created"] += 1

    def _item_for(self, book_id):
        """Return the Hardcover book item, loading its metadata when new."""
        item = app.models.Item.objects.filter(
            source=Sources.HARDCOVER.value,
            media_type=MediaTypes.BOOK.value,
            media_id=book_id,
        ).first()
        if item:
            return item
        book = self._resolve_book({"Hardcover Book ID": book_id}, Sources.HARDCOVER)
        return self._create_or_update_item(book)[0] if book else None

    def _entry_defaults(self, entry, status, existing):
        """Work out the tracking fields Hardcover implies for one entry."""
        reads = entry.get("user_book_reads") or []
        held_progress = existing.progress if existing else 0
        if status == Status.COMPLETED.value:
            pages = int((entry.get("book") or {}).get("pages") or 0)
            progress = pages or held_progress
            end_date = self._parse_hardcover_date(entry.get("last_read_date")) or (
                existing.end_date if existing else None
            )
        else:
            read_pages = [
                read["progress_pages"]
                for read in reads
                if read.get("progress_pages")
            ]
            progress = int(read_pages[-1]) if read_pages else held_progress
            end_date = None

        started = [
            self._parse_hardcover_date(read.get("started_at")) for read in reads
        ]
        start_date = self._parse_hardcover_date(
            entry.get("first_started_reading_date"),
        ) or min((date for date in started if date), default=None)

        defaults = {
            "status": status,
            "progress": progress,
            "start_date": start_date or (existing.start_date if existing else None),
            "end_date": end_date,
        }
        score = self._parse_rating(entry.get("rating"))
        if score is not None:
            defaults["score"] = score
        return defaults
