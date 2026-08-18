from decimal import Decimal
from pathlib import Path
from unittest.mock import call, patch

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase
from requests import Response

from app.models import (
    TV,
    CollectionEntry,
    DeletedMedia,
    Episode,
    Item,
    MediaTypes,
    Movie,
    Season,
    Sources,
    Status,
)
from app.providers import services
from integrations.imports import helpers
from integrations.imports.helpers import MediaImportError
from integrations.imports.trakt import TraktImporter, importer

mock_path = Path(__file__).resolve().parent.parent / "mock_data"
app_mock_path = (
    Path(__file__).resolve().parent.parent.parent.parent / "app" / "tests" / "mock_data"
)


class ImportTrakt(TestCase):
    """Test importing media from Trakt."""

    def setUp(self):
        """Create user for the tests."""
        credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**credentials)

    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_process_watched_movie(self, mock_get_metadata):
        """Test processing a movie entry."""
        movie_entry = {
            "type": "movie",
            "movie": {"title": "Test Movie", "ids": {"tmdb": 67890}},
            "watched_at": "2023-01-02T00:00:00.000Z",
        }

        mock_get_metadata.return_value = {
            "title": "Test Movie",
            "image": "movie_image.jpg",
        }

        trakt_importer = TraktImporter("test", self.user, "new")
        trakt_importer.process_watched_movie(movie_entry)

        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.MOVIE.value]), 1)
        self.assertEqual(len(trakt_importer.media_instances[MediaTypes.MOVIE.value]), 1)

        # Verify progress is set to 1 for completed movies
        movie_obj = trakt_importer.bulk_media[MediaTypes.MOVIE.value][0]
        self.assertEqual(movie_obj.progress, 1)

        # Process the same movie again to test repeat handling
        trakt_importer.process_watched_movie(movie_entry)
        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.MOVIE.value]), 2)

    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_process_watched_episode(self, mock_get_metadata):
        """Test processing an episode entry."""
        episode_entry = {
            "type": "episode",
            "episode": {"season": 1, "number": 1, "title": "Pilot"},
            "show": {"title": "Test Show", "ids": {"tmdb": 12345}},
            "watched_at": "2023-01-01T00:00:00.000Z",
        }

        def mock_metadata_side_effect(media_type, _, __, ___=None):
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
                        {
                            "episode_number": 1,
                            "still_path": "/still.jpg",
                            "title": "Pilot Episode Title",
                        },
                    ],
                    "max_progress": 1,
                }
            return None

        mock_get_metadata.side_effect = mock_metadata_side_effect

        trakt_importer = TraktImporter("testuser", self.user, "new")
        trakt_importer.process_watched_episode(episode_entry)

        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.TV.value]), 1)
        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.SEASON.value]), 1)
        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.EPISODE.value]), 1)

        # A freshly-created show/season whose watch history already reaches
        # max_progress should still land as Completed.
        self.assertEqual(
            trakt_importer.bulk_media[MediaTypes.TV.value][0].status,
            Status.COMPLETED.value,
        )
        self.assertEqual(
            trakt_importer.bulk_media[MediaTypes.SEASON.value][0].status,
            Status.COMPLETED.value,
        )

        # Episode item should carry the episode's own title, not the show title.
        episode_item = trakt_importer.bulk_media[MediaTypes.EPISODE.value][0].item
        self.assertEqual(episode_item.title, "Pilot Episode Title")

        # Process a replay of the same episode at a different time.
        trakt_importer.process_watched_episode(
            {
                **episode_entry,
                "watched_at": "2023-01-02T00:00:00.000Z",
            },
        )
        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.EPISODE.value]), 2)

    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_process_watched_episode_existing_show_imports_new_episode(
        self,
        mock_get_metadata,
    ):
        """New-mode import should add episodes even when the show already exists."""
        tv_item = Item.objects.get_or_create(
            media_id="12345",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            defaults={"title": "Test Show"},
        )[0]
        tv_obj = TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        season_item = Item.objects.get_or_create(
            media_id="12345",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            defaults={"title": "Season 1"},
        )[0]
        season_obj = Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=tv_obj,
            status=Status.IN_PROGRESS.value,
        )

        episode_entry = {
            "type": "episode",
            "episode": {"season": 1, "number": 2, "title": "Episode 2"},
            "show": {"title": "Test Show", "ids": {"tmdb": 12345}},
            "watched_at": "2023-01-02T00:00:00.000Z",
        }

        def mock_metadata_side_effect(media_type, _, __, ___=None):
            if media_type == MediaTypes.TV.value:
                return {
                    "title": "Test Show",
                    "image": "tv_image.jpg",
                    "last_episode_season": 1,
                    "max_progress": 2,
                }
            if media_type == MediaTypes.SEASON.value:
                return {
                    "title": "Season 1",
                    "image": "season_image.jpg",
                    "episodes": [
                        {"episode_number": 1, "still_path": "/still1.jpg"},
                        {"episode_number": 2, "still_path": "/still2.jpg"},
                    ],
                    "max_progress": 2,
                }
            return None

        mock_get_metadata.side_effect = mock_metadata_side_effect

        trakt_importer = TraktImporter("testuser", self.user, "new")
        trakt_importer.process_watched_episode(episode_entry)

        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.TV.value]), 0)
        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.SEASON.value]), 0)
        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.EPISODE.value]), 1)
        self.assertEqual(
            trakt_importer.bulk_media[MediaTypes.EPISODE.value][0].related_season_id,
            season_obj.id,
        )

        # Regression (#375): the episode completes the season (max_progress)
        # and is the show's last season, but the show/season were already
        # tracked locally as In Progress — that status must not be silently
        # overwritten to Completed.
        self.assertEqual(len(trakt_importer.completed_seasons), 0)
        self.assertEqual(len(trakt_importer.completed_tvs), 0)

    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_process_watched_episode_overwrite_mode_existing_show(
        self,
        mock_get_metadata,
    ):
        """Overwrite-mode re-import must not reference a deleted TV row (#419)."""
        tv_item = Item.objects.get_or_create(
            media_id="12345",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            defaults={"title": "Test Show"},
        )[0]
        TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

        episode_entry = {
            "type": "episode",
            "episode": {"season": 1, "number": 1, "title": "Pilot"},
            "show": {"title": "Test Show", "ids": {"tmdb": 12345}},
            "watched_at": "2023-01-01T00:00:00.000Z",
        }

        def mock_metadata_side_effect(media_type, _, __, ___=None):
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
                    "episodes": [{"episode_number": 1, "still_path": "/still.jpg"}],
                    "max_progress": 1,
                }
            return None

        mock_get_metadata.side_effect = mock_metadata_side_effect

        trakt_importer = TraktImporter("testuser", self.user, "overwrite")
        trakt_importer.process_watched_episode(episode_entry)

        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.TV.value]), 1)

        # Exercise the actual delete-then-create sequence used by import_data().
        helpers.cleanup_existing_media(trakt_importer.to_delete, trakt_importer.user)
        helpers.bulk_create_media(trakt_importer.bulk_media, trakt_importer.user)

        new_tv = TV.objects.get(user=self.user, item__media_id="12345")
        season = Season.objects.get(user=self.user, related_tv=new_tv)
        self.assertTrue(
            Episode.objects.filter(related_season=season).exists(),
        )

        # Overwrite mode recreates the row, so completion status derived from
        # Trakt history should still apply (unlike "new" mode against an
        # already-tracked show).
        self.assertEqual(new_tv.status, Status.COMPLETED.value)
        self.assertEqual(season.status, Status.COMPLETED.value)

    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_process_watched_episode_overwrite_mode_existing_season(
        self,
        mock_get_metadata,
    ):
        """Overwrite-mode re-import must not reference a deleted Season row (#531)."""
        tv_item = Item.objects.get_or_create(
            media_id="12345",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            defaults={"title": "Test Show"},
        )[0]
        old_tv = TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        season_item = Item.objects.get_or_create(
            media_id="12345",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            defaults={"title": "Season 1"},
        )[0]
        old_season = Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=old_tv,
            status=Status.IN_PROGRESS.value,
        )
        episode_item = Item.objects.get_or_create(
            media_id="12345",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            defaults={"title": "Pilot"},
        )[0]
        Episode.objects.create(item=episode_item, related_season=old_season)

        episode_entry = {
            "type": "episode",
            "episode": {"season": 1, "number": 1, "title": "Pilot"},
            "show": {"title": "Test Show", "ids": {"tmdb": 12345}},
            "watched_at": "2023-01-01T00:00:00.000Z",
        }

        def mock_metadata_side_effect(media_type, _, __, ___=None):
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
                    "episodes": [{"episode_number": 1, "still_path": "/still.jpg"}],
                    "max_progress": 1,
                }
            return None

        mock_get_metadata.side_effect = mock_metadata_side_effect

        trakt_importer = TraktImporter("testuser", self.user, "overwrite")
        trakt_importer.process_watched_episode(episode_entry)

        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.TV.value]), 1)
        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.SEASON.value]), 1)

        # Exercise the actual delete-then-create sequence used by import_data().
        # This must not raise IntegrityError from a stale (soon-to-be-deleted)
        # Season row being referenced by the new Episode.
        helpers.cleanup_existing_media(trakt_importer.to_delete, trakt_importer.user)
        helpers.bulk_create_media(trakt_importer.bulk_media, trakt_importer.user)

        new_tv = TV.objects.get(user=self.user, item__media_id="12345")
        new_season = Season.objects.get(user=self.user, related_tv=new_tv)
        self.assertNotEqual(new_season.pk, old_season.pk)
        self.assertTrue(
            Episode.objects.filter(related_season=new_season).exists(),
        )

    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_process_watchlist(self, mock_get_metadata, mock_make_request):
        """Test processing a watchlist entry."""
        watchlist_entry = {
            "listed_at": "2023-01-01T00:00:00.000Z",
            "type": "show",
            "show": {"title": "Watchlist Show", "ids": {"tmdb": 54321}},
        }

        mock_make_request.side_effect = [[watchlist_entry], []]
        mock_get_metadata.return_value = {
            "title": "Watchlist Show",
            "image": "show_image.jpg",
        }

        trakt_importer = TraktImporter("testuser", self.user, "new")
        trakt_importer.process_watchlist()

        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.TV.value]), 1)
        tv_obj = trakt_importer.bulk_media[MediaTypes.TV.value][0]
        self.assertEqual(tv_obj.status, Status.PLANNING.value)

    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_process_ratings(self, mock_get_metadata, mock_make_request):
        """Test processing a rating entry."""
        rating_entry = {
            "rated_at": "2023-01-01T00:00:00.000Z",
            "type": "movie",
            "movie": {"title": "Rated Movie", "ids": {"tmdb": 238}},
            "rating": 8,
        }

        mock_make_request.side_effect = [[rating_entry], []]
        mock_get_metadata.return_value = {
            "title": "Rated Movie",
            "image": "movie_image.jpg",
        }

        trakt_importer = TraktImporter("testuser", self.user, "new")
        trakt_importer.process_ratings()

        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.MOVIE.value]), 1)
        movie_obj = trakt_importer.bulk_media[MediaTypes.MOVIE.value][0]
        self.assertEqual(movie_obj.score, 8)
        # A rating is not a watch: no status, no fabricated progress.
        self.assertIsNone(movie_obj.status)
        self.assertEqual(movie_obj.progress, 0)

    @patch("integrations.imports.trakt.services.get_media_metadata")
    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    def test_process_ratings_tmdb_401_raises_clean_import_error(
        self,
        mock_make_request,
        mock_get_metadata,
    ):
        """A TMDB 401 aborts rating import with a clear error, not a raw crash."""
        rating_entry = {
            "rated_at": "2023-01-01T00:00:00.000Z",
            "type": "movie",
            "movie": {"title": "Rated Movie", "ids": {"tmdb": 238}},
            "rating": 8,
        }
        mock_make_request.side_effect = [[rating_entry], []]

        response = Response()
        response.status_code = requests.codes.unauthorized
        mock_get_metadata.side_effect = services.ProviderAPIError(
            Sources.TMDB.value,
            requests.exceptions.HTTPError(response=response),
        )

        trakt_importer = TraktImporter("testuser", self.user, "new")
        with self.assertRaises(MediaImportError):
            trakt_importer.process_ratings()

    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_season_rating_for_unwatched_show_is_statusless(
        self,
        mock_get_metadata,
        mock_make_request,
    ):
        """A rating on a never-watched season must not fabricate a tracked show."""
        rating_entry = {
            "rated_at": "2023-01-01T00:00:00.000Z",
            "type": "season",
            "show": {"title": "Never Watched", "ids": {"tmdb": 4321}},
            "season": {"number": 1},
            "rating": 10,
        }

        mock_make_request.side_effect = [[rating_entry], []]
        mock_get_metadata.return_value = {
            "title": "Never Watched",
            "image": "show.jpg",
            "season_title": "Season 1",
            "season_number": 1,
            "max_progress": 8,
            "episodes": [],
        }

        trakt_importer = TraktImporter("testuser", self.user, "new")
        trakt_importer.process_ratings()

        season_obj = trakt_importer.bulk_media[MediaTypes.SEASON.value][0]
        self.assertEqual(season_obj.score, 10)
        self.assertIsNone(season_obj.status)

        # The parent show is created to hang the season off, but it is not
        # tracked either — this is what used to flood the library.
        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.TV.value]), 1)
        self.assertIsNone(trakt_importer.bulk_media[MediaTypes.TV.value][0].status)

    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_season_rating_leaves_watched_show_status_alone(
        self,
        mock_get_metadata,
        mock_make_request,
    ):
        """A rating on a season watched in the same run only adds the score."""
        rating_entry = {
            "rated_at": "2023-01-01T00:00:00.000Z",
            "type": "season",
            "show": {"title": "Watched Show", "ids": {"tmdb": 4322}},
            "season": {"number": 1},
            "rating": 9,
        }

        mock_make_request.side_effect = [[rating_entry], []]
        mock_get_metadata.return_value = {
            "title": "Watched Show",
            "image": "show.jpg",
            "season_title": "Season 1",
            "season_number": 1,
            "max_progress": 8,
            "episodes": [],
        }

        trakt_importer = TraktImporter("testuser", self.user, "new")
        # Stand in for a season already built by process_history.
        tracked_season = Season(user=self.user, status=Status.IN_PROGRESS.value)
        trakt_importer.media_instances[MediaTypes.SEASON.value]["4322:1"] = [
            tracked_season,
        ]
        trakt_importer.media_instances[MediaTypes.TV.value]["4322"] = [
            TV(user=self.user, status=Status.IN_PROGRESS.value),
        ]

        trakt_importer.process_ratings()

        self.assertEqual(tracked_season.score, 9)
        self.assertEqual(tracked_season.status, Status.IN_PROGRESS.value)
        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.SEASON.value]), 0)

    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_rating_score_is_stored_unscaled_for_five_point_users(
        self,
        mock_get_metadata,
        mock_make_request,
    ):
        """Trakt rates out of 10, which is already the storage scale."""
        self.user.rating_scale = "5"
        self.user.save(update_fields=["rating_scale"])

        rating_entry = {
            "rated_at": "2023-01-01T00:00:00.000Z",
            "type": "movie",
            "movie": {"title": "Scaled Movie", "ids": {"tmdb": 239}},
            "rating": 6,
        }
        mock_make_request.side_effect = [[rating_entry], []]
        mock_get_metadata.return_value = {
            "title": "Scaled Movie",
            "image": "movie.jpg",
        }

        trakt_importer = TraktImporter("testuser", self.user, "new")
        trakt_importer.process_ratings()

        movie_obj = trakt_importer.bulk_media[MediaTypes.MOVIE.value][0]
        # Stored as-is (displays as 3/5), not doubled to the 10 ceiling.
        self.assertEqual(movie_obj.score, 6)
        self.assertEqual(self.user.scale_score_for_display(Decimal(6)), Decimal(3))

    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    def test_invalid_username_fails_before_importing(self, mock_make_request):
        """A bad slug errors immediately instead of importing an empty library."""
        response = Response()
        response.status_code = 404
        mock_make_request.side_effect = requests.exceptions.HTTPError(response=response)

        trakt_importer = TraktImporter("@bad-slug", self.user, "new")

        with self.assertRaises(MediaImportError):
            trakt_importer.import_data()

        # Only the validation request was made; no import work was attempted.
        self.assertEqual(mock_make_request.call_count, 1)

    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_process_comments(self, mock_get_metadata, mock_make_request):
        """Test processing paginated comments from Trakt."""
        # First page with one comment
        first_page = [
            {
                "type": "movie",
                "movie": {"title": "Commented Movie", "ids": {"tmdb": 123}},
                "comment": {
                    "comment": "Great movie!",
                    "updated_at": "2023-01-01T00:00:00.000Z",
                },
            },
        ]

        # Second empty page to stop pagination
        second_page = []

        mock_make_request.side_effect = [first_page, second_page]
        mock_get_metadata.return_value = {
            "title": "Commented Movie",
            "image": "movie_image.jpg",
        }

        trakt_importer = TraktImporter("testuser", self.user, "new")
        trakt_importer.process_comments()

        calls = mock_make_request.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertIn("?page=1&limit=1000", calls[0].args[0])  # First page
        self.assertIn("?page=2&limit=1000", calls[1].args[0])  # Second page

        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.MOVIE.value]), 1)
        movie_obj = trakt_importer.bulk_media[MediaTypes.MOVIE.value][0]
        self.assertEqual(movie_obj.notes, "Great movie!")

    @patch("integrations.imports.trakt.services.get_media_metadata")
    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    def test_process_comments_tmdb_401_raises_clean_import_error(
        self,
        mock_make_request,
        mock_get_metadata,
    ):
        """A TMDB 401 aborts comment import with a clear error, not a raw crash."""
        comment_entry = {
            "type": "movie",
            "movie": {"title": "Commented Movie", "ids": {"tmdb": 123}},
            "comment": {
                "comment": "Great movie!",
                "updated_at": "2023-01-01T00:00:00.000Z",
            },
        }
        mock_make_request.side_effect = [[comment_entry], []]

        response = Response()
        response.status_code = requests.codes.unauthorized
        mock_get_metadata.side_effect = services.ProviderAPIError(
            Sources.TMDB.value,
            requests.exceptions.HTTPError(response=response),
        )

        trakt_importer = TraktImporter("testuser", self.user, "new")
        with self.assertRaises(MediaImportError):
            trakt_importer.process_comments()

    @patch("integrations.imports.trakt.TraktImporter._get_paginated_data")
    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_public_import_full_flow(
        self,
        mock_get_metadata,
        mock_make_request,
        mock_get_paginated,
    ):
        """Test full import flow with public username (no OAuth)."""
        mock_get_paginated.side_effect = [
            [
                {
                    "type": "movie",
                    "movie": {"title": "Public Movie", "ids": {"tmdb": 999}},
                    "watched_at": "2023-01-01T00:00:00.000Z",
                },
            ],  # history
            [],  # watchlist — empty
            [],  # ratings — empty
            [],  # notes — empty
            [],  # comments — empty
            [],  # collection movies — empty
            [],  # collection shows — empty
        ]

        mock_make_request.return_value = []

        mock_get_metadata.return_value = {
            "title": "Public Movie",
            "image": "movie.jpg",
        }

        imported_counts, _ = importer(None, self.user, "new", "public_user")

        self.assertEqual(imported_counts[MediaTypes.MOVIE.value], 1)
        self.assertEqual(Movie.objects.filter(user=self.user).count(), 1)

    @patch("integrations.imports.trakt.TraktImporter._get_paginated_data")
    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_oauth_import_full_flow(
        self,
        mock_get_metadata,
        mock_make_request,
        mock_get_paginated,
    ):
        """Test full import flow with OAuth token."""
        mock_get_paginated.side_effect = [
            [],  # process_dropped — progress_watched, no dropped shows
            [],  # process_dropped — progress_watched_reset, no dropped shows
            [
                {
                    "type": "movie",
                    "movie": {"title": "OAuth Movie", "ids": {"tmdb": 888}},
                    "watched_at": "2023-01-01T00:00:00.000Z",
                },
            ],  # history
            [],  # watchlist — empty
            [],  # ratings — empty
            [],  # notes — empty
            [],  # comments — empty
            [],  # collection movies — empty
            [],  # collection shows — empty
        ]

        mock_make_request.return_value = []

        mock_get_metadata.return_value = {
            "title": "OAuth Movie",
            "image": "movie.jpg",
        }

        encrypted_token = helpers.encrypt("test_refresh_token")
        imported_counts, _ = importer(
            encrypted_token,
            self.user,
            "new",
            "oauth_user",
        )

        self.assertEqual(imported_counts[MediaTypes.MOVIE.value], 1)
        self.assertEqual(Movie.objects.filter(user=self.user).count(), 1)

    def test_trakt_importer_with_refresh_token(self):
        """Test TraktImporter initialization with refresh token."""
        encrypted_token = helpers.encrypt("test_token")
        importer = TraktImporter(
            "testuser",
            self.user,
            "new",
            refresh_token=encrypted_token,
        )

        self.assertEqual(importer.username, "testuser")
        self.assertEqual(importer.refresh_token, encrypted_token)
        self.assertEqual(importer.mode, "new")
        self.assertTrue(importer.is_oauth_import)
        self.assertEqual(importer.user_base_url, "https://api.trakt.tv/users/me")

    def test_trakt_importer_without_refresh_token(self):
        """Test TraktImporter initialization without refresh token (public)."""
        importer = TraktImporter("testuser", self.user, "new", refresh_token=None)

        self.assertEqual(importer.username, "testuser")
        self.assertIsNone(importer.refresh_token)
        self.assertEqual(importer.mode, "new")
        self.assertFalse(importer.is_oauth_import)
        self.assertEqual(importer.user_base_url, "https://api.trakt.tv/users/testuser")

    @patch("integrations.imports.trakt.TraktImporter.process_watched_movie")
    @patch("integrations.imports.trakt.TraktImporter._get_paginated_data")
    def test_process_history_oauth_falls_back_to_sync_when_empty(
        self,
        mock_get_paginated,
        mock_process_movie,
    ):
        """OAuth history import retries against sync endpoint if user history is empty."""
        encrypted_token = helpers.encrypt("test_refresh_token")
        history_entry = {
            "type": "movie",
            "movie": {"title": "Fallback Movie", "ids": {"tmdb": 123}},
            "watched_at": "2023-01-02T00:00:00.000Z",
        }
        mock_get_paginated.side_effect = [[], [history_entry]]

        trakt_importer = TraktImporter(
            "testuser",
            self.user,
            "new",
            refresh_token=encrypted_token,
        )
        trakt_importer.process_history()

        self.assertEqual(
            mock_get_paginated.call_args_list,
            [
                call(
                    "https://api.trakt.tv/users/me/history",
                    "history entries",
                ),
                call(
                    "https://api.trakt.tv/sync/history",
                    "history entries",
                ),
            ],
        )
        mock_process_movie.assert_called_once_with(history_entry)

    @patch("integrations.imports.trakt.TraktImporter._get_paginated_data")
    def test_process_history_public_does_not_fallback(self, mock_get_paginated):
        """Public history import does not retry sync endpoint when empty."""
        mock_get_paginated.return_value = []

        trakt_importer = TraktImporter("testuser", self.user, "new", refresh_token=None)
        trakt_importer.process_history()

        mock_get_paginated.assert_called_once_with(
            "https://api.trakt.tv/users/testuser/history",
            "history entries",
        )

    @patch("integrations.imports.trakt.TraktImporter._get_paginated_data")
    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_reimport_does_not_duplicate_episode_history(
        self,
        mock_get_metadata,
        mock_make_request,
        mock_get_paginated,
    ):
        """Running the same Trakt sync twice should not create duplicate episodes."""
        episode_entry = {
            "type": "episode",
            "episode": {"season": 1, "number": 1, "title": "Pilot"},
            "show": {"title": "Repeat Show", "ids": {"tmdb": 12345}},
            "watched_at": "2023-01-01T00:00:00.000Z",
        }

        def mock_metadata_side_effect(media_type, _, __, ___=None):
            if media_type == MediaTypes.TV.value:
                return {
                    "title": "Repeat Show",
                    "image": "tv_image.jpg",
                    "last_episode_season": 1,
                    "max_progress": 1,
                }
            if media_type == MediaTypes.SEASON.value:
                return {
                    "title": "Season 1",
                    "image": "season_image.jpg",
                    "episodes": [{"episode_number": 1, "still_path": "/still.jpg"}],
                    "max_progress": 1,
                }
            return None

        mock_get_metadata.side_effect = mock_metadata_side_effect
        mock_get_paginated.side_effect = [
            [episode_entry],  # history (1st import)
            [],  # watchlist
            [],  # ratings
            [],  # comments
            [],  # collection movies
            [],  # collection shows
            [],  # notes
            [episode_entry],  # history (2nd import)
            [],  # watchlist
            [],  # ratings
            [],  # notes
            [],  # comments
            [],  # collection movies
            [],  # collection shows
        ]
        mock_make_request.return_value = []

        first_counts, _ = importer(None, self.user, "new", "public_user")
        second_counts, _ = importer(None, self.user, "new", "public_user")

        self.assertEqual(first_counts[MediaTypes.EPISODE.value], 1)
        self.assertEqual(second_counts.get(MediaTypes.EPISODE.value, 0), 0)
        self.assertEqual(
            Episode.objects.filter(related_season__user=self.user).count(),
            1,
        )

    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    def test_process_episode_rating(self, mock_make_request):
        """Episode ratings from Trakt are applied to existing Episode records."""
        # Build the minimum DB state: TV → Season → Episode
        tv_item = Item.objects.get_or_create(
            media_id="12345",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            defaults={"title": "Test Show"},
        )[0]
        tv_obj = TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        season_item = Item.objects.get_or_create(
            media_id="12345",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            defaults={"title": "Season 1"},
        )[0]
        season_obj = Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=tv_obj,
            status=Status.IN_PROGRESS.value,
        )
        episode_item = Item.objects.get_or_create(
            media_id="12345",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            defaults={"title": "Pilot"},
        )[0]
        episode_obj = Episode.objects.create(
            item=episode_item,
            related_season=season_obj,
        )

        rating_entry = {
            "rated_at": "2023-01-01T00:00:00.000Z",
            "type": "episode",
            "show": {"title": "Test Show", "ids": {"tmdb": 12345}},
            "episode": {"season": 1, "number": 1, "title": "Pilot"},
            "rating": 8,
        }
        mock_make_request.side_effect = [[rating_entry], []]

        trakt_importer = TraktImporter("testuser", self.user, "new")
        trakt_importer.process_ratings()

        episode_obj.refresh_from_db()
        # Trakt rating 8 on a 10-point scale → stored as 8.0 (no scaling needed)
        self.assertIsNotNone(episode_obj.score)
        self.assertEqual(float(episode_obj.score), 8.0)

    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    def test_process_episode_rating_no_season(self, mock_make_request):
        """Episode rating is silently skipped when the season isn't tracked."""
        rating_entry = {
            "rated_at": "2023-01-01T00:00:00.000Z",
            "type": "episode",
            "show": {"title": "Untracked Show", "ids": {"tmdb": 99999}},
            "episode": {"season": 1, "number": 1, "title": "Pilot"},
            "rating": 7,
        }
        mock_make_request.side_effect = [[rating_entry], []]

        trakt_importer = TraktImporter("testuser", self.user, "new")
        # Should not raise; simply skips because no matching Season exists
        trakt_importer.process_ratings()
        self.assertEqual(
            Episode.objects.filter(related_season__user=self.user).count(),
            0,
        )

    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    def test_process_episode_rating_no_episode_row(self, mock_make_request):
        """Episode rating is silently skipped when Season exists but Episode row doesn't."""
        TMDB_ID = 55502
        tv_item, _ = Item.objects.get_or_create(
            media_id=str(TMDB_ID),
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            defaults={"title": "Test Show"},
        )
        tv_obj, _ = TV.objects.get_or_create(
            item=tv_item,
            user=self.user,
            defaults={"status": Status.IN_PROGRESS.value},
        )
        season_item, _ = Item.objects.get_or_create(
            media_id=str(TMDB_ID),
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            defaults={"title": "Season 1"},
        )
        Season.objects.get_or_create(
            item=season_item,
            user=self.user,
            defaults={"related_tv": tv_obj, "status": Status.IN_PROGRESS.value},
        )
        # Intentionally no Episode row created

        mock_make_request.side_effect = [
            [
                {
                    "rated_at": "2024-01-01T00:00:00.000Z",
                    "type": "episode",
                    "show": {"title": "Test Show", "ids": {"tmdb": TMDB_ID}},
                    "episode": {"season": 1, "number": 1, "title": "Pilot"},
                    "rating": 8,
                },
            ],
            [],
        ]

        # Should not raise; no Episode created
        TraktImporter("testuser", self.user, "new").process_ratings()
        self.assertEqual(
            Episode.objects.filter(related_season__user=self.user).count(), 0
        )

    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    def test_process_episode_rating_no_tmdb_id(self, mock_make_request):
        """Episode rating is silently skipped when the show has no TMDB ID."""
        mock_make_request.side_effect = [
            [
                {
                    "rated_at": "2024-01-01T00:00:00.000Z",
                    "type": "episode",
                    "show": {"title": "No-ID Show", "ids": {"tmdb": None}},
                    "episode": {"season": 1, "number": 1, "title": "Pilot"},
                    "rating": 8,
                },
            ],
            [],
        ]

        # Should not raise; no DB writes
        TraktImporter("testuser", self.user, "new").process_ratings()
        self.assertEqual(
            Episode.objects.filter(related_season__user=self.user).count(), 0
        )

    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_episode_rating_mixed_payload(self, mock_get_metadata, mock_make_request):
        """Movie and episode ratings in the same payload are each handled correctly."""
        TMDB_ID = 55503
        _, _, episode_obj = self._make_tv_season_episode(TMDB_ID, 1, 1)

        mock_get_metadata.return_value = {"title": "Rated Movie", "image": "img.jpg"}
        mock_make_request.side_effect = [
            [
                {
                    "rated_at": "2024-01-01T00:00:00.000Z",
                    "type": "movie",
                    "movie": {"title": "Rated Movie", "ids": {"tmdb": 77777}},
                    "rating": 7,
                },
                {
                    "rated_at": "2024-01-01T00:00:00.000Z",
                    "type": "episode",
                    "show": {"title": "Test Show", "ids": {"tmdb": TMDB_ID}},
                    "episode": {"season": 1, "number": 1, "title": "Pilot"},
                    "rating": 9,
                },
            ],
            [],
        ]

        trakt_importer = TraktImporter("testuser", self.user, "new")
        trakt_importer.process_ratings()

        # Movie rating queued in bulk_media
        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.MOVIE.value]), 1)
        self.assertEqual(trakt_importer.bulk_media[MediaTypes.MOVIE.value][0].score, 7)

        # Episode score written directly to DB
        episode_obj.refresh_from_db()
        self.assertEqual(float(episode_obj.score), 9.0)

    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    @patch("integrations.imports.trakt.TraktImporter._get_paginated_data")
    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_episode_rating_survives_full_import_flow(
        self, mock_get_metadata, mock_get_paginated, _mock_make_request
    ):
        """Episode ratings are applied when running the full import_data() pipeline."""
        from integrations.imports.trakt import importer

        TMDB_ID = 55504
        _, _, episode_obj = self._make_tv_season_episode(TMDB_ID, 1, 1)

        # process_history, process_watchlist, process_ratings, process_comments
        # all use paginated data (public import skips process_dropped)
        mock_get_paginated.side_effect = [
            [],  # history — empty
            [],  # watchlist — empty
            [  # ratings — one episode entry
                {
                    "rated_at": "2024-01-01T00:00:00.000Z",
                    "type": "episode",
                    "show": {"title": "Test Show", "ids": {"tmdb": TMDB_ID}},
                    "episode": {"season": 1, "number": 1, "title": "Pilot"},
                    "rating": 8,
                }
            ],
            [],  # notes — empty
            [],  # comments — empty
            [],  # collection movies — empty
            [],  # collection shows — empty
        ]
        mock_get_metadata.return_value = {"title": "Test Show", "image": "img.jpg"}

        importer(None, self.user, "new", "public_user")

        episode_obj.refresh_from_db()
        self.assertIsNotNone(episode_obj.score)
        self.assertEqual(float(episode_obj.score), 8.0)

    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    @patch("integrations.imports.trakt.TraktImporter._get_paginated_data")
    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_episode_rating_applied_on_first_ever_import(
        self, mock_get_metadata, mock_get_paginated, _mock_make_request
    ):
        """Ratings land correctly when history and ratings are imported in the same run.

        Regression test: process_history() buffers new Season/Episode objects in
        bulk_media without writing them to the DB.  process_ratings() then runs
        before bulk_create_media() commits those rows, so a plain DB lookup finds
        nothing and silently drops the rating.  The fix checks media_instances for
        in-flight objects from the same run.
        """
        from integrations.imports.trakt import importer

        TMDB_ID = 55505
        # No pre-existing DB rows — simulates a brand-new Floppy account

        episode_entry = {
            "type": "episode",
            "episode": {"season": 1, "number": 1, "title": "Pilot"},
            "show": {"title": "New Show", "ids": {"tmdb": TMDB_ID}},
            "watched_at": "2024-01-01T00:00:00.000Z",
        }
        rating_entry = {
            "rated_at": "2024-01-01T00:00:00.000Z",
            "type": "episode",
            "show": {"title": "New Show", "ids": {"tmdb": TMDB_ID}},
            "episode": {"season": 1, "number": 1, "title": "Pilot"},
            "rating": 9,
        }

        def metadata_side_effect(media_type, tmdb_id, *args, **kwargs):
            if media_type == MediaTypes.TV.value:
                return {
                    "title": "New Show",
                    "image": "img.jpg",
                    "last_episode_season": None,
                }
            if media_type == MediaTypes.SEASON.value:
                return {
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.SEASON.value,
                    "season_title": "Season 1",
                    "season_number": 1,
                    "max_progress": 6,
                    "image": "img.jpg",
                    "episodes": [
                        {"episode_number": 1, "still_path": None},
                    ],
                    "score": 0,
                    "score_count": 0,
                    "synopsis": "",
                    "details": {},
                    "cast": [],
                    "crew": [],
                }
            return None

        mock_get_metadata.side_effect = metadata_side_effect
        # process_history, process_watchlist, process_ratings, process_comments
        # all use paginated data (public import skips process_dropped)
        mock_get_paginated.side_effect = [
            [episode_entry],  # history
            [],  # watchlist — empty
            [rating_entry],  # ratings — one episode entry
            [],  # notes
            [],  # comments
            [],  # collection movies — empty
            [],  # collection shows — empty
        ]

        importer(None, self.user, "new", "public_user")

        episode_obj = Episode.objects.filter(
            related_season__user=self.user,
            item__episode_number=1,
        ).first()
        self.assertIsNotNone(
            episode_obj, "Episode should have been created by history import"
        )
        self.assertIsNotNone(
            episode_obj.score, "Episode score should be set from Trakt rating"
        )
        self.assertEqual(float(episode_obj.score), 9.0)

    # ------------------------------------------------------------------
    # Dropped show status import
    # ------------------------------------------------------------------

    @patch("integrations.imports.trakt.TraktImporter._get_paginated_data")
    def test_process_dropped_collects_ids(self, mock_get_paginated):
        """process_dropped() populates dropped_tmdb_ids from the hidden endpoint."""
        mock_get_paginated.return_value = [
            {"type": "show", "show": {"title": "Dropped Show", "ids": {"tmdb": 11111}}},
            {"type": "show", "show": {"title": "Also Dropped", "ids": {"tmdb": 22222}}},
            {
                "type": "movie",
                "movie": {"title": "Hidden Movie", "ids": {"tmdb": 33333}},
            },
        ]
        encrypted_token = helpers.encrypt("test_token")
        trakt_importer = TraktImporter(
            "testuser", self.user, "new", refresh_token=encrypted_token
        )
        trakt_importer.process_dropped()

        self.assertIn("11111", trakt_importer.dropped_tmdb_ids)
        self.assertIn("22222", trakt_importer.dropped_tmdb_ids)
        # Movie-type hidden entries should be ignored
        self.assertNotIn("33333", trakt_importer.dropped_tmdb_ids)
        self.assertEqual(len(trakt_importer.dropped_tmdb_ids), 2)

    @patch("integrations.imports.trakt.TraktImporter._get_paginated_data")
    def test_process_dropped_skipped_without_oauth(self, mock_get_paginated):
        """process_dropped() is a no-op for public (non-OAuth) imports."""
        trakt_importer = TraktImporter("testuser", self.user, "new")
        trakt_importer.process_dropped()

        mock_get_paginated.assert_not_called()
        self.assertEqual(len(trakt_importer.dropped_tmdb_ids), 0)

    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    @patch("integrations.imports.trakt.TraktImporter._get_paginated_data")
    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_dropped_show_status_on_first_import(
        self, mock_get_metadata, mock_get_paginated, _mock_make_request
    ):
        """A show that is both watched and dropped lands in DB with status Dropped."""
        from integrations.imports.trakt import importer

        TMDB_ID = 66601
        episode_entry = {
            "type": "episode",
            "episode": {"season": 1, "number": 1, "title": "Pilot"},
            "show": {"title": "Dropped Show", "ids": {"tmdb": TMDB_ID}},
            "watched_at": "2024-01-01T00:00:00.000Z",
        }

        def metadata_side_effect(media_type, tmdb_id, *args, **kwargs):
            if media_type == MediaTypes.TV.value:
                return {
                    "title": "Dropped Show",
                    "image": "img.jpg",
                    "last_episode_season": None,
                }
            if media_type == MediaTypes.SEASON.value:
                return {
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.SEASON.value,
                    "season_title": "Season 1",
                    "season_number": 1,
                    "max_progress": 6,
                    "image": "img.jpg",
                    "episodes": [{"episode_number": 1, "still_path": None}],
                    "score": 0,
                    "score_count": 0,
                    "synopsis": "",
                    "details": {},
                    "cast": [],
                    "crew": [],
                }
            return None

        mock_get_metadata.side_effect = metadata_side_effect
        mock_get_paginated.side_effect = [
            # process_dropped — progress_watched: show is hidden/dropped
            [
                {
                    "type": "show",
                    "show": {"title": "Dropped Show", "ids": {"tmdb": TMDB_ID}},
                }
            ],
            [],  # process_dropped — progress_watched_reset
            [episode_entry],  # process_history
            [],  # process_watchlist
            [],  # process_ratings
            [],  # process_notes
            [],  # process_comments
            [],  # collection movies — empty
            [],  # collection shows — empty
        ]

        encrypted_token = helpers.encrypt("test_token")
        importer(encrypted_token, self.user, "new", "oauth_user")

        tv_obj = TV.objects.filter(user=self.user, item__media_id=str(TMDB_ID)).first()
        self.assertIsNotNone(tv_obj)
        self.assertEqual(tv_obj.status, Status.DROPPED.value)

    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    @patch("integrations.imports.trakt.TraktImporter._get_paginated_data")
    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_dropped_show_updates_existing_tv_in_overwrite_mode(
        self, mock_get_metadata, mock_get_paginated, _mock_make_request
    ):
        """An overwrite re-sync updates an existing IN_PROGRESS TV show to Dropped.

        Following #375, this only applies in "overwrite" mode (an explicit
        re-sync, which deletes and recreates the row) — see
        test_dropped_show_does_not_update_existing_tv_in_new_mode for the
        "new" mode (default recurring sync) case.
        """
        from integrations.imports.trakt import importer

        TMDB_ID = 66602
        # Pre-existing TV show in DB marked as IN_PROGRESS
        tv_item, _ = Item.objects.get_or_create(
            media_id=str(TMDB_ID),
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            defaults={"title": "Ongoing Show"},
        )
        tv_obj = TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        episode_entry = {
            "type": "episode",
            "episode": {"season": 1, "number": 1, "title": "Old Episode"},
            "show": {"title": "Ongoing Show", "ids": {"tmdb": TMDB_ID}},
            "watched_at": "2024-01-01T00:00:00.000Z",
        }

        def metadata_side_effect(media_type, tmdb_id, *args, **kwargs):
            if media_type == MediaTypes.TV.value:
                return {
                    "title": "Ongoing Show",
                    "image": "img.jpg",
                    "last_episode_season": None,
                }
            if media_type == MediaTypes.SEASON.value:
                return {
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.SEASON.value,
                    "season_title": "Season 1",
                    "season_number": 1,
                    "max_progress": 6,
                    "image": "img.jpg",
                    "episodes": [{"episode_number": 1, "still_path": None}],
                    "score": 0,
                    "score_count": 0,
                    "synopsis": "",
                    "details": {},
                    "cast": [],
                    "crew": [],
                }
            return None

        mock_get_metadata.side_effect = metadata_side_effect
        mock_get_paginated.side_effect = [
            # process_dropped — progress_watched: show is now dropped
            [
                {
                    "type": "show",
                    "show": {"title": "Ongoing Show", "ids": {"tmdb": TMDB_ID}},
                }
            ],
            [],  # process_dropped — progress_watched_reset
            [episode_entry],  # process_history
            [],  # process_watchlist
            [],  # process_ratings
            [],  # process_notes
            [],  # process_comments
            [],  # collection movies — empty
            [],  # collection shows — empty
        ]

        encrypted_token = helpers.encrypt("test_token")
        importer(encrypted_token, self.user, "overwrite", "oauth_user")

        # Overwrite mode deletes and recreates the row.
        new_tv = TV.objects.get(user=self.user, item__media_id=str(TMDB_ID))
        self.assertEqual(new_tv.status, Status.DROPPED.value)

    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    @patch("integrations.imports.trakt.TraktImporter._get_paginated_data")
    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_dropped_show_does_not_update_existing_tv_in_new_mode(
        self, mock_get_metadata, mock_get_paginated, _mock_make_request
    ):
        """Regression test for #375: a "new"-mode sync (the default for
        recurring/scheduled imports) must not silently flip an already-
        tracked show's status to Dropped just because Trakt now hides it.
        """
        from integrations.imports.trakt import importer

        TMDB_ID = 66603
        tv_item, _ = Item.objects.get_or_create(
            media_id=str(TMDB_ID),
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            defaults={"title": "Ongoing Show"},
        )
        tv_obj = TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        episode_entry = {
            "type": "episode",
            "episode": {"season": 1, "number": 1, "title": "Old Episode"},
            "show": {"title": "Ongoing Show", "ids": {"tmdb": TMDB_ID}},
            "watched_at": "2024-01-01T00:00:00.000Z",
        }

        def metadata_side_effect(media_type, tmdb_id, *args, **kwargs):
            if media_type == MediaTypes.TV.value:
                return {
                    "title": "Ongoing Show",
                    "image": "img.jpg",
                    "last_episode_season": None,
                }
            if media_type == MediaTypes.SEASON.value:
                return {
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.SEASON.value,
                    "season_title": "Season 1",
                    "season_number": 1,
                    "max_progress": 6,
                    "image": "img.jpg",
                    "episodes": [{"episode_number": 1, "still_path": None}],
                    "score": 0,
                    "score_count": 0,
                    "synopsis": "",
                    "details": {},
                    "cast": [],
                    "crew": [],
                }
            return None

        mock_get_metadata.side_effect = metadata_side_effect
        mock_get_paginated.side_effect = [
            # process_dropped — progress_watched: show is now dropped
            [
                {
                    "type": "show",
                    "show": {"title": "Ongoing Show", "ids": {"tmdb": TMDB_ID}},
                }
            ],
            [],  # process_dropped — progress_watched_reset
            [episode_entry],  # process_history
            [],  # process_watchlist
            [],  # process_ratings
            [],  # process_notes
            [],  # process_comments
            [],  # collection movies — empty
            [],  # collection shows — empty
        ]

        encrypted_token = helpers.encrypt("test_token")
        importer(encrypted_token, self.user, "new", "oauth_user")

        tv_obj.refresh_from_db()
        self.assertEqual(tv_obj.status, Status.IN_PROGRESS.value)

    def test_get_or_create_item_reuses_item_across_library_buckets(self):
        """Episode existing under two library buckets must not crash the lookup.

        Marking a season complete creates episode items inheriting the season's
        ``library_media_type`` ('season'), while the importer creates them as
        'episode'. Both rows are valid under the unique constraints, so a lookup
        that ignores ``library_media_type`` previously raised
        ``MultipleObjectsReturned``.
        """
        common = {
            "media_id": "63404",
            "source": Sources.TMDB.value,
            "media_type": MediaTypes.EPISODE.value,
            "season_number": 21,
            "episode_number": 9,
            "title": "Taskmaster",
            "image": "img.jpg",
        }
        Item.objects.create(library_media_type=MediaTypes.EPISODE.value, **common)
        Item.objects.create(library_media_type=MediaTypes.SEASON.value, **common)

        trakt_importer = TraktImporter("testuser", self.user, "new")
        metadata = {"title": "Taskmaster", "image": "img.jpg"}

        result = trakt_importer._get_or_create_item(
            MediaTypes.EPISODE.value,
            "63404",
            metadata,
            season_number=21,
            episode_number=9,
        )

        # Reuses the importer's preferred bucket, creates no duplicate.
        self.assertEqual(result.library_media_type, MediaTypes.EPISODE.value)
        self.assertEqual(
            Item.objects.filter(
                media_id="63404",
                media_type=MediaTypes.EPISODE.value,
                season_number=21,
                episode_number=9,
            ).count(),
            2,
        )

    @patch("integrations.imports.trakt.TraktImporter._get_paginated_data")
    def test_process_history_skips_unexpected_entry_error(self, mock_paginated):
        """A single failing entry is recorded as a warning, not fatal."""
        episode_entry = {
            "type": "episode",
            "episode": {"season": 21, "number": 9, "title": "Bad Episode"},
            "show": {"title": "Taskmaster", "ids": {"tmdb": 63404}},
            "watched_at": "2023-01-01T00:00:00.000Z",
        }
        mock_paginated.return_value = [episode_entry]

        trakt_importer = TraktImporter("testuser", self.user, "new")

        with patch.object(
            trakt_importer,
            "process_watched_episode",
            side_effect=ValueError("boom"),
        ):
            # Must not raise.
            trakt_importer.process_history()

        self.assertTrue(
            any(
                "skipped a watch entry" in warning
                for warning in trakt_importer.warnings
            ),
            trakt_importer.warnings,
        )

    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_process_collection_movie(self, mock_get_metadata, mock_make_request):
        """Test processing a collected movie entry."""
        collected_movie = {
            "collected_at": "2023-01-05T00:00:00.000Z",
            "movie": {"title": "Owned Movie", "ids": {"tmdb": 999}},
            "metadata": {
                "media_type": "bluray",
                "resolution": "1080p",
                "hdr": "",
                "audio": "dts",
                "audio_channels": "5.1",
                "3d": False,
            },
        }
        # movies page1, movies page2 (empty, stops loop), shows page1 (empty, stops loop)
        mock_make_request.side_effect = [[collected_movie], [], []]
        mock_get_metadata.return_value = {
            "title": "Owned Movie",
            "image": "movie_image.jpg",
        }

        trakt_importer = TraktImporter("testuser", self.user, "new")
        trakt_importer.process_collection()

        entry = CollectionEntry.objects.get(
            user=self.user,
            item__media_id="999",
            item__media_type=MediaTypes.MOVIE.value,
        )
        self.assertEqual(entry.resolution, "1080p")
        self.assertEqual(entry.audio_codec, "dts")
        self.assertEqual(entry.audio_channels, "5.1")
        self.assertEqual(entry.media_type, "bluray")
        self.assertFalse(entry.is_3d)

    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_process_collection_show_rolls_up_season_and_show(
        self,
        mock_get_metadata,
        mock_make_request,
    ):
        """A fully-collected season/show should get season/show-level entries too."""
        collected_show = {
            "show": {"title": "Owned Show", "ids": {"tmdb": 4242}},
            "seasons": [
                {
                    "number": 1,
                    "episodes": [
                        {
                            "number": 1,
                            "collected_at": "2023-01-01T00:00:00.000Z",
                            "metadata": {"resolution": "1080p"},
                        },
                        {
                            "number": 2,
                            "collected_at": "2023-01-02T00:00:00.000Z",
                            "metadata": {"resolution": "1080p"},
                        },
                    ],
                },
            ],
        }
        # movies page1 (empty, stops loop), shows page1, shows page2 (empty, stops loop)
        mock_make_request.side_effect = [[], [collected_show], []]

        def mock_metadata_side_effect(media_type, _, __, ___=None):
            if media_type == MediaTypes.TV.value:
                return {
                    "title": "Owned Show",
                    "image": "tv_image.jpg",
                    "related": {"seasons": [{"season_number": 1}]},
                }
            if media_type == MediaTypes.SEASON.value:
                return {
                    "title": "Season 1",
                    "image": "season_image.jpg",
                    "episodes": [
                        {"episode_number": 1, "still_path": "/s1.jpg"},
                        {"episode_number": 2, "still_path": "/s2.jpg"},
                    ],
                    "max_progress": 2,
                }
            return None

        mock_get_metadata.side_effect = mock_metadata_side_effect

        trakt_importer = TraktImporter("testuser", self.user, "new")
        trakt_importer.process_collection()

        self.assertEqual(
            CollectionEntry.objects.filter(
                user=self.user,
                item__media_id="4242",
                item__media_type=MediaTypes.EPISODE.value,
            ).count(),
            2,
        )
        self.assertTrue(
            CollectionEntry.objects.filter(
                user=self.user,
                item__media_id="4242",
                item__media_type=MediaTypes.SEASON.value,
                item__season_number=1,
            ).exists(),
        )
        self.assertTrue(
            CollectionEntry.objects.filter(
                user=self.user,
                item__media_id="4242",
                item__media_type=MediaTypes.TV.value,
            ).exists(),
        )

    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_process_collection_new_mode_does_not_overwrite(
        self,
        mock_get_metadata,
        mock_make_request,
    ):
        """ "new" mode must not touch an existing collection entry's fields."""
        item = Item.objects.get_or_create(
            media_id="999",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={"title": "Owned Movie"},
        )[0]
        existing_entry = CollectionEntry.objects.create(
            user=self.user,
            item=item,
            resolution="4k",
        )

        collected_movie = {
            "collected_at": "2023-01-05T00:00:00.000Z",
            "movie": {"title": "Owned Movie", "ids": {"tmdb": 999}},
            "metadata": {"resolution": "1080p"},
        }
        mock_make_request.side_effect = [[collected_movie], [], []]
        mock_get_metadata.return_value = {
            "title": "Owned Movie",
            "image": "movie_image.jpg",
        }

        trakt_importer = TraktImporter("testuser", self.user, "new")
        trakt_importer.process_collection()

        existing_entry.refresh_from_db()
        self.assertEqual(existing_entry.resolution, "4k")
        self.assertEqual(
            CollectionEntry.objects.filter(user=self.user, item=item).count(),
            1,
        )

    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_process_watched_movie_skips_deleted_movie(self, mock_get_metadata):
        """A movie the user deleted locally is not recreated from watch history."""
        DeletedMedia.objects.create(
            user=self.user,
            media_type=MediaTypes.MOVIE.value,
            source=Sources.TMDB.value,
            media_id="67890",
        )
        movie_entry = {
            "type": "movie",
            "movie": {"title": "Test Movie", "ids": {"tmdb": 67890}},
            "watched_at": "2023-01-02T00:00:00.000Z",
        }
        mock_get_metadata.return_value = {
            "title": "Test Movie",
            "image": "movie_image.jpg",
        }

        trakt_importer = TraktImporter("test", self.user, "new")
        trakt_importer.process_watched_movie(movie_entry)

        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.MOVIE.value]), 0)

    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_process_watched_episode_skips_deleted_show(self, mock_get_metadata):
        """A show the user deleted locally is not recreated from watch history."""
        DeletedMedia.objects.create(
            user=self.user,
            media_type=MediaTypes.TV.value,
            source=Sources.TMDB.value,
            media_id="12345",
        )
        episode_entry = {
            "type": "episode",
            "episode": {"season": 1, "number": 1, "title": "Pilot"},
            "show": {"title": "Test Show", "ids": {"tmdb": 12345}},
            "watched_at": "2023-01-01T00:00:00.000Z",
        }

        trakt_importer = TraktImporter("testuser", self.user, "new")
        trakt_importer.process_watched_episode(episode_entry)

        mock_get_metadata.assert_not_called()
        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.TV.value]), 0)
        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.SEASON.value]), 0)
        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.EPISODE.value]), 0)

    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_process_watchlist_skips_deleted_show_overwrite_mode(
        self,
        mock_get_metadata,
        mock_make_request,
    ):
        """Deletion tombstones are honored in overwrite mode too."""
        DeletedMedia.objects.create(
            user=self.user,
            media_type=MediaTypes.TV.value,
            source=Sources.TMDB.value,
            media_id="54321",
        )
        watchlist_entry = {
            "listed_at": "2023-01-01T00:00:00.000Z",
            "type": "show",
            "show": {"title": "Watchlist Show", "ids": {"tmdb": 54321}},
        }
        mock_make_request.side_effect = [[watchlist_entry], []]
        mock_get_metadata.return_value = {
            "title": "Watchlist Show",
            "image": "show_image.jpg",
        }

        trakt_importer = TraktImporter("testuser", self.user, "overwrite")
        trakt_importer.process_watchlist()

        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.TV.value]), 0)
        self.assertEqual(TV.objects.filter(user=self.user).count(), 0)

    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_deleted_movie_tombstone_cleared_on_manual_retrack(self, mock_get_metadata):
        """Manually re-adding a deleted item clears its tombstone for future imports."""
        item = Item.objects.create(
            media_id="67890",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Test Movie",
        )
        movie = Movie.objects.create(
            item=item,
            user=self.user,
            status=Status.COMPLETED.value,
        )
        movie.delete()
        self.assertTrue(
            DeletedMedia.objects.filter(
                user=self.user,
                media_type=MediaTypes.MOVIE.value,
                source=Sources.TMDB.value,
                media_id="67890",
            ).exists(),
        )

        # User manually re-tracks the movie themselves.
        Movie.objects.create(item=item, user=self.user, status=Status.PLANNING.value)
        self.assertFalse(
            DeletedMedia.objects.filter(
                user=self.user,
                media_type=MediaTypes.MOVIE.value,
                source=Sources.TMDB.value,
                media_id="67890",
            ).exists(),
        )

        movie_entry = {
            "type": "movie",
            "movie": {"title": "Test Movie", "ids": {"tmdb": 67890}},
            "watched_at": "2023-01-02T00:00:00.000Z",
        }
        mock_get_metadata.return_value = {
            "title": "Test Movie",
            "image": "movie_image.jpg",
        }

        trakt_importer = TraktImporter("test", self.user, "overwrite")
        trakt_importer.process_watched_movie(movie_entry)

        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.MOVIE.value]), 1)

    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_deleting_tv_show_prevents_resurrection_from_watch_history(
        self,
        mock_get_metadata,
    ):
        """Deleting a TV show (the reported issue #361 scenario) tombstones it."""
        tv_item = Item.objects.create(
            media_id="12345",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Test Show",
        )
        tv_obj = TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.COMPLETED.value,
        )

        tv_obj.delete()

        self.assertTrue(
            DeletedMedia.objects.filter(
                user=self.user,
                media_type=MediaTypes.TV.value,
                source=Sources.TMDB.value,
                media_id="12345",
            ).exists(),
        )

        episode_entry = {
            "type": "episode",
            "episode": {"season": 1, "number": 1, "title": "Pilot"},
            "show": {"title": "Test Show", "ids": {"tmdb": 12345}},
            "watched_at": "2023-01-01T00:00:00.000Z",
        }

        trakt_importer = TraktImporter("testuser", self.user, "new")
        trakt_importer.process_watched_episode(episode_entry)

        mock_get_metadata.assert_not_called()
        self.assertEqual(TV.objects.filter(user=self.user).count(), 0)


class ImportTraktPreferredProviderDedup(TestCase):
    """A TVDB-preferring user's Trakt import must not create a duplicate Item (#620)."""

    def setUp(self):
        """Create a TVDB-preferring user with an existing TVDB-tracked show."""
        self.user = get_user_model().objects.create_user(
            username="tvdb-pref",
            password="12345",
        )
        self.user.tv_metadata_source_default = Sources.TVDB.value
        self.user.save()

        self.existing_tv_item = Item.objects.create(
            media_id="81189",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            title="Breaking Bad",
            image="",
        )
        TV.objects.create(
            item=self.existing_tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

    @patch("integrations.imports.trakt.item_merge.find_tvdb_counterpart")
    @patch("integrations.imports.trakt.tvdb.enabled", return_value=True)
    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_reuses_existing_tvdb_item_instead_of_creating_tmdb_duplicate(
        self,
        mock_get_metadata,
        _mock_tvdb_enabled,
        mock_find_tvdb_counterpart,
    ):
        """Importing a show the user already tracks via TVDB reuses that Item."""
        mock_get_metadata.return_value = {
            "title": "Breaking Bad",
            "image": "tv_image.jpg",
            "last_episode_season": 1,
            "max_progress": 1,
        }
        mock_find_tvdb_counterpart.return_value = self.existing_tv_item

        movie_entry = {
            "type": "show",
            "show": {"title": "Breaking Bad", "ids": {"tmdb": 1396}},
            "watched_at": "2023-01-01T00:00:00.000Z",
        }
        trakt_importer = TraktImporter("testuser", self.user, "new")
        tv_item = trakt_importer._get_or_create_item(
            MediaTypes.TV.value,
            "1396",
            movie_entry["show"],
        )

        self.assertEqual(tv_item.pk, self.existing_tv_item.pk)
        self.assertFalse(
            Item.objects.filter(source=Sources.TMDB.value, media_id="1396").exists(),
        )
        mock_find_tvdb_counterpart.assert_called_once_with(
            "1396",
            MediaTypes.TV.value,
            season_number=None,
            library_media_type=MediaTypes.TV.value,
        )

    @patch("integrations.imports.trakt.item_merge.find_tvdb_counterpart")
    def test_skips_lookup_for_tmdb_preferring_user(
        self,
        mock_find_tvdb_counterpart,
    ):
        """A TMDB-preferring user's import never pays for the TVDB lookup."""
        self.user.tv_metadata_source_default = Sources.TMDB.value
        self.user.save()

        trakt_importer = TraktImporter("testuser", self.user, "new")
        item = trakt_importer._get_or_create_item(
            MediaTypes.TV.value,
            "1396",
            {"title": "Breaking Bad", "image": "tv_image.jpg"},
        )

        mock_find_tvdb_counterpart.assert_not_called()
        self.assertEqual(item.source, Sources.TMDB.value)
