from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, tag

from app.models import (
    TV,
    MediaTypes,
    Movie,
    MoviePlay,
    Status,
)
from integrations.imports import (
    imdb,
)

mock_path = Path(__file__).resolve().parent.parent / "mock_data"
app_mock_path = (
    Path(__file__).resolve().parent.parent.parent.parent / "app" / "tests" / "mock_data"
)


@tag("network")
class ImportIMDB(TestCase):
    """Test importing media from IMDB CSV."""

    def setUp(self):
        """Create user for the tests."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        with Path(mock_path / "import_imdb.csv").open("rb") as file:
            self.import_results = imdb.importer(file, self.user, "new")

    def test_import_imdb_csv(self):
        """Test importing movies and TV shows from IMDB CSV."""
        imported_counts, warnings = self.import_results

        self.assertEqual(imported_counts[MediaTypes.MOVIE.value], 5)
        self.assertEqual(imported_counts[MediaTypes.TV.value], 2)

        self.assertIn(
            "The Last of Us: Unsupported title type 'Video Game' - skipped",
            warnings,
        )

        movie_1 = Movie.objects.get(item__title="The Shawshank Redemption")
        self.assertEqual(movie_1.score, 9)
        self.assertIsNone(movie_1.status)
        self.assertEqual(movie_1.progress, 0)
        self.assertIsNone(movie_1.end_date)
        self.assertFalse(MoviePlay.objects.filter(movie=movie_1).exists())

        game_of_thrones = TV.objects.get(item__title="Game of Thrones")
        self.assertEqual(game_of_thrones.status, Status.PLANNING.value)

    def test_extract_imdb_id(self):
        """Test IMDB ID extraction and formatting."""
        importer_instance = imdb.IMDBImporter(None, self.user, "new")

        self.assertEqual(
            importer_instance._extract_imdb_id({"Const": "tt0111161"}),
            "tt0111161",
        )
        self.assertEqual(
            importer_instance._extract_imdb_id({"Const": "0111161"}),
            "tt0111161",
        )
        self.assertIsNone(importer_instance._extract_imdb_id({"Const": ""}))
        self.assertIsNone(importer_instance._extract_imdb_id({"Const": "invalid"}))

    def test_parse_rating(self):
        """Test rating parsing."""
        importer_instance = imdb.IMDBImporter(None, self.user, "new")

        # Valid ratings
        self.assertEqual(importer_instance._parse_rating("8.5"), 8.5)
        self.assertEqual(importer_instance._parse_rating("10"), 10.0)
        self.assertEqual(importer_instance._parse_rating("1"), 1.0)

        self.assertIsNone(importer_instance._parse_rating(""))
        self.assertIsNone(importer_instance._parse_rating("invalid"))
        self.assertIsNone(importer_instance._parse_rating("11"))
        self.assertIsNone(importer_instance._parse_rating("0"))

    def test_parse_date_rated(self):
        """Test date parsing."""
        importer_instance = imdb.IMDBImporter(None, self.user, "new")

        # Valid date
        parsed_date = importer_instance._parse_date("2023-01-15")
        self.assertEqual(parsed_date.date(), datetime(2023, 1, 15, tzinfo=UTC).date())

        self.assertIsNone(importer_instance._parse_date(""))
        self.assertIsNone(importer_instance._parse_date("invalid-date"))

    def test_is_supported_type(self):
        """Test title type support checking."""
        importer_instance = imdb.IMDBImporter(None, self.user, "new")
        type_tests = {
            ("Movie", True),
            ("TV Series", True),
            ("Short", True),
            ("TV Mini Series", True),
            ("TV Movie", True),
            ("TV Special", True),
            ("Video", True),
            ("TV Episode", False),
            ("TV Short", False),
            ("Video Game", False),
            ("Music Video", False),
            ("Podcast Series", False),
            ("Podcast Episode", False),
        }

        for media_type, result in type_tests:
            self.assertEqual(importer_instance._is_supported_type(media_type), result)

    @patch("app.providers.tmdb.find")
    def test_lookup_in_tmdb_not_found(self, mock_tmdb_find):
        """Test TMDB lookup when no results are found."""
        mock_tmdb_find.return_value = {}

        importer_instance = imdb.IMDBImporter(None, self.user, "new")
        result = importer_instance._lookup_in_tmdb("tt9999999", "movie")

        self.assertIsNone(result)

    def test_duplicate_handling(self):
        """Test handling of duplicate IMDB entries that map to same TMDB ID."""
        imported_counts, warnings = self.import_results

        # There are six movies in the test CSV, one of them is a duplicate
        # The test CSV file contains a duplicate of The Dark Knight
        self.assertEqual(imported_counts.get(MediaTypes.MOVIE.value, 0), 5)

        self.assertIn("They were matched to the same TMDB ID 155", warnings)


class IMDBStreamingTests(TestCase):
    """Exercise local import semantics without a live provider."""

    def setUp(self):
        """Create a user and resolve test identifiers deterministically."""
        self.user = get_user_model().objects.create_user(username="stream-imdb")
        patcher = patch.object(
            imdb.IMDBImporter,
            "_lookup_in_tmdb",
            side_effect=lambda identifier, _: {
                "media_id": int(identifier[2:]),
                "title": "Resolved",
                "image": "",
                "media_type": MediaTypes.MOVIE,
            },
        )
        self.lookup = patcher.start()
        self.addCleanup(patcher.stop)

    def upload(self, rows):
        """Build a valid CSV with a multiline title."""
        return BytesIO(("Const,Title,Title Type,Created,Your Rating\n" + rows).encode())

    def test_rating_does_not_create_a_watch_or_episode_progress(self):
        """IMDb ratings are not evidence of watched films or series."""
        counts, _ = imdb.importer(
            self.upload(
                "tt1,Film,Movie,2025-01-01,8\n"
                "tt2,Series,TV Series,2025-01-02,7\n"
                "tt3,Watchlist,Movie,2025-01-03,\n"
            ),
            self.user,
            "new",
        )
        self.assertEqual(counts, {MediaTypes.MOVIE: 2, MediaTypes.TV: 1})

        film = Movie.objects.get(item__media_id="1")
        self.assertEqual(film.score, 8)
        self.assertIsNone(film.status)
        self.assertEqual(film.progress, 0)
        self.assertIsNone(film.start_date)
        self.assertIsNone(film.end_date)
        self.assertFalse(MoviePlay.objects.filter(movie=film).exists())

        series = TV.objects.get(item__media_id="2")
        self.assertEqual(series.score, 7)
        self.assertIsNone(series.status)
        self.assertIsNone(series.start_date)
        self.assertIsNone(series.end_date)
        self.assertFalse(series.seasons.exists())

        watchlist = Movie.objects.get(item__media_id="3")
        self.assertEqual(watchlist.status, Status.PLANNING.value)
        self.assertIsNone(watchlist.score)

    def test_overwrite_updates_rating_without_deleting_watches(self):
        """Re-importing a rating must preserve an existing play and its date."""
        imdb.importer(self.upload("tt1,Film,Movie,2025-01-01,\n"), self.user, "new")
        film = Movie.objects.get(item__media_id="1")
        watched_at = datetime(2024, 5, 12, 20, 0, tzinfo=UTC)
        Movie.objects.filter(pk=film.pk).update(
            status=Status.COMPLETED.value, progress=1, end_date=watched_at
        )
        play = MoviePlay.objects.create(movie=film, end_date=watched_at)

        imdb.importer(
            self.upload("tt1,Film,Movie,2025-06-01,9\n"), self.user, "overwrite"
        )
        film.refresh_from_db()
        self.assertEqual(Movie.objects.filter(item=film.item).count(), 1)
        self.assertEqual(film.score, 9)
        self.assertIsNotNone(film.scored_at)
        self.assertEqual(film.status, Status.COMPLETED.value)
        self.assertEqual(film.progress, 1)
        self.assertEqual(film.end_date, watched_at)
        self.assertTrue(MoviePlay.objects.filter(pk=play.pk).exists())
        self.assertEqual(play.end_date, watched_at)

    def test_overwrite_prefers_existing_rating_only_row(self):
        """Scores must not be pushed onto a different, legitimately watched row."""
        imdb.importer(self.upload("tt1,Film,Movie,2025-01-01,8\n"), self.user, "new")
        rating = Movie.objects.get(item__media_id="1")
        watched_at = datetime(2026, 1, 10, 19, 0, tzinfo=UTC)
        watch = Movie.objects.create(
            item=rating.item,
            user=self.user,
            status=Status.COMPLETED.value,
            progress=1,
            end_date=watched_at,
            score=6,
        )
        imdb.importer(
            self.upload("tt1,Film,Movie,2026-02-01,9\n"), self.user, "overwrite"
        )
        rating.refresh_from_db()
        watch.refresh_from_db()
        self.assertEqual(Movie.objects.filter(item=rating.item).count(), 2)
        self.assertIsNone(rating.status)
        self.assertEqual(rating.score, 9)
        self.assertEqual(watch.score, 6)
        self.assertEqual(watch.end_date, watched_at)

    def test_overwrite_preserves_existing_series_status_and_progress(self):
        """A score update must not reset a show's tracking state."""
        imdb.importer(
            self.upload("tt2,Series,TV Series,2025-01-01,6\n"),
            self.user,
            "new",
        )
        series = TV.objects.get(item__media_id="2")
        TV.objects.filter(pk=series.pk).update(status=Status.PLANNING.value)

        imdb.importer(
            self.upload("tt2,Series,TV Series,2025-02-01,9\n"),
            self.user,
            "overwrite",
        )
        series.refresh_from_db()
        self.assertEqual(TV.objects.filter(item=series.item).count(), 1)
        self.assertEqual(series.status, Status.PLANNING.value)
        self.assertEqual(series.score, 9)
        self.assertIsNotNone(series.scored_at)
        self.assertFalse(series.seasons.exists())

    def test_unrated_overwrite_keeps_existing_rating_and_status(self):
        """An unrated IMDb list row is not a request to erase a saved rating."""
        imdb.importer(self.upload("tt1,Film,Movie,2025-01-01,8\n"), self.user, "new")
        imdb.importer(
            self.upload("tt1,Film,Movie,2025-02-01,\n"),
            self.user,
            "overwrite",
        )
        film = Movie.objects.get(item__media_id="1")
        self.assertIsNone(film.status)
        self.assertEqual(film.score, 8)
        self.assertEqual(Movie.objects.count(), 1)

    def test_rated_entry_without_dates_does_not_fabricate_completion(self):
        """A missing IMDb date is valid; it must not become a watch today."""
        imdb.importer(self.upload("tt1,Film,Movie,,8\n"), self.user, "new")
        film = Movie.objects.get(item__media_id="1")
        self.assertEqual(film.score, 8)
        self.assertIsNone(film.status)
        self.assertIsNone(film.end_date)

    def test_duplicate_validation_precedes_overwrite(self):
        """Duplicates spanning the file never delete existing tracking."""
        imdb.importer(
            self.upload("tt1,Original,Movie,2025-01-01,8\n"), self.user, "new"
        )
        counts, warnings = imdb.importer(
            self.upload(
                'tt1,"First\nTitle",Movie,2025-01-01,9\n'
                "tt2,Other,Movie,2025-01-01,7\n"
                "tt1,Duplicate,Movie,2025-01-01,10\n",
            ),
            self.user,
            "overwrite",
        )
        self.assertEqual(counts, {MediaTypes.MOVIE: 1})
        self.assertIn("First\nTitle", warnings)
        self.assertEqual(Movie.objects.get(item__media_id="1").score, 8)
        self.assertEqual(self.lookup.call_count, 4)

    def test_late_invalid_encoding_preserves_existing_media(self):
        """An invalid suffix cannot trigger partial overwrite writes."""
        imdb.importer(
            self.upload("tt1,Original,Movie,2025-01-01,8\n"), self.user, "new"
        )
        file = self.upload("tt1,Replacement,Movie,2025-01-01,9\n")
        file.seek(0, 2)
        file.write(b"\xff")
        file.seek(0)
        with self.assertRaises(imdb.MediaImportError):
            imdb.importer(file, self.user, "overwrite")
        self.assertEqual(Movie.objects.get(item__media_id="1").score, 8)

    def test_batches_preserve_history_and_new_mode(self):
        """Multiple persistence batches retain row counts and history."""
        rows = "".join(f"tt{i},Title,Movie,2025-01-01,8\n" for i in range(1, 253))
        counts, warnings = imdb.importer(self.upload(rows), self.user, "new")
        self.assertEqual(counts, {MediaTypes.MOVIE: 252})
        self.assertIsNone(warnings)
        self.assertEqual(Movie.objects.count(), 252)
        self.assertEqual(Movie.history.count(), 252)
        counts, _ = imdb.importer(self.upload(rows), self.user, "new")
        self.assertEqual(counts, {})
