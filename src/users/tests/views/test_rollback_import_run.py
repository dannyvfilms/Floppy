from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from app.models import Item, MediaTypes, Movie, Music, Sources, Status
from integrations.models import ImportRun


class RollbackImportRunTests(TestCase):
    """Tests for the rollback_import_run view."""

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

    def test_rollback_deletes_only_this_runs_rows(self):
        """Rollback removes rows tagged with this run, not other runs or manual rows."""
        run = ImportRun.objects.create(
            user=self.user, source="trakt", status=ImportRun.Status.COMPLETED
        )
        other_run = ImportRun.objects.create(
            user=self.user, source="trakt", status=ImportRun.Status.COMPLETED
        )
        movie_from_run = self._movie("run-movie", self.user, import_run=run)
        movie_from_other_run = self._movie(
            "other-run-movie", self.user, import_run=other_run
        )
        manual_movie = self._movie("manual-movie", self.user, import_run=None)

        response = self.client.post(
            reverse("rollback_import_run", args=[run.id]),
        )

        self.assertRedirects(response, reverse("import_data"))
        self.assertFalse(Movie.objects.filter(id=movie_from_run.id).exists())
        self.assertTrue(Movie.objects.filter(id=movie_from_other_run.id).exists())
        self.assertTrue(Movie.objects.filter(id=manual_movie.id).exists())

        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertIn("removed 1 item", str(messages[0]))

    def test_rollback_is_scoped_to_the_requesting_user(self):
        """A user cannot roll back another user's import run."""
        other_run = ImportRun.objects.create(
            user=self.other_user, source="trakt", status=ImportRun.Status.COMPLETED
        )
        other_movie = self._movie("other-user-movie", self.other_user, other_run)

        response = self.client.post(
            reverse("rollback_import_run", args=[other_run.id]),
        )

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Movie.objects.filter(id=other_movie.id).exists())

    def test_rollback_refuses_while_run_is_still_running(self):
        """A running import must be cancelled before it can be rolled back."""
        run = ImportRun.objects.create(
            user=self.user, source="trakt", status=ImportRun.Status.RUNNING
        )
        movie = self._movie("running-movie", self.user, import_run=run)

        response = self.client.post(
            reverse("rollback_import_run", args=[run.id]),
        )

        self.assertRedirects(response, reverse("import_data"))
        self.assertTrue(Movie.objects.filter(id=movie.id).exists())
        messages = list(get_messages(response.wsgi_request))
        self.assertIn("Cancel the import", str(messages[0]))

    def test_rollback_deletes_music_row_the_run_created(self):
        """A Music row with no history before this run's touch is deleted."""
        run = ImportRun.objects.create(
            user=self.user, source="lastfm", status=ImportRun.Status.COMPLETED
        )
        item = Item.objects.create(
            media_id="music-item-new",
            source=Sources.MUSICBRAINZ.value,
            media_type=MediaTypes.MUSIC.value,
            title="Some Track",
        )
        music = Music.objects.create(
            item=item,
            user=self.user,
            status=Status.COMPLETED.value,
            progress=1,
            import_run=run,
        )

        response = self.client.post(
            reverse("rollback_import_run", args=[run.id]),
        )

        self.assertRedirects(response, reverse("import_data"))
        self.assertFalse(Music.objects.filter(id=music.id).exists())
        messages = list(get_messages(response.wsgi_request))
        self.assertIn("removed 1 item", str(messages[0]))

    def test_rollback_reverts_music_row_the_run_only_incremented(self):
        """A pre-existing row the run only updated is reverted, not deleted."""
        item = Item.objects.create(
            media_id="music-item-existing",
            source=Sources.MUSICBRAINZ.value,
            media_type=MediaTypes.MUSIC.value,
            title="Some Track",
        )
        original_end_date = timezone.now() - timezone.timedelta(days=1)
        music = Music.objects.create(
            item=item,
            user=self.user,
            status=Status.COMPLETED.value,
            progress=1,
            end_date=original_end_date,
        )

        run = ImportRun.objects.create(
            user=self.user, source="lastfm", status=ImportRun.Status.COMPLETED
        )
        music.progress = 2
        music.end_date = timezone.now()
        music.import_run = run
        music.save()

        response = self.client.post(
            reverse("rollback_import_run", args=[run.id]),
        )

        self.assertRedirects(response, reverse("import_data"))
        music.refresh_from_db()
        self.assertEqual(music.progress, 1)
        self.assertEqual(music.end_date, original_end_date)
        self.assertIsNone(music.import_run_id)
        messages = list(get_messages(response.wsgi_request))
        self.assertIn("reverted 1 play", str(messages[0]))
