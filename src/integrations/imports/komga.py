"""Komga importer for book and comic reading progress."""

import logging
import re

from django.utils import timezone

import app
from app.models import MediaTypes
from integrations import import_progress
from integrations.imports.mylar import comic_issue_item
from integrations.imports.reading_server import (
    ReadingServerImporter,
    parse_datetime,
    request_json,
    write_reading_progress,
)
from integrations.models import KomgaAccount, KomgaBookLink

logger = logging.getLogger(__name__)

ENTRY_SOURCE = "komga"
PAGE_SIZE = 100
EPUB_MEDIA_TYPE = "application/epub+zip"
# Comic Vine issue urls end in "4000-<issue id>" (4050 is a volume).
COMICVINE_ISSUE_LINK = re.compile(r"comicvine\.gamespot\.com/.*?4000-(\d+)")
AUTHOR_ROLES = frozenset({"", "author", "writer"})


class KomgaClient:
    """Thin API client for the Komga REST API."""

    def __init__(self, base_url: str, api_key: str):
        """Store the server URL and API key."""
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _get(self, path: str, **params):
        return request_json(
            "Komga",
            "get",
            f"{self.base_url}{path}",
            headers={"X-API-Key": self.api_key},
            params=params,
        )

    def healthcheck(self):
        """Verify the server is reachable and the key is accepted."""
        return self._get("/api/v2/users/me")

    def recently_read_books(self):
        """Yield books with reading progress, most recently read first."""
        page = 0
        while True:
            payload = self._get(
                "/api/v1/books",
                read_status=["IN_PROGRESS", "READ"],
                sort="readProgress.readDate,desc",
                page=page,
                size=PAGE_SIZE,
            )
            yield from payload.get("content") or []
            if payload.get("last", True):
                return
            page += 1


def importer(identifier, user, mode):
    """Import Komga reading progress for a user."""
    return KomgaImporter(user).import_data()


class KomgaImporter(ReadingServerImporter):
    """Import reading progress from Komga."""

    service = "Komga"
    account_attr = "komga_account"
    account_model = KomgaAccount
    link_model = KomgaBookLink
    link_field = "komga_book_id"
    client_class = KomgaClient

    def sync(self, cutoff, counts, links):
        """Import every book with reading progress newer than the cutoff."""
        for index, book in enumerate(self.client.recently_read_books(), start=1):
            # Pages arrive lazily, so there is no total to report.
            import_progress.report(index, None, "Komga")
            progress = book.get("readProgress") or {}
            read_at = parse_datetime(
                progress.get("readDate") or progress.get("lastModified"),
            )
            if cutoff and read_at and read_at < cutoff:
                break
            self._import_book(book, links, counts)

    def _import_book(self, book, links, counts):
        """Write one Komga book's progress, counting the outcome."""
        progress = book.get("readProgress") or {}
        completed = bool(progress.get("completed"))
        page = int(progress.get("page") or 0)
        if not completed and page <= 0:
            return

        metadata = book.get("metadata") or {}
        title = metadata.get("title") or book.get("name") or ""
        is_book = (book.get("media") or {}).get("mediaType") == EPUB_MEDIA_TYPE
        media_type = MediaTypes.BOOK if is_book else MediaTypes.COMIC_ISSUE
        book_id = str(book.get("id") or "")

        self.import_entry(
            links,
            book_id,
            title or book_id,
            counts,
            media_type,
            lambda: self._resolve_book_item(book, is_book),
            lambda item: self._write_progress(item, media_type, book, completed, page),
        )

    def _resolve_book_item(self, book, is_book):
        """Return the Floppy item a Komga book maps to, or None."""
        metadata = book.get("metadata") or {}
        title = metadata.get("title") or book.get("name") or ""
        if is_book:
            authors = [
                author["name"]
                for author in metadata.get("authors") or []
                if author.get("name")
                and str(author.get("role") or "").lower() in AUTHOR_ROLES
            ]
            return self.resolve_book_item(title, authors, metadata.get("isbn"))

        series = book.get("seriesTitle") or ""
        number = metadata.get("number") or book.get("number")
        label = f"{series} #{number}" if series and number else title or series
        for link in metadata.get("links") or []:
            match = COMICVINE_ISSUE_LINK.search(str(link.get("url") or ""))
            if match:
                return comic_issue_item(match.group(1), label, None)
        if not self.account.create_missing or not label:
            return None
        return self.manual_item(MediaTypes.COMIC_ISSUE, label)

    def _write_progress(self, item, media_type, book, completed, page):
        """Save the reading progress; return True if created, False if updated.

        Returns None when nothing changed.
        """
        model = (
            app.models.Book
            if media_type == MediaTypes.BOOK
            else app.models.ComicIssue
        )
        progress = book.get("readProgress") or {}
        pages_total = int((book.get("media") or {}).get("pagesCount") or 0)
        return write_reading_progress(
            self.user,
            item,
            model,
            progress=max(pages_total, page) if completed else page,
            completed=completed,
            read_at=parse_datetime(progress.get("readDate")) or timezone.now(),
            started_at=parse_datetime(progress.get("created")),
            entry_source=ENTRY_SOURCE,
        )
