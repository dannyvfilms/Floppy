from datetime import datetime

from django.test import SimpleTestCase
from django.utils import timezone

from app.models import Status
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
