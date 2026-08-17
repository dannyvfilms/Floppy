# FORK: tests for the first-class music API endpoints.
import datetime
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch

from django.contrib.messages import get_messages
from django.urls import reverse

from app.models import (
    Album,
    AlbumTracker,
    Artist,
    ArtistTracker,
    Music,
    Status,
    Track,
)

from .base import FloppyApiTestCase


class MusicApiTestCase(FloppyApiTestCase):
    """Shared music catalog fixtures."""

    def setUp(self):
        """Create an artist with an album and two tracks."""
        super().setUp()
        self.artist = Artist.objects.create(
            name="The Testers",
            musicbrainz_id="11111111-1111-1111-1111-111111111111",
        )
        self.album = Album.objects.create(
            title="First Album",
            artist=self.artist,
            image="https://example.com/album.jpg",
        )
        self.track1 = Track.objects.create(
            album=self.album,
            title="Opening Song",
            track_number=1,
            musicbrainz_recording_id="22222222-2222-2222-2222-222222222222",
            duration_ms=180000,
        )
        self.track2 = Track.objects.create(
            album=self.album,
            title="Closing Song",
            track_number=2,
        )


class ArtistTrackerTests(MusicApiTestCase):
    """Artist tracker CRUD."""

    def test_track_and_list_artist(self):
        """POST creates a tracker; GET lists it."""
        response = self.call_api(
            "post",
            "api_music_artists",
            payload={"artist_id": self.artist.id, "status": "In progress"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.CREATED)
        self.assertEqual(response.json()["name"], "The Testers")

        listed = self.call_api("get", "api_music_artists", headers=self.auth_headers)
        self.assertEqual(listed.status_code, HTTP.OK)
        self.assertEqual(listed.json()["pagination"]["total"], 1)

    def test_patch_tracker_partial(self):
        """PATCH updates only the provided fields."""
        ArtistTracker.objects.create(
            user=self.user1,
            artist=self.artist,
            notes="keep me",
        )
        response = self.call_api(
            "patch",
            "api_music_artist_detail",
            args=(self.artist.id,),
            payload={"score": "8.5"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        tracker = ArtistTracker.objects.get(user=self.user1, artist=self.artist)
        self.assertEqual(str(tracker.score), "8.5")
        self.assertEqual(tracker.notes, "keep me")

    def test_detail_includes_albums(self):
        """GET artist detail includes album summaries."""
        response = self.call_api(
            "get",
            "api_music_artist_detail",
            args=(self.artist.id,),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        payload = response.json()
        self.assertEqual(len(payload["albums"]), 1)
        self.assertIsNone(payload["tracker"])

    def test_delete_tracker(self):
        """DELETE removes the tracker but not the artist."""
        ArtistTracker.objects.create(user=self.user1, artist=self.artist)
        response = self.call_api(
            "delete",
            "api_music_artist_detail",
            args=(self.artist.id,),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NO_CONTENT)
        self.assertTrue(Artist.objects.filter(id=self.artist.id).exists())
        self.assertFalse(
            ArtistTracker.objects.filter(
                user=self.user1,
                artist=self.artist,
            ).exists(),
        )

    def test_untracked_delete_not_found(self):
        """DELETE without a tracker returns 404."""
        response = self.call_api(
            "delete",
            "api_music_artist_detail",
            args=(self.artist.id,),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    @patch("app.fork_services_music.get_or_create_artist_from_musicbrainz")
    def test_track_by_musicbrainz_id(self, mock_create):
        """POST with musicbrainz_id resolves via the shared creation service."""
        mock_create.return_value = self.artist
        response = self.call_api(
            "post",
            "api_music_artists",
            payload={"musicbrainz_id": "11111111-1111-1111-1111-111111111111"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.CREATED)
        mock_create.assert_called_once()


class AlbumTrackerTests(MusicApiTestCase):
    """Album tracker CRUD and tracks listing."""

    def test_track_album_and_get_detail(self):
        """POST creates the tracker; GET returns it."""
        response = self.call_api(
            "post",
            "api_music_albums",
            payload={"album_id": self.album.id, "score": "9.0"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.CREATED)
        detail = self.call_api(
            "get",
            "api_music_album_detail",
            args=(self.album.id,),
            headers=self.auth_headers,
        )
        self.assertEqual(detail.status_code, HTTP.OK)
        self.assertEqual(detail.json()["tracker"]["score"], "9.0")

    def test_tracks_listing_includes_play_state(self):
        """GET tracks lists catalog rows with the user's plays."""
        music = Music.objects.create(
            user=self.user1,
            item=self._make_music_item("play-1"),
            album=self.album,
            artist=self.artist,
            track=self.track1,
        )
        response = self.call_api(
            "get",
            "api_music_album_tracks",
            args=(self.album.id,),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        rows = {row["title"]: row for row in response.json()["results"]}
        self.assertEqual(rows["Opening Song"]["music_id"], music.id)
        self.assertGreaterEqual(rows["Opening Song"]["play_count"], 1)
        self.assertIsNone(rows["Closing Song"]["music_id"])

    def _make_music_item(self, media_id):
        from app.models import Item, MediaTypes, Sources

        return Item.objects.create(
            media_id=media_id,
            source=Sources.MUSICBRAINZ.value,
            media_type=MediaTypes.MUSIC.value,
            title="Play Item",
            image="https://example.com/x.jpg",
        )


class SongPlayTests(MusicApiTestCase):
    """POST music/songs/plays records listens."""

    def test_first_play_creates_music_row(self):
        """The first play creates a Completed Music row with a keyed item."""
        response = self.call_api(
            "post",
            "api_music_song_play",
            payload={
                "album_id": self.album.id,
                "track_id": self.track1.id,
                "recording_id": self.track1.musicbrainz_recording_id,
                "end_date": "2024-06-01",
            },
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.CREATED)
        music = Music.objects.get(user=self.user1, album=self.album, track=self.track1)
        self.assertEqual(
            music.item.media_id,
            "22222222-2222-2222-2222-222222222222",
        )
        self.assertEqual(music.item.runtime_minutes, 3)

    def test_repeat_play_updates_end_date(self):
        """A second play updates end_date on the same row (history counts plays)."""
        for end_date in ("2024-06-01", "2024-06-02"):
            self.call_api(
                "post",
                "api_music_song_play",
                payload={
                    "album_id": self.album.id,
                    "track_id": self.track2.id,
                    "end_date": end_date,
                },
                headers=self.auth_headers,
            )
        rows = Music.objects.filter(
            user=self.user1,
            album=self.album,
            track=self.track2,
        )
        self.assertEqual(rows.count(), 1)
        self.assertEqual(str(rows.first().end_date.date()), "2024-06-02")
        self.assertEqual(rows.first().item.media_id, f"track_{self.track2.id}")

    def test_wrong_album_track_rejected(self):
        """A track from another album returns 404."""
        other_album = Album.objects.create(title="Other", artist=self.artist)
        response = self.call_api(
            "post",
            "api_music_song_play",
            payload={"album_id": other_album.id, "track_id": self.track1.id},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)


class PlaysDeletionTests(MusicApiTestCase):
    """DELETE plays endpoints."""

    def test_delete_album_plays(self):
        """All of the caller's plays for the album are removed."""
        self.call_api(
            "post",
            "api_music_song_play",
            payload={"album_id": self.album.id, "track_id": self.track1.id},
            headers=self.auth_headers,
        )
        response = self.call_api(
            "delete",
            "api_music_album_plays",
            args=(self.album.id,),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["deleted_plays"], 1)
        self.assertFalse(
            Music.objects.filter(user=self.user1, album=self.album).exists(),
        )

    def test_delete_artist_plays_scoped_to_user(self):
        """Another user's plays are untouched."""
        self.call_api(
            "post",
            "api_music_song_play",
            payload={"album_id": self.album.id, "track_id": self.track1.id},
            headers=self.auth_headers,
        )
        self.call_api(
            "post",
            "api_music_song_play",
            payload={"album_id": self.album.id, "track_id": self.track1.id},
            headers=self.auth_headers2,
        )
        response = self.call_api(
            "delete",
            "api_music_artist_plays",
            args=(self.artist.id,),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertFalse(Music.objects.filter(user=self.user1).exists())
        self.assertTrue(Music.objects.filter(user=self.user2).exists())


class TrackScoreTests(MusicApiTestCase):
    """PATCH music/tracks/{music_id}/score."""

    def test_score_set_and_clear(self):
        """Score is stored raw and can be cleared."""
        play = self.call_api(
            "post",
            "api_music_song_play",
            payload={"album_id": self.album.id, "track_id": self.track1.id},
            headers=self.auth_headers,
        )
        music_id = Music.objects.get(user=self.user1, track=self.track1).id
        self.assertEqual(play.status_code, HTTP.CREATED)

        response = self.call_api(
            "patch",
            "api_music_track_score",
            args=(music_id,),
            payload={"score": 7.5},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(str(Music.objects.get(id=music_id).score), "7.5")

        cleared = self.call_api(
            "patch",
            "api_music_track_score",
            args=(music_id,),
            payload={"score": None},
            headers=self.auth_headers,
        )
        self.assertEqual(cleared.status_code, HTTP.OK)
        self.assertIsNone(Music.objects.get(id=music_id).score)


class MusicBulkPlaysTests(MusicApiTestCase):
    """POST music/bulk-plays dispatches the Celery task."""

    @patch("api.fork_views_music.bulk_music_plays_task.apply_async")
    def test_bulk_dispatch(self, mock_apply):
        """A valid range returns 202 with the task id."""
        mock_apply.return_value.id = "music-task-1"
        response = self.call_api(
            "post",
            "api_music_bulk_plays",
            payload={
                "context_kind": "album",
                "context_id": self.album.id,
                "first_disc_number": 1,
                "first_track_number": 1,
                "last_disc_number": 1,
                "last_track_number": 2,
                "start_date": "2024-01-01",
                "end_date": "2024-01-02",
            },
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.ACCEPTED)
        self.assertEqual(response.json()["task_id"], "music-task-1")
        kwargs = mock_apply.call_args.kwargs["kwargs"]
        self.assertEqual(kwargs["context_kind"], "album")
        self.assertEqual(kwargs["first_season_number"], 1)

    def test_bulk_invalid_context_rejected(self):
        """Unknown context kinds return 400."""
        response = self.call_api(
            "post",
            "api_music_bulk_plays",
            payload={"context_kind": "playlist", "context_id": 1},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)


class DiscographySyncTests(MusicApiTestCase):
    """POST music/artists/{id}/sync-discography."""

    @patch("api.fork_views_music.dedupe_artist_albums")
    @patch("api.fork_views_music.sync_artist_discography")
    def test_sync_returns_count(self, mock_sync, mock_dedupe):
        """The synced album count is returned."""
        mock_sync.return_value = 4
        response = self.call_api(
            "post",
            "api_music_artist_sync",
            args=(self.artist.id,),
            payload={},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["synced_albums"], 4)
        mock_dedupe.assert_called_once_with(self.artist)


class AlbumTrackerScopeTests(MusicApiTestCase):
    """Per-user isolation of trackers."""

    def test_trackers_are_per_user(self):
        """User2's tracker is invisible to user1."""
        AlbumTracker.objects.create(user=self.user2, album=self.album)
        listed = self.call_api("get", "api_music_albums", headers=self.auth_headers)
        self.assertEqual(listed.json()["pagination"]["total"], 0)


class SongPlayDateTests(MusicApiTestCase):
    """A listen without a date must still carry a completion timestamp."""

    def test_blank_date_records_the_current_server_time(self):
        """A blank date records a completed listen at the current server time.

        Listen counts read history records that have an end_date, so a listen
        stored without one does not appear.
        """
        completed_at = datetime.datetime(2025, 1, 15, 12, tzinfo=datetime.UTC)

        with patch(
            "app.fork_services_music.timezone.now",
            return_value=completed_at,
        ):
            response = self.call_api(
                "post",
                "api_music_song_play",
                payload={
                    "album_id": self.album.id,
                    "track_id": self.track1.id,
                    "end_date": "",
                },
                headers=self.auth_headers,
            )

        music = Music.objects.get(user=self.user1, album=self.album, track=self.track1)
        self.assertEqual(response.status_code, HTTP.CREATED)
        self.assertEqual(music.status, Status.COMPLETED.value)
        self.assertEqual(music.end_date, completed_at)

    def test_dateless_listen_does_not_clear_an_earlier_timestamp(self):
        """A later dateless listen must not erase the date already recorded.

        The row was updated with whatever the caller sent, so a dateless listen
        wrote NULL over a good timestamp and the earlier listen stopped being
        counted.
        """
        completed_at = datetime.datetime(2025, 1, 15, 12, tzinfo=datetime.UTC)
        self.call_api(
            "post",
            "api_music_song_play",
            payload={
                "album_id": self.album.id,
                "track_id": self.track1.id,
                "end_date": "2024-06-01",
            },
            headers=self.auth_headers,
        )

        with patch(
            "app.fork_services_music.timezone.now",
            return_value=completed_at,
        ):
            self.call_api(
                "post",
                "api_music_song_play",
                payload={"album_id": self.album.id, "track_id": self.track1.id},
                headers=self.auth_headers,
            )

        music = Music.objects.get(user=self.user1, album=self.album, track=self.track1)
        self.assertIsNotNone(music.end_date)
        self.assertEqual(music.end_date, completed_at)


class SongSaveWebDateTests(MusicApiTestCase):
    """The music web form and the REST API must read a date the same way."""

    def _post(self, end_date, **extra):
        self.client.force_login(self.user1)
        return self.client.post(
            reverse("song_save"),
            {
                "album_id": self.album.id,
                "track_id": self.track1.id,
                "recording_id": self.track1.musicbrainz_recording_id,
                "end_date": end_date,
            },
            HTTP_REFERER="/",
            **extra,
        )

    def test_blank_date_records_the_current_server_time(self):
        """A blank date on the web form behaves like a blank date on the API."""
        completed_at = datetime.datetime(2025, 1, 15, 12, tzinfo=datetime.UTC)

        with patch(
            "app.fork_services_music.timezone.now",
            return_value=completed_at,
        ):
            response = self._post("")

        music = Music.objects.get(user=self.user1, album=self.album, track=self.track1)
        self.assertEqual(response.status_code, HTTP.FOUND)
        self.assertEqual(music.end_date, completed_at)

    def test_unreadable_date_records_nothing_and_reports_the_problem(self):
        """An unreadable date must not become "now" behind the user's back.

        The API answers 400 for the same input. The web form discarded the
        value, so the listen was recorded against a time the user never entered.
        """
        response = self._post("not-a-date")

        self.assertEqual(response.status_code, HTTP.FOUND)
        self.assertFalse(
            Music.objects.filter(
                user=self.user1,
                album=self.album,
                track=self.track1,
            ).exists(),
        )
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("YYYY-MM-DD" in message for message in messages), messages)

    def test_unreadable_date_keeps_the_modal_open_for_htmx(self):
        """The modal must survive the error so the typed date can be fixed."""
        response = self._post("not-a-date", HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response["HX-Reswap"], "none")
        self.assertNotIn("closeModal", response["HX-Trigger"])
        self.assertIn("showToast", response["HX-Trigger"])
        self.assertFalse(
            Music.objects.filter(
                user=self.user1,
                album=self.album,
                track=self.track1,
            ).exists(),
        )

    def test_explicit_date_is_kept_exactly(self):
        """An explicit date must survive unchanged."""
        response = self._post("2024-03-01T10:00:00")

        music = Music.objects.get(user=self.user1, album=self.album, track=self.track1)
        self.assertEqual(response.status_code, HTTP.FOUND)
        self.assertEqual(
            music.end_date,
            datetime.datetime(2024, 3, 1, 10, tzinfo=datetime.UTC),
        )

    def test_dateless_listen_is_counted_in_history(self):
        """The point of the fix: a dateless listen must be countable.

        Listen counts read history records that have an end_date. Asserting the
        row's end_date alone does not prove the history record carries one.
        """
        completed_at = datetime.datetime(2025, 1, 15, 12, tzinfo=datetime.UTC)

        with patch(
            "app.fork_services_music.timezone.now",
            return_value=completed_at,
        ):
            self._post("")

        music = Music.objects.get(user=self.user1, album=self.album, track=self.track1)
        dated_history = music.history.filter(end_date__isnull=False)
        self.assertEqual(dated_history.count(), 1)
        self.assertEqual(dated_history.first().end_date, completed_at)

    def test_date_without_a_time_is_read_as_midnight(self):
        """The error copy asks for YYYY-MM-DD, so that form must work."""
        response = self._post("2024-03-01")

        music = Music.objects.get(user=self.user1, album=self.album, track=self.track1)
        self.assertEqual(response.status_code, HTTP.FOUND)
        self.assertEqual(
            music.end_date,
            datetime.datetime(2024, 3, 1, 0, 0, tzinfo=datetime.UTC),
        )
