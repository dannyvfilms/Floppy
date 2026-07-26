"""Importer for The StoryGraph's account export CSV.

StoryGraph has no public API, so the export CSV is the supported path. Each
read in the ``Dates Read`` column becomes its own ``Book`` row, which is how
Yamtrack models re-reads: the history calendar is built from live rows rather
than from simple-history records.
"""

import logging
import re
from datetime import datetime
from typing import NamedTuple

from django.utils import timezone

from app.models import Status

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
