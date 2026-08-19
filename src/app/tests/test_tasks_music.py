from unittest.mock import patch

from django.conf import settings
from django.test import TestCase

from app.models import Artist
from app.tasks_music import prefetch_artist_images_batch


class PrefetchArtistImagesBatchTests(TestCase):
    @patch("app.providers.musicbrainz.get_artist")
    def test_backfills_wikipedia_image_when_no_album_art_available(
        self, mock_get_artist
    ):
        artist = Artist.objects.create(name="Kurt Cobain", musicbrainz_id="member-mbid")
        mock_get_artist.return_value = {"image": "http://example.com/wiki-photo.jpg"}

        result = prefetch_artist_images_batch([artist.id])

        artist.refresh_from_db()
        self.assertEqual(artist.image, "http://example.com/wiki-photo.jpg")
        self.assertEqual(result, {"artists": 1, "images_updated": 1})

    @patch("app.providers.musicbrainz.get_artist")
    def test_sets_img_none_sentinel_when_no_image_found_anywhere(self, mock_get_artist):
        artist = Artist.objects.create(
            name="Obscure Member", musicbrainz_id="member-mbid-2"
        )
        mock_get_artist.return_value = {"image": None}

        result = prefetch_artist_images_batch([artist.id])

        artist.refresh_from_db()
        self.assertEqual(artist.image, settings.IMG_NONE)
        self.assertEqual(result, {"artists": 1, "images_updated": 0})

    @patch("app.providers.musicbrainz.get_artist")
    def test_skips_artists_that_already_have_an_image(self, mock_get_artist):
        artist = Artist.objects.create(
            name="Already Has Photo",
            musicbrainz_id="member-mbid-3",
            image="http://example.com/existing.jpg",
        )

        prefetch_artist_images_batch([artist.id])

        artist.refresh_from_db()
        self.assertEqual(artist.image, "http://example.com/existing.jpg")
        mock_get_artist.assert_not_called()

    @patch("app.services.music.get_artist_hero_image")
    @patch("app.providers.musicbrainz.get_artist")
    def test_prefers_album_hero_image_over_wikipedia(
        self,
        mock_get_artist,
        mock_hero_image,
    ):
        artist = Artist.objects.create(
            name="Has Albums", musicbrainz_id="member-mbid-4"
        )
        mock_hero_image.return_value = "http://example.com/album-cover.jpg"

        result = prefetch_artist_images_batch([artist.id])

        artist.refresh_from_db()
        self.assertEqual(artist.image, "http://example.com/album-cover.jpg")
        self.assertEqual(result, {"artists": 1, "images_updated": 1})
        mock_get_artist.assert_not_called()

    def test_skips_missing_artist_ids_without_error(self):
        result = prefetch_artist_images_batch([999999])

        self.assertEqual(result, {"artists": 1, "images_updated": 0})
