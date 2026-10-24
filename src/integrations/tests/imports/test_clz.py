"""Tests for the CLZ (Collectorz) CSV and XML importer.

CLZ has no fixed export schema — the user chooses the columns — so these
fixtures exercise the header-mapped contract rather than one canonical file.
"""

from hashlib import blake2s
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app import local_covers
from app.collection_field_import import normalize_label as normalize
from app.models import (
    CollectionEntry,
    CollectionEntrySource,
    CollectionField,
    CollectionFieldType,
    Item,
    ItemTag,
    Manga,
    MediaTypes,
    Sources,
    Tag,
)
from integrations.imports import clz
from integrations.imports.helpers import MediaImportError
from lists.models import CustomList, CustomListItem

COMICS_CSV = (
    "Series,Issue Nr,Release Year,Story Arc,Publisher,Storage Box,Variant,"
    "Quantity,Collection Status\n"
    '"Saga",001,2012,"Chapter One","Image","Box A","Cover A",2,"In Collection"\n'
    '"Saga",002,2012,"Chapter One","Image","Box A","Cover B",1,"In Collection"\n'
    '"Saga",003,2012,"Chapter Two","Image","Box B","Cover A",1,"On Wishlist"\n'
)

# The shape of a real CLZ Comics export (issue #809): the issue column is
# headed "Issue", not "Issue Nr", and nothing else marks it as comics.
CLZ_COMICS_EXPORT_CSV = (
    "Series,Issue,Publisher,Format,Storage Box,Collection Status\n"
    '"Death Note [GER]",1,"Tokyopop","Manga","Kallax 1","In Collection"\n'
    '"Death Note [GER]",2,"Tokyopop","Graphic Novel","Kallax 1","In Collection"\n'
    '"Death Note [GER]",3,"Tokyopop","Manga","","On Wishlist"\n'
)

GAMES_CSV = (
    "Title,Platform,Region,Box,Manual,Notes\n"
    '"Chrono Trigger","SNES","NTSC","Yes","Yes","Bought at a fair.\n'
    'Spine is faded."\n'
)

MOVIES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<movielist>
  <movie id="4412">
    <title>Perfect Blue</title>
    <year>1997</year>
    <format>Blu-ray</format>
    <purchaseprice>24.99</purchaseprice>
    <purchasestore>Local Shop</purchasestore>
    <collectionstatus>In Collection</collectionstatus>
    <genres>
      <genre>Animation</genre>
      <genre>Thriller</genre>
    </genres>
  </movie>
</movielist>
"""

XXE_XML = """<?xml version="1.0"?>
<!DOCTYPE movielist [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<movielist><movie><title>&xxe;</title><year>1997</year></movie></movielist>
"""


def upload(name, content):
    """Return an uploaded-file stand-in the importer can read."""
    stream = BytesIO(content.encode("utf-8"))
    stream.name = name
    return stream


def block_cover_downloads(test):
    """Keep an import test off the network: a cover download simply fails."""
    patcher = patch(
        "integrations.imports.clz.local_covers.fetch_cover",
        side_effect=local_covers.CoverError("offline"),
    )
    test.fetch_cover = patcher.start()
    test.addCleanup(patcher.stop)


class CLZParsingTests(TestCase):
    """Parsing must survive CLZ's quoting, encodings and multi-valued XML."""

    def test_csv_keeps_multiline_quoted_values(self):
        """A quoted multiline notes cell survives with its newline intact."""
        records, columns = clz.parse_csv(GAMES_CSV)
        self.assertIn("Notes", columns)
        self.assertIn("\n", records[0]["Notes"])

    def test_xml_collapses_repeated_siblings_into_a_list(self):
        """Repeated genre elements are preserved rather than overwritten."""
        records, columns = clz.parse_xml(upload("clz.xml", MOVIES_XML))
        self.assertEqual(records[0]["genres genre"], ["Animation", "Thriller"])
        self.assertIn("genres genre", columns)

    def test_xml_external_entities_are_refused(self):
        """An XXE payload is rejected instead of resolving the local file."""
        with self.assertRaises(MediaImportError):
            clz.parse_xml(upload("clz.xml", XXE_XML))

    def test_header_only_csv_is_rejected_with_a_diagnostic(self):
        """A file with no header raises a message the user can act on."""
        with self.assertRaises(MediaImportError):
            clz.parse_csv("")

    def test_disk_staging_preserves_late_encoding_fallback(self):
        """A non-UTF8 value beyond the read buffer survives complete validation."""
        file = BytesIO(("Title,Notes\nA," + "a" * 70000 + "é\n").encode("cp1252"))
        instance = clz.CLZImporter(file, None, "new")
        with instance._parse_staged() as (records, columns, total):
            self.assertEqual(total, 1)
            self.assertEqual(columns, ["Title", "Notes"])
            self.assertTrue(next(clz._read_records(records))["Notes"].endswith("é"))

    def test_disk_xml_preserves_multivalued_columns(self):
        """The streamed XML import has the same row shape as public parsing."""
        instance = clz.CLZImporter(upload("export.xml", MOVIES_XML), None, "new")
        with instance._parse_staged() as (records, columns, total):
            self.assertEqual(total, 1)
            self.assertIn("genres genre", columns)
            self.assertEqual(
                next(clz._read_records(records))["genres genre"],
                ["Animation", "Thriller"],
            )


class CLZImportTests(TestCase):
    """End-to-end import behaviour for owned copies and wishlist rows."""

    def setUp(self):
        """Create the importing user and stub out provider lookups."""
        self.user = get_user_model().objects.create_user(
            username="clz",
            password="12345",
        )
        patcher = patch(
            "integrations.imports.clz.services.search",
            return_value={"results": []},
        )
        self.search = patcher.start()
        self.addCleanup(patcher.stop)
        block_cover_downloads(self)

    def run_import(self, name, content, mode="new"):
        """Run the CLZ importer over an in-memory export."""
        return clz.importer(upload(name, content), self.user, mode)

    def test_comics_import_creates_copies_per_quantity(self):
        """An explicit quantity of 2 creates two owned copies."""
        counts, _ = self.run_import("clz-comics.csv", COMICS_CSV)

        self.assertEqual(counts["collection"], 3)
        self.assertEqual(CollectionEntry.objects.filter(user=self.user).count(), 3)

    def test_comics_attach_to_individual_issues(self):
        """Each issue gets its own item rather than collapsing to the series."""
        self.run_import("clz-comics.csv", COMICS_CSV)

        titles = set(
            Item.objects.filter(source=Sources.MANUAL.value).values_list(
                "title",
                flat=True,
            ),
        )
        self.assertIn("Saga #001", titles)
        self.assertIn("Saga #002", titles)

    def test_media_type_is_detected_from_columns(self):
        """Issue/story-arc columns identify the export as comic issues."""
        self.run_import("clz-comics.csv", COMICS_CSV)

        self.assertTrue(
            Item.objects.filter(media_type=MediaTypes.COMIC_ISSUE.value).exists(),
        )

    def test_unmapped_columns_become_custom_fields(self):
        """Columns with no built-in home land in the user's custom fields."""
        self.run_import("clz-comics.csv", COMICS_CSV)

        labels = set(
            CollectionField.objects.filter(group__user=self.user).values_list(
                "label",
                flat=True,
            ),
        )
        self.assertIn("Storage Box", labels)
        self.assertIn("Variant", labels)

    def test_thin_vocabulary_column_stays_text(self):
        """Too little repetition to be sure of a vocabulary, so it stays text.

        Committing to a select constrains every later value, so inference
        only does it when the column repeats convincingly. (The threshold
        itself is covered in app.tests.test_collection_field_import.)
        """
        self.run_import("clz-comics.csv", COMICS_CSV)

        field = CollectionField.objects.get(label="Storage Box")
        self.assertEqual(field.field_type, CollectionFieldType.TEXT)

    def test_leading_zero_issue_numbers_are_not_numeric(self):
        """Issue numbers keep their leading zeros in the item title."""
        self.run_import("clz-comics.csv", COMICS_CSV)

        self.assertTrue(Item.objects.filter(title="Saga #001").exists())

    def test_wishlist_rows_create_no_copies(self):
        """A wishlist row goes to the CLZ wishlist list, not the collection."""
        counts, _ = self.run_import("clz-comics.csv", COMICS_CSV)

        self.assertEqual(counts["wishlist"], 1)
        wishlist = CustomList.objects.get(
            owner=self.user,
            name=clz.WISHLIST_LIST_NAME,
        )
        self.assertEqual(wishlist.customlistitem_set.count(), 1)
        self.assertFalse(
            CollectionEntry.objects.filter(
                user=self.user,
                item__title="Saga #003",
            ).exists(),
        )

    def test_repeat_import_reuses_source_linked_copies(self):
        """Importing twice in new mode does not duplicate owned copies."""
        self.run_import("clz-comics.csv", COMICS_CSV)
        counts, _ = self.run_import("clz-comics.csv", COMICS_CSV)

        self.assertEqual(CollectionEntry.objects.filter(user=self.user).count(), 3)
        self.assertEqual(counts.get("collection", 0), 0)
        self.assertEqual(counts["skipped"], 3)

    def test_overwrite_updates_only_source_linked_copies(self):
        """A manually created copy survives an overwrite import."""
        self.run_import("clz-comics.csv", COMICS_CSV)
        item = Item.objects.get(title="Saga #001")
        manual = CollectionEntry.objects.create(user=self.user, item=item)

        self.run_import("clz-comics.csv", COMICS_CSV, mode="overwrite")

        self.assertTrue(CollectionEntry.objects.filter(id=manual.id).exists())
        self.assertEqual(CollectionEntry.objects.filter(user=self.user).count(), 4)

    def test_source_identity_is_persisted(self):
        """Every imported copy is linked back to its source record."""
        self.run_import("clz-comics.csv", COMICS_CSV)

        links = CollectionEntrySource.objects.filter(user=self.user, source="clz")
        self.assertEqual(links.count(), 3)
        self.assertTrue(all(link.derived_identity for link in links))

    def test_xml_import_maps_purchase_metadata(self):
        """Purchase price and store land on built-in entry fields."""
        self.run_import("clz-movies.xml", MOVIES_XML)

        entry = CollectionEntry.objects.get(user=self.user)
        self.assertEqual(str(entry.purchase_price), "24.99")
        self.assertEqual(entry.purchase_location, "Local Shop")
        self.assertEqual(entry.media_type, "Blu-ray")

    def test_xml_uses_the_clz_record_id_as_identity(self):
        """CLZ's own record id is preferred over a derived identity."""
        self.run_import("clz-movies.xml", MOVIES_XML)

        link = CollectionEntrySource.objects.get(user=self.user)
        self.assertEqual(link.source_record_id, "4412")
        self.assertFalse(link.derived_identity)

    def test_structured_xml_values_are_preserved_reversibly(self):
        """A multi-valued genre list is stored as reversible JSON text."""
        self.run_import("clz-movies.xml", MOVIES_XML)

        field = CollectionField.objects.get(
            group__user=self.user,
            label="genres genre",
        )
        entry = CollectionEntry.objects.get(user=self.user)
        self.assertEqual(
            entry.custom_field_values[str(field.id)],
            '["Animation", "Thriller"]',
        )

    def test_unmatched_records_fall_back_to_custom_items(self):
        """A record no provider matched is kept as a manual item."""
        self.run_import("clz-games.csv", GAMES_CSV)

        item = Item.objects.get(title="Chrono Trigger")
        self.assertEqual(item.source, Sources.MANUAL.value)
        self.assertEqual(item.media_type, MediaTypes.GAME.value)

    def test_multiline_note_survives_into_a_custom_field(self):
        """The embedded newline in a quoted CLZ note is preserved."""
        self.run_import("clz-games.csv", GAMES_CSV)

        field = CollectionField.objects.get(group__user=self.user, label="Notes")
        entry = CollectionEntry.objects.get(user=self.user)
        self.assertIn("\n", entry.custom_field_values[str(field.id)])

    def test_rows_without_a_title_are_reported_not_dropped(self):
        """An unidentifiable row is rejected with an actionable message."""
        counts, warnings = self.run_import(
            "clz-bad.csv",
            "Title,Platform\n,\n",
        )

        self.assertEqual(counts["rejected"], 1)
        self.assertIn("no title", warnings)


def legacy_identity(record, item):
    """Return the derived identity versions before #809 stored for *record*.

    Those versions hashed the resolved item into the identity and only read
    "Issue Nr"/"Issue Number", so an export that fell back to Movie produced
    links a corrected re-import could never find by the current identity.
    """
    parts = [
        item.media_type,
        item.source,
        item.media_id,
        record.get("Series", ""),
        record.get("Issue Nr", ""),
        "",  # volume
        "",  # year
        record.get("Publisher", ""),
        "",  # platform
        "",  # edition
        "",  # variant
        record.get("Format", ""),
        "",  # identifier
    ]
    return blake2s(
        "|".join(normalize(part) for part in parts).encode("utf-8"),
        digest_size=16,
    ).hexdigest()


class CLZMediaTypeTests(TestCase):
    """Issue #809: CLZ Comics exports must not land as movies."""

    def setUp(self):
        """Create the importing user and stub out provider lookups."""
        self.user = get_user_model().objects.create_user(
            username="clz",
            password="12345",
        )
        patcher = patch(
            "integrations.imports.clz.services.search",
            return_value={"results": []},
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        block_cover_downloads(self)

    def run_import(self, content, mode="new", media_type=None):
        """Run the CLZ importer over the in-memory export *content*."""
        return clz.importer(
            upload("clz.csv", content),
            self.user,
            mode,
            media_type=media_type,
        )

    def legacy_movie_import(self):
        """Store copies the way the old Movie fallback left them."""
        records, _ = clz.parse_csv(CLZ_COMICS_EXPORT_CSV)
        item = Item.objects.create(
            media_id=Item.generate_manual_id(),
            source=Sources.MANUAL.value,
            media_type=MediaTypes.MOVIE.value,
            library_media_type=MediaTypes.MOVIE.value,
            title="Death Note [GER]",
        )
        entries = []
        for position, record in enumerate(records[:2]):
            entry = CollectionEntry.objects.create(
                user=self.user,
                item=item,
                media_type=record["Format"],
            )
            CollectionEntrySource.objects.create(
                user=self.user,
                source="clz",
                source_record_id=legacy_identity(record, item),
                occurrence=position * 1000,
                derived_identity=True,
                entry=entry,
            )
            entries.append(entry)
        wishlist = CustomList.objects.create(
            owner=self.user,
            name=clz.WISHLIST_LIST_NAME,
        )
        CustomListItem.objects.create(custom_list=wishlist, item=item)
        return item, entries, wishlist

    def test_issue_column_identifies_a_comics_export(self):
        """A plain "Issue" header is enough to detect comic issues."""
        self.run_import(CLZ_COMICS_EXPORT_CSV)

        types = set(
            CollectionEntry.objects.filter(user=self.user).values_list(
                "item__media_type",
                flat=True,
            ),
        )
        self.assertEqual(types, {MediaTypes.COMIC_ISSUE.value})

    def test_issue_column_keeps_volumes_apart(self):
        """Each volume becomes its own item instead of merging by series."""
        self.run_import(CLZ_COMICS_EXPORT_CSV)

        titles = set(
            CollectionEntry.objects.filter(user=self.user).values_list(
                "item__title",
                flat=True,
            ),
        )
        self.assertEqual(titles, {"Death Note [GER] #1", "Death Note [GER] #2"})

    def test_format_stays_on_the_copy(self):
        """The CLZ Format is the copy's physical format, not the item type."""
        self.run_import(CLZ_COMICS_EXPORT_CSV)

        entry = CollectionEntry.objects.get(item__title="Death Note [GER] #2")
        self.assertEqual(entry.media_type, "Graphic Novel")

    def test_chosen_media_type_overrides_detection(self):
        """Picking Manga on the import page imports manga items."""
        self.run_import(CLZ_COMICS_EXPORT_CSV, media_type=MediaTypes.MANGA.value)

        types = set(
            Item.objects.filter(collectionentry__user=self.user).values_list(
                "media_type",
                flat=True,
            ),
        )
        self.assertEqual(types, {MediaTypes.MANGA.value})

    def test_undetectable_export_warns_instead_of_guessing_silently(self):
        """Falling back to Movie tells the user how to choose the type."""
        _, warnings = self.run_import("Title,Notes\nSomething,Hi\n")

        self.assertIn("Import as", warnings)

    def test_overwrite_moves_copies_imported_as_movies(self):
        """Overwrite re-types the old copies in place, without duplicates."""
        old_item, entries, _ = self.legacy_movie_import()

        counts, _ = self.run_import(CLZ_COMICS_EXPORT_CSV, mode="overwrite")

        self.assertEqual(counts["updated"], 2)
        self.assertEqual(counts.get("collection", 0), 0)
        moved = CollectionEntry.objects.filter(user=self.user).order_by("id")
        self.assertEqual([entry.id for entry in moved], [e.id for e in entries])
        self.assertEqual(
            [entry.item.title for entry in moved],
            ["Death Note [GER] #1", "Death Note [GER] #2"],
        )
        self.assertTrue(
            all(e.item.media_type == MediaTypes.COMIC_ISSUE.value for e in moved),
        )

    def test_overwrite_deletes_the_emptied_placeholder(self):
        """The old Movie placeholder goes once nothing references it."""
        old_item, _, wishlist = self.legacy_movie_import()
        wishlist.customlistitem_set.all().delete()

        self.run_import(CLZ_COMICS_EXPORT_CSV, mode="overwrite")

        self.assertFalse(Item.objects.filter(id=old_item.id).exists())

    def test_overwrite_reports_old_wishlist_rows_without_deleting(self):
        """A same-titled Movie wishlist entry is reported, never removed.

        Wishlist rows carry no source identity, so the old entry cannot be
        told apart from a Movie the user added to the list by hand.
        """
        old_item, _, wishlist = self.legacy_movie_import()

        _, warnings = self.run_import(CLZ_COMICS_EXPORT_CSV, mode="overwrite")

        titles = set(
            wishlist.customlistitem_set.values_list("item__title", flat=True),
        )
        self.assertEqual(titles, {"Death Note [GER]", "Death Note [GER] #3"})
        self.assertTrue(Item.objects.filter(id=old_item.id).exists())
        self.assertIn("Death Note [GER]: the CLZ Wishlist list also has", warnings)

    def test_wishlist_rows_of_other_types_are_not_reported(self):
        """Only the type an earlier run could have used is flagged."""
        wishlist = CustomList.objects.create(
            owner=self.user,
            name=clz.WISHLIST_LIST_NAME,
        )
        book = Item.objects.create(
            media_id=Item.generate_manual_id(),
            source=Sources.MANUAL.value,
            media_type=MediaTypes.BOOK.value,
            library_media_type=MediaTypes.BOOK.value,
            title="Death Note [GER]",
        )
        CustomListItem.objects.create(custom_list=wishlist, item=book)

        _, warnings = self.run_import(CLZ_COMICS_EXPORT_CSV, mode="overwrite")

        self.assertNotIn("also has", warnings)

    def test_new_mode_recognises_old_copies_without_duplicating(self):
        """A repeat import in the default mode skips the old copies."""
        self.legacy_movie_import()

        counts, _ = self.run_import(CLZ_COMICS_EXPORT_CSV)

        self.assertEqual(counts["skipped"], 2)
        self.assertEqual(CollectionEntry.objects.filter(user=self.user).count(), 2)

    def test_overwrite_keeps_an_old_item_still_in_use(self):
        """The old item survives if anything else still points at it."""
        old_item, _, wishlist = self.legacy_movie_import()
        wishlist.customlistitem_set.all().delete()
        other = get_user_model().objects.create_user(username="other")
        CollectionEntry.objects.create(user=other, item=old_item)

        self.run_import(CLZ_COMICS_EXPORT_CSV, mode="overwrite")

        self.assertTrue(Item.objects.filter(id=old_item.id).exists())

    def test_import_page_offers_the_media_type_picker(self):
        """The CLZ window lets the user choose what the export contains."""
        self.client.force_login(self.user)

        response = self.client.get(reverse("import_data"))

        self.assertContains(response, 'name="clz_media_type"')


def native_record(
    series,
    issue,
    *,
    status="In Collection",
    barcode="",
    fmt="Manga",
    tags=(),
    read="No",
    cover="",
):
    """Return one record in CLZ's own export shape (invented titles)."""
    tag_xml = "".join(f"<tag><displayname>{tag}</displayname></tag>" for tag in tags)
    return f"""<comic>
  <datasetversion>14</datasetversion>
  <hash>deadbeef{issue}</hash>
  <bpcomicid>0</bpcomicid>
  <mainsection>
    <series><bpseriesid>9</bpseriesid><displayname>{series}</displayname></series>
    <pagecount>0</pagecount>
  </mainsection>
  <issuenr>{issue}</issuenr>
  <publisher><displayname>Viz</displayname></publisher>
  <publicationdate><year><displayname>2021</displayname></year></publicationdate>
  <barcode>{barcode}</barcode>
  <format><displayname>{fmt}</displayname></format>
  <coverfrontdefault>{cover}</coverfrontdefault>
  <quantity>1</quantity>
  <index>0</index>
  <collectionstatus listid="3">{status}</collectionstatus>
  <purchaseprice>10</purchaseprice>
  <store><displayname>Amazon</displayname></store>
  <purchasedate><year><displayname>2023</displayname></year>
    <date>2023/04/05</date></purchasedate>
  <readit boolvalue="1">{read}</readit>
  <tags>{tag_xml}</tags>
  <language><displayname>English</displayname></language>
</comic>"""


def native_export(*records, udf=""):
    """Wrap records in CLZ's collectorz > data > comicinfo > comiclist nesting."""
    return (
        '<?xml version="1.0" encoding="utf-8" ?>\n'
        "<collectorz><response><iserror>0</iserror></response>"
        "<meta><scope>export</scope></meta><data><comicinfo>"
        f"<udfdefinitions>{udf}</udfdefinitions><comiclist>"
        + "".join(records)
        + "</comiclist></comicinfo></data></collectorz>"
    )


NATIVE_RECORDS = (
    native_record(
        "Test Series",
        "1",
        barcode="9781234567897",
        tags=("Gelesen", "Kleinanzeigen"),
        read="Yes",
        cover="https://clzcomics.r.sizr.io/core/covers/lg/aa/test-1.jpg",
    ),
    native_record("Test Series", "2", barcode="978123456789712345", tags=("Gelesen",)),
    # A second copy of volume 2 sits in the export as its own record.
    native_record("Test Series", "2", barcode="978123456789712345"),
    native_record("Test Series", "3", status="On Wish List", tags=("Missing",)),
    native_record("Test Series", "4", status="On Order"),
)


class CLZNativeExportTests(TestCase):
    """CLZ's own XML nests records under collectorz > data > ... > comiclist."""

    def setUp(self):
        """Create the importing user and stub out provider lookups."""
        self.user = get_user_model().objects.create_user(
            username="native",
            password="12345",
        )
        patcher = patch(
            "integrations.imports.clz.services.search",
            return_value={"results": []},
        )
        self.search = patcher.start()
        self.addCleanup(patcher.stop)
        block_cover_downloads(self)

    def run_import(self, content=None, mode="new", **options):
        """Import the native export, as manga unless told otherwise."""
        options.setdefault("media_type", MediaTypes.MANGA.value)
        content = content or native_export(*NATIVE_RECORDS)
        return clz.importer(
            upload("comic_export.xml", content),
            self.user,
            mode,
            **options,
        )

    def test_records_are_found_inside_the_envelope(self):
        """Every comic is a record; response, meta and data are not."""
        records, columns = clz.parse_xml(
            upload("e.xml", native_export(*NATIVE_RECORDS)),
        )

        self.assertEqual(len(records), len(NATIVE_RECORDS))
        self.assertIn("Series", columns)
        self.assertNotIn("response iserror", columns)

    def test_definitions_are_not_mistaken_for_records(self):
        """Children of udfdefinitions sit at record depth but are not records."""
        udf = "<udf><name>Box</name></udf><udf><name>Shelf</name></udf>"

        records, _ = clz.parse_xml(
            upload("e.xml", native_export(NATIVE_RECORDS[0], udf=udf)),
        )

        self.assertEqual(len(records), 1)

    def test_an_empty_envelope_is_reported(self):
        """A native export with no comics fails loudly, not as a silent import."""
        with self.assertRaisesMessage(MediaImportError, "no records"):
            clz.parse_xml(upload("e.xml", native_export()))

    def test_housekeeping_is_dropped_and_names_are_readable(self):
        """CLZ's sync bookkeeping never becomes a field; real data keeps a name."""
        records, columns = clz.parse_xml(
            upload("e.xml", native_export(NATIVE_RECORDS[0]))
        )

        for dropped in ("datasetversion", "hash", "index", "bpcomicid"):
            self.assertNotIn(dropped, [column.lower() for column in columns])
        record = records[0]
        self.assertEqual(record["Series"], "Test Series")
        self.assertEqual(record["Format"], "Manga")
        self.assertEqual(record["Store"], "Amazon")
        self.assertEqual(record["Year"], "2021")
        self.assertEqual(record["Purchase Date"], "2023/04/05")
        self.assertTrue(record["Cover URL"].endswith("test-1.jpg"))

    def test_owned_records_become_copies_and_the_rest_the_wishlist(self):
        """Owned records are copies; Wish List and On Order go to the list."""
        counts, _ = self.run_import()

        self.assertEqual(counts["collection"], 3)
        self.assertEqual(counts["wishlist"], 2)
        wishlist = CustomList.objects.get(owner=self.user, name=clz.WISHLIST_LIST_NAME)
        self.assertEqual(wishlist.customlistitem_set.count(), 1)

    def test_manga_volumes_share_one_series_item(self):
        """One series item holds every volume as a copy carrying its volume."""
        self.run_import()

        item = Item.objects.get(title="Test Series", media_type=MediaTypes.MANGA.value)
        entries = CollectionEntry.objects.filter(user=self.user, item=item)
        self.assertEqual(entries.count(), 3)
        field = CollectionField.objects.get(group__user=self.user, label="Volume")
        volumes = sorted(entry.custom_field_values[str(field.id)] for entry in entries)
        self.assertEqual(volumes, [1, 2, 2])

    def test_explicit_volume_column_is_kept_on_manga_copies(self):
        """A Volume column, not an issue column, still marks each copy."""
        csv = "Title,Series,Volume\nTest Series Vol. 1,Test Series,1\nTest Series Vol. 2,Test Series,2\n"
        clz.importer(
            upload("manga.csv", csv),
            self.user,
            "new",
            media_type=MediaTypes.MANGA.value,
        )

        item = Item.objects.get(title="Test Series", media_type=MediaTypes.MANGA.value)
        field = CollectionField.objects.get(group__user=self.user, label="Volume")
        volumes = sorted(
            entry.custom_field_values[str(field.id)]
            for entry in CollectionEntry.objects.filter(user=self.user, item=item)
        )
        self.assertEqual(volumes, [1, 2])

    def test_comics_keep_one_item_per_issue(self):
        """Issues stay separate items, with the issue saved on each copy."""
        self.run_import(media_type=MediaTypes.COMIC_ISSUE.value)

        self.assertTrue(Item.objects.filter(title="Test Series #2").exists())
        self.assertTrue(
            CollectionField.objects.filter(
                group__user=self.user,
                label="Issue Nr",
            ).exists(),
        )

    def test_clz_physical_details_are_kept(self):
        """Format, store, price and purchase date land on the copy."""
        self.run_import()

        entry = CollectionEntry.objects.filter(user=self.user).first()
        self.assertEqual(entry.media_type, "Manga")
        self.assertEqual(entry.purchase_location, "Amazon")
        self.assertEqual(str(entry.purchase_price), "10.00")
        self.assertEqual(entry.collected_at.date().isoformat(), "2023-04-05")

    def test_barcode_is_stored_and_supplement_is_ignored_for_lookup(self):
        """The copy keeps the printed barcode; lookups use the base number."""
        self.assertEqual(clz._clean_barcode("978123456789712345"), "9781234567897")
        self.assertEqual(clz._clean_barcode("9781234567897"), "9781234567897")
        self.assertEqual(clz._clean_barcode("123456789012"), "123456789012")
        self.assertEqual(clz._clean_barcode(""), "")
        self.assertEqual(clz._clean_barcode("097522980X"), "097522980X")
        self.assertEqual(clz._clean_barcode("0-9752-2980-x"), "097522980X")
        self.run_import()
        field = CollectionField.objects.get(group__user=self.user, label="Barcode")
        stored = {
            entry.custom_field_values.get(str(field.id))
            for entry in CollectionEntry.objects.filter(user=self.user)
        }
        self.assertIn("978123456789712345", stored)

    def test_series_is_searched_once_and_never_by_barcode(self):
        """A series asks its provider once, and no manga provider gets a barcode."""
        self.run_import()

        queries = [call.args[1] for call in self.search.call_args_list]
        self.assertEqual(queries, ["Test Series"])

    def test_clz_tags_are_kept_as_tags(self):
        """Every CLZ tag becomes the user's tag on the item, once."""
        self.run_import()

        names = set(Tag.objects.filter(user=self.user).values_list("name", flat=True))
        self.assertEqual(names, {"Gelesen", "Kleinanzeigen", "Missing"})
        item = Item.objects.get(title="Test Series")
        self.assertEqual(
            ItemTag.objects.filter(item=item, tag__user=self.user).count(),
            3,
        )

    def test_existing_tag_is_reused_case_insensitively(self):
        """A tag the user already has is not duplicated."""
        Tag.objects.create(user=self.user, name="gelesen")

        self.run_import()

        self.assertEqual(
            Tag.objects.filter(user=self.user, name__iexact="Gelesen").count(),
            1,
        )

    def test_the_best_cover_becomes_the_item_image(self):
        """When the download fails, the export's cover link is kept as the image."""
        self.run_import()

        item = Item.objects.get(title="Test Series")
        self.assertTrue(item.image.endswith("test-1.jpg"))

    def test_the_cover_is_copied_into_floppy(self):
        """A cover that downloads is stored locally, so CLZ going away costs nothing."""
        self.fetch_cover.side_effect = None
        self.fetch_cover.return_value = "/covers/" + "a" * 64 + ".jpg"

        self.run_import()

        item = Item.objects.get(title="Test Series")
        self.assertEqual(item.image, "/covers/" + "a" * 64 + ".jpg")

    def test_a_run_stops_downloading_after_repeated_failures(self):
        """An unreachable host is tried a few times, not once per record."""
        records = [
            native_record(
                f"Series {n}",
                "1",
                cover=f"https://clzcomics.r.sizr.io/c/{n}.jpg",
            )
            for n in range(clz.COVER_FAILURE_LIMIT + 3)
        ]
        self.run_import(native_export(*records))

        self.assertEqual(self.fetch_cover.call_count, clz.COVER_FAILURE_LIMIT)

    def test_wishlist_items_can_be_tagged_and_given_a_status(self):
        """The user picks a tag and a status to mark what CLZ calls wishlist."""
        self.run_import(wishlist_tag="Wanted", wishlist_status="Planning")

        item = Item.objects.get(title="Test Series")
        self.assertTrue(
            ItemTag.objects.filter(item=item, tag__name="Wanted").exists(),
        )
        self.assertEqual(
            Manga.objects.get(user=self.user, item=item).status,
            "Planning",
        )

    def test_wishlist_status_keeps_what_the_user_already_tracks(self):
        """An item the user already tracks keeps its own status."""
        item = Item.objects.create(
            media_id="m1",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.MANGA.value,
            library_media_type=MediaTypes.MANGA.value,
            title="Test Series",
            image="",
        )
        Manga.objects.create(user=self.user, item=item, status="Completed")

        self.run_import(wishlist_status="Planning")

        self.assertEqual(
            Manga.objects.get(user=self.user, item=item).status, "Completed"
        )

    def test_wishlist_choices_default_to_the_list_only(self):
        """Without a choice, wishlist rows only join the list."""
        self.run_import()

        self.assertFalse(Manga.objects.filter(user=self.user).exists())
        self.assertFalse(Tag.objects.filter(user=self.user, name="Wanted").exists())

    def test_reimport_in_either_mode_makes_no_duplicates(self):
        """New mode skips known copies; Overwrite updates them in place."""
        self.run_import()

        again, _ = self.run_import()
        overwritten, _ = self.run_import(mode="overwrite")

        self.assertEqual(again["skipped"], 3)
        self.assertEqual(overwritten["updated"], 3)
        self.assertEqual(CollectionEntry.objects.filter(user=self.user).count(), 3)

    def test_reordered_export_finds_the_same_copies(self):
        """A re-export in another order must not orphan or duplicate copies."""
        self.run_import()
        reordered = native_export(*reversed(NATIVE_RECORDS))

        counts, _ = self.run_import(reordered)

        self.assertEqual(counts["skipped"], 3)
        self.assertEqual(CollectionEntry.objects.filter(user=self.user).count(), 3)

    def test_records_without_a_barcode_or_title_still_import(self):
        """Blank barcodes are common; a record needs only its series."""
        counts, _ = self.run_import(native_export(native_record("No Code", "1")))

        self.assertEqual(counts["collection"], 1)

    def test_overwrite_moves_per_volume_manga_onto_the_series_item(self):
        """Copies imported as one item per volume move onto the series item."""
        self.run_import(media_type=MediaTypes.COMIC_ISSUE.value)
        self.run_import(mode="overwrite")

        item = Item.objects.get(title="Test Series", media_type=MediaTypes.MANGA.value)
        self.assertEqual(
            CollectionEntry.objects.filter(user=self.user, item=item).count(),
            3,
        )

    def test_import_page_offers_wishlist_choices(self):
        """The CLZ window has the wishlist status and tag controls."""
        self.client.force_login(self.user)

        response = self.client.get(reverse("import_data"))

        self.assertContains(response, 'name="clz_wishlist_status"')
        self.assertContains(response, 'name="clz_wishlist_tag"')

    def test_view_refuses_an_unknown_wishlist_status(self):
        """A made-up status is rejected before anything is queued."""
        self.client.force_login(self.user)

        with patch("integrations.views._queue_staged_task_or_message") as queue:
            response = self.client.post(
                reverse("import_clz"),
                {
                    "clz_export": upload("e.xml", native_export(NATIVE_RECORDS[0])),
                    "clz_wishlist_status": "Hoarding",
                },
                follow=True,
            )

        queue.assert_not_called()
        self.assertContains(response, "Unknown status for the CLZ wishlist items.")
