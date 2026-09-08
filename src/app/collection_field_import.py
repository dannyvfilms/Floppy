"""Shared resolution of imported collection columns onto custom fields.

Importers hand this module the columns they could not map onto a built-in
``CollectionEntry`` attribute. It reuses a field the user already has, or
creates one in the "Imported collection fields" group, and records a
``CollectionFieldSource`` mapping so later runs of the same import reuse the
same row even after the user renames or moves it.

Two rules shape everything here:

* nothing is silently lost. A value that cannot live in the resolved field's
  type is preserved verbatim in a source-qualified text companion field and
  reported as a conflict.
* an existing field is never retyped and its select options are never
  rewritten. Only ``media_types`` is widened, because a field that does not
  cover the incoming media type would never render.
"""

import json
import logging
import unicodedata
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import date, datetime
from hashlib import blake2s

from django.db import transaction

from app.models import (
    CollectionField,
    CollectionFieldGroup,
    CollectionFieldSource,
    CollectionFieldType,
)

logger = logging.getLogger(__name__)

IMPORTED_GROUP_NAME = "Imported collection fields"
MAX_LABEL_LENGTH = 100
MAX_SOURCE_KEY_LENGTH = 200

# A column is only turned into a select when it looks like a controlled
# vocabulary rather than free text: few distinct values, each seen more
# than once, all short.
MAX_SELECT_OPTIONS = 20
MIN_SELECT_REPETITION = 2
MAX_SELECT_OPTION_LENGTH = 50

_TRUE_TOKENS = frozenset({"true", "yes", "y", "on", "x", "✓", "checked"})
_FALSE_TOKENS = frozenset({"false", "no", "n", "off", "", "unchecked"})
# Digits alone cannot decide checkbox vs number, so they only count once an
# alphabetic boolean token has already appeared in the column.
_AMBIGUOUS_TRUE = frozenset({"1"})
_AMBIGUOUS_FALSE = frozenset({"0"})

_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d")


def normalize_label(label):
    """Return a comparison key for a field label.

    Folds Unicode form and case, and collapses whitespace and separator
    punctuation, so "Story Arc", "story_arc" and "STORY-ARC" all match.
    """
    text = unicodedata.normalize("NFKC", str(label or "")).casefold()
    collapsed = []
    previous_separator = False
    for char in text:
        if char.isalnum():
            collapsed.append(char)
            previous_separator = False
        elif not previous_separator:
            collapsed.append(" ")
            previous_separator = True
    return "".join(collapsed).strip()


def normalize_source_key(key):
    """Return the stable per-source column key stored in the mapping table."""
    normalized = normalize_label(key)[:MAX_SOURCE_KEY_LENGTH]
    return normalized or "column"


def _stable_suffix(text):
    """Return a short deterministic suffix used to disambiguate labels."""
    return blake2s(text.encode("utf-8"), digest_size=3).hexdigest()


def _truncate_label(label, suffix=""):
    """Fit *label* (plus an optional suffix) inside the label column."""
    budget = MAX_LABEL_LENGTH - len(suffix)
    text = label[:budget].rstrip()
    return f"{text}{suffix}"


def _serialize(value):
    """Return a reversible string for a structured value."""
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _clean(value):
    """Return the trimmed text form of a raw column value."""
    if value is None:
        return ""
    return _serialize(value).strip()


def _parse_bool(text):
    """Return True/False for a boolean token, or None when it is not one."""
    lowered = text.casefold()
    if lowered in _TRUE_TOKENS:
        return True
    if lowered in _FALSE_TOKENS:
        return False
    return None


def _parse_number(text):
    """Return a float for a plainly numeric token, or None.

    Identifier-shaped values (leading zeros, grouping, currency, ranges) stay
    text so barcodes and issue numbers survive the round trip.
    """
    candidate = text.replace(" ", "")
    if not candidate:
        return None
    body = candidate.removeprefix("-").removeprefix("+")
    if body.startswith("0") and len(body) > 1 and not body.startswith("0."):
        return None
    try:
        return float(candidate)
    except ValueError:
        return None


def _parse_date(text):
    """Return an ISO date string for an unambiguous date, or None.

    Only year-first formats are accepted. ``03/04/2020`` could be March or
    April depending on locale, so it is preserved as text instead.
    """
    candidate = text.split("T")[0].split(" ")[0]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(candidate, fmt).date().isoformat()  # noqa: DTZ007
        except ValueError:
            continue
    return None


def infer_field_type(values):
    """Infer a field type from every value in a column.

    Anything mixed, ambiguous or unrepresentable falls back to text, which
    can hold any value losslessly.
    """
    texts = [text for text in (_clean(value) for value in values) if text]
    if not texts:
        return CollectionFieldType.TEXT, []

    if _looks_boolean(texts):
        return CollectionFieldType.CHECKBOX, []

    if all(_parse_number(text) is not None for text in texts):
        return CollectionFieldType.NUMBER, []

    if all(_parse_date(text) is not None for text in texts):
        return CollectionFieldType.DATE, []

    options = _select_options(texts)
    if options:
        return CollectionFieldType.SELECT, options

    return CollectionFieldType.TEXT, []


def _looks_boolean(texts):
    """Return whether every value is a boolean token, alphabetic ones included."""
    saw_alphabetic = False
    for text in texts:
        lowered = text.casefold()
        if lowered in _AMBIGUOUS_TRUE or lowered in _AMBIGUOUS_FALSE:
            continue
        if _parse_bool(text) is None:
            return False
        saw_alphabetic = True
    return saw_alphabetic


def _select_options(texts):
    """Return sorted select options when the column is a controlled vocabulary."""
    distinct = set(texts)
    if len(distinct) > MAX_SELECT_OPTIONS:
        return []
    if len(texts) < len(distinct) * MIN_SELECT_REPETITION:
        return []
    if any(len(text) > MAX_SELECT_OPTION_LENGTH for text in distinct):
        return []
    return sorted(distinct)


@dataclass
class ImportColumn:
    """One unmapped column from a source export."""

    key: str
    label: str
    values: list
    media_types: list


@dataclass
class FieldConflict:
    """A value that could not be stored in its resolved field's type."""

    source_label: str
    field_label: str
    value: str

    def __str__(self):
        """Return the message shown in the import summary."""
        return (
            f"{self.source_label}: {self.value!r} does not fit "
            f"'{self.field_label}', kept as text."
        )


@dataclass
class ResolverReport:
    """Summary of what a resolver did, for the import result."""

    created_fields: list = dataclass_field(default_factory=list)
    reused_fields: list = dataclass_field(default_factory=list)
    conflicts: list = dataclass_field(default_factory=list)

    def messages(self):
        """Return deduplicated human-readable lines for the import summary."""
        lines = []
        if self.created_fields:
            lines.append(
                f"Created {len(self.created_fields)} collection field(s): "
                + ", ".join(sorted(self.created_fields)),
            )
        if self.reused_fields:
            lines.append(
                f"Reused {len(self.reused_fields)} existing collection field(s): "
                + ", ".join(sorted(self.reused_fields)),
            )
        lines.extend(str(conflict) for conflict in self.conflicts)
        return list(dict.fromkeys(lines))


class ImportedFieldResolver:
    """Resolve a source's columns onto a user's custom collection fields."""

    def __init__(self, user, source, import_run=None):
        """Store the import identity the resolved mappings are recorded under."""
        self.user = user
        self.source = source
        self.import_run = import_run
        self.report = ResolverReport()
        self._by_key = {}
        self._fallback_by_key = {}
        self._group = None

    # -- schema ---------------------------------------------------------

    def prepare(self, columns):
        """Resolve every column to a field, creating what is missing.

        Runs in one transaction so a failure cannot leave half a schema
        behind, and so a concurrent run of the same import cannot end up
        with duplicate definitions.
        """
        with transaction.atomic():
            for column in columns:
                self._by_key[column.key] = self._resolve_column(column)
        return self._by_key

    def register(self, key, field):
        """Bind a column key to a field the caller resolved itself.

        Used by the native import, which already knows each field's type
        from the export's schema row and does not need it inferred.
        """
        self._by_key[key] = field

    def _get_group(self):
        """Return (creating if needed) the group imported fields land in."""
        if self._group is None:
            self._group, _ = CollectionFieldGroup.objects.get_or_create(
                user=self.user,
                name=IMPORTED_GROUP_NAME,
                defaults={
                    "position": CollectionFieldGroup.objects.filter(
                        user=self.user,
                    ).count(),
                },
            )
        return self._group

    def _resolve_column(self, column):
        """Return the CollectionField that *column* should be written to."""
        source_key = normalize_source_key(column.key)

        mapping = (
            CollectionFieldSource.objects.select_related("field")
            .filter(user=self.user, source=self.source, source_key=source_key)
            .first()
        )
        if mapping:
            self._widen_media_types(mapping.field, column.media_types)
            self.report.reused_fields.append(mapping.field.label)
            return mapping.field

        field_type, options = infer_field_type(column.values)
        existing = self._match_by_label(column.label)
        if existing:
            self._widen_media_types(existing, column.media_types)
            self._record_mapping(source_key, column, existing, created=False)
            self.report.reused_fields.append(existing.label)
            return existing

        created = CollectionField.objects.create(
            group=self._get_group(),
            label=self._unique_label(column.label),
            field_type=field_type,
            options=options,
            media_types=list(column.media_types),
            position=CollectionField.objects.filter(
                group__user=self.user,
            ).count(),
        )
        self._record_mapping(source_key, column, created, created=True)
        self.report.created_fields.append(created.label)
        logger.info(
            "Created collection field %r for %s column %r",
            created.label,
            self.source,
            column.label,
        )
        return created

    def _match_by_label(self, label):
        """Return an existing field whose label normalizes to the same key."""
        target = normalize_label(label)
        if not target:
            return None
        for candidate in CollectionField.objects.filter(group__user=self.user):
            if normalize_label(candidate.label) == target:
                return candidate
        return None

    def _unique_label(self, label):
        """Return a label that no existing field of this user already uses."""
        base = _truncate_label(str(label or "").strip() or "Imported field")
        taken = {
            normalize_label(existing)
            for existing in CollectionField.objects.filter(
                group__user=self.user,
            ).values_list("label", flat=True)
        }
        if normalize_label(base) not in taken:
            return base
        # Deterministic rather than a counter, so a re-run of the same import
        # against the same clash produces the same label.
        suffix = f" ({_stable_suffix(f'{self.source}:{label}')})"
        return _truncate_label(base, suffix)

    def _widen_media_types(self, field, media_types):
        """Add any missing media types so the field renders for this import."""
        missing = [
            media_type
            for media_type in media_types
            if media_type not in field.media_types
        ]
        if not missing:
            return
        field.media_types = [*field.media_types, *missing]
        field.save(update_fields=["media_types", "updated_at"])

    def _record_mapping(self, source_key, column, field, *, created):
        """Persist the source-column-to-field mapping and its provenance."""
        CollectionFieldSource.objects.update_or_create(
            user=self.user,
            source=self.source,
            source_key=source_key,
            defaults={
                "source_label": str(column.label or "")[:MAX_SOURCE_KEY_LENGTH],
                "field": field,
                "created_field": created,
                "created_by_import_run": self.import_run,
            },
        )

    # -- values ---------------------------------------------------------

    def build_values(self, row, media_type, base_values=None):
        """Return ``custom_field_values`` for one source row.

        *row* maps prepared column keys to raw values. Values that do not fit
        the resolved field are diverted to a source-qualified text field
        rather than dropped.
        """
        values = dict(base_values or {})
        for key, raw in row.items():
            field = self._by_key.get(key)
            if field is None:
                continue
            if media_type not in field.media_types:
                continue
            stored, ok = self._coerce(field, raw)
            if ok:
                if stored is None:
                    values.pop(str(field.id), None)
                else:
                    values[str(field.id)] = stored
                continue
            fallback = self._fallback_field(key, field, media_type)
            values[str(fallback.id)] = _clean(raw)
            self.report.conflicts.append(
                FieldConflict(
                    source_label=key,
                    field_label=field.label,
                    value=_clean(raw),
                ),
            )
        return values

    def _coerce(self, field, raw):
        """Return ``(stored_value, fits)`` for *raw* under *field*'s type."""
        text = _clean(raw)
        if field.field_type == CollectionFieldType.CHECKBOX:
            parsed = _parse_bool(text)
            if parsed is None:
                return None, False
            return parsed, True
        if not text:
            return None, True
        if field.field_type == CollectionFieldType.NUMBER:
            parsed = _parse_number(text)
            if parsed is None:
                return None, False
            return parsed, True
        if field.field_type == CollectionFieldType.DATE:
            parsed = _parse_date(text)
            if parsed is None:
                return None, False
            return parsed, True
        if field.field_type == CollectionFieldType.SELECT:
            if text not in field.options:
                return None, False
            return text, True
        return text, True

    def _fallback_field(self, key, field, media_type):
        """Return the text field holding values *field*'s type cannot store."""
        cached = self._fallback_by_key.get(key)
        if cached is not None:
            self._widen_media_types(cached, [media_type])
            return cached

        column = ImportColumn(
            key=f"{key}::text",
            label=_truncate_label(f"{field.label} ({self.source})"),
            values=[],
            media_types=[media_type],
        )
        with transaction.atomic():
            fallback = self._resolve_column(column)
        self._fallback_by_key[key] = fallback
        return fallback
