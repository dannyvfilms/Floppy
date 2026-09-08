"""Import a CLZ (Collectorz) CSV or XML export into owned collection copies.

CLZ has no fixed export schema: the user picks which columns to include
before generating the file, and custom fields can be included too. So this
importer is header-mapped rather than schema-bound. A small explicit table
maps known CLZ column labels onto built-in ``CollectionEntry`` attributes
and matching signals; every remaining column is handed to
``app.collection_field_import``, which reuses or creates a custom field for
it. Nothing in the export is dropped for lack of a place to put it.
"""

import logging
import re
from collections import defaultdict
from csv import DictReader
from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import blake2s
from io import StringIO

from defusedxml.ElementTree import parse as defused_parse
from django.db import transaction
from django.utils import timezone

from app.collection_field_import import ImportColumn, ImportedFieldResolver
from app.collection_field_import import normalize_label as normalize
from app.models import (
    CollectionEntry,
    CollectionEntrySource,
    Item,
    MediaTypes,
    Sources,
)
from app.providers import services
from integrations import import_progress
from integrations.imports import helpers
from integrations.imports.helpers import MediaImportError

logger = logging.getLogger(__name__)

SOURCE = "clz"
WISHLIST_LIST_NAME = "CLZ Wishlist"
MAX_TITLE_MATCH_RESULTS = 5

# CLZ column labels that feed a built-in CollectionEntry attribute. Keys are
# matched through ``column_key`` below, which also drops spaces, so the CSV
# header "Purchase Price" and the XML tag <purchaseprice> both land here and
# neither becomes a custom field.
ENTRY_FIELD_COLUMNS = {
    "format": "media_type",
    "media": "media_type",
    "purchaseprice": "purchase_price",
    "purchasestore": "purchase_location",
    "store": "purchase_location",
    "audiochannels": "audio_channels",
    "audiocodec": "audio_codec",
}

# Columns consumed for identification, quantity and ownership rather than
# stored on the entry. They are excluded from custom-field resolution
# because the importer already represents them structurally.
STRUCTURAL_COLUMNS = frozenset(
    {
        "title",
        "sorttitle",
        "originaltitle",
        "series",
        "issuenr",
        "issuenumber",
        "volume",
        "year",
        "releaseyear",
        "publicationyear",
        "publisher",
        "platform",
        "barcode",
        "upc",
        "ean",
        "isbn",
        "imdbnumber",
        "imdb",
        "tmdb",
        "quantity",
        "qty",
        "collectionstatus",
        "status",
        "purchasedate",
        "index",
        "id",
        "clzid",
    },
)

IDENTIFIER_COLUMNS = ("barcode", "upc", "ean", "isbn")
QUANTITY_COLUMNS = ("quantity", "qty")
RECORD_ID_COLUMNS = ("clz id", "id", "index")

_WISHLIST_TOKENS = frozenset({"wishlist", "onwishlist", "want", "notincollection"})
_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d")


def column_key(label):
    """Return the match key for a column label.

    Normalizes case, Unicode form and separators, then drops the remaining
    spaces: CLZ's CSV headers are spaced words ("Purchase Price") while its
    XML uses run-together tags (<purchaseprice>) for the same field.
    """
    return normalize(label).replace(" ", "")


def importer(file, user, mode, media_type=None):
    """Import a CLZ export for *user*. Entry point used by the import task."""
    return CLZImporter(file, user, mode, media_type=media_type).import_data()


# -- parsing ------------------------------------------------------------


def _decode(file):
    """Return the export's text, tolerating the BOM CLZ writes."""
    raw = file.read()
    if isinstance(raw, str):
        return raw.lstrip("﻿")
    for encoding in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    msg = "Could not decode the CLZ export. Save it as UTF-8 and retry."
    raise MediaImportError(msg)


def parse_csv(text):
    """Return ``(records, columns)`` for a CLZ CSV/TXT export.

    ``DictReader`` handles CLZ's quoted multiline notes fields natively, so
    embedded newlines survive intact.
    """
    sample = text[:4096]
    delimiter = "\t" if sample.count("\t") > sample.count(",") else ","
    reader = DictReader(StringIO(text), delimiter=delimiter)
    columns = [name.strip() for name in (reader.fieldnames or []) if name]
    if not columns:
        msg = "The CLZ CSV export has no header row."
        raise MediaImportError(msg)
    records = []
    for raw in reader:
        record = {}
        for name, value in raw.items():
            if name is None:
                continue
            record[name.strip()] = value
        records.append(record)
    return records, columns


def _flatten_element(element, prefix, into):
    """Flatten an XML element's descendants into ``label -> value`` pairs.

    Repeated siblings collapse into a list so multi-valued CLZ fields
    (genres, credits) survive as structured data rather than being
    overwritten by the last one.
    """
    for child in element:
        label = f"{prefix} {child.tag}".strip() if prefix else child.tag
        if len(child):
            _flatten_element(child, label, into)
            continue
        value = (child.text or "").strip()
        if not value:
            continue
        if label in into:
            existing = into[label]
            if isinstance(existing, list):
                existing.append(value)
            else:
                into[label] = [existing, value]
        else:
            into[label] = value
    for name, value in element.attrib.items():
        label = f"{prefix} {name}".strip() if prefix else name
        into.setdefault(label, value)


def parse_xml(file):
    """Return ``(records, columns)`` for a CLZ XML export.

    Parsed through ``defusedxml``, so entity expansion and external DTD or
    entity resolution are refused rather than fetched.
    """
    try:
        tree = defused_parse(file)
    except Exception as error:
        msg = f"Could not parse the CLZ XML export: {error}"
        raise MediaImportError(msg) from error

    root = tree.getroot()
    record_elements = [child for child in root if len(child)]
    if not record_elements:
        msg = "The CLZ XML export contains no records."
        raise MediaImportError(msg)

    records = []
    columns = []
    seen = set()
    for element in record_elements:
        record = {}
        _flatten_element(element, "", record)
        records.append(record)
        for name in record:
            if name not in seen:
                seen.add(name)
                columns.append(name)
    return records, columns


# -- value helpers ------------------------------------------------------


def _text(value):
    """Return a trimmed single-line-safe text form of a raw cell."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(part).strip() for part in value if str(part).strip())
    return str(value).strip()


def _parse_date(text):
    """Return a timezone-aware datetime for a CLZ date, or None."""
    candidate = _text(text).split("T")[0]
    if not candidate:
        return None
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(candidate, fmt)  # noqa: DTZ007
        except ValueError:
            continue
        return timezone.make_aware(parsed, timezone.get_default_timezone())
    return None


def _parse_price(text):
    """Return a Decimal price from a CLZ currency string, or None."""
    cleaned = re.sub(r"[^\d.,-]", "", _text(text))
    if not cleaned:
        return None
    # CLZ writes the user's locale, so treat the last separator as decimal.
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(",", "")
    elif cleaned.count(",") == 1 and len(cleaned.split(",")[-1]) <= 2:  # noqa: PLR2004
        cleaned = cleaned.replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _parse_quantity(text):
    """Return an explicit copy count, defaulting to one when absent."""
    raw = _text(text)
    if not raw:
        return 1
    match = re.search(r"\d+", raw)
    if not match:
        return 1
    return max(1, int(match.group()))


def is_wishlist(value):
    """Return whether a CLZ collection-status value means "not owned"."""
    return column_key(value) in _WISHLIST_TOKENS


# -- importer -----------------------------------------------------------


class CLZImporter:
    """Import a CLZ export into owned copies, preserving every column."""

    def __init__(self, file, user, mode, media_type=None):
        """Store the upload and the mode the run was requested with."""
        self.file = file
        self.user = user
        self.mode = mode
        self.requested_media_type = media_type
        self.warnings = []
        self.counts = defaultdict(int)
        self.import_run_id = import_progress.get_current_import_run_id()
        self.resolver = ImportedFieldResolver(
            user,
            SOURCE,
            import_run=self._import_run(),
        )
        self._column_index = {}
        self._custom_columns = []
        self._wishlist = None

    def _import_run(self):
        """Return the ImportRun this task is running under, if any."""
        if not self.import_run_id:
            return None
        from integrations.models import ImportRun

        return ImportRun.objects.filter(id=self.import_run_id).first()

    # -- entry point ----------------------------------------------------

    def import_data(self):
        """Parse the export, resolve its schema, then import every record."""
        records, columns = self._parse()
        if not records:
            return dict(self.counts), "The CLZ export contained no records."

        media_type = self.requested_media_type or self._detect_media_type(columns)
        self._build_column_index(columns)
        self._prepare_fields(records, media_type)

        total = len(records)
        for index, record in enumerate(records, start=1):
            import_progress.report(index, total, "CLZ")
            try:
                self._process_record(record, index - 1, media_type)
            except MediaImportError:
                raise
            except Exception as error:
                logger.exception("CLZ row %s failed", index)
                self.warnings.append(
                    f"Row {index} ({self._describe(record)}): {error}",
                )
                self.counts["rejected"] += 1

        messages = self.resolver.report.messages()
        messages.extend(self.warnings)
        return dict(self.counts), "\n".join(dict.fromkeys(messages))

    def _parse(self):
        """Return ``(records, columns)`` for whichever CLZ format was uploaded."""
        name = (getattr(self.file, "name", "") or "").lower()
        if name.endswith(".xml"):
            return parse_xml(self.file)
        if name.endswith(".xml.txt"):
            return parse_xml(self.file)
        text = _decode(self.file)
        if text.lstrip().startswith("<"):
            self.file.seek(0)
            return parse_xml(self.file)
        return parse_csv(text)

    # -- schema ---------------------------------------------------------

    def _detect_media_type(self, columns):
        """Infer which CLZ product produced the export from its columns."""
        present = {column_key(column) for column in columns}
        if present & {"issuenr", "issuenumber", "storyarc"}:
            return MediaTypes.COMIC_ISSUE.value
        if "platform" in present:
            return MediaTypes.GAME.value
        if present & {"isbn", "author", "authors", "pages"}:
            return MediaTypes.BOOK.value
        return MediaTypes.MOVIE.value

    def _build_column_index(self, columns):
        """Split the export's columns into structural, built-in and custom."""
        for column in columns:
            self._column_index.setdefault(column_key(column), column)
        self._custom_columns = [
            column
            for column in columns
            if column_key(column) not in STRUCTURAL_COLUMNS
            and column_key(column) not in ENTRY_FIELD_COLUMNS
        ]

    def _prepare_fields(self, records, media_type):
        """Resolve every custom column against the user's fields once."""
        if not self._custom_columns:
            return
        columns = [
            ImportColumn(
                key=column,
                label=column,
                values=[record.get(column) for record in records],
                media_types=[media_type],
            )
            for column in self._custom_columns
        ]
        self.resolver.prepare(columns)

    def _get(self, record, *labels):
        """Return the first present value among normalized column *labels*."""
        for label in labels:
            column = self._column_index.get(column_key(label))
            if column is None:
                continue
            value = _text(record.get(column))
            if value:
                return value
        return ""

    def _describe(self, record):
        """Return a short human label for a record, for diagnostics."""
        title = self._get(record, "title") or self._get(record, "series")
        issue = self._get(record, "issue nr", "issue number")
        return f"{title} #{issue}" if issue else (title or "untitled")

    # -- records --------------------------------------------------------

    def _process_record(self, record, position, media_type):
        """Import one CLZ record into copies, or into the wishlist."""
        item = self._resolve_item(record, media_type)
        if item is None:
            self.counts["rejected"] += 1
            self.warnings.append(
                f"{self._describe(record)}: no title or series to identify it by.",
            )
            return

        status = self._get(record, "collection status", "status")
        if is_wishlist(status):
            self._add_to_wishlist(item, record)
            self.counts["wishlist"] += 1
            return

        quantity = _parse_quantity(self._get(record, *QUANTITY_COLUMNS))
        entry_fields = self._entry_fields(record)
        custom_values = self.resolver.build_values(
            {column: record.get(column) for column in self._custom_columns},
            item.media_type,
        )
        collected_at = _parse_date(self._get(record, "purchase date"))
        record_id, derived = self._record_identity(record, item)

        for copy_index in range(quantity):
            self._upsert_copy(
                item=item,
                record_id=record_id,
                derived=derived,
                occurrence=position * 1000 + copy_index
                if derived
                else copy_index,
                entry_fields=entry_fields,
                custom_values=custom_values,
                collected_at=collected_at,
            )

    def _entry_fields(self, record):
        """Return the built-in CollectionEntry attributes this record sets."""
        fields = {}
        for key, attribute in ENTRY_FIELD_COLUMNS.items():
            column = self._column_index.get(key)
            if column is None:
                continue
            value = _text(record.get(column))
            if not value:
                continue
            if attribute == "purchase_price":
                price = _parse_price(value)
                if price is None:
                    self.warnings.append(
                        f"{self._describe(record)}: unreadable price {value!r}.",
                    )
                    continue
                fields[attribute] = price
            else:
                fields[attribute] = value[:100]
        return fields

    def _record_identity(self, record, item):
        """Return ``(record_id, derived)`` identifying this source record.

        Prefers CLZ's own stable record id. Otherwise derives one from
        bibliographic and edition attributes only — never from mutable
        collection values like price or storage box, so editing those in CLZ
        does not orphan the copy on the next import.
        """
        explicit = self._get(record, *RECORD_ID_COLUMNS)
        if explicit:
            return explicit[:200], False

        parts = [
            item.media_type,
            item.source,
            item.media_id,
            self._get(record, "series"),
            self._get(record, "issue nr", "issue number"),
            self._get(record, "volume"),
            self._get(record, "year", "release year", "publication year"),
            self._get(record, "publisher"),
            self._get(record, "platform"),
            self._get(record, "edition"),
            self._get(record, "variant"),
            self._get(record, "format", "media"),
            self._get(record, *IDENTIFIER_COLUMNS),
        ]
        digest = blake2s(
            "|".join(normalize(part) for part in parts).encode("utf-8"),
            digest_size=16,
        ).hexdigest()
        return digest, True

    def _upsert_copy(
        self,
        *,
        item,
        record_id,
        derived,
        occurrence,
        entry_fields,
        custom_values,
        collected_at,
    ):
        """Create or update the copy this source record owns."""
        link = (
            CollectionEntrySource.objects.select_related("entry")
            .filter(
                user=self.user,
                source=SOURCE,
                source_record_id=record_id,
                occurrence=occurrence,
            )
            .first()
        )

        if link is not None and self.mode != "overwrite":
            # Default mode imports new records only.
            self.counts["skipped"] += 1
            return

        with transaction.atomic():
            if link is not None:
                entry = link.entry
                for attribute, value in entry_fields.items():
                    setattr(entry, attribute, value)
                # Only supplied values are written, so unrelated fields and
                # anything the user edited by hand survive an overwrite.
                entry.custom_field_values = {
                    **(entry.custom_field_values or {}),
                    **custom_values,
                }
                entry.save()
                self.counts["updated"] += 1
            else:
                entry = helpers.retry_on_lock(
                    lambda: CollectionEntry.objects.create(
                        user=self.user,
                        item=item,
                        custom_field_values=custom_values,
                        **entry_fields,
                    ),
                )
                CollectionEntrySource.objects.create(
                    user=self.user,
                    source=SOURCE,
                    source_record_id=record_id,
                    occurrence=occurrence,
                    derived_identity=derived,
                    entry=entry,
                    created_by_import_run_id=self.import_run_id,
                )
                self.counts["collection"] += 1

            if collected_at:
                # collected_at is auto_now_add, so it must be set post-save.
                CollectionEntry.objects.filter(id=entry.id).update(
                    collected_at=collected_at,
                )

    # -- media resolution -----------------------------------------------

    def _resolve_item(self, record, media_type):
        """Resolve a record to an Item, falling back to a custom item."""
        explicit = self._explicit_item(record, media_type)
        if explicit is not None:
            return explicit

        identifier = self._get(record, *IDENTIFIER_COLUMNS)
        if identifier:
            matched = self._search_item(record, media_type, identifier)
            if matched is not None:
                return matched

        matched = self._title_item(record, media_type)
        if matched is not None:
            return matched

        return self._custom_item(record, media_type)

    def _explicit_item(self, record, media_type):
        """Return an Item built from an explicit provider id, if present."""
        imdb_id = self._get(record, "imdb number", "imdb")
        if imdb_id and imdb_id.startswith("tt"):
            return self._item_for(Sources.IMDB.value, imdb_id, record, media_type)
        tmdb_id = self._get(record, "tmdb")
        if tmdb_id.isdigit():
            return self._item_for(Sources.TMDB.value, tmdb_id, record, media_type)
        return None

    def _item_for(self, source, media_id, record, media_type):
        """Get or create the Item for an explicit provider identifier."""
        item, _ = Item.objects.get_or_create(
            media_id=media_id,
            source=source,
            media_type=media_type,
            library_media_type=media_type,
            season_number=None,
            episode_number=None,
            defaults={"title": self._title(record), "image": ""},
        )
        return item

    def _search_item(self, record, media_type, query):
        """Return the single provider result for *query*, or None."""
        try:
            results = services.search(media_type, query, 1).get("results", [])
        except Exception as error:
            logger.debug("CLZ lookup failed for %r: %s", query, error)
            return None
        if len(results) != 1:
            return None
        return self._item_from_result(results[0], media_type)

    def _title_item(self, record, media_type):
        """Return a title match only when corroborated by other columns.

        A bare title match is not enough: the result must also agree with the
        year, or with the issue/volume the export names, or the record is
        preserved as a custom item instead of guessed at.
        """
        title = self._title(record)
        if not title:
            return None
        corroboration = self._get(
            record,
            "year",
            "release year",
            "publication year",
        ) or self._get(record, "issue nr", "issue number", "volume")
        if not corroboration:
            return None

        try:
            results = services.search(media_type, title, 1).get("results", [])
        except Exception as error:
            logger.debug("CLZ title search failed for %r: %s", title, error)
            return None

        matches = [
            result
            for result in results[:MAX_TITLE_MATCH_RESULTS]
            if normalize(result.get("title", "")) == normalize(title)
            and corroboration in str(result.get("details", {}))
            + str(result.get("release_date", ""))
        ]
        if len(matches) != 1:
            return None
        return self._item_from_result(matches[0], media_type)

    def _item_from_result(self, result, media_type):
        """Get or create the Item backing a provider search result."""
        item, _ = Item.objects.get_or_create(
            media_id=str(result["media_id"]),
            source=result.get("source", Sources.TMDB.value),
            media_type=media_type,
            library_media_type=media_type,
            season_number=None,
            episode_number=None,
            defaults={
                "title": result.get("title", ""),
                "image": result.get("image", ""),
            },
        )
        return item

    def _custom_item(self, record, media_type):
        """Preserve an unmatched record as a manual item.

        Comics keep their issue identity and books/manga keep their volume,
        rather than collapsing into one row for the whole series.
        """
        title = self._title(record)
        if not title:
            return None
        existing = Item.objects.filter(
            source=Sources.MANUAL.value,
            media_type=media_type,
            library_media_type=media_type,
            title=title,
        ).first()
        if existing is not None:
            return existing
        return Item.objects.create(
            media_id=Item.generate_manual_id(),
            source=Sources.MANUAL.value,
            media_type=media_type,
            library_media_type=media_type,
            title=title,
            image="",
        )

    def _title(self, record):
        """Return the display title for a record.

        Comic and volume-based rows carry the issue or volume in the title so
        two issues of one series stay distinguishable.
        """
        title = self._get(record, "title")
        series = self._get(record, "series")
        issue = self._get(record, "issue nr", "issue number")
        volume = self._get(record, "volume")

        base = title or series
        if not base:
            return ""
        if series and issue:
            return f"{series} #{issue}"
        if series and volume and not title:
            return f"{series} Vol. {volume}"
        return base

    # -- wishlist -------------------------------------------------------

    def _add_to_wishlist(self, item, record):
        """Add an unowned record to the dedicated CLZ wishlist list.

        No copy is created and no reading progress is inferred; the source
        columns are still preserved through the custom fields.
        """
        from lists.models import CustomList, CustomListItem

        if self._wishlist is None:
            self._wishlist, _ = CustomList.objects.get_or_create(
                name=WISHLIST_LIST_NAME,
                owner=self.user,
                defaults={
                    "description": "Wishlist records imported from CLZ.",
                },
            )
        CustomListItem.objects.get_or_create(
            custom_list=self._wishlist,
            item=item,
            defaults={"added_by": self.user},
        )
        logger.debug("CLZ wishlist row kept for %s", self._describe(record))
