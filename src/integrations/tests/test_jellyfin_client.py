from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from integrations.jellyfin_client import (
    JellyfinAuthError,
    JellyfinClient,
    JellyfinClientError,
)


class JellyfinClientTests(SimpleTestCase):
    """Cover the outbound Jellyfin REST client."""

    def setUp(self):
        """Create a client pointed at a fake server."""
        self.client = JellyfinClient("https://jellyfin.local:8096", "api-key", "user-1")

    @patch("integrations.jellyfin_client.requests.request")
    def test_healthcheck_returns_json(self, mock_request):
        """Healthcheck should hit /System/Info and return the parsed body."""
        mock_request.return_value = MagicMock(
            status_code=200,
            json=lambda: {"Version": "10.9"},
        )

        result = self.client.healthcheck()

        self.assertEqual(result, {"Version": "10.9"})
        called_url = mock_request.call_args.args[1]
        self.assertTrue(called_url.endswith("/System/Info"))
        self.assertEqual(
            mock_request.call_args.kwargs["headers"]["Authorization"],
            'MediaBrowser Token="api-key"',
        )

    @patch("integrations.jellyfin_client.requests.request")
    def test_unauthorized_raises_auth_error(self, mock_request):
        """A 401 response should raise JellyfinAuthError."""
        mock_request.return_value = MagicMock(status_code=401)

        with self.assertRaises(JellyfinAuthError):
            self.client.healthcheck()

    @patch("integrations.jellyfin_client.requests.request")
    def test_server_error_raises_client_error(self, mock_request):
        """A 500 response should raise JellyfinClientError."""
        mock_request.return_value = MagicMock(status_code=500, text="")

        with self.assertRaises(JellyfinClientError):
            self.client.healthcheck()

    @patch("integrations.jellyfin_client.requests.request")
    def test_error_message_includes_response_body(self, mock_request):
        """Failure messages should carry a snippet of what Jellyfin answered."""
        mock_request.return_value = MagicMock(
            status_code=500,
            text="Something exploded server-side",
        )

        with self.assertRaisesRegex(JellyfinClientError, "Something exploded"):
            self.client.healthcheck()

    @patch("integrations.jellyfin_client.requests.request")
    def test_get_current_user_returns_none_on_client_error(self, mock_request):
        """A 400 from /Users/Me (Dashboard API key) should resolve to no user."""
        mock_request.return_value = MagicMock(status_code=400, text="Bad Request")

        self.assertIsNone(self.client.get_current_user())

    @patch("integrations.jellyfin_client.requests.request")
    def test_get_current_user_still_raises_auth_error(self, mock_request):
        """A 401 from /Users/Me means the key is bad and must propagate."""
        mock_request.return_value = MagicMock(status_code=401)

        with self.assertRaises(JellyfinAuthError):
            self.client.get_current_user()

    @patch("integrations.jellyfin_client.requests.request")
    def test_get_current_user(self, mock_request):
        """Users/Me should resolve to the current Jellyfin user."""
        mock_request.return_value = MagicMock(
            status_code=200,
            content=b"{}",
            json=lambda: {"Id": "abc123", "Name": "danny"},
        )

        result = self.client.get_current_user()

        self.assertEqual(result, {"Id": "abc123", "Name": "danny"})

    @patch("integrations.jellyfin_client.requests.request")
    def test_iter_library_items_pages_until_exhausted(self, mock_request):
        """Library iteration should page through results using StartIndex/Limit."""
        page_one = MagicMock(
            status_code=200,
            json=lambda: {
                "Items": [{"Id": "1"}, {"Id": "2"}],
                "TotalRecordCount": 3,
            },
        )
        page_two = MagicMock(
            status_code=200,
            json=lambda: {"Items": [{"Id": "3"}], "TotalRecordCount": 3},
        )
        mock_request.side_effect = [page_one, page_two]

        items = list(self.client.iter_library_items())

        self.assertEqual([item["Id"] for item in items], ["1", "2", "3"])
        self.assertEqual(mock_request.call_count, 2)
        first_params = mock_request.call_args_list[0].kwargs["params"]
        second_params = mock_request.call_args_list[1].kwargs["params"]
        self.assertEqual(first_params["StartIndex"], 0)
        self.assertEqual(second_params["StartIndex"], 2)
        self.assertEqual(first_params["IncludeItemTypes"], "Movie,Episode,Series")

    @patch("integrations.jellyfin_client.requests.request")
    def test_mark_played_posts_to_played_items(self, mock_request):
        """mark_played should POST to the PlayedItems endpoint for the item."""
        mock_request.return_value = MagicMock(status_code=200)

        self.client.mark_played("item-42")

        method, url = mock_request.call_args.args[:2]
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith("/Users/user-1/PlayedItems/item-42"))

    @patch("integrations.jellyfin_client.requests.request")
    def test_mark_unplayed_deletes_played_items(self, mock_request):
        """mark_unplayed should DELETE the PlayedItems entry for the item."""
        mock_request.return_value = MagicMock(status_code=200)

        self.client.mark_unplayed("item-42")

        method, url = mock_request.call_args.args[:2]
        self.assertEqual(method, "DELETE")
        self.assertTrue(url.endswith("/Users/user-1/PlayedItems/item-42"))

    def test_mark_played_without_user_id_raises(self):
        """Writes require a resolved Jellyfin user id."""
        client = JellyfinClient("https://jellyfin.local:8096", "api-key")

        with self.assertRaises(JellyfinClientError):
            client.mark_played("item-42")

    @patch("integrations.jellyfin_client.requests.request")
    def test_probe_playback_reporting_true_when_reachable(self, mock_request):
        """A 200 from the plugin's route means the API tier is usable."""
        mock_request.return_value = MagicMock(status_code=200, content=b"[]")

        self.assertTrue(self.client.probe_playback_reporting())
        called_url = mock_request.call_args.args[1]
        self.assertTrue(called_url.endswith("/user_usage_stats/type_filter_list"))

    @patch("integrations.jellyfin_client.requests.request")
    def test_probe_playback_reporting_false_when_forbidden(self, mock_request):
        """A non-admin key (403) or missing plugin (404) both mean unavailable."""
        mock_request.return_value = MagicMock(status_code=403, text="Forbidden")

        self.assertFalse(self.client.probe_playback_reporting())

    @patch("integrations.jellyfin_client.requests.request")
    def test_fetch_playback_activity_parses_rows(self, mock_request):
        """Rows come back positionally and are mapped to named columns."""
        mock_request.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "results": [
                    [
                        5,
                        "2024-01-02 03:04:05",
                        "jf-user",
                        "jf-item",
                        "Movie",
                        "Example",
                        "DirectPlay",
                        "Web",
                        "Laptop",
                        120,
                    ],
                ],
            },
        )

        rows = self.client.fetch_playback_activity(2, 100)

        self.assertEqual(rows, [
            {
                "rowid": 5,
                "date_created": "2024-01-02 03:04:05",
                "user_id": "jf-user",
                "item_id": "jf-item",
                "item_type": "Movie",
                "item_name": "Example",
                "playback_method": "DirectPlay",
                "client_name": "Web",
                "device_name": "Laptop",
                "play_duration": 120,
            },
        ])
        body = mock_request.call_args.kwargs["json"]
        self.assertIn("rowid > 2", body["CustomQueryString"])
        self.assertIn("LIMIT 100", body["CustomQueryString"])

    @patch("integrations.jellyfin_client.requests.request")
    def test_fetch_max_playback_activity_rowid(self, mock_request):
        """The max-rowid lookup returns 0 for an empty table."""
        mock_request.return_value = MagicMock(
            status_code=200,
            json=lambda: {"results": [[None]]},
        )

        self.assertEqual(self.client.fetch_max_playback_activity_rowid(), 0)
