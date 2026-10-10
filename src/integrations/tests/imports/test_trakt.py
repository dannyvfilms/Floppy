import json
import sqlite3
import tempfile
import threading
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, patch

import redis
import requests
from django.contrib.auth import get_user_model
from django.db import OperationalError, connection
from django.test import (
    RequestFactory,
    SimpleTestCase,
    TestCase,
    TransactionTestCase,
    override_settings,
    tag,
)
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
from app.services.grouped_anime import GroupedAnimeMatch
from integrations.imports import helpers, trakt
from integrations.imports.helpers import MediaImportError
from integrations.imports.trakt import TraktImporter, importer
from integrations.models import ExternalReference

mock_path = Path(__file__).resolve().parent.parent / "mock_data"
app_mock_path = (
    Path(__file__).resolve().parent.parent.parent.parent / "app" / "tests" / "mock_data"
)


class TraktSqliteWriteRetryTests(SimpleTestCase):
    def test_transient_lock_retries_complete_operation(self):
        with (
            patch.object(connection, "in_atomic_block", False),
            patch("integrations.imports.trakt.time.sleep") as pause,
        ):
            operation = SimpleNamespace(calls=0)

            def write():
                operation.calls += 1
                if operation.calls < 3:
                    msg = "database is locked"
                    raise OperationalError(msg)
                return "saved"

            self.assertEqual(trakt._retry_sqlite_write(write), "saved")
        self.assertEqual(operation.calls, 3)
        self.assertEqual(pause.call_count, 2)

    def test_enclosing_transaction_is_never_retried(self):
        with (
            patch.object(connection, "in_atomic_block", True),
            patch("integrations.imports.trakt.time.sleep") as pause,
            self.assertRaises(OperationalError),
        ):
            trakt._retry_sqlite_write(self._raise_lock)
        pause.assert_not_called()

    def test_exhausted_locks_are_bounded(self):
        with (
            patch.object(connection, "in_atomic_block", False),
            patch("integrations.imports.trakt.time.sleep") as pause,
            self.assertRaises(OperationalError),
        ):
            trakt._retry_sqlite_write(self._raise_lock)
        self.assertEqual(pause.call_count, trakt.SQLITE_WRITE_ATTEMPTS - 1)

    def test_long_busy_timeout_is_not_multiplied(self):
        with (
            patch.object(connection, "in_atomic_block", False),
            patch("integrations.imports.trakt.time.monotonic", side_effect=[0, 2]),
            patch("integrations.imports.trakt.time.sleep") as pause,
            self.assertRaises(OperationalError),
        ):
            trakt._retry_sqlite_write(self._raise_lock)
        pause.assert_not_called()

    @staticmethod
    def _raise_lock():
        msg = "database is locked"
        raise OperationalError(msg)


class TraktResolutionMemoTests(SimpleTestCase):
    """Import snapshots bound positive reuse and collapse confirmed misses."""

    def setUp(self):
        self.importer = object.__new__(TraktImporter)
        self.importer.warnings = []
        self.importer.user = SimpleNamespace(tv_metadata_source_default="tmdb")

    def missing_error(self, status=404, *, confirmed=True):
        response = Response()
        response.status_code = status
        error = services.ProviderAPIError("tmdb", requests.HTTPError(response=response))
        error.confirmed_absent = confirmed
        return error

    @tag("slow", "benchmark")
    def test_repeated_confirmed_absence_needs_no_redis_or_repeated_warning(self):
        with (
            patch.object(services, "get_media_metadata", side_effect=self.missing_error()) as metadata,
            patch("django.core.cache.cache.set", side_effect=redis.ConnectionError("offline")) as cache_write,
        ):
            for _ in range(80_849):
                self.assertIsNone(self.importer._get_metadata("season", "123", "Show", 1986))
        metadata.assert_called_once()
        cache_write.assert_not_called()
        self.assertEqual(len(self.importer.warnings), 1)
        self.assertEqual(len(self.importer._missing_metadata), 1)

    def test_missing_keys_distinguish_language_show_and_season(self):
        with patch.object(services, "get_media_metadata", side_effect=self.missing_error()) as metadata:
            with override_settings(TMDB_LANG="en-US"):
                for show, season in (("123", 1986), ("123", 1987), ("456", 1986)):
                    self.importer._get_metadata("season", show, "Show", season)
                self.importer._get_metadata("season", "123", "Show", "01986")
            with override_settings(TMDB_LANG="fr-FR"):
                self.importer._get_metadata("season", "123", "Show", 1986)
        self.assertEqual(metadata.call_count, 4)
        self.assertEqual(len(self.importer.warnings), 4)

    def test_generic_not_found_and_transient_errors_are_not_memoized(self):
        for error in (self.missing_error(confirmed=False), self.missing_error(503)):
            with self.subTest(status=error.status_code), patch.object(services, "get_media_metadata", side_effect=error) as metadata:
                for _ in range(2):
                    if error.status_code == 404:
                        self.assertIsNone(self.importer._get_metadata("season", "123", "Show", 1))
                    else:
                        with self.assertRaises(services.ProviderAPIError):
                            self.importer._get_metadata("season", "123", "Show", 1)
                self.assertEqual(metadata.call_count, 2)

    @tag("slow", "benchmark")
    def test_warm_metadata_and_items_do_not_repeat_resolution_operations(self):
        item = SimpleNamespace(library_media_type="tv")
        dto = {"title": "Show", "image": "image"}
        with (
            patch.object(services, "get_media_metadata", return_value=dto) as metadata,
            patch.object(Item.objects, "filter", return_value=[item]) as lookup,
        ):
            for _ in range(1000):
                resolved = self.importer._get_metadata("tv", "123", "Show")
                self.assertIs(self.importer._get_or_create_item("tv", "123", resolved), item)
        metadata.assert_called_once()
        lookup.assert_called_once()

    def test_metadata_lru_is_bounded_and_refreshes_recent_entries(self):
        with patch.object(services, "get_media_metadata", return_value={"title": "Show"}) as metadata:
            for identity in range(8):
                self.importer._get_metadata("tv", identity, "Show")
            self.importer._get_metadata("tv", 0, "Show")
            self.importer._get_metadata("tv", 8, "Show")
            self.assertEqual(len(self.importer._metadata_memo), 8)
            self.assertEqual(metadata.call_count, 9)
            self.importer._get_metadata("tv", 1, "Show")
            self.assertEqual(metadata.call_count, 10)

    def test_empty_metadata_is_not_confirmed_absence(self):
        with patch.object(services, "get_media_metadata", return_value=None) as metadata:
            for _ in range(2):
                self.assertIsNone(self.importer._get_metadata("tv", "123", "Show"))
            self.assertEqual(metadata.call_count, 2)

    def test_real_metadata_dates_are_admitted_without_changing_the_dto(self):
        dto = {"details": {"first_air_date": date(2020, 1, 1)}, "score": Decimal("1.5")}
        with patch.object(services, "get_media_metadata", return_value=dto) as metadata:
            self.assertIs(self.importer._get_metadata("tv", "123", "Show"), dto)
            self.assertIs(self.importer._get_metadata("tv", "123", "Show"), dto)
        metadata.assert_called_once()
        self.assertIsInstance(dto["details"]["first_air_date"], date)

    def test_large_or_non_json_metadata_is_returned_without_retention(self):
        for dto in ({"synopsis": "x" * (129 * 1024)}, {"value": object()}):
            with self.subTest(large="synopsis" in dto), patch.object(services, "get_media_metadata", return_value=dto) as metadata:
                for _ in range(2):
                    self.assertIs(self.importer._get_metadata("tv", "large", "Show"), dto)
                self.assertEqual(metadata.call_count, 2)
                self.assertEqual(len(self.importer._metadata_memo), 0)

    def test_item_memo_distinguishes_buckets_coordinates_and_provider_preference(self):
        tv = SimpleNamespace(library_media_type="tv")
        anime = SimpleNamespace(library_media_type="anime")
        with patch.object(Item.objects, "filter", return_value=[tv, anime]) as lookup:
            self.assertIs(self.importer._get_or_create_item("tv", "123", {}, library_media_type="tv"), tv)
            self.assertIs(self.importer._get_or_create_item("tv", "123", {}, library_media_type="anime"), anime)
            self.importer._get_or_create_item("episode", "123", {}, season_number=1, episode_number=1)
            self.importer._get_or_create_item("episode", "123", {}, season_number=1, episode_number=2)
            self.importer.user.tv_metadata_source_default = "tvdb"
            self.importer._get_or_create_item("tv", "123", {}, library_media_type="tv")
            self.assertEqual(lookup.call_count, 5)

    def test_item_lru_is_bounded_and_retains_preferred_provider_items(self):
        preferred = SimpleNamespace(library_media_type="tv", source="tvdb")
        with (
            patch.object(Item.objects, "filter", return_value=[]) as lookup,
            patch.object(self.importer, "_find_preferred_provider_item", return_value=preferred) as resolve,
        ):
            for identity in range(65):
                self.assertIs(self.importer._get_or_create_item("tv", identity, {}), preferred)
            self.assertEqual(len(self.importer._item_memo), 64)
            self.importer._get_or_create_item("tv", 64, {})
            self.assertEqual(resolve.call_count, 65)
            self.importer._get_or_create_item("tv", 0, {})
            self.assertEqual(lookup.call_count, 66)
            self.assertEqual(resolve.call_count, 66)

    def test_unknown_play_runtime_is_reread_until_enrichment_supplies_it(self):
        unknown = SimpleNamespace(library_media_type="episode", runtime_minutes=0)
        enriched = SimpleNamespace(library_media_type="episode", runtime_minutes=30)
        with patch.object(Item.objects, "filter", side_effect=[[unknown], [enriched]]) as lookup:
            self.assertIs(self.importer._get_or_create_item("episode", "123", {}, 1, 1), unknown)
            self.assertIs(self.importer._get_or_create_item("episode", "123", {}, 1, 1), enriched)
            self.assertIs(self.importer._get_or_create_item("episode", "123", {}, 1, 1), enriched)
        self.assertEqual(lookup.call_count, 2)

    def test_reference_reuses_only_current_entry_and_observes_next_correction(self):
        self.importer.external_reference_integration = "trakt"
        show = {"title": "Show", "ids": {"trakt": 10, "tmdb": 123}}
        corrected = SimpleNamespace(
            review_status="matched", episode_mapping={"1986:3": [2, 7]},
        )
        with (
            patch.object(trakt.external_references, "lookup_reference", side_effect=[None, corrected]) as lookup,
            patch.object(trakt.external_references, "reference_target", return_value=None),
        ):
            self.assertEqual(self.importer._get_tmdb_id(show, "tv"), "123")
            self.assertIsNone(self.importer._get_trakt_reference(show, "tv"))
            self.assertEqual(lookup.call_count, 1)
            # Deliberately reuse the same input object on the next entry.
            self.assertEqual(self.importer._get_tmdb_id(show, "tv"), "123")
            reference = self.importer._get_trakt_reference(show, "tv")
            self.assertEqual(lookup.call_count, 2)
            self.assertEqual(
                trakt.external_references.map_episode_coordinates(reference, 1986, 3),
                (2, 7),
            )


class ImportTrakt(TestCase):
    """Test importing media from Trakt."""

    def setUp(self):
        """Create user for the tests."""
        credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**credentials)

    def test_history_year_coordinate_only_changes_with_explicit_mapping(self):
        """Trakt's episode.season is not implicitly interpreted as a year."""
        entry = {
            "show": {"title": "Diagnostic show", "ids": {"tmdb": 123}},
            "episode": {"season": 1986, "number": 3},
            "watched_at": "2023-01-02T00:00:00.000Z",
        }
        for reference, expected_season in (
            (None, 1986),
            (SimpleNamespace(episode_mapping={"1986:3": [2, 7]}), 2),
        ):
            with self.subTest(mapped=reference is not None):
                trakt_importer = TraktImporter("test", self.user, "new")
                with (
                    patch.object(trakt_importer, "_get_tmdb_id", return_value="123"),
                    patch.object(trakt_importer, "_get_trakt_reference", return_value=reference),
                    patch.object(trakt_importer, "_get_metadata", side_effect=[{"title": "Diagnostic show"}, None]) as metadata,
                ):
                    trakt_importer.process_watched_episode(entry)
                self.assertEqual(
                    metadata.call_args_list,
                    [
                        call("tv", "123", "Diagnostic show"),
                        call("season", "123", "Diagnostic show", expected_season),
                    ],
                )

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

        # Reprocessing the exact same entry is a duplicate play (issue #854)
        # and must not create a second row.
        trakt_importer.process_watched_movie(movie_entry)
        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.MOVIE.value]), 1)

    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_process_watched_movie_dedupes_nearby_play(self, mock_get_metadata):
        """A movie watch within the dedupe window of an existing play is skipped."""
        mock_get_metadata.return_value = {
            "title": "Test Movie",
            "image": "movie_image.jpg",
        }

        trakt_importer = TraktImporter("test", self.user, "new")
        trakt_importer.process_watched_movie(
            {
                "type": "movie",
                "movie": {"title": "Test Movie", "ids": {"tmdb": 67890}},
                "watched_at": "2023-01-02T00:00:00.000Z",
            },
        )
        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.MOVIE.value]), 1)

        # 10 minutes later, same movie: within the 15 minute dedupe window.
        trakt_importer.process_watched_movie(
            {
                "type": "movie",
                "movie": {"title": "Test Movie", "ids": {"tmdb": 67890}},
                "watched_at": "2023-01-02T00:10:00.000Z",
            },
        )
        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.MOVIE.value]), 1)

        # 1 day later, same movie: a legitimate rewatch outside the window.
        trakt_importer.process_watched_movie(
            {
                "type": "movie",
                "movie": {"title": "Test Movie", "ids": {"tmdb": 67890}},
                "watched_at": "2023-01-03T00:00:00.000Z",
            },
        )
        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.MOVIE.value]), 2)

        # A different movie at a nearby time is not a duplicate.
        mock_get_metadata.return_value = {
            "title": "Other Movie",
            "image": "movie_image.jpg",
        }
        trakt_importer.process_watched_movie(
            {
                "type": "movie",
                "movie": {"title": "Other Movie", "ids": {"tmdb": 11111}},
                "watched_at": "2023-01-03T00:05:00.000Z",
            },
        )
        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.MOVIE.value]), 3)

    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_process_watched_movie_dedupes_against_existing_db_play(
        self,
        mock_get_metadata,
    ):
        """A Trakt-imported play is skipped if it's near an existing DB play (e.g. webhook)."""
        item = Item.objects.get_or_create(
            media_id="67890",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={"title": "Test Movie"},
        )[0]
        Movie.objects.create(
            item=item,
            user=self.user,
            end_date="2023-01-02T00:00:00Z",
            status=Status.COMPLETED.value,
            progress=1,
        )

        mock_get_metadata.return_value = {
            "title": "Test Movie",
            "image": "movie_image.jpg",
        }
        trakt_importer = TraktImporter("test", self.user, "new")
        trakt_importer.process_watched_movie(
            {
                "type": "movie",
                "movie": {"title": "Test Movie", "ids": {"tmdb": 67890}},
                "watched_at": "2023-01-02T00:12:00.000Z",
            },
        )

        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.MOVIE.value]), 0)

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
    def test_process_watched_episode_dedupes_nearby_play(self, mock_get_metadata):
        """An episode watch within the dedupe window of an existing play is skipped."""

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
                        {
                            "episode_number": 2,
                            "still_path": "/still2.jpg",
                            "title": "Episode 2 Title",
                        },
                    ],
                    "max_progress": 2,
                }
            return None

        mock_get_metadata.side_effect = mock_metadata_side_effect

        episode_entry = {
            "type": "episode",
            "episode": {"season": 1, "number": 1, "title": "Pilot"},
            "show": {"title": "Test Show", "ids": {"tmdb": 12345}},
            "watched_at": "2023-01-01T00:00:00.000Z",
        }

        trakt_importer = TraktImporter("testuser", self.user, "new")
        trakt_importer.process_watched_episode(episode_entry)
        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.EPISODE.value]), 1)

        # 10 minutes later, same episode: within the 15 minute dedupe window.
        trakt_importer.process_watched_episode(
            {
                **episode_entry,
                "watched_at": "2023-01-01T00:10:00.000Z",
            },
        )
        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.EPISODE.value]), 1)

        # A different episode of the same show at a nearby time is not a duplicate.
        trakt_importer.process_watched_episode(
            {
                "type": "episode",
                "episode": {"season": 1, "number": 2, "title": "Episode 2"},
                "show": {"title": "Test Show", "ids": {"tmdb": 12345}},
                "watched_at": "2023-01-01T00:12:00.000Z",
            },
        )
        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.EPISODE.value]), 2)

    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_process_watched_episode_dedupes_against_existing_db_play(
        self,
        mock_get_metadata,
    ):
        """A Trakt-imported episode play is skipped if it's near an existing DB play."""
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
            related_tv=tv_obj,
            user=self.user,
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
        Episode.objects.create(
            item=episode_item,
            related_season=season_obj,
            end_date="2023-01-01T00:00:00Z",
        )

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
        trakt_importer.process_watched_episode(
            {
                "type": "episode",
                "episode": {"season": 1, "number": 1, "title": "Pilot"},
                "show": {"title": "Test Show", "ids": {"tmdb": 12345}},
                "watched_at": "2023-01-01T00:12:00.000Z",
            },
        )

        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.EPISODE.value]), 0)

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

    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_last_episode_import_marks_season_and_tv_completed_in_overwrite_mode(
        self, mock_get_metadata
    ):
        """Regression test for #202: an overwrite re-sync marks season/TV
        completed when the last episode is imported.

        Following #375, this completion cascade only applies in "overwrite"
        mode (an explicit re-sync) — see
        test_last_episode_import_does_not_complete_existing_show_in_new_mode
        for the "new" mode (default recurring sync) case, which must leave
        an already-tracked show's status alone.
        """
        TMDB_ID = 99999
        SEASON_NUMBER = 1
        TOTAL_EPISODES = 20

        # Pre-create TV, season in DB (simulates prior sync of eps 1-19)
        item_tv, _ = Item.objects.get_or_create(
            media_id=TMDB_ID,
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            defaults={"title": "Test Show", "image": ""},
        )
        tv_obj = TV.objects.create(
            item=item_tv, user=self.user, status=Status.IN_PROGRESS.value
        )
        item_season, _ = Item.objects.get_or_create(
            media_id=TMDB_ID,
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=SEASON_NUMBER,
            defaults={"title": "Test Show", "image": ""},
        )
        season_obj = Season.objects.create(
            item=item_season,
            user=self.user,
            related_tv=tv_obj,
            status=Status.IN_PROGRESS.value,
        )

        def mock_metadata(media_type, tmdb_id, title, season_number=None):
            if media_type == MediaTypes.TV.value:
                return {
                    "title": "Test Show",
                    "image": "",
                    "last_episode_season": SEASON_NUMBER,
                    "max_progress": TOTAL_EPISODES,
                }
            if media_type == MediaTypes.SEASON.value:
                return {
                    "title": "Season 1",
                    "image": "",
                    "episodes": [
                        {"episode_number": i, "still_path": None}
                        for i in range(1, TOTAL_EPISODES + 1)
                    ],
                    "max_progress": TOTAL_EPISODES,
                }
            return None

        mock_get_metadata.side_effect = mock_metadata

        entry = {
            "type": "episode",
            "episode": {
                "season": SEASON_NUMBER,
                "number": TOTAL_EPISODES,
                "title": "Finale",
            },
            "show": {"title": "Test Show", "ids": {"tmdb": TMDB_ID}},
            "watched_at": "2024-06-01T00:00:00.000Z",
        }

        trakt_importer = TraktImporter("testuser", self.user, "overwrite")
        trakt_importer.process_watched_episode(entry)
        helpers.cleanup_existing_media(trakt_importer.to_delete, trakt_importer.user)
        helpers.bulk_create_media(trakt_importer.bulk_media, self.user)

        # This is the persistence step that the fix adds to import_data()
        from simple_history.utils import bulk_update_with_history

        if trakt_importer.completed_seasons:
            bulk_update_with_history(
                trakt_importer.completed_seasons, Season, fields=["status"]
            )
        if trakt_importer.completed_tvs:
            bulk_update_with_history(
                trakt_importer.completed_tvs, TV, fields=["status"]
            )

        # Overwrite mode deletes and recreates the rows, so re-query rather
        # than refresh the pre-existing instances.
        new_tv = TV.objects.get(user=self.user, item__media_id=str(TMDB_ID))
        new_season = Season.objects.get(
            user=self.user,
            item__media_id=str(TMDB_ID),
            item__season_number=SEASON_NUMBER,
        )
        self.assertEqual(new_season.status, Status.COMPLETED.value)
        self.assertEqual(new_tv.status, Status.COMPLETED.value)

    @patch("app.models.providers.services.get_media_metadata")
    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_import_data_cascades_completed_tv_status_to_other_seasons(
        self, mock_get_metadata, mock_get_media_metadata
    ):
        """Regression test for #985: a show that Trakt import marks
        Completed must also cascade that completion down to its other
        seasons/episodes, exactly like manually marking a show Completed in
        the UI does (TV.save() -> _completed()). The bulk_update_with_history
        flush in import_data() never calls TV.save(), so without the fix
        this cascade is silently skipped.
        """
        TMDB_ID = 99997
        SEASON_NUMBER = 2
        TOTAL_EPISODES = 5

        # Season 1 already exists and is only partially watched; it isn't
        # touched by the watch-history entry below, so only the completion
        # cascade (not the history walk) can bring it to Completed.
        item_tv, _ = Item.objects.get_or_create(
            media_id=TMDB_ID,
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            defaults={"title": "Test Show", "image": ""},
        )
        tv_obj = TV.objects.create(
            item=item_tv, user=self.user, status=Status.IN_PROGRESS.value
        )
        item_season1, _ = Item.objects.get_or_create(
            media_id=TMDB_ID,
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            defaults={"title": "Test Show", "image": ""},
        )
        Season.objects.create(
            item=item_season1,
            user=self.user,
            related_tv=tv_obj,
            status=Status.IN_PROGRESS.value,
        )

        def mock_metadata(media_type, tmdb_id, title, season_number=None):
            if media_type == MediaTypes.TV.value:
                return {
                    "title": "Test Show",
                    "image": "",
                    "last_episode_season": SEASON_NUMBER,
                    "max_progress": TOTAL_EPISODES,
                }
            if media_type == MediaTypes.SEASON.value:
                return {
                    "title": f"Season {season_number}",
                    "image": "",
                    "episodes": [
                        {"episode_number": i, "still_path": None}
                        for i in range(1, TOTAL_EPISODES + 1)
                    ],
                    "max_progress": TOTAL_EPISODES,
                }
            return None

        mock_get_metadata.side_effect = mock_metadata

        # Metadata used by TV._completed(), the cascade helper the fix wires
        # up. It reports season 1 as the only remaining incomplete season.
        mock_get_media_metadata.return_value = {
            "max_progress": TOTAL_EPISODES,
            "related": {"seasons": [{"season_number": 1, "image": ""}]},
            "season/1": {
                "image": "",
                "season_number": 1,
                "episodes": [{"episode_number": i} for i in range(1, TOTAL_EPISODES + 1)],
            },
        }

        entry = {
            "type": "episode",
            "episode": {
                "season": SEASON_NUMBER,
                "number": TOTAL_EPISODES,
                "title": "Finale",
            },
            "show": {"title": "Test Show", "ids": {"tmdb": TMDB_ID}},
            "watched_at": "2024-06-01T00:00:00.000Z",
        }

        trakt_importer = TraktImporter("testuser", self.user, "overwrite")
        trakt_importer.process_watched_episode(entry)
        trakt_importer.process_history = lambda: None
        trakt_importer.process_watchlist = lambda: None
        trakt_importer.process_ratings = lambda: None
        trakt_importer.process_notes = lambda: None
        trakt_importer.process_comments = lambda: None
        trakt_importer.process_collection = lambda: None
        trakt_importer.process_dropped = lambda: None
        trakt_importer._validate_username = lambda: None

        trakt_importer.import_data()

        season1 = Season.objects.get(
            user=self.user,
            item__media_id=str(TMDB_ID),
            item__season_number=1,
        )
        self.assertEqual(season1.status, Status.COMPLETED.value)
        self.assertTrue(season1.episodes.exists())

    @patch("app.models.providers.services.get_media_metadata")
    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_new_mode_import_does_not_fabricate_earlier_seasons_from_one_finale(
        self, mock_get_metadata, mock_get_media_metadata
    ):
        """Regression test for #1178: a "new"-mode import (a first-time Trakt
        export/history import) must not treat a single watched finale as
        proof the whole series was watched. Watching S2's last episode of a
        show that has other seasons the import never touched must not
        trigger TV._completed()'s fan-out, which would fabricate every
        missing season/episode dated "today" -- exactly the bug reported
        (thousands of phantom episodes logged against the import date).
        """
        TMDB_ID = 99999
        SEASON_NUMBER = 2
        TOTAL_EPISODES = 5

        def mock_metadata(media_type, tmdb_id, title, season_number=None):
            if media_type == MediaTypes.TV.value:
                return {
                    "title": "Test Show",
                    "image": "",
                    "last_episode_season": SEASON_NUMBER,
                    "max_progress": TOTAL_EPISODES,
                }
            if media_type == MediaTypes.SEASON.value:
                return {
                    "title": f"Season {season_number}",
                    "image": "",
                    "episodes": [
                        {"episode_number": i, "still_path": None}
                        for i in range(1, TOTAL_EPISODES + 1)
                    ],
                    "max_progress": TOTAL_EPISODES,
                }
            return None

        mock_get_metadata.side_effect = mock_metadata

        entry = {
            "type": "episode",
            "episode": {
                "season": SEASON_NUMBER,
                "number": TOTAL_EPISODES,
                "title": "Finale",
            },
            "show": {"title": "Test Show", "ids": {"tmdb": TMDB_ID}},
            "watched_at": "2024-06-01T00:00:00.000Z",
        }

        trakt_importer = TraktImporter("testuser", self.user, "new")
        trakt_importer.process_watched_episode(entry)
        trakt_importer.process_history = lambda: None
        trakt_importer.process_watchlist = lambda: None
        trakt_importer.process_ratings = lambda: None
        trakt_importer.process_notes = lambda: None
        trakt_importer.process_comments = lambda: None
        trakt_importer.process_collection = lambda: None
        trakt_importer.process_dropped = lambda: None
        trakt_importer._validate_username = lambda: None

        trakt_importer.import_data()

        # Never asked to fetch the full show's metadata to fan out episodes.
        mock_get_media_metadata.assert_not_called()

        tv_obj = TV.objects.get(user=self.user, item__media_id=str(TMDB_ID))
        self.assertEqual(tv_obj.status, Status.IN_PROGRESS.value)
        self.assertFalse(
            Season.objects.filter(
                user=self.user,
                item__media_id=str(TMDB_ID),
                item__season_number=1,
            ).exists(),
        )

    @patch("app.models.providers.services.get_media_metadata")
    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_completion_cascade_dates_fabricated_episodes_from_the_watch_not_today(
        self, mock_get_metadata, mock_get_media_metadata
    ):
        """Regression test for #1178: when the overwrite-mode completion
        cascade does legitimately fire (see
        test_import_data_cascades_completed_tv_status_to_other_seasons), the
        episodes it fabricates for other seasons must be dated from the
        watch event that triggered completion, not from timezone.now(). The
        reported bug showed thousands of episodes logged as watched "today"
        purely because the import ran today.
        """
        TMDB_ID = 99995
        SEASON_NUMBER = 2
        TOTAL_EPISODES = 5
        WATCHED_AT = "2016-03-04T00:00:00.000Z"

        item_tv, _ = Item.objects.get_or_create(
            media_id=TMDB_ID,
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            defaults={"title": "Test Show", "image": ""},
        )
        tv_obj = TV.objects.create(
            item=item_tv, user=self.user, status=Status.IN_PROGRESS.value
        )
        item_season1, _ = Item.objects.get_or_create(
            media_id=TMDB_ID,
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            defaults={"title": "Test Show", "image": ""},
        )
        Season.objects.create(
            item=item_season1,
            user=self.user,
            related_tv=tv_obj,
            status=Status.IN_PROGRESS.value,
        )

        def mock_metadata(media_type, tmdb_id, title, season_number=None):
            if media_type == MediaTypes.TV.value:
                return {
                    "title": "Test Show",
                    "image": "",
                    "last_episode_season": SEASON_NUMBER,
                    "max_progress": TOTAL_EPISODES,
                }
            if media_type == MediaTypes.SEASON.value:
                return {
                    "title": f"Season {season_number}",
                    "image": "",
                    "episodes": [
                        {"episode_number": i, "still_path": None}
                        for i in range(1, TOTAL_EPISODES + 1)
                    ],
                    "max_progress": TOTAL_EPISODES,
                }
            return None

        mock_get_metadata.side_effect = mock_metadata

        mock_get_media_metadata.return_value = {
            "max_progress": TOTAL_EPISODES,
            "related": {"seasons": [{"season_number": 1, "image": ""}]},
            "season/1": {
                "image": "",
                "season_number": 1,
                "episodes": [{"episode_number": i} for i in range(1, TOTAL_EPISODES + 1)],
            },
        }

        entry = {
            "type": "episode",
            "episode": {
                "season": SEASON_NUMBER,
                "number": TOTAL_EPISODES,
                "title": "Finale",
            },
            "show": {"title": "Test Show", "ids": {"tmdb": TMDB_ID}},
            "watched_at": WATCHED_AT,
        }

        trakt_importer = TraktImporter("testuser", self.user, "overwrite")
        trakt_importer.process_watched_episode(entry)
        trakt_importer.process_history = lambda: None
        trakt_importer.process_watchlist = lambda: None
        trakt_importer.process_ratings = lambda: None
        trakt_importer.process_notes = lambda: None
        trakt_importer.process_comments = lambda: None
        trakt_importer.process_collection = lambda: None
        trakt_importer.process_dropped = lambda: None
        trakt_importer._validate_username = lambda: None

        trakt_importer.import_data()

        season1 = Season.objects.get(
            user=self.user,
            item__media_id=str(TMDB_ID),
            item__season_number=1,
        )
        fabricated_episodes = list(season1.episodes.all())
        self.assertTrue(fabricated_episodes)
        for episode in fabricated_episodes:
            self.assertEqual(episode.end_date, trakt._parse_watched_at(WATCHED_AT))

    def test_import_data_cascades_dropped_tv_status_to_in_progress_seasons(self):
        """Regression test for #985: a show hidden/dropped on Trakt must
        have its in-progress seasons marked Dropped too, matching what
        manually dropping a show does via TV.save() ->
        _mark_in_progress_seasons_as_dropped(). Without the fix, the bulk
        flush in import_data() only updates the TV row's own status.
        """
        TMDB_ID = 99996

        item_tv, _ = Item.objects.get_or_create(
            media_id=TMDB_ID,
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            defaults={"title": "Test Show", "image": ""},
        )
        tv_obj = TV.objects.create(
            item=item_tv, user=self.user, status=Status.IN_PROGRESS.value
        )
        item_season, _ = Item.objects.get_or_create(
            media_id=TMDB_ID,
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            defaults={"title": "Test Show", "image": ""},
        )
        Season.objects.create(
            item=item_season,
            user=self.user,
            related_tv=tv_obj,
            status=Status.IN_PROGRESS.value,
        )

        trakt_importer = TraktImporter("testuser", self.user, "overwrite")
        trakt_importer.dropped_tmdb_ids.add(TMDB_ID)
        tv_obj.status = Status.DROPPED.value
        trakt_importer.dropped_tvs.append(tv_obj)

        trakt_importer.process_dropped = lambda: None
        trakt_importer.process_history = lambda: None
        trakt_importer.process_watchlist = lambda: None
        trakt_importer.process_ratings = lambda: None
        trakt_importer.process_notes = lambda: None
        trakt_importer.process_comments = lambda: None
        trakt_importer.process_collection = lambda: None
        trakt_importer._validate_username = lambda: None

        trakt_importer.import_data()

        season = Season.objects.get(
            user=self.user,
            item__media_id=str(TMDB_ID),
            item__season_number=1,
        )
        self.assertEqual(season.status, Status.DROPPED.value)

    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_last_episode_import_does_not_complete_existing_show_in_new_mode(
        self, mock_get_metadata
    ):
        """Regression test for #375: a "new"-mode sync (the default for
        recurring/scheduled imports) must not silently flip an already-
        tracked show's status to Completed just because Trakt's watch
        history now reaches the last known episode — the user may have
        manually set the status, or the provider's season data may be
        stale (e.g. a new season confirmed but not yet reflected).
        """
        TMDB_ID = 99998
        SEASON_NUMBER = 1
        TOTAL_EPISODES = 20

        item_tv, _ = Item.objects.get_or_create(
            media_id=TMDB_ID,
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            defaults={"title": "Test Show", "image": ""},
        )
        tv_obj = TV.objects.create(
            item=item_tv, user=self.user, status=Status.IN_PROGRESS.value
        )
        item_season, _ = Item.objects.get_or_create(
            media_id=TMDB_ID,
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=SEASON_NUMBER,
            defaults={"title": "Test Show", "image": ""},
        )
        Season.objects.create(
            item=item_season,
            user=self.user,
            related_tv=tv_obj,
            status=Status.IN_PROGRESS.value,
        )

        def mock_metadata(media_type, tmdb_id, title, season_number=None):
            if media_type == MediaTypes.TV.value:
                return {
                    "title": "Test Show",
                    "image": "",
                    "last_episode_season": SEASON_NUMBER,
                    "max_progress": TOTAL_EPISODES,
                }
            if media_type == MediaTypes.SEASON.value:
                return {
                    "title": "Season 1",
                    "image": "",
                    "episodes": [
                        {"episode_number": i, "still_path": None}
                        for i in range(1, TOTAL_EPISODES + 1)
                    ],
                    "max_progress": TOTAL_EPISODES,
                }
            return None

        mock_get_metadata.side_effect = mock_metadata

        entry = {
            "type": "episode",
            "episode": {
                "season": SEASON_NUMBER,
                "number": TOTAL_EPISODES,
                "title": "Finale",
            },
            "show": {"title": "Test Show", "ids": {"tmdb": TMDB_ID}},
            "watched_at": "2024-06-01T00:00:00.000Z",
        }

        trakt_importer = TraktImporter("testuser", self.user, "new")
        trakt_importer.process_watched_episode(entry)

        self.assertEqual(len(trakt_importer.completed_seasons), 0)
        self.assertEqual(len(trakt_importer.completed_tvs), 0)

    # ------------------------------------------------------------------
    # Episode rating import — gap coverage
    # ------------------------------------------------------------------

    def _make_tv_season_episode(
        self, tmdb_id, season_num, episode_num, initial_score=None
    ):
        """Helper: create TV → Season → Episode hierarchy and return all three objects."""
        tv_item, _ = Item.objects.get_or_create(
            media_id=str(tmdb_id),
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
            media_id=str(tmdb_id),
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=season_num,
            defaults={"title": f"Season {season_num}"},
        )
        season_obj, _ = Season.objects.get_or_create(
            item=season_item,
            user=self.user,
            defaults={"related_tv": tv_obj, "status": Status.IN_PROGRESS.value},
        )
        episode_item, _ = Item.objects.get_or_create(
            media_id=str(tmdb_id),
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=season_num,
            episode_number=episode_num,
            defaults={"title": f"S{season_num}E{episode_num}"},
        )
        kwargs = {"related_season": season_obj}
        if initial_score is not None:
            kwargs["score"] = initial_score
        episode_obj, _ = Episode.objects.get_or_create(item=episode_item, **kwargs)
        return tv_obj, season_obj, episode_obj

    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    def test_episode_rating_multiple_episodes(self, mock_make_request):
        """All episode ratings in a single batch are applied correctly."""
        TMDB_ID = 55500
        _, _, ep1 = self._make_tv_season_episode(TMDB_ID, 1, 1)
        _, _, ep2 = self._make_tv_season_episode(TMDB_ID, 1, 2)
        _, _, ep3 = self._make_tv_season_episode(TMDB_ID, 1, 3)

        mock_make_request.side_effect = [
            [
                {
                    "rated_at": "2024-01-01T00:00:00.000Z",
                    "type": "episode",
                    "show": {"title": "Test Show", "ids": {"tmdb": TMDB_ID}},
                    "episode": {"season": 1, "number": 1, "title": "Pilot"},
                    "rating": 7,
                },
                {
                    "rated_at": "2024-01-01T00:00:00.000Z",
                    "type": "episode",
                    "show": {"title": "Test Show", "ids": {"tmdb": TMDB_ID}},
                    "episode": {"season": 1, "number": 2, "title": "Episode 2"},
                    "rating": 8,
                },
                {
                    "rated_at": "2024-01-01T00:00:00.000Z",
                    "type": "episode",
                    "show": {"title": "Test Show", "ids": {"tmdb": TMDB_ID}},
                    "episode": {"season": 1, "number": 3, "title": "Episode 3"},
                    "rating": 9,
                },
            ],
            [],
        ]

        TraktImporter("testuser", self.user, "new").process_ratings()

        ep1.refresh_from_db()
        ep2.refresh_from_db()
        ep3.refresh_from_db()
        self.assertEqual(float(ep1.score), 7.0)
        self.assertEqual(float(ep2.score), 8.0)
        self.assertEqual(float(ep3.score), 9.0)

    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    def test_episode_rating_overwrites_existing_score(self, mock_make_request):
        """A new rating overwrites an episode's pre-existing score."""
        TMDB_ID = 55501
        _, _, episode_obj = self._make_tv_season_episode(
            TMDB_ID, 1, 1, initial_score="5.0"
        )

        mock_make_request.side_effect = [
            [
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

        TraktImporter("testuser", self.user, "new").process_ratings()

        episode_obj.refresh_from_db()
        self.assertEqual(float(episode_obj.score), 9.0)

    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    def test_episode_rating_no_episode_row(self, mock_make_request):
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
    def test_episode_rating_no_tmdb_id(self, mock_make_request):
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

    @patch("integrations.imports.trakt.services.search")
    def test_get_tmdb_id_falls_back_to_title_search(self, mock_search):
        """Trakt export missing a tmdb id (#965) is resolved via title search."""
        mock_search.return_value = {
            "results": [{"media_id": 76942, "title": "OSL 24/7", "year": 2023}],
        }
        trakt_importer = TraktImporter("testuser", self.user, "new")

        tmdb_id = trakt_importer._get_tmdb_id(
            {"title": "OSL 24-7", "year": 2023, "ids": {"tmdb": None}},
            MediaTypes.TV.value,
        )

        self.assertEqual(tmdb_id, "76942")
        mock_search.assert_called_once_with(
            MediaTypes.TV.value,
            "OSL 24-7",
            1,
            source=Sources.TMDB.value,
        )
        self.assertEqual(trakt_importer.warnings, [])

    @patch("integrations.imports.trakt.services.search")
    def test_get_tmdb_id_warns_when_title_search_finds_nothing(self, mock_search):
        """No tmdb id and no search match still records the existing warning."""
        mock_search.return_value = {"results": []}
        trakt_importer = TraktImporter("testuser", self.user, "new")

        tmdb_id = trakt_importer._get_tmdb_id(
            {"title": "OSL 24-7", "year": 2023, "ids": {}},
            MediaTypes.TV.value,
        )

        self.assertIsNone(tmdb_id)
        self.assertIn(
            "OSL 24-7: No The Movie Database ID found.",
            trakt_importer.warnings,
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

    def test_process_history_database_failure_aborts_without_skipping(self):
        """Persistent locking must fail the run instead of losing a watch."""
        trakt_importer = TraktImporter("testuser", self.user, "new")
        entry = {"type": "movie", "movie": {"title": "Test"},
                 "watched_at": "2023-01-01T00:00:00Z"}
        with (
            patch.object(trakt_importer, "_get_paginated_data", return_value=[entry]),
            patch.object(trakt_importer, "process_watched_movie",
                         side_effect=OperationalError("database is locked")),
            self.assertRaisesMessage(MediaImportError, "database write failed"),
        ):
            trakt_importer.process_history()
        self.assertFalse(trakt_importer.warnings)

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


@tag("slow", "benchmark")
class TraktSqliteWriteContentionTests(TransactionTestCase):
    """Real rollback-journal writer contention against a disposable file."""

    def test_reference_lock_retry_preserves_every_watch_once(self):
        self._run_locked_history(existing_item=True)

    def test_item_lock_retry_preserves_every_watch_once(self):
        self._run_locked_history(existing_item=False)

    def _run_locked_history(self, *, existing_item):
        if connection.vendor != "sqlite":
            self.skipTest("SQLite lock semantics")
        user = get_user_model().objects.create_user(username="lock-test")
        item = None
        if existing_item:
            item = Item.objects.create(media_id="67890", source=Sources.TMDB.value,
                                       media_type=MediaTypes.MOVIE.value, title="Test Movie",
                                       image="movie.jpg")
        ExternalReference.objects.create(
            user=user, integration="trakt", source_account="test",
            external_namespace="trakt", external_identity="123",
            media_type=MediaTypes.MOVIE.value, matched_item=item,
            metadata={"title": "Old title"},
        )
        importer_instance = TraktImporter("test", user, "new")
        original_name = connection.settings_dict["NAME"]
        original_connection = connection.connection
        with tempfile.TemporaryDirectory() as directory:
            database_path = str(Path(directory) / "contention.sqlite3")
            with closing(sqlite3.connect(database_path)) as database, database:
                original_connection.backup(database)
                database.execute("PRAGMA journal_mode=DELETE")
            connection.connection = None
            connection.settings_dict["NAME"] = database_path
            locked = threading.Event()
            release = threading.Event()
            failures = []

            def competing_writer():
                try:
                    with closing(sqlite3.connect(database_path, timeout=1)) as database, database:
                        database.execute("BEGIN IMMEDIATE")
                        database.execute("UPDATE integrations_externalreference SET metadata = metadata")
                        locked.set()
                        self.assertTrue(release.wait(5), "test writer was not released")
                except Exception as error:
                    failures.append(error)
                    locked.set()

            thread = threading.Thread(target=competing_writer)
            try:
                connection.ensure_connection()
                with connection.cursor() as cursor:
                    cursor.execute("PRAGMA busy_timeout=50")
                thread.start()
                self.assertTrue(locked.wait(5))
                self.assertFalse(failures)

                def release_on_retry(_delay):
                    release.set()
                    thread.join(5)
                    self.assertFalse(thread.is_alive())

                entries = [
                    {"type": "movie", "movie": {"title": "Test Movie",
                      "ids": {"tmdb": 67890, "trakt": 123}},
                     "watched_at": f"2023-01-0{day}T00:00:00Z"}
                    for day in (2, 1)
                ]
                with (
                    patch.object(importer_instance, "_get_paginated_data", return_value=entries),
                    patch.object(importer_instance, "_get_metadata",
                                 return_value={"title": "Test Movie", "image": "movie.jpg"}),
                    patch("integrations.imports.trakt.time.sleep", side_effect=release_on_retry) as pause,
                ):
                    importer_instance.process_history()
                self.assertEqual(pause.call_count, 1)
                helpers.bulk_create_media(importer_instance.bulk_media, user)
                self.assertEqual(Movie.objects.filter(user=user).count(), 2)
                self.assertEqual(Item.objects.filter(media_id="67890").count(), 1)
                self.assertEqual(ExternalReference.objects.filter(user=user).count(), 1)
                self.assertFalse(importer_instance.warnings)
                self.assertFalse(failures)
            finally:
                release.set()
                if thread.ident is not None:
                    thread.join(5)
                connection.close()
                connection.settings_dict["NAME"] = original_name
                connection.connection = original_connection


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


class ImportTraktAnimeRouting(TestCase):
    """Trakt had no anime handling at all, so anime always landed in TV."""

    def setUp(self):
        """Create a TMDB-preferring user with the Anime library enabled."""
        self.user = get_user_model().objects.create_user(
            username="trakt-anime",
            password="12345",
        )
        self.user.anime_metadata_source_default = Sources.TMDB.value
        self.user.save()

        self.match = GroupedAnimeMatch(
            decision="move",
            reason="exact_external_id_and_animation_genre",
            tmdb_id="1396",
            mal_ids=("12345",),
        )
        self.tv_metadata = {
            "title": "Anime Show",
            "image": "tv_image.jpg",
            "last_episode_season": 1,
            "max_progress": 1,
            "episodes": [{"episode_number": 1, "title": "One", "image": ""}],
        }

    def _importer(self):
        return TraktImporter("testuser", self.user, "new")

    def test_classified_anime_buckets_the_whole_item_tree(self):
        """Show, season and episode Items must all land in the anime bucket."""
        importer_instance = self._importer()
        with patch(
            "app.services.grouped_anime.classify_tv_metadata",
            return_value=self.match,
        ):
            bucket = importer_instance._anime_bucket_for_show("1396", self.tv_metadata)
            tv_item = importer_instance._get_or_create_item(
                MediaTypes.TV.value,
                "1396",
                self.tv_metadata,
                library_media_type=bucket,
            )
            season_item = importer_instance._get_or_create_item(
                MediaTypes.SEASON.value,
                "1396",
                self.tv_metadata,
                1,
                library_media_type=bucket,
            )
            episode_item = importer_instance._get_or_create_item(
                MediaTypes.EPISODE.value,
                "1396",
                self.tv_metadata,
                1,
                1,
                library_media_type=bucket,
            )

        for item in (tv_item, season_item, episode_item):
            self.assertEqual(item.library_media_type, MediaTypes.ANIME.value)

    def test_plain_tv_show_is_untouched(self):
        """A show the classifier rejects keeps its ordinary TV bucket."""
        importer_instance = self._importer()
        with patch(
            "app.services.grouped_anime.classify_tv_metadata",
            return_value=None,
        ):
            bucket = importer_instance._anime_bucket_for_show("1396", self.tv_metadata)
            tv_item = importer_instance._get_or_create_item(
                MediaTypes.TV.value,
                "1396",
                self.tv_metadata,
                library_media_type=bucket,
            )

        self.assertIsNone(bucket)
        self.assertEqual(tv_item.library_media_type, MediaTypes.TV.value)

    def test_sticks_to_an_existing_grouped_home(self):
        """An existing anime home wins even when the classifier says nothing."""
        grouped_item = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.ANIME.value,
            title="Anime Show",
            image="",
        )
        TV.objects.create(
            item=grouped_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

        importer_instance = self._importer()
        with patch(
            "app.services.grouped_anime.classify_tv_metadata",
            return_value=None,
        ) as mock_classify:
            bucket = importer_instance._anime_bucket_for_show("1396", self.tv_metadata)

        self.assertEqual(bucket, MediaTypes.ANIME.value)
        mock_classify.assert_not_called()

    def test_flat_mal_home_is_skipped_rather_than_imported_to_tv(self):
        """Trakt cannot write a MAL identity, so it must not import a TV twin."""
        from app.models import Anime, ItemProviderLink

        anime_item = Item.objects.create(
            media_id="12345",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Anime Show",
            image="",
        )
        ItemProviderLink.objects.create(
            item=anime_item,
            provider=Sources.TMDB.value,
            provider_media_type=MediaTypes.TV.value,
            provider_media_id="1396",
            episode_offset=0,
        )
        Anime.objects.create(
            item=anime_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
            progress=1,
        )

        importer_instance = self._importer()
        bucket = importer_instance._anime_bucket_for_show("1396", self.tv_metadata)

        self.assertEqual(bucket, "skip")

    def test_classifier_runs_once_per_show_not_once_per_episode(self):
        """Episodes share one show-level verdict via the run cache."""
        importer_instance = self._importer()
        with patch(
            "app.services.grouped_anime.classify_tv_metadata",
            return_value=self.match,
        ) as mock_classify:
            for _ in range(5):
                importer_instance._anime_bucket_for_show("1396", self.tv_metadata)

        self.assertEqual(mock_classify.call_count, 1)


class TraktDeviceFlow(TestCase):
    """Trakt's device code flow, used when the callback URL cannot be HTTPS (#681)."""

    @staticmethod
    def _response(status_code, payload=None):
        response = Response()
        response.status_code = status_code
        response._content = json.dumps(payload or {}).encode()
        return response

    @patch("integrations.imports.trakt.services.api_request")
    def test_request_device_code_clamps_interval(self, mock_api_request):
        mock_api_request.return_value = {
            "device_code": "device-code",
            "user_code": "5055CC52",
            "verification_url": "https://trakt.tv/activate",
            "expires_in": 600,
            "interval": 1,
        }
        device = trakt.request_device_code(client_id="client")
        self.assertEqual(device["user_code"], "5055CC52")
        self.assertEqual(device["interval"], trakt.TRAKT_DEVICE_MIN_INTERVAL)

    @patch("integrations.imports.trakt.services.api_request")
    def test_request_device_code_failure_is_actionable(self, mock_api_request):
        mock_api_request.side_effect = services.ProviderAPIError(
            "TRAKT",
            requests.RequestException("boom"),
        )
        with self.assertRaises(MediaImportError) as ctx:
            trakt.request_device_code(client_id="client")
        self.assertIn("Could not start Trakt authorization", str(ctx.exception))

    @patch("integrations.imports.trakt.get_username_from_oauth", return_value="floppy")
    @patch("integrations.imports.trakt.services.session.post")
    def test_poll_returns_tokens_on_success(self, mock_post, _mock_username):
        mock_post.return_value = self._response(
            200,
            {"access_token": "access", "refresh_token": "refresh"},
        )
        result = trakt.poll_device_token("device-code", "client", "secret")
        self.assertEqual(
            result,
            {
                "access_token": "access",
                "refresh_token": "refresh",
                "redirect_uri": trakt.TRAKT_OOB_REDIRECT_URI,
                "username": "floppy",
            },
        )

    @patch("integrations.imports.trakt.services.session.post")
    def test_poll_pending_statuses_return_none(self, mock_post):
        for status_code in (400, 429):
            with self.subTest(status_code=status_code):
                mock_post.return_value = self._response(status_code)
                self.assertIsNone(
                    trakt.poll_device_token("device-code", "client", "secret"),
                )

    @patch("integrations.imports.trakt.services.session.post")
    def test_poll_terminal_statuses_raise(self, mock_post):
        expected = {
            404: "no longer valid",
            409: "already used",
            410: "expired",
            418: "denied",
            500: "Trakt authorization failed.",
        }
        for status_code, fragment in expected.items():
            with self.subTest(status_code=status_code):
                mock_post.return_value = self._response(status_code)
                with self.assertRaises(MediaImportError) as ctx:
                    trakt.poll_device_token("device-code", "client", "secret")
                self.assertIn(fragment, str(ctx.exception))

    @patch("integrations.imports.trakt.get_username_from_oauth", return_value="floppy")
    @patch("integrations.imports.trakt.services._fallback_session.post")
    @patch("integrations.imports.trakt.services.session.post")
    def test_poll_falls_back_when_redis_breaks_the_limiter(
        self,
        mock_post,
        mock_fallback_post,
        _mock_username,
    ):
        """A mid-run Redis outage must not crash device-code polling (#1166)."""
        mock_post.side_effect = redis.exceptions.ConnectionError("refused")
        mock_fallback_post.return_value = self._response(
            200,
            {"access_token": "access", "refresh_token": "refresh"},
        )

        result = trakt.poll_device_token("device-code", "client", "secret")

        self.assertEqual(
            result,
            {
                "access_token": "access",
                "refresh_token": "refresh",
                "redirect_uri": trakt.TRAKT_OOB_REDIRECT_URI,
                "username": "floppy",
            },
        )
        mock_fallback_post.assert_called_once()


class TraktRefreshRedirectUri(TestCase):
    """The refresh grant needs a redirect URI Trakt will accept (#681)."""

    @override_settings(URLS=[], BASE_URL=None)
    def test_falls_back_to_out_of_band_uri(self):
        self.assertEqual(trakt._refresh_redirect_uri(), trakt.TRAKT_OOB_REDIRECT_URI)

    @override_settings(URLS=["http://192.168.1.50:8000"])
    def test_plain_http_lan_url_falls_back_to_out_of_band_uri(self):
        self.assertEqual(trakt._refresh_redirect_uri(), trakt.TRAKT_OOB_REDIRECT_URI)

    @override_settings(URLS=["https://floppy.example.com"])
    def test_https_url_is_used_directly(self):
        self.assertEqual(
            trakt._refresh_redirect_uri(),
            "https://floppy.example.com/import/trakt/private",
        )


class TraktRefreshUsesAuthorizedRedirectUri(TestCase):
    """The refresh grant repeats the redirect URI the connection was made with (#1404)."""

    CALLBACK_URI = "https://floppy.example.com/import/trakt/private"

    @staticmethod
    def _rejected(payload):
        response = Response()
        response.status_code = 400
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps(payload).encode()
        return services.ProviderAPIError(
            "TRAKT",
            requests.HTTPError(response=response),
        )

    @override_settings(URLS=[], BASE_URL=None)
    @patch("integrations.imports.trakt.update_refresh_token")
    @patch("integrations.imports.trakt.helpers.decrypt_or_raise", return_value="old")
    @patch("integrations.imports.trakt.services.api_request")
    def test_stored_redirect_uri_is_sent_even_when_none_is_configured(
        self,
        mock_api_request,
        _mock_decrypt,
        _mock_update,
    ):
        # No URLS/BASE_URL in the worker would otherwise mean the out-of-band
        # value, which a custom Trakt app that only lists its https callback
        # rejects.
        mock_api_request.return_value = {"access_token": "a", "refresh_token": "r"}

        trakt.get_access_token("enc", self.CALLBACK_URI)

        sent = mock_api_request.call_args.kwargs["params"]
        self.assertEqual(sent["redirect_uri"], self.CALLBACK_URI)

    @override_settings(URLS=[], BASE_URL=None)
    @patch("integrations.imports.trakt.update_refresh_token")
    @patch("integrations.imports.trakt.helpers.decrypt_or_raise", return_value="old")
    @patch("integrations.imports.trakt.services.api_request")
    def test_connections_without_a_stored_uri_keep_the_old_fallback(
        self,
        mock_api_request,
        _mock_decrypt,
        _mock_update,
    ):
        mock_api_request.return_value = {"access_token": "a", "refresh_token": "r"}

        trakt.get_access_token("enc")

        sent = mock_api_request.call_args.kwargs["params"]
        self.assertEqual(sent["redirect_uri"], trakt.TRAKT_OOB_REDIRECT_URI)

    @patch("integrations.imports.trakt.helpers.decrypt_or_raise", return_value="old")
    @patch("integrations.imports.trakt.services.api_request")
    def test_rejected_refresh_names_the_oauth_error(
        self,
        mock_api_request,
        _mock_decrypt,
    ):
        mock_api_request.side_effect = self._rejected({"error": "invalid_grant"})

        with (
            self.assertLogs("integrations.imports.trakt", level="WARNING") as logs,
            self.assertRaises(MediaImportError) as ctx,
        ):
            trakt.get_access_token("enc", self.CALLBACK_URI)

        self.assertIn("invalid_grant", str(ctx.exception))
        self.assertIn("Redirect URI", str(ctx.exception))
        self.assertIn("invalid_grant", "\n".join(logs.output))

    @patch("integrations.imports.trakt.helpers.decrypt_or_raise", return_value="old")
    @patch("integrations.imports.trakt.services.api_request")
    def test_rejected_refresh_without_a_json_body_still_explains(
        self,
        mock_api_request,
        _mock_decrypt,
    ):
        response = Response()
        response.status_code = 400
        response._content = b"<html>Bad Request</html>"
        mock_api_request.side_effect = services.ProviderAPIError(
            "TRAKT",
            requests.HTTPError(response=response),
        )

        with self.assertRaises(MediaImportError) as ctx:
            trakt.get_access_token("enc", self.CALLBACK_URI)

        self.assertIn("rejected the token refresh", str(ctx.exception))

    @patch("integrations.imports.trakt.get_access_token", return_value="access")
    @patch("integrations.imports.trakt.services.api_request", return_value={})
    def test_importer_passes_the_stored_uri_to_the_refresh(
        self,
        _mock_api_request,
        mock_get_access_token,
    ):
        user = get_user_model().objects.create_user(username="trakt-1404")
        trakt_importer = TraktImporter(
            "trakt-user",
            user,
            "new",
            refresh_token="enc",
            redirect_uri=self.CALLBACK_URI,
        )

        trakt_importer._make_api_request("https://api.trakt.tv/users/me")

        mock_get_access_token.assert_called_once_with("enc", self.CALLBACK_URI)

    @patch("integrations.imports.trakt.get_username_from_oauth", return_value="floppy")
    @patch("integrations.imports.trakt.services.api_request")
    def test_sign_in_result_carries_the_redirect_uri_it_used(
        self,
        mock_api_request,
        _mock_username,
    ):
        mock_api_request.return_value = {"access_token": "a", "refresh_token": "r"}
        request = RequestFactory().get("/import/trakt/private", {"code": "abc"})

        result = trakt.handle_oauth_callback(
            request,
            redirect_uri=self.CALLBACK_URI,
            client_id="client",
            client_secret="secret",
        )

        self.assertEqual(result["redirect_uri"], self.CALLBACK_URI)
        sent = mock_api_request.call_args.kwargs["params"]
        self.assertEqual(sent["redirect_uri"], self.CALLBACK_URI)
