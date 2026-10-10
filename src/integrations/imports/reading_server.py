"""Shared pieces for the self-hosted reading servers (Komga, Kavita).

Both servers sync reading progress the same way: poll with a stored key, match
each book or series to an item, write progress without overriding a status the
user chose, and record health on the account. Each server keeps only its own
client, matching rules and link table.
"""

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta
from http import HTTPStatus
from urllib.parse import urlsplit

import requests
from django.conf import settings
from django.utils import timezone

from app.models import Item, Sources, Status
from app.services.synced_status import keep_held_status
from integrations import connection_health
from integrations.imports.helpers import (
    ConnectionAuthError,
    MediaImportError,
    decrypt_or_raise,
)
from integrations.imports.koreader import KoreaderImporter
from integrations.safe_fetch import SelfHostedUrlError, send_to_self_hosted

logger = logging.getLogger(__name__)

# The server's and Floppy's clocks can differ a little; re-read a short overlap.
SYNC_OVERLAP = timedelta(minutes=5)


def request_json(service, method, url, **kwargs):
    """Call a self-hosted server and return its JSON body.

    A rejected key raises ``ConnectionAuthError`` (the only failure that may
    mark the account broken); everything else raises ``MediaImportError``.
    """
    path = urlsplit(url).path
    try:
        response = send_to_self_hosted(
            getattr(requests, method),
            url,
            timeout=20,
            **kwargs,
        )
    except SelfHostedUrlError as error:
        msg = f"Could not reach {service}: {error}"
        raise MediaImportError(msg) from error
    except requests.RequestException as error:
        msg = f"Could not reach {service} ({type(error).__name__})"
        raise MediaImportError(msg) from error
    if response.status_code in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
        msg = f"{service} API key is invalid or unauthorized"
        raise ConnectionAuthError(msg)
    if response.status_code >= HTTPStatus.BAD_REQUEST:
        msg = f"{service} request failed ({response.status_code}) for {path}"
        raise MediaImportError(msg)
    try:
        return response.json()
    except ValueError as error:
        msg = f"{service} returned an unreadable response for {path}"
        raise MediaImportError(msg) from error


def parse_datetime(value):
    """Return an aware datetime from a server timestamp, or None."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else timezone.make_aware(parsed)


def write_reading_progress(
    user,
    item,
    model,
    *,
    progress,
    completed,
    read_at,
    started_at,
    entry_source,
):
    """Save reading progress; return True if created, False if updated.

    Returns None when nothing changed. A status the user set by hand is kept.
    """
    existing = (
        model.objects.filter(user=user, item=item)
        .only("progress", "status", "start_date", "end_date")
        .first()
    )
    defaults = {
        "progress": progress,
        "status": Status.COMPLETED.value if completed else Status.IN_PROGRESS.value,
        "start_date": (existing.start_date if existing else None)
        or started_at
        or read_at,
        "end_date": (
            ((existing.end_date if existing else None) or read_at)
            if completed
            else None
        ),
    }
    defaults = keep_held_status(existing, defaults, read_at)

    if existing and all(
        getattr(existing, field) == value for field, value in defaults.items()
    ):
        return None
    model.objects.update_or_create(
        user=user,
        item=item,
        defaults=defaults,
        create_defaults={**defaults, "entry_source": entry_source},
    )
    return existing is None


def clean_isbn(value):
    """Return an ISBN without hyphens or spaces, uppercased."""
    return re.sub(r"[^0-9Xx]", "", str(value or "")).upper()


class ReadingServerImporter(KoreaderImporter):
    """Base importer: one account, one link table, one poll per run.

    Books are matched with the same title/author matching KOReader uses, so a
    server only supplies its client, its own matching and the progress write.
    Subclasses set the class attributes and implement ``sync``.
    """

    service = ""  # display name, e.g. "Komga"
    account_attr = ""  # reverse one-to-one name on the user
    account_model = None
    link_model = None
    link_field = ""  # the link model's field holding the server's own id
    client_class = None

    def __init__(self, user):
        """Initialize importer and validate account access."""
        self.user = user
        try:
            self.account = getattr(user, self.account_attr)
        except self.account_model.DoesNotExist as error:
            msg = f"Connect {self.service} before importing"
            raise MediaImportError(msg) from error

        try:
            api_key = decrypt_or_raise(self.account.api_key)
        except MediaImportError as error:
            # An unreadable stored key needs a reconnect as much as a rejected one.
            connection_health.record_failure(self.account, error, auth=True)
            raise

        self.client = self.client_class(self.account.base_url, api_key)
        self.warnings = []
        self.enable_provider_enrichment = not settings.TESTING

    def sync(self, cutoff, counts, links):
        """Import everything read after ``cutoff`` (None on the first run)."""
        raise NotImplementedError

    def import_data(self):
        """Import progress newer than the last sync and record the outcome."""
        started_at = timezone.now()
        self.account.refresh_from_db()
        cutoff = (
            self.account.last_sync_at - SYNC_OVERLAP
            if self.account.last_sync_at
            else None
        )
        counts = defaultdict(int)
        self._retry_entries = []
        self._library_items = self._build_library_index()
        links = {
            getattr(link, self.link_field): link
            for link in self.link_model.objects.filter(user=self.user).select_related(
                "item",
            )
        }

        try:
            self.sync(cutoff, counts, links)
            if self._retry_entries:
                self._retrying = True
                for entry in self._retry_entries:
                    self.import_entry(*entry, force_resolve=True)
                self._retrying = False
        except MediaImportError as error:
            connection_health.record_failure(
                self.account,
                error,
                auth=isinstance(error, ConnectionAuthError),
            )
            raise

        self.account.last_sync_at = started_at
        connection_health.record_success(self.account, extra_fields=["last_sync_at"])
        return dict(counts), "\n".join(dict.fromkeys(self.warnings))

    def import_entry(
        self,
        links,
        key,
        label,
        counts,
        media_type,
        resolve_item,
        write,
        force_resolve=False,
    ):
        """Match one server entry to an item, write it and count the outcome.

        ``resolve_item()`` runs only for an entry that has no stored link, and
        ``write(item)`` returns what ``write_reading_progress`` returns.
        """
        link = links.get(key)
        item = resolve_item() if force_resolve else (link.item if link else resolve_item())
        if item is None:
            self.warnings.append(f"Could not match {self.service} item {label}")
            counts["skipped"] += 1
            return
        if link is None and key:
            links[key] = self.link_model.objects.update_or_create(
                user=self.user,
                **{self.link_field: key},
                defaults={"item": item},
            )[0]

        result = write(item)
        if result is None:
            counts["skipped"] += 1
            return
        counts[media_type.value] += 1
        counts["created" if result else "updated"] += 1

    def resolve_book_item(self, title, authors, isbn=""):
        """Match a book by ISBN in the library, then by title and author."""
        isbn = clean_isbn(isbn)
        if isbn:
            for item in self._library_items:
                if isbn in {clean_isbn(value) for value in item.isbn or []}:
                    return item
        return self._resolve_item(title, authors)

    @staticmethod
    def manual_item(media_type, title):
        """Create a local-only item for something the provider can't identify."""
        return Item.objects.create(
            media_id=Item.generate_manual_id(),
            source=Sources.MANUAL.value,
            media_type=media_type.value,
            library_media_type=media_type.value,
            title=title,
            image="",
        )
