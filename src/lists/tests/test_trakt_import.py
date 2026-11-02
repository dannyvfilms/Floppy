import base64
import hashlib
from unittest.mock import call, patch
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from app.models import MediaTypes
from integrations.imports import helpers as import_helpers
from integrations.models import TraktAccount
from lists.imports import trakt
from lists.models import CustomList
from lists.views_trakt import TRAKT_LISTS_DEVICE_SESSION_KEY


class TraktListImportTests(TestCase):
    """Tests for Trakt custom list import helpers."""

    def setUp(self):
        """Create a user for import tests."""
        self.user = get_user_model().objects.create_user(
            username="trakt-import-user",
        )

    @patch("lists.imports.trakt._make_trakt_request")
    def test_get_trakt_list_items_paginates_until_empty_page(self, mock_make_request):
        """List item fetch should continue until Trakt returns an empty page."""
        mock_make_request.side_effect = [
            [{"id": 1}, {"id": 2}],
            [{"id": 3}],
            [],
        ]

        items = trakt._get_trakt_list_items("token-123", "42", client_id="client-id")

        self.assertEqual(len(items), 3)
        self.assertEqual(
            mock_make_request.call_args_list,
            [
                call(
                    "token-123",
                    "https://api.trakt.tv/users/me/lists/42/items?page=1&limit=1000",
                    client_id="client-id",
                ),
                call(
                    "token-123",
                    "https://api.trakt.tv/users/me/lists/42/items?page=2&limit=1000",
                    client_id="client-id",
                ),
                call(
                    "token-123",
                    "https://api.trakt.tv/users/me/lists/42/items?page=3&limit=1000",
                    client_id="client-id",
                ),
            ],
        )

    @patch("app.tasks.enqueue_episode_runtime_backfill")
    @patch("lists.imports.trakt._get_metadata")
    @patch("lists.imports.trakt._get_trakt_watchlist_items")
    @patch("lists.imports.trakt._get_trakt_list_items")
    @patch("lists.imports.trakt._get_trakt_lists")
    def test_import_trakt_lists_imports_episode_entries(
        self,
        mock_get_lists,
        mock_get_list_items,
        mock_get_watchlist_items,
        mock_get_metadata,
        mock_enqueue_episode_runtime_backfill,
    ):
        """Episode entries from Trakt lists should be imported as episode items."""
        del mock_enqueue_episode_runtime_backfill
        mock_get_lists.return_value = [
            {
                "ids": {"trakt": 123},
                "name": "Episode Picks",
                "privacy": "private",
            },
        ]
        mock_get_list_items.return_value = [
            {
                "type": "episode",
                "show": {
                    "title": "My Show",
                    "ids": {"tmdb": 555},
                },
                "episode": {
                    "season": 2,
                    "number": 3,
                },
            },
        ]
        mock_get_watchlist_items.return_value = []
        mock_get_metadata.return_value = {
            "title": "My Show",
            "episode_title": "Episode 3",
            "image": "http://example.com/episode.jpg",
        }

        trakt.import_trakt_lists(self.user, "token-123", client_id="client-id")

        imported_list = CustomList.objects.get(owner=self.user, source_id="123")
        imported_item = imported_list.items.get()

        self.assertEqual(imported_item.media_type, MediaTypes.EPISODE.value)
        self.assertEqual(imported_item.media_id, "555")
        self.assertEqual(imported_item.season_number, 2)
        self.assertEqual(imported_item.episode_number, 3)
        mock_get_metadata.assert_called_once_with(
            MediaTypes.EPISODE.value,
            "555",
            "My Show",
            season_number=2,
            episode_number=3,
        )


@override_settings(URLS=["http://192.168.1.50:8000"])
class TraktListsDeviceFlowTests(TestCase):
    """List imports fall back to Trakt's device code flow over plain HTTP (#681)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="trakt-device-user",
            password="device-password",
        )
        self.client.force_login(self.user)
        TraktAccount.objects.update_or_create(
            user=self.user,
            defaults={
                "client_id": import_helpers.encrypt("client-id"),
                "client_secret": import_helpers.encrypt("client-secret"),
            },
        )
        self.device = {
            "device_code": "device-code",
            "user_code": "5055CC52",
            "verification_url": "https://trakt.tv/activate",
            "expires_in": 600,
            "interval": 5,
        }

    def _start(self):
        with patch(
            "lists.views_trakt.trakt_imports.request_device_code",
            return_value=self.device,
        ):
            return self.client.post(reverse("trakt_lists_oauth"))

    def test_start_redirects_to_the_code_screen_without_storing_the_secret(self):
        response = self._start()

        self.assertRedirects(
            response,
            reverse("trakt_lists_device_verify"),
            fetch_redirect_response=False,
        )
        state = self.client.session[TRAKT_LISTS_DEVICE_SESSION_KEY]
        self.assertEqual(state["device_code"], "device-code")
        self.assertNotIn("client_secret", state)
        self.assertNotIn("client-secret", str(state))

    def test_poll_success_queues_the_list_import(self):
        self._start()
        with (
            patch(
                "lists.views_trakt.trakt_imports.poll_device_token",
                return_value={
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "username": "trakt-user",
                },
            ),
            patch(
                "lists.views_trakt.list_tasks.import_trakt_lists_task.delay",
            ) as import_task,
        ):
            response = self.client.get(reverse("trakt_lists_device_poll"))

        import_task.assert_called_once_with(
            self.user.id,
            "access",
            client_id="client-id",
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Redirect"], reverse("lists"))
        self.assertNotIn(TRAKT_LISTS_DEVICE_SESSION_KEY, self.client.session)

    def test_poll_while_pending_keeps_the_session(self):
        self._start()
        with patch(
            "lists.views_trakt.trakt_imports.poll_device_token",
            return_value=None,
        ):
            response = self.client.get(reverse("trakt_lists_device_poll"))

        self.assertEqual(response.status_code, 204)
        self.assertNotIn("HX-Redirect", response)
        self.assertIn(TRAKT_LISTS_DEVICE_SESSION_KEY, self.client.session)


class TraktListImportTransactionTests(TestCase):
    """Network work must finish before the rebuild takes the write lock."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="trakt-txn-user")
        # TestCase wraps each test in a transaction; the import's own atomic
        # block is the one that must not be open during network calls.
        self.baseline_depth = len(connection.atomic_blocks)
        self.depths = []

    def _record_depth(self, value):
        def recorder(*_args, **_kwargs):
            self.depths.append(len(connection.atomic_blocks))
            return value

        return recorder

    def test_network_calls_happen_outside_the_rebuild_transaction(self):
        entry = {"type": "movie", "movie": {"title": "Heat", "ids": {"tmdb": 949}}}
        metadata = {"title": "Heat", "image": "https://example.com/heat.jpg"}

        with (
            patch.object(
                trakt,
                "_get_trakt_lists",
                side_effect=self._record_depth([{"name": "L", "ids": {"trakt": 1}}]),
            ),
            patch.object(
                trakt, "_get_trakt_list_items", side_effect=self._record_depth([entry])
            ),
            patch.object(
                trakt, "_get_trakt_watchlist_items", side_effect=self._record_depth([])
            ),
            patch.object(
                trakt, "_get_metadata", side_effect=self._record_depth(metadata)
            ),
        ):
            trakt.import_trakt_lists(self.user, "token")

        self.assertTrue(self.depths)
        self.assertEqual(set(self.depths), {self.baseline_depth})
        self.assertEqual(
            CustomList.objects.filter(owner=self.user, source="trakt").count(), 2
        )


class TraktListImportFailureTests(TestCase):
    """A failed import must not cost the user lists they already imported."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="trakt-fail-user")
        CustomList.objects.create(
            name="Watchlist",
            owner=self.user,
            source="trakt",
            source_id="watchlist",
        )
        CustomList.objects.create(
            name="Old List", owner=self.user, source="trakt", source_id="7"
        )

    def test_resolution_failure_aborts_before_deleting(self):
        entry = {"type": "movie", "movie": {"title": "Heat", "ids": {"tmdb": 949}}}
        with (
            patch.object(trakt, "_get_trakt_lists", return_value=[]),
            patch.object(trakt, "_get_trakt_watchlist_items", return_value=[entry]),
            patch.object(
                trakt, "_get_metadata", side_effect=RuntimeError("TMDB is down")
            ),
            self.assertRaises(RuntimeError),
        ):
            trakt.import_trakt_lists(self.user, "token")

        self.assertEqual(
            CustomList.objects.filter(owner=self.user, source="trakt").count(), 2
        )

    def test_watchlist_fetch_failure_keeps_the_existing_watchlist(self):
        with (
            patch.object(trakt, "_get_trakt_lists", return_value=[]),
            patch.object(
                trakt,
                "_get_trakt_watchlist_items",
                side_effect=RuntimeError("Trakt is down"),
            ),
        ):
            trakt.import_trakt_lists(self.user, "token")

        remaining = set(
            CustomList.objects.filter(owner=self.user, source="trakt").values_list(
                "source_id", flat=True
            )
        )
        self.assertEqual(remaining, {"watchlist"})


@override_settings(URLS=["https://floppy.example.com"])
class TraktListsWithoutClientSecretTests(TestCase):
    """A Trakt app made without a client secret connects through PKCE (#1523)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="trakt-pkce-user",
            password="pkce-password",
        )
        self.client.force_login(self.user)

    def _save_credentials(self, **fields):
        return self.client.post(reverse("trakt_lists_credentials"), data=fields)

    def test_credentials_save_without_a_secret(self):
        response = self._save_credentials(client_id="client-id", client_secret="")

        self.assertRedirects(response, reverse("lists"), fetch_redirect_response=False)
        account = TraktAccount.objects.get(user=self.user)
        self.assertEqual(import_helpers.decrypt(account.client_id), "client-id")
        self.assertIsNone(account.client_secret)
        self.assertTrue(account.is_configured)

    def test_credentials_still_need_a_client_id(self):
        self._save_credentials(client_id="", client_secret="secret")

        self.assertFalse(TraktAccount.objects.filter(user=self.user).exists())

    def test_authorize_sends_a_pkce_challenge_and_keeps_the_verifier(self):
        self._save_credentials(client_id="client-id", client_secret="")

        response = self.client.post(reverse("trakt_lists_oauth"), secure=True)

        query = parse_qs(urlparse(response["Location"]).query)
        verifier = self.client.session[query["state"][0]]["code_verifier"]
        digest = hashlib.sha256(verifier.encode()).digest()
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(
            query["code_challenge"],
            [base64.urlsafe_b64encode(digest).decode().rstrip("=")],
        )

    def test_authorize_with_a_secret_skips_pkce(self):
        self._save_credentials(client_id="client-id", client_secret="secret")

        response = self.client.post(reverse("trakt_lists_oauth"), secure=True)

        query = parse_qs(urlparse(response["Location"]).query)
        self.assertNotIn("code_challenge", query)
        self.assertNotIn("code_verifier", self.client.session[query["state"][0]])

    def test_callback_exchanges_the_code_with_the_verifier_and_no_secret(self):
        self._save_credentials(client_id="client-id", client_secret="")
        response = self.client.post(reverse("trakt_lists_oauth"), secure=True)
        state_token = parse_qs(urlparse(response["Location"]).query)["state"][0]
        verifier = self.client.session[state_token]["code_verifier"]

        with (
            patch(
                "lists.views_trakt.trakt_imports.handle_oauth_callback",
                return_value={"access_token": "access"},
            ) as handle_callback,
            patch("lists.views_trakt.list_tasks.import_trakt_lists_task.delay"),
        ):
            self.client.get(
                reverse("trakt_lists_callback"),
                {"code": "abc", "state": state_token},
                secure=True,
            )

        kwargs = handle_callback.call_args.kwargs
        self.assertEqual(kwargs["code_verifier"], verifier)
        self.assertEqual(kwargs["client_secret"], "")
