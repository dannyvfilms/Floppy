# CLZ import and imported collection fields

Covers the CLZ (Collectorz) importer and the shared field-resolution layer
it sits on. Read this before changing `src/integrations/imports/clz.py` or
`src/app/collection_field_import.py`.

## Why CLZ has no schema contract

CLZ exports are user-configured: you pick which columns to include before
generating the CSV/TXT, and custom fields can be included too. Two exports
from the same CLZ product can therefore have completely different headers.

So the importer is **header-mapped, not schema-bound**. There is no fixture
that defines "the CLZ format", and none should be introduced as if there
were. What is supported is the mapping behaviour, not a column list.

## Supported inputs

- **CSV / TXT** — comma or tab delimited (sniffed from the header region),
  UTF-8/UTF-16/CP1252, BOM tolerated. Quoted multiline cells (CLZ notes) are
  preserved with their newlines.
- **XML** — parsed through `defusedxml`, so DTDs, entity expansion and
  external resource loading are refused. Records are the root's element
  children; each record's descendants are flattened to `parent child` labels
  and repeated siblings collapse into a list.

Column identity is matched with `clz.column_key`, which folds case, Unicode
form and separators **and then drops spaces** — the CSV header
`Purchase Price` and the XML tag `<purchaseprice>` are the same column.

## What happens to each column

1. **Structural** (`STRUCTURAL_COLUMNS`) — title, series, issue, barcode,
   quantity, collection status, and so on. Consumed for identification and
   ownership; never duplicated into a custom field.
2. **Built-in** (`ENTRY_FIELD_COLUMNS`) — written to `CollectionEntry`
   attributes (format, purchase price, purchase store, audio codec/channels).
3. **Everything else** — handed to `app.collection_field_import`, which
   reuses or creates a custom field for it.

## Field resolution

Order, in `ImportedFieldResolver._resolve_column`:

1. A saved `CollectionFieldSource` mapping for `(user, source, source_key)`.
   This is why renaming or moving a field does not break the next import.
2. An existing field whose label normalizes to the same key.
3. A new field in the **Imported collection fields** group.

Type is inferred across the whole column and only committed when the reading
is unambiguous. Identifiers with leading zeros, locale-ambiguous dates
(`03/04/2020`), mixed columns and structured values all stay **text**;
structured values are serialized as reversible JSON. A select is only
inferred for a short vocabulary that repeats convincingly, because
committing to one constrains every later value.

Two invariants:

- An existing field is **never retyped** and its select options are never
  rewritten. Only `media_types` is widened, since a field that does not cover
  the incoming media type would never render.
- A value that cannot live in the resolved field's type is **not dropped**.
  It goes to a source-qualified text companion (`Grade (clz)`) and the
  conflict is reported in the import result.

## Copies and identity

Media is resolved by explicit provider id, then barcode/ISBN lookup, then a
title match **only when corroborated** by year or issue/volume. Anything else
is preserved as a manual item — comics keep their issue and volume-based
books keep their volume, rather than collapsing into one series row.

Owned copies are created per explicit `Quantity` (default 1) and linked to
their source record through `CollectionEntrySource`. The link prefers CLZ's
own record id; otherwise it derives one from bibliographic and edition
attributes only — never from mutable collection values like price or storage
box, so editing those in CLZ does not orphan the copy.

- **New mode (default)** imports new records only; a record already linked to
  a copy is skipped.
- **Overwrite mode** updates only source-linked copies, and only with the
  values the export supplied. Copies the user made by hand are untouched.

Wishlist rows (`Collection Status`) go to a dedicated **CLZ Wishlist** list.
No copy is created and no reading progress is inferred; their columns are
still preserved through the custom fields.

## Native export/import

The CSV backup carries the whole picture:

- a `collection_schema` row (versioned by `COLLECTION_SCHEMA_VERSION`) with
  the group/field definitions and their source mappings;
- `collection_custom_fields` on each collection row, keyed by a **portable
  uid** (`group name` + `label`) rather than the database id, which is
  per-user and not transferable;
- `collection_purchase_price`, `collection_purchase_location`, and
  `collection_source_identity`.

On import, the schema row is remapped onto the destination user's own field
ids, reusing anything compatible they already have. Columns are appended, so
an export written by this version still loads in an older one.

## Limitations

- No cloud scraping, ongoing sync, barcode-scanning UI or cover management.
  Those remain separate from this work (see issue #809).
- Title-only matches are deliberately refused. An uncorroborated row becomes
  a manual item rather than a guess at the wrong edition.
- CLZ's own custom fields arrive as ordinary columns; there is no separate
  channel for them, and none is needed.
