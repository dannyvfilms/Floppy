"""Importer for The StoryGraph's account export CSV.

StoryGraph has no public API, so the export CSV is the supported path. Each
read in the ``Dates Read`` column becomes its own ``Book`` row, which is how
Yamtrack models re-reads: the history calendar is built from live rows rather
than from simple-history records.
"""

import logging
import re
from datetime import datetime
from difflib import SequenceMatcher
from typing import NamedTuple

from django.utils import timezone

from app.log_safety import exception_summary
from app.models import MediaTypes, Sources, Status
from app.providers import services

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
BEST_TIER = 3


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


def determine_status(raw_status):
    """Map a StoryGraph read status onto a Yamtrack status."""
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
    """Map a StoryGraph format onto the format values Yamtrack stores."""
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
        """Walk the provider and query ladder, keeping the best candidate."""
        best_tier = 0
        best_result = None

        for source in BOOK_METADATA_PROVIDER_ORDER:
            for query in self._queries(title, authors, isbn):
                tier, result = self._match_query(source, query, title, authors)
                if tier > best_tier:
                    best_tier, best_result = tier, result
                    if best_tier == BEST_TIER:
                        return best_result

        return best_result

    def _match_query(self, source, query, title, authors):
        """Search one provider with one query, returning ``(tier, result)``."""
        try:
            response = services.search(MediaTypes.BOOK.value, query, 1, source)
        except Exception as error:  # noqa: BLE001 - a bad provider must not stop the import
            logger.debug(
                "StoryGraph search failed source=%s error=%s",
                source,
                exception_summary(error),
            )
            return 0, None

        results = response.get("results", []) if isinstance(response, dict) else []
        best_tier = 0
        best_result = None

        for candidate in self._title_candidates(results, title):
            media_id = candidate.get("media_id")
            if not media_id:
                continue

            try:
                metadata = services.get_media_metadata(
                    MediaTypes.BOOK.value,
                    str(media_id),
                    source,
                )
            except Exception as error:  # noqa: BLE001 - same reasoning as above
                logger.debug(
                    "StoryGraph metadata fetch failed source=%s error=%s",
                    source,
                    exception_summary(error),
                )
                continue

            if not titles_match(title, str(metadata.get("title") or "")):
                continue

            verdict = classify_authors(authors, extract_provider_authors(metadata))
            if verdict == "conflict":
                continue

            tier = BEST_TIER if verdict == "match" else 2
            if tier > best_tier:
                best_tier = tier
                best_result = (source, str(media_id), metadata)
                if best_tier == BEST_TIER:
                    break

        return best_tier, best_result

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
