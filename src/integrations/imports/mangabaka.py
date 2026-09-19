"""Import a MangaBaka library.

Unlike every other provider-backed importer, this one has no public read path.
MangaBaka does expose `GET /series/...` anonymously, but a user's library is
only reachable through `GET /v1/my/library`, which requires a Personal Access
Token (`mb-...`). There is no way to read someone else's library: the public
profile pages at /u/<name> are rendered HTML, and no `/users/<name>` API
endpoint exists (every shape of it 404s).

So the token *is* the credential, and there is nothing to import without one.
That also makes this importer the only one that owns no upstream identifier of
its own -- it reads the library the user already curated on MangaBaka, keyed by
MangaBaka series ids.

MangaBaka's own importer (from AniList/MAL/MangaUpdates/Mihon) is a separate
one-way door on their side; this module never calls it.
"""

import logging
from collections import defaultdict

import requests
from django.apps import apps
from django.utils import timezone

import app
import app.providers.mangabaka
from app.models import Item, MediaTypes, Sources, Status
from app.providers import services
from integrations import import_progress
from integrations.imports import helpers
from integrations.imports.helpers import MediaImportError, MediaImportUnexpectedError

logger = logging.getLogger(__name__)

# MangaBaka caps `limit` at 100 and 400s above it.
PAGE_SIZE = 100
# Belt-and-braces bound on pagination: the largest sampled library is ~1k
# entries, so ten thousand is far past any real account and only exists to stop
# a malformed `next` from looping forever.
MAX_PAGES = 100

# MangaBaka's seven entry states onto Floppy's five. "considering" and
# "plan_to_read" are both "not started" in its model, and "rereading" is still
# an in-progress read.
STATE_STATUS = {
    "reading": Status.IN_PROGRESS.value,
    "rereading": Status.IN_PROGRESS.value,
    "completed": Status.COMPLETED.value,
    "paused": Status.PAUSED.value,
    "dropped": Status.DROPPED.value,
    "considering": Status.PLANNING.value,
    "plan_to_read": Status.PLANNING.value,
}

# MangaBaka rates out of 100; Floppy's score field is 0-10 with one decimal.
RATING_DIVISOR = 10


def _int_or_zero(value):
    """Coerce MangaBaka's string counts ("82") into an int, defaulting to 0."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def importer(token, user, mode):
    """Import manga from a MangaBaka library."""
    mangabaka_importer = MangaBakaImporter(token, user, mode)
    return mangabaka_importer.import_data()


class MangaBakaImporter:
    """Class to handle importing user data from MangaBaka."""

    def __init__(self, token, user, mode):
        """Initialize the importer with token, user, and mode.

        Args:
            token (str): Encrypted MangaBaka Personal Access Token.
            user: Django user object to import data for.
            mode (str): Import mode ("new" or "overwrite").
        """
        self.token = helpers.decrypt_or_raise(token) if token else None
        if not self.token:
            msg = "A MangaBaka API token is required to import a library."
            raise MediaImportError(msg)

        self.user = user
        self.mode = mode
        self.warnings = []
        self._progress_total = None
        self._progress_current = 0

        # Track existing media for "new" mode
        self.existing_media = helpers.get_existing_media(user)
        self.deleted_media = helpers.get_deleted_media(user)

        # Track media IDs to delete in overwrite mode
        self.to_delete = defaultdict(lambda: defaultdict(set))

        # Track bulk creation lists for each media type
        self.bulk_media = defaultdict(list)

        logger.info(
            "Initialized MangaBaka importer for user %s with mode %s",
            user,
            mode,
        )

    def import_data(self):
        """Import all manga from the user's MangaBaka library."""
        page = 1

        while page <= MAX_PAGES:
            payload = self._fetch_page(page)
            rows = payload.get("data") or []
            if not rows:
                break

            pagination = payload.get("pagination") or {}
            if self._progress_total is None:
                self._progress_total = pagination.get("count") or len(rows)

            for entry in rows:
                self._progress_current += 1
                import_progress.report(
                    self._progress_current,
                    self._progress_total,
                    "MangaBaka",
                )
                try:
                    self._process_entry(entry)
                except Exception as error:
                    msg = f"Error processing MangaBaka entry: {entry}"
                    raise MediaImportUnexpectedError(msg) from error

            if not pagination.get("next"):
                break
            page += 1
        else:
            self.warnings.append(
                f"Stopped after {MAX_PAGES} pages; some entries were not imported.",
            )

        helpers.cleanup_existing_media(self.to_delete, self.user)
        helpers.bulk_create_media(self.bulk_media, self.user)

        imported_counts = {
            media_type: len(media_list)
            for media_type, media_list in self.bulk_media.items()
        }

        deduplicated_messages = "\n".join(dict.fromkeys(self.warnings))
        return imported_counts, deduplicated_messages

    def _fetch_page(self, page):
        """Return one page of the user's MangaBaka library."""
        url = f"{app.providers.mangabaka.base_url}/my/library"
        headers = {
            **app.providers.mangabaka.headers,
            "x-api-key": self.token,
        }

        try:
            return services.api_request(
                Sources.MANGABAKA.value,
                "GET",
                url,
                params={"limit": PAGE_SIZE, "page": page},
                headers=headers,
            )
        except requests.exceptions.HTTPError as error:
            status_code = getattr(error.response, "status_code", None)
            if status_code in (401, 403):
                # A bad or revoked token is the user's to fix, not a retryable
                # fault, so surface the real cause instead of a traceback.
                msg = "MangaBaka rejected the API token. Check the token is current."
                raise MediaImportError(msg) from error
            raise

    def _process_entry(self, entry):
        """Process a single entry from the MangaBaka library."""
        series = entry.get("Series") or {}
        series_id = series.get("id") or entry.get("series_id")
        if series_id is None:
            self.warnings.append("Skipped a library entry with no series id.")
            return

        if not helpers.should_process_media(
            self.existing_media,
            self.to_delete,
            MediaTypes.MANGA.value,
            Sources.MANGABAKA.value,
            str(series_id),
            self.mode,
            deleted_media=self.deleted_media,
        ):
            return

        title = series.get("title") or ""
        item, _ = Item.objects.get_or_create(
            media_id=str(series_id),
            source=Sources.MANGABAKA.value,
            media_type=MediaTypes.MANGA.value,
            defaults={
                **Item.title_fields_from_metadata(
                    {
                        "title": title,
                        "localized_title": title,
                        "original_title": series.get("romanized_title"),
                    },
                ),
                "image": app.providers.mangabaka.get_image_url(series),
            },
        )

        model = apps.get_model(app_label="app", model_name=MediaTypes.MANGA.value)
        state = entry.get("state")
        status = STATE_STATUS.get(state)
        if status is None:
            self.warnings.append(f"{title}: unrecognised state {state!r}.")
            status = Status.PLANNING.value

        score = self._get_score(entry.get("rating"))
        start_date = self._parse_date(entry.get("start_date"))
        end_date = self._parse_date(entry.get("finish_date"))

        # MangaBaka records rereads as a count on the one entry, where Floppy
        # models each pass as its own completed row -- the same translation the
        # MAL and AniList importers make for their repeat fields.
        rereads = entry.get("number_of_rereads") or 0
        for _ in range(rereads):
            reread = model(
                item=item,
                user=self.user,
                score=score,
                progress=_int_or_zero(series.get("total_chapters")),
                status=Status.COMPLETED.value,
                start_date=None,
                end_date=None,
                notes="",
            )
            self.bulk_media[MediaTypes.MANGA.value].append(reread)

        instance = model(
            item=item,
            user=self.user,
            score=score,
            progress=entry.get("progress_chapter") or 0,
            status=status,
            start_date=start_date,
            end_date=end_date,
            notes=entry.get("note") or "",
        )
        self.bulk_media[MediaTypes.MANGA.value].append(instance)

    @staticmethod
    def _get_score(rating):
        """Convert a MangaBaka 0-100 rating into Floppy's 0-10 score."""
        if rating is None:
            return None
        try:
            return round(float(rating) / RATING_DIVISOR, 1)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_date(value):
        """Build a tz-aware midnight datetime from a MangaBaka date string.

        MangaBaka emits calendar days as `YYYY-MM-DDT00:00:00.000Z`. Parsing
        that as an instant and converting timezones would slide the day for
        anyone behind UTC, so the day is read off the string as written.
        """
        if not value:
            return None

        try:
            year, month, day = (
                int(part) for part in str(value)[:10].split("-")
            )
            return timezone.datetime(
                year=year,
                month=month,
                day=day,
                hour=0,
                minute=0,
                second=0,
                tzinfo=timezone.get_current_timezone(),
            )
        except (TypeError, ValueError):
            logger.debug("Unparseable MangaBaka date: %r", value)
            return None
