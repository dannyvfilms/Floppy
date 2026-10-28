"""Tests for the KOReader sync importer."""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from app.models import Book, Item, MediaTypes, Sources, Status
from app.providers import services
from integrations.imports import helpers
from integrations.imports.helpers import MediaImportError
from integrations.imports.koreader import (
    KoreaderAuthError,
    KoreaderClient,
    KoreaderClientError,
    KoreaderImporter,
)
from integrations.imports.koreader import (
    importer as koreader_importer,
)
from integrations.koreader_links import (
    get_document_hash_for_item,
    normalize_document_hash,
    save_document_link,
)
from integrations.models import ImportRun, KoreaderAccount, KoreaderDocumentLink
from integrations.tasks._media_imports import import_media

DOCUMENT_HASH = "0b229176d4e8db7f6d2b5a4952368d7a"


class KoreaderClientTests(TestCase):
    """Validate KOReader client helpers."""

    def test_password_to_auth_key(self):
        self.assertEqual(
            KoreaderClient.password_to_auth_key("test"),
            "098f6bcd4621d373cade4e832627b4f6",
        )


class KoreaderLinkHelperTests(TestCase):
    """Validate document link helpers."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="koreader-links",
            password="pass",
        )
        self.item = Item.objects.create(
            media_id="123",
            source=Sources.HARDCOVER.value,
            media_type=MediaTypes.BOOK.value,
            title="Dune",
        )

    def test_normalize_document_hash(self):
        self.assertEqual(
            normalize_document_hash(f"  {DOCUMENT_HASH.upper()}  "),
            DOCUMENT_HASH,
        )
        self.assertIsNone(normalize_document_hash("not-a-hash"))

    def test_save_and_read_document_link(self):
        save_document_link(self.user, self.item, DOCUMENT_HASH)
        self.assertEqual(
            get_document_hash_for_item(self.user, self.item),
            DOCUMENT_HASH,
        )

    def test_clearing_document_link(self):
        save_document_link(self.user, self.item, DOCUMENT_HASH)
        save_document_link(self.user, self.item, "")
        self.assertEqual(get_document_hash_for_item(self.user, self.item), "")


class KoreaderImporterTests(TestCase):
    """Validate KOReader import mapping and discovery."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="koreader-user",
            password="pass",
        )
        KoreaderAccount.objects.create(
            user=self.user,
            server_url="https://kosync.example.com",
            username="reader",
            auth_key=helpers.encrypt(
                KoreaderClient.password_to_auth_key("secret"),
            ),
            create_missing=False,
            finished_threshold=1.0,
        )
        self.item = Item.objects.create(
            media_id="42",
            source=Sources.HARDCOVER.value,
            media_type=MediaTypes.BOOK.value,
            title="Dune",
            number_of_pages=400,
        )

    @patch("integrations.imports.koreader.KoreaderClient.probe_list_support")
    @patch("integrations.imports.koreader.KoreaderClient.get_progress")
    def test_syncs_linked_document_progress(self, mock_progress, mock_probe):
        mock_probe.return_value = False
        mock_progress.return_value = {
            "document": DOCUMENT_HASH,
            "percentage": 0.5,
            "timestamp": 1_700_000_000,
        }
        KoreaderDocumentLink.objects.create(
            user=self.user,
            item=self.item,
            document_hash=DOCUMENT_HASH,
        )
        Book.objects.create(
            user=self.user,
            item=self.item,
            status=Status.PLANNING.value,
            progress=0,
        )

        counts, warnings = KoreaderImporter(self.user).import_data()

        self.assertEqual(counts.get(MediaTypes.BOOK.value), 1)
        self.assertEqual(counts["updated"], 1)
        self.assertEqual(counts["created"], 0)
        self.assertEqual(warnings, "")
        media = Book.objects.get(user=self.user, item=self.item)
        self.assertEqual(media.status, Status.IN_PROGRESS.value)
        self.assertEqual(media.progress, 200)
        self.assertEqual(media.entry_source, "koreader")

    @patch("integrations.imports.koreader.KoreaderClient.probe_list_support")
    @patch("integrations.imports.koreader.KoreaderClient.get_progress")
    def test_sync_keeps_a_status_the_user_set(self, mock_progress, mock_probe):
        """Reading from before a pause does not undo it (#1316)."""
        mock_probe.return_value = False
        KoreaderDocumentLink.objects.create(
            user=self.user,
            item=self.item,
            document_hash=DOCUMENT_HASH,
        )
        book = Book.objects.create(
            user=self.user,
            item=self.item,
            status=Status.DROPPED.value,
            progress=100,
        )
        mock_progress.return_value = {
            "document": DOCUMENT_HASH,
            "percentage": 0.5,
            "timestamp": (timezone.now() - timedelta(minutes=5)).timestamp(),
        }

        KoreaderImporter(self.user).import_data()

        book.refresh_from_db()
        self.assertEqual(book.status, Status.DROPPED.value)
        self.assertEqual(book.progress, 200)

    @patch("integrations.imports.koreader.KoreaderClient.probe_list_support")
    @patch("integrations.imports.koreader.KoreaderClient.get_progress")
    def test_resync_with_unchanged_progress_counts_as_skipped(
        self,
        mock_progress,
        mock_probe,
    ):
        mock_probe.return_value = False
        mock_progress.return_value = {
            "document": DOCUMENT_HASH,
            "percentage": 0.5,
            "timestamp": 1_700_000_000,
        }
        KoreaderDocumentLink.objects.create(
            user=self.user,
            item=self.item,
            document_hash=DOCUMENT_HASH,
        )
        Book.objects.create(
            user=self.user,
            item=self.item,
            status=Status.IN_PROGRESS.value,
            progress=200,
        )

        counts, warnings = KoreaderImporter(self.user).import_data()

        self.assertEqual(counts.get(MediaTypes.BOOK.value), 0)
        self.assertEqual(counts["created"], 0)
        self.assertEqual(counts["updated"], 0)
        self.assertEqual(counts["skipped"], 1)
        self.assertEqual(warnings, "")

    @patch("integrations.imports.koreader.KoreaderClient.probe_list_support")
    @patch("integrations.imports.koreader.KoreaderClient.get_progress")
    def test_resyncing_linked_book_counts_as_update(self, mock_progress, mock_probe):
        mock_probe.return_value = False
        mock_progress.return_value = {
            "document": DOCUMENT_HASH,
            "percentage": 0.75,
            "timestamp": 1_700_000_100,
        }
        KoreaderDocumentLink.objects.create(
            user=self.user,
            item=self.item,
            document_hash=DOCUMENT_HASH,
        )
        Book.objects.create(
            user=self.user,
            item=self.item,
            status=Status.IN_PROGRESS.value,
            progress=100,
        )

        counts, warnings = KoreaderImporter(self.user).import_data()

        self.assertEqual(counts.get(MediaTypes.BOOK.value), 1)
        self.assertEqual(counts["created"], 0)
        self.assertEqual(counts["updated"], 1)
        self.assertEqual(warnings, "")

    @patch("integrations.imports.koreader.KoreaderClient.probe_list_support")
    @patch("integrations.imports.koreader.KoreaderClient.get_progress")
    def test_import_run_records_created_and_updated_counts(self, mock_progress, mock_probe):
        mock_probe.return_value = False
        KoreaderDocumentLink.objects.create(
            user=self.user,
            item=self.item,
            document_hash=DOCUMENT_HASH,
        )
        Book.objects.create(
            user=self.user,
            item=self.item,
            status=Status.IN_PROGRESS.value,
            progress=100,
        )
        mock_progress.return_value = {
            "document": DOCUMENT_HASH,
            "percentage": 0.75,
            "timestamp": 1_700_000_100,
        }

        import_media(koreader_importer, None, self.user.id, "new")

        run = ImportRun.objects.get(user=self.user, source="koreader")
        self.assertEqual(run.status, ImportRun.Status.COMPLETED)
        self.assertEqual(run.created_count, 0)
        self.assertEqual(run.updated_count, 1)
        self.assertEqual(run.skipped_count, 0)

    @patch("integrations.imports.koreader.KoreaderClient.list_documents")
    @patch("integrations.imports.koreader.KoreaderClient.probe_list_support")
    @patch("integrations.imports.koreader.KoreaderClient.get_progress")
    def test_skips_unlinked_documents_without_metadata(
        self,
        mock_progress,
        mock_probe,
        mock_list,
    ):
        mock_probe.return_value = True
        mock_list.return_value = [
            {
                "document": DOCUMENT_HASH,
                "percentage": 0.4,
                "timestamp": 1_700_000_000,
            },
        ]

        counts, warnings = KoreaderImporter(self.user).import_data()

        self.assertEqual(counts.get(MediaTypes.BOOK.value), 0)
        self.assertEqual(counts.get("created"), 0)
        self.assertEqual(counts.get("updated"), 0)
        self.assertIn("link it on the book track modal", warnings)
        mock_progress.assert_not_called()

    @patch("integrations.imports.koreader.KoreaderClient.list_documents")
    @patch("integrations.imports.koreader.KoreaderClient.probe_list_support")
    def test_auto_match_creates_link_and_updates_existing_book(
        self,
        mock_probe,
        mock_list,
    ):
        mock_probe.return_value = True
        mock_list.return_value = [
            {
                "document": DOCUMENT_HASH,
                "percentage": 0.96,
                "title": "Dune",
                "authors": "Frank Herbert",
                "timestamp": 1_700_000_000,
            },
        ]
        Book.objects.create(
            user=self.user,
            item=self.item,
            status=Status.IN_PROGRESS.value,
            progress=10,
        )

        counts, warnings = KoreaderImporter(self.user).import_data()

        self.assertEqual(counts.get(MediaTypes.BOOK.value), 1)
        self.assertEqual(counts["created"], 0)
        self.assertEqual(counts["updated"], 1)
        self.assertEqual(warnings, "")
        self.assertTrue(
            KoreaderDocumentLink.objects.filter(
                user=self.user,
                document_hash=DOCUMENT_HASH,
                item=self.item,
            ).exists(),
        )
        media = Book.objects.get(user=self.user, item=self.item)
        self.assertEqual(media.status, Status.IN_PROGRESS.value)
        self.assertEqual(media.progress, 384)

    @patch("integrations.imports.koreader.KoreaderClient.probe_list_support")
    @patch("integrations.imports.koreader.KoreaderClient.get_progress")
    def test_near_complete_progress_stays_in_progress_below_threshold(
        self,
        mock_progress,
        mock_probe,
    ):
        mock_probe.return_value = False
        mock_progress.return_value = {
            "document": DOCUMENT_HASH,
            "percentage": 1896 / 1907,
            "timestamp": 1_700_000_000,
        }
        self.item.number_of_pages = 1907
        self.item.save(update_fields=["number_of_pages"])
        KoreaderDocumentLink.objects.create(
            user=self.user,
            item=self.item,
            document_hash=DOCUMENT_HASH,
        )
        Book.objects.create(
            user=self.user,
            item=self.item,
            status=Status.IN_PROGRESS.value,
            progress=1800,
        )

        counts, warnings = KoreaderImporter(self.user).import_data()

        self.assertEqual(counts["updated"], 1)
        self.assertEqual(warnings, "")
        media = Book.objects.get(user=self.user, item=self.item)
        self.assertEqual(media.status, Status.IN_PROGRESS.value)
        self.assertEqual(media.progress, 1896)

    @patch("integrations.imports.koreader.KoreaderClient.probe_list_support")
    @patch("integrations.imports.koreader.KoreaderClient.get_progress")
    def test_marks_completed_when_progress_meets_threshold(
        self,
        mock_progress,
        mock_probe,
    ):
        KoreaderAccount.objects.filter(user=self.user).update(finished_threshold=0.95)
        mock_probe.return_value = False
        mock_progress.return_value = {
            "document": DOCUMENT_HASH,
            "percentage": 0.96,
            "timestamp": 1_700_000_000,
        }
        KoreaderDocumentLink.objects.create(
            user=self.user,
            item=self.item,
            document_hash=DOCUMENT_HASH,
        )
        Book.objects.create(
            user=self.user,
            item=self.item,
            status=Status.IN_PROGRESS.value,
            progress=10,
        )

        counts, warnings = KoreaderImporter(self.user).import_data()

        self.assertEqual(counts["updated"], 1)
        self.assertEqual(warnings, "")
        media = Book.objects.get(user=self.user, item=self.item)
        self.assertEqual(media.status, Status.COMPLETED.value)
        self.assertEqual(media.progress, 400)

    @patch("integrations.imports.koreader.services.get_media_metadata")
    @patch("integrations.imports.koreader.services.search")
    @patch("integrations.imports.koreader.KoreaderClient.list_documents")
    @patch("integrations.imports.koreader.KoreaderClient.probe_list_support")
    def test_provider_rate_limit_falls_back_to_open_library(
        self,
        mock_probe,
        mock_list,
        mock_search,
        mock_metadata,
    ):
        account = KoreaderAccount.objects.get(user=self.user)
        account.create_missing = True
        account.save(update_fields=["create_missing"])
        Book.objects.filter(user=self.user).delete()
        self.item.delete()

        new_hash = "a" * 32
        mock_probe.return_value = True
        mock_list.return_value = [
            {
                "document": new_hash,
                "percentage": 0.5,
                "title": "The Left Hand of Darkness",
                "authors": "Ursula K. Le Guin",
                "timestamp": 1_700_000_000,
            },
        ]

        def search(_media_type, query, _page, source):
            if source == Sources.HARDCOVER.value:
                raise services.ProviderAPIError(
                    Sources.HARDCOVER.value,
                    Exception("rate limited"),
                )
            if source == Sources.OPENLIBRARY.value:
                return {
                    "results": [
                        {
                            "media_id": "OL123W",
                            "title": "The Left Hand of Darkness",
                        },
                    ],
                }
            return {"results": []}

        mock_search.side_effect = search
        mock_metadata.return_value = {
            "title": "The Left Hand of Darkness",
            "image": "https://example.com/cover.jpg",
            "details": {"authors": [{"name": "Ursula K. Le Guin"}]},
            "max_progress": 300,
        }

        importer = KoreaderImporter(self.user)
        importer.enable_provider_enrichment = True
        counts, warnings = importer.import_data()

        self.assertEqual(counts.get(MediaTypes.BOOK.value), 1)
        self.assertEqual(counts["created"], 1)
        self.assertEqual(counts["updated"], 0)
        self.assertEqual(warnings, "")
        item = Item.objects.get(
            media_id="OL123W",
            source=Sources.OPENLIBRARY.value,
        )
        self.assertTrue(
            KoreaderDocumentLink.objects.filter(
                user=self.user,
                document_hash=new_hash,
                item=item,
            ).exists(),
        )

    @patch("integrations.imports.koreader.KoreaderClient.probe_list_support")
    @patch("integrations.imports.koreader.KoreaderClient.get_progress")
    def test_marks_account_broken_on_auth_error(self, mock_progress, mock_probe):
        mock_probe.return_value = False
        mock_progress.side_effect = KoreaderAuthError("bad creds")
        KoreaderDocumentLink.objects.create(
            user=self.user,
            item=self.item,
            document_hash=DOCUMENT_HASH,
        )

        with self.assertRaises(MediaImportError):
            KoreaderImporter(self.user).import_data()

        account = KoreaderAccount.objects.get(user=self.user)
        self.assertTrue(account.connection_broken)
        self.assertIn("bad creds", account.last_error_message)

    @patch("integrations.imports.koreader.KoreaderClient.probe_list_support")
    @patch("integrations.imports.koreader.KoreaderClient.get_progress")
    def test_import_run_failed_when_linked_fetch_errors(self, mock_progress, mock_probe):
        mock_probe.return_value = False
        mock_progress.side_effect = KoreaderClientError(
            "KOReader progress response was not JSON",
        )
        KoreaderDocumentLink.objects.create(
            user=self.user,
            item=self.item,
            document_hash=DOCUMENT_HASH,
        )

        with self.assertRaises(MediaImportError):
            import_media(koreader_importer, None, self.user.id, "new")

        run = ImportRun.objects.get(user=self.user, source="koreader")
        self.assertEqual(run.status, ImportRun.Status.FAILED)

    @patch("integrations.imports.koreader.KoreaderClient.probe_list_support")
    @patch("integrations.imports.koreader.KoreaderClient.get_progress")
    def test_recalculates_progress_after_page_count_added(
        self,
        mock_progress,
        mock_probe,
    ):
        mock_probe.return_value = False
        mock_progress.return_value = {
            "document": DOCUMENT_HASH,
            "percentage": 0.45,
            "timestamp": 1_700_000_000,
        }
        self.item.number_of_pages = 400
        self.item.save(update_fields=["number_of_pages"])
        KoreaderDocumentLink.objects.create(
            user=self.user,
            item=self.item,
            document_hash=DOCUMENT_HASH,
        )
        Book.objects.create(
            user=self.user,
            item=self.item,
            status=Status.IN_PROGRESS.value,
            progress=45,
        )

        counts, warnings = KoreaderImporter(self.user).import_data()

        self.assertEqual(counts["updated"], 1)
        self.assertEqual(warnings, "")
        media = Book.objects.get(user=self.user, item=self.item)
        self.assertEqual(media.progress, 180)

    @patch("integrations.imports.koreader.KoreaderClient.probe_list_support")
    @patch("integrations.imports.koreader.KoreaderClient.get_progress")
    def test_uses_custom_metadata_page_count_when_item_pages_cleared(
        self,
        mock_progress,
        mock_probe,
    ):
        mock_probe.return_value = False
        mock_progress.return_value = {
            "document": DOCUMENT_HASH,
            "percentage": 0.93,
            "timestamp": 1_700_000_000,
        }
        self.item.number_of_pages = 0
        self.item.manual_metadata = {"details": {"number_of_pages": 1907}}
        self.item.save(update_fields=["number_of_pages", "manual_metadata"])
        KoreaderDocumentLink.objects.create(
            user=self.user,
            item=self.item,
            document_hash=DOCUMENT_HASH,
        )
        Book.objects.create(
            user=self.user,
            item=self.item,
            status=Status.IN_PROGRESS.value,
            progress=93,
        )

        counts, warnings = KoreaderImporter(self.user).import_data()

        self.assertEqual(counts["updated"], 1)
        self.assertEqual(warnings, "")
        media = Book.objects.get(user=self.user, item=self.item)
        self.assertEqual(media.progress, 1774)


    @patch("integrations.imports.koreader.KoreaderClient.probe_list_support")
    @patch("integrations.imports.koreader.KoreaderClient.get_progress")
    def test_skips_finished_linked_books_when_enabled(self, mock_progress, mock_probe):
        mock_probe.return_value = False
        KoreaderAccount.objects.filter(user=self.user).update(skip_finished_books=True)
        KoreaderDocumentLink.objects.create(
            user=self.user,
            item=self.item,
            document_hash=DOCUMENT_HASH,
        )
        Book.objects.create(
            user=self.user,
            item=self.item,
            status=Status.COMPLETED.value,
            progress=400,
        )

        counts, warnings = KoreaderImporter(self.user).import_data()

        self.assertEqual(counts.get(MediaTypes.BOOK.value), 0)
        self.assertEqual(counts.get("created"), 0)
        self.assertEqual(counts.get("updated"), 0)
        self.assertEqual(warnings, "")
        mock_progress.assert_not_called()

    @patch("integrations.views.tasks.import_koreader.delay")
    @patch("integrations.views._validate_koreader_connection")
    def test_settings_updates_account_options(self, mock_validate, mock_delay):
        user = get_user_model().objects.create_user(
            username="koreader-settings",
            password="pass",
        )
        client = Client()
        client.force_login(user)
        KoreaderAccount.objects.create(
            user=user,
            server_url="https://kosync.example.com",
            username="reader",
            auth_key=helpers.encrypt("abc"),
            verify_ssl=True,
            create_missing=False,
            skip_finished_books=True,
        )

        response = client.post(
            "/import/koreader/settings",
            {
                "server_url": "https://kosync2.example.com",
                "username": "reader2",
                "verify_ssl": "on",
                "create_missing": "on",
                "finished_threshold_percent": "100",
            },
        )
        self.assertEqual(response.status_code, 302)
        account = KoreaderAccount.objects.get(user=user)
        self.assertEqual(account.server_url, "https://kosync2.example.com")
        self.assertEqual(account.username, "reader2")
        self.assertTrue(account.create_missing)
        self.assertFalse(account.skip_finished_books)
        self.assertTrue(account.verify_ssl)
        self.assertEqual(account.finished_threshold, 1.0)


class KoreaderViewTests(TestCase):
    """Validate KOReader connect/disconnect views."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="koreader-view",
            password="pass",
        )
        self.client = Client()
        self.client.force_login(self.user)

    @patch("integrations.views.tasks.import_koreader.delay")
    @patch("integrations.views.KoreaderClient.auth")
    def test_connect_creates_account(self, mock_auth, mock_delay):
        mock_auth.return_value = True
        response = self.client.post(
            "/import/koreader/connect",
            {
                "server_url": "https://kosync.example.com",
                "username": "reader",
                "password": "secret",
                "verify_ssl": "on",
                "frequency": "once",
                "mode": "new",
                "time": "00:00",
            },
        )
        self.assertEqual(response.status_code, 302)
        account = KoreaderAccount.objects.get(user=self.user)
        self.assertEqual(account.username, "reader")
        self.assertTrue(account.verify_ssl)

    def test_disconnect_removes_account_and_links(self):
        item = Item.objects.create(
            media_id="99",
            source=Sources.HARDCOVER.value,
            media_type=MediaTypes.BOOK.value,
            title="Book",
        )
        KoreaderAccount.objects.create(
            user=self.user,
            server_url="https://kosync.example.com",
            username="reader",
            auth_key=helpers.encrypt("abc"),
        )
        KoreaderDocumentLink.objects.create(
            user=self.user,
            item=item,
            document_hash=DOCUMENT_HASH,
        )

        response = self.client.post("/import/koreader/disconnect")
        self.assertEqual(response.status_code, 302)
        self.assertFalse(KoreaderAccount.objects.filter(user=self.user).exists())
        self.assertFalse(KoreaderDocumentLink.objects.filter(user=self.user).exists())


class KoreaderTrackModalTests(TestCase):
    """Validate KOReader document ID field on book track modal save."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="koreader-track",
            password="pass",
        )
        self.client = Client()
        self.client.force_login(self.user)
        KoreaderAccount.objects.create(
            user=self.user,
            server_url="https://kosync.example.com",
            username="reader",
            auth_key=helpers.encrypt("abc"),
        )
        self.item = Item.objects.create(
            media_id="777",
            source=Sources.HARDCOVER.value,
            media_type=MediaTypes.BOOK.value,
            title="Foundation",
            number_of_pages=250,
        )
        self.book = Book.objects.create(
            user=self.user,
            item=self.item,
            status=Status.IN_PROGRESS.value,
            progress=50,
        )

    def test_media_save_persists_document_link(self):
        response = self.client.post(
            "/media_save",
            {
                "media_id": self.item.media_id,
                "source": self.item.source,
                "media_type": MediaTypes.BOOK.value,
                "instance_id": self.book.id,
                "status": Status.IN_PROGRESS.value,
                "progress": "50",
                "koreader_document_id": DOCUMENT_HASH,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            KoreaderDocumentLink.objects.filter(
                user=self.user,
                item=self.item,
                document_hash=DOCUMENT_HASH,
            ).exists(),
        )
