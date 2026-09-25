from unittest.mock import MagicMock, patch

import requests
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from integrations import seerr_api
from integrations.imports.helpers import decrypt, encrypt
from users.models import User

TV_PAYLOAD = {
    "seasons": [
        {"seasonNumber": 0, "name": "Specials", "episodeCount": 3},
        {"seasonNumber": 1, "name": "Season 1", "episodeCount": 8},
        {"seasonNumber": 2, "name": "Season 2", "episodeCount": 8},
        {"seasonNumber": 3, "name": "Season 3", "episodeCount": 8},
        {"seasonNumber": 4, "name": "Season 4", "episodeCount": 0},
    ],
    "mediaInfo": {
        "status": 4,
        "seasons": [{"seasonNumber": 1, "status": 5}],
        "requests": [
            {"status": 1, "seasons": [{"seasonNumber": 2}]},
            {"status": 3, "seasons": [{"seasonNumber": 3}]},  # declined
        ],
    },
}


USERS_PAYLOAD = {
    "results": [
        {
            "id": 7,
            "username": "bob",
            "email": "bob@example.com",
            "jellyfinUsername": "bob_jf",
        },
        {"id": 8, "username": "bobby", "email": "bobby@example.com"},
        {"id": 9, "plexUsername": "shared"},
        {"id": 10, "jellyfinUsername": "shared"},
    ]
}


def _response(status=200, payload=None):
    response = MagicMock()
    response.ok = status < 400
    response.status_code = status
    response.content = b"{}"
    response.json.return_value = payload or {}
    return response


class SummarizeTests(SimpleTestCase):
    def test_movie_without_media_info_is_requestable(self):
        self.assertEqual(
            seerr_api.summarize("movie", {}),
            {"status": "unknown", "requestable": True},
        )

    def test_available_movie_is_not_requestable(self):
        summary = seerr_api.summarize("movie", {"mediaInfo": {"status": 5}})
        self.assertEqual(summary, {"status": "available", "requestable": False})

    def test_tv_seasons_merge_availability_and_active_requests(self):
        summary = seerr_api.summarize("tv", TV_PAYLOAD)
        self.assertEqual(
            [(s["number"], s["status"], s["requestable"]) for s in summary["seasons"]],
            [
                (1, "available", False),
                (2, "pending", False),
                (3, "unknown", True),  # its only request was declined
            ],
        )
        self.assertTrue(summary["requestable"])


class SeerrClientTests(SimpleTestCase):
    @patch("integrations.seerr_api.requests.request")
    def test_tv_request_sends_seasons_and_user(self, mock_request):
        mock_request.return_value = _response(201)
        seerr_api.SeerrClient("http://seerr:5055/", "key").request(
            "tv", 1399, 7, seasons=[2, 3]
        )
        args, kwargs = mock_request.call_args
        self.assertEqual(args, ("POST", "http://seerr:5055/api/v1/request"))
        self.assertEqual(kwargs["headers"], {"X-Api-Key": "key"})
        self.assertEqual(
            kwargs["json"],
            {"mediaType": "tv", "mediaId": 1399, "seasons": [2, 3], "userId": 7},
        )

    @patch("integrations.seerr_api.requests.request")
    def test_movie_request_has_no_seasons(self, mock_request):
        mock_request.return_value = _response(201)
        seerr_api.SeerrClient("http://seerr", "key").request("movie", 603, 7)
        self.assertEqual(
            mock_request.call_args.kwargs["json"],
            {"mediaType": "movie", "mediaId": 603, "userId": 7},
        )

    @patch("integrations.seerr_api.requests.request")
    def test_tv_request_defaults_to_all_seasons(self, mock_request):
        mock_request.return_value = _response(201)
        seerr_api.SeerrClient("http://seerr", "key").request("tv", 1399, 7)
        self.assertEqual(mock_request.call_args.kwargs["json"]["seasons"], "all")

    @patch("integrations.seerr_api.requests.request")
    def test_refusal_surfaces_seerr_message(self, mock_request):
        mock_request.return_value = _response(403, {"message": "Quota exceeded"})
        with self.assertRaisesMessage(seerr_api.SeerrError, "(403) Quota exceeded"):
            seerr_api.SeerrClient("http://seerr", "key").media("movie", 603)

    @patch("integrations.seerr_api.requests.request")
    def test_unreachable_raises_seerr_error(self, mock_request):
        mock_request.side_effect = requests.ConnectionError("http://seerr/?t=secret")
        with self.assertRaises(seerr_api.SeerrError) as caught:
            seerr_api.SeerrClient("http://seerr", "key").media("movie", 603)
        # The configured URL is never echoed back (outbound-fetch.md).
        self.assertEqual(
            str(caught.exception), "Could not reach Seerr (ConnectionError)"
        )


class FindUserTests(SimpleTestCase):
    @patch("integrations.seerr_api.requests.request")
    def test_exact_login_match_wins_over_substring_hits(self, mock_request):
        mock_request.return_value = _response(200, USERS_PAYLOAD)
        client = seerr_api.SeerrClient("http://seerr", "key")
        self.assertEqual(client.find_user_id("Bob"), 7)
        self.assertEqual(client.find_user_id("bobby@example.com"), 8)
        self.assertEqual(client.find_user_id("bob_jf"), 7)  # Jellyfin login
        self.assertEqual(
            mock_request.call_args.kwargs["params"], {"q": "bob_jf", "take": 50}
        )

    @patch("integrations.seerr_api.requests.request")
    def test_unknown_or_ambiguous_name_raises(self, mock_request):
        mock_request.return_value = _response(200, USERS_PAYLOAD)
        client = seerr_api.SeerrClient("http://seerr", "key")
        with self.assertRaisesMessage(seerr_api.SeerrError, "No Seerr user named"):
            client.find_user_id("bo")
        with self.assertRaisesMessage(seerr_api.SeerrError, "Several Seerr users"):
            client.find_user_id("shared")


class SeerrRequestViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="john", password="pw")
        self.user.seerr_url = "http://seerr:5055"
        self.user.seerr_api_key = encrypt("key")
        self.user.seerr_user_id = 7
        self.user.save()
        self.client.force_login(self.user)

    @patch("integrations.seerr_api.requests.request")
    def test_get_renders_state(self, mock_request):
        mock_request.return_value = _response(200, TV_PAYLOAD)
        response = self.client.get(reverse("seerr_request", args=["tv", 1399]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["summary"]["seasons"][2]["number"], 3)
        self.assertContains(response, "http://seerr:5055/tv/1399")

    @patch("integrations.seerr_api.requests.request")
    def test_post_requests_season_then_refreshes(self, mock_request):
        mock_request.side_effect = [_response(201), _response(200, TV_PAYLOAD)]
        response = self.client.post(
            reverse("seerr_request", args=["tv", 1399]), {"season": "3"}
        )
        self.assertEqual(response.status_code, 200)
        post_call = mock_request.call_args_list[0]
        self.assertEqual(
            post_call.kwargs["json"],
            {"mediaType": "tv", "mediaId": 1399, "seasons": [3], "userId": 7},
        )

    @patch("integrations.seerr_api.requests.request")
    def test_error_is_shown_not_raised(self, mock_request):
        mock_request.side_effect = requests.ConnectionError("refused")
        response = self.client.get(reverse("seerr_request", args=["movie", 603]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Could not reach Seerr")

    def test_not_found_without_settings_or_for_other_types(self):
        self.assertEqual(
            self.client.get(reverse("seerr_request", args=["anime", 1])).status_code,
            404,
        )
        self.user.seerr_user_id = None
        self.user.save()
        self.assertEqual(
            self.client.get(reverse("seerr_request", args=["movie", 603])).status_code,
            404,
        )


class SeerrSettingsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="john", password="pw")
        self.client.force_login(self.user)
        self.url = reverse("update_jellyseerr_settings")

    def _post(self, **data):
        self.client.post(self.url, data)
        self.user.refresh_from_db()

    @patch("integrations.seerr_api.requests.request")
    def test_resolves_username_and_encrypts_key(self, mock_request):
        mock_request.return_value = _response(200, USERS_PAYLOAD)
        self._post(
            seerr_url="http://seerr:5055/", seerr_api_key="secret", seerr_username="bob"
        )
        self.assertEqual(self.user.seerr_url, "http://seerr:5055")
        self.assertEqual(decrypt(self.user.seerr_api_key), "secret")
        self.assertEqual(self.user.seerr_username, "bob")
        self.assertEqual(self.user.seerr_user_id, 7)
        self.assertEqual(
            mock_request.call_args.kwargs["headers"], {"X-Api-Key": "secret"}
        )

    @patch("integrations.seerr_api.requests.request")
    def test_blank_key_keeps_stored_one_for_resolution(self, mock_request):
        self.user.seerr_url = "http://seerr:5055"
        self.user.seerr_api_key = encrypt("secret")
        self.user.save()
        mock_request.return_value = _response(200, USERS_PAYLOAD)
        self._post(seerr_url="http://seerr:5055", seerr_username="bobby")
        self.assertEqual(decrypt(self.user.seerr_api_key), "secret")
        self.assertEqual(self.user.seerr_user_id, 8)
        self.assertEqual(
            mock_request.call_args.kwargs["headers"], {"X-Api-Key": "secret"}
        )

    @patch("integrations.seerr_api.requests.request")
    def test_unchanged_settings_do_not_call_seerr(self, mock_request):
        self.user.seerr_url = "http://seerr:5055"
        self.user.seerr_api_key = encrypt("secret")
        self.user.seerr_username = "bob"
        self.user.seerr_user_id = 7
        self.user.save()
        self._post(
            seerr_url="http://seerr:5055", seerr_username="bob", jellyseerr_enabled="on"
        )
        mock_request.assert_not_called()
        self.assertTrue(self.user.jellyseerr_enabled)
        self.assertEqual(self.user.seerr_user_id, 7)

    @patch("integrations.seerr_api.requests.request")
    def test_unknown_user_or_bad_key_saves_nothing(self, mock_request):
        for response in (
            _response(200, USERS_PAYLOAD),
            _response(403, {"message": "Forbidden"}),
        ):
            mock_request.return_value = response
            self._post(
                seerr_url="http://seerr:5055",
                seerr_api_key="secret",
                seerr_username="nobody",
            )
            self.assertEqual(self.user.seerr_url, "")
            self.assertIsNone(self.user.seerr_user_id)

    def test_username_is_required_with_a_url(self):
        self._post(seerr_url="http://seerr:5055", seerr_api_key="secret")
        self.assertEqual(self.user.seerr_url, "")
        self.assertEqual(self.user.seerr_api_key, "")

    def test_clearing_url_disconnects(self):
        self.user.seerr_url = "http://seerr:5055"
        self.user.seerr_api_key = encrypt("secret")
        self.user.seerr_username = "bob"
        self.user.seerr_user_id = 7
        self.user.save()
        self._post(seerr_url="")
        self.assertEqual(self.user.seerr_api_key, "")
        self.assertEqual(self.user.seerr_username, "")
        self.assertIsNone(self.user.seerr_user_id)

    def test_rejects_non_http_url(self):
        self._post(seerr_url="javascript:alert(1)", seerr_username="bob")
        self.assertEqual(self.user.seerr_url, "")
