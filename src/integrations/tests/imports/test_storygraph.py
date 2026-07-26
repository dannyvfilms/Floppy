from datetime import datetime
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from app.models import Book, Item, Sources, Status
from integrations.imports import storygraph
from lists.models import CustomList, CustomListItem


class ParseReads(SimpleTestCase):
    """Tests for parsing StoryGraph's Dates Read column."""

    def test_range_gives_start_and_end(self):
        """A dash-separated range is a start date and an end date."""
        reads = storygraph.parse_reads("2022/03/16-2022/04/01")
        self.assertEqual(len(reads), 1)
        self.assertEqual(reads[0].start.date(), datetime(2022, 3, 16).date())  # noqa: DTZ001
        self.assertEqual(reads[0].end.date(), datetime(2022, 4, 1).date())  # noqa: DTZ001

    def test_single_date_is_end_only(self):
        """StoryGraph writes one date when only the finish date is known."""
        reads = storygraph.parse_reads("2021/07/21")
        self.assertEqual(len(reads), 1)
        self.assertIsNone(reads[0].start)
        self.assertEqual(reads[0].end.date(), datetime(2021, 7, 21).date())  # noqa: DTZ001

    def test_multiple_reads_sorted_oldest_first(self):
        """Re-reads are comma separated and come back oldest first."""
        reads = storygraph.parse_reads("2022/10/29-2022/11/28, 2021/09/14")
        self.assertEqual(len(reads), 2)
        self.assertEqual(reads[0].end.date(), datetime(2021, 9, 14).date())  # noqa: DTZ001
        self.assertEqual(reads[1].end.date(), datetime(2022, 11, 28).date())  # noqa: DTZ001

    def test_blank_and_garbage_ignored(self):
        """Empty or unparseable values produce no reads."""
        self.assertEqual(storygraph.parse_reads(""), [])
        self.assertEqual(storygraph.parse_reads(None), [])
        self.assertEqual(storygraph.parse_reads("not a date"), [])

    def test_dates_are_timezone_aware(self):
        """Parsed dates are aware so Django never warns on save."""
        read = storygraph.parse_reads("2021/07/21")[0]
        self.assertTrue(timezone.is_aware(read.end))


class ParseFields(SimpleTestCase):
    """Tests for the remaining column parsers."""

    def test_status_mapping(self):
        """Each StoryGraph read status maps to a Yamtrack status."""
        self.assertEqual(storygraph.determine_status("read"), Status.COMPLETED.value)
        self.assertEqual(
            storygraph.determine_status("currently-reading"),
            Status.IN_PROGRESS.value,
        )
        self.assertEqual(storygraph.determine_status("to-read"), Status.PLANNING.value)
        self.assertEqual(
            storygraph.determine_status("did-not-finish"),
            Status.DROPPED.value,
        )

    def test_blank_status_defaults_to_planning(self):
        """Rows with no read status are library entries, so plan them."""
        self.assertEqual(storygraph.determine_status(""), Status.PLANNING.value)
        self.assertEqual(storygraph.determine_status(None), Status.PLANNING.value)
        self.assertEqual(storygraph.determine_status("nonsense"), Status.PLANNING.value)

    def test_rating_doubled_to_ten_point_scale(self):
        """StoryGraph rates 0-5 with halves; Yamtrack scores 0-10."""
        self.assertEqual(storygraph.parse_rating("4.5"), 9.0)
        self.assertEqual(storygraph.parse_rating("5.0"), 10.0)
        self.assertIsNone(storygraph.parse_rating(""))
        self.assertIsNone(storygraph.parse_rating("0"))
        self.assertIsNone(storygraph.parse_rating("nonsense"))

    def test_tags_split_and_deduplicated(self):
        """Tags are comma separated free text."""
        self.assertEqual(
            storygraph.parse_tags("management, spanish , management"),
            ["management", "spanish"],
        )
        self.assertEqual(storygraph.parse_tags(""), [])

    def test_authors_split(self):
        """Multiple authors are comma separated in one column."""
        self.assertEqual(
            storygraph.parse_authors("Brandon Sanderson, Robert Jordan"),
            ["Brandon Sanderson", "Robert Jordan"],
        )
        self.assertEqual(storygraph.parse_authors(""), [])

    def test_isbn_normalization(self):
        """Only ISBN-10 and ISBN-13 values survive; ASINs do not."""
        self.assertEqual(
            storygraph.normalize_isbn("978-0-575-07979-3"), "9780575079793"
        )
        self.assertEqual(storygraph.normalize_isbn("080442957X"), "080442957X")
        self.assertEqual(storygraph.normalize_isbn("B0851JCZYV"), "")
        self.assertEqual(storygraph.normalize_isbn(""), "")

    def test_format_mapping(self):
        """StoryGraph formats map onto the values Yamtrack already uses."""
        self.assertEqual(storygraph.map_format("digital"), "ebook")
        self.assertEqual(storygraph.map_format("audio"), "audiobook")
        self.assertEqual(storygraph.map_format("paperback"), "paperback")
        self.assertEqual(storygraph.map_format("hardcover"), "hardcover")
        self.assertEqual(storygraph.map_format(""), "")
        self.assertEqual(storygraph.map_format("something else"), "")


class MatchingHelpers(SimpleTestCase):
    """Tests for the title and author comparison helpers."""

    def test_titles_match_tolerates_subtitles(self):
        """A provider title with a subtitle still matches the CSV title."""
        self.assertTrue(
            storygraph.titles_match("Mistborn", "Mistborn: The Final Empire")
        )
        self.assertTrue(
            storygraph.titles_match("The Blade Itself", "the blade itself")
        )

    def test_titles_do_not_match_across_books(self):
        """Unrelated titles do not match."""
        self.assertFalse(storygraph.titles_match("Mistborn", "The God Delusion"))
        self.assertFalse(storygraph.titles_match("", "Mistborn"))

    def test_author_classification(self):
        """Authors classify as match, unknown, or conflict."""
        self.assertEqual(
            storygraph.classify_authors(["Joe Abercrombie"], ["Joe Abercrombie"]),
            "match",
        )
        self.assertEqual(
            storygraph.classify_authors(["Joe Abercrombie"], ["J. Abercrombie"]),
            "match",
        )
        self.assertEqual(
            storygraph.classify_authors(["Joe Abercrombie"], []), "unknown"
        )
        self.assertEqual(
            storygraph.classify_authors(["Joe Abercrombie"], ["Robin Hobb"]),
            "conflict",
        )
        self.assertEqual(storygraph.classify_authors([], ["Robin Hobb"]), "match")

    def test_extract_provider_authors_handles_shapes(self):
        """Provider metadata carries authors as strings, lists, or dicts."""
        self.assertEqual(
            storygraph.extract_provider_authors(
                {"details": {"author": ["Robin Hobb"]}},
            ),
            ["Robin Hobb"],
        )
        self.assertEqual(
            storygraph.extract_provider_authors(
                {"details": {"authors": [{"name": "Robin Hobb"}]}},
            ),
            ["Robin Hobb"],
        )
        self.assertEqual(
            storygraph.extract_provider_authors({"details": {"author": "Robin Hobb"}}),
            ["Robin Hobb"],
        )
        self.assertEqual(storygraph.extract_provider_authors({}), [])


class BookResolverTests(SimpleTestCase):
    """Tests for resolving CSV rows against metadata providers."""

    def setUp(self):
        """Build the provider fixtures shared by these tests."""
        self.metadata = {
            "1": {
                "media_id": "1",
                "title": "The Blade Itself",
                "image": "https://example.com/blade.jpg",
                "max_progress": 515,
                "details": {"author": ["Joe Abercrombie"]},
            },
            "2": {
                "media_id": "2",
                "title": "A Completely Different Book",
                "image": "https://example.com/other.jpg",
                "max_progress": 100,
                "details": {"author": ["Someone Else"]},
            },
        }

    def _search(self, results_by_query):
        def search(_media_type, query, _page, source):
            return {"results": results_by_query.get((source, query), [])}

        return search

    def _metadata(self, _media_type, media_id, _source):
        return self.metadata[str(media_id)]

    def test_isbn_hit_on_hardcover_wins(self):
        """An ISBN search on Hardcover short circuits the ladder."""
        search = self._search(
            {
                (Sources.HARDCOVER.value, "9780575079793"): [
                    {"media_id": "1", "title": "The Blade Itself"}
                ]
            },
        )
        with patch(
            "integrations.imports.storygraph.services.search",
            side_effect=search,
        ), patch(
            "integrations.imports.storygraph.services.get_media_metadata",
            side_effect=self._metadata,
        ):
            resolved = storygraph.BookResolver({}).resolve(
                "The Blade Itself",
                ["Joe Abercrombie"],
                "9780575079793",
            )

        self.assertIsNotNone(resolved)
        source, media_id, metadata = resolved
        self.assertEqual(source, Sources.HARDCOVER.value)
        self.assertEqual(media_id, "1")
        self.assertEqual(metadata["max_progress"], 515)

    def test_falls_back_to_openlibrary(self):
        """A book Hardcover cannot find is looked up on Open Library."""
        search = self._search(
            {
                (Sources.OPENLIBRARY.value, "The Blade Itself Joe Abercrombie"): [
                    {"media_id": "1", "title": "The Blade Itself"},
                ]
            },
        )
        with patch(
            "integrations.imports.storygraph.services.search",
            side_effect=search,
        ), patch(
            "integrations.imports.storygraph.services.get_media_metadata",
            side_effect=self._metadata,
        ):
            resolved = storygraph.BookResolver({}).resolve(
                "The Blade Itself",
                ["Joe Abercrombie"],
                "",
            )

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved[0], Sources.OPENLIBRARY.value)

    def test_wrong_title_is_rejected(self):
        """A search result for a different book is not accepted."""
        search = self._search(
            {
                (Sources.HARDCOVER.value, "The Blade Itself Joe Abercrombie"): [
                    {"media_id": "2", "title": "A Completely Different Book"},
                ]
            },
        )
        with patch(
            "integrations.imports.storygraph.services.search",
            side_effect=search,
        ), patch(
            "integrations.imports.storygraph.services.get_media_metadata",
            side_effect=self._metadata,
        ):
            resolved = storygraph.BookResolver({}).resolve(
                "The Blade Itself",
                ["Joe Abercrombie"],
                "",
            )

        self.assertIsNone(resolved)

    def test_provider_error_does_not_propagate(self):
        """A provider blowing up leaves the book unresolved, not the import."""
        with patch(
            "integrations.imports.storygraph.services.search",
            side_effect=Exception("provider down"),
        ):
            resolved = storygraph.BookResolver({}).resolve("Whatever", [], "")

        self.assertIsNone(resolved)

    def test_resolution_is_cached(self):
        """Resolving the same book twice hits the provider once."""
        calls = []

        def search(_media_type, query, _page, source):
            calls.append(query)
            if (source, query) == (Sources.HARDCOVER.value, "9780575079793"):
                return {"results": [{"media_id": "1", "title": "The Blade Itself"}]}
            return {"results": []}

        cache = {}
        with patch(
            "integrations.imports.storygraph.services.search",
            side_effect=search,
        ), patch(
            "integrations.imports.storygraph.services.get_media_metadata",
            side_effect=self._metadata,
        ):
            resolver = storygraph.BookResolver(cache)
            first = resolver.resolve(
                "The Blade Itself", ["Joe Abercrombie"], "9780575079793"
            )
            second = resolver.resolve(
                "The Blade Itself", ["Joe Abercrombie"], "9780575079793"
            )

        self.assertEqual(first, second)
        self.assertEqual(calls.count("9780575079793"), 1)


mock_path = Path(__file__).resolve().parent.parent / "mock_data"

PROVIDER_BOOKS = {
    "The Blade Itself": {"media_id": "1", "pages": 515, "author": "Joe Abercrombie"},
    "Kindle Only": {"media_id": "2", "pages": 300, "author": "Some Author"},
    "No Isbn Book": {"media_id": "3", "pages": 200, "author": "Another Author"},
    "Re-read Book": {"media_id": "4", "pages": 400, "author": "Third Author"},
    "Current Book": {"media_id": "5", "pages": 350, "author": "Fourth Author"},
    "Planned Book": {"media_id": "6", "pages": 1007, "author": "Fifth Author"},
    "Dnf Book": {"media_id": "7", "pages": 250, "author": "Sixth Author"},
    "Tagged Only Book": {"media_id": "8", "pages": 150, "author": "Seventh Author"},
    "Audio Book": {"media_id": "9", "pages": 320, "author": "Eighth Author"},
}
PROVIDER_BY_ID = {
    book["media_id"]: (title, book) for title, book in PROVIDER_BOOKS.items()
}


def fake_search(_media_type, query, _page, source):
    """Return a hit when the query names or identifies a fixture book."""
    if source != Sources.HARDCOVER.value:
        return {"results": []}
    for title, book in PROVIDER_BOOKS.items():
        if title.lower() in query.lower():
            return {"results": [{"media_id": book["media_id"], "title": title}]}
    return {"results": []}


def fake_metadata(_media_type, media_id, _source):
    """Return provider metadata for a fixture book."""
    title, book = PROVIDER_BY_ID[str(media_id)]
    return {
        "media_id": book["media_id"],
        "title": title,
        "image": f"https://example.com/{book['media_id']}.jpg",
        "max_progress": book["pages"],
        "details": {"author": [book["author"]]},
    }


class ImportStoryGraph(TestCase):
    """Tests for importing a StoryGraph export."""

    def setUp(self):
        """Import the fixture export with the providers mocked out."""
        self.user = get_user_model().objects.create_user(
            username="test",
            password="12345",  # noqa: S106 - test credential
        )
        with patch(
            "integrations.imports.storygraph.services.search",
            side_effect=fake_search,
        ), patch(
            "integrations.imports.storygraph.services.get_media_metadata",
            side_effect=fake_metadata,
        ), Path(mock_path / "import_storygraph.csv").open("rb") as file:
            self.counts, self.messages = storygraph.importer(file, self.user, "new")

    def _books(self, title):
        return Book.objects.filter(
            user=self.user, item__title=title,
        ).order_by("end_date")

    def test_entry_count(self):
        """Nine resolvable rows produce ten entries, the re-read counting twice."""
        self.assertEqual(Book.objects.filter(user=self.user).count(), 10)
        self.assertEqual(self.counts["book"], 10)

    def test_completed_read_dates(self):
        """A dash separated read keeps its start and end date."""
        book = self._books("The Blade Itself").get()
        self.assertEqual(book.status, Status.COMPLETED.value)
        self.assertEqual(book.start_date.date(), datetime(2021, 1, 20).date())  # noqa: DTZ001
        self.assertEqual(book.end_date.date(), datetime(2021, 2, 9).date())  # noqa: DTZ001

    def test_finish_date_only_leaves_start_null(self):
        """A bare date is a finish date, not a one day read."""
        book = self._books("Kindle Only").get()
        self.assertIsNone(book.start_date)
        self.assertEqual(book.end_date.date(), datetime(2025, 7, 16).date())  # noqa: DTZ001

    def test_reread_creates_two_entries(self):
        """Each read in Dates Read becomes its own entry."""
        books = list(self._books("Re-read Book"))
        self.assertEqual(len(books), 2)
        self.assertEqual(books[0].end_date.date(), datetime(2021, 9, 14).date())  # noqa: DTZ001
        self.assertEqual(books[1].end_date.date(), datetime(2022, 11, 28).date())  # noqa: DTZ001

    def test_rating_only_on_newest_read(self):
        """One StoryGraph rating must not be counted once per re-read."""
        books = list(self._books("Re-read Book"))
        self.assertIsNone(books[0].score)
        self.assertEqual(float(books[1].score), 10.0)

    def test_review_becomes_notes(self):
        """The Review column lands in notes."""
        book = self._books("The Blade Itself").get()
        self.assertEqual(book.notes, "Grim and funny.")
        self.assertEqual(float(book.score), 9.0)

    def test_progress_from_provider_page_count(self):
        """Completed books take their page count from provider metadata."""
        self.assertEqual(self._books("The Blade Itself").get().progress, 515)
        self.assertEqual(self._books("Planned Book").get().progress, 0)

    def test_audiobook_keeps_zero_progress(self):
        """Audiobook progress is minutes, so a page count would render wrong."""
        book = self._books("Audio Book").get()
        self.assertEqual(book.status, Status.COMPLETED.value)
        self.assertEqual(book.progress, 0)
        self.assertEqual(book.item.format, "audiobook")

    def test_status_mapping_across_rows(self):
        """Every read status maps through to the tracked entry."""
        current_status = self._books("Current Book").get().status
        self.assertEqual(current_status, Status.IN_PROGRESS.value)
        planned_status = self._books("Planned Book").get().status
        self.assertEqual(planned_status, Status.PLANNING.value)
        dnf_status = self._books("Dnf Book").get().status
        self.assertEqual(dnf_status, Status.DROPPED.value)
        tagged_status = self._books("Tagged Only Book").get().status
        self.assertEqual(tagged_status, Status.PLANNING.value)

    def test_date_added_is_never_a_start_date(self):
        """Date Added is when a book was shelved, not when reading began."""
        self.assertIsNone(self._books("Current Book").get().start_date)
        self.assertIsNone(self._books("Current Book").get().end_date)

    def test_read_without_dates_has_no_dates(self):
        """A read with no dates is completed but contributes no calendar day."""
        book = self._books("No Isbn Book").get()
        self.assertEqual(book.status, Status.COMPLETED.value)
        self.assertIsNone(book.start_date)
        self.assertIsNone(book.end_date)

    def test_format_written_only_when_empty(self):
        """Item.format is shared between users, so an existing value stands."""
        item = Item.objects.get(title="The Blade Itself")
        self.assertEqual(item.format, "ebook")

        item.format = "hardcover"
        item.save(update_fields=["format"])
        with patch(
            "integrations.imports.storygraph.services.search",
            side_effect=fake_search,
        ), patch(
            "integrations.imports.storygraph.services.get_media_metadata",
            side_effect=fake_metadata,
        ), Path(mock_path / "import_storygraph.csv").open("rb") as file:
            storygraph.importer(file, self.user, "new")

        item.refresh_from_db()
        self.assertEqual(item.format, "hardcover")

    def test_unresolvable_book_warns(self):
        """A book no provider knows is reported, not imported."""
        self.assertIn("Missing Book", self.messages)
        self.assertFalse(Book.objects.filter(item__title="Missing Book").exists())

    def test_history_record_dated_from_the_read(self):
        """The history record is stamped with the read's end date."""
        book = self._books("The Blade Itself").get()
        record = book.history.first()
        self.assertEqual(record.history_date.date(), datetime(2021, 2, 9).date())  # noqa: DTZ001


class ImportStoryGraphTags(TestCase):
    """Tests for mapping StoryGraph tags onto custom lists."""

    def setUp(self):
        """Create the user and import the fixture."""
        self.user = get_user_model().objects.create_user(
            username="test",
            password="12345",  # noqa: S106 - test credential
        )
        self._import()

    def _import(self):
        with patch(
            "integrations.imports.storygraph.services.search",
            side_effect=fake_search,
        ), patch(
            "integrations.imports.storygraph.services.get_media_metadata",
            side_effect=fake_metadata,
        ), Path(mock_path / "import_storygraph.csv").open("rb") as file:
            return storygraph.importer(file, self.user, "new")

    def test_lists_created_from_tags(self):
        """Each tag becomes a local custom list owned by the user."""
        names = set(
            CustomList.objects.filter(owner=self.user).values_list("name", flat=True),
        )
        self.assertEqual(names, {"fantasy", "management", "spanish"})

    def test_items_added_to_their_lists(self):
        """A tagged book joins every list its tags name."""
        tagged = Item.objects.get(title="Tagged Only Book")
        list_names = set(
            CustomListItem.objects.filter(item=tagged).values_list(
                "custom_list__name",
                flat=True,
            ),
        )
        self.assertEqual(list_names, {"management", "spanish"})

    def test_membership_is_idempotent(self):
        """Re-importing does not duplicate lists or memberships."""
        self._import()
        self.assertEqual(CustomList.objects.filter(owner=self.user).count(), 3)
        self.assertEqual(
            CustomListItem.objects.filter(custom_list__owner=self.user).count(),
            3,
        )


class ImportStoryGraphDeduplication(TestCase):
    """Tests that re-importing does not duplicate reads."""

    def setUp(self):
        """Create the user and import the fixture once."""
        self.user = get_user_model().objects.create_user(
            username="test",
            password="12345",  # noqa: S106 - test credential
        )
        self._import()

    def _import(self, mode="new", rows=None):
        """Import the fixture, or a custom CSV body, with providers mocked."""
        if rows is None:
            source_file = Path(  # noqa: SIM115 - closed by the with-block below
                mock_path / "import_storygraph.csv",
            ).open("rb")
        else:
            source_file = BytesIO(rows.encode("utf-8"))
        with patch(
            "integrations.imports.storygraph.services.search",
            side_effect=fake_search,
        ), patch(
            "integrations.imports.storygraph.services.get_media_metadata",
            side_effect=fake_metadata,
        ), source_file as file:
            return storygraph.importer(file, self.user, mode)

    def test_reimport_creates_nothing(self):
        """Importing the same export twice leaves the entry count unchanged."""
        before = Book.objects.filter(user=self.user).count()
        counts, _ = self._import()
        self.assertEqual(Book.objects.filter(user=self.user).count(), before)
        self.assertEqual(counts.get("book", 0), 0)

    def test_new_read_creates_one_entry(self):
        """A read added in StoryGraph after the first import arrives."""
        header = Path(mock_path / "import_storygraph.csv").read_text().splitlines()[0]
        row = (
            'The Blade Itself,Joe Abercrombie,"",9780575079793,digital,read,'
            '2021/01/01,2026/05/10,"2021/01/20-2021/02/09, 2026/05/01-2026/05/10",2,'
            '"",,,,,,,4.5,Grim and funny.,"",,"fantasy",No'
        )
        counts, _ = self._import(rows=f"{header}\n{row}\n")

        self.assertEqual(counts.get("book", 0), 1)
        books = Book.objects.filter(
            user=self.user, item__title="The Blade Itself",
        ).order_by("end_date")
        self.assertEqual(books.count(), 2)
        preexisting, new_read = books
        self.assertEqual(float(preexisting.score), 9.0)
        self.assertIsNone(new_read.score)
        self.assertEqual(new_read.notes, "")

    def test_dateless_read_not_duplicated(self):
        """A read with no dates is added once and never again."""
        counts, _ = self._import()
        self.assertEqual(counts.get("book", 0), 0)
        self.assertEqual(
            Book.objects.filter(user=self.user, item__title="No Isbn Book").count(),
            1,
        )

    def test_overwrite_rebuilds_entries(self):
        """Overwrite mode replaces the book's entries rather than adding to them."""
        counts, _ = self._import(mode="overwrite")
        self.assertEqual(counts.get("book", 0), 10)
        self.assertEqual(Book.objects.filter(user=self.user).count(), 10)
        self.assertEqual(
            Book.objects.filter(user=self.user, item__title="Re-read Book").count(),
            2,
        )

    def test_overwrite_does_not_wipe_twice_for_duplicate_rows(self):
        """Two CSV rows for one book in overwrite mode do not duplicate reads."""
        header = Path(mock_path / "import_storygraph.csv").read_text().splitlines()[0]
        row = (
            'The Blade Itself,Joe Abercrombie,"",9780575079793,digital,read,'
            "2021/01/01,2021/02/09,2021/01/20-2021/02/09,1,"
            '"",,,,,,,4.5,Grim and funny.,"",,"fantasy",No'
        )
        counts, _ = self._import(mode="overwrite", rows=f"{header}\n{row}\n{row}\n")

        self.assertEqual(counts.get("book", 0), 1)
        books = Book.objects.filter(user=self.user, item__title="The Blade Itself")
        self.assertEqual(books.count(), 1)
        self.assertEqual(float(books.get().score), 9.0)
