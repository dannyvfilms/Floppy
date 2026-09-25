"""Import a CLZ (Collectorz) CSV or XML export into owned collection copies.

CLZ has no fixed export schema: the user picks which columns to include
before generating the file, and custom fields can be included too. So this
importer is header-mapped rather than schema-bound. A small explicit table
maps known CLZ column labels onto built-in ``CollectionEntry`` attributes
and matching signals; every remaining column is handed to
``app.collection_field_import``, which reuses or creates a custom field for
it. Nothing in the export is dropped for lack of a place to put it.
"""

import json
import logging
import re
from collections import defaultdict
from contextlib import contextmanager
from csv import DictReader
from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import blake2s
from io import StringIO, TextIOWrapper
from tempfile import TemporaryFile

from defusedxml.ElementTree import iterparse as defused_iterparse
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
        "issue",
        "issuenr",
        "issuenumber",
        "issueno",
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
# CLZ Comics heads its issue column "Issue"; other exports use "Issue Nr".
ISSUE_COLUMNS = ("issue nr", "issue number", "issue no", "issue")
# What versions before issue #809 read, kept only to recognise their links.
LEGACY_ISSUE_COLUMNS = ("issue nr", "issue number")
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


def _read_records(file):
    """Read one repeatable pass over the disk-backed export."""
    file.seek(0)
    for line in file:
        yield json.loads(line)


def _column_values(file, column):
    """Yield one column for exact streaming field inference."""
    for record in _read_records(file):
        yield record.get(column)


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


def parse_xml(file, sink=None):
    """Parse safe XML, optionally writing records to disk as they complete."""
    records = []
    columns = []
    seen = set()
    count = 0
    try:
        depth = 0
        root = None
        for event, element in defused_iterparse(file, events=("start", "end")):
            if event == "start":
                depth += 1
                if root is None:
                    root = element
                continue
            if depth == 2:  # noqa: PLR2004
                if len(element):
                    record = {}
                    _flatten_element(element, "", record)
                    if sink is None:
                        records.append(record)
                    else:
                        sink.write(json.dumps(record) + "\n")
                    count += 1
                    for name in record:
                        if name not in seen:
                            seen.add(name)
                            columns.append(name)
                root.remove(element)
            depth -= 1
    except Exception as error:
        msg = f"Could not parse the CLZ XML export: {error}"
        raise MediaImportError(msg) from error
    if not count:
        msg = "The CLZ XML export contains no records."
        raise MediaImportError(msg)
    return (records if sink is None else count), columns


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
        self._legacy_links = None
        self._legacy_items = ()
        self._legacy_media_type = None

    def _import_run(self):
        """Return the ImportRun this task is running under, if any."""
        if not self.import_run_id:
            return None
        from integrations.models import ImportRun

        return ImportRun.objects.filter(id=self.import_run_id).first()

    # -- entry point ----------------------------------------------------

    def import_data(self):
        """Parse the export, resolve its schema, then import every record."""
        with self._parse_staged() as (records, columns, total):
            return self._import_records(records, columns, total)

    def _import_records(self, records, columns, total):
        """Import validated disk-staged records without retaining the export."""
        if not total:
            return dict(self.counts), "The CLZ export contained no records."

        media_type = self.requested_media_type or self._detect_media_type(columns)
        self._legacy_media_type = _legacy_detect_media_type(columns)
        self._build_column_index(columns)
        self._prepare_fields(records, media_type)

        for index, record in enumerate(_read_records(records), start=1):
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

    @contextmanager
    def _parse_staged(self):
        """Validate decoding before writes and stage repeatable rows on disk."""
        if isinstance(self.file.read(0), str):
            original = self.file
            with TemporaryFile() as binary:
                for chunk in iter(lambda: original.read(65536), ""):
                    binary.write(chunk.encode("utf-8"))
                binary.seek(0)
                self.file = binary
                try:
                    with self._parse_staged() as staged:
                        yield staged
                finally:
                    self.file = original
            return
        with TemporaryFile(mode="w+", encoding="utf-8") as records:
            name = (getattr(self.file, "name", "") or "").lower()
            if name.endswith((".xml", ".xml.txt")):
                total, columns = parse_xml(self.file, records)
                yield records, columns, total
                return
            else:
                # Validate incrementally before selecting an encoding: a late
                # decoding failure must not leave partially imported records.
                encoding = None
                for candidate in ("utf-8-sig", "utf-16", "cp1252"):
                    self.file.seek(0)
                    wrapper = TextIOWrapper(self.file, encoding=candidate, newline="")
                    try:
                        while wrapper.read(65536):
                            pass
                        encoding = candidate
                        break
                    except UnicodeError:
                        continue
                    finally:
                        wrapper.detach()
                if encoding is None:
                    msg = "Could not decode the CLZ export. Save it as UTF-8 and retry."
                    raise MediaImportError(msg)
                self.file.seek(0)
                wrapper = TextIOWrapper(self.file, encoding=encoding, newline="")
                try:
                    sample = wrapper.read(4096)
                    wrapper.seek(0)
                    if sample.lstrip().startswith("<"):
                        total, columns = parse_xml(wrapper, records)
                        yield records, columns, total
                        return
                    else:
                        delimiter = (
                            "\t" if sample.count("\t") > sample.count(",") else ","
                        )
                        reader = DictReader(wrapper, delimiter=delimiter)
                        columns = [
                            name.strip() for name in (reader.fieldnames or []) if name
                        ]
                        if not columns:
                            msg = "The CLZ CSV export has no header row."
                            raise MediaImportError(msg)
                        rows = (
                            {
                                name.strip(): value
                                for name, value in raw.items()
                                if name is not None
                            }
                            for raw in reader
                        )
                    total = 0
                    for row in rows:
                        records.write(json.dumps(row) + "\n")
                        total += 1
                finally:
                    wrapper.detach()
                yield records, columns, total
                return

    # -- schema ---------------------------------------------------------

    def _detect_media_type(self, columns):
        """Infer which CLZ product produced the export from its columns."""
        present = {column_key(column) for column in columns}
        if present & {"issue", "issuenr", "issuenumber", "issueno", "storyarc"}:
            return MediaTypes.COMIC_ISSUE.value
        if "platform" in present:
            return MediaTypes.GAME.value
        if present & {"isbn", "author", "authors", "pages"}:
            return MediaTypes.BOOK.value
        if not present & {"imdb", "imdbnumber", "tmdb", "director", "runtime"}:
            self.warnings.append(
                "Could not tell what this CLZ export contains, so it was "
                "imported as movies. Choose the type under Import as and "
                "re-import in Overwrite mode to correct it.",
            )
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
                values=_column_values(records, column),
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
        issue = self._get(record, *ISSUE_COLUMNS)
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
            self._add_to_wishlist(item, record, media_type)
            self.counts["wishlist"] += 1
            return

        quantity = _parse_quantity(self._get(record, *QUANTITY_COLUMNS))
        entry_fields = self._entry_fields(record)
        custom_values = self.resolver.build_values(
            {column: record.get(column) for column in self._custom_columns},
            item.media_type,
        )
        collected_at = _parse_date(self._get(record, "purchase date"))
        record_id, derived = self._record_identity(record)

        for copy_index in range(quantity):
            self._upsert_copy(
                record=record,
                item=item,
                record_id=record_id,
                derived=derived,
                occurrence=position * 1000 + copy_index if derived else copy_index,
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

    def _record_identity(self, record):
        """Return ``(record_id, derived)`` identifying this source record.

        Prefers CLZ's own stable record id. Otherwise derives one from
        bibliographic and edition attributes only — never from mutable
        collection values like price or storage box, so editing those in CLZ
        does not orphan the copy on the next import, and never from the item
        it resolved to, so importing it as a different media type still
        finds the same copy.
        """
        explicit = self._get(record, *RECORD_ID_COLUMNS)
        if explicit:
            return explicit[:200], False
        return _digest([self._get(record, "title"), *self._edition_parts(record)]), True

    def _edition_parts(self, record, issue_columns=ISSUE_COLUMNS):
        """Return the bibliographic and edition values a derived id hashes."""
        return [
            self._get(record, "series"),
            self._get(record, *issue_columns),
            self._get(record, "volume"),
            self._get(record, "year", "release year", "publication year"),
            self._get(record, "publisher"),
            self._get(record, "platform"),
            self._get(record, "edition"),
            self._get(record, "variant"),
            self._get(record, "format", "media"),
            self._get(record, *IDENTIFIER_COLUMNS),
        ]

    def _find_link(self, record, record_id, derived, occurrence):
        """Return the link for this source record, re-keying an old one.

        Versions before issue #809 hashed the resolved item into derived
        ids, so an export imported under the wrong media type could not be
        found again once the type was corrected. Such a link is recognised
        by recomputing that old id for each item this user's CLZ copies sit
        on, then moved to the current id so the lookup happens only once.
        """
        links = CollectionEntrySource.objects.select_related("entry").filter(
            user=self.user,
            source=SOURCE,
        )
        link = links.filter(
            source_record_id=record_id,
            occurrence=occurrence,
        ).first()
        if link is not None or not derived:
            return link

        if self._legacy_links is None:
            self._legacy_links = {
                (source_record_id, link_occurrence): link_id
                for link_id, source_record_id, link_occurrence in links.filter(
                    derived_identity=True,
                ).values_list("id", "source_record_id", "occurrence")
            }
            self._legacy_items = set(
                links.filter(derived_identity=True).values_list(
                    "entry__item__media_type",
                    "entry__item__source",
                    "entry__item__media_id",
                ),
            )
        rest = self._edition_parts(record, LEGACY_ISSUE_COLUMNS)
        for item_parts in self._legacy_items:
            link_id = self._legacy_links.pop(
                (_digest([*item_parts, *rest]), occurrence),
                None,
            )
            if link_id is not None:
                link = links.get(id=link_id)
                link.source_record_id = record_id
                link.save(update_fields=["source_record_id"])
                return link
        return None

    def _upsert_copy(
        self,
        *,
        record,
        item,
        record_id,
        derived,
        occurrence,
        entry_fields,
        custom_values,
        collected_at,
    ):
        """Create or update the copy this source record owns."""
        link = self._find_link(record, record_id, derived, occurrence)

        if link is not None and self.mode != "overwrite":
            # Default mode imports new records only.
            self.counts["skipped"] += 1
            return

        with transaction.atomic():
            if link is not None:
                entry = link.entry
                previous_item = entry.item
                # A record first imported as the wrong media type moves to
                # the item it resolves to now.
                entry.item = item
                for attribute, value in entry_fields.items():
                    setattr(entry, attribute, value)
                # Only supplied values are written, so unrelated fields and
                # anything the user edited by hand survive an overwrite.
                entry.custom_field_values = {
                    **(entry.custom_field_values or {}),
                    **custom_values,
                }
                entry.save()
                if previous_item.id != item.id:
                    _delete_if_unused(previous_item)
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
        ) or self._get(record, *ISSUE_COLUMNS, "volume")
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
            and corroboration
            in str(result.get("details", {})) + str(result.get("release_date", ""))
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

    def _title(self, record, issue_columns=ISSUE_COLUMNS):
        """Return the display title for a record.

        Comic and volume-based rows carry the issue or volume in the title so
        two issues of one series stay distinguishable.
        """
        title = self._get(record, "title")
        series = self._get(record, "series")
        issue = self._get(record, *issue_columns)
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

    def _add_to_wishlist(self, item, record, media_type):
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
        if self.mode == "overwrite":
            self._note_mistyped_wishlist_item(item, record, media_type)
        logger.debug("CLZ wishlist row kept for %s", self._describe(record))

    def _note_mistyped_wishlist_item(self, item, record, media_type):
        """Report a wishlist entry an earlier run may have added as another type.

        Versions before issue #809 could import a comics export as movies.
        Wishlist rows carry no source identity, so an entry of that old type
        with the same title cannot be told apart from one the user added by
        hand. It is reported for the user to remove, never deleted.
        """
        from lists.models import CustomListItem

        if self._legacy_media_type == media_type:
            return
        stale = (
            CustomListItem.objects.filter(
                custom_list=self._wishlist,
                item__source=Sources.MANUAL.value,
                item__media_type=self._legacy_media_type,
                item__title=self._title(record, LEGACY_ISSUE_COLUMNS),
            )
            .exclude(item=item)
            .select_related("item")
        )
        for list_item in stale:
            self.warnings.append(
                f"{list_item.item.title}: the {WISHLIST_LIST_NAME} list also "
                f"has a {list_item.item.get_media_type_display()} entry with "
                "this title. Remove it if an earlier import added it.",
            )


def _legacy_detect_media_type(columns):
    """Return the media type versions before issue #809 detected."""
    present = {column_key(column) for column in columns}
    if present & {"issuenr", "issuenumber", "storyarc"}:
        return MediaTypes.COMIC_ISSUE.value
    if "platform" in present:
        return MediaTypes.GAME.value
    if present & {"isbn", "author", "authors", "pages"}:
        return MediaTypes.BOOK.value
    return MediaTypes.MOVIE.value


def _digest(parts):
    """Return the derived identity hash of *parts*."""
    return blake2s(
        "|".join(normalize(part) for part in parts).encode("utf-8"),
        digest_size=16,
    ).hexdigest()


def _delete_if_unused(item):
    """Delete a manual *item* an import left with nothing pointing at it.

    Only manual items are considered, since the importer created them, and
    only when no copy, list entry, history or other row still references
    them, including another user's.
    """
    if item.source != Sources.MANUAL.value:
        return
    for relation in item._meta.related_objects:
        manager = relation.related_model._base_manager
        if manager.filter(**{relation.field.name: item}).exists():
            return
    item.delete()
