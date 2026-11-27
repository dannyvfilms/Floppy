from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from app.models import (
    TV,
    Episode,
    Item,
    MediaTypes,
    Movie,
    Music,
    Season,
    Sources,
    Status,
)
from integrations.models import ImportRun, NetflixPendingRow


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

        self.assertRedirects(response, reverse("import_data"), fetch_redirect_response=False)
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

    def test_rollback_requires_post_and_csrf(self):
        run = ImportRun.objects.create(
            user=self.user, source="trakt", status=ImportRun.Status.COMPLETED
        )
        movie = self._movie("csrf-protected-movie", self.user, run)
        url = reverse("rollback_import_run", args=[run.id])

        self.assertEqual(self.client.get(url).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        response = csrf_client.post(url, HTTP_REFERER=reverse("import_data"))
        self.assertRedirects(
            response, reverse("import_data"), fetch_redirect_response=False
        )
        self.assertIn(
            "quick refresh", str(next(iter(get_messages(response.wsgi_request))))
        )
        self.assertTrue(Movie.objects.filter(pk=movie.pk).exists())

    def test_rollback_refuses_while_run_is_still_running(self):
        """A running import must be cancelled before it can be rolled back."""
        run = ImportRun.objects.create(
            user=self.user, source="trakt", status=ImportRun.Status.RUNNING
        )
        movie = self._movie("running-movie", self.user, import_run=run)

        response = self.client.post(
            reverse("rollback_import_run", args=[run.id]),
        )

        self.assertRedirects(response, reverse("import_data"), fetch_redirect_response=False)
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

        self.assertRedirects(response, reverse("import_data"), fetch_redirect_response=False)
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

        self.assertRedirects(response, reverse("import_data"), fetch_redirect_response=False)
        music.refresh_from_db()
        self.assertEqual(music.progress, 1)
        self.assertEqual(music.end_date, original_end_date)
        self.assertIsNone(music.import_run_id)
        messages = list(get_messages(response.wsgi_request))
        self.assertIn("reverted 1 play", str(messages[0]))

    def _show_with_episode(self, media_id, user, import_run=None, episode_run=None):
        """A show, its season, and one episode play (provenance per argument)."""
        item = Item.objects.create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title=f"Show {media_id}",
        )
        tv = TV.objects.create(
            item=item,
            user=user,
            status=Status.IN_PROGRESS.value,
            import_run=import_run,
        )
        season_item = Item.objects.create(
            media_id=f"{media_id}-s1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title=f"Show {media_id} Season 1",
        )
        season = Season.objects.create(
            item=season_item,
            user=user,
            related_tv=tv,
            status=Status.IN_PROGRESS.value,
            import_run=import_run,
        )
        episode_item = Item.objects.create(
            media_id=f"{media_id}-e1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title=f"Show {media_id} Episode 1",
        )
        return Episode.objects.create(
            item=episode_item,
            related_season=season,
            import_run=episode_run if episode_run is not None else import_run,
        )

    def test_rollback_netflix_removes_plays_under_preexisting_shows(self):
        """Episode plays and pending rows belong to the run even when the
        show itself predates it.
        """
        run = ImportRun.objects.create(
            user=self.user, source="netflix", status=ImportRun.Status.COMPLETED
        )
        movie = self._movie("netflix-movie", self.user, import_run=run)
        show = self._show_with_episode(
            "preexisting-show", self.user, import_run=None, episode_run=run
        )
        pending = NetflixPendingRow.objects.create(
            user=self.user,
            title="Unresolved row",
            media_type="movie",
            import_run=run,
        )

        response = self.client.post(
            reverse("rollback_import_run", args=[run.id]),
        )

        self.assertRedirects(response, reverse("import_data"), fetch_redirect_response=False)
        self.assertFalse(Movie.objects.filter(id=movie.id).exists())
        self.assertFalse(Episode.objects.filter(id=show.id).exists())
        self.assertFalse(NetflixPendingRow.objects.filter(id=pending.id).exists())
        # The pre-existing show (and its season) stays.
        self.assertTrue(TV.objects.filter(item__media_id="preexisting-show").exists())
        messages = list(get_messages(response.wsgi_request))
        self.assertIn("removed 1 item", str(messages[0]))
        self.assertIn("removed 1 episode play", str(messages[0]))
        self.assertIn("removed 1 pending row", str(messages[0]))

    def test_rollback_netflix_cascades_the_show_the_run_created(self):
        """Undoing a run drops the shows it created, cascading to everything
        inside them (including later manual plays -- the same semantics the
        Trakt rollback has).
        """
        run = ImportRun.objects.create(
            user=self.user, source="netflix", status=ImportRun.Status.COMPLETED
        )
        show = self._show_with_episode(
            "run-created-show", self.user, import_run=run
        )
        manual_item = Item.objects.create(
            media_id="run-created-show-e2",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=2,
            title="Show run-created-show Episode 2",
        )
        manual_episode = Episode.objects.create(
            item=manual_item, related_season=show.related_season
        )

        response = self.client.post(
            reverse("rollback_import_run", args=[run.id]),
        )

        self.assertRedirects(response, reverse("import_data"), fetch_redirect_response=False)
        self.assertFalse(TV.objects.filter(item__media_id="run-created-show").exists())
        self.assertFalse(Episode.objects.filter(id=show.id).exists())
        self.assertFalse(Episode.objects.filter(id=manual_episode.id).exists())

    def test_rollback_of_other_sources_keeps_episode_plays(self):
        """The episode-play undo is Netflix-specific; other sources keep
        today's behaviour (history rows are not deleted by run).
        """
        run = ImportRun.objects.create(
            user=self.user, source="trakt", status=ImportRun.Status.COMPLETED
        )
        show = self._show_with_episode(
            "trakt-show", self.user, import_run=None, episode_run=run
        )

        self.client.post(reverse("rollback_import_run", args=[run.id]))

        self.assertTrue(Episode.objects.filter(id=show.id).exists())
