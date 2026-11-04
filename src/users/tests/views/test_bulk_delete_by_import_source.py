from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from app.models import (
    Album,
    AlbumTracker,
    Artist,
    ArtistTracker,
    Item,
    MediaTypes,
    Movie,
    Music,
    Sources,
    Status,
)
from integrations.models import ImportRun


class BulkDeleteByImportSourceTests(TestCase):
    """Tests for the bulk_delete_by_import_source view."""

    def setUp(self):
        """Create user and test data for the tests."""
        self.credentials = {"username": "testuser", "password": "testpass123"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        self.other_credentials = {"username": "otheruser", "password": "testpass123"}
        self.other_user = get_user_model().objects.create_user(**self.other_credentials)

    def _finished_run(self, user, source):
        """An import run that has already finished.

        Deleting by source is refused while a run from it is still RUNNING,
        which is the ImportRun default -- these tests are about the
        after-the-import cleanup.
        """
        return ImportRun.objects.create(
            user=user,
            source=source,
            status=ImportRun.Status.COMPLETED,
        )

    def _movie(self, media_id, user, import_run=None):
        item = Item.objects.create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title=f"Movie {media_id}",
        )
        return Movie.objects.create(
            item=item,
            user=user,
            status=Status.COMPLETED.value,
            import_run=import_run,
        )

    def test_deletes_only_matching_media_type_and_source_for_this_user(self):
        """Delete is scoped to (user, media_type, import source)."""
        trakt_run = self._finished_run(self.user, "trakt")
        simkl_run = self._finished_run(self.user, "simkl")
        other_user_run = self._finished_run(self.other_user, "trakt")

        trakt_movie = self._movie("trakt-movie", self.user, trakt_run)
        simkl_movie = self._movie("simkl-movie", self.user, simkl_run)
        manual_movie = self._movie("manual-movie", self.user, None)
        other_user_movie = self._movie("other-user-movie", self.other_user, other_user_run)

        response = self.client.post(
            reverse(
                "bulk_delete_by_import_source",
                args=[MediaTypes.MOVIE.value, "trakt"],
            ),
        )

        self.assertRedirects(response, reverse("import_data"), fetch_redirect_response=False)
        self.assertFalse(Movie.objects.filter(id=trakt_movie.id).exists())
        self.assertTrue(Movie.objects.filter(id=simkl_movie.id).exists())
        self.assertTrue(Movie.objects.filter(id=manual_movie.id).exists())
        self.assertTrue(Movie.objects.filter(id=other_user_movie.id).exists())

        messages = list(get_messages(response.wsgi_request))
        self.assertIn("Permanently deleted 1 item", str(messages[0]))

    def test_rejects_unknown_media_type(self):
        """An invalid media_type is refused, not passed to apps.get_model."""
        self._finished_run(self.user, "trakt")

        response = self.client.post(
            reverse("bulk_delete_by_import_source", args=["not-a-real-type", "trakt"]),
        )

        self.assertRedirects(response, reverse("import_data"), fetch_redirect_response=False)
        messages = list(get_messages(response.wsgi_request))
        self.assertIn("Unknown media type", str(messages[0]))

    def test_rejects_source_the_user_has_no_import_run_for(self):
        """A source string with no ImportRun for this user is refused."""
        movie = self._movie("untouched-movie", self.user, None)

        response = self.client.post(
            reverse(
                "bulk_delete_by_import_source",
                args=[MediaTypes.MOVIE.value, "not-a-real-source"],
            ),
        )

        self.assertRedirects(response, reverse("import_data"), fetch_redirect_response=False)
        self.assertTrue(Movie.objects.filter(id=movie.id).exists())
        messages = list(get_messages(response.wsgi_request))
        self.assertIn("Unknown import source", str(messages[0]))

    def test_deletes_music_rows_for_source(self):
        """Unlike rollback, bulk delete can remove Music rows outright."""
        run = self._finished_run(self.user, "lastfm")
        item = Item.objects.create(
            media_id="music-item",
            source=Sources.MUSICBRAINZ.value,
            media_type=MediaTypes.MUSIC.value,
            title="Some Track",
        )
        music = Music.objects.create(
            item=item, user=self.user, status=Status.COMPLETED.value, import_run=run
        )

        response = self.client.post(
            reverse(
                "bulk_delete_by_import_source",
                args=[MediaTypes.MUSIC.value, "lastfm"],
            ),
        )

        self.assertRedirects(response, reverse("import_data"), fetch_redirect_response=False)
        self.assertFalse(Music.objects.filter(id=music.id).exists())

    def _music(self, media_id, user, import_run, artist=None, album=None):
        """Create one tracked Music row backed by its own Item."""
        item = Item.objects.create(
            media_id=media_id,
            source=Sources.MUSICBRAINZ.value,
            media_type=MediaTypes.MUSIC.value,
            title=f"Track {media_id}",
        )
        return Music.objects.create(
            item=item,
            user=user,
            status=Status.COMPLETED.value,
            import_run=import_run,
            artist=artist,
            album=album,
        )

    def test_deleting_music_for_source_sweeps_the_trackers_it_stranded(self):
        """Artists/albums left with no tracks leave the user's library too.

        The trackers carry no import_run of their own, so without this sweep a
        "delete all Last.fm music" left /medialist/music looking untouched.
        """
        run = self._finished_run(self.user, "lastfm")
        artist = Artist.objects.create(name="Last.fm Artist")
        album = Album.objects.create(title="Last.fm Album", artist=artist)
        artist_tracker = ArtistTracker.objects.create(user=self.user, artist=artist)
        album_tracker = AlbumTracker.objects.create(user=self.user, album=album)
        music = self._music("lastfm-track", self.user, run, artist, album)

        response = self.client.post(
            reverse(
                "bulk_delete_by_import_source",
                args=[MediaTypes.MUSIC.value, "lastfm"],
            ),
        )

        self.assertRedirects(response, reverse("import_data"), fetch_redirect_response=False)
        self.assertFalse(Music.objects.filter(id=music.id).exists())
        self.assertFalse(ArtistTracker.objects.filter(id=artist_tracker.id).exists())
        self.assertFalse(AlbumTracker.objects.filter(id=album_tracker.id).exists())

    def test_music_tracker_survives_when_another_source_still_has_tracks(self):
        """An artist with tracks left from another source keeps its tracker."""
        lastfm_run = self._finished_run(self.user, "lastfm")
        koito_run = self._finished_run(self.user, "koito")
        artist = Artist.objects.create(name="Shared Artist")
        album = Album.objects.create(title="Shared Album", artist=artist)
        artist_tracker = ArtistTracker.objects.create(user=self.user, artist=artist)
        album_tracker = AlbumTracker.objects.create(user=self.user, album=album)
        lastfm_music = self._music("lastfm-dupe", self.user, lastfm_run, artist, album)
        koito_music = self._music("koito-track", self.user, koito_run, artist, album)

        response = self.client.post(
            reverse(
                "bulk_delete_by_import_source",
                args=[MediaTypes.MUSIC.value, "lastfm"],
            ),
        )

        self.assertRedirects(response, reverse("import_data"), fetch_redirect_response=False)
        self.assertFalse(Music.objects.filter(id=lastfm_music.id).exists())
        self.assertTrue(Music.objects.filter(id=koito_music.id).exists())
        self.assertTrue(ArtistTracker.objects.filter(id=artist_tracker.id).exists())
        self.assertTrue(AlbumTracker.objects.filter(id=album_tracker.id).exists())

    def test_music_delete_leaves_unrelated_and_other_user_trackers_alone(self):
        """Only artists/albums the deleted rows referenced are considered."""
        run = self._finished_run(self.user, "lastfm")
        imported_artist = Artist.objects.create(name="Imported Artist")
        followed_artist = Artist.objects.create(name="Hand-followed Artist")
        ArtistTracker.objects.create(user=self.user, artist=imported_artist)
        hand_followed = ArtistTracker.objects.create(
            user=self.user,
            artist=followed_artist,
        )
        other_user_tracker = ArtistTracker.objects.create(
            user=self.other_user,
            artist=imported_artist,
        )
        self._music("lastfm-only", self.user, run, imported_artist, None)

        response = self.client.post(
            reverse(
                "bulk_delete_by_import_source",
                args=[MediaTypes.MUSIC.value, "lastfm"],
            ),
        )

        self.assertRedirects(response, reverse("import_data"), fetch_redirect_response=False)
        self.assertFalse(
            ArtistTracker.objects.filter(
                user=self.user,
                artist=imported_artist,
            ).exists(),
        )
        self.assertTrue(ArtistTracker.objects.filter(id=hand_followed.id).exists())
        self.assertTrue(ArtistTracker.objects.filter(id=other_user_tracker.id).exists())

    def test_music_tracker_sweep_spans_id_lookup_chunks(self):
        """The sweep still deletes every tracker when ids span several chunks."""
        run = self._finished_run(self.user, "lastfm")
        artists = [Artist.objects.create(name=f"Artist {i}") for i in range(5)]
        for index, artist in enumerate(artists):
            ArtistTracker.objects.create(user=self.user, artist=artist)
            self._music(f"chunked-{index}", self.user, run, artist, None)

        with mock.patch("users.views._ID_LOOKUP_CHUNK", 2):
            response = self.client.post(
                reverse(
                    "bulk_delete_by_import_source",
                    args=[MediaTypes.MUSIC.value, "lastfm"],
                ),
            )

        self.assertRedirects(response, reverse("import_data"), fetch_redirect_response=False)
        self.assertFalse(ArtistTracker.objects.filter(user=self.user).exists())

    def test_music_sweep_reaches_artists_only_linked_through_the_album(self):
        """Music.artist is nullable and derivable from the album.

        A row with no direct artist FK still implies its album's artist, so
        deleting it must sweep that artist's tracker too.
        """
        run = self._finished_run(self.user, "lastfm")
        artist = Artist.objects.create(name="Album-only Artist")
        album = Album.objects.create(title="Album-only LP", artist=artist)
        artist_tracker = ArtistTracker.objects.create(user=self.user, artist=artist)
        album_tracker = AlbumTracker.objects.create(user=self.user, album=album)
        # artist=None: the link exists only through album.artist.
        self._music("album-linked", self.user, run, None, album)

        response = self.client.post(
            reverse(
                "bulk_delete_by_import_source",
                args=[MediaTypes.MUSIC.value, "lastfm"],
            ),
        )

        self.assertRedirects(response, reverse("import_data"), fetch_redirect_response=False)
        self.assertFalse(AlbumTracker.objects.filter(id=album_tracker.id).exists())
        self.assertFalse(ArtistTracker.objects.filter(id=artist_tracker.id).exists())

    def test_refuses_while_an_import_from_that_source_is_running(self):
        """A running import keeps writing rows, so deleting underneath it is refused.

        The importer re-creates trackers as it goes, so a delete that races it
        can strip the tracker off a row the importer is about to write --
        recreating the very orphan state this endpoint exists to clear.
        """
        run = ImportRun.objects.create(
            user=self.user,
            source="lastfm",
            status=ImportRun.Status.RUNNING,
        )
        artist = Artist.objects.create(name="Mid-import Artist")
        tracker = ArtistTracker.objects.create(user=self.user, artist=artist)
        music = self._music("mid-import", self.user, run, artist, None)

        response = self.client.post(
            reverse(
                "bulk_delete_by_import_source",
                args=[MediaTypes.MUSIC.value, "lastfm"],
            ),
        )

        self.assertRedirects(response, reverse("import_data"), fetch_redirect_response=False)
        self.assertTrue(Music.objects.filter(id=music.id).exists())
        self.assertTrue(ArtistTracker.objects.filter(id=tracker.id).exists())
        message = str(next(iter(get_messages(response.wsgi_request))))
        self.assertIn("Cancel the running import", message)
