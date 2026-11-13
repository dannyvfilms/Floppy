import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django_celery_beat.models import PeriodicTask

from app.models import Book, Item, MediaTypes, Sources, Status
from app.providers import credentials, services
from app.providers import hardcover as hardcover_provider
from integrations.imports import hardcover
from integrations.imports.helpers import MediaImportError

PROVIDER = "app.providers.hardcover"


def _entry(book_id, status_id, **overrides):
    return {
        "id": book_id * 10,
        "book_id": book_id,
        "status_id": status_id,
        "rating": None,
        "review_raw": None,
        "private_notes": None,
        "date_added": "2026-01-01",
        "first_started_reading_date": None,
        "last_read_date": None,
        "updated_at": "2026-09-01T12:00:00+00:00",
        "book": {"pages": 300},
        "user_book_reads": [],
        **overrides,
    }


def _page(entries):
    return {"data": {"me": [{"user_books": entries}]}}


class HardcoverAccountSyncTests(TestCase):
    """Test syncing the Hardcover library through the official API."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="hc",
            password="12345",
        )
        credentials.set_user("hardcover", self.user, {"api_key": "token"})

    def _item(self, book_id, title="Book"):
        return Item.objects.create(
            media_id=str(book_id),
            source=Sources.HARDCOVER.value,
            media_type=MediaTypes.BOOK.value,
            title=title,
            image="http://example.com/c.jpg",
        )

    def _sync(self, entries, mode="overwrite"):
        with patch(f"{PROVIDER}.fetch_user_books", return_value=entries):
            return hardcover.sync_importer(None, self.user, mode)

    def test_creates_entry_with_status_rating_dates_and_progress(self):
        self._item(1)
        entry = _entry(
            1,
            3,
            rating=4.5,
            review_raw="Loved it",
            first_started_reading_date="2026-08-01",
            last_read_date="2026-08-20",
        )

        counts, warnings = self._sync([entry])

        book = Book.objects.get(user=self.user, item__media_id="1")
        self.assertEqual(book.status, Status.COMPLETED.value)
        self.assertEqual(book.score, 9)
        self.assertEqual(book.progress, 300)
        self.assertEqual(book.start_date.date().isoformat(), "2026-08-01")
        self.assertEqual(book.end_date.date().isoformat(), "2026-08-20")
        self.assertEqual(book.notes, "Loved it")
        self.assertEqual(book.entry_source, "hardcover")
        self.assertEqual(counts["created"], 1)
        self.assertEqual(warnings, "")

    def test_maps_every_status_and_skips_ignored(self):
        for book_id in range(1, 7):
            self._item(book_id)

        self._sync([_entry(book_id, book_id) for book_id in range(1, 7)])

        statuses = {
            book.item.media_id: book.status
            for book in Book.objects.filter(user=self.user).select_related("item")
        }
        self.assertEqual(
            statuses,
            {
                "1": Status.PLANNING.value,
                "2": Status.IN_PROGRESS.value,
                "3": Status.COMPLETED.value,
                "4": Status.PAUSED.value,
                "5": Status.DROPPED.value,
            },
        )

    def test_in_progress_uses_latest_read_progress(self):
        self._item(1)
        entry = _entry(
            1,
            2,
            user_book_reads=[
                {"started_at": "2026-08-01", "finished_at": None, "progress_pages": 40},
                {"started_at": "2026-09-01", "finished_at": None, "progress_pages": 120},
            ],
        )

        self._sync([entry])

        book = Book.objects.get(user=self.user, item__media_id="1")
        self.assertEqual(book.progress, 120)
        self.assertEqual(book.start_date.date().isoformat(), "2026-08-01")
        self.assertIsNone(book.end_date)

    def test_updates_existing_entry_and_keeps_floppy_notes(self):
        item = self._item(1)
        Book.objects.create(
            user=self.user,
            item=item,
            status=Status.PLANNING.value,
            notes="my note",
        )

        counts, _ = self._sync([_entry(1, 2, rating=3, review_raw="other")])

        book = Book.objects.get(user=self.user, item=item)
        self.assertEqual(book.status, Status.IN_PROGRESS.value)
        self.assertEqual(book.score, 6)
        self.assertEqual(book.notes, "my note")
        self.assertEqual(counts["updated"], 1)

    def test_new_mode_adds_missing_books_but_leaves_tracked_ones_alone(self):
        tracked = self._item(1)
        self._item(2)
        Book.objects.create(user=self.user, item=tracked, status=Status.PLANNING.value)

        counts, _ = self._sync([_entry(1, 3, rating=5), _entry(2, 2)], mode="new")

        self.assertEqual(
            Book.objects.get(user=self.user, item=tracked).status,
            Status.PLANNING.value,
        )
        self.assertEqual(
            Book.objects.get(user=self.user, item__media_id="2").status,
            Status.IN_PROGRESS.value,
        )
        self.assertEqual(counts["created"], 1)
        self.assertEqual(counts["unchanged"], 1)

    def test_missing_rating_keeps_existing_score(self):
        item = self._item(1)
        Book.objects.create(
            user=self.user,
            item=item,
            status=Status.PLANNING.value,
            score=7,
        )

        self._sync([_entry(1, 2)])

        self.assertEqual(Book.objects.get(user=self.user, item=item).score, 7)

    def test_second_run_changes_nothing(self):
        self._item(1)
        entry = _entry(1, 3, rating=5, last_read_date="2026-08-20")
        self._sync([entry])

        counts, _ = self._sync([entry])

        self.assertEqual(counts, {"unchanged": 1})

    def test_paused_in_floppy_survives_older_hardcover_activity(self):
        item = self._item(1)
        Book.objects.create(user=self.user, item=item, status=Status.PAUSED.value)

        self._sync([_entry(1, 2, updated_at="2000-01-01T00:00:00+00:00")])

        self.assertEqual(
            Book.objects.get(user=self.user, item=item).status,
            Status.PAUSED.value,
        )

    def test_new_book_metadata_comes_from_hardcover(self):
        metadata = {
            "media_id": "42",
            "title": "Fetched",
            "image": "http://example.com/f.jpg",
        }
        with patch(
            "integrations.imports.hardcover.services.get_media_metadata",
            return_value=metadata,
        ):
            self._sync([_entry(42, 1)])

        self.assertEqual(
            Item.objects.get(media_id="42", source=Sources.HARDCOVER.value).title,
            "Fetched",
        )

    def test_unloadable_book_becomes_warning(self):
        with patch(
            "integrations.imports.hardcover.services.get_media_metadata",
            side_effect=services.ProviderAPIError(
                Sources.HARDCOVER.value,
                Exception("boom"),
            ),
        ):
            counts, warnings = self._sync([_entry(42, 1)])

        self.assertEqual(counts["skipped"], 1)
        self.assertIn("42", warnings)
        self.assertFalse(Book.objects.filter(user=self.user).exists())

    def test_provider_failure_raises_import_error(self):
        with (
            patch(
                f"{PROVIDER}.fetch_user_books",
                side_effect=services.ProviderAPIError(
                    Sources.HARDCOVER.value,
                    Exception("boom"),
                    "bad token",
                ),
            ),
            self.assertRaises(MediaImportError),
        ):
            hardcover.sync_importer(None, self.user, "new")


class HardcoverFetchUserBooksTests(TestCase):
    """Test paging through the Hardcover ``me`` query."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="hc",
            password="12345",
        )

    def test_requires_a_personal_token(self):
        with patch(f"{PROVIDER}.services.api_request") as request:
            with self.assertRaises(services.ProviderAPIError):
                hardcover_provider.fetch_user_books(self.user)
        request.assert_not_called()

    def test_instance_token_is_not_used(self):
        with (
            patch.object(credentials, "get", return_value="instance-token"),
            patch(f"{PROVIDER}.services.api_request") as request,
            self.assertRaises(services.ProviderAPIError),
        ):
            hardcover_provider.fetch_user_books(self.user)
        request.assert_not_called()

    def test_pages_until_a_short_page(self):
        credentials.set_user("hardcover", self.user, {"api_key": "token"})
        full = [_entry(i, 1) for i in range(hardcover_provider.USER_BOOKS_PAGE_SIZE)]
        short = [_entry(1000, 1)]
        with (
            patch(f"{PROVIDER}.USER_BOOKS_PAGE_DELAY_SECONDS", 0),
            patch(
                f"{PROVIDER}.services.api_request",
                side_effect=[_page(full), _page(short)],
            ) as request,
        ):
            entries = hardcover_provider.fetch_user_books(self.user)

        self.assertEqual(len(entries), len(full) + 1)
        offsets = [
            call.kwargs["params"]["variables"]["offset"]
            for call in request.call_args_list
        ]
        self.assertEqual(offsets, [0, hardcover_provider.USER_BOOKS_PAGE_SIZE])
        self.assertEqual(
            request.call_args.kwargs["headers"]["Authorization"],
            "Bearer token",
        )

    def test_graphql_errors_raise(self):
        credentials.set_user("hardcover", self.user, {"api_key": "token"})
        with (
            patch(
                f"{PROVIDER}.services.api_request",
                return_value={"errors": [{"message": "bad"}]},
            ),
            self.assertRaises(services.ProviderAPIError),
        ):
            hardcover_provider.fetch_user_books(self.user)


class HardcoverSyncViewTests(TestCase):
    """Test the Sync now button follows the shared import frequency."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="hc",
            password="12345",
        )
        self.client.login(username="hc", password="12345")
        self.task = "Import from Hardcover Account"
        self.form = {"mode": "overwrite", "frequency": "once", "time": "06:30"}

    def test_needs_a_personal_key(self):
        with patch("integrations.tasks.import_hardcover_account.delay") as delay:
            self.client.post(reverse("hardcover_sync"), self.form)
        delay.assert_not_called()

    def test_once_queues_a_sync_with_the_chosen_mode(self):
        credentials.set_user("hardcover", self.user, {"api_key": "token"})
        with patch("integrations.tasks.import_hardcover_account.delay") as delay:
            self.client.post(reverse("hardcover_sync"), self.form)
        delay.assert_called_once_with(user_id=self.user.id, mode="overwrite")
        self.assertFalse(PeriodicTask.objects.filter(task=self.task).exists())

    def test_daily_schedules_instead_of_queueing(self):
        credentials.set_user("hardcover", self.user, {"api_key": "token"})
        with patch("integrations.tasks.import_hardcover_account.delay") as delay:
            self.client.post(
                reverse("hardcover_sync"),
                {**self.form, "frequency": "daily"},
            )
        delay.assert_not_called()
        task = PeriodicTask.objects.get(task=self.task)
        self.assertEqual(
            json.loads(task.kwargs),
            {
                "username": "hc",
                "user_id": self.user.id,
                "mode": "overwrite",
            },
        )

    def test_modal_has_its_own_frequency_and_time(self):
        credentials.set_user("hardcover", self.user, {"api_key": "token"})
        response = self.client.get(reverse("provider_detail", args=["hardcover"]) + "?tab=import")
        self.assertContains(response, 'x-model="scheduleFrequency"')
        self.assertContains(response, 'x-model="scheduleTime"')
