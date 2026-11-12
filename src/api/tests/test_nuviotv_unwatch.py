"""What Floppy does when a client retracts a Mark Watched (#1671).

Arc's Mark as Unwatched used to be a local-only change because Floppy's client
guide said no unmark was sent. That left the title in Floppy's history. The
`unwatch` action closes that gap: it retracts the watch the client added and
clears the saved resume point, without deleting the user's other plays.
"""

from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch

from django.core.cache import cache

from app.models import (
    Episode,
    Movie,
    PlaybackProgress,
    Status,
)
from integrations.models import IntegrationToken
from integrations.webhooks.generic_scrobble import GenericScrobbleProcessor

from .base import FloppyApiTestCase

SCROBBLE = "/api/v1/scrobble/"
HISTORY = "/api/v1/history/"

MATRIX = {
    "title": "The Matrix",
    "image": "https://example.com/matrix.jpg",
    "max_progress": 1,
    "provider_external_ids": {},
}
FRIENDS = {
    "media_id": "1668",
    "title": "Friends",
    "image": "https://example.com/friends.jpg",
    "tvdb_id": "79175",
    "provider_external_ids": {"tmdb_id": "1668", "tvdb_id": "79175"},
    "season/1": {
        "season_number": 1,
        "image": "https://example.com/friends-s1.jpg",
        "episodes": [
            {
                "episode_number": 1,
                "runtime": 22,
                "air_date": None,
                "still_path": None,
                "name": "The Pilot",
                "overview": "",
            },
            {"episode_number": 2},
        ],
    },
}

MOVIE_MARK = {
    "action": "stop",
    "media_type": "movie",
    "ids": {"imdb": "tt0133093", "tmdb": "603"},
    "title": "The Matrix",
    "completed": True,
    "manual": True,
}
MOVIE_UNWATCH = {
    "action": "unwatch",
    "media_type": "movie",
    "ids": {"imdb": "tt0133093", "tmdb": "603"},
}
EPISODE_MARK = {
    "action": "stop",
    "media_type": "episode",
    "ids": {"tmdb": "1668"},
    "series_title": "Friends",
    "title": "The Pilot",
    "season_number": 1,
    "episode_number": 1,
    "completed": True,
    "manual": True,
}
EPISODE_UNWATCH = {
    "action": "unwatch",
    "media_type": "episode",
    "ids": {"tmdb": "1668"},
    "season_number": 1,
    "episode_number": 1,
}


@patch("app.live_playback._attach_resolved_image")
@patch("app.providers.tmdb.movie", return_value=MATRIX)
@patch.object(
    GenericScrobbleProcessor,
    "_find_tv_media_id",
    return_value=("1668", None, None),
)
@patch("app.providers.tmdb.get_tvdb_episode_image_map", return_value={})
@patch("app.providers.tmdb.tv_with_seasons", return_value=FRIENDS)
class UnwatchTests(FloppyApiTestCase):
    """Unwatch retracts a watch and clears its resume point."""

    def setUp(self):
        """Mint the default-preset token a user pastes into NuvioTV."""
        super().setUp()
        self.user1.anime_enabled = False
        self.user1.save(update_fields=["anime_enabled"])
        _, secret = IntegrationToken.generate(user=self.user1, name="NuvioTV")
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {secret}"}

    def _send(self, payload):
        return self.client.post(SCROBBLE, payload, format="json", **self.headers)

    def _movies(self):
        return Movie.objects.filter(user=self.user1, item__media_id="603")

    def _episodes(self):
        return Episode.objects.filter(
            item__media_id="1668",
            item__season_number=1,
            item__episode_number=1,
            related_season__user=self.user1,
        )

    def test_unwatching_a_manually_marked_movie_removes_it_from_history(self, *_mocks):
        """The mark becomes a play; unwatch reverts it so history drops the row."""
        self._send(MOVIE_MARK)
        self.assertEqual(self._movies().get().status, Status.COMPLETED.value)

        response = self._send(MOVIE_UNWATCH)

        self.assertEqual(response.status_code, HTTP.OK)
        movie = self._movies().get()
        self.assertEqual(movie.status, Status.IN_PROGRESS.value)
        self.assertIsNone(movie.end_date)
        cache.clear()
        history = self.client.get(f"{HISTORY}?flat=1", **self.headers)
        self.assertEqual(history.status_code, HTTP.OK)
        self.assertFalse(
            any(
                entry.get("item", {}).get("media_id") == "603"
                for entry in history.json()["results"]
            ),
        )

    def test_unwatching_a_manually_marked_episode_removes_the_play(self, *_mocks):
        """An episode play is one row, so unwatch deletes exactly that watch."""
        self._send(EPISODE_MARK)
        self.assertEqual(self._episodes().count(), 1)

        response = self._send(EPISODE_UNWATCH)

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertFalse(self._episodes().exists())

    def test_unwatch_clears_the_saved_resume_point(self, *_mocks):
        """A resume position must not survive Mark as Unwatched."""
        self._send(
            {
                **MOVIE_MARK,
                "completed": False,
                "manual": False,
                "position_seconds": 1200,
                "duration_seconds": 8160,
            },
        )
        self.assertTrue(
            PlaybackProgress.objects.filter(
                user=self.user1,
                item__media_id="603",
            ).exists(),
        )

        response = self._send(MOVIE_UNWATCH)

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertFalse(
            PlaybackProgress.objects.filter(
                user=self.user1,
                item__media_id="603",
            ).exists(),
        )

    def test_unwatching_an_untracked_title_is_a_no_op(self, *_mocks):
        """Unmarking something already unmarked is the same outcome, not a 404."""
        response = self._send(MOVIE_UNWATCH)

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertFalse(self._movies().exists())
