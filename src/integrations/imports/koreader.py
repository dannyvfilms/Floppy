"""KOReader sync server importer for book reading progress."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime
from difflib import SequenceMatcher
from functools import partial
from http import HTTPStatus
from pathlib import Path
from typing import Any

import requests
from django.conf import settings
from django.utils import timezone

import app
from app import custom_metadata
from app import helpers as app_helpers
from app.log_safety import exception_summary
from app.models import MediaTypes, Sources, Status
from app.providers import services
from integrations import connection_health, import_progress
from integrations.imports.helpers import MediaImportError, decrypt_or_raise
from integrations.models import KoreaderAccount, KoreaderDocumentLink
from integrations.safe_fetch import send_to_self_hosted

logger = logging.getLogger(__name__)

HTTP_BAD_REQUEST = 400
HTTP_NOT_FOUND = 404
AUTH_TIMEOUT = 15
API_TIMEOUT = 20
TITLE_MATCH_THRESHOLD = 0.72
BOOK_METADATA_PROVIDER_ORDER = (
    Sources.HARDCOVER.value,
    Sources.OPENLIBRARY.value,
    Sources.GOOGLEBOOKS.value,
)
DOCUMENT_HASH_RE = re.compile(r"^[a-f0-9]{32}$")
MILLIS_TIMESTAMP_THRESHOLD = 1_000_000_000_000


class KoreaderClientError(Exception):
    """Base KOReader client error."""


class KoreaderAuthError(KoreaderClientError):
    """KOReader auth failure."""


class UnsupportedListEndpointError(KoreaderClientError):
    """Server does not expose a document list endpoint."""


class KoreaderClient:
    """HTTP client for the KOReader sync server API."""

    ACCEPT = "application/vnd.koreader.v1+json"

    def __init__(
        self,
        server_url: str,
        username: str,
        auth_key: str,
        *,
        verify_ssl: bool = True,
    ):
        """Initialize with server URL, credentials, and TLS verification preference."""
        self.server_url = server_url.rstrip("/")
        self.username = username
        self.auth_key = auth_key
        self.verify_ssl = verify_ssl

    @classmethod
    def password_to_auth_key(cls, password: str) -> str:
        """Return the MD5 hex digest expected by the sync server."""
        return hashlib.md5(password.encode("utf-8")).hexdigest()  # noqa: S324

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": self.ACCEPT,
            "X-Auth-User": self.username,
            "X-Auth-Key": self.auth_key,
        }

    def _url(self, path: str) -> str:
        return f"{self.server_url}/{path.lstrip('/')}"

    def _request(self, method: str, path: str, **kwargs):
        response = send_to_self_hosted(
            partial(requests.request, method),
            self._url(path),
            headers=self._headers(),
            timeout=kwargs.pop("timeout", API_TIMEOUT),
            verify=self.verify_ssl,
            **kwargs,
        )
        if response.status_code in (401, 403):
            msg = "KOReader credentials are invalid or expired"
            raise KoreaderAuthError(msg)
        return response

    def auth(self) -> bool:
        """Verify credentials against the sync server."""
        response = self._request("GET", "/users/auth", timeout=AUTH_TIMEOUT)
        if response.status_code >= HTTP_BAD_REQUEST:
            msg = f"KOReader auth failed ({response.status_code})"
            raise KoreaderAuthError(msg)
        return True

    def get_progress(self, document_hash: str) -> dict[str, Any] | None:
        """Fetch progress for one document hash."""
        if not DOCUMENT_HASH_RE.fullmatch(document_hash):
            return None
        response = self._request("GET", f"/syncs/progress/{document_hash}")
        if response.status_code == HTTP_NOT_FOUND:
            return None
        if response.status_code >= HTTP_BAD_REQUEST:
            msg = f"KOReader progress fetch failed ({response.status_code})"
            raise KoreaderClientError(msg)
        try:
            data = response.json()
        except ValueError as error:
            msg = "KOReader progress response was not JSON"
            raise KoreaderClientError(msg) from error
        if not isinstance(data, dict) or not data.get("document"):
            return None
        return data

    def list_documents(self) -> list[dict[str, Any]]:
        """Return all synced documents when the server supports listing."""
        for path in ("/syncs/documents", "/books"):
            response = self._request("GET", path)
            if response.status_code in (HTTP_NOT_FOUND, 405):
                continue
            if response.status_code >= HTTP_BAD_REQUEST:
                continue
            try:
                data = response.json()
            except ValueError:
                continue
            documents = self._normalize_document_list(data)
            if documents is not None:
                return documents
        msg = "KOReader server does not support document listing"
        raise UnsupportedListEndpointError(msg)

    def probe_list_support(self) -> bool:
        """Return True when the server exposes a document list endpoint."""
        try:
            self.list_documents()
        except UnsupportedListEndpointError:
            return False
        except KoreaderClientError:
            return False
        else:
            return True

    @staticmethod
    def _normalize_document_list(data) -> list[dict[str, Any]] | None:
        if isinstance(data, dict):
            for key in ("documents", "books", "results"):
                value = data.get(key)
                if isinstance(value, list):
                    return [entry for entry in value if isinstance(entry, dict)]
        if isinstance(data, list):
            return [entry for entry in data if isinstance(entry, dict)]
        return None


def importer(identifier, user, mode):
    """Import KOReader reading progress for a user."""
    return KoreaderImporter(user, mode).import_data()


class KoreaderImporter:
    """Import reading progress from a KOReader sync server."""

    def __init__(self, user, mode="new"):
        """Initialize importer and validate account access."""
        self.user = user
        self.mode = mode
        try:
            self.account = user.koreader_account
        except KoreaderAccount.DoesNotExist as error:
            msg = "Connect KOReader before importing"
            raise MediaImportError(msg) from error

        if not self.account.auth_key:
            msg = "Connect KOReader before importing"
            raise MediaImportError(msg)

        try:
            auth_key = decrypt_or_raise(self.account.auth_key)
        except MediaImportError as error:
            self._mark_broken(str(error))
            raise

        self.client = KoreaderClient(
            self.account.server_url,
            self.account.username,
            auth_key,
            verify_ssl=self.account.verify_ssl,
        )
        self.warnings: list[str] = []
        self.enable_provider_enrichment = not settings.TESTING

    def import_data(self):
        """Import linked documents and optionally discover new ones."""
        self.account.refresh_from_db()
        imported_counts: dict[str, int] = {
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "failed": 0,
            MediaTypes.BOOK.value: 0,
        }
        self._library_items = self._build_library_index()
        links_by_hash = {
            link.document_hash: link
            for link in KoreaderDocumentLink.objects.filter(user=self.user).select_related(
                "item",
            )
        }

        documents: list[dict[str, Any]] = []
        seen_hashes: set[str] = set()

        for document_hash, link in links_by_hash.items():
            seen_hashes.add(document_hash)
            if self._should_skip_finished_link(link):
                continue
            try:
                progress = self.client.get_progress(document_hash)
            except KoreaderAuthError as error:
                self._mark_broken(str(error))
                raise MediaImportError(str(error)) from error
            except KoreaderClientError as error:
                imported_counts["failed"] += 1
                self.warnings.append(
                    f"Could not fetch progress for {document_hash[:8]}…: {error}",
                )
                continue
            if progress:
                documents.append(progress)

        list_supported = self.client.probe_list_support()
        self.account.supports_document_list = list_supported
        if list_supported:
            try:
                listed = self.client.list_documents()
            except KoreaderClientError as error:
                self.warnings.append(f"Could not list KOReader documents: {error}")
                listed = []
            for entry in listed:
                document_hash = str(entry.get("document") or "").strip().lower()
                if not DOCUMENT_HASH_RE.fullmatch(document_hash):
                    continue
                if document_hash in seen_hashes:
                    continue
                seen_hashes.add(document_hash)
                documents.append(entry)

        total = len(documents)
        for index, entry in enumerate(documents, start=1):
            import_progress.report(index, total, "KOReader")
            document_hash = str(entry.get("document") or "").strip().lower()
            if not DOCUMENT_HASH_RE.fullmatch(document_hash):
                continue

            percentage = self._extract_percentage(entry)
            if percentage is None or percentage <= 0:
                continue

            if document_hash not in links_by_hash and not self._has_match_metadata(entry):
                self.warnings.append(
                    f"Skipped unlinked document {document_hash[:8]}… "
                    "(link it on the book track modal)",
                )
                continue

            result = self._upsert_book(entry, document_hash, percentage)
            if result is None:
                imported_counts["skipped"] += 1
                continue
            _media, created = result
            imported_counts[MediaTypes.BOOK.value] += 1
            if created:
                imported_counts["created"] += 1
            else:
                imported_counts["updated"] += 1
            if document_hash not in links_by_hash:
                links_by_hash[document_hash] = KoreaderDocumentLink.objects.get(
                    user=self.user,
                    document_hash=document_hash,
                )

        if (
            imported_counts["failed"] > 0
            and imported_counts["created"] + imported_counts["updated"] == 0
        ):
            message = "\n".join(dict.fromkeys(self.warnings)) or "KOReader import failed"
            raise MediaImportError(message)

        self.account.last_sync_at = timezone.now()
        self.account.connection_broken = False
        self.account.last_error_message = ""
        self.account.save(
            update_fields=[
                "supports_document_list",
                "last_sync_at",
                "connection_broken",
                "last_error_message",
                "updated_at",
            ],
        )
        return dict(imported_counts), "\n".join(dict.fromkeys(self.warnings))

    def _mark_broken(self, message: str):
        connection_health.record_failure(self.account, message, auth=True)

    def _should_skip_finished_link(self, link: KoreaderDocumentLink) -> bool:
        if not self.account.skip_finished_books:
            return False
        return app.models.Book.objects.filter(
            user=self.user,
            item=link.item,
            status=Status.COMPLETED.value,
        ).exists()

    def _has_match_metadata(self, entry: dict[str, Any]) -> bool:
        title, authors = self._extract_title_authors(entry)
        return bool(title or authors)

    def _extract_percentage(self, entry: dict[str, Any]) -> float | None:
        value = entry.get("percentage")
        try:
            percentage = float(value)
        except (TypeError, ValueError):
            return None
        return max(0.0, min(1.0, percentage))

    def _extract_timestamp(self, entry: dict[str, Any]):
        value = entry.get("timestamp")
        if value in (None, ""):
            return None
        try:
            ts = float(value)
        except (TypeError, ValueError):
            return None
        if ts > MILLIS_TIMESTAMP_THRESHOLD:
            ts /= 1000
        return datetime.fromtimestamp(ts, tz=UTC)

    def _extract_title_authors(self, entry: dict[str, Any]) -> tuple[str, list[str]]:
        title = str(entry.get("title") or "").strip()
        authors_raw = entry.get("authors")
        authors: list[str] = []
        if isinstance(authors_raw, str) and authors_raw.strip():
            authors = [part.strip() for part in re.split(r"[,;&]", authors_raw) if part.strip()]
        elif isinstance(authors_raw, list):
            authors = [str(value).strip() for value in authors_raw if str(value).strip()]

        if not title:
            filename = str(entry.get("filename") or "").strip()
            if filename:
                title, parsed_authors = self._parse_filename(filename)
                if not authors:
                    authors = parsed_authors
        return title, authors

    def _parse_filename(self, filename: str) -> tuple[str, list[str]]:
        base = Path(filename).stem.replace("_", " ").strip()
        if " - " in base:
            left, right = base.split(" - ", 1)
            return right.strip() or base, [left.strip()] if left.strip() else []
        return base, []

    def _upsert_book(self, entry: dict[str, Any], document_hash: str, percentage: float):
        link = KoreaderDocumentLink.objects.filter(
            user=self.user,
            document_hash=document_hash,
        ).select_related("item").first()

        if link:
            item = link.item
        else:
            title, authors = self._extract_title_authors(entry)
            if not title and not authors:
                return None
            item = self._resolve_item(title, authors)
            if item is None:
                self.warnings.append(
                    f"Could not match KOReader document {document_hash[:8]}… "
                    f"({title or 'unknown title'})",
                )
                return None
            KoreaderDocumentLink.objects.update_or_create(
                user=self.user,
                document_hash=document_hash,
                defaults={"item": item},
            )

        number_of_pages = self._resolve_number_of_pages(item)

        is_finished = percentage >= self.account.finished_threshold
        if number_of_pages:
            progress_value = (
                number_of_pages
                if is_finished
                else max(1, round(percentage * number_of_pages))
            )
        else:
            progress_value = 100 if is_finished else max(1, round(percentage * 100))

        progress_time = self._extract_timestamp(entry)
        existing = (
            app.models.Book.objects.filter(user=self.user, item=item)
            .only("progress", "status", "start_date", "end_date")
            .first()
        )
        existing_start = existing.start_date if existing else None
        existing_end = existing.end_date if existing else None
        start_date = existing_start or progress_time or timezone.now()
        if is_finished:
            status = Status.COMPLETED.value
            end_date = existing_end or progress_time or timezone.now()
        else:
            status = Status.IN_PROGRESS.value
            end_date = None

        if existing and self._book_progress_unchanged(
            existing,
            progress_value,
            status,
            end_date,
            percentage=percentage,
            number_of_pages=number_of_pages,
            is_finished=is_finished,
        ):
            return None

        media, _created = app.models.Book.objects.update_or_create(
            user=self.user,
            item=item,
            defaults={
                "progress": progress_value,
                "status": status,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        return media, existing is None

    def _resolve_number_of_pages(self, item):
        """Return the best available page count for progress conversion."""
        item.refresh_from_db(
            fields=["number_of_pages", "manual_metadata", "source", "media_type"],
        )
        if item.media_type != MediaTypes.BOOK.value:
            return None

        if custom_metadata.supports_custom_metadata(item):
            pages = custom_metadata.detail_value_for_item(item, "page_count")
            if pages:
                return int(pages)

        if item.number_of_pages:
            return item.number_of_pages

        if not self.enable_provider_enrichment:
            return None

        return self._fetch_page_count(item)

    def _book_progress_unchanged(
        self,
        existing,
        progress_value,
        status,
        end_date,
        *,
        percentage,
        number_of_pages,
        is_finished,
    ):
        if self._needs_pseudo_progress_recalc(
            existing,
            percentage,
            number_of_pages,
            is_finished,
        ):
            return False
        return (
            existing.progress == progress_value
            and existing.status == status
            and existing.end_date == end_date
        )

    def _needs_pseudo_progress_recalc(
        self,
        existing,
        percentage,
        number_of_pages,
        is_finished,
    ):
        """Detect progress stored as whole-percent before a page count existed."""
        if not number_of_pages:
            return False
        if is_finished:
            return existing.progress != number_of_pages
        page_based = max(1, round(percentage * number_of_pages))
        pseudo_based = max(1, round(percentage * 100))
        return existing.progress == pseudo_based and page_based != pseudo_based

    def _resolve_item(self, title: str, authors: list[str]):
        existing_item = self._find_existing_library_item(title, authors)
        if existing_item is not None:
            return existing_item

        if not self.account.create_missing:
            return None

        resolved = (
            self._resolve_provider_item(title, authors)
            if self.enable_provider_enrichment
            else None
        )
        if resolved:
            provider_source, provider_media_id, provider_metadata = resolved
            return self._upsert_provider_item(
                provider_source,
                provider_media_id,
                title,
                provider_metadata,
            )
        return None

    def _fetch_page_count(self, item):
        try:
            with services.interactive_request_scope():
                metadata = services.get_media_metadata(
                    item.media_type,
                    item.media_id,
                    item.source,
                )
                if (
                    item.source != Sources.MANUAL.value
                    and custom_metadata.supports_custom_metadata(item)
                    and item.manual_metadata
                ):
                    metadata = custom_metadata.build_custom_overlay_metadata(
                        metadata if isinstance(metadata, dict) else {},
                        item,
                    )
        except services.ProviderAPIError:
            return None
        except Exception:
            return None
        pages = metadata.get("max_progress") or (metadata.get("details") or {}).get(
            "number_of_pages",
        )
        if pages:
            item.number_of_pages = pages
            item.save(update_fields=["number_of_pages"])
            return pages
        return None

    def _upsert_provider_item(self, source, media_id, fallback_title, metadata):
        provider_title = metadata.get("title") or fallback_title
        title_fields = app.models.Item.title_fields_from_metadata(
            {"title": provider_title},
            fallback_title=provider_title,
        )
        details = metadata.get("details") or {}
        pages = metadata.get("max_progress") or details.get("number_of_pages")
        defaults = {
            **title_fields,
            "title": provider_title,
            "authors": self._extract_provider_authors(metadata),
            "isbn": self._normalize_list(details.get("isbn")),
            "publishers": self._first(
                details.get("publishers") or details.get("publisher"),
            ),
            "genres": self._normalize_list(metadata.get("genres")),
            "number_of_pages": pages,
            "release_datetime": app_helpers.extract_release_datetime(metadata),
            "series_name": metadata.get("series_name"),
            "series_position": metadata.get("series_position"),
            "metadata_fetched_at": timezone.now(),
        }
        image = metadata.get("image")
        if image and image != settings.IMG_NONE:
            defaults["image"] = image

        item, created = app.models.Item.objects.get_or_create(
            media_id=str(media_id),
            source=source,
            media_type=MediaTypes.BOOK.value,
            defaults=defaults,
        )
        if not created and not item.number_of_pages and pages:
            item.number_of_pages = pages
            item.save(update_fields=["number_of_pages"])
        return item

    def _build_library_index(self):
        items_by_id = {}
        books = app.models.Book.objects.filter(user=self.user).select_related("item")
        for book in books:
            items_by_id[book.item_id] = book.item
        return list(items_by_id.values())

    def _find_existing_library_item(self, title, authors):
        weak = None
        for item in getattr(self, "_library_items", []):
            if not self._titles_match(title, item.title):
                continue
            verdict = self._classify_authors(authors, item.authors or [])
            if verdict == "match":
                return item
            if verdict == "unknown" and weak is None:
                weak = item
        return weak

    def _resolve_provider_item(self, title: str, authors: list[str]):
        if not title:
            return None
        author_hint = authors[0] if authors else ""
        queries = []
        if author_hint:
            queries.append(f"{title} {author_hint}".strip())
        queries.append(title)

        best_tier, best_result = 0, None
        last_error = None
        any_success = False
        seen = set()
        for provider_source in BOOK_METADATA_PROVIDER_ORDER:
            provider_failed = False
            for query in queries:
                normalized_query = query.strip()
                if not normalized_query or (provider_source, normalized_query) in seen:
                    continue
                seen.add((provider_source, normalized_query))
                try:
                    with services.interactive_request_scope():
                        tier, result = self._match_provider_query(
                            provider_source,
                            normalized_query,
                            title,
                            authors,
                        )
                except services.ProviderAPIError as error:
                    last_error = error
                    provider_failed = True
                    break
                any_success = True
                if tier > best_tier:
                    best_tier, best_result = tier, result
                    if best_tier == 3:  # noqa: PLR2004
                        return best_result
            if provider_failed:
                continue
            if best_tier >= 2:  # noqa: PLR2004
                break

        if best_result is None and not any_success and last_error is not None:
            logger.warning(
                "KOReader metadata search failed for %r: %s",
                title,
                exception_summary(last_error),
            )
        return best_result

    def _match_provider_query(self, provider_source, query, title, authors):
        response = services.search(MediaTypes.BOOK.value, query, 1, provider_source)

        results = response.get("results", []) if isinstance(response, dict) else []
        best_tier, best_result = 0, None
        for candidate in self._title_candidates(results, title):
            media_id = candidate.get("media_id")
            if not media_id:
                continue
            try:
                metadata = services.get_media_metadata(
                    MediaTypes.BOOK.value,
                    str(media_id),
                    provider_source,
                )
            except services.ProviderAPIError as error:
                if error.status_code == HTTPStatus.TOO_MANY_REQUESTS:
                    raise
                logger.debug(
                    "KOReader metadata fetch failed provider=%s error=%s",
                    provider_source,
                    exception_summary(error),
                )
                continue
            except Exception as error:
                logger.debug(
                    "KOReader metadata fetch failed provider=%s error=%s",
                    provider_source,
                    exception_summary(error),
                )
                continue

            if not self._titles_match(title, str(metadata.get("title") or "")):
                continue

            verdict = self._author_verdict(authors, metadata)
            if verdict == "conflict":
                continue
            tier = (3 if self._has_cover(metadata) else 2) if verdict == "match" else 1
            if tier > best_tier:
                best_tier = tier
                best_result = (provider_source, str(media_id), metadata)
                if best_tier == 3:  # noqa: PLR2004
                    break
        return best_tier, best_result

    def _has_cover(self, metadata):
        image = (metadata.get("image") or "").strip()
        return bool(image) and image != settings.IMG_NONE

    def _title_candidates(self, results, title):
        scored = []
        for result in results[:5]:
            candidate_title = str(result.get("title") or "")
            if not self._titles_match(title, candidate_title):
                continue
            scored.append((self._title_similarity(title, candidate_title), result))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [result for _score, result in scored[:3]]

    def _author_verdict(self, target_authors, metadata):
        return self._classify_authors(
            target_authors,
            self._extract_provider_authors(metadata),
        )

    def _classify_authors(self, target_authors, candidate_authors):
        if not target_authors:
            return "match"
        if not candidate_authors:
            return "unknown"
        if self._authors_overlap(target_authors, candidate_authors):
            return "match"
        return "conflict"

    def _authors_overlap(self, target_authors, provider_authors):
        target = {n for n in map(self._normalize_name, target_authors) if n}
        provider = {n for n in map(self._normalize_name, provider_authors) if n}
        if not target or not provider:
            return False
        if target & provider:
            return True
        for left in target:
            for right in provider:
                if left in right or right in left:
                    return True
                if left.split()[-1] == right.split()[-1]:
                    return True
        return False

    def _titles_match(self, left, right):
        left_n = self._normalize_name(left)
        right_n = self._normalize_name(right)
        if not left_n or not right_n:
            return False
        if left_n == right_n:
            return True
        if right_n.startswith(left_n) or left_n.startswith(right_n):
            return True
        return self._title_similarity(left, right) >= TITLE_MATCH_THRESHOLD

    def _title_similarity(self, left, right):
        left_n = self._normalize_name(left)
        right_n = self._normalize_name(right)
        if not left_n or not right_n:
            return 0.0
        return SequenceMatcher(None, left_n, right_n).ratio()

    def _normalize_name(self, value):
        normalized = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
        return re.sub(r"\s+", " ", normalized).strip()

    def _extract_provider_authors(self, provider_metadata):
        details = provider_metadata.get("details", {}) if isinstance(provider_metadata, dict) else {}
        if not isinstance(details, dict):
            details = {}
        raw_authors = details.get("authors") or details.get("author") or []
        if isinstance(raw_authors, str):
            raw_authors = [part.strip() for part in raw_authors.split(",") if part.strip()]
        elif not isinstance(raw_authors, list):
            raw_authors = [raw_authors] if raw_authors else []

        authors = []
        for raw_author in raw_authors:
            if isinstance(raw_author, dict):
                value = raw_author.get("name") or raw_author.get("person")
            else:
                value = raw_author
            normalized = str(value or "").strip()
            if normalized:
                authors.append(normalized)
        return list(dict.fromkeys(authors))

    def _normalize_list(self, value):
        if value is None:
            return []
        if not isinstance(value, list):
            value = [value]
        return [str(v).strip() for v in value if str(v).strip()]

    def _first(self, value):
        if isinstance(value, list):
            value = value[0] if value else ""
        return str(value or "").strip()
