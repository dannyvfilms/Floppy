from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, tag

from app.models import (
    TV,
    Album,
    AlbumTracker,
    Anime,
    Artist,
    ArtistTracker,
    BoardGame,
    Book,
    CollectionEntry,
    Comic,
    Episode,
    Game,
    Item,
    ItemTag,
    Manga,
    MediaTypes,
    Movie,
    Podcast,
    Season,
    Sources,
    Status,
    Tag,
)
from integrations import exports
from integrations.imports import (
    yamtrack,
)
from lists.models import CustomList, CustomListItem

mock_path = Path(__file__).resolve().parent.parent / "mock_data"
app_mock_path = (
    Path(__file__).resolve().parent.parent.parent.parent / "app" / "tests" / "mock_data"
)


class ImportYamtrack(TestCase):
    """Test importing media from Yamtrack CSV."""

    def setUp(self):
        """Create user for the tests."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        with Path(mock_path / "import_yamtrack.csv").open("rb") as file:
            self.import_results = yamtrack.importer(file, self.user, "new")

    def test_import_counts(self):
        """Test basic counts of imported media."""
        self.assertEqual(Anime.objects.filter(user=self.user).count(), 1)
        self.assertEqual(Manga.objects.filter(user=self.user).count(), 1)
        self.assertEqual(TV.objects.filter(user=self.user).count(), 1)
        self.assertEqual(Movie.objects.filter(user=self.user).count(), 1)
        self.assertEqual(Season.objects.filter(user=self.user).count(), 1)
        self.assertEqual(
            Episode.objects.filter(related_season__user=self.user).count(),
            24,
        )

    def test_historical_records(self):
        """Test historical records creation during import."""
        anime = Anime.objects.filter(user=self.user).first()
        self.assertEqual(anime.history.count(), 1)
        self.assertEqual(
            anime.history.first().history_date,
            datetime(2024, 2, 9, 10, 0, 0, tzinfo=UTC),
        )

        movie = Movie.objects.filter(user=self.user).first()
        self.assertEqual(movie.history.count(), 1)
        self.assertEqual(
            movie.history.first().history_date,
            datetime(2024, 2, 9, 15, 30, 0, tzinfo=UTC),
        )

        tv = TV.objects.filter(user=self.user).first()
        self.assertEqual(tv.history.count(), 1)
        self.assertEqual(
            tv.history.first().history_date,
            datetime(2024, 2, 9, 12, 0, 0, tzinfo=UTC),
        )

        episode = Episode.objects.filter(related_season__user=self.user).first()
        self.assertEqual(
            episode.history.first().history_date,
            datetime(2024, 2, 9, 12, 0, 0, tzinfo=UTC),
        )

    @tag("network")
    def test_missing_metadata_handling(self):
        """Test _handle_missing_metadata method directly."""
        test_rows = [
            # TV Show
            {
                "media_id": "1668",
                "source": "tmdb",
                "media_type": "tv",
                "title": "",
                "image": "",
                "season_number": "",
                "episode_number": "",
            },
            {
                "media_id": "1668",
                "source": "tmdb",
                "media_type": "season",
                "title": "",
                "image": "",
                "season_number": "2",
                "episode_number": "",
            },
            # Episode
            {
                "media_id": "1668",
                "source": "tmdb",
                "media_type": "episode",
                "title": "",
                "image": "",
                "season_number": "2",
                "episode_number": "5",
            },
        ]

        importer = yamtrack.YamtrackImporter(None, self.user, "new")

        for row in test_rows:
            # Make copies of original rows to verify they're modified
            original_row = row.copy()

            # Call the method directly
            importer._handle_missing_metadata(
                row,
                row["media_type"],
                row["season_number"],
                row["episode_number"],
            )

            self.assertNotEqual(row["title"], original_row["title"])
            self.assertNotEqual(row["image"], original_row["image"])


class ImportYamtrackEpisodeHistoryDate(TestCase):
    """Test episode history dates from Yamtrack CSV exports."""

    def setUp(self):
        """Create an importing user."""
        self.user = get_user_model().objects.create_user(
            username="test",
            password="12345",
        )

    def test_episode_history_date_falls_back_to_end_date(self):
        """A blank progressed_at uses the episode watch date."""
        csv_data = """media_id,source,media_type,title,image,season_number,episode_number,score,progress,status,start_date,end_date,notes,progressed_at
1668,tmdb,tv,Friends,https://image.url,,,,1,In progress,,,,2025-11-20T10:00:00+00:00
1668,tmdb,season,Friends,https://image.url,1,,,1,In progress,,,,2025-11-20T10:00:00+00:00
1668,tmdb,episode,Friends,https://image.url,1,1,,,,,2025-11-19T19:00:05+00:00,,
"""

        yamtrack.importer(BytesIO(csv_data.encode()), self.user, "new")

        episode = Episode.objects.get(related_season__user=self.user)
        self.assertEqual(
            episode.history.get().history_date,
            datetime(2025, 11, 19, 19, 0, 5, tzinfo=UTC),
        )


@tag("network")
class ImportYamtrackPartials(TestCase):
    """Test importing yamtrack media with no ID."""

    def setUp(self):
        """Create user for the tests."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        with Path(mock_path / "import_yamtrack_partials.csv").open("rb") as file:
            self.import_results = yamtrack.importer(file, self.user, "new")

    def test_import_counts(self):
        """Test basic counts of imported media."""
        self.assertEqual(Book.objects.filter(user=self.user).count(), 3)
        self.assertEqual(Movie.objects.filter(user=self.user).count(), 1)

    def test_end_dates(self):
        """Test end dates during import."""
        book = Book.objects.filter(user=self.user).first()
        self.assertEqual(book.history.count(), 1)
        bookqs = Book.objects.filter(
            user=self.user,
            item__title="Warlock",
        ).order_by("-end_date")
        books = list(bookqs)

        self.assertEqual(len(books), 3)
        self.assertEqual(
            books[0].end_date,
            datetime(2024, 5, 9, 0, 0, 0, tzinfo=UTC),
        )
        self.assertEqual(
            books[1].end_date,
            datetime(2024, 4, 9, 0, 0, 0, tzinfo=UTC),
        )
        self.assertEqual(
            books[2].end_date,
            datetime(2024, 3, 9, 0, 0, 0, tzinfo=UTC),
        )


class ImportYamtrackLists(TestCase):
    """Test importing yamtrack lists and list items."""

    def setUp(self):
        """Create user for the tests."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        with Path(mock_path / "import_yamtrack_with_lists.csv").open("rb") as file:
            self.import_results = yamtrack.importer(file, self.user, "new")

    def test_list_created(self):
        """Ensure list rows create lists."""
        custom_list = CustomList.objects.filter(
            owner=self.user, name="Favorites"
        ).first()
        self.assertIsNotNone(custom_list)
        self.assertEqual(custom_list.description, "Top picks")
        self.assertEqual(custom_list.tags, ["tag1", "tag2"])

    def test_list_item_created(self):
        """Ensure list item rows create list items without tracking media."""
        custom_list = CustomList.objects.get(owner=self.user, name="Favorites")
        self.assertEqual(
            CustomListItem.objects.filter(custom_list=custom_list).count(), 2
        )
        titles = set(
            CustomListItem.objects.filter(custom_list=custom_list).values_list(
                "item__title", flat=True
            )
        )
        self.assertIn("Manual Book", titles)
        self.assertIn("Manual Episode S1E1", titles)

    def test_episode_list_item_created(self):
        """Episode items should be importable as list items (issue #93)."""
        custom_list = CustomList.objects.get(owner=self.user, name="Favorites")
        episode_item = CustomListItem.objects.filter(
            custom_list=custom_list,
            item__media_type="episode",
        ).first()
        self.assertIsNotNone(episode_item)
        self.assertEqual(episode_item.item.title, "Manual Episode S1E1")
        self.assertEqual(episode_item.item.season_number, 1)
        self.assertEqual(episode_item.item.episode_number, 1)

    def test_list_item_does_not_track_media(self):
        """List items should not create tracked media entries."""
        self.assertEqual(Book.objects.filter(user=self.user).count(), 0)
        self.assertEqual(
            Episode.objects.filter(related_season__user=self.user).count(), 0
        )


class ImportYamtrackListsOnly(TestCase):
    """Test the lists_only import flag used by the per-list CSV import."""

    def setUp(self):
        """Create user for the tests."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        with Path(mock_path / "import_yamtrack_with_lists.csv").open("rb") as file:
            self.import_results = yamtrack.importer(
                file, self.user, "new", lists_only=True
            )

    def test_list_and_list_items_still_created(self):
        """List and list_item rows are processed even with lists_only=True."""
        custom_list = CustomList.objects.filter(
            owner=self.user, name="Favorites"
        ).first()
        self.assertIsNotNone(custom_list)
        self.assertEqual(
            CustomListItem.objects.filter(custom_list=custom_list).count(), 2
        )

    def test_media_row_skipped(self):
        """Media rows in the CSV are ignored when lists_only=True."""
        self.assertEqual(Movie.objects.filter(user=self.user).count(), 0)
        self.assertFalse(Item.objects.filter(media_id="manualmovie1").exists())


class ImportYamtrackStatusNormalization(TestCase):
    """Test status normalization during Yamtrack import."""

    def setUp(self):
        """Create user for the tests."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        with Path(mock_path / "import_yamtrack_status_normalization.csv").open(
            "rb"
        ) as file:
            self.import_results = yamtrack.importer(file, self.user, "new")

    def test_status_values_are_normalized(self):
        """Ensure status values are normalized to Status choices."""
        tv = TV.objects.filter(user=self.user).first()
        season = Season.objects.filter(user=self.user).first()

        self.assertIsNotNone(tv)
        self.assertIsNotNone(season)
        self.assertEqual(tv.status, Status.COMPLETED.value)
        self.assertEqual(season.status, Status.IN_PROGRESS.value)


class ImportYamtrackStatuslessRoundTrip(TestCase):
    """A rating-only media row survives an export/import cycle without a status."""

    def setUp(self):
        """Export a statusless, rated movie for a second user to import."""
        self.exporter = get_user_model().objects.create_user(
            username="statusless-exporter",
            password="12345",
        )
        self.importer_user = get_user_model().objects.create_user(
            username="statusless-importer",
            password="12345",
        )
        item, _ = Item.objects.get_or_create(
            media_id="10494",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            season_number=None,
            episode_number=None,
            defaults={"title": "Perfect Blue", "image": "https://image.url"},
        )
        Movie.objects.create(
            item=item,
            user=self.exporter,
            status=None,
            score=8,
        )
        self.csv_bytes = "".join(exports.generate_rows(self.exporter)).encode("utf-8")

    def test_statusless_media_round_trips_as_null(self):
        """An exported blank status must come back as NULL, not an empty string."""
        yamtrack.importer(BytesIO(self.csv_bytes), self.importer_user, "new")

        movie = Movie.objects.get(user=self.importer_user)
        self.assertIsNone(movie.status)
        self.assertEqual(movie.score, 8)


class ImportYamtrackTagsRoundTrip(TestCase):
    """An item's tags survive an export/import cycle (issue #574)."""

    def setUp(self):
        """Export a tagged movie for a second user to import."""
        self.exporter = get_user_model().objects.create_user(
            username="tags-exporter",
            password="12345",
        )
        self.importer_user = get_user_model().objects.create_user(
            username="tags-importer",
            password="12345",
        )
        item, _ = Item.objects.get_or_create(
            media_id="1368337",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            season_number=None,
            episode_number=None,
            defaults={"title": "The Odyssey", "image": "https://image.url"},
        )
        Movie.objects.create(item=item, user=self.exporter, status=Status.COMPLETED.value)
        tag = Tag.objects.create(user=self.exporter, name="ABCXYZ")
        ItemTag.objects.create(tag=tag, item=item)
        self.csv_content = "".join(exports.generate_rows(self.exporter))

    def test_export_includes_tags(self):
        """The CSV's item_tags column includes the tag name."""
        self.assertIn("ABCXYZ", self.csv_content)

    def test_import_restores_tags(self):
        """Re-importing the CSV recreates the Tag/ItemTag rows for the new user."""
        yamtrack.importer(
            BytesIO(self.csv_content.encode("utf-8")),
            self.importer_user,
            "new",
        )

        movie = Movie.objects.get(user=self.importer_user)
        tag_names = list(
            ItemTag.objects.filter(item=movie.item, tag__user=self.importer_user)
            .values_list("tag__name", flat=True)
        )
        self.assertEqual(tag_names, ["ABCXYZ"])


@tag("network")
class ImportSampleTemplate(TestCase):
    """Test that the downloadable sample template imports cleanly, unmodified."""

    def setUp(self):
        """Create a user and import the generated sample template."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        content = exports.generate_sample_template()
        file = BytesIO(content.encode("utf-8"))
        self.import_results, self.warnings = yamtrack.importer(file, self.user, "new")

    def test_no_warnings(self):
        """The sample template should import without any warnings."""
        self.assertEqual(self.warnings, "")

    def test_media_created_for_each_type(self):
        """Five real items of every trackable media type should be created."""
        self.assertEqual(Movie.objects.filter(user=self.user).count(), 5)
        self.assertEqual(TV.objects.filter(user=self.user).count(), 5)
        self.assertEqual(Season.objects.filter(user=self.user).count(), 5)
        self.assertEqual(Anime.objects.filter(user=self.user).count(), 5)
        self.assertEqual(Manga.objects.filter(user=self.user).count(), 5)
        self.assertEqual(Game.objects.filter(user=self.user).count(), 5)
        self.assertEqual(Book.objects.filter(user=self.user).count(), 5)
        self.assertEqual(Comic.objects.filter(user=self.user).count(), 5)
        self.assertEqual(BoardGame.objects.filter(user=self.user).count(), 5)
        self.assertEqual(Podcast.objects.filter(user=self.user).count(), 5)

    def test_real_titles_used(self):
        """Imported items should carry real, recognizable titles, not placeholders."""
        movie_titles = set(
            Movie.objects.filter(user=self.user).values_list("item__title", flat=True)
        )
        self.assertIn("Pulp Fiction", movie_titles)
        tv_titles = set(
            TV.objects.filter(user=self.user).values_list("item__title", flat=True)
        )
        self.assertIn("Friends", tv_titles)
        self.assertFalse(any("Sample" in title for title in movie_titles | tv_titles))

    def test_music_artists_and_albums_created_from_musicbrainz(self):
        """Music rows should fetch and create real Artist/Album records on demand."""
        self.assertEqual(Artist.objects.filter(musicbrainz_id__isnull=False).count(), 5)
        self.assertEqual(ArtistTracker.objects.filter(user=self.user).count(), 5)
        self.assertEqual(AlbumTracker.objects.filter(user=self.user).count(), 5)
        self.assertTrue(Artist.objects.filter(name="Radiohead").exists())
        self.assertTrue(Album.objects.filter(title="OK Computer").exists())

    def test_per_type_lists_created(self):
        """A regular list should be created for each media type, with its 5 items."""
        for media_type, list_name in (
            ("movie", "Sample Movies"),
            ("tv", "Sample TV Shows"),
            ("season", "Sample TV Seasons"),
            ("anime", "Sample Anime"),
            ("manga", "Sample Manga"),
            ("game", "Sample Games"),
            ("book", "Sample Books"),
            ("comic", "Sample Comics"),
            ("boardgame", "Sample Board Games"),
            ("podcast", "Sample Podcasts"),
        ):
            custom_list = CustomList.objects.get(owner=self.user, name=list_name)
            self.assertFalse(custom_list.is_smart)
            list_items = CustomListItem.objects.filter(custom_list=custom_list)
            self.assertEqual(list_items.count(), 5)
            self.assertTrue(
                list_items.filter(item__media_type=media_type).exists(),
            )

    def test_no_music_list_since_trackers_are_not_item_backed(self):
        """Music can't join a CustomList since Artist/Album aren't Item-backed."""
        self.assertFalse(
            CustomList.objects.filter(owner=self.user, name__icontains="Music").exists()
        )

    def test_smart_list_created_and_synced(self):
        """The cross-type smart list should be created and auto-populated."""
        custom_list = CustomList.objects.get(
            owner=self.user,
            name="Top-Rated Completed (All Types)",
        )
        self.assertTrue(custom_list.is_smart)
        self.assertEqual(
            custom_list.smart_filters, {"status": "Completed", "rating_min": "8"}
        )

        list_item_media_types = set(
            CustomListItem.objects.filter(custom_list=custom_list).values_list(
                "item__media_type",
                flat=True,
            ),
        )
        # Exactly one top-rated Completed item per list-eligible media type should match.
        expected_media_types = {
            "movie",
            "tv",
            "season",
            "anime",
            "manga",
            "game",
            "book",
            "comic",
            "boardgame",
            "podcast",
        }
        self.assertEqual(list_item_media_types, expected_media_types)
        self.assertEqual(
            CustomListItem.objects.filter(custom_list=custom_list).count(),
            len(expected_media_types),
        )

    def test_sample_collection_entry_created(self):
        """The sample template's collection row should create a collection entry."""
        entries = CollectionEntry.objects.filter(user=self.user)
        self.assertEqual(entries.count(), 1)
        entry = entries.first()
        self.assertEqual(entry.item.title, "Pulp Fiction")
        self.assertEqual(entry.media_type, "4K Blu-ray")


class ImportYamtrackCollectionRoundTrip(TestCase):
    """Test that collection entries round-trip through export and import."""

    def setUp(self):
        """Create an exporting user with collection entries and build the CSV."""
        self.exporter = get_user_model().objects.create_user(
            username="exporter",
            password="12345",
        )
        self.importer_user = get_user_model().objects.create_user(
            username="importer",
            password="12345",
        )

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
            user=self.exporter,
            item=movie_item,
            media_type="4K Blu-ray",
            resolution="4K",
            hdr="Dolby Vision",
            audio_codec="Dolby Atmos",
            audio_channels="7.1",
            bitrate=8000,
        )
        CollectionEntry.objects.create(
            user=self.exporter,
            item=movie_item,
            media_type="DVD",
        )
        episode_entry = CollectionEntry.objects.create(
            user=self.exporter,
            item=episode_item,
        )
        self.episode_collected_at = datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)
        CollectionEntry.objects.filter(id=episode_entry.id).update(
            collected_at=self.episode_collected_at,
        )

        self.csv_bytes = "".join(exports.generate_rows(self.exporter)).encode("utf-8")

    def _import(self, mode):
        return yamtrack.importer(BytesIO(self.csv_bytes), self.importer_user, mode)

    def test_round_trip_new_mode(self):
        """Collection entries import with all metadata and timestamps intact."""
        counts, warnings = self._import("new")
        self.assertEqual(warnings, "")
        self.assertEqual(counts.get("collection"), 3)

        entries = CollectionEntry.objects.filter(user=self.importer_user)
        self.assertEqual(entries.count(), 3)

        full_copy = entries.get(media_type="4K Blu-ray")
        self.assertEqual(full_copy.item.media_id, "10494")
        self.assertEqual(full_copy.resolution, "4K")
        self.assertEqual(full_copy.hdr, "Dolby Vision")
        self.assertEqual(full_copy.audio_codec, "Dolby Atmos")
        self.assertEqual(full_copy.audio_channels, "7.1")
        self.assertEqual(full_copy.bitrate, 8000)
        self.assertFalse(full_copy.is_3d)

        episode_entry = entries.get(item__media_type=MediaTypes.EPISODE.value)
        self.assertEqual(episode_entry.item.season_number, 1)
        self.assertEqual(episode_entry.item.episode_number, 1)
        self.assertEqual(episode_entry.collected_at, self.episode_collected_at)

    def test_reimport_new_mode_skips_identical(self):
        """Re-importing the same file does not duplicate collection entries."""
        self._import("new")
        counts, _ = self._import("new")
        self.assertNotIn("collection", counts)
        self.assertEqual(
            CollectionEntry.objects.filter(user=self.importer_user).count(),
            3,
        )

    def test_overwrite_mode_replaces_existing_entries(self):
        """Overwrite mode replaces divergent entries with the CSV copies."""
        movie_item = Item.objects.get(
            media_id="10494",
            media_type=MediaTypes.MOVIE.value,
        )
        CollectionEntry.objects.create(
            user=self.importer_user,
            item=movie_item,
            media_type="VHS",
        )

        counts, _ = self._import("overwrite")
        self.assertEqual(counts.get("collection"), 3)

        movie_entries = CollectionEntry.objects.filter(
            user=self.importer_user,
            item=movie_item,
        )
        self.assertEqual(
            sorted(movie_entries.values_list("media_type", flat=True)),
            ["4K Blu-ray", "DVD"],
        )
