import csv
from datetime import UTC, datetime
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.test import TestCase
from django.urls import reverse

from app.mixins import disable_fetch_releases
from app.models import (
    TV,
    Album,
    AlbumTracker,
    Anime,
    Artist,
    ArtistTracker,
    Book,
    CollectionEntry,
    Episode,
    Game,
    Item,
    ItemTag,
    Manga,
    MediaTypes,
    Movie,
    MoviePlay,
    Season,
    Sources,
    Status,
    Tag,
)
from lists.models import CustomList, CustomListItem


class ExportCSVTest(TestCase):
    """Test exporting media to CSV."""

    @patch("app.providers.services.get_media_metadata", return_value={"max_progress": None})
    def setUp(self, _mock_get_media_metadata):
        """Create necessary data for the tests."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_superuser(**self.credentials)
        self.client.login(**self.credentials)

        with disable_fetch_releases():
            item_movie = Item.objects.create(
                media_id="10494",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title="Perfect Blue",
                image="https://image.url",
            )
            Movie.objects.create(
                item=item_movie,
                user=self.user,
                score=9,
                status=Status.COMPLETED.value,
                notes="Nice",
                start_date=datetime(2023, 6, 1, 0, 0, tzinfo=UTC),
                end_date=datetime(2023, 6, 1, 0, 0, tzinfo=UTC),
            )

            item_season = Item.objects.create(
                media_id="1668",
                source=Sources.TMDB.value,
                media_type=MediaTypes.SEASON.value,
                title="Friends",
                image="https://image.url",
                season_number=1,
            )

            season = Season.objects.create(
                item=item_season,
                user=self.user,
                score=9,
                status=Status.IN_PROGRESS.value,
                notes="Nice",
            )

            item_episode = Item.objects.create(
                media_id="1668",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title="Friends",
                image="https://image.url",
                season_number=1,
                episode_number=1,
            )
            Episode.objects.create(
                item=item_episode,
                related_season=season,
                end_date=datetime(2023, 6, 1, 0, 0, tzinfo=UTC),
            )

            item_anime = Item.objects.create(
                media_id="1",
                source=Sources.MAL.value,
                media_type=MediaTypes.ANIME.value,
                title="Cowboy Bebop",
                image="https://image.url",
            )
            Anime.objects.create(
                item=item_anime,
                user=self.user,
                status=Status.IN_PROGRESS.value,
                progress=2,
                start_date=datetime(2021, 6, 1, 0, 0, tzinfo=UTC),
            )

            item_manga = Item.objects.create(
                media_id="1",
                source=Sources.MAL.value,
                media_type=MediaTypes.MANGA.value,
                title="Berserk",
                image="https://image.url",
            )
            Manga.objects.create(
                item=item_manga,
                user=self.user,
                status=Status.IN_PROGRESS.value,
                progress=2,
                start_date=datetime(2021, 6, 1, 0, 0, tzinfo=UTC),
            )

            item_game = Item.objects.create(
                media_id="1",
                source=Sources.IGDB.value,
                media_type=MediaTypes.GAME.value,
                title="The Witcher 3: Wild Hunt",
                image="https://image.url",
            )
            Game.objects.create(
                item=item_game,
                user=self.user,
                status=Status.IN_PROGRESS.value,
                progress=120,
                start_date=datetime(2021, 6, 1, 0, 0, tzinfo=UTC),
            )

            item_book = Item.objects.create(
                media_id="OL21733390M",
                source=Sources.OPENLIBRARY.value,
                media_type=MediaTypes.BOOK.value,
                title="Fantastic Mr. Fox",
                image="https://image.url",
            )
            Book.objects.create(
                item=item_book,
                user=self.user,
                status=Status.IN_PROGRESS.value,
                progress=120,
                start_date=datetime(2021, 6, 1, 0, 0, tzinfo=UTC),
            )

            custom_list = CustomList.objects.create(
                name="Favorites",
                description="Top picks",
                owner=self.user,
                visibility="private",
            )
            CustomListItem.objects.create(
                custom_list=custom_list,
                item=item_movie,
                added_by=self.user,
            )
            CustomListItem.objects.create(
                custom_list=custom_list,
                item=item_episode,
                added_by=self.user,
            )

    def test_export_csv(self):
        """Basic test exporting media to CSV."""
        # Generate the CSV file by accessing the export view
        response = self.client.get(reverse("export_csv"))

        # Assert that the response is successful (status code 200)
        self.assertEqual(response.status_code, 200)

        # Assert that the response content type is text/csv
        self.assertEqual(response["Content-Type"], "text/csv")

        # Read the streaming content and decode it
        content = b"".join(response.streaming_content).decode("utf-8")

        # Create a CSV reader from the CSV content
        reader = csv.DictReader(StringIO(content))

        db_media_ids = set(
            Item.objects.filter(
                Q(tv__user=self.user)
                | Q(movie__user=self.user)
                | Q(season__user=self.user)
                | Q(episode__related_season__user=self.user)
                | Q(anime__user=self.user)
                | Q(manga__user=self.user)
                | Q(game__user=self.user)
                | Q(book__user=self.user),
            ).values_list("media_id", flat=True),
        )

        list_rows = []
        list_item_rows = []

        # Verify each row in the CSV exists in the database
        for row in reader:
            row_type = row.get("row_type") or "media"
            if row_type == "list":
                list_rows.append(row)
                continue
            if row_type == "list_item":
                list_item_rows.append(row)
                continue

            media_id = row["media_id"]
            self.assertIn(media_id, db_media_ids)

        self.assertEqual(len(list_rows), 1)
        self.assertEqual(list_rows[0]["list_name"], "Favorites")
        self.assertEqual(len(list_item_rows), 2)
        self.assertTrue(all(r["list_name"] == "Favorites" for r in list_item_rows))
        exported_media_types = {r["media_type"] for r in list_item_rows}
        self.assertIn("movie", exported_media_types)
        self.assertIn("episode", exported_media_types)

    def test_export_csv_lists_only_when_no_media_types_selected(self):
        """Deselecting all media types but keeping lists on exports only list rows."""
        response = self.client.get(
            reverse("export_csv"),
            {"media_types": [], "include_lists": "on"},
        )
        self.assertEqual(response.status_code, 200)

        content = b"".join(response.streaming_content).decode("utf-8")
        reader = csv.DictReader(StringIO(content))
        rows = list(reader)

        row_types = {(row.get("row_type") or "media") for row in rows}
        self.assertEqual(row_types, {"list", "list_item"})
        self.assertTrue(any(row["row_type"] == "list" for row in rows))
        self.assertTrue(any(row["row_type"] == "list_item" for row in rows))

    def test_export_csv_includes_item_entries_for_each_list_membership(self):
        """Items that appear on multiple lists should be exported once per list item."""
        movie_item = Item.objects.get(
            media_id="10494", media_type=MediaTypes.MOVIE.value
        )
        second_list = CustomList.objects.create(
            name="Rewatch",
            description="Need to revisit",
            owner=self.user,
            visibility="private",
        )
        CustomListItem.objects.create(
            custom_list=second_list,
            item=movie_item,
            added_by=self.user,
        )

        response = self.client.get(reverse("export_csv"))
        self.assertEqual(response.status_code, 200)

        content = b"".join(response.streaming_content).decode("utf-8")
        reader = csv.DictReader(StringIO(content))

        movie_list_item_rows = [
            row
            for row in reader
            if (row.get("row_type") or "media") == "list_item"
            and row.get("media_id") == movie_item.media_id
            and row.get("media_type") == movie_item.media_type
        ]

        exported_list_names = sorted({row["list_name"] for row in movie_list_item_rows})
        self.assertEqual(exported_list_names, ["Favorites", "Rewatch"])

    def test_generate_list_csv_only_includes_target_list(self):
        """generate_list_csv should only emit rows for the given list."""
        from integrations import exports

        movie_item = Item.objects.get(
            media_id="10494", media_type=MediaTypes.MOVIE.value
        )
        favorites = CustomList.objects.get(owner=self.user, name="Favorites")
        other_list = CustomList.objects.create(
            name="Rewatch",
            description="Need to revisit",
            owner=self.user,
            visibility="private",
        )
        CustomListItem.objects.create(
            custom_list=other_list,
            item=movie_item,
            added_by=self.user,
        )

        content = "".join(exports.generate_list_csv(favorites))
        reader = csv.DictReader(StringIO(content))
        rows = list(reader)

        list_rows = [row for row in rows if row["row_type"] == "list"]
        list_item_rows = [row for row in rows if row["row_type"] == "list_item"]
        media_rows = [
            row for row in rows if row["row_type"] not in ("list", "list_item")
        ]

        self.assertEqual(len(list_rows), 1)
        self.assertEqual(list_rows[0]["list_name"], "Favorites")
        self.assertEqual(len(list_item_rows), 2)
        self.assertTrue(all(r["list_name"] == "Favorites" for r in list_item_rows))
        self.assertEqual(media_rows, [])

    def test_export_csv_includes_music_artist_and_album_rows(self):
        """ArtistTracker and AlbumTracker rows appear in the CSV export."""
        artist = Artist.objects.create(
            name="Radiohead",
            musicbrainz_id="a74b1b7f-71a5-4011-9441-d0b5e4122711",
            image="https://image.url/artist",
        )
        ArtistTracker.objects.create(
            user=self.user,
            artist=artist,
            status=Status.COMPLETED.value,
            score=9,
        )

        album = Album.objects.create(
            title="OK Computer",
            musicbrainz_release_group_id="0f5d2a1f-c2e3-4e9e-b7b3-5b8c3d2e1f0a",
            artist=artist,
            image="https://image.url/album",
        )
        AlbumTracker.objects.create(
            user=self.user,
            album=album,
            status=Status.COMPLETED.value,
            score=10,
        )

        response = self.client.get(reverse("export_csv"))
        self.assertEqual(response.status_code, 200)

        content = b"".join(response.streaming_content).decode("utf-8")
        reader = csv.DictReader(StringIO(content))
        rows = list(reader)

        artist_rows = [r for r in rows if r.get("media_type") == "music_artist"]
        album_rows = [r for r in rows if r.get("media_type") == "music_album"]

        self.assertEqual(len(artist_rows), 1)
        self.assertEqual(artist_rows[0]["media_id"], artist.musicbrainz_id)
        self.assertEqual(artist_rows[0]["score"], "9.0")

        self.assertEqual(len(album_rows), 1)
        self.assertEqual(album_rows[0]["media_id"], album.musicbrainz_release_group_id)
        self.assertEqual(album_rows[0]["score"], "10.0")

    def _create_collection_entries(self):
        """Create two movie copies and a bare episode collection entry."""
        movie_item, _ = Item.objects.get_or_create(
            media_id="10494",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            season_number=None,
            episode_number=None,
            defaults={"title": "Perfect Blue", "image": "https://image.url"},
        )
        episode_item, _ = Item.objects.get_or_create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            defaults={"title": "Friends", "image": "https://image.url"},
        )
        CollectionEntry.objects.create(
            user=self.user,
            item=movie_item,
            media_type="4K Blu-ray",
            resolution="4K",
            hdr="Dolby Vision",
            audio_codec="Dolby Atmos",
            audio_channels="7.1",
            bitrate=8000,
        )
        CollectionEntry.objects.create(
            user=self.user,
            item=movie_item,
            media_type="DVD",
        )
        episode_entry = CollectionEntry.objects.create(
            user=self.user,
            item=episode_item,
        )
        collected_at = datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)
        CollectionEntry.objects.filter(id=episode_entry.id).update(
            collected_at=collected_at,
        )
        return collected_at

    def test_export_csv_includes_collection_rows(self):
        """Collection entries are exported with collection_* columns."""
        collected_at = self._create_collection_entries()

        response = self.client.get(reverse("export_csv"))
        self.assertEqual(response.status_code, 200)

        content = b"".join(response.streaming_content).decode("utf-8")
        reader = csv.DictReader(StringIO(content))
        header = reader.fieldnames
        for column in (
            "collection_format",
            "collection_resolution",
            "collection_is_3d",
            "collection_bitrate",
            "collection_collected_at",
        ):
            self.assertIn(column, header)

        collection_rows = [r for r in reader if r["row_type"] == "collection"]
        self.assertEqual(len(collection_rows), 3)

        movie_rows = [r for r in collection_rows if r["media_type"] == "movie"]
        self.assertEqual(len(movie_rows), 2)
        full_copy = next(
            r for r in movie_rows if r["collection_format"] == "4K Blu-ray"
        )
        self.assertEqual(full_copy["media_id"], "10494")
        self.assertEqual(full_copy["collection_resolution"], "4K")
        self.assertEqual(full_copy["collection_hdr"], "Dolby Vision")
        self.assertEqual(full_copy["collection_audio_codec"], "Dolby Atmos")
        self.assertEqual(full_copy["collection_audio_channels"], "7.1")
        self.assertEqual(full_copy["collection_bitrate"], "8000")

        episode_rows = [r for r in collection_rows if r["media_type"] == "episode"]
        self.assertEqual(len(episode_rows), 1)
        self.assertEqual(episode_rows[0]["season_number"], "1")
        self.assertEqual(episode_rows[0]["episode_number"], "1")
        self.assertEqual(
            episode_rows[0]["collection_collected_at"],
            collected_at.isoformat(),
        )

    def test_export_csv_excludes_watch_providers(self):
        """watch_providers is dropped from the export (never re-imported, huge)."""
        response = self.client.get(reverse("export_csv"))
        self.assertEqual(response.status_code, 200)

        content = b"".join(response.streaming_content).decode("utf-8")
        header = csv.DictReader(StringIO(content)).fieldnames
        self.assertNotIn("watch_providers", header)

    def test_export_csv_collection_respects_media_type_filter(self):
        """Collection rows follow the media_types filter, including children."""
        self._create_collection_entries()

        response = self.client.get(reverse("export_csv"), {"media_types": ["movie"]})
        content = b"".join(response.streaming_content).decode("utf-8")
        rows = [
            r
            for r in csv.DictReader(StringIO(content))
            if r["row_type"] == "collection"
        ]
        self.assertEqual({r["media_type"] for r in rows}, {"movie"})

        response = self.client.get(reverse("export_csv"), {"media_types": ["tv"]})
        content = b"".join(response.streaming_content).decode("utf-8")
        rows = [
            r
            for r in csv.DictReader(StringIO(content))
            if r["row_type"] == "collection"
        ]
        self.assertEqual({r["media_type"] for r in rows}, {"episode"})

    def test_export_csv_exclude_collection(self):
        """include_collection off removes collection rows."""
        self._create_collection_entries()

        response = self.client.get(
            reverse("export_csv"),
            {"include_collection": "off"},
        )
        content = b"".join(response.streaming_content).decode("utf-8")
        rows = list(csv.DictReader(StringIO(content)))
        self.assertFalse(any(r["row_type"] == "collection" for r in rows))

    def test_export_csv_collection_only(self):
        """No media types + lists off + collection on exports only collection rows."""
        self._create_collection_entries()

        response = self.client.get(
            reverse("export_csv"),
            {"include_lists": "off", "include_collection": "on"},
        )
        content = b"".join(response.streaming_content).decode("utf-8")
        rows = list(csv.DictReader(StringIO(content)))
        self.assertTrue(rows)
        self.assertEqual({r["row_type"] for r in rows}, {"collection"})

    def _create_show_with_episodes(self, media_id, episode_count):
        """Create a TV show, one season, and *episode_count* episodes for it."""
        with disable_fetch_releases():
            show_item = Item.objects.create(
                media_id=media_id,
                source=Sources.TMDB.value,
                media_type=MediaTypes.TV.value,
                title=f"Show {media_id}",
                image="https://image.url",
            )
            TV.objects.create(
                item=show_item,
                user=self.user,
                status=Status.IN_PROGRESS.value,
            )
            season_item = Item.objects.create(
                media_id=media_id,
                source=Sources.TMDB.value,
                media_type=MediaTypes.SEASON.value,
                title=f"Show {media_id}",
                season_number=1,
                image="https://image.url",
            )
            season = Season.objects.create(
                item=season_item,
                user=self.user,
                status=Status.IN_PROGRESS.value,
            )
            episodes = []
            for episode_number in range(1, episode_count + 1):
                episode_item = Item.objects.create(
                    media_id=media_id,
                    source=Sources.TMDB.value,
                    media_type=MediaTypes.EPISODE.value,
                    title=f"Show {media_id}",
                    season_number=1,
                    episode_number=episode_number,
                    image="https://image.url",
                )
                episodes.append(
                    Episode(
                        item=episode_item,
                        related_season=season,
                        end_date=datetime(2023, 6, 1, 0, 0, tzinfo=UTC),
                    ),
                )
            Episode.objects.bulk_create(episodes)

    def test_export_csv_includes_every_episode_past_iterator_chunk_size(self):
        """All episodes are exported even when they outnumber the 500-row
        iterator chunk size used while streaming (regression test for #618:
        a dead season/episode prefetch on the tv/season querysets used to
        multiply query cost per show and could truncate the stream well
        before every episode was written).
        """
        episode_count = 1200
        self._create_show_with_episodes("999001", episode_count)

        response = self.client.get(reverse("export_csv"))
        self.assertEqual(response.status_code, 200)

        content = b"".join(response.streaming_content).decode("utf-8")
        reader = csv.DictReader(StringIO(content))
        episode_rows = [
            r
            for r in reader
            if r.get("row_type") == "media" and r.get("media_type") == "episode"
        ]

        # +1 for the single episode created in setUp.
        self.assertEqual(len(episode_rows), episode_count + 1)
        self.assertEqual(
            Episode.objects.filter(related_season__user=self.user).count(),
            episode_count + 1,
        )

    def test_export_csv_skips_episodes_with_no_linked_item(self):
        """An episode row with a null item is skipped, not emitted blank."""
        season_item = Item.objects.create(
            media_id="999002",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Orphaned",
            season_number=1,
            image="https://image.url",
        )
        season = Season.objects.create(
            item=season_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        # bulk_create bypasses Episode.save(), which dereferences self.item
        # and can't handle a null item -- this row models data that reached
        # the DB some other way (the item FK is nullable), not something the
        # normal save path can produce.
        Episode.objects.bulk_create(
            [
                Episode(
                    item=None,
                    related_season=season,
                    end_date=datetime(2023, 6, 1, 0, 0, tzinfo=UTC),
                ),
            ],
        )

        response = self.client.get(reverse("export_csv"))
        self.assertEqual(response.status_code, 200)

        content = b"".join(response.streaming_content).decode("utf-8")
        reader = csv.DictReader(StringIO(content))
        episode_rows = [
            r
            for r in reader
            if r.get("row_type") == "media" and r.get("media_type") == "episode"
        ]

        # The one legitimate episode from setUp, but not the orphaned one.
        self.assertEqual(len(episode_rows), 1)


class LetterboxdExportCSVTest(TestCase):
    """Test exporting watched movies to a Letterboxd-import-ready CSV."""

    @patch("app.providers.services.get_media_metadata", return_value={"max_progress": None})
    def setUp(self, _mock_get_media_metadata):
        """Create a superuser and log in."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_superuser(**self.credentials)
        self.client.login(**self.credentials)

    def _get_rows(self):
        response = self.client.get(reverse("export_csv_letterboxd"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        content = b"".join(response.streaming_content).decode("utf-8")
        return list(csv.DictReader(StringIO(content)))

    def test_basic_watch(self):
        """A single watch exports title, year, watched date, rating and review."""
        with disable_fetch_releases():
            item = Item.objects.create(
                media_id="10494",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title="Perfect Blue",
                image="https://image.url",
                release_datetime=datetime(1997, 7, 26, 0, 0, tzinfo=UTC),
            )
            movie = Movie.objects.create(
                item=item,
                user=self.user,
                score=9,
                status=Status.COMPLETED.value,
                notes="Nice",
                end_date=datetime(2023, 6, 1, 0, 0, tzinfo=UTC),
            )
            MoviePlay.objects.create(movie=movie, end_date=movie.end_date)

        rows = self._get_rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["Title"], "Perfect Blue")
        self.assertEqual(row["Year"], "1997")
        self.assertEqual(row["tmdbID"], "10494")
        self.assertEqual(row["WatchedDate"], "2023-06-01")
        self.assertEqual(row["Rating"], "4.5")
        self.assertEqual(row["Review"], "Nice")
        self.assertEqual(row["Rewatch"], "")

    def test_rating_conversion_and_absence(self):
        """Scores convert to the 0.5-5 scale; missing/zero scores stay blank."""
        with disable_fetch_releases():
            item_rated = Item.objects.create(
                media_id="1",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title="Rated",
                image="https://image.url",
            )
            movie_rated = Movie.objects.create(
                item=item_rated,
                user=self.user,
                score="6.7",
                status=Status.COMPLETED.value,
                end_date=datetime(2023, 1, 1, 0, 0, tzinfo=UTC),
            )
            MoviePlay.objects.create(movie=movie_rated, end_date=movie_rated.end_date)

            item_unrated = Item.objects.create(
                media_id="2",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title="Unrated",
                image="https://image.url",
            )
            movie_unrated = Movie.objects.create(
                item=item_unrated,
                user=self.user,
                status=Status.COMPLETED.value,
                end_date=datetime(2023, 1, 1, 0, 0, tzinfo=UTC),
            )
            MoviePlay.objects.create(
                movie=movie_unrated, end_date=movie_unrated.end_date,
            )

            item_zero = Item.objects.create(
                media_id="3",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title="Zero Score",
                image="https://image.url",
            )
            movie_zero = Movie.objects.create(
                item=item_zero,
                user=self.user,
                score=0,
                status=Status.COMPLETED.value,
                end_date=datetime(2023, 1, 1, 0, 0, tzinfo=UTC),
            )
            MoviePlay.objects.create(movie=movie_zero, end_date=movie_zero.end_date)

        rows = {row["Title"]: row for row in self._get_rows()}
        # 6.7 / 2 = 3.35 -> rounds to nearest 0.5 -> 3.5
        self.assertEqual(rows["Rated"]["Rating"], "3.5")
        self.assertEqual(rows["Unrated"]["Rating"], "")
        self.assertEqual(rows["Zero Score"]["Rating"], "")

    def test_only_rating_column_present(self):
        """Only a single rating column is emitted, avoiding Letterboxd's ambiguity rule."""
        with disable_fetch_releases():
            item = Item.objects.create(
                media_id="10494",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title="Perfect Blue",
                image="https://image.url",
            )
            movie = Movie.objects.create(
                item=item,
                user=self.user,
                score=9,
                status=Status.COMPLETED.value,
                end_date=datetime(2023, 6, 1, 0, 0, tzinfo=UTC),
            )
            MoviePlay.objects.create(movie=movie, end_date=movie.end_date)

        response = self.client.get(reverse("export_csv_letterboxd"))
        content = b"".join(response.streaming_content).decode("utf-8")
        header = content.splitlines()[0]
        self.assertIn("Rating", header.split(","))
        self.assertNotIn("Rating10", header.split(","))

    def test_rewatch_flagging(self):
        """Only plays after the first for a movie are flagged as a rewatch."""
        with disable_fetch_releases():
            item = Item.objects.create(
                media_id="10494",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title="Perfect Blue",
                image="https://image.url",
            )
            movie = Movie.objects.create(
                item=item,
                user=self.user,
                status=Status.COMPLETED.value,
                end_date=datetime(2023, 6, 3, 0, 0, tzinfo=UTC),
            )
            MoviePlay.objects.create(
                movie=movie, end_date=datetime(2023, 6, 1, 0, 0, tzinfo=UTC),
            )
            MoviePlay.objects.create(
                movie=movie, end_date=datetime(2023, 6, 2, 0, 0, tzinfo=UTC),
            )
            MoviePlay.objects.create(
                movie=movie, end_date=datetime(2023, 6, 3, 0, 0, tzinfo=UTC),
            )

        rows = sorted(self._get_rows(), key=lambda r: r["WatchedDate"])
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["Rewatch"], "")
        self.assertEqual(rows[1]["Rewatch"], "true")
        self.assertEqual(rows[2]["Rewatch"], "true")

    def test_tags_included_as_plain_comma_separated_string(self):
        """Tags are joined as plain text, not the JSON shape used by the full export."""
        with disable_fetch_releases():
            item = Item.objects.create(
                media_id="10494",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title="Perfect Blue",
                image="https://image.url",
            )
            movie = Movie.objects.create(
                item=item,
                user=self.user,
                status=Status.COMPLETED.value,
                end_date=datetime(2023, 6, 1, 0, 0, tzinfo=UTC),
            )
            MoviePlay.objects.create(movie=movie, end_date=movie.end_date)

            tag_thriller = Tag.objects.create(user=self.user, name="thriller")
            tag_anime = Tag.objects.create(user=self.user, name="anime")
            ItemTag.objects.create(tag=tag_thriller, item=item)
            ItemTag.objects.create(tag=tag_anime, item=item)

        rows = self._get_rows()
        self.assertEqual(len(rows), 1)
        tags = {t.strip() for t in rows[0]["Tags"].split(",")}
        self.assertEqual(tags, {"thriller", "anime"})

    def test_no_tags_is_empty_string(self):
        """A movie with no tags exports an empty Tags field."""
        with disable_fetch_releases():
            item = Item.objects.create(
                media_id="10494",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title="Perfect Blue",
                image="https://image.url",
            )
            movie = Movie.objects.create(
                item=item,
                user=self.user,
                status=Status.COMPLETED.value,
                end_date=datetime(2023, 6, 1, 0, 0, tzinfo=UTC),
            )
            MoviePlay.objects.create(movie=movie, end_date=movie.end_date)

        rows = self._get_rows()
        self.assertEqual(rows[0]["Tags"], "")

    def test_movie_play_fallback_for_pre_feature_completions(self):
        """A completed movie with no MoviePlay rows still exports one row."""
        with disable_fetch_releases():
            item = Item.objects.create(
                media_id="10494",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title="Perfect Blue",
                image="https://image.url",
            )
            Movie.objects.create(
                item=item,
                user=self.user,
                score=8,
                status=Status.COMPLETED.value,
                end_date=datetime(2020, 1, 1, 0, 0, tzinfo=UTC),
            )
            # deliberately no MoviePlay row created

        rows = self._get_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["WatchedDate"], "2020-01-01")
        self.assertEqual(rows[0]["Rewatch"], "")

    def test_unwatched_movie_excluded(self):
        """A movie that was never completed and has no MoviePlay is not exported."""
        with disable_fetch_releases():
            item = Item.objects.create(
                media_id="10494",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title="Perfect Blue",
                image="https://image.url",
            )
            Movie.objects.create(
                item=item,
                user=self.user,
                status=Status.PLANNING.value,
            )

        rows = self._get_rows()
        self.assertEqual(rows, [])

    def test_completed_movie_without_watch_date_is_included(self):
        """A Completed movie with no end_date and no MoviePlay still exports.

        Legacy/imported completions can have Status.COMPLETED with no
        end_date at all (see
        app.tests.models.test_media.test_repeated_completed_plays_remain_separate),
        so status -- not end_date -- is the "was this watched" signal.
        """
        with disable_fetch_releases():
            item = Item.objects.create(
                media_id="10494",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title="Perfect Blue",
                image="https://image.url",
            )
            Movie.objects.create(
                item=item,
                user=self.user,
                status=Status.COMPLETED.value,
            )

        rows = self._get_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["WatchedDate"], "")
        self.assertEqual(rows[0]["Rewatch"], "")

    def test_legacy_repeated_completions_grouped_by_item_for_rewatch(self):
        """Repeat watches stored as separate Movie rows for one Item rewatch-flag correctly.

        Some completions are recorded as multiple standalone Movie rows
        sharing the same Item rather than MoviePlay entries (see
        app.tests.models.test_media.test_repeated_completed_plays_remain_separate).
        Grouping must key off the underlying Item, not the Movie row, or
        every such row looks like an unrelated first watch.
        """
        with disable_fetch_releases():
            item = Item.objects.create(
                media_id="10494",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title="Perfect Blue",
                image="https://image.url",
            )
            Movie.objects.create(
                item=item,
                user=self.user,
                status=Status.COMPLETED.value,
                end_date=datetime(2020, 1, 1, 0, 0, tzinfo=UTC),
            )
            Movie.objects.create(
                item=item,
                user=self.user,
                status=Status.COMPLETED.value,
                end_date=datetime(2021, 1, 1, 0, 0, tzinfo=UTC),
            )
            # deliberately no MoviePlay rows -- both are legacy standalone rows

        rows = sorted(self._get_rows(), key=lambda r: r["WatchedDate"])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["WatchedDate"], "2020-01-01")
        self.assertEqual(rows[0]["Rewatch"], "")
        self.assertEqual(rows[1]["WatchedDate"], "2021-01-01")
        self.assertEqual(rows[1]["Rewatch"], "true")

    def test_legacy_repeated_completion_without_date_sorts_after_dated_ones(self):
        """An undated legacy completion never displaces a dated one as 'first'."""
        with disable_fetch_releases():
            item = Item.objects.create(
                media_id="10494",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title="Perfect Blue",
                image="https://image.url",
            )
            Movie.objects.create(
                item=item,
                user=self.user,
                status=Status.COMPLETED.value,
            )
            Movie.objects.create(
                item=item,
                user=self.user,
                status=Status.COMPLETED.value,
                end_date=datetime(2020, 1, 1, 0, 0, tzinfo=UTC),
            )

        rows = self._get_rows()
        self.assertEqual(len(rows), 2)
        dated = next(r for r in rows if r["WatchedDate"] == "2020-01-01")
        undated = next(r for r in rows if r["WatchedDate"] == "")
        self.assertEqual(dated["Rewatch"], "")
        self.assertEqual(undated["Rewatch"], "true")

    def test_imdb_id_population(self):
        """tmdbID/imdbID are populated from Item source/media_id/provider_external_ids."""
        with disable_fetch_releases():
            item_with_imdb = Item.objects.create(
                media_id="10494",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title="With IMDb",
                image="https://image.url",
                provider_external_ids={"imdb_id": "tt0113402"},
            )
            movie_with_imdb = Movie.objects.create(
                item=item_with_imdb,
                user=self.user,
                status=Status.COMPLETED.value,
                end_date=datetime(2023, 6, 1, 0, 0, tzinfo=UTC),
            )
            MoviePlay.objects.create(
                movie=movie_with_imdb, end_date=movie_with_imdb.end_date,
            )

            item_without_imdb = Item.objects.create(
                media_id="10495",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title="Without IMDb",
                image="https://image.url",
            )
            movie_without_imdb = Movie.objects.create(
                item=item_without_imdb,
                user=self.user,
                status=Status.COMPLETED.value,
                end_date=datetime(2023, 6, 1, 0, 0, tzinfo=UTC),
            )
            MoviePlay.objects.create(
                movie=movie_without_imdb, end_date=movie_without_imdb.end_date,
            )

        rows = {row["Title"]: row for row in self._get_rows()}
        self.assertEqual(rows["With IMDb"]["tmdbID"], "10494")
        self.assertEqual(rows["With IMDb"]["imdbID"], "tt0113402")
        self.assertEqual(rows["Without IMDb"]["tmdbID"], "10495")
        self.assertEqual(rows["Without IMDb"]["imdbID"], "")

    @patch("app.providers.services.get_media_metadata", return_value={"max_progress": None})
    def test_non_movie_media_types_excluded(self, _mock_get_media_metadata):
        """Only movies are exported; other media types are excluded."""
        with disable_fetch_releases():
            item_movie = Item.objects.create(
                media_id="10494",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title="Perfect Blue",
                image="https://image.url",
            )
            movie = Movie.objects.create(
                item=item_movie,
                user=self.user,
                status=Status.COMPLETED.value,
                end_date=datetime(2023, 6, 1, 0, 0, tzinfo=UTC),
            )
            MoviePlay.objects.create(movie=movie, end_date=movie.end_date)

            item_season = Item.objects.create(
                media_id="1668",
                source=Sources.TMDB.value,
                media_type=MediaTypes.SEASON.value,
                title="Friends",
                image="https://image.url",
                season_number=1,
            )
            Season.objects.create(
                item=item_season,
                user=self.user,
                status=Status.COMPLETED.value,
            )

        rows = self._get_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Title"], "Perfect Blue")
