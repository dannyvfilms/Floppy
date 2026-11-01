# FORK: tests for the ListenBrainz-compatible ingest endpoints used by
# Multi-Scrobbler and any other client accepting a custom ListenBrainz URL.
import json
import posixpath
import re
from datetime import UTC, datetime
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch
from urllib.parse import urlencode, urlsplit

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from django.urls import resolve, reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from api.listenbrainz_views import _stats_window
from app.models import Music
from integrations.models import IntegrationToken

SUBMIT_URL = "/apis/listenbrainz/1/submit-listens"
VALIDATE_URL = "/apis/listenbrainz/1/validate-token"
USER_LISTENS_URL = "/apis/listenbrainz/1/user/{username}/listens"
USER_STATS_URL = "/apis/listenbrainz/1/stats/user/{username}/{entity}"

BOC_MBID = "69158f97-4c07-4c4e-baf8-4e4ab1ed666e"
MHTRTC_GROUP_MBID = "a7e0d9a8-5c8f-3d0a-9e0e-4a1c5e7e1f00"
ROYGBIV_MBID = "2c4d8e6f-1a3b-4c5d-8e7f-9a0b1c2d3e4f"


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


class UserListensTests(ListenBrainzTestCase):
    """GET user listens gives Multi-Scrobbler the history it dedupes against."""

    def listens_url(self, username=None, **params):
        """Build the user-listens URL for this user."""
        url = USER_LISTENS_URL.format(username=username or self.user.username)
        if params:
            url = f"{url}?{urlencode(params)}"
        return url

    def test_recorded_plays_are_returned_newest_first(self):
        """Each recorded play is a listen, ordered like ListenBrainz."""
        self.submit(
            {
                "listen_type": "import",
                "payload": [
                    _listen(1700000000, track_name="Roygbiv"),
                    _listen(1700000300, track_name="Olson"),
                ],
            },
        )

        response = self.client.get(self.listens_url(), **self.auth)

        self.assertEqual(response.status_code, HTTP.OK)
        payload = response.json()["payload"]
        self.assertEqual(payload["count"], 2)
        self.assertEqual(
            [listen["track_metadata"]["track_name"] for listen in payload["listens"]],
            ["Olson", "Roygbiv"],
        )
        self.assertEqual(payload["listens"][0]["listened_at"], 1700000300)
        self.assertEqual(
            payload["listens"][0]["track_metadata"]["artist_name"],
            "Boards of Canada",
        )
        self.assertEqual(
            payload["listens"][0]["track_metadata"]["release_name"],
            "Music Has the Right to Children",
        )
        self.assertEqual(payload["latest_listen_ts"], 1700000300)
        self.assertEqual(payload["oldest_listen_ts"], 1700000000)

    def test_repeated_plays_of_one_track_are_separate_listens(self):
        """A track played twice has one listen per play, not one per row."""
        self.submit(
            {
                "listen_type": "import",
                "payload": [_listen(1700000000), _listen(1700003600)],
            },
        )

        payload = self.client.get(self.listens_url(), **self.auth).json()["payload"]

        self.assertEqual(payload["count"], 2)
        self.assertEqual(
            [listen["listened_at"] for listen in payload["listens"]],
            [1700003600, 1700000000],
        )

    def test_time_window_and_count_filter_the_page(self):
        """min_ts and max_ts are exclusive, and count bounds the page."""
        self.submit(
            {
                "listen_type": "import",
                "payload": [
                    _listen(1700000000, track_name="One"),
                    _listen(1700000300, track_name="Two"),
                    _listen(1700000600, track_name="Three"),
                ],
            },
        )

        payload = self.client.get(
            self.listens_url(min_ts=1700000000, max_ts=1700000600, count=1),
            **self.auth,
        ).json()["payload"]

        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["listens"][0]["listened_at"], 1700000300)
        self.assertEqual(
            payload["listens"][0]["track_metadata"]["track_name"],
            "Two",
        )

    def test_listens_are_scoped_to_the_token_owner(self):
        """Another account's account token cannot read these plays."""
        other = get_user_model().objects.create_user(username="lbz-other")
        other.music_enabled = True
        other.save()
        other_auth = {"HTTP_AUTHORIZATION": f"Token {other.token}"}
        self.submit({"listen_type": "single", "payload": [_listen()]})

        response = self.client.get(
            self.listens_url(username=other.username),
            **other_auth,
        )

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["payload"]["count"], 0)

    def test_unknown_username_is_not_found(self):
        """A username that is not the token owner is a 404."""
        response = self.client.get(
            self.listens_url(username="someone-else"),
            **self.auth,
        )

        self.assertEqual(response.status_code, HTTP.NOT_FOUND)
        self.assertEqual(response.json()["code"], HTTP.NOT_FOUND)

    def test_invalid_time_window_is_rejected(self):
        """A non-numeric bound is a 400 rather than silently ignored."""
        response = self.client.get(
            self.listens_url(min_ts="yesterday"),
            **self.auth,
        )

        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_token_is_required(self):
        """The endpoint is not public."""
        response = self.client.get(self.listens_url())

        self.assertEqual(response.status_code, HTTP.UNAUTHORIZED)

    def test_trailing_slash_is_routed(self):
        """Both spellings resolve, as with the other ingest routes."""
        response = self.client.get(self.listens_url() + "/", **self.auth)

        self.assertEqual(response.status_code, HTTP.OK)


class UserStatsTests(ListenBrainzTestCase):
    """GET stats/user ranks the token owner's plays like ListenBrainz does."""

    def stats(self, entity, username=None, **params):
        """GET one statistics endpoint for this user."""
        url = USER_STATS_URL.format(
            username=username or self.user.username,
            entity=entity,
        )
        if params:
            url = f"{url}?{urlencode(params)}"
        return self.client.get(url, **self.auth)

    def play(self, *listens):
        """Record listens through the ingest endpoint."""
        self.submit({"listen_type": "import", "payload": list(listens)})

    def test_artists_are_ranked_by_plays(self):
        """Each play counts once towards its artist, most played first."""
        self.play(
            _listen(1700000000, track_name="Roygbiv"),
            _listen(1700000300, track_name="Olson"),
            _listen(1700000600, track_name="Roygbiv"),
            _listen(1700000900, artist_name="Aphex Twin", track_name="Xtal"),
        )

        response = self.stats("artists")

        self.assertEqual(response.status_code, HTTP.OK)
        payload = response.json()["payload"]
        self.assertEqual(
            [(a["artist_name"], a["listen_count"]) for a in payload["artists"]],
            [("Boards of Canada", 3), ("Aphex Twin", 1)],
        )
        self.assertEqual(payload["total_artist_count"], 2)
        self.assertEqual(payload["range"], "all_time")
        self.assertEqual(payload["user_id"], self.user.username)
        self.assertEqual(payload["from_ts"], 1700000000)

    def test_release_groups_and_recordings_carry_musicbrainz_ids(self):
        """Stored MBIDs come back on the album and recording rankings."""
        self.play(_listen(1700000000), _listen(1700000300))
        music = Music.objects.filter(user=self.user).select_related(
            "artist", "album", "track"
        )[0]
        music.artist.musicbrainz_id = BOC_MBID
        music.artist.save()
        music.album.musicbrainz_release_group_id = MHTRTC_GROUP_MBID
        music.album.save()
        music.track.musicbrainz_recording_id = ROYGBIV_MBID
        music.track.save()

        group = self.stats("release-groups").json()["payload"]["release_groups"][0]
        recording = self.stats("recordings").json()["payload"]["recordings"][0]

        self.assertEqual(group["release_group_mbid"], MHTRTC_GROUP_MBID)
        self.assertEqual(group["release_group_name"], music.album.title)
        self.assertEqual(group["artist_mbids"], [BOC_MBID])
        self.assertEqual(group["listen_count"], 2)
        self.assertEqual(recording["recording_mbid"], ROYGBIV_MBID)
        self.assertEqual(recording["track_name"], "Roygbiv")
        self.assertEqual(recording["listen_count"], 2)

    def test_identifiers_that_are_not_mbids_are_withheld(self):
        """A slug stored as an identifier is not sent to MusicBrainz clients."""
        self.play(_listen())
        music = Music.objects.select_related("artist").get(user=self.user)
        music.artist.musicbrainz_id = "boards-of-canada"
        music.artist.save()

        artist = self.stats("artists").json()["payload"]["artists"][0]

        self.assertIsNone(artist["artist_mbid"])

    def test_range_bounds_the_plays(self):
        """this_year leaves out older plays that all_time counts."""
        recent = int(timezone.now().timestamp()) - 60
        self.play(_listen(1700000000), _listen(recent, track_name="Olson"))

        this_year = self.stats("recordings", range="this_year").json()["payload"]
        all_time = self.stats("recordings", range="all_time").json()["payload"]

        self.assertEqual(
            [r["track_name"] for r in this_year["recordings"]],
            ["Olson"],
        )
        self.assertEqual(all_time["total_recording_count"], 2)

    def test_count_and_offset_page_the_ranking(self):
        """The count and offset parameters select a window of the ranking."""
        self.play(
            _listen(1700000000, track_name="One"),
            _listen(1700000300, track_name="One"),
            _listen(1700000600, track_name="Two"),
        )

        payload = self.stats("recordings", count=1, offset=1).json()["payload"]

        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["offset"], 1)
        self.assertEqual(payload["total_recording_count"], 2)
        self.assertEqual(payload["recordings"][0]["track_name"], "Two")

    def test_no_plays_is_an_empty_ranking(self):
        """A range without plays answers 200 with nothing ranked."""
        for entity, key in (
            ("artists", "artists"),
            ("release-groups", "release_groups"),
            ("recordings", "recordings"),
        ):
            with self.subTest(entity=entity):
                response = self.stats(entity)
                self.assertEqual(response.status_code, HTTP.OK)
                self.assertEqual(response.json()["payload"][key], [])
        response = self.stats("genre-activity")
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["result"], [])

    def test_genre_activity_counts_plays_per_genre_and_hour(self):
        """A play counts once per genre, in its local hour of the day."""
        self.play(_listen(1700000000), _listen(1700000300, track_name="Olson"))
        album = Music.objects.select_related("album").filter(user=self.user)[0].album
        album.genres = ["Electronic", "IDM"]
        album.save()
        hour = timezone.localtime(datetime.fromtimestamp(1700000000, tz=UTC)).hour

        result = self.stats("genre-activity").json()["result"]

        self.assertEqual(
            sorted((e["genre"], e["hour"], e["listen_count"]) for e in result),
            [("electronic", hour, 2), ("idm", hour, 2)],
        )

    def test_invalid_requests_are_rejected(self):
        """A bad range or page is a 400, another user a 404, no token a 401."""
        self.play(_listen())

        self.assertEqual(
            self.stats("artists", range="forever").status_code,
            HTTP.BAD_REQUEST,
        )
        self.assertEqual(
            self.stats("artists", count="many").status_code,
            HTTP.BAD_REQUEST,
        )
        self.assertEqual(
            self.stats("artists", offset=-1).status_code,
            HTTP.BAD_REQUEST,
        )
        self.assertEqual(
            self.stats("artists", username="someone-else").status_code,
            HTTP.NOT_FOUND,
        )
        self.assertEqual(
            self.client.get(
                USER_STATS_URL.format(username=self.user.username, entity="artists")
            ).status_code,
            HTTP.UNAUTHORIZED,
        )

    def test_stats_are_scoped_to_the_token_owner(self):
        """Another account's plays never enter this user's ranking."""
        other = get_user_model().objects.create_user(username="lbz-other")
        other.music_enabled = True
        other.save()
        self.submit(
            {"listen_type": "single", "payload": [_listen()]},
            headers={"HTTP_AUTHORIZATION": f"Token {other.token}"},
        )

        self.assertEqual(self.stats("artists").json()["payload"]["artists"], [])


class StatsWindowTests(SimpleTestCase):
    """The ranges match ListenBrainz: this_* run to now, the rest are complete."""

    def test_windows_for_a_thursday_in_may(self):
        """Each range starts and ends where ListenBrainz's would."""
        now = datetime(2026, 5, 14, 15, 30, tzinfo=UTC)

        def day(month, day_of_month, year=2026):
            return datetime(year, month, day_of_month, tzinfo=UTC)

        expected = {
            "all_time": (None, None),
            "this_week": (day(5, 11), now),
            "this_month": (day(5, 1), now),
            "this_year": (day(1, 1), now),
            "week": (day(5, 4), day(5, 11)),
            "month": (day(4, 1), day(5, 1)),
            "quarter": (day(1, 1), day(4, 1)),
            "half_yearly": (day(7, 1, 2025), day(1, 1)),
            "year": (day(1, 1, 2025), day(1, 1)),
        }
        for range_, bounds in expected.items():
            with self.subTest(range=range_):
                self.assertEqual(_stats_window(range_, now), bounds)


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
                            "origin_url": "https://soundcloud.com/duskymusic/dusky-careless",
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
        self.assertEqual(
            event.origin_url,
            "https://soundcloud.com/duskymusic/dusky-careless",
        )
        self.assertTrue(event.completed)

    @patch("integrations.webhooks.listenbrainz.music_scrobble.record_music_playback")
    def test_spotify_track_url_is_the_play_link_when_origin_is_empty(self, mock_record):
        """Multi-Scrobbler sends the Spotify URL as spotify_id, not origin_url."""
        mock_record.return_value = None
        spotify_url = "https://open.spotify.com/track/5xkYA3NvMBHLqefhDTYaCO"
        self.submit(
            {
                "listen_type": "single",
                "payload": [
                    _listen(additional_info={"spotify_id": spotify_url}),
                ],
            },
        )

        self.assertEqual(mock_record.call_args.args[0].origin_url, spotify_url)

    @patch("integrations.webhooks.listenbrainz.music_scrobble.record_music_playback")
    def test_spotify_lookalike_url_is_not_a_play_link(self, mock_record):
        """A URL that only mentions spotify.com in its query is not a Spotify link."""
        mock_record.return_value = None
        self.submit(
            {
                "listen_type": "single",
                "payload": [
                    _listen(
                        additional_info={
                            "spotify_id": "https://evil.example/?q=spotify.com",
                        },
                    ),
                ],
            },
        )

        self.assertEqual(mock_record.call_args.args[0].origin_url, "")

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
