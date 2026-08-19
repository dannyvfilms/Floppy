from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from app.models import Item, MediaTypes, Movie, Music, Sources, Status
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
        trakt_run = ImportRun.objects.create(user=self.user, source="trakt")
        simkl_run = ImportRun.objects.create(user=self.user, source="simkl")
        other_user_run = ImportRun.objects.create(user=self.other_user, source="trakt")

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

        self.assertRedirects(response, reverse("import_data"))
        self.assertFalse(Movie.objects.filter(id=trakt_movie.id).exists())
        self.assertTrue(Movie.objects.filter(id=simkl_movie.id).exists())
        self.assertTrue(Movie.objects.filter(id=manual_movie.id).exists())
        self.assertTrue(Movie.objects.filter(id=other_user_movie.id).exists())

        messages = list(get_messages(response.wsgi_request))
        self.assertIn("Permanently deleted 1 item", str(messages[0]))

    def test_rejects_unknown_media_type(self):
        """An invalid media_type is refused, not passed to apps.get_model."""
        ImportRun.objects.create(user=self.user, source="trakt")

        response = self.client.post(
            reverse("bulk_delete_by_import_source", args=["not-a-real-type", "trakt"]),
        )

        self.assertRedirects(response, reverse("import_data"))
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

        self.assertRedirects(response, reverse("import_data"))
        self.assertTrue(Movie.objects.filter(id=movie.id).exists())
        messages = list(get_messages(response.wsgi_request))
        self.assertIn("Unknown import source", str(messages[0]))

    def test_deletes_music_rows_for_source(self):
        """Unlike rollback, bulk delete can remove Music rows outright."""
        run = ImportRun.objects.create(user=self.user, source="lastfm")
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

        self.assertRedirects(response, reverse("import_data"))
        self.assertFalse(Music.objects.filter(id=music.id).exists())
