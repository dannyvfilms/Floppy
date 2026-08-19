from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import CollectionEntry, Item, MediaTypes, Sources
from integrations.imports.trakt_collection import TraktCollectionCsvImporter, importer

CSV_HEADER = (
    "collected_at,type,title,year,trakt_rating,trakt_id,imdb_id,tmdb_id,tvdb_id,"
    "url,released,runtime,season_number,episode_number,episode_title,"
    "episode_released,episode_trakt_rating,episode_trakt_id,episode_imdb_id,"
    "episode_tmdb_id,episode_tvdb_id,genres,media_type,resolution,3d,hdr,audio,"
    "audio_channels"
)


def _movie_row(*, tmdb_id, title, collected_at="2026-01-04T15:16:51Z"):
    return (
        f"{collected_at},movie,{title},2017,4.5,369109,tt6999498,{tmdb_id},,"
        "https://trakt.tv/movies/x,2017-06-04,90,,,,,,,,,,romance,bluray,1080p,"
        "false,,dts,5.1"
    )


def _episode_row(
    *,
    tmdb_id,
    title,
    season_number,
    episode_number,
    collected_at="2026-01-04T15:32:57Z",
):
    return (
        f"{collected_at},episode,{title},2024,7.17,216574,tt29780951,{tmdb_id},"
        f"440865,https://trakt.tv/shows/x,2024-01-11,42,{season_number},"
        f"{episode_number},Episode Title,2025-04-03T00:00:00Z,7.74,12812507,,"
        '5974635,10924936,"drama,comedy",,,false,,,'
    )


def _malformed_movie_row():
    return (
        "2026-01-04T15:16:51Z,movie,Bad Movie,2017,4.5,369109,tt6999498,,,,,,,,,,,"
        ",,,,,,,,,"
    )


def _csv_bytes(*rows):
    return (CSV_HEADER + "\n" + "\n".join(rows) + "\n").encode("utf-8")


def _tv_metadata(title, season_numbers):
    return {
        "title": title,
        "image": "tv_image.jpg",
        "related": {
            "seasons": [{"season_number": n} for n in season_numbers],
        },
    }


def _season_metadata(episode_numbers):
    return {
        "title": "Season 1",
        "image": "season_image.jpg",
        "max_progress": len(episode_numbers),
        "episodes": [
            {"episode_number": n, "still_path": f"/s{n}.jpg"} for n in episode_numbers
        ],
    }


class ImportTraktCollectionCsv(TestCase):
    """Test importing collection ownership from a Trakt collection CSV export."""

    def setUp(self):
        """Create user for the tests."""
        credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**credentials)

    @patch(
        "integrations.imports.trakt_collection.TraktCollectionCsvImporter._get_metadata",
    )
    def test_movie_row_creates_collection_entry(self, mock_get_metadata):
        """A movie row should create a CollectionEntry with the right A/V metadata."""
        mock_get_metadata.return_value = {"title": "Movie One", "image": "movie.jpg"}

        csv_file = BytesIO(_csv_bytes(_movie_row(tmdb_id=111, title="Movie One")))
        imported_counts, warnings = importer(csv_file, self.user, "new")

        self.assertEqual(imported_counts["movie"], 1)
        self.assertEqual(warnings, "")

        entry = CollectionEntry.objects.get(
            user=self.user,
            item__media_id="111",
            item__media_type=MediaTypes.MOVIE.value,
        )
        self.assertEqual(entry.media_type, "bluray")
        self.assertEqual(entry.resolution, "1080p")
        self.assertEqual(entry.audio_codec, "dts")
        self.assertEqual(entry.audio_channels, "5.1")
        self.assertFalse(entry.is_3d)
        self.assertIsNotNone(entry.collected_at)

    @patch(
        "integrations.imports.trakt_collection.TraktCollectionCsvImporter._get_metadata",
    )
    def test_full_season_rolls_up_to_season_and_show(self, mock_get_metadata):
        """A CSV with every episode of a season should mark season + show collected."""

        def metadata_side_effect(media_type, _tmdb_id, _title, _season_number=None):
            if media_type == MediaTypes.TV.value:
                return _tv_metadata("Owned Show", season_numbers=[1])
            if media_type == MediaTypes.SEASON.value:
                return _season_metadata(episode_numbers=[1, 2])
            return None

        mock_get_metadata.side_effect = metadata_side_effect

        csv_file = BytesIO(
            _csv_bytes(
                _episode_row(
                    tmdb_id=222,
                    title="Owned Show",
                    season_number=1,
                    episode_number=1,
                ),
                _episode_row(
                    tmdb_id=222,
                    title="Owned Show",
                    season_number=1,
                    episode_number=2,
                ),
            ),
        )
        imported_counts, warnings = importer(csv_file, self.user, "new")

        self.assertEqual(imported_counts["episode"], 2)
        self.assertEqual(warnings, "")

        self.assertEqual(
            CollectionEntry.objects.filter(
                user=self.user,
                item__media_id="222",
                item__media_type=MediaTypes.EPISODE.value,
            ).count(),
            2,
        )
        self.assertTrue(
            CollectionEntry.objects.filter(
                user=self.user,
                item__media_id="222",
                item__media_type=MediaTypes.SEASON.value,
                item__season_number=1,
            ).exists(),
        )
        self.assertTrue(
            CollectionEntry.objects.filter(
                user=self.user,
                item__media_id="222",
                item__media_type=MediaTypes.TV.value,
            ).exists(),
        )

    @patch(
        "integrations.imports.trakt_collection.TraktCollectionCsvImporter._get_metadata",
    )
    def test_partial_season_does_not_roll_up(self, mock_get_metadata):
        """Only some of a season's episodes present should not mark it collected."""

        def metadata_side_effect(media_type, _tmdb_id, _title, _season_number=None):
            if media_type == MediaTypes.TV.value:
                return _tv_metadata("Owned Show", season_numbers=[1])
            if media_type == MediaTypes.SEASON.value:
                return _season_metadata(episode_numbers=[1, 2])
            return None

        mock_get_metadata.side_effect = metadata_side_effect

        csv_file = BytesIO(
            _csv_bytes(
                _episode_row(
                    tmdb_id=333,
                    title="Owned Show",
                    season_number=1,
                    episode_number=1,
                ),
            ),
        )
        imported_counts, _ = importer(csv_file, self.user, "new")

        self.assertEqual(imported_counts["episode"], 1)
        self.assertFalse(
            CollectionEntry.objects.filter(
                user=self.user,
                item__media_id="333",
                item__media_type=MediaTypes.SEASON.value,
            ).exists(),
        )

    def test_malformed_row_produces_warning_not_abort(self):
        """A malformed row is skipped and reported, not fatal to the import."""
        csv_file = BytesIO(_csv_bytes(_malformed_movie_row()))
        imported_counts, warnings = importer(csv_file, self.user, "new")

        self.assertEqual(imported_counts["movie"], 0)
        self.assertIn("No", warnings)

    @patch(
        "integrations.imports.trakt_collection.TraktCollectionCsvImporter._get_metadata",
    )
    def test_new_mode_does_not_overwrite_existing_entry(self, mock_get_metadata):
        """ "new" mode must leave an existing CollectionEntry's fields untouched."""
        mock_get_metadata.return_value = {"title": "Movie One", "image": "movie.jpg"}

        item = Item.objects.get_or_create(
            media_id="444",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={"title": "Movie One"},
        )[0]
        existing_entry = CollectionEntry.objects.create(
            user=self.user,
            item=item,
            resolution="4k",
        )

        csv_file = BytesIO(_csv_bytes(_movie_row(tmdb_id=444, title="Movie One")))
        importer(csv_file, self.user, "new")

        existing_entry.refresh_from_db()
        self.assertEqual(existing_entry.resolution, "4k")
        self.assertEqual(
            CollectionEntry.objects.filter(user=self.user, item=item).count(),
            1,
        )

    @patch(
        "integrations.imports.trakt_collection.TraktCollectionCsvImporter._get_metadata",
    )
    def test_overwrite_mode_updates_existing_entry(self, mock_get_metadata):
        """ "overwrite" mode should update an existing CollectionEntry's fields."""
        mock_get_metadata.return_value = {"title": "Movie One", "image": "movie.jpg"}

        item = Item.objects.get_or_create(
            media_id="555",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={"title": "Movie One"},
        )[0]
        CollectionEntry.objects.create(user=self.user, item=item, resolution="4k")

        csv_file = BytesIO(_csv_bytes(_movie_row(tmdb_id=555, title="Movie One")))
        importer(csv_file, self.user, "overwrite")

        entry = CollectionEntry.objects.get(user=self.user, item=item)
        self.assertEqual(entry.resolution, "1080p")

    def test_unknown_row_type_produces_warning(self):
        """An unrecognized row `type` should be skipped with a warning, not crash."""
        rows = CSV_HEADER + "\n" + "2026-01-01T00:00:00Z,show,Ignored Show," + "," * 24
        csv_file = BytesIO(rows.encode("utf-8"))
        importer_instance = TraktCollectionCsvImporter(csv_file, self.user, "new")
        imported_counts, warnings = importer_instance.import_data()

        self.assertEqual(imported_counts, {"movie": 0, "episode": 0})
        self.assertIn("Skipping unknown row type", warnings)
