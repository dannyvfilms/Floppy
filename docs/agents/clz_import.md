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

- **CLZ's own XML export** (`<collectorz>` root) — the records sit inside
  `collectorz/data/<product>info/<product>list`, not under the root. They are
  found by depth (5) and a `...list` parent, so a `udfdefinitions` sibling is
  never mistaken for a record. `_native_record` then renames the flattened
  labels onto the names a CSV would carry (`mainsection series displayname`
  becomes `Series`, `format displayname` becomes `Format`), drops CLZ's sync
  bookkeeping (`hash`, `index`, `bpcomicid`, timestamps, thumbnail sizes), and
  keeps the best cover link as `Cover URL`. Records are marked `CLZ Native`.

Column identity is matched with `clz.column_key`, which folds case, Unicode
form and separators **and then drops spaces** — the CSV header
`Purchase Price` and the XML tag `<purchaseprice>` are the same column.

## Media type

The import window's **Import as** picker sets the item media type for the
whole export. Left on auto-detect, `_detect_media_type` reads the headers:
an issue column (`Issue`, `Issue Nr`, `Issue No`) or `Story Arc` means comic
issues, `Platform` means games, `ISBN`/`Author`/`Pages` means books, and
anything else falls back to movies. The fallback adds a warning to the import
result unless a movie column (`IMDb`, `TMDb`, `Director`, `Runtime`) is present.

CLZ's `Format` column ("Graphic Novel", "Manga", "Blu-ray") is the copy's
physical format and lands on `CollectionEntry.media_type`. It never sets the
item type: one manga collection is commonly spread across several formats.

For **manga** the item is the series: every volume is a copy of one item and
carries its number in a **Volume** custom field. Comics keep one item per
issue (`Series #3`) with the number in an **Issue Nr** field. Both columns are
custom fields rather than structural ones so the number is not lost.

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
  values the export supplied. Copies the user made by hand are untouched. A
  copy whose record now resolves to a different item (for example after
  choosing the right media type) moves to that item, and the manual item it
  left is deleted once nothing else references it.

Native XML ids are derived, not taken from `hash` (nothing says it survives
an edit in CLZ). Records sharing one derived id are second copies and are
numbered in file order, so a re-export in another order finds the same copies.

Derived ids never include the resolved item, so correcting the media type
still finds the same copy. Versions before issue #809 did hash the item in;
`_find_link` recognises those links by recomputing the old id and re-keys
them on first sight.

Wishlist rows have no source identity, so an Overwrite run never deletes
one. A same-titled manual entry of the type an older version would have
detected is reported in the import result for the user to remove.

Wishlist rows (`Collection Status`: `On Wish List`, `On Order`) go to a
dedicated **CLZ Wishlist** list. No copy is created and no reading progress is
inferred; their columns are still preserved through the custom fields. The
import window can additionally track them with a status the user picks, and
tag them; a status is only set when the user has no entry for the item yet.

CLZ tags are kept as the user's own Floppy tags on the item (matched
case-insensitively) and also stay on the copy as a **Tags** field, because a
tag belongs to the whole item while CLZ records it per copy. The `Read` flag
is a custom field only: collecting never creates tracking.

## Finding copies by imported fields

On the Collection page, search also matches custom field values, dropdown and
checkbox fields appear in **Filters**, and every field the user has appears in
the sort menu (numbers sort numerically, copies with no value come last).
These read `custom_field_values` in Python, not with a JSON key lookup: keys
are `str(field.id)`, and Django compiles a numeric key as an array index
(`$[2]`) on SQLite, so a database lookup silently matches nothing.

## Scanning a barcode

The search bar's camera button shows for Books, Manga, Comics and Comic Issues.
For the last three, `services.search` turns a checksum-valid ISBN into a series
title through Open Library (Google Books if enabled) and searches that, since no
manga or comic provider answers an ISBN. The search page also lists the user's
own items whose **Barcode** custom field starts with the scanned digits
(`search_views._barcode_owned_items`, in Python for the reason above), so a CLZ
barcode with a price supplement still matches a 12 or 13 digit scan. A scan does
not yet fill the Barcode field of a newly added item.

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

- No cloud scraping or ongoing sync (see issue #809).
- Barcodes are stored on the copy in a **Barcode** field (a 2 or 5 digit
  supplement is ignored for lookups). Manga and comic providers cannot answer
  a barcode, so the import does not search by it for those types.
- A digit run of 10 or more characters is never inferred as a number (a float
  cannot hold an 18 digit barcode), so barcode columns stay text.
- Covers: the item image is the export's cover link. `clzcomics.r.sizr.io` and
  `comic-clzimages.s3.amazonaws.com` are approved image hosts.
- User-defined CLZ fields (`udfdefinitions`) are untested: the only native
  sample had none.
- Title-only matches are deliberately refused. An uncorroborated row becomes
  a manual item rather than a guess at the wrong edition.
- CLZ's own custom fields arrive as ordinary columns; there is no separate
  channel for them, and none is needed.
- Covers: each record's cover link is copied into Floppy's data folder as a local
  cover (see `docs/architecture/local-covers.md`). A failed download keeps the link.
