import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, tag
from django.urls import reverse

from app.models import (
    TV,
    Episode,
    Movie,
    Season,
    Status,
)


class StremioAddonViewTests(TestCase):
    """Tests for the Stremio scrobbler addon endpoints."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.credentials = {"username": "testuser", "token": "test-token"}
        self.user = get_user_model().objects.create_superuser(**self.credentials)
        cache.clear()

    def _subtitles_url(self, media_type, media_id, token="test-token"):  # noqa: S107
        return f"/stremio-addon/{token}/subtitles/{media_type}/{media_id}.json"

    def test_manifest(self):
        """The manifest is served with CORS headers."""
        url = reverse("stremio_addon_manifest", kwargs={"token": "test-token"})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")
        manifest = json.loads(response.content)
        self.assertEqual(manifest["id"], "org.yamtrack.scrobbler")
        self.assertEqual(manifest["resources"], ["subtitles"])
        self.assertEqual(manifest["idPrefixes"], ["tt"])

    def test_manifest_invalid_token(self):
        """An unknown token returns 401."""
        url = reverse("stremio_addon_manifest", kwargs={"token": "bad-token"})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 401)

    def test_subtitles_invalid_token(self):
        """An unknown token returns 401 on the subtitles resource."""
        response = self.client.get(
            self._subtitles_url("movie", "tt0133093", token="bad-token"),
        )

        self.assertEqual(response.status_code, 401)

    @patch("integrations.views.tasks.process_webhook.delay")
    def test_subtitles_enqueues_scrobble(self, mock_delay):
        """A subtitles request records one scrobble per throttle window."""
        response = self.client.get(self._subtitles_url("movie", "tt0133093"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")
        self.assertEqual(json.loads(response.content), {"subtitles": []})
        mock_delay.assert_called_once_with(
            "stremio",
            {"id": "tt0133093", "type": "movie"},
            self.user.id,
        )

        # Repeat requests (seeks, quality changes) are throttled.
        self.client.get(self._subtitles_url("movie", "tt0133093"))
        self.assertEqual(mock_delay.call_count, 1)

        # A different item scrobbles immediately.
        self.client.get(self._subtitles_url("series", "tt0108778:1:1"))
        self.assertEqual(mock_delay.call_count, 2)

    @patch("integrations.views.tasks.process_webhook.delay")
    def test_subtitles_with_extra_path(self, mock_delay):
        """Stremio extra segments like videoHash are accepted and ignored."""
        response = self.client.get(
            "/stremio-addon/test-token/subtitles/series/"
            "tt0108778%3A1%3A1/videoHash=abcd1234.json",
        )

        self.assertEqual(response.status_code, 200)
        mock_delay.assert_called_once_with(
            "stremio",
            {"id": "tt0108778:1:1", "type": "series"},
            self.user.id,
        )


class StremioWebhookProcessorTests(TestCase):
    """Tests for the Stremio scrobble processor via the addon endpoint."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.credentials = {"username": "testuser", "token": "test-token"}
        self.user = get_user_model().objects.create_superuser(**self.credentials)
        cache.clear()

    def _get(self, media_type, media_id):
        return self.client.get(
            f"/stremio-addon/test-token/subtitles/{media_type}/{media_id}.json",
        )

    @tag("network")
    def test_movie_start_marks_in_progress(self):
        """A movie playback start marks the movie in progress."""
        response = self._get("movie", "tt0133093")

        self.assertEqual(response.status_code, 200)
        movie = Movie.objects.get(item__media_id="603", user=self.user)
        self.assertEqual(movie.status, Status.IN_PROGRESS.value)
        self.assertEqual(movie.progress, 0)

    @tag("network")
    def test_episode_start_marks_show_in_progress(self):
        """An episode playback start marks the show and season in progress."""
        response = self._get("series", "tt0108778:1:1")

        self.assertEqual(response.status_code, 200)

        tv = TV.objects.get(item__media_id="1668", user=self.user)
        self.assertEqual(tv.status, Status.IN_PROGRESS.value)

        season = Season.objects.get(
            item__media_id="1668",
            item__season_number=1,
        )
        self.assertEqual(season.status, Status.IN_PROGRESS.value)

        # Start-only signal: no completed episode record is created.
        self.assertFalse(
            Episode.objects.filter(item__media_id="1668").exists(),
        )

    def test_unsupported_id_is_ignored(self):
        """Non-IMDB ids are ignored without creating media."""
        response = self._get("movie", "yt%3Aabc123")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Movie.objects.filter(user=self.user).exists())

    @tag("network")
    @patch("integrations.webhooks.stremio.live_playback.apply_playback_event")
    def test_movie_start_updates_live_playback(self, mock_apply_event):
        """A movie playback start updates the Now Playing card."""
        response = self._get("movie", "tt0133093")

        self.assertEqual(response.status_code, 200)
        mock_apply_event.assert_called_once()
        _, kwargs = mock_apply_event.call_args
        self.assertEqual(kwargs["user_id"], self.user.id)
        self.assertEqual(kwargs["event_type"], "media.play")
        self.assertEqual(kwargs["playback_media_type"], "movie")
        self.assertEqual(kwargs["media_id"], "603")
        self.assertEqual(kwargs["title"], "The Matrix")

    @tag("network")
    @patch("integrations.webhooks.stremio.live_playback.apply_playback_event")
    def test_episode_start_updates_live_playback(self, mock_apply_event):
        """An episode playback start updates the Now Playing card."""
        response = self._get("series", "tt0108778:1:1")

        self.assertEqual(response.status_code, 200)
        mock_apply_event.assert_called_once()
        _, kwargs = mock_apply_event.call_args
        self.assertEqual(kwargs["user_id"], self.user.id)
        self.assertEqual(kwargs["event_type"], "media.play")
        self.assertEqual(kwargs["playback_media_type"], "episode")
        self.assertEqual(kwargs["media_id"], "1668")
        self.assertEqual(kwargs["series_title"], "Friends")
        self.assertEqual(kwargs["season_number"], 1)
        self.assertEqual(kwargs["episode_number"], 1)

    @patch("integrations.webhooks.stremio.live_playback.apply_playback_event")
    def test_unsupported_id_skips_live_playback(self, mock_apply_event):
        """Non-IMDB ids never reach the live playback update."""
        response = self._get("movie", "yt%3Aabc123")

        self.assertEqual(response.status_code, 200)
        mock_apply_event.assert_not_called()
