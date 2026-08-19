import json
import zipfile
from io import BytesIO
from unittest.mock import Mock, patch

import requests
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, tag
from django.urls import reverse

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
from app.providers import services
from integrations.imports import helpers
from integrations.imports.helpers import MediaImportError
from integrations.imports.trakt_export import TraktExportArchive, importer
from lists.models import CustomList, CustomListItem


def _zip_bytes(files):
    """Build an in-memory zip from a {filename: python-object-or-bytes} mapping."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in files.items():
            if isinstance(payload, bytes):
                archive.writestr(name, payload)
            else:
                archive.writestr(name, json.dumps(payload))
    buffer.seek(0)
    return buffer


def _show(tmdb_id=12345, title="Test Show"):
    return {"title": title, "year": 2020, "ids": {"tmdb": tmdb_id, "trakt": 1}}


def _movie(tmdb_id=67890, title="Test Movie"):
    return {"title": title, "year": 2021, "ids": {"tmdb": tmdb_id, "trakt": 2}}


def _tv_metadata(title="Test Show", *, season_numbers=(1,), last_season=None):
    return {
        "title": title,
        "image": "tv_image.jpg",
        "last_episode_season": last_season,
        "related": {"seasons": [{"season_number": n} for n in season_numbers]},
    }


def _season_metadata(episode_numbers=(1,), title="Season 1"):
    return {
        "title": title,
        "image": "season_image.jpg",
        "max_progress": len(episode_numbers),
        "episodes": [
            {"episode_number": n, "still_path": f"/s{n}.jpg"} for n in episode_numbers
        ],
    }


def _metadata_side_effect(media_type, _tmdb_id, _title, _season_number=None):
    if media_type == MediaTypes.TV.value:
        return _tv_metadata(last_season=1)
    if media_type == MediaTypes.SEASON.value:
        return _season_metadata(episode_numbers=[1, 2])
    return {"title": "Test Movie", "image": "movie_image.jpg"}


class TraktExportArchiveTests(TestCase):
    """Test the prefix-matching file reader over a Trakt export archive."""

    def test_prefix_does_not_match_longer_named_sibling(self):
        """hidden-progress-watched must not swallow -reset or -collected."""
        archive = TraktExportArchive(
            _zip_bytes(
                {
                    "hidden-progress-watched.json": [{"a": 1}],
                    "hidden-progress-watched-reset.json": [{"b": 2}],
                    "hidden-progress-collected.json": [{"c": 3}],
                },
            ),
        )

        self.assertEqual(archive.load("hidden-progress-watched"), [{"a": 1}])
        self.assertEqual(archive.load("hidden-progress-watched-reset"), [{"b": 2}])

    def test_watched_history_does_not_match_watched_movies(self):
        """Distinct sections sharing a word prefix stay separate."""
        archive = TraktExportArchive(
            _zip_bytes(
                {
                    "watched-history-1.json": [{"h": 1}],
                    "watched-movies-1.json": [{"m": 1}],
                    "watched-shows-1.json": [{"s": 1}],
                },
            ),
        )

        self.assertEqual(archive.load("watched-history"), [{"h": 1}])

    def test_numbered_pages_concatenate_in_numeric_order(self):
        """Page 10 must sort after page 2, not lexicographically before it."""
        archive = TraktExportArchive(
            _zip_bytes(
                {
                    "watched-history-1.json": [1],
                    "watched-history-2.json": [2],
                    "watched-history-10.json": [10],
                },
            ),
        )

        self.assertEqual(archive.load("watched-history"), [1, 2, 10])

    def test_multiple_prefixes_and_missing_files(self):
        """load() merges several prefixes and tolerates absent ones."""
        archive = TraktExportArchive(
            _zip_bytes(
                {
                    "ratings-movies-1.json": [{"r": "movie"}],
                    "ratings-shows.json": [{"r": "show"}],
                    "ratings-episodes.json": [],
                },
            ),
        )

        self.assertEqual(
            archive.load(
                "ratings-movies",
                "ratings-shows",
                "ratings-seasons",
                "ratings-episodes",
            ),
            [{"r": "movie"}, {"r": "show"}],
        )

    def test_archive_wrapped_in_a_folder_is_readable(self):
        """A zip whose members sit under a directory still resolves."""
        archive = TraktExportArchive(
            _zip_bytes({"trakt-export/watched-history-1.json": [{"h": 1}]}),
        )

        self.assertEqual(archive.load("watched-history"), [{"h": 1}])

    def test_malformed_member_warns_instead_of_raising(self):
        """A corrupt JSON file is skipped with a warning."""
        archive = TraktExportArchive(
            _zip_bytes(
                {
                    "watched-history-1.json": b"{not json",
                    "watched-history-2.json": [{"h": 2}],
                },
            ),
        )

        self.assertEqual(archive.load("watched-history"), [{"h": 2}])
        self.assertTrue(archive.warnings)

    def test_corrupt_zip_raises_media_import_error(self):
        """A non-zip upload fails as an import error, not a 500."""
        with self.assertRaises(MediaImportError):
            TraktExportArchive(BytesIO(b"this is not a zip"))

    def test_list_item_files_group_by_trakt_id(self):
        """List item files are grouped by their embedded list id."""
        archive = TraktExportArchive(
            _zip_bytes(
                {
                    "lists-list-100-my-list.json": [],
                    "lists-list-200-other-1.json": [],
                    "lists-list-200-other-2.json": [],
                    "lists-lists.json": [],
                    "lists-watchlist-1.json": [],
                },
            ),
        )

        grouped = archive.list_item_files()
        self.assertEqual(sorted(grouped), ["100", "200"])
        self.assertEqual(len(grouped["200"]), 2)


class ImportTraktExport(TestCase):
    """Test importing media from a Trakt data export archive."""

    def setUp(self):
        """Create user for the tests."""
        # A stale cached TMDB movie payload for the shared test id (67890)
        # from another test class run earlier in the same worker process
        # would make test_watchlist_movie_tmdb_401_raises_clean_import_error
        # skip the mocked API call entirely.
        cache.clear()
        credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**credentials)

    def test_duplicate_show_rows_are_deduplicated_before_bulk_create(self):
        """Duplicate in-memory rows must not abort a large export import."""
        item = Item.objects.create(
            media_id="12345",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Duplicate Show",
            image="",
        )

        helpers.bulk_create_media(
            {
                MediaTypes.TV.value: [
                    TV(item=item, user=self.user, status=Status.IN_PROGRESS.value),
                    TV(item=item, user=self.user, status=Status.COMPLETED.value),
                ],
            },
            self.user,
        )

        self.assertEqual(TV.objects.filter(user=self.user, item=item).count(), 1)
        self.assertEqual(
            TV.objects.get(user=self.user, item=item).status,
            Status.COMPLETED.value,
        )

    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_history_creates_movie_and_episodes(self, mock_get_metadata):
        """Watch history creates Movie/Episode rows and rolls progress up."""
        mock_get_metadata.side_effect = _metadata_side_effect

        export = _zip_bytes(
            {
                "user-profile.json": {"username": "someone"},
                "watched-history-1.json": [
                    {
                        "type": "episode",
                        "watched_at": "2023-01-02T00:00:00.000Z",
                        "episode": {"season": 1, "number": 2, "title": "Two"},
                        "show": _show(),
                    },
                    {
                        "type": "episode",
                        "watched_at": "2023-01-01T00:00:00.000Z",
                        "episode": {"season": 1, "number": 1, "title": "One"},
                        "show": _show(),
                    },
                ],
                "watched-history-2.json": [
                    {
                        "type": "movie",
                        "watched_at": "2022-12-31T00:00:00.000Z",
                        "movie": _movie(),
                    },
                ],
            },
        )

        imported_counts, _ = importer(export, self.user, "new")

        self.assertEqual(imported_counts[MediaTypes.MOVIE.value], 1)
        self.assertEqual(imported_counts[MediaTypes.EPISODE.value], 2)
        self.assertEqual(Movie.objects.filter(user=self.user).count(), 1)
        self.assertEqual(Episode.objects.filter(item__media_id="12345").count(), 2)

        season = Season.objects.get(user=self.user, item__media_id="12345")
        self.assertEqual(season.status, Status.COMPLETED.value)
        self.assertEqual(
            TV.objects.get(user=self.user, item__media_id="12345").status,
            Status.COMPLETED.value,
        )

    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_history_is_replayed_oldest_first(self, mock_get_metadata):
        """Export pages run newest-first, so episodes must still land in order."""
        mock_get_metadata.side_effect = _metadata_side_effect

        export = _zip_bytes(
            {
                "watched-history-1.json": [
                    {
                        "type": "episode",
                        "watched_at": "2023-01-02T00:00:00.000Z",
                        "episode": {"season": 1, "number": 2, "title": "Two"},
                        "show": _show(),
                    },
                ],
                "watched-history-2.json": [
                    {
                        "type": "episode",
                        "watched_at": "2023-01-01T00:00:00.000Z",
                        "episode": {"season": 1, "number": 1, "title": "One"},
                        "show": _show(),
                    },
                ],
            },
        )

        importer(export, self.user, "new")

        watched = list(
            Episode.objects.filter(item__media_id="12345")
            .order_by("end_date")
            .values_list("item__episode_number", flat=True),
        )
        self.assertEqual(watched, [1, 2])

    @tag("network")
    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_ratings_watchlist_and_comments(self, mock_get_metadata):
        """Ratings keep the raw 1-10 score; watchlist plans; comments become notes."""
        mock_get_metadata.side_effect = _metadata_side_effect

        export = _zip_bytes(
            {
                "ratings-movies-1.json": [
                    {
                        "type": "movie",
                        "rating": 9,
                        "rated_at": "2023-02-01T00:00:00.000Z",
                        "movie": _movie(),
                    },
                ],
                "ratings-shows.json": [
                    {
                        "type": "show",
                        "rating": 7,
                        "rated_at": "2023-02-01T00:00:00.000Z",
                        "show": _show(),
                    },
                ],
                "lists-watchlist-1.json": [
                    {
                        "type": "movie",
                        "listed_at": "2023-03-01T00:00:00.000Z",
                        "movie": _movie(tmdb_id=555, title="Planned"),
                    },
                ],
                "comments-movies.json": [
                    {
                        "type": "movie",
                        "movie": _movie(),
                        "comment": {
                            "comment": "Great film.",
                            "updated_at": "2023-04-01T00:00:00.000Z",
                        },
                    },
                ],
            },
        )

        importer(export, self.user, "new")

        movie = Movie.objects.get(user=self.user, item__media_id="67890")
        self.assertEqual(movie.score, 9)
        self.assertEqual(movie.notes, "Great film.")

        show = TV.objects.get(user=self.user, item__media_id="12345")
        self.assertEqual(show.score, 7)
        self.assertEqual(
            Movie.objects.get(user=self.user, item__media_id="555").status,
            Status.PLANNING.value,
        )

    @tag("network")
    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_notes_become_notes(self, mock_get_metadata):
        """A private Trakt note (distinct from a comment) becomes item notes."""
        mock_get_metadata.side_effect = _metadata_side_effect

        export = _zip_bytes(
            {
                "notes-movies.json": [
                    {
                        "type": "movie",
                        "movie": _movie(),
                        "note": {
                            "notes": "Private note.",
                            "spoiler": False,
                            "updated_at": "2023-05-01T00:00:00.000Z",
                        },
                    },
                ],
            },
        )

        importer(export, self.user, "new")

        movie = Movie.objects.get(user=self.user, item__media_id="67890")
        self.assertEqual(movie.notes, "Private note.")

    @tag("network")
    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_comment_wins_over_note_for_same_item(self, mock_get_metadata):
        """Notes import before comments, so a comment overwrites a note's text."""
        mock_get_metadata.side_effect = _metadata_side_effect

        export = _zip_bytes(
            {
                "notes-movies.json": [
                    {
                        "type": "movie",
                        "movie": _movie(),
                        "note": {
                            "notes": "Private note.",
                            "updated_at": "2023-05-01T00:00:00.000Z",
                        },
                    },
                ],
                "comments-movies.json": [
                    {
                        "type": "movie",
                        "movie": _movie(),
                        "comment": {
                            "comment": "Great film.",
                            "updated_at": "2023-04-01T00:00:00.000Z",
                        },
                    },
                ],
            },
        )

        importer(export, self.user, "new")

        movie = Movie.objects.get(user=self.user, item__media_id="67890")
        self.assertEqual(movie.notes, "Great film.")

    @tag("network")
    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_note_missing_text_is_skipped(self, mock_get_metadata):
        """A malformed note entry without note text is skipped, not fatal."""
        mock_get_metadata.side_effect = _metadata_side_effect

        export = _zip_bytes(
            {
                "notes-movies.json": [
                    {
                        "type": "movie",
                        "movie": _movie(),
                        "note": {"updated_at": "2023-05-01T00:00:00.000Z"},
                    },
                ],
            },
        )

        importer(export, self.user, "new")

        self.assertFalse(
            Movie.objects.filter(user=self.user, item__media_id="67890").exists(),
        )

    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_collection_shows_create_collection_entries(self, mock_get_metadata):
        """The nested collection-shows payload creates CollectionEntry rows."""
        mock_get_metadata.side_effect = _metadata_side_effect

        export = _zip_bytes(
            {
                "collection-movies-1.json": [
                    {
                        "type": "movie",
                        "collected_at": "2026-01-01T00:00:00.000Z",
                        "movie": _movie(),
                        "metadata": {"resolution": "1080p", "audio": "dts"},
                    },
                ],
                "collection-shows.json": [
                    {
                        "type": "show",
                        "show": _show(),
                        "seasons": [
                            {
                                "number": 1,
                                "episodes": [
                                    {
                                        "number": 1,
                                        "collected_at": "2026-01-01T00:00:00.000Z",
                                        "metadata": None,
                                    },
                                ],
                            },
                        ],
                    },
                ],
            },
        )

        importer(export, self.user, "new")

        movie_entry = CollectionEntry.objects.get(
            user=self.user,
            item__media_type=MediaTypes.MOVIE.value,
        )
        self.assertEqual(movie_entry.resolution, "1080p")
        self.assertEqual(movie_entry.audio_codec, "dts")
        self.assertEqual(
            CollectionEntry.objects.filter(
                user=self.user,
                item__media_type=MediaTypes.EPISODE.value,
            ).count(),
            1,
        )

    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_hidden_progress_marks_show_dropped(self, mock_get_metadata):
        """hidden-progress-watched is read even though there is no OAuth token."""
        mock_get_metadata.side_effect = _metadata_side_effect

        export = _zip_bytes(
            {
                "watched-history-1.json": [
                    {
                        "type": "episode",
                        "watched_at": "2023-01-01T00:00:00.000Z",
                        "episode": {"season": 1, "number": 1, "title": "One"},
                        "show": _show(),
                    },
                ],
                "hidden-progress-watched.json": [
                    {"type": "show", "show": _show()},
                ],
            },
        )

        importer(export, self.user, "new")

        self.assertEqual(
            TV.objects.get(user=self.user, item__media_id="12345").status,
            Status.DROPPED.value,
        )

    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_import_never_hits_the_network(self, mock_get_metadata, mock_request):
        """The export importer must resolve everything from files."""
        mock_get_metadata.side_effect = _metadata_side_effect

        export = _zip_bytes(
            {
                "watched-history-1.json": [
                    {
                        "type": "movie",
                        "watched_at": "2023-01-01T00:00:00.000Z",
                        "movie": _movie(),
                    },
                ],
            },
        )
        importer(export, self.user, "new")

        mock_request.assert_not_called()

    @patch("app.providers.tmdb.services.api_request")
    def test_watchlist_movie_tmdb_401_raises_clean_import_error(self, mock_api_request):
        """A TMDB 401 (e.g. bad API key) aborts the import with a clear message.

        Regression test for GitHub issue #424: a bad TMDB_API key used to
        surface as an unhandled MediaImportUnexpectedError. TraktImporter
        now treats a 401 as fatal, just like it already does for 404s.
        """
        response = Mock()
        response.status_code = requests.codes.unauthorized
        response.json.return_value = {
            "status_message": "Invalid API key: You must be granted a valid key.",
        }
        mock_api_request.side_effect = requests.exceptions.HTTPError(response=response)

        export = _zip_bytes(
            {
                "lists-watchlist-1.json": [
                    {
                        "type": "movie",
                        "listed_at": "2023-03-01T00:00:00.000Z",
                        "movie": _movie(),
                    },
                ],
            },
        )

        with self.assertRaises(MediaImportError) as ctx:
            importer(export, self.user, "new")

        self.assertIsInstance(ctx.exception.__cause__, services.ProviderAPIError)
        self.assertIn("API key", str(ctx.exception))

    @patch("lists.imports.trakt._get_metadata")
    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_lists_and_watchlist_become_custom_lists(
        self,
        mock_get_metadata,
        mock_list_metadata,
    ):
        """lists-lists.json plus item files rebuild CustomList/CustomListItem."""
        mock_get_metadata.side_effect = _metadata_side_effect
        mock_list_metadata.return_value = {
            "title": "Test Movie",
            "image": "movie_image.jpg",
        }

        export = _zip_bytes(
            {
                "lists-lists.json": [
                    {
                        "name": "Favorite Movies",
                        "description": "Best of",
                        "privacy": "public",
                        "ids": {"trakt": 100, "slug": "favorite-movies"},
                    },
                ],
                "lists-list-100-favorite-movies.json": [
                    {"type": "movie", "movie": _movie()},
                ],
                "lists-watchlist-1.json": [
                    {
                        "type": "movie",
                        "listed_at": "2023-03-01T00:00:00.000Z",
                        "movie": _movie(tmdb_id=555, title="Planned"),
                    },
                ],
            },
        )

        imported_counts, _ = importer(export, self.user, "new")

        self.assertEqual(imported_counts["lists"], 2)

        favorites = CustomList.objects.get(owner=self.user, source_id="100")
        self.assertEqual(favorites.name, "Favorite Movies")
        self.assertEqual(favorites.visibility, "public")
        self.assertEqual(
            CustomListItem.objects.filter(custom_list=favorites).count(),
            1,
        )

        watchlist = CustomList.objects.get(owner=self.user, source_id="watchlist")
        self.assertEqual(
            CustomListItem.objects.filter(custom_list=watchlist).count(),
            1,
        )

    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_rerun_does_not_duplicate_episode_plays(self, mock_get_metadata):
        """Re-uploading the same export in "new" mode is idempotent for episodes."""
        mock_get_metadata.side_effect = _metadata_side_effect

        files = {
            "watched-history-1.json": [
                {
                    "type": "episode",
                    "watched_at": "2023-01-01T00:00:00.000Z",
                    "episode": {"season": 1, "number": 1, "title": "One"},
                    "show": _show(),
                },
            ],
        }

        importer(_zip_bytes(files), self.user, "new")
        importer(_zip_bytes(files), self.user, "new")

        self.assertEqual(Episode.objects.filter(item__media_id="12345").count(), 1)


class TraktExportUploadViewTests(TestCase):
    """Test that the unified Trakt upload routes each file type to the right task."""

    def setUp(self):
        """Create and sign in a user for the tests."""
        credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**credentials)
        self.client.force_login(self.user)
        self.url = reverse("import_trakt_export_file")

    def _post(self, uploads):
        return self.client.post(self.url, {"mode": "new", "trakt_export": uploads})

    @patch("integrations.views.tasks.import_trakt_export.delay")
    def test_zip_upload_routes_to_export_task(self, mock_delay):
        """A .zip goes to the export importer, unwrapped."""
        payload = _zip_bytes({"watched-history-1.json": []}).getvalue()
        upload = SimpleUploadedFile("export.zip", payload, "application/zip")

        self._post(upload)

        mock_delay.assert_called_once()
        self.assertEqual(mock_delay.call_args.kwargs["file"], payload)

    @patch("integrations.views.tasks.import_trakt_export.delay")
    def test_loose_json_uploads_are_repackaged_as_a_zip(self, mock_delay):
        """Multiple .json files are zipped in the view before being queued."""
        uploads = [
            SimpleUploadedFile("watched-history-1.json", b"[]", "application/json"),
            SimpleUploadedFile("ratings-shows.json", b"[]", "application/json"),
        ]

        self._post(uploads)

        queued = mock_delay.call_args.kwargs["file"]
        with zipfile.ZipFile(BytesIO(queued)) as archive:
            self.assertEqual(
                sorted(archive.namelist()),
                ["ratings-shows.json", "watched-history-1.json"],
            )

    @patch("integrations.views.tasks.import_trakt_collection_csv.delay")
    def test_csv_upload_still_routes_to_the_legacy_task(self, mock_delay):
        """The older collection CSV keeps working unchanged."""
        upload = SimpleUploadedFile(
            "collection.csv",
            b"collected_at,type\n",
            "text/csv",
        )

        self._post(upload)

        mock_delay.assert_called_once()

    @patch("integrations.views.tasks.import_trakt_export.delay")
    def test_oversize_upload_is_rejected(self, mock_delay):
        """An upload above the size cap is refused before queueing anything."""
        with patch("integrations.views.TRAKT_EXPORT_MAX_UPLOAD_BYTES", 10):
            self._post(SimpleUploadedFile("export.zip", b"x" * 100, "application/zip"))

        mock_delay.assert_not_called()

    @patch("integrations.views.tasks.import_trakt_export.delay")
    def test_missing_file_is_rejected(self, mock_delay):
        """Submitting with no file selected does not queue a task."""
        self.client.post(self.url, {"mode": "new"})

        mock_delay.assert_not_called()
