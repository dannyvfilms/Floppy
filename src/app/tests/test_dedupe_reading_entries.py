"""Tests for the dedupe_reading_entries repair command."""

from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from app.models import Book, DeletedMedia, Item, MediaTypes, Sources, Status


def _patch_media_metadata(test_case):
    """Stop book saves from making provider calls."""
    metadata_patch = patch(
        "app.models.media.providers.services.get_media_metadata",
        return_value={"max_progress": 1},
    )
    fetch_releases_patch = patch("app.models.Item.fetch_releases")
    metadata_patch.start()
    fetch_releases_patch.start()
    test_case.addCleanup(metadata_patch.stop)
    test_case.addCleanup(fetch_releases_patch.stop)


class DedupeReadingEntriesTests(TestCase):
    """The command collapses same-day duplicates without touching re-reads."""

    def setUp(self):
        _patch_media_metadata(self)
        self.user = get_user_model().objects.create_user(
            username="reader",
            password="12345",
        )
        self.item = Item.objects.create(
            media_id="book-1",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.BOOK.value,
            title="Doubled Book",
            image="http://example.com/x.jpg",
        )
        self.day = timezone.localtime().replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

    def _book(self, end_date, **kwargs):
        return Book.objects.create(
            item=self.item,
            user=self.user,
            status=kwargs.pop("status", Status.COMPLETED.value),
            progress=kwargs.pop("progress", 0),
            end_date=end_date,
            **kwargs,
        )

    def _run(self, *args):
        out = StringIO()
        call_command("dedupe_reading_entries", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_reports_without_deleting(self):
        """The default run writes nothing."""
        self._book(self.day, score=9)
        self._book(self.day)

        output = self._run()

        self.assertEqual(Book.objects.filter(user=self.user).count(), 2)
        self.assertIn("DRY RUN", output)
        self.assertIn("Doubled Book", output)

    def test_apply_keeps_one_row_per_day(self):
        """Two rows on the same local day collapse to one."""
        keeper = self._book(self.day, score=9)
        self._book(self.day)

        self._run("--apply")

        remaining = Book.objects.filter(user=self.user)
        self.assertEqual(remaining.count(), 1)
        self.assertEqual(remaining.get().pk, keeper.pk)

    def test_genuine_reread_is_left_alone(self):
        """Reads on different days are separate reads, not duplicates."""
        self._book(self.day)
        self._book(self.day - timedelta(days=400))

        self._run("--apply")

        self.assertEqual(Book.objects.filter(user=self.user).count(), 2)

    def test_values_are_folded_into_the_survivor(self):
        """A rating living on the duplicate row is not lost with it."""
        keeper = self._book(self.day)
        self._book(self.day, score=8, notes="Good")

        self._run("--apply")

        keeper.refresh_from_db()
        self.assertEqual(float(keeper.score), 8)
        self.assertEqual(keeper.notes, "Good")

    def test_the_survivors_own_values_win(self):
        """Merging only fills gaps - it never overwrites what the keeper has."""
        keeper = self._book(self.day, score=9, notes="Mine")
        self._book(self.day, score=3, notes="Theirs")

        self._run("--apply")

        keeper.refresh_from_db()
        self.assertEqual(float(keeper.score), 9)
        self.assertEqual(keeper.notes, "Mine")

    def test_a_start_date_only_on_the_duplicate_is_kept(self):
        """The import writes start dates the older row often lacks."""
        keeper = self._book(self.day)
        self._book(self.day, start_date=self.day - timedelta(days=10))

        self._run("--apply")

        keeper.refresh_from_db()
        self.assertIsNotNone(keeper.start_date)
        self.assertEqual(
            timezone.localdate(keeper.start_date),
            timezone.localdate(self.day - timedelta(days=10)),
        )

    def test_survivor_does_not_leave_a_deletion_tombstone(self):
        """Removing a duplicate must not make imports skip a book still tracked."""
        self._book(self.day, score=9)
        self._book(self.day)

        self._run("--apply")

        self.assertFalse(
            DeletedMedia.objects.filter(
                user=self.user,
                media_id=self.item.media_id,
            ).exists(),
        )

    def test_other_users_are_not_touched(self):
        """Rows are grouped per user."""
        other = get_user_model().objects.create_user(
            username="other",
            password="12345",
        )
        Book.objects.create(
            item=self.item,
            user=other,
            status=Status.COMPLETED.value,
            end_date=self.day,
        )
        self._book(self.day)

        self._run("--apply", "--username", "reader")

        self.assertEqual(Book.objects.filter(user=other).count(), 1)
