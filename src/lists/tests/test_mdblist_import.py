from unittest.mock import call, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import MediaTypes
from integrations.imports import helpers as import_helpers
from integrations.models import MDBListAccount
from lists.imports import mdblist
from lists.models import CustomList


def _make_account(user, **overrides):
    """Create an MDBList account with an encrypted key."""
    defaults = {"api_key": import_helpers.encrypt("test-key")}
    defaults.update(overrides)
    return MDBListAccount.objects.create(user=user, **defaults)


class MDBListImportTests(TestCase):
    """Tests for MDBList custom list import helpers."""

    def setUp(self):
        """Create a user for import tests."""
        self.user = get_user_model().objects.create_user(
            username="mdblist-import-user",
        )

    @patch("lists.imports.mdblist._request")
    def test_get_list_items_paginates_until_short_page(self, mock_request):
        """Item fetch should continue until MDBList returns a short page."""
        full_page = [{"id": i} for i in range(mdblist.PAGE_SIZE)]
        mock_request.side_effect = [full_page, [{"id": "last"}]]

        items = mdblist._get_list_items("key", "42")

        self.assertEqual(len(items), mdblist.PAGE_SIZE + 1)
        self.assertEqual(
            mock_request.call_args_list,
            [
                call(
                    "key",
                    "/lists/42/items",
                    params={
                        "limit": mdblist.PAGE_SIZE,
                        "offset": 0,
                        "unified": "true",
                    },
                ),
                call(
                    "key",
                    "/lists/42/items",
                    params={
                        "limit": mdblist.PAGE_SIZE,
                        "offset": mdblist.PAGE_SIZE,
                        "unified": "true",
                    },
                ),
            ],
        )

    def test_normalize_items_response_handles_grouped_shape(self):
        """Grouped movies/shows responses should flatten with mediatype set."""
        entries = mdblist._normalize_items_response(
            {
                "movies": [{"id": 1}],
                "shows": [{"id": 2, "mediatype": "show"}],
            },
        )

        self.assertEqual(
            entries,
            [
                {"id": 1, "mediatype": "movie"},
                {"id": 2, "mediatype": "show"},
            ],
        )

    def test_resolve_list_reference_parses_forms(self):
        """List references may be an ID, a URL, or username/slug."""
        with patch("lists.imports.mdblist._request") as mock_request:
            mock_request.return_value = [{"id": 7, "name": "A list"}]

            mdblist.resolve_list_reference("key", "12345")
            mdblist.resolve_list_reference(
                "key",
                "https://mdblist.com/lists/someuser/top-picks",
            )
            mdblist.resolve_list_reference("key", "someuser/top-picks")

        self.assertEqual(
            [args[0][1] for args in mock_request.call_args_list],
            [
                "/lists/12345",
                "/lists/someuser/top-picks",
                "/lists/someuser/top-picks",
            ],
        )

    def test_resolve_list_reference_rejects_garbage(self):
        """Unparseable references should raise a MediaImportError."""
        with self.assertRaises(import_helpers.MediaImportError):
            mdblist.resolve_list_reference("key", "not a list reference")

    @patch("lists.imports.mdblist._get_metadata")
    @patch("lists.imports.mdblist._get_list_items")
    @patch("lists.imports.mdblist._request")
    def test_import_creates_lists_and_items(
        self,
        mock_request,
        mock_get_list_items,
        mock_get_metadata,
    ):
        """Own lists should be imported with movie and show items."""
        _make_account(self.user)
        mock_request.return_value = [
            {"id": 11, "name": "Favorites", "description": "Best stuff"},
        ]
        mock_get_list_items.return_value = [
            {
                "title": "A Movie",
                "mediatype": "movie",
                "ids": {"tmdb": 100},
            },
            {
                "title": "A Show",
                "mediatype": "show",
                "ids": {"tmdb": 200},
            },
        ]
        mock_get_metadata.side_effect = lambda _media_type, _tmdb_id, title: {
            "title": title,
            "image": "http://example.com/img.jpg",
        }

        mdblist.import_mdblist_lists(self.user)

        imported_list = CustomList.objects.get(
            owner=self.user,
            source="mdblist",
            source_id="11",
        )
        self.assertEqual(imported_list.name, "Favorites")
        media_types = set(imported_list.items.values_list("media_type", flat=True))
        self.assertEqual(
            media_types,
            {MediaTypes.MOVIE.value, MediaTypes.TV.value},
        )
        account = MDBListAccount.objects.get(user=self.user)
        self.assertIsNotNone(account.last_sync_at)
        self.assertFalse(account.connection_broken)

    @patch("lists.imports.mdblist._get_metadata")
    @patch("lists.imports.mdblist._get_list_items")
    @patch("lists.imports.mdblist._request")
    def test_resync_upserts_and_reconciles_items(
        self,
        mock_request,
        mock_get_list_items,
        mock_get_metadata,
    ):
        """A second sync must keep the list row and reconcile membership."""
        _make_account(self.user)
        mock_request.return_value = [{"id": 11, "name": "Favorites"}]
        mock_get_metadata.side_effect = lambda _media_type, _tmdb_id, title: {
            "title": title,
            "image": "http://example.com/img.jpg",
        }

        mock_get_list_items.return_value = [
            {"title": "Old Movie", "mediatype": "movie", "ids": {"tmdb": 100}},
            {"title": "Kept Movie", "mediatype": "movie", "ids": {"tmdb": 101}},
        ]
        mdblist.import_mdblist_lists(self.user)
        original = CustomList.objects.get(owner=self.user, source_id="11")

        mock_get_list_items.return_value = [
            {"title": "Kept Movie", "mediatype": "movie", "ids": {"tmdb": 101}},
            {"title": "New Movie", "mediatype": "movie", "ids": {"tmdb": 102}},
        ]
        mdblist.import_mdblist_lists(self.user)

        resynced = CustomList.objects.get(owner=self.user, source_id="11")
        self.assertEqual(resynced.pk, original.pk)
        media_ids = set(resynced.items.values_list("media_id", flat=True))
        self.assertEqual(media_ids, {"101", "102"})

    @patch("integrations.imports.mdblist.tmdb.find")
    @patch("lists.imports.mdblist._get_metadata")
    @patch("lists.imports.mdblist._get_list_items")
    @patch("lists.imports.mdblist._request")
    def test_imdb_only_entry_resolves_via_tmdb_find(
        self,
        mock_request,
        mock_get_list_items,
        mock_get_metadata,
        mock_find,
    ):
        """Entries without a TMDB id should resolve through /find."""
        _make_account(self.user)
        mock_request.return_value = [{"id": 11, "name": "Favorites"}]
        mock_get_list_items.return_value = [
            {"title": "IMDB Movie", "mediatype": "movie", "ids": {"imdb": "tt123"}},
            {"title": "Unresolvable", "mediatype": "movie", "ids": {}},
        ]
        mock_find.return_value = {"movie_results": [{"id": 300}]}
        mock_get_metadata.return_value = {
            "title": "IMDB Movie",
            "image": "http://example.com/img.jpg",
        }

        mdblist.import_mdblist_lists(self.user)

        imported_list = CustomList.objects.get(owner=self.user, source_id="11")
        item = imported_list.items.get()
        self.assertEqual(item.media_id, "300")
        mock_find.assert_called_once_with("tt123", "imdb_id")

    @patch("lists.imports.mdblist._sync_list", return_value=0)
    @patch("lists.imports.mdblist.get_list_info")
    @patch("lists.imports.mdblist._request")
    def test_vanished_upstream_list_is_kept_locally(
        self,
        mock_request,
        mock_get_list_info,
        mock_sync_list,
    ):
        """A URL-imported list gone upstream should be kept, not deleted."""
        _make_account(self.user)
        CustomList.objects.create(
            owner=self.user,
            name="Gone list",
            source="mdblist",
            source_id="99",
        )
        mock_request.return_value = []
        mock_get_list_info.return_value = None

        mdblist.import_mdblist_lists(self.user)

        self.assertTrue(
            CustomList.objects.filter(owner=self.user, source_id="99").exists(),
        )
        mock_sync_list.assert_not_called()

    @patch("lists.imports.mdblist._request")
    def test_auth_failure_marks_connection_broken(self, mock_request):
        """An invalid key should flag the account and raise."""
        _make_account(self.user)
        mock_request.side_effect = import_helpers.MediaImportError(
            "MDBList API key is invalid or revoked.",
        )

        with self.assertRaises(import_helpers.MediaImportError):
            mdblist.import_mdblist_lists(self.user)

        account = MDBListAccount.objects.get(user=self.user)
        self.assertTrue(account.connection_broken)
        self.assertIn("invalid", account.last_error_message)


class MDBListViewTests(TestCase):
    """Tests for the MDBList connect/disconnect/import views."""

    def setUp(self):
        """Create and log in a user."""
        self.credentials = {"username": "mdblist-view-user", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    @patch("lists.views_mdblist.list_tasks.import_mdblist_lists_task")
    @patch("lists.views_mdblist.mdblist_imports.validate_api_key")
    def test_connect_stores_key_and_schedules_sync(self, mock_validate, mock_task):
        """Connecting should store an encrypted key and create a schedule."""
        from django_celery_beat.models import PeriodicTask

        mock_validate.return_value = {"username": "mdblist-user"}

        response = self.client.post(
            reverse("mdblist_connect"),
            {"api_key": "secret-key", "sync_frequency": "12h"},
        )

        self.assertRedirects(response, reverse("lists"))
        account = MDBListAccount.objects.get(user=self.user)
        self.assertNotEqual(account.api_key, "secret-key")
        self.assertEqual(import_helpers.decrypt(account.api_key), "secret-key")
        self.assertEqual(account.sync_frequency, "12h")
        task = PeriodicTask.objects.get(task="Import MDBList Lists")
        self.assertEqual(task.crontab.hour, "*/12")
        mock_task.delay.assert_called_once_with(self.user.id)

    @patch("lists.views_mdblist.mdblist_imports.validate_api_key")
    def test_connect_rejects_invalid_key(self, mock_validate):
        """An invalid key should not create an account."""
        mock_validate.side_effect = import_helpers.MediaImportError("bad key")

        response = self.client.post(
            reverse("mdblist_connect"),
            {"api_key": "bad-key"},
        )

        self.assertRedirects(response, reverse("lists"))
        self.assertFalse(MDBListAccount.objects.filter(user=self.user).exists())

    @patch("lists.views_mdblist.list_tasks.import_mdblist_lists_task")
    @patch("lists.views_mdblist.mdblist_imports.validate_api_key")
    def test_disconnect_removes_account_and_schedule_keeps_lists(
        self,
        mock_validate,
        mock_task,
    ):
        """Disconnecting should drop the account and schedule but keep lists."""
        from django_celery_beat.models import PeriodicTask

        del mock_task
        mock_validate.return_value = {}
        self.client.post(reverse("mdblist_connect"), {"api_key": "secret-key"})
        CustomList.objects.create(
            owner=self.user,
            name="Imported",
            source="mdblist",
            source_id="5",
        )

        response = self.client.post(reverse("mdblist_disconnect"))

        self.assertRedirects(response, reverse("lists"))
        self.assertFalse(MDBListAccount.objects.filter(user=self.user).exists())
        self.assertFalse(
            PeriodicTask.objects.filter(task="Import MDBList Lists").exists(),
        )
        self.assertTrue(
            CustomList.objects.filter(owner=self.user, source="mdblist").exists(),
        )

    @patch("lists.views_mdblist.list_tasks.import_mdblist_list_by_reference_task")
    def test_import_url_queues_task(self, mock_task):
        """Importing by URL should queue the single-list task."""
        MDBListAccount.objects.create(
            user=self.user,
            api_key=import_helpers.encrypt("secret-key"),
        )

        response = self.client.post(
            reverse("mdblist_import_url"),
            {"list_reference": "https://mdblist.com/lists/user/some-list"},
        )

        self.assertRedirects(response, reverse("lists"))
        mock_task.delay.assert_called_once_with(
            self.user.id,
            "https://mdblist.com/lists/user/some-list",
        )

    def test_import_url_requires_account(self):
        """Importing by URL without an account should not queue anything."""
        with patch(
            "lists.views_mdblist.list_tasks.import_mdblist_list_by_reference_task",
        ) as mock_task:
            self.client.post(
                reverse("mdblist_import_url"),
                {"list_reference": "12345"},
            )
        mock_task.delay.assert_not_called()
