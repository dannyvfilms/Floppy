"""Kavita importer for manga, comic and book reading progress.

Verified against Kavita's OpenAPI file (v0.9.1.6): an API key is exchanged for
a JWT at ``/api/Plugin/authenticate``, series come from ``/api/Series/all-v2``
with their MyAnimeList and Comic Vine ids, and chapters (with pages read) from
``/api/Series/series-detail``. Comic identities are enriched from Comic Vine
before their local progress rows are written. Nothing is written back to
Kavita.
"""

import logging
import re
from http import HTTPStatus

from django.conf import settings
from django.utils import timezone

import app
from app import metadata_utils
from app.models import Item, MediaTypes, Sources
from app.providers import comicvine, services
from app.services import metadata_resolution
from app.services.item_merge import merge_item
from integrations.imports.helpers import (
    ConnectionAuthError,
    find_item_across_buckets,
)
from integrations.imports.reading_server import (
    ReadingServerImporter,
    parse_datetime,
    request_json,
    write_reading_progress,
)
from integrations.models import KavitaAccount, KavitaLink

logger = logging.getLogger(__name__)

ENTRY_SOURCE = "kavita"
PLUGIN_NAME = "Floppy"
PAGE_SIZE = 100

# Kavita's LibraryType enum.
MANGA_LIBRARY = 0
COMIC_LIBRARIES = frozenset({1, 5})
BOOK_LIBRARIES = frozenset({2, 4})  # Book and LightNovel are both epubs

# SeriesFilterField.ReadProgress > 0, sorted by name so paging is stable.
READ_PROGRESS_FIELD = 20
GREATER_THAN = 1
AND_COMBINATION = 1
SORT_BY_NAME = 1


class KavitaClient:
    """Thin API client for the Kavita REST API."""

    def __init__(self, base_url: str, api_key: str):
        """Store the server URL and API key."""
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._token = None

    def _request(self, method, path, **kwargs):
        headers = {"Authorization": f"Bearer {self._authenticate()}"}
        return request_json(
            "Kavita",
            method,
            f"{self.base_url}{path}",
            headers=headers,
            **kwargs,
        )

    def _authenticate(self):
        """Exchange the API key for a short-lived token, once per run."""
        if self._token is None:
            payload = request_json(
                "Kavita",
                "post",
                f"{self.base_url}/api/Plugin/authenticate",
                params={"apiKey": self.api_key, "pluginName": PLUGIN_NAME},
            )
            self._token = (payload or {}).get("token")
            if not self._token:
                msg = "Kavita API key is invalid or unauthorized"
                raise ConnectionAuthError(msg)
        return self._token

    def healthcheck(self):
        """Verify the server is reachable and the key is accepted."""
        self._authenticate()

    def series_with_progress(self):
        """Yield every series the user has started reading."""
        body = {
            "statements": [
                {
                    "comparison": GREATER_THAN,
                    "field": READ_PROGRESS_FIELD,
                    "value": "0",
                },
            ],
            "combination": AND_COMBINATION,
            "sortOptions": {"sortField": SORT_BY_NAME, "isAscending": True},
            "limitTo": 0,
        }
        page = 1
        while True:
            series = self._request(
                "post",
                "/api/Series/all-v2",
                params={"PageNumber": page, "PageSize": PAGE_SIZE},
                json=body,
            )
            yield from series or []
            if len(series or []) < PAGE_SIZE:
                return
            page += 1

    def series_detail(self, series_id):
        """Return a series' volumes and chapters with the user's progress."""
        return self._request(
            "get",
            "/api/Series/series-detail",
            params={"seriesId": series_id},
        )

    def series_metadata(self, series_id):
        """Return editable series metadata, including external web links."""
        return self._request(
            "get",
            "/api/Series/metadata",
            params={"seriesId": series_id},
        )

    def chapter_metadata(self, chapter_id):
        """Return chapter metadata, including its Comic Vine identity."""
        return self._request(
            "get",
            "/api/Chapter",
            params={"chapterId": chapter_id},
        )


def importer(identifier, user, mode):
    """Import Kavita reading progress for a user."""
    importer_instance = KavitaImporter(user)
    if mode == "overwrite":
        importer_instance.account.last_sync_at = None
        importer_instance.account.save(update_fields=["last_sync_at"])
    return importer_instance.import_data()


def mal_manga_item(mal_id, title):
    """Return the MyAnimeList manga Item, creating it from Kavita's data.

    The MAL id is the identity, so no provider lookup is needed; the details
    page fills in the rest the first time it is opened.
    """
    identity = {
        "media_id": str(mal_id),
        "source": Sources.MAL.value,
        "media_type": MediaTypes.MANGA.value,
    }
    existing = find_item_across_buckets(**identity)
    if existing:
        return existing
    item, _ = Item.objects.get_or_create(
        **identity,
        library_media_type=MediaTypes.MANGA.value,
        season_number=None,
        episode_number=None,
        defaults={
            "title": title,
            "original_title": title,
            "localized_title": title,
            "image": settings.IMG_NONE,
        },
    )
    return item


def _chapters(detail):
    """Return each chapter of a series once (volumes, loose chapters, specials)."""
    chapters = {}
    for volume in detail.get("volumes") or []:
        for chapter in volume.get("chapters") or []:
            chapters[chapter.get("id")] = chapter
    for chapter in [*(detail.get("chapters") or []), *(detail.get("specials") or [])]:
        chapters.setdefault(chapter.get("id"), chapter)
    return list(chapters.values())


def _is_read(chapter):
    pages = int(chapter.get("pages") or 0)
    return pages > 0 and int(chapter.get("pagesRead") or 0) >= pages


def _normalized_title(value):
    """Normalize a title for conservative provider-search matching."""
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _issue_number(value):
    """Return the leading issue number from a Kavita issue label."""
    match = re.match(r"\s*(\d+(?:\.\d+)?)", str(value or ""))
    return match.group(1) if match else ""


def _comicvine_id(value, resource_prefix):
    """Normalize a Comic Vine ID or URL from Kavita."""
    normalized = str(value or "").strip()
    match = re.search(
        rf"/(?:volume|issue)/{resource_prefix}-(\d+)",
        normalized,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1)
    prefix = f"{resource_prefix}-"
    return normalized.removeprefix(prefix)


def _comicvine_id_from_links(value, resource_prefix):
    """Extract a Comic Vine identity from Kavita's comma-separated links."""
    for link in str(value or "").split(","):
        media_id = _comicvine_id(link.strip(), resource_prefix)
        if media_id and media_id != link.strip():
            return media_id
    return None


def _search_volume_id(title, user):
    """Return a ComicVine volume ID only for a unique title match."""
    results = comicvine.search(title, 1, user=user).get("results", [])
    matches = [
        result
        for result in results
        if _normalized_title(result.get("title")) == _normalized_title(title)
    ]
    return str(matches[0]["media_id"]) if len(matches) == 1 else None


def _search_issue_id(series_title, issue_number, user):
    """Return a ComicVine issue ID only for a matching volume and number."""
    results = comicvine.search_issues(
        f"{series_title} {issue_number}",
        1,
        user=user,
    ).get("results", [])
    expected_title = _normalized_title(series_title)
    matches = []
    for result in results:
        title = str(result.get("title") or "")
        match = re.match(r"^(.*?)\s+#\s*([0-9.]+)", title)
        if (
            match
            and _normalized_title(match.group(1)) == expected_title
            and match.group(2) == str(issue_number).strip()
        ):
            matches.append(result)
    return str(matches[0]["media_id"]) if len(matches) == 1 else None


def _volume_issue_id(volume_id, issue_number, user):
    """Return an exact issue from a known Comic Vine volume."""
    expected = str(issue_number).strip().lstrip("0") or "0"
    matches = []
    for issue in comicvine.get_volume_issues(volume_id, user=user):
        number = str(issue.get("issue_number") or "").strip().lstrip("0") or "0"
        if number == expected:
            matches.append(issue)
    return str(matches[0]["media_id"]) if len(matches) == 1 else None


def _apply_provider_metadata(item, metadata):
    """Persist normalized provider metadata on a resolved Kavita item."""
    title_fields = Item.title_fields_from_metadata(metadata, fallback_title=item.title)
    update_fields = []
    for field, value in title_fields.items():
        if getattr(item, field) != value:
            setattr(item, field, value)
            update_fields.append(field)
    image = metadata.get("image") or settings.IMG_NONE
    if item.image != image:
        item.image = image
        update_fields.append("image")
    update_fields.extend(metadata_utils.apply_item_metadata(item, metadata))
    if update_fields:
        item.metadata_fetched_at = timezone.now()
        update_fields.append("metadata_fetched_at")
        item.save(update_fields=list(dict.fromkeys(update_fields)))
    metadata_resolution.upsert_provider_links(
        item,
        metadata,
        provider=Sources.COMICVINE.value,
        provider_media_type=item.media_type,
    )


def _provider_item(media_id, media_type, title, user, enrich):
    """Resolve a ComicVine identity and optionally persist its metadata."""
    identity = {
        "media_id": str(media_id),
        "source": Sources.COMICVINE.value,
        "media_type": media_type.value,
    }
    item = find_item_across_buckets(**identity)
    if item is None:
        metadata = None
        if enrich:
            metadata = services.get_media_metadata(
                media_type.value,
                str(media_id),
                Sources.COMICVINE.value,
                user=user,
            )
        item = Item.objects.create(
            **identity,
            library_media_type=media_type.value,
            season_number=None,
            episode_number=None,
            title=title,
            original_title=title,
            localized_title=title,
            image=settings.IMG_NONE,
        )
        if metadata:
            _apply_provider_metadata(item, metadata)
    elif enrich and (item.metadata_fetched_at is None or not item.synopsis):
        metadata = services.get_media_metadata(
            media_type.value,
            str(media_id),
            Sources.COMICVINE.value,
            user=user,
        )
        _apply_provider_metadata(item, metadata)
    model = app.models.Item
    tracking_model = {
        MediaTypes.COMIC.value: app.models.Comic,
        MediaTypes.COMIC_ISSUE.value: app.models.ComicIssue,
    }.get(media_type.value)
    if tracking_model is not None:
        manual_items = model.objects.filter(
            source=Sources.MANUAL.value,
            media_type=media_type.value,
            title__iexact=title,
        ).exclude(pk=item.pk)
        tracked = tracking_model.objects.filter(user=user, item__in=manual_items)
        for manual in manual_items.filter(pk__in=tracked.values("item_id")):
            merge_item(manual, item)
    return item


def _provider_unavailable(error):
    """Return whether a provider error is a transient connectivity failure."""
    return isinstance(error, services.ProviderAPIError) and error.status_code is None


def _provider_not_found(error):
    """Return whether a provider failure confirms an unknown identity."""
    return isinstance(error, services.ProviderAPIError) and (
        error.status_code == HTTPStatus.NOT_FOUND
        or getattr(error, "confirmed_absent", False)
    )


class KavitaImporter(ReadingServerImporter):
    """Import reading progress from Kavita."""

    service = "Kavita"
    account_attr = "kavita_account"
    account_model = KavitaAccount
    link_model = KavitaLink
    link_field = "kavita_key"
    client_class = KavitaClient

    def __init__(self, user):
        """Initialize the importer and its deferred retry state."""
        super().__init__(user)
        self._retrying = False

    def sync(self, cutoff, counts, links):
        """Import every started series read after the cutoff."""
        for series in self.client.series_with_progress():
            read_at = parse_datetime(series.get("latestReadDate"))
            if cutoff and read_at and read_at < cutoff:
                continue
            self._import_series(series, read_at or timezone.now(), links, counts)

    def _import_series(self, series, read_at, links, counts):
        """Write one series' progress as a manga, book or comic issues."""
        detail = self.client.series_detail(series["id"])
        library_type = detail.get("libraryType")
        chapters = _chapters(detail)
        if library_type == MANGA_LIBRARY:
            self._import_manga(series, chapters, read_at, links, counts)
        elif library_type in BOOK_LIBRARIES:
            self._import_book(series, chapters, read_at, links, counts)
        elif library_type in COMIC_LIBRARIES:
            if self.enable_provider_enrichment and not series.get("comicVineId"):
                metadata = self.client.series_metadata(series["id"])
                series["comicVineId"] = _comicvine_id_from_links(
                    metadata.get("webLinks"),
                    4050,
                )
            self._import_comic_series(series, chapters, read_at, links, counts)
            for chapter in chapters:
                if int(chapter.get("pagesRead") or 0) > 0:
                    if self.enable_provider_enrichment and not chapter.get("comicVineId"):
                        metadata = self.client.chapter_metadata(chapter["id"])
                        chapter["comicVineId"] = metadata.get("comicVineId")
                        if not chapter["comicVineId"]:
                            chapter["comicVineId"] = _comicvine_id_from_links(
                                metadata.get("webLinks"),
                                4000,
                            )
                    self._import_comic_issue(series, chapter, read_at, links, counts)

    def _import_comic_series(self, series, chapters, read_at, links, counts):
        """Track the Kavita comic series by its read-issue count."""
        title = series.get("name") or ""
        volume_id = series.get("comicVineId")
        provider_matching_failed = False
        if not volume_id and self.enable_provider_enrichment and title:
            try:
                volume_id = _search_volume_id(title, self.user)
            except services.ProviderAPIError as error:
                if not _provider_unavailable(error):
                    raise
                provider_matching_failed = True
                logger.warning("Comic Vine unavailable while matching series %s", title)
                self.warnings.append(
                    f"Comic Vine unavailable; skipped Kavita series {title}",
                )

        volume_id = _comicvine_id(volume_id, 4050)

        def resolve():
            if provider_matching_failed:
                return None
            provider_enrichment_failed = False
            if volume_id:
                try:
                    return _provider_item(
                        volume_id,
                        MediaTypes.COMIC,
                        title,
                        self.user,
                        self.enable_provider_enrichment,
                    )
                except services.ProviderAPIError as error:
                    if _provider_unavailable(error):
                        logger.warning(
                            "Comic Vine unavailable while enriching series %s",
                            title,
                        )
                        self.warnings.append(
                            f"Comic Vine unavailable; skipped Kavita series {title}",
                        )
                        provider_enrichment_failed = True
                    elif not _provider_not_found(error):
                        raise
            if provider_enrichment_failed:
                return None
            if self.account.create_missing and title and not self._retrying:
                self._retry_entries.append(
                    (
                        links,
                        f"series:{series['id']}",
                        title,
                        counts,
                        MediaTypes.COMIC,
                        resolve,
                        lambda item: write_reading_progress(
                            self.user,
                            item,
                            app.models.Comic,
                            progress=read_count,
                            completed=completed,
                            read_at=read_at,
                            started_at=None,
                            entry_source=ENTRY_SOURCE,
                        ),
                    ),
                )
                return None
            return None

        read_count = sum(1 for chapter in chapters if _is_read(chapter))
        pages = int(series.get("pages") or 0)
        page = int(series.get("pagesRead") or 0)
        completed = pages > 0 and page >= pages
        self.import_entry(
            links,
            f"series:{series['id']}",
            title,
            counts,
            MediaTypes.COMIC,
            resolve,
            lambda item: write_reading_progress(
                self.user,
                item,
                app.models.Comic,
                progress=read_count,
                completed=completed,
                read_at=read_at,
                started_at=None,
                entry_source=ENTRY_SOURCE,
            ),
        )

    def _import_manga(self, series, chapters, read_at, links, counts):
        """Track a manga series by its chapters read."""
        title = series.get("name") or ""
        read = [chapter for chapter in chapters if _is_read(chapter)]
        # Chapter numbers when Kavita has them, else volumes read.
        progress = max((int(c.get("maxNumber") or 0) for c in read), default=0) or len(
            read,
        )
        pages = int(series.get("pages") or 0)
        completed = pages > 0 and int(series.get("pagesRead") or 0) >= pages
        mal_id = int(series.get("malId") or 0)

        def resolve():
            if mal_id:
                return mal_manga_item(mal_id, title)
            if not self.account.create_missing or not title:
                return None
            return self.manual_item(MediaTypes.MANGA, title)

        self.import_entry(
            links,
            f"series:{series['id']}",
            title,
            counts,
            MediaTypes.MANGA,
            resolve,
            lambda item: write_reading_progress(
                self.user,
                item,
                app.models.Manga,
                progress=progress,
                completed=completed,
                read_at=read_at,
                started_at=None,
                entry_source=ENTRY_SOURCE,
            ),
        )

    def _import_book(self, series, chapters, read_at, links, counts):
        """Track a book (epub) series by pages read."""
        title = series.get("name") or ""
        pages = int(series.get("pages") or 0)
        page = int(series.get("pagesRead") or 0)
        completed = pages > 0 and page >= pages
        authors = list(
            dict.fromkeys(
                writer["name"]
                for chapter in chapters
                for writer in chapter.get("writers") or []
                if writer.get("name")
            ),
        )
        isbn = next((c["isbn"] for c in chapters if c.get("isbn")), "")

        self.import_entry(
            links,
            f"series:{series['id']}",
            title,
            counts,
            MediaTypes.BOOK,
            lambda: self.resolve_book_item(title, authors, isbn),
            lambda item: write_reading_progress(
                self.user,
                item,
                app.models.Book,
                progress=max(pages, page) if completed else page,
                completed=completed,
                read_at=read_at,
                started_at=None,
                entry_source=ENTRY_SOURCE,
            ),
        )

    def _import_comic_issue(self, series, chapter, read_at, links, counts):
        """Track one comic chapter as a comic issue."""
        number = chapter.get("range") or chapter.get("number")
        series_name = series.get("name") or ""
        label = (
            f"{series_name} #{number}"
            if series_name and number
            else chapter.get("titleName") or series_name
        )
        pages = int(chapter.get("pages") or 0)
        page = int(chapter.get("pagesRead") or 0)
        completed = _is_read(chapter)

        def resolve():
            existing = (
                app.models.Item.objects.filter(
                    media_type=MediaTypes.COMIC_ISSUE.value,
                    title__iexact=label,
                )
                .order_by("id")
                .first()
            )
            if existing:
                return existing
            issue_id = chapter.get("comicVineId")
            if (
                not issue_id
                and self.enable_provider_enrichment
                and series_name
                and number
            ):
                try:
                    volume_id = _comicvine_id(series.get("comicVineId"), 4050)
                    if volume_id:
                        issue_id = _volume_issue_id(volume_id, number, self.user)
                    if not issue_id:
                        issue_id = _search_issue_id(
                            series_name,
                            number,
                            self.user,
                        )
                except services.ProviderAPIError as error:
                    if not _provider_unavailable(error):
                        raise
                    logger.warning(
                        "Comic Vine unavailable while matching issue %s",
                        label,
                    )
                    self.warnings.append(
                        f"Comic Vine unavailable; skipped Kavita issue {label}",
                    )
                    return None
            issue_id = _comicvine_id(issue_id, 4000)
            item = None
            provider_enrichment_failed = False
            if issue_id:
                try:
                    item = _provider_item(
                        issue_id,
                        MediaTypes.COMIC_ISSUE,
                        label,
                        self.user,
                        self.enable_provider_enrichment,
                    )
                except services.ProviderAPIError as error:
                    if _provider_unavailable(error):
                        logger.warning(
                            "Comic Vine unavailable while enriching issue %s",
                            label,
                        )
                        self.warnings.append(
                            f"Comic Vine unavailable; skipped Kavita issue {label}",
                        )
                        provider_enrichment_failed = True
                    elif not _provider_not_found(error):
                        raise
            if provider_enrichment_failed:
                return None
            # Do not create title-only issue items when Comic Vine cannot
            # identify the chapter; those placeholders are easy to mis-match.
            return item

        self.import_entry(
            links,
            f"chapter:{chapter['id']}",
            label,
            counts,
            MediaTypes.COMIC_ISSUE,
            resolve,
            lambda item: write_reading_progress(
                self.user,
                item,
                app.models.ComicIssue,
                progress=max(pages, page) if completed else page,
                completed=completed,
                read_at=parse_datetime(chapter.get("lastReadingProgressUtc"))
                or read_at,
                started_at=None,
                entry_source=ENTRY_SOURCE,
            ),
        )
