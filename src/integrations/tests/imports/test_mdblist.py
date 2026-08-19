from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django_celery_beat.models import PeriodicTask

from app.models import (
    TV,
    CollectionEntry,
    Episode,
    Item,
    MediaTypes,
    Movie,
    Season,
    Sources,
    Status,
)
from integrations import tasks
from integrations.imports import helpers
from integrations.imports.mdblist import importer
from integrations.models import MDBListAccount


def _metadata_side_effect(media_type, _, __, ___=None):
    if media_type == MediaTypes.TV.value:
        return {
            "title": "Test Show",
            "image": "tv_image.jpg",
            "last_episode_season": 1,
            "max_progress": 1,
        }
    if media_type == MediaTypes.SEASON.value:
        return {
            "title": "Season 1",
            "image": "season_image.jpg",
            "episodes": [
                {"episode_number": 1, "still_path": "/still.jpg"},
                {"episode_number": 2, "still_path": None},
            ],
            "max_progress": 2,
        }
    return {"title": "Test Media", "image": "image.jpg"}


def _empty_sync_response():
    return {"pagination": {"next_cursor": None}}


class ImportMDBList(TestCase):
    """Test importing tracking data from MDBList."""

    def setUp(self):
        """Create user for the tests."""
        credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**credentials)

    def _run_import(self, responses, mode="new"):
        """Run a full import with per-path canned responses."""

        def request_side_effect(_api_key, path, params=None):
            return responses.get(path, _empty_sync_response())

        with (
            patch(
                "integrations.imports.mdblist.request",
                side_effect=request_side_effect,
            ),
            patch(
                "integrations.imports.mdblist.MDBListImporter._get_metadata",
                side_effect=_metadata_side_effect,
            ),
        ):
            return importer("key", self.user, mode)

    def test_full_import(self):
        """A full import maps every category to the right models."""
        responses = {
            "/sync/dropped": {
                "shows": [
                    {
                        "dropped_at": "2023-03-01T00:00:00Z",
                        "show": {"title": "Dropped Show", "ids": {"tmdb": 555}},
                    },
                ],
            },
            "/sync/watched": {
                "movies": [
                    {
                        "watched_at": "2023-01-02T00:00:00Z",
                        "movie": {"title": "Test Movie", "ids": {"tmdb": 67890}},
                    },
                ],
                "episodes": [
                    {
                        "watched_at": "2023-01-01T00:00:00Z",
                        "episode": {
                            "season": 1,
                            "number": 1,
                            "show": {"title": "Test Show", "ids": {"tmdb": 12345}},
                        },
                    },
                ],
                "shows": [
                    {
                        "watched_at": "2023-02-01T00:00:00Z",
                        "show": {"title": "Whole Show", "ids": {"tmdb": 777}},
                    },
                ],
            },
            "/watchlist/items": [
                {"title": "WL Movie", "mediatype": "movie", "ids": {"tmdb": 999}},
            ],
            "/sync/ratings": {
                "movies": [
                    {
                        "rated_at": "2023-01-03T00:00:00Z",
                        "rating": 8,
                        "movie": {"title": "Test Movie", "ids": {"tmdb": 67890}},
                    },
                ],
                "episodes": [
                    {
                        "rated_at": "2023-01-03T00:00:00Z",
                        "rating": 9,
                        "episode": {
                            "season": 1,
                            "number": 1,
                            "show": {"title": "Test Show", "ids": {"tmdb": 12345}},
                        },
                    },
                ],
            },
            "/sync/collection": {
                "movies": [
                    {
                        "collected_at": "2023-01-04T00:00:00Z",
                        "movie": {"title": "Test Movie", "ids": {"tmdb": 67890}},
                    },
                ],
            },
        }

        self._run_import(responses)

        movie = Movie.objects.get(item__media_id="67890", user=self.user)
        self.assertEqual(movie.status, Status.COMPLETED.value)
        self.assertEqual(movie.progress, 1)
        self.assertIsNotNone(movie.end_date)
        self.assertEqual(movie.score, 8)

        tv = TV.objects.get(item__media_id="12345", user=self.user)
        self.assertEqual(tv.status, Status.IN_PROGRESS.value)
        season = Season.objects.get(item__media_id="12345", user=self.user)
        episode = Episode.objects.get(item__media_id="12345")
        self.assertIsNotNone(episode.end_date)
        expected_score = self.user.scale_score_for_storage(Decimal(9))
        self.assertEqual(episode.score, expected_score)
        self.assertEqual(season.status, Status.IN_PROGRESS.value)

        whole_show = TV.objects.get(item__media_id="777", user=self.user)
        self.assertEqual(whole_show.status, Status.COMPLETED.value)

        watchlist_movie = Movie.objects.get(item__media_id="999", user=self.user)
        self.assertEqual(watchlist_movie.status, Status.PLANNING.value)

        collected = CollectionEntry.objects.get(
            user=self.user,
            item__media_id="67890",
        )
        self.assertIsNotNone(collected.collected_at)

    def test_season_completion_rollup(self):
        """Watching the last episode completes the season and show."""
        responses = {
            "/sync/watched": {
                "episodes": [
                    {
                        "watched_at": "2023-01-01T00:00:00Z",
                        "episode": {
                            "season": 1,
                            "number": number,
                            "show": {"title": "Test Show", "ids": {"tmdb": 12345}},
                        },
                    }
                    for number in (1, 2)
                ],
            },
        }
        self._run_import(responses)

        season = Season.objects.get(item__media_id="12345", user=self.user)
        tv = TV.objects.get(item__media_id="12345", user=self.user)
        self.assertEqual(season.status, Status.COMPLETED.value)
        self.assertEqual(tv.status, Status.COMPLETED.value)

    def test_watched_season_expands_to_episodes(self):
        """A season marked watched creates all of its episodes."""
        responses = {
            "/sync/watched": {
                "seasons": [
                    {
                        "watched_at": "2023-01-01T00:00:00Z",
                        "season": {
                            "number": 1,
                            "show": {"title": "Test Show", "ids": {"tmdb": 12345}},
                        },
                    },
                ],
            },
        }
        self._run_import(responses)

        self.assertEqual(Episode.objects.filter(item__media_id="12345").count(), 2)
        season = Season.objects.get(item__media_id="12345", user=self.user)
        self.assertEqual(season.status, Status.COMPLETED.value)

    def test_season_rating_backfills_episodes(self):
        """Rating a season with no watch history still creates its episodes.

        A season rating with no accompanying watched entry is built as a
        COMPLETED Season via bulk_create, which bypasses Season.save()'s
        normal episode-completion fan-out (see issue #369: exports/stats
        were missing episodes for seasons completed this way).
        """
        responses = {
            "/sync/ratings": {
                "seasons": [
                    {
                        "rated_at": "2023-01-03T00:00:00Z",
                        "rating": 7,
                        "season": {
                            "number": 1,
                            "show": {"title": "Test Show", "ids": {"tmdb": 12345}},
                        },
                    },
                ],
            },
        }
        season_metadata = {
            "title": "Season 1",
            "image": "season_image.jpg",
            "episodes": [
                {"episode_number": 1, "still_path": "/still.jpg"},
                {"episode_number": 2, "still_path": None},
            ],
            "max_progress": 2,
            "_tvdb_episode_image_map": {},
        }
        with patch(
            "app.providers.services.get_media_metadata",
            side_effect=lambda media_type, *_a, **_kw: (
                season_metadata if media_type == MediaTypes.SEASON.value else {}
            ),
        ):
            self._run_import(responses)

        season = Season.objects.get(item__media_id="12345", user=self.user)
        self.assertEqual(season.status, Status.COMPLETED.value)
        self.assertEqual(
            Episode.objects.filter(related_season=season).count(),
            2,
        )

    def test_dropped_show_marks_existing_tv(self):
        """Dropped shows set DROPPED on the TV row built during the import."""
        responses = {
            "/sync/dropped": {
                "shows": [
                    {"show": {"title": "Test Show", "ids": {"tmdb": 12345}}},
                ],
            },
            "/sync/watched": {
                "episodes": [
                    {
                        "watched_at": "2023-01-01T00:00:00Z",
                        "episode": {
                            "season": 1,
                            "number": 1,
                            "show": {"title": "Test Show", "ids": {"tmdb": 12345}},
                        },
                    },
                ],
            },
        }
        self._run_import(responses)

        tv = TV.objects.get(item__media_id="12345", user=self.user)
        self.assertEqual(tv.status, Status.DROPPED.value)

    def test_new_mode_rerun_does_not_duplicate(self):
        """Rerunning the same import in new mode creates no duplicates."""
        responses = {
            "/sync/watched": {
                "movies": [
                    {
                        "watched_at": "2023-01-02T00:00:00Z",
                        "movie": {"title": "Test Movie", "ids": {"tmdb": 67890}},
                    },
                ],
                "episodes": [
                    {
                        "watched_at": "2023-01-01T00:00:00Z",
                        "episode": {
                            "season": 1,
                            "number": 1,
                            "show": {"title": "Test Show", "ids": {"tmdb": 12345}},
                        },
                    },
                ],
            },
        }
        self._run_import(responses)
        self._run_import(responses)

        self.assertEqual(Movie.objects.filter(user=self.user).count(), 1)
        self.assertEqual(
            Episode.objects.filter(related_season__user=self.user).count(),
            1,
        )

    def test_overwrite_mode_replaces_existing(self):
        """Overwrite mode deletes preexisting media before importing."""
        item = Item.objects.get_or_create(
            media_id="67890",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={"title": "Test Movie"},
        )[0]
        Movie.objects.create(
            item=item,
            user=self.user,
            status=Status.PLANNING.value,
        )

        responses = {
            "/sync/watched": {
                "movies": [
                    {
                        "watched_at": "2023-01-02T00:00:00Z",
                        "movie": {"title": "Test Movie", "ids": {"tmdb": 67890}},
                    },
                ],
            },
        }
        self._run_import(responses, mode="overwrite")

        movie = Movie.objects.get(item__media_id="67890", user=self.user)
        self.assertEqual(movie.status, Status.COMPLETED.value)

    def test_cursor_pagination(self):
        """Sync pagination follows next_cursor until exhausted."""
        pages = [
            {
                "movies": [
                    {
                        "watched_at": "2023-01-02T00:00:00Z",
                        "movie": {"title": "Movie 1", "ids": {"tmdb": 1001}},
                    },
                ],
                "pagination": {"next_cursor": "abc"},
            },
            {
                "movies": [
                    {
                        "watched_at": "2023-01-03T00:00:00Z",
                        "movie": {"title": "Movie 2", "ids": {"tmdb": 1002}},
                    },
                ],
                "pagination": {"next_cursor": None},
            },
        ]
        calls = []

        def request_side_effect(_api_key, path, params=None):
            if path == "/sync/watched":
                calls.append(params)
                return pages[len(calls) - 1]
            return _empty_sync_response()

        with (
            patch(
                "integrations.imports.mdblist.request",
                side_effect=request_side_effect,
            ),
            patch(
                "integrations.imports.mdblist.MDBListImporter._get_metadata",
                side_effect=_metadata_side_effect,
            ),
        ):
            importer("key", self.user, "new")

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1].get("cursor"), "abc")
        self.assertEqual(Movie.objects.filter(user=self.user).count(), 2)

    def test_tmdb_fallback_via_imdb_id(self):
        """Entries without a TMDB id resolve through tmdb.find."""
        responses = {
            "/sync/watched": {
                "movies": [
                    {
                        "watched_at": "2023-01-02T00:00:00Z",
                        "movie": {"title": "IMDB Movie", "ids": {"imdb": "tt123"}},
                    },
                ],
            },
        }

        with patch(
            "integrations.imports.mdblist.tmdb.find",
            return_value={"movie_results": [{"id": 300}]},
        ) as mock_find:
            self._run_import(responses)

        mock_find.assert_called_once_with("tt123", "imdb_id")
        self.assertTrue(
            Movie.objects.filter(item__media_id="300", user=self.user).exists(),
        )

    def test_malformed_entry_is_skipped_with_warning(self):
        """A malformed entry produces a warning instead of aborting."""
        responses = {
            "/sync/watched": {
                "episodes": [
                    {"watched_at": "2023-01-01T00:00:00Z", "episode": {}},
                    {
                        "watched_at": "2023-01-02T00:00:00Z",
                        "episode": {
                            "season": 1,
                            "number": 1,
                            "show": {"title": "Test Show", "ids": {"tmdb": 12345}},
                        },
                    },
                ],
            },
        }
        _, warnings = self._run_import(responses)

        self.assertIn("skipped", warnings)
        self.assertEqual(
            Episode.objects.filter(related_season__user=self.user).count(),
            1,
        )


class ImportMDBListTask(TestCase):
    """Test the MDBList Celery task."""

    def setUp(self):
        """Create user for the tests."""
        credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**credentials)

    def test_task_requires_account(self):
        """The task fails cleanly without a connected account."""
        with self.assertRaises(helpers.MediaImportError):
            tasks.import_mdblist(self.user.id, "new")

    def test_task_decrypts_key_and_runs_import(self):
        """The task decrypts the stored key and runs the importer."""
        MDBListAccount.objects.create(
            user=self.user,
            api_key=helpers.encrypt("secret-key"),
        )
        with patch("integrations.imports.mdblist.importer") as mock_importer:
            mock_importer.return_value = ({}, "")
            tasks.import_mdblist(self.user.id, "new")

        self.assertEqual(mock_importer.call_args[0][0], "secret-key")


class ImportMDBListView(TestCase):
    """Test the MDBList import view."""

    def setUp(self):
        """Create and log in a user."""
        credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**credentials)
        self.client.login(**credentials)

    def _post(self, **extra):
        data = {"mode": "new", "frequency": "once", "time": "03:00", **extra}
        return self.client.post("/import/mdblist", data)

    def test_requires_key_when_unconnected(self):
        """Without a stored account, an API key is required."""
        with patch("integrations.tasks.import_mdblist.delay") as mock_delay:
            self._post()
        mock_delay.assert_not_called()

    def test_queues_task_with_connected_account(self):
        """A connected account queues the import without a key."""
        MDBListAccount.objects.create(
            user=self.user,
            api_key=helpers.encrypt("secret-key"),
        )
        with patch("integrations.tasks.import_mdblist.delay") as mock_delay:
            response = self._post()

        self.assertEqual(response.status_code, 302)
        mock_delay.assert_called_once_with(user_id=self.user.id, mode="new")

    def test_saves_key_and_schedules_recurring(self):
        """Providing a key stores an encrypted account and schedules imports."""
        with patch(
            "integrations.imports.mdblist.validate_api_key",
            return_value={"username": "mdb"},
        ):
            self._post(api_key="secret-key", frequency="daily")

        account = MDBListAccount.objects.get(user=self.user)
        self.assertEqual(helpers.decrypt(account.api_key), "secret-key")
        task = PeriodicTask.objects.get(task="Import from MDBList")
        self.assertIn(f'"user_id": {self.user.id}', task.kwargs)
        self.assertNotIn("secret-key", task.kwargs)
