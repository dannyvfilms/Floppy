from unittest import skipUnless
from unittest.mock import Mock, patch

from django.db import OperationalError, connection
from django.test import SimpleTestCase, TestCase

from app.db_retry import (
    BRIEF_WRITER_WAIT_MS,
    _describe_conflicting_row,
    brief_writer_wait,
    in_read_request,
    optional_save,
    read_request,
    update_or_create_race_safe,
)
from app.models import Item, ItemProviderLink, MediaTypes, Sources


class UpdateOrCreateRaceSafeTests(TestCase):
    """Tests for update_or_create_race_safe's conflict handling."""

    def setUp(self):
        """Create two distinct tracked items to link providers against."""
        self.item_a = Item.objects.create(
            media_id="1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Show A",
            season_number=1,
        )
        self.item_b = Item.objects.create(
            media_id="2",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Show B",
            season_number=1,
        )

    def test_happy_path_creates_row(self):
        """A non-conflicting call creates the row normally."""
        link, created = update_or_create_race_safe(
            ItemProviderLink.objects,
            item=self.item_a,
            provider=Sources.TVDB.value,
            provider_media_type=MediaTypes.SEASON.value,
            season_number=1,
            defaults={"provider_media_id": "111"},
        )
        self.assertTrue(created)
        self.assertEqual(link.provider_media_id, "111")

    def test_updates_existing_row_on_matching_lookup(self):
        """A second call with the same lookup updates in place."""
        update_or_create_race_safe(
            ItemProviderLink.objects,
            item=self.item_a,
            provider=Sources.TVDB.value,
            provider_media_type=MediaTypes.SEASON.value,
            season_number=1,
            defaults={"provider_media_id": "111"},
        )
        link, created = update_or_create_race_safe(
            ItemProviderLink.objects,
            item=self.item_a,
            provider=Sources.TVDB.value,
            provider_media_type=MediaTypes.SEASON.value,
            season_number=1,
            defaults={"provider_media_id": "222"},
        )
        self.assertFalse(created)
        self.assertEqual(link.provider_media_id, "222")

    def test_returns_none_false_on_persistent_conflict(self):
        """A conflicting provider_media_id must not raise.

        Already claimed by a different item's link under the same
        (provider, provider_media_type, season_number), it should be
        skipped and reported as (None, False).
        """
        ItemProviderLink.objects.create(
            item=self.item_a,
            provider=Sources.TVDB.value,
            provider_media_type=MediaTypes.SEASON.value,
            season_number=1,
            provider_media_id="303821",
        )

        result, created = update_or_create_race_safe(
            ItemProviderLink.objects,
            item=self.item_b,
            provider=Sources.TVDB.value,
            provider_media_type=MediaTypes.SEASON.value,
            season_number=1,
            defaults={"provider_media_id": "303821"},
        )

        self.assertIsNone(result)
        self.assertFalse(created)

    def test_logs_conflicting_row_diagnostic(self):
        """The persistent-conflict warning should be diagnosable.

        It should include the raw DB error and identify the pre-existing
        conflicting row.
        """
        ItemProviderLink.objects.create(
            item=self.item_a,
            provider=Sources.TVDB.value,
            provider_media_type=MediaTypes.SEASON.value,
            season_number=1,
            provider_media_id="303821",
        )

        with self.assertLogs("app.db_retry", level="WARNING") as logs:
            update_or_create_race_safe(
                ItemProviderLink.objects,
                item=self.item_b,
                provider=Sources.TVDB.value,
                provider_media_type=MediaTypes.SEASON.value,
                season_number=1,
                defaults={"provider_media_id": "303821"},
            )

        message = "\n".join(logs.output)
        self.assertIn("Persistent IntegrityError", message)
        self.assertIn("UNIQUE constraint failed", message)
        self.assertIn("303821", message)


class DescribeConflictingRowTests(TestCase):
    """Tests for the _describe_conflicting_row diagnostic helper."""

    def test_returns_unknown_when_defaults_not_probeable(self):
        """Non-scalar-only lookup/defaults yield an explicit unknown result."""
        result = _describe_conflicting_row(
            ItemProviderLink.objects,
            {},
            {"metadata": {"foo": "bar"}},
        )
        self.assertEqual(
            result,
            "unknown (no probeable scalar fields in lookup/defaults)",
        )

    def test_never_raises_on_bad_input(self):
        """An invalid field name in lookup/defaults must not propagate."""
        result = _describe_conflicting_row(
            ItemProviderLink.objects,
            {},
            {"not_a_real_field": object()},
        )
        self.assertIsInstance(result, str)

    def test_lookup_fields_narrow_the_probe(self):
        """The probe must use lookup fields, not just defaults.

        A `defaults`-only probe would match a row sharing provider_media_id
        regardless of season_number, producing a false-positive "conflicting
        row" (issue #326 follow-up: the original diagnostic listed an
        unrelated season-2 row alongside the real season-3 conflict).
        """
        item = Item.objects.create(
            media_id="1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Show A",
            season_number=2,
        )
        ItemProviderLink.objects.create(
            item=item,
            provider=Sources.TVDB.value,
            provider_media_type=MediaTypes.SEASON.value,
            season_number=2,
            provider_media_id="303821",
        )

        result = _describe_conflicting_row(
            ItemProviderLink.objects,
            {
                "provider": Sources.TVDB.value,
                "provider_media_type": MediaTypes.SEASON.value,
                "season_number": 3,
            },
            {"provider_media_id": "303821"},
        )

        self.assertEqual(
            result,
            "unknown (no existing row matches the attempted lookup/defaults)",
        )


def _busy_timeout_ms():
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA busy_timeout")
        return int(cursor.fetchone()[0])


@skipUnless(connection.vendor == "sqlite", "busy_timeout is a SQLite setting.")
class BriefWriterWaitTests(TestCase):
    """The short wait must never outlive its block: connections are reused."""

    def setUp(self):
        """Give the connection a recognisable timeout to restore."""
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA busy_timeout=4321")

    def test_lowers_the_timeout_and_restores_it(self):
        with brief_writer_wait():
            self.assertEqual(_busy_timeout_ms(), BRIEF_WRITER_WAIT_MS)
        self.assertEqual(_busy_timeout_ms(), 4321)

    def test_restores_the_timeout_when_the_block_raises(self):
        with self.assertRaises(OperationalError), brief_writer_wait():
            msg = "database is locked"
            raise OperationalError(msg)
        self.assertEqual(_busy_timeout_ms(), 4321)

    def test_nested_blocks_restore_in_order(self):
        with brief_writer_wait(200):
            with brief_writer_wait(0):
                self.assertEqual(_busy_timeout_ms(), 0)
            self.assertEqual(_busy_timeout_ms(), 200)
        self.assertEqual(_busy_timeout_ms(), 4321)

    def test_optional_save_changes_nothing_outside_a_page_load(self):
        self.assertFalse(in_read_request())
        with optional_save():
            self.assertEqual(_busy_timeout_ms(), 4321)

    def test_optional_save_waits_briefly_once_per_page_load(self):
        with read_request():
            self.assertTrue(in_read_request())
            with self.assertRaises(OperationalError), optional_save():
                self.assertEqual(_busy_timeout_ms(), BRIEF_WRITER_WAIT_MS)
                msg = "database is locked"
                raise OperationalError(msg)
            # The writer was busy: later saves in this page load do not wait.
            with optional_save():
                self.assertEqual(_busy_timeout_ms(), 0)
            self.assertEqual(_busy_timeout_ms(), 4321)
        self.assertFalse(in_read_request())

    def test_an_unrelated_error_does_not_mark_the_writer_busy(self):
        with read_request():
            with self.assertRaises(OperationalError), optional_save():
                msg = "no such table: nothing"
                raise OperationalError(msg)
            with optional_save():
                self.assertEqual(_busy_timeout_ms(), BRIEF_WRITER_WAIT_MS)


class BriefWriterWaitOtherDatabasesTests(SimpleTestCase):
    """PostgreSQL has no single writer to wait for: the block does nothing."""

    def test_no_statement_is_issued_on_postgresql(self):
        postgres = Mock(vendor="postgresql")
        with (
            patch("app.db_retry.connections", {"default": postgres}),
            read_request(),
            optional_save(),
        ):
            pass
        postgres.cursor.assert_not_called()
