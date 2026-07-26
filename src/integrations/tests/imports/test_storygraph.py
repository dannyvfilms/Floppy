from datetime import datetime
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from app.models import Sources, Status
from integrations.imports import storygraph


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
