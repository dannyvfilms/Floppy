# FORK: tests for the ListenBrainz-compatible ingest endpoints used by
# Multi-Scrobbler and any other client accepting a custom ListenBrainz URL.
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from app.models import Music

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
