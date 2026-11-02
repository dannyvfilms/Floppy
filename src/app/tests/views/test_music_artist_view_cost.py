"""Viewing an artist must not call MusicBrainz on every page load."""

from datetime import UTC, datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from app.models import (
    Album,
    AlbumArtist,
    Artist,
    Item,
    MediaTypes,
    Music,
    Sources,
    Status,
)


class ArtistViewProviderCostTests(TestCase):
    """Repeat views reuse the last MusicBrainz attempt instead of repeating it."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="artistview")
        cls.user.music_enabled = True
        cls.user.save()
        # An album MusicBrainz could not match keeps its MBIDs empty, which
        # used to force a full discography sync on every view.
        cls.artist = Artist.objects.create(name="Unmatched Artist")
        cls.album = Album.objects.create(title="Unmatched Album", artist=cls.artist)
        played_at = datetime(2026, 1, 15, 20, 0, tzinfo=UTC)
        for index in range(3):
            track = Item.objects.create(
                media_id=f"artist-view-track-{index}",
                source=Sources.MUSICBRAINZ.value,
                media_type=MediaTypes.MUSIC.value,
                title=f"Track {index}",
            )
            Music.objects.create(
                user=cls.user,
                item=track,
                artist=cls.artist,
                album=cls.album,
                status=Status.COMPLETED.value,
                start_date=played_at,
                end_date=played_at,
            )

    def setUp(self):
        cache.clear()
        self.client.force_login(self.user)

    def _view(self):
        return self.client.get(
            reverse("music_artist_details", args=[self.artist.id, "unmatched-artist"]),
        )

    @patch("app.services.music.resolve_artist_mbid", return_value=(None, 0, ""))
    def test_unmatched_artist_is_searched_once_per_day(self, mock_resolve):
        self.assertEqual(self._view().status_code, 200)
        self.assertEqual(self._view().status_code, 200)

        self.assertEqual(mock_resolve.call_count, 1)

    @patch("app.services.music.sync_artist_discography", return_value=0)
    def test_forced_sync_runs_once_across_repeat_views(self, mock_sync):
        Artist.objects.filter(pk=self.artist.pk).update(
            musicbrainz_id="11111111-2222-3333-4444-555555555555",
        )

        self.assertEqual(self._view().status_code, 200)
        self.assertEqual(self._view().status_code, 200)

        self.assertEqual(mock_sync.call_count, 1)


class ArtistCoverPollerCostTests(TestCase):
    """The cover poller stops on its own and reads play counts in one query."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="coverpoll")
        cls.artist = Artist.objects.create(name="Coverless Artist")
        # No image: the provider cannot find a cover, so it never arrives.
        cls.album = Album.objects.create(title="Coverless Album", artist=cls.artist)
        played_at = datetime(2026, 1, 15, 20, 0, tzinfo=UTC)
        for index in range(5):
            track = Item.objects.create(
                media_id=f"cover-poll-track-{index}",
                source=Sources.MUSICBRAINZ.value,
                media_type=MediaTypes.MUSIC.value,
                title=f"Track {index}",
            )
            Music.objects.create(
                user=cls.user,
                item=track,
                artist=cls.artist,
                album=cls.album,
                status=Status.COMPLETED.value,
                start_date=played_at,
                end_date=played_at,
            )

    def setUp(self):
        cache.clear()
        self.client.force_login(self.user)

    @patch("app.tasks.prefetch_album_covers_batch.delay")
    def test_polling_stops_after_the_attempt_cap(self, _mock_delay):
        url = reverse("prefetch_artist_covers", args=[self.artist.id])

        first = self.client.get(url).content.decode()
        last = self.client.get(url, {"attempt": 24}).content.decode()

        self.assertIn("every 5s", first)
        self.assertIn("?attempt=1", first)
        self.assertNotIn("every 5s", last)

    @patch("app.tasks.prefetch_album_covers_batch.delay")
    def test_play_counts_do_not_grow_queries_per_track(self, _mock_delay):
        url = reverse("prefetch_artist_covers", args=[self.artist.id])
        self.client.get(url)

        with CaptureQueriesContext(connection) as captured:
            self.client.get(url)

        history_reads = [
            query["sql"]
            for query in captured.captured_queries
            if "historicalmusic" in query["sql"].lower()
        ]
        self.assertEqual(len(history_reads), 1)


class ArtistViewAlbumScalingTests(TestCase):
    """The artist page checks albums for duplicates in one query, not one per album."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username="albumscale")
        self.user.music_enabled = True
        self.user.save()
        self.client.force_login(self.user)

    def _artist_with_albums(self, name, count):
        artist = Artist.objects.create(name=name)
        for index in range(count):
            Album.objects.create(
                title=f"{name} Album {index}",
                artist=artist,
                musicbrainz_release_group_id=f"00000000-0000-0000-0000-{artist.id:06d}{index:06d}",
            )
        return artist

    def _query_count(self, artist):
        url = reverse("music_artist_details", args=[artist.id, "artist"])
        self.client.get(url)
        with CaptureQueriesContext(connection) as captured:
            self.assertEqual(self.client.get(url).status_code, 200)
        return len(captured)

    @patch("app.services.music.resolve_artist_mbid", return_value=(None, 0, ""))
    def test_query_count_does_not_grow_with_discography_size(self, _mock_resolve):
        small = self._query_count(self._artist_with_albums("Small", 3))
        large = self._query_count(self._artist_with_albums("Large", 30))

        self.assertLessEqual(large, small + 2)

    @patch("app.services.music.resolve_artist_mbid", return_value=(None, 0, ""))
    def test_duplicate_album_rows_are_still_merged(self, _mock_resolve):
        artist = self._artist_with_albums("Dupes", 2)
        original = Album.objects.filter(artist=artist).first()
        other = Artist.objects.create(name="Other Credit")
        copy = Album.objects.create(
            title="Duplicate copy",
            artist=other,
            musicbrainz_release_group_id=original.musicbrainz_release_group_id,
        )
        AlbumArtist.objects.create(album=copy, artist=artist, position=0)

        url = reverse("music_artist_details", args=[artist.id, "dupes"])
        self.assertEqual(self.client.get(url).status_code, 200)

        remaining = Album.objects.filter(
            musicbrainz_release_group_id=original.musicbrainz_release_group_id,
        ).count()
        self.assertEqual(remaining, 1)
