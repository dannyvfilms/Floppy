"""Importer for The StoryGraph's account export CSV.

StoryGraph has no public API, so the export CSV is the supported path. Each
read in the ``Dates Read`` column becomes its own ``Book`` row, which is how
Floppy models re-reads: the history calendar is built from live rows rather
than from simple-history records.
"""

import logging
import re
from collections import defaultdict
from csv import DictReader
from datetime import datetime
from difflib import SequenceMatcher
from typing import NamedTuple

from django.apps import apps
from django.conf import settings
from django.utils import timezone

import app
from app.models import MediaTypes, Sources, Status
from app.providers import services
from integrations import import_progress
from integrations.imports import helpers
from integrations.imports.helpers import MediaImportError, MediaImportUnexpectedError
from lists.models import CustomList, CustomListItem

logger = logging.getLogger(__name__)

STATUS_MAP = {
    "read": Status.COMPLETED.value,
    "currently-reading": Status.IN_PROGRESS.value,
    "to-read": Status.PLANNING.value,
    "did-not-finish": Status.DROPPED.value,
}
FORMAT_MAP = {
    "digital": "ebook",
    "audio": "audiobook",
    "paperback": "paperback",
    "hardcover": "hardcover",
}
ISBN_13_LENGTH = 13
ISBN_10_LENGTH = 10
MAX_STAR_RATING = 5
BOOK_METADATA_PROVIDER_ORDER = (Sources.HARDCOVER.value, Sources.OPENLIBRARY.value)
TITLE_MATCH_THRESHOLD = 0.72
MAX_SEARCH_RESULTS = 5
MAX_TITLE_CANDIDATES = 3
# Candidates rank on author agreement first, then on how exactly the title
# lines up. Author agreement leads because a bare title with no author behind
# it is the weakest evidence there is; the title rank only breaks ties.
AUTHOR_RANK = {"match": 2, "unknown": 1}
EXACT_TITLE_RANK = 2
LOOSE_TITLE_RANK = 1
LEADING_ARTICLES = frozenset({"a", "an", "the"})
NO_MATCH = (0, 0, False, 0.0)
BEST_MATCH = (AUTHOR_RANK["match"], EXACT_TITLE_RANK, True, 1.0)


class Read(NamedTuple):
    """A single read interval with optional start date."""

    start: datetime | None
    end: datetime | None


def parse_date(value):
    """Parse a StoryGraph ``YYYY/MM/DD`` date into an aware datetime."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.strptime(text, "%Y/%m/%d")  # noqa: DTZ007 - tz applied below
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.get_current_timezone())


def parse_reads(dates_read):
    """Parse ``Dates Read`` into ordered reads, oldest first.

    A dash separated chunk is a start and an end date. A bare date is a finish
    date with no known start, so ``start`` stays ``None``.
    """
    reads = []
    for chunk in str(dates_read or "").split(","):
        pieces = [piece.strip() for piece in chunk.split("-") if piece.strip()]
        dates = [date for date in map(parse_date, pieces) if date]
        if not dates:
            continue
        if len(dates) == 1:
            reads.append(Read(start=None, end=dates[0]))
        else:
            reads.append(Read(start=dates[0], end=dates[-1]))

    reads.sort(key=lambda read: read.end or read.start)
    return reads


def read_day(value):
    """Return the local calendar day a stored or parsed read date falls on.

    ``parse_date`` builds local midnight, which the database keeps in UTC -
    for any zone east of Greenwich that is the *previous* day. Reading
    ``.date()`` off either side would compare a local day against a UTC one,
    so both sides go through this instead. That mismatch is invisible under
    ``TZ=UTC``, which is why the test suite never caught it.
    """
    return timezone.localdate(value) if value else None


def determine_status(raw_status):
    """Map a StoryGraph read status onto a Floppy status."""
    return STATUS_MAP.get(
        str(raw_status or "").strip().lower(),
        Status.PLANNING.value,
    )


def parse_rating(raw_rating):
    """Convert a 0-5 star rating with halves into a 0-10 score."""
    text = str(raw_rating or "").strip()
    if not text:
        return None
    try:
        rating = float(text)
    except ValueError:
        return None
    if rating <= 0:
        return None
    return round(min(rating, MAX_STAR_RATING) * 2, 1)


def parse_tags(raw_tags):
    """Split the comma separated ``Tags`` column, preserving order."""
    tags = [tag.strip() for tag in str(raw_tags or "").split(",") if tag.strip()]
    return list(dict.fromkeys(tags))


def parse_authors(raw_authors):
    """Split the comma separated ``Authors`` column."""
    return [name.strip() for name in str(raw_authors or "").split(",") if name.strip()]


def normalize_isbn(raw_isbn):
    """Return the value as an ISBN, or ``""`` when it is an ASIN or junk."""
    candidate = str(raw_isbn or "").strip().replace("-", "").replace(" ", "").upper()
    if len(candidate) == ISBN_13_LENGTH and candidate.isdigit():
        return candidate
    if len(candidate) == ISBN_10_LENGTH and candidate[:9].isdigit():
        return candidate
    return ""


def map_format(raw_format):
    """Map a StoryGraph format onto the format values Floppy stores."""
    return FORMAT_MAP.get(str(raw_format or "").strip().lower(), "")


def normalize_name(value):
    """Lowercase a title or name down to alphanumerics for comparison."""
    normalized = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
    return re.sub(r"\s+", " ", normalized).strip()


def title_similarity(left, right):
    """Return a 0-1 similarity ratio between two normalized titles."""
    left_normalized = normalize_name(left)
    right_normalized = normalize_name(right)
    if not left_normalized or not right_normalized:
        return 0.0
    return SequenceMatcher(None, left_normalized, right_normalized).ratio()


def titles_match(left, right):
    """Match titles, tolerating subtitles ('Mistborn' vs 'Mistborn: ...')."""
    left_normalized = normalize_name(left)
    right_normalized = normalize_name(right)
    if not left_normalized or not right_normalized:
        return False
    if left_normalized == right_normalized:
        return True
    if right_normalized.startswith(left_normalized) or left_normalized.startswith(
        right_normalized,
    ):
        return True
    return title_similarity(left, right) >= TITLE_MATCH_THRESHOLD


def authors_overlap(target_authors, provider_authors):
    """Return True when two author name sets plausibly mean the same person."""
    target = {name for name in map(normalize_name, target_authors) if name}
    provider = {name for name in map(normalize_name, provider_authors) if name}
    if not target or not provider:
        return False
    if target & provider:
        return True
    for left in target:
        for right in provider:
            if left in right or right in left:
                return True
            if left.split()[-1] == right.split()[-1]:  # shared surname
                return True
    return False


def prepends_extra_words(target_title, candidate_title):
    """Return whether the candidate is the export title with words bolted on front.

    Closeness alone cannot separate a novel from a companion book about it:
    'Spark Notes Harry Potter and the Sorcerer's Stone' repeats the export
    title in full and so scores fractionally above the novel itself, whose
    edition differs by a word ('Philosopher's'). What gives the guide away is
    position - it carries the title complete and unaltered, with framing words
    in front of it.

    The test is deliberately narrow: the export title must appear in the
    candidate word for word, starting somewhere after the beginning. A title
    that merely differs in spelling ('Valour' / 'Valor') or gains words in the
    middle ('A Storm of Swords, Part 2: ...') is not prepended, and is left
    for closeness to judge. Leading articles vary freely between editions
    ('Dragon Keeper' / 'The Dragon Keeper'), so they are dropped first.
    """
    target = _significant_words(target_title)
    candidate = _significant_words(candidate_title)
    if not target or len(candidate) <= len(target):
        return False
    return any(
        candidate[start : start + len(target)] == target
        for start in range(1, len(candidate) - len(target) + 1)
    )


def _significant_words(value):
    """Split a title into normalized words, dropping a leading article."""
    words = normalize_name(value).split()
    if words and words[0] in LEADING_ARTICLES:
        words = words[1:]
    return words


def match_rank(target_title, candidate_title, verdict):
    """Rank a candidate by author agreement, then title exactness, then closeness.

    The title rank exists because ``titles_match`` accepts a prefix in either
    direction. That is what lets a CSV title of 'Mistborn' match 'Mistborn:
    The Final Empire', but read the other way it also lets a bare 'The
    Visitor' answer for 'The Visitor: Kill or Cure' - a different book by the
    same author. Both agree on the author, so without a tiebreak the two are
    indistinguishable and whichever query ran first won.

    Closeness settles the rest. A novel published in halves has a record for
    each half and one for the whole, all by the same author and none titled
    exactly as the export writes it: 'A Storm of Swords: Blood and Gold'
    reads much closer to 'A Storm of Swords, Part 2: Blood and Gold' (0.90)
    than to the bare 'A Storm of Swords' (0.69), so each half keeps its own
    book instead of both collapsing onto the whole novel.
    """
    title_rank = (
        EXACT_TITLE_RANK
        if normalize_name(target_title) == normalize_name(candidate_title)
        else LOOSE_TITLE_RANK
    )
    return (
        AUTHOR_RANK[verdict],
        title_rank,
        not prepends_extra_words(target_title, candidate_title),
        title_similarity(target_title, candidate_title),
    )


def classify_authors(target_authors, candidate_authors):
    """Classify author agreement as 'match', 'unknown', or 'conflict'."""
    if not target_authors:
        return "match"
    if not candidate_authors:
        return "unknown"
    if authors_overlap(target_authors, candidate_authors):
        return "match"
    return "conflict"


def extract_provider_authors(metadata):
    """Pull author names out of provider metadata, whatever shape they take."""
    details = metadata.get("details", {}) if isinstance(metadata, dict) else {}
    if not isinstance(details, dict):
        details = {}

    raw_authors = details.get("authors") or details.get("author") or []
    if isinstance(raw_authors, str):
        raw_authors = [part.strip() for part in raw_authors.split(",") if part.strip()]
    elif not isinstance(raw_authors, list):
        raw_authors = [raw_authors] if raw_authors else []

    authors = []
    for raw_author in raw_authors:
        value = (
            raw_author.get("name") or raw_author.get("person")
            if isinstance(raw_author, dict)
            else raw_author
        )
        name = str(value or "").strip()
        if name:
            authors.append(name)
    return list(dict.fromkeys(authors))


class BookResolver:
    """Resolve StoryGraph rows to books on Hardcover, then Open Library."""

    def __init__(self, cache):
        """Initialize with a dict used to memoize resolutions across rows."""
        self.cache = cache

    def resolve(self, title, authors, isbn):
        """Return ``(source, media_id, metadata)`` for a book, or None."""
        cache_key = isbn or (
            f"{normalize_name(title)}|{normalize_name(' '.join(authors))}"
        )
        if cache_key in self.cache:
            return self.cache[cache_key]

        resolved = self._search_providers(title, authors, isbn)
        self.cache[cache_key] = resolved
        return resolved

    def _queries(self, title, authors, isbn):
        """Build the ordered search queries for one book."""
        queries = [isbn] if isbn else []
        if title and authors:
            queries.append(f"{title} {authors[0]}")
        if title:
            queries.append(title)
        return list(dict.fromkeys(query for query in queries if query))

    def _search_providers(self, title, authors, isbn):
        """Walk the provider and query ladder, keeping the best candidate.

        A ``ProviderAPIError`` on one query does not stop the ladder - Open
        Library exists as a coverage fallback specifically for when
        Hardcover is unavailable, so the next query or provider still gets
        tried. Only when every query on every provider fails outright, with
        no successful response from any of them, does the last failure
        propagate - the caller must not be told the book was "not found"
        when the truth is that nothing was ever actually checked. Any other
        exception is genuinely unexpected and is not caught here at all, so
        it can abort the import as the design spec requires.

        Only an exact title from an author-confirmed record ends the walk
        outright; a looser match keeps looking, because the remaining queries
        are what turn up the record that actually carries the full title. To
        stop that costing every book a full ladder, an author-confirmed match
        does end the walk at the provider boundary - Hardcover is the
        preferred source, and Open Library is only here for coverage.
        """
        best_rank = NO_MATCH
        best_result = None
        last_error = None
        any_success = False

        for source in BOOK_METADATA_PROVIDER_ORDER:
            for query in self._queries(title, authors, isbn):
                try:
                    rank, result = self._match_query(source, query, title, authors)
                except services.ProviderAPIError as error:
                    last_error = error
                    continue
                any_success = True
                if rank > best_rank:
                    best_rank, best_result = rank, result
                    if best_rank == BEST_MATCH:
                        return best_result
            if best_rank[0] == AUTHOR_RANK["match"]:
                break

        if best_result is None and not any_success and last_error is not None:
            raise last_error

        return best_result

    def _match_query(self, source, query, title, authors):
        """Search one provider with one query, returning ``(rank, result)``.

        Provider failures are not caught here: ``services.search`` and
        ``services.get_media_metadata`` only raise ``ProviderAPIError`` once
        their own retries are exhausted, so it always represents a real
        failure, and ``_search_providers`` is what decides whether to fall
        back to the next provider or let it propagate. Any other exception
        is unexpected and must propagate too.
        """
        response = services.search(MediaTypes.BOOK.value, query, 1, source)

        results = response.get("results", []) if isinstance(response, dict) else []
        best_rank = NO_MATCH
        best_result = None

        for candidate in self._title_candidates(results, title):
            media_id = candidate.get("media_id")
            if not media_id:
                continue

            metadata = services.get_media_metadata(
                MediaTypes.BOOK.value,
                str(media_id),
                source,
            )

            candidate_title = str(metadata.get("title") or "")
            if not titles_match(title, candidate_title):
                continue

            verdict = classify_authors(authors, extract_provider_authors(metadata))
            if verdict == "conflict":
                continue

            rank = match_rank(title, candidate_title, verdict)
            if rank > best_rank:
                best_rank = rank
                best_result = (source, str(media_id), metadata)
                if best_rank == BEST_MATCH:
                    break

        return best_rank, best_result

    def _title_candidates(self, results, title):
        """Return the best title-matching search results, best first."""
        scored = []
        for result in results[:MAX_SEARCH_RESULTS]:
            candidate_title = str(result.get("title") or "")
            if not titles_match(title, candidate_title):
                continue
            scored.append((title_similarity(title, candidate_title), result))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [result for _score, result in scored[:MAX_TITLE_CANDIDATES]]


def importer(file, user, mode):
    """Import books from a StoryGraph export CSV."""
    return StoryGraphImporter(file, user, mode).import_data()


class StoryGraphImporter:
    """Import a StoryGraph export, one tracked entry per read."""

    def __init__(self, file, user, mode):
        """Initialize the importer with the upload, user, and import mode."""
        self.file = file
        self.user = user
        self.mode = mode
        self.warnings = []

        self.existing_media = helpers.get_existing_media(user)
        self.to_delete = defaultdict(lambda: defaultdict(set))
        self.bulk_media = defaultdict(list)
        self.resolver = BookResolver({})
        self.tracked_reads, self.tracked_statuses = self._load_tracked_reads()
        self._overwritten = set()
        self.list_cache = {}
        self.missing_read_dates = []
        self.missing_start_dates = []

        logger.info(
            "Initialized StoryGraph CSV importer for user %s with mode %s",
            user.username,
            mode,
        )

    def import_data(self):
        """Import every row of the CSV and return counts plus messages."""
        try:
            raw_file = self.file.read()
            try:
                decoded_file = raw_file.decode("utf-8-sig").splitlines()
            except UnicodeDecodeError:
                decoded_file = raw_file.decode("latin-1").splitlines()
        except (UnicodeDecodeError, AttributeError) as error:
            msg = "Invalid file format. Please upload a CSV file."
            raise MediaImportError(msg) from error

        rows = list(DictReader(decoded_file))
        total = len(rows)
        for i, row in enumerate(rows, start=1):
            import_progress.report(i, total, "StoryGraph")
            try:
                self._process_row(row)
            except services.ProviderAPIError as error:
                title = (row.get("Title") or "").strip() or str(row)
                self.warnings.append(f"Error processing entry: {title} - {error}")
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
        messages = list(dict.fromkeys(self.warnings)) + self._report_lines()
        return imported_counts, "\n".join(messages)

    def _process_row(self, row):
        """Resolve one CSV row and queue its tracked entries."""
        title = (row.get("Title") or "").strip()
        if not title:
            return

        resolved = self.resolver.resolve(
            title,
            parse_authors(row.get("Authors")),
            normalize_isbn(row.get("ISBN/UID")),
        )
        if not resolved:
            self.warnings.append(
                f"{title}: couldn't find this book on Hardcover or Open Library",
            )
            return

        source, media_id, metadata = resolved
        item = self._create_or_update_item(source, media_id, metadata, row)
        self._sync_tags(item, row)
        self._record_date_gaps(item, row)
        tracked_dates, tracked_statuses = self._tracked_state(source, media_id)
        for instance in self._build_entries(
            item,
            row,
            metadata,
            tracked_dates,
            tracked_statuses,
        ):
            self.bulk_media[MediaTypes.BOOK.value].append(instance)

    def _record_date_gaps(self, item, row):
        """Note date gaps in the row itself, regardless of dedup or mode.

        The report describes the quality of the export, not what a given run
        happened to write, so it is derived straight from the row's own
        ``Read Status`` and ``Dates Read`` values every time the row is
        processed - including on a re-import where every read is already
        tracked and no new instance gets built.
        """
        if determine_status(row.get("Read Status")) != Status.COMPLETED.value:
            return
        reads = parse_reads(row.get("Dates Read"))
        if not reads:
            self.missing_read_dates.append(item.title)
            return
        for read in reads:
            if not read.start:
                self.missing_start_dates.append(item.title)

    def _load_tracked_reads(self):
        """Map each already-tracked book to its completed dates and statuses.

        ``tracked_dates`` is seeded only from existing ``Completed`` rows -
        real end dates plus a ``None`` sentinel for a completed read that
        was recorded with no date at all. ``tracked_statuses`` is seeded
        from every other existing row, keyed to the status itself rather
        than to a shared ``None`` sentinel.

        Keeping these separate matters: every non-completed status
        (Planning, In progress, Dropped) is created dateless by
        construction, so a shared sentinel would make an existing Planning
        row look identical to an existing dateless Completed row. That was
        the bug - a Planning row left a ``None`` sentinel behind, so a later
        export marking the same book finished with no recorded date (the
        most common gap in real StoryGraph exports) was silently dropped
        because the sentinel was already "used".
        """
        tracked_dates = defaultdict(set)
        tracked_statuses = defaultdict(set)
        model = apps.get_model(app_label="app", model_name=MediaTypes.BOOK.value)
        for book in model.objects.filter(user=self.user).select_related("item"):
            key = (book.item.source, book.item.media_id)
            if book.status == Status.COMPLETED.value:
                tracked_dates[key].add(read_day(book.end_date))
            else:
                tracked_statuses[key].add(book.status)
        return tracked_dates, tracked_statuses

    def _tracked_state(self, source, media_id):
        """Return the (dates, statuses) sets to skip, wiping both in overwrite mode."""
        key = (source, media_id)
        if self.mode == "overwrite" and key not in self._overwritten:
            self._overwritten.add(key)
            if media_id in self.existing_media[MediaTypes.BOOK.value][source]:
                self.to_delete[MediaTypes.BOOK.value][source].add(media_id)
            self.tracked_reads[key] = set()
            self.tracked_statuses[key] = set()
        return self.tracked_reads[key], self.tracked_statuses[key]

    def _create_or_update_item(self, source, media_id, metadata, row):
        """Create or update the item, filling in an empty format only."""
        item, _ = app.models.Item.objects.update_or_create(
            media_id=media_id,
            source=source,
            media_type=MediaTypes.BOOK.value,
            defaults={
                **app.models.Item.title_fields_from_metadata(
                    metadata,
                    fallback_title=(row.get("Title") or "").strip(),
                ),
                "image": metadata.get("image") or settings.IMG_NONE,
            },
        )

        book_format = map_format(row.get("Format"))
        if book_format and not item.format:
            item.format = book_format
            item.save(update_fields=["format"])

        return item

    def _sync_tags(self, item, row):
        """Mirror the row's tags as custom lists holding this item."""
        for tag in parse_tags(row.get("Tags")):
            custom_list = self.list_cache.get(tag)
            if custom_list is None:
                custom_list = CustomList.objects.filter(
                    owner=self.user,
                    name=tag,
                ).first() or CustomList.objects.create(
                    owner=self.user,
                    name=tag,
                    source="local",
                )
                self.list_cache[tag] = custom_list

            CustomListItem.objects.get_or_create(
                item=item,
                custom_list=custom_list,
                defaults={"added_by": self.user},
            )

    def _page_count(self, item, metadata, status):
        """Return the progress to store, in pages, for a tracked entry."""
        if status != Status.COMPLETED.value or item.format == "audiobook":
            return 0
        max_progress = metadata.get("max_progress")
        return int(max_progress) if max_progress else 0

    def _report_lines(self):
        """Describe the date gaps in the export worth fixing in StoryGraph."""
        lines = []
        if self.missing_read_dates:
            titles = ", ".join(dict.fromkeys(self.missing_read_dates))
            lines.append(f"Marked read in StoryGraph with no read date: {titles}")
        if self.missing_start_dates:
            titles = ", ".join(dict.fromkeys(self.missing_start_dates))
            lines.append(
                f"Has a finish date in StoryGraph but no start date: {titles}",
            )
        return lines

    def _build_entries(self, item, row, metadata, tracked_dates, tracked_statuses):
        """Build one unsaved Book per untracked read, newest last.

        A dateless entry is gated differently depending on whether the row
        is Completed: a dateless Completed read is created once per item
        (``tracked_dates`` carries the ``None`` sentinel for that), while a
        dateless non-completed row is created once per status
        (``tracked_statuses``) - so a Planning row followed by another
        Planning row still does not duplicate, but a Planning row followed
        by a dateless Completed row is not blocked by it.
        """
        status = determine_status(row.get("Read Status"))
        progress = self._page_count(item, metadata, status)
        reads = (
            parse_reads(row.get("Dates Read"))
            if status == Status.COMPLETED.value
            else []
        )
        fallback_date = parse_date(row.get("Date Added"))
        had_entries = bool(tracked_dates)

        instances = []
        for read in reads:
            day = read_day(read.end)
            if day in tracked_dates:
                continue
            tracked_dates.add(day)
            instances.append(
                self._build_instance(
                    item,
                    status,
                    read.start,
                    read.end,
                    progress,
                    fallback_date,
                ),
            )

        if not reads:
            if status == Status.COMPLETED.value:
                if not had_entries:
                    tracked_dates.add(None)
                    instances.append(
                        self._build_instance(
                            item,
                            status,
                            None,
                            None,
                            progress,
                            fallback_date,
                        ),
                    )
            elif status not in tracked_statuses:
                tracked_statuses.add(status)
                instances.append(
                    self._build_instance(
                        item,
                        status,
                        None,
                        None,
                        progress,
                        fallback_date,
                    ),
                )

        if instances and not had_entries:
            # One StoryGraph rating covers the book, so it goes on the newest
            # entry only - repeating it per re-read would double count it in
            # statistics. A book that already has entries carries its rating
            # there, so a newly added re-read is left unrated.
            newest = instances[-1]
            newest.score = parse_rating(row.get("Star Rating"))
            newest.notes = (row.get("Review") or "").strip()

        return instances

    def _build_instance(
        self,
        item,
        status,
        start_date,
        end_date,
        progress,
        fallback_date,
    ):
        """Build a single unsaved Book instance for one read."""
        model = apps.get_model(app_label="app", model_name=MediaTypes.BOOK.value)
        instance = model(
            item=item,
            user=self.user,
            status=status,
            progress=progress,
            start_date=start_date,
            end_date=end_date,
        )
        instance._history_date = (
            end_date or start_date or fallback_date or timezone.now()
        )
        return instance
