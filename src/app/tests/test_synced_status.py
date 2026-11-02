"""Tests for the book-sync held-status rule (#1316)."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from app.models import Book, Item, MediaTypes, Sources, Status
from app.services.synced_status import keep_held_status, status_changed_at
from integrations.plex_audiobook_sync import upsert_plex_audiobook

MINUTE_MS = 60 * 1000


class KeepHeldStatusTests(TestCase):
    """Which status a progress sync may write over an existing book."""

    def setUp(self):
        """Create a tracked book the user has paused."""
        self.user = get_user_model().objects.create_user(username="u", password="p")
        self.item = Item.objects.create(
            media_id="1",
            source=Sources.HARDCOVER.value,
            media_type=MediaTypes.BOOK.value,
            title="Dune",
            number_of_pages=400,
        )
        self.book = Book.objects.create(
            user=self.user,
            item=self.item,
            status=Status.IN_PROGRESS.value,
            progress=100,
        )
        self.book.status = Status.PAUSED.value
        self.book.save()
        self.before = timezone.now() - timedelta(minutes=5)
        self.after = timezone.now() + timedelta(minutes=5)

    def _reported(self, status=Status.IN_PROGRESS.value):
        return {"progress": 150, "status": status, "end_date": None}

    def test_status_changed_at_is_when_the_current_status_began(self):
        """The time comes from the first history row in the current status."""
        paused_at = self.book.history.order_by("-history_date").first().history_date
        self.book.progress = 120
        self.book.save()

        self.assertEqual(status_changed_at(self.book), paused_at)

    def test_new_book_takes_the_reported_status(self):
        """With nothing tracked yet, the service decides."""
        self.assertEqual(
            keep_held_status(None, self._reported(), self.before)["status"],
            Status.IN_PROGRESS.value,
        )

    def test_activity_before_the_pause_keeps_it(self):
        """Progress still updates; the status stays."""
        result = keep_held_status(self.book, self._reported(), self.before)

        self.assertEqual(result["status"], Status.PAUSED.value)
        self.assertEqual(result["progress"], 150)

    def test_activity_after_the_pause_resumes(self):
        """New reading after the pause is a real return to the book."""
        result = keep_held_status(self.book, self._reported(), self.after)

        self.assertEqual(result["status"], Status.IN_PROGRESS.value)

    def test_no_activity_time_keeps_the_status(self):
        """Without a time the sync cannot show the user came back."""
        result = keep_held_status(self.book, self._reported(), None)

        self.assertEqual(result["status"], Status.PAUSED.value)

    def test_finish_always_wins(self):
        """A service reporting the book finished completes it."""
        result = keep_held_status(
            self.book,
            self._reported(Status.COMPLETED.value),
            self.before,
        )

        self.assertEqual(result["status"], Status.COMPLETED.value)

    def test_completed_keeps_its_progress_and_end_date(self):
        """A held Completed book is not rewound to the service's position."""
        self.book.status = Status.COMPLETED.value
        self.book.save()
        self.book.refresh_from_db()

        result = keep_held_status(self.book, self._reported(), self.before)

        self.assertEqual(result["status"], Status.COMPLETED.value)
        self.assertEqual(result["progress"], self.book.progress)
        self.assertEqual(result["end_date"], self.book.end_date)

    def test_in_progress_follows_the_service(self):
        """Statuses a sync writes itself are never held."""
        self.book.status = Status.IN_PROGRESS.value
        self.book.save()

        result = keep_held_status(
            self.book,
            self._reported(Status.PLANNING.value),
            self.before,
        )

        self.assertEqual(result["status"], Status.PLANNING.value)


class PlexAudiobookHeldStatusTests(TestCase):
    """The Plex audiobook sync uses the same rule."""

    def test_sync_keeps_a_status_the_user_set(self):
        """Listening from before a pause does not undo it."""
        user = get_user_model().objects.create_user(username="plex", password="p")
        album = {"ratingKey": "10", "title": "Dune", "parentTitle": "Frank Herbert"}
        earlier = int((timezone.now() - timedelta(minutes=5)).timestamp())
        tracks = [
            {"duration": 30 * MINUTE_MS, "viewOffset": 10 * MINUTE_MS},
            {"duration": 30 * MINUTE_MS},
        ]
        book = upsert_plex_audiobook(user, album, tracks, machine_identifier="m")
        self.assertEqual(book.status, Status.IN_PROGRESS.value)
        book.status = Status.PAUSED.value
        book.save()

        tracks[0]["viewOffset"] = 20 * MINUTE_MS
        tracks[0]["lastViewedAt"] = earlier
        book = upsert_plex_audiobook(user, album, tracks, machine_identifier="m")

        self.assertEqual(book.status, Status.PAUSED.value)
        self.assertEqual(book.progress, 20)
