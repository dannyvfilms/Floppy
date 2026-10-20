"""Tests for the Komga reading progress sync."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import requests
from django.contrib.auth import get_user_model
from django.db import OperationalError
from django.db.models.query import QuerySet
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django_celery_beat.models import IntervalSchedule, PeriodicTask

from app.models import Book, ComicIssue, Item, MediaTypes, Sources, Status
from integrations.imports import helpers, komga
from integrations.models import KomgaAccount, KomgaBookLink

# Shapes follow Komga's BookDto: readProgress is the calling user's progress,
# media.pagesCount the page total and metadata.links the ComicInfo Web urls.
CBZ = "application/vnd.comicbook+zip"


def _book(book_id, *, read_date, page=0, completed=False, **overrides):
    book = {
        "id": book_id,
        "seriesTitle": "Saga",
        "name": f"Saga {book_id}",
        "number": 1,
        "media": {"mediaType": CBZ, "pagesCount": 30},
        "metadata": {
            "title": "Chapter One",
            "number": "1",
            "links": [],
            "authors": [],
            "isbn": "",
        },
        "readProgress": {
            "page": page,
            "completed": completed,
            "created": "2026-09-01T10:00:00Z",
            "readDate": read_date,
        },
    }
    book.update(overrides)
    return book


def _response(payload, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    return response


def _page(books, *, last=True):
    return _response({"content": books, "last": last})


class KomgaImporterTests(TestCase):
    """Cover what the sync writes and how it treats failures."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="komga-user")
        self.account = KomgaAccount.objects.create(
            user=self.user,
            base_url="https://komga.local:25600/",
            api_key=helpers.encrypt("komga-key"),
        )

    def _sync(self, *pages):
        with patch(
            "integrations.imports.reading_server.requests.get",
            side_effect=list(pages),
        ) as mock_get:
            result = komga.importer(None, self.user, "new")
        self.mock_get = mock_get
        return result

    def test_comic_with_comicvine_link_tracks_the_issue(self):
        """A Comic Vine link on the book gives the issue its provider identity."""
        book = _book("b1", read_date="2026-09-20T12:00:00Z", page=12)
        book["metadata"]["links"] = [
            {
                "label": "Comic Vine",
                "url": "https://comicvine.gamespot.com/saga-1/4000-301/",
            },
        ]

        counts, warnings = self._sync(_page([book]))

        item = Item.objects.get(media_id="301")
        self.assertEqual(item.source, Sources.COMICVINE.value)
        self.assertEqual(item.media_type, MediaTypes.COMIC_ISSUE.value)
        entry = ComicIssue.objects.get(user=self.user, item=item)
        self.assertEqual(entry.progress, 12)
        self.assertEqual(entry.status, Status.IN_PROGRESS.value)
        self.assertEqual(entry.entry_source, "komga")
        self.assertEqual(
            entry.start_date,
            datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
        )
        self.assertEqual(counts["created"], 1)
        self.assertEqual(counts[MediaTypes.COMIC_ISSUE.value], 1)
        self.assertEqual(warnings, "")
        self.assertEqual(
            self.mock_get.call_args.kwargs["headers"],
            {"X-API-Key": "komga-key"},
        )

    def test_completed_comic_is_marked_completed_on_the_read_date(self):
        book = _book("b1", read_date="2026-09-20T12:00:00Z", page=30, completed=True)
        book["metadata"]["links"] = [
            {"url": "https://comicvine.gamespot.com/saga-1/4000-301/"},
        ]

        self._sync(_page([book]))

        entry = ComicIssue.objects.get(user=self.user)
        self.assertEqual(entry.status, Status.COMPLETED.value)
        self.assertEqual(entry.progress, 30)
        self.assertEqual(entry.end_date, datetime(2026, 9, 20, 12, 0, tzinfo=UTC))

    def test_comic_without_link_becomes_a_manual_item(self):
        self._sync(_page([_book("b1", read_date="2026-09-20T12:00:00Z", page=3)]))

        item = ComicIssue.objects.get(user=self.user).item
        self.assertEqual(item.source, Sources.MANUAL.value)
        self.assertEqual(item.title, "Saga #1")
        self.assertTrue(KomgaBookLink.objects.filter(user=self.user, item=item).exists())

    def test_write_retries_when_sqlite_reports_a_lock(self):
        """A lock that fails the first write at once must not abort the sync."""
        real = QuerySet.update_or_create
        failures = []

        def locked_once(queryset, *args, **kwargs):
            if queryset.model is ComicIssue and not failures:
                failures.append(1)
                raise OperationalError("database is locked")
            return real(queryset, *args, **kwargs)

        with (
            patch.object(QuerySet, "update_or_create", locked_once),
            patch("app.db_retry.time.sleep"),
        ):
            counts, _warnings = self._sync(
                _page([_book("b1", read_date="2026-09-20T12:00:00Z", page=3)]),
            )

        self.assertEqual(failures, [1])
        self.assertEqual(ComicIssue.objects.filter(user=self.user).count(), 1)
        self.assertEqual(counts["created"], 1)

    def test_unlinked_comic_is_skipped_when_create_missing_is_off(self):
        self.account.create_missing = False
        self.account.save()

        counts, warnings = self._sync(
            _page([_book("b1", read_date="2026-09-20T12:00:00Z", page=3)]),
        )

        self.assertFalse(ComicIssue.objects.exists())
        self.assertEqual(counts["skipped"], 1)
        self.assertIn("Could not match Komga item", warnings)

    def test_unread_book_is_ignored(self):
        counts, _warnings = self._sync(
            _page([_book("b1", read_date="2026-09-20T12:00:00Z", page=0)]),
        )

        self.assertFalse(ComicIssue.objects.exists())
        self.assertEqual(sum(counts.values()), 0)

    def test_epub_matches_a_library_book_by_isbn(self):
        item = Item.objects.create(
            media_id="hc-1",
            source=Sources.HARDCOVER.value,
            media_type=MediaTypes.BOOK.value,
            title="Dune",
            isbn=["9780441172719"],
        )
        Book.objects.create(user=self.user, item=item, status=Status.PLANNING.value)
        epub = _book(
            "b9",
            read_date="2026-09-20T12:00:00Z",
            page=120,
            media={"mediaType": komga.EPUB_MEDIA_TYPE, "pagesCount": 600},
            metadata={"title": "Dune (Deluxe)", "isbn": "978-0-441-17271-9"},
        )

        counts, _warnings = self._sync(_page([epub]))

        entry = Book.objects.get(user=self.user, item=item)
        self.assertEqual(entry.progress, 120)
        self.assertEqual(entry.status, Status.IN_PROGRESS.value)
        self.assertEqual(counts[MediaTypes.BOOK.value], 1)
        self.assertEqual(Item.objects.filter(media_type=MediaTypes.BOOK.value).count(), 1)

    def test_status_the_user_chose_is_kept(self):
        """An old read must not pull a Paused book back to In progress."""
        book = _book("b1", read_date="2020-01-01T00:00:00Z", page=5)
        item = Item.objects.create(
            media_id=Item.generate_manual_id(),
            source=Sources.MANUAL.value,
            media_type=MediaTypes.COMIC_ISSUE.value,
            library_media_type=MediaTypes.COMIC_ISSUE.value,
            title="Saga #1",
        )
        KomgaBookLink.objects.create(user=self.user, komga_book_id="b1", item=item)
        ComicIssue.objects.create(user=self.user, item=item, status=Status.PAUSED.value)

        self._sync(_page([book]))

        self.assertEqual(
            ComicIssue.objects.get(user=self.user).status,
            Status.PAUSED.value,
        )

    def test_second_sync_only_reads_newer_progress_and_keeps_edited_source(self):
        book = _book("b1", read_date="2026-09-20T12:00:00Z", page=3)
        self._sync(_page([book]))
        ComicIssue.objects.filter(user=self.user).update(entry_source="Theatre")
        self.account.refresh_from_db()
        first_sync = self.account.last_sync_at
        self.assertIsNotNone(first_sync)

        older = _book("b2", read_date=(first_sync - timedelta(hours=1)).isoformat(), page=9)
        newer_read = _book("b1", read_date=timezone.now().isoformat(), page=8)
        self._sync(_page([newer_read, older]))

        entries = ComicIssue.objects.filter(user=self.user)
        self.assertEqual(entries.count(), 1)
        entry = entries.get()
        self.assertEqual(entry.progress, 8)
        self.assertEqual(entry.entry_source, "Theatre")

    def test_unchanged_progress_is_skipped(self):
        book = _book("b1", read_date="2026-09-20T12:00:00Z", page=3)
        self._sync(_page([book]))
        self.account.last_sync_at = None
        self.account.save()

        counts, _warnings = self._sync(_page([book]))

        self.assertEqual(counts["skipped"], 1)
        self.assertNotIn("updated", counts)

    def test_reads_every_page_of_results(self):
        first = _book("b1", read_date="2026-09-20T12:00:00Z", page=3)
        second = _book("b2", read_date="2026-09-19T12:00:00Z", page=4, number=2)
        second["metadata"]["number"] = "2"

        self._sync(_page([first], last=False), _page([second]))

        self.assertEqual(ComicIssue.objects.filter(user=self.user).count(), 2)
        self.assertEqual(self.mock_get.call_args.kwargs["params"]["page"], 1)

    def test_rejected_key_marks_connection_broken(self):
        with (
            patch(
                "integrations.imports.reading_server.requests.get",
                return_value=_response({}, 401),
            ),
            self.assertRaises(helpers.ConnectionAuthError),
        ):
            komga.importer(None, self.user, "new")

        self.account.refresh_from_db()
        self.assertTrue(self.account.connection_broken)

    def test_server_error_does_not_mark_connection_broken(self):
        with (
            patch(
                "integrations.imports.reading_server.requests.get",
                return_value=_response({}, 500),
            ),
            self.assertRaises(helpers.MediaImportError),
        ):
            komga.importer(None, self.user, "new")

        self.account.refresh_from_db()
        self.assertFalse(self.account.connection_broken)
        self.assertIn("500", self.account.last_error_message)

    def test_timeout_is_recorded_without_leaking_the_key(self):
        with (
            patch(
                "integrations.imports.reading_server.requests.get",
                side_effect=requests.Timeout("timeout for komga-key"),
            ),
            self.assertRaises(helpers.MediaImportError),
        ):
            komga.importer(None, self.user, "new")

        self.account.refresh_from_db()
        self.assertFalse(self.account.connection_broken)
        self.assertNotIn("komga-key", self.account.last_error_message)


class KomgaViewTests(TestCase):
    """Cover connecting, syncing and disconnecting from the Import page."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="komga-viewer")
        self.client.force_login(self.user)

    @patch("integrations.views.tasks.import_komga.delay")
    @patch("integrations.views.KomgaClient.healthcheck")
    def test_connect_creates_schedule_at_chosen_interval_and_queues_import(
        self,
        mock_healthcheck,
        mock_delay,
    ):
        response = self.client.post(
            reverse("komga_connect"),
            {
                "base_url": "https://komga.local:25600",
                "api_key": "komga-key",
                "sync_interval_minutes": "30",
            },
        )

        self.assertEqual(response.status_code, 302)
        account = KomgaAccount.objects.get(user=self.user)
        self.assertEqual(helpers.decrypt(account.api_key), "komga-key")
        self.assertEqual(account.sync_interval_minutes, 30)
        task = PeriodicTask.objects.get(task="Import from Komga (Recurring)")
        self.assertEqual(task.interval.every, 30)
        self.assertIn(f'"user_id": {self.user.id}', task.kwargs)
        mock_healthcheck.assert_called_once()
        mock_delay.assert_called_once_with(user_id=self.user.id, mode="new")

    @patch("integrations.views.tasks.import_komga.delay")
    @patch("integrations.imports.reading_server.requests.get")
    def test_connect_with_bad_key_saves_nothing(self, mock_get, mock_delay):
        mock_get.return_value = _response({}, 401)

        self.client.post(
            reverse("komga_connect"),
            {"base_url": "https://komga.local:25600", "api_key": "wrong"},
        )

        self.assertFalse(KomgaAccount.objects.exists())
        self.assertFalse(
            PeriodicTask.objects.filter(task="Import from Komga (Recurring)").exists(),
        )
        mock_delay.assert_not_called()

    @patch("integrations.views.tasks.import_komga.delay")
    @patch("integrations.views.KomgaClient.healthcheck")
    def test_disconnect_removes_account_and_schedule(self, _healthcheck, _delay):
        self.client.post(
            reverse("komga_connect"),
            {"base_url": "https://komga.local:25600", "api_key": "komga-key"},
        )

        self.client.post(reverse("komga_disconnect"))

        self.assertFalse(KomgaAccount.objects.exists())
        self.assertFalse(
            PeriodicTask.objects.filter(task="Import from Komga (Recurring)").exists(),
        )

    def test_import_page_shows_komga(self):
        response = self.client.get(reverse("import_data"))

        self.assertContains(response, "Sync book and comic reading progress from Komga.")
        self.assertContains(response, reverse("komga_connect"))


class PeriodicTaskUserMatchTests(TestCase):
    """A user's schedule must never be matched by another user's id prefix."""

    def test_connect_and_disconnect_leave_users_sharing_an_id_prefix_alone(self):
        users = [
            get_user_model().objects.create_user(username=f"prefix-{n}", id=n)
            for n in (1, 10)
        ]
        for user in users:
            komga_task = "Import from Komga (Recurring)"
            PeriodicTask.objects.create(
                name=f"komga {user.id}",
                task=komga_task,
                interval=IntervalSchedule.objects.get_or_create(
                    every=15,
                    period=IntervalSchedule.MINUTES,
                )[0],
                kwargs=f'{{"user_id": {user.id}}}',
            )

        # User 10 connecting must not repurpose user 1's schedule, and user 1
        # disconnecting must not delete user 10's.
        self.client.force_login(users[0])
        self.client.post(reverse("komga_disconnect"))

        remaining = PeriodicTask.objects.filter(task="Import from Komga (Recurring)")
        self.assertEqual([task.kwargs for task in remaining], ['{"user_id": 10}'])
