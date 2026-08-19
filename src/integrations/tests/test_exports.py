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
    Manga,
    MediaTypes,
    Movie,
    Season,
    Sources,
    Status,
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
