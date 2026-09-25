# FORK: tests for the ListenBrainz-compatible ingest endpoints used by
# Multi-Scrobbler and any other client accepting a custom ListenBrainz URL.
import json
import posixpath
import re
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.urls import resolve, reverse
from rest_framework.test import APITestCase

from app.models import Music
from integrations.models import IntegrationToken

SUBMIT_URL = "/apis/listenbrainz/1/submit-listens"
VALIDATE_URL = "/apis/listenbrainz/1/validate-token"


def _listen(listened_at=1700000000, **metadata):
    """Build a minimal ListenBrainz listen entry."""
    track_metadata = {
        "artist_name": "Boards of Canada",
        "track_name": "Roygbiv",
        "release_name": "Music Has the Right to Children",
    }
    track_metadata.update(metadata)
    return {"listened_at": listened_at, "track_metadata": track_metadata}


class ListenBrainzTestCase(APITestCase):
    """Shared setup: a music-enabled user and no MusicBrainz network calls."""

    def setUp(self):
        """Create a music-enabled user and stub MusicBrainz lookups."""
        self.user = get_user_model().objects.create_user(username="lbz-user")
        self.user.music_enabled = True
        self.user.save()
        self.auth = {"HTTP_AUTHORIZATION": f"Token {self.user.token}"}

        for name in ("search", "search_artists"):
            patcher = patch(
                f"app.services.music_scrobble.musicbrainz.{name}",
                return_value={"results": [], "total_results": 0},
            )
            patcher.start()
            self.addCleanup(patcher.stop)

    def submit(self, body, headers=None):
        """POST a submission body to the ingest endpoint."""
        return self.client.post(
            SUBMIT_URL,
            body,
            format="json",
            **(self.auth if headers is None else headers),
        )


class ListenBrainzAuthTests(ListenBrainzTestCase):
    """The endpoints use ListenBrainz-style `Authorization: Token` auth."""

    def test_missing_token_rejected(self):
        """No Authorization header returns 401, as the protocol specifies."""
        response = self.submit(
            {"listen_type": "single", "payload": [_listen()]}, headers={}
        )
        self.assertEqual(response.status_code, HTTP.UNAUTHORIZED)

    def test_invalid_token_rejected(self):
        """An unknown token returns 401."""
        response = self.submit(
            {"listen_type": "single", "payload": [_listen()]},
            headers={"HTTP_AUTHORIZATION": "Token not-a-real-token"},
        )
        self.assertEqual(response.status_code, HTTP.UNAUTHORIZED)

    def test_validate_token_reports_username(self):
        """validate-token confirms the token and echoes the username."""
        response = self.client.get(VALIDATE_URL, **self.auth)
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(
            response.json(),
            {
                "code": 200,
                "message": "Token valid.",
                "valid": True,
                "user_name": self.user.username,
            },
        )

    def test_validate_token_rejects_bad_token(self):
        """validate-token returns 401 for an unknown token."""
        response = self.client.get(
            VALIDATE_URL,
            HTTP_AUTHORIZATION="Token nope",
        )
        self.assertEqual(response.status_code, HTTP.UNAUTHORIZED)

    def test_url_resolves_without_trailing_slash_and_with(self):
        """Both /submit-listens and /submit-listens/ are routed."""
        self.assertEqual(
            reverse("listenbrainz_submit_listens"),
            "/apis/listenbrainz/1/submit-listens",
        )
        response = self.submit({"listen_type": "playing_now", "payload": []})
        self.assertEqual(response.status_code, HTTP.OK)
        trailing = self.client.post(
            SUBMIT_URL + "/",
            {"listen_type": "playing_now", "payload": []},
            format="json",
            **self.auth,
        )
        self.assertEqual(trailing.status_code, HTTP.OK)


class ListenBrainzValidationTests(ListenBrainzTestCase):
    """400s for malformed submissions."""

    def test_invalid_listen_type_rejected(self):
        """An unrecognised listen_type is rejected."""
        response = self.submit({"listen_type": "bogus", "payload": [_listen()]})
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_missing_payload_rejected(self):
        """A submission without a payload list is rejected."""
        response = self.submit({"listen_type": "single"})
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_single_requires_exactly_one_listen(self):
        """listen_type 'single' must carry exactly one listen."""
        response = self.submit(
            {"listen_type": "single", "payload": [_listen(), _listen(1700000100)]},
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_oversized_submission_rejected(self):
        """A submission beyond the per-request cap is rejected."""
        response = self.submit(
            {
                "listen_type": "import",
                "payload": [_listen(1700000000 + i) for i in range(1001)],
            },
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_music_disabled_rejected(self):
        """Users with music tracking off cannot ingest listens."""
        self.user.music_enabled = False
        self.user.save()
        response = self.submit({"listen_type": "single", "payload": [_listen()]})
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)
        self.assertFalse(Music.objects.filter(user=self.user).exists())


class ListenBrainzIngestTests(ListenBrainzTestCase):
    """Recorded submissions reach the shared music write path."""

    def test_single_listen_creates_music_entry(self):
        """A 'single' submission records one play."""
        response = self.submit({"listen_type": "single", "payload": [_listen()]})
        self.assertEqual(response.status_code, HTTP.OK)

        entry = Music.objects.get(user=self.user)
        self.assertEqual(entry.track.title, "Roygbiv")
        self.assertEqual(entry.artist.name, "Boards of Canada")
        self.assertEqual(entry.album.title, "Music Has the Right to Children")
        self.assertEqual(entry.progress, 1)
        self.assertIsNotNone(entry.end_date)

    def test_import_records_multiple_listens(self):
        """An 'import' submission records every listen it carries."""
        payload = [
            _listen(1700000000, track_name="Roygbiv"),
            _listen(1700000300, track_name="Olson"),
            _listen(1700000600, track_name="Turquoise Hexagon Sun"),
        ]
        response = self.submit({"listen_type": "import", "payload": payload})
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(Music.objects.filter(user=self.user).count(), 3)

    def test_playing_now_is_accepted_but_not_recorded(self):
        """Now-playing pings return 200 without writing anything."""
        response = self.submit(
            {
                "listen_type": "playing_now",
                "payload": [
                    {
                        "track_metadata": {
                            "artist_name": "Boards of Canada",
                            "track_name": "Roygbiv",
                        }
                    }
                ],
            },
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertFalse(Music.objects.filter(user=self.user).exists())

    def test_duplicate_submission_is_a_noop(self):
        """Re-submitting the same listen does not double-count it."""
        body = {"listen_type": "single", "payload": [_listen()]}
        self.assertEqual(self.submit(body).status_code, HTTP.OK)
        self.assertEqual(self.submit(body).status_code, HTTP.OK)

        entry = Music.objects.get(user=self.user)
        self.assertEqual(entry.progress, 1)

    def test_listen_without_required_metadata_is_skipped(self):
        """A listen missing artist or track is skipped, not fatal."""
        response = self.submit(
            {
                "listen_type": "import",
                "payload": [
                    {
                        "listened_at": 1700000000,
                        "track_metadata": {"track_name": "Orphan"},
                    },
                    _listen(1700000300),
                ],
            },
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(Music.objects.filter(user=self.user).count(), 1)

    def test_listens_are_scoped_to_the_submitting_user(self):
        """A listen is recorded against the token's owner only."""
        other = get_user_model().objects.create_user(username="lbz-other")
        other.music_enabled = True
        other.save()

        self.submit({"listen_type": "single", "payload": [_listen()]})

        self.assertEqual(Music.objects.filter(user=self.user).count(), 1)
        self.assertEqual(Music.objects.filter(user=other).count(), 0)


class ListenBrainzMetadataTests(ListenBrainzTestCase):
    """additional_info is mapped onto the playback event."""

    @patch("integrations.webhooks.listenbrainz.music_scrobble.record_music_playback")
    def test_additional_info_maps_to_external_ids(self, mock_record):
        """MBIDs, duration and track number reach the playback event."""
        mock_record.return_value = None
        self.submit(
            {
                "listen_type": "single",
                "payload": [
                    _listen(
                        additional_info={
                            "recording_mbid": "rec-1",
                            "release_mbid": "rel-1",
                            "artist_mbids": ["art-1", "art-2"],
                            "duration_ms": 210000,
                            "track_number": 4,
                        },
                    ),
                ],
            },
        )

        event = mock_record.call_args.args[0]
        self.assertEqual(
            event.external_ids,
            {
                "musicbrainz_recording": "rec-1",
                "musicbrainz_release": "rel-1",
                "musicbrainz_artist": "art-1",
            },
        )
        self.assertEqual(event.duration_ms, 210000)
        self.assertEqual(event.track_number, 4)
        self.assertTrue(event.completed)

    @patch("integrations.webhooks.listenbrainz.music_scrobble.record_music_playback")
    def test_duration_in_seconds_is_converted(self, mock_record):
        """Clients sending whole-second `duration` are normalised to ms."""
        mock_record.return_value = None
        self.submit(
            {
                "listen_type": "single",
                "payload": [_listen(additional_info={"duration": 195})],
            },
        )

        self.assertEqual(mock_record.call_args.args[0].duration_ms, 195000)

    @patch("integrations.webhooks.listenbrainz.music_scrobble.record_music_playback")
    def test_spec_tracknumber_key_is_read(self, mock_record):
        """The spec's `tracknumber` spelling reaches the playback event."""
        mock_record.return_value = None
        self.submit(
            {
                "listen_type": "single",
                "payload": [_listen(additional_info={"tracknumber": 7})],
            },
        )

        self.assertEqual(mock_record.call_args.args[0].track_number, 7)


def _navidrome_listen(listened_at=None):
    """Build a listen shaped exactly like Navidrome's ListenBrainz agent sends.

    Mirrors formatListen() in navidrome/adapters/listenbrainz/agent.go:
    `playing_now` listens carry no `listened_at`.
    """
    listen = {
        "track_metadata": {
            "artist_name": "Boards of Canada",
            "track_name": "Roygbiv",
            "release_name": "Music Has the Right to Children",
            "additional_info": {
                "submission_client": "Navidrome",
                "submission_client_version": "0.58.0",
                "tracknumber": 7,
                "artist_names": ["Boards of Canada"],
                "artist_mbids": ["art-1"],
                "recording_mbid": "rec-1",
                "release_mbid": "rel-1",
                "release_group_mbid": "rg-1",
                "duration_ms": 142000,
            },
        },
    }
    if listened_at is not None:
        listen["listened_at"] = listened_at
    return listen


class NavidromeConformanceTests(ListenBrainzTestCase):
    """Replays the requests Navidrome makes when pointed at Floppy.

    Navidrome joins its ListenBrainz BaseURL with the endpoint name, so paths
    arrive without a trailing slash, and it authenticates with
    `Authorization: Token <key>`. The key is a scoped integration token.
    """

    NAVIDROME_CONTENT_TYPE = "application/json; charset=UTF-8"

    def setUp(self):
        """Issue a scrobble-scoped integration token, as the setup guide says."""
        super().setUp()
        _, raw = IntegrationToken.generate(
            user=self.user,
            name="Navidrome",
            scopes=["scrobble:write"],
        )
        self.navidrome_auth = {"HTTP_AUTHORIZATION": f"Token {raw}"}

    def navidrome_request(self, method, url, body, auth=None):
        """Send a request with Navidrome's headers and JSON body."""
        # generic() sends the JSON body even on GET, as Navidrome does.
        return self.client.generic(
            method,
            url,
            json.dumps(body),
            content_type=self.NAVIDROME_CONTENT_TYPE,
            **(self.navidrome_auth if auth is None else auth),
        )

    def test_link_validates_token(self):
        """Linking in Navidrome's UI sends GET validate-token with a `{}` body."""
        response = self.navidrome_request("GET", VALIDATE_URL, {})

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertIs(response.json()["valid"], True)
        self.assertEqual(response.json()["user_name"], self.user.username)

    def test_now_playing_is_accepted_and_not_recorded(self):
        """Navidrome warns unless the reply's status is `ok`."""
        response = self.navidrome_request(
            "POST",
            SUBMIT_URL,
            {"listen_type": "playing_now", "payload": [_navidrome_listen()]},
        )

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(Music.objects.filter(user=self.user).count(), 0)

    # Navidrome's MBIDs trigger MusicBrainz lookups by ID; answer them offline.
    @patch("app.providers.musicbrainz.get_cover_art", return_value=None)
    @patch("app.services.music_scrobble.sync_artist_discography")
    @patch("app.services.music_scrobble.musicbrainz.get_artist")
    @patch("app.services.music_scrobble.musicbrainz.recording")
    def test_scrobble_records_a_play(
        self,
        mock_recording,
        mock_get_artist,
        _mock_sync,
        _mock_cover,
    ):
        """A finished track becomes a music play for the token's user."""
        mock_recording.return_value = {
            "title": "Roygbiv",
            "_artist_name": "Boards of Canada",
            "_artist_id": "art-1",
            "_album_title": "Music Has the Right to Children",
            "_album_id": "rel-1",
            "image": "",
            "genres": [],
            "details": {"duration_minutes": 2.4, "release_date": "1998-04-20"},
            "max_progress": None,
        }
        mock_get_artist.return_value = {"sort_name": "Boards of Canada"}

        response = self.navidrome_request(
            "POST",
            SUBMIT_URL,
            {
                "listen_type": "single",
                "payload": [_navidrome_listen(listened_at=1700000000)],
            },
        )

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(Music.objects.filter(user=self.user).count(), 1)

    @patch("integrations.webhooks.listenbrainz.music_scrobble.record_music_playback")
    def test_scrobble_metadata_is_mapped(self, mock_record):
        """Navidrome's MBIDs, duration and track number all reach the event."""
        mock_record.return_value = None
        self.navidrome_request(
            "POST",
            SUBMIT_URL,
            {
                "listen_type": "single",
                "payload": [_navidrome_listen(listened_at=1700000000)],
            },
        )

        event = mock_record.call_args.args[0]
        self.assertEqual(
            event.external_ids,
            {
                "musicbrainz_recording": "rec-1",
                "musicbrainz_release": "rel-1",
                "musicbrainz_artist": "art-1",
            },
        )
        self.assertEqual(event.track_number, 7)
        self.assertEqual(event.duration_ms, 142000)
        self.assertEqual(event.entry_source, "listenbrainz")

    def test_token_without_scrobble_scope_cannot_submit(self):
        """A token missing `scrobble:write` is refused, so nothing is recorded."""
        _, raw = IntegrationToken.generate(
            user=self.user,
            name="read only",
            scopes=["watchlist:read"],
        )
        response = self.navidrome_request(
            "POST",
            SUBMIT_URL,
            {
                "listen_type": "single",
                "payload": [_navidrome_listen(listened_at=1700000000)],
            },
            auth={"HTTP_AUTHORIZATION": f"Token {raw}"},
        )

        self.assertEqual(response.status_code, HTTP.FORBIDDEN)
        self.assertEqual(Music.objects.filter(user=self.user).count(), 0)

    def test_settings_page_url_reaches_the_endpoints(self):
        """The Base URL on the Integrations page is one Navidrome can use.

        Navidrome appends the endpoint name with Go's path.Join, so the copied
        URL plus `submit-listens` / `validate-token` must hit these views.
        """
        self.client.force_login(self.user)
        page = self.client.get(reverse("integrations")).content.decode()
        match = re.search(r'id="navidrome-listenbrainz-url"[^>]*value="([^"]+)"', page)
        self.assertIsNotNone(match)
        base_path = urlsplit(match.group(1)).path

        for endpoint, view_name in (
            ("submit-listens", "listenbrainz_submit_listens"),
            ("validate-token", "listenbrainz_validate_token"),
        ):
            with self.subTest(endpoint=endpoint):
                joined = posixpath.join(base_path, endpoint)
                self.assertEqual(resolve(joined).url_name, view_name)
