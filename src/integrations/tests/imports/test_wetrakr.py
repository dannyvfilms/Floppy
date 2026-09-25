import zipfile
from datetime import UTC, datetime
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from app.models import TV, Episode, Item, MediaTypes, Movie, Sources, Status
from integrations.imports.helpers import MediaImportError
from integrations.imports.wetrakr import WeTrakrExport, importer, parse_wetrakr_date
from integrations.upload_staging import discard_staged_upload
from lists.models import CustomList, CustomListItem

# Rows below are copied from the WeTrakr export samples attached to issue #421.
TRACKLOG_HEADER = (
    "title,year,type,tmdb_id,imdb_id,show_title,season_number,episode_number,"
    "status,tracked_at,updated_at\n"
)
UPDATED = "Tue May 26 2026 09:08:09 GMT+0000 (Coordinated Universal Time)"
RATINGS_HEADER = (
    "title,year,type,tmdb_id,imdb_id,show_title,season_number,episode_number,"
    "rating,rated_at\n"
)
LISTS_HEADER = "list_name,list_description,title,year,type,tmdb_id,imdb_id,rank,created_at\n"


def _date(text):
    return f"{text} GMT+0000 (Coordinated Universal Time)"


def _zip_bytes(files):
    """Build an in-memory zip from a {filename: text} mapping."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    buffer.seek(0)
    return buffer


def _metadata_side_effect(media_type, _tmdb_id, _title, _season_number=None):
    if media_type == MediaTypes.TV.value:
        return {
            "title": "Show",
            "image": "tv.jpg",
            "last_episode_season": 1,
            "related": {"seasons": [{"season_number": 1}]},
        }
    if media_type == MediaTypes.SEASON.value:
        return {
            "title": "Season 1",
            "image": "season.jpg",
            "max_progress": 2,
            "episodes": [
                {"episode_number": n, "still_path": f"/s{n}.jpg"} for n in (1, 2)
            ],
        }
    return {"title": "Movie", "image": "movie.jpg"}


def _find_episode(imdb_id, _source):
    """Stand in for TMDB /find: Great Expectations episodes belong to show 555."""
    episodes = {
        "tt13071520": {"show_id": 555, "season_number": 1, "episode_number": 1},
        "tt18396332": {"show_id": 555, "season_number": 1, "episode_number": 2},
    }
    match = episodes.get(imdb_id)
    return {"tv_episode_results": [match] if match else []}


class ParseDateTests(TestCase):
    """WeTrakr writes dates as JavaScript Date.toString() text."""

    def test_parses_javascript_date_text(self):
        self.assertEqual(
            parse_wetrakr_date(_date("Wed Mar 21 2018 03:42:00")),
            datetime(2018, 3, 21, 3, 42, tzinfo=UTC),
        )

    def test_parses_full_month_name(self):
        self.assertEqual(
            parse_wetrakr_date(_date("Thu January 1 2026 00:00:00")),
            datetime(2026, 1, 1, tzinfo=UTC),
        )

    def test_blank_or_garbage_is_none(self):
        self.assertIsNone(parse_wetrakr_date(""))
        self.assertIsNone(parse_wetrakr_date("yesterday"))


class WeTrakrExportTests(TestCase):
    """Reading the archive itself, before anything is imported."""

    def test_corrupt_zip_raises_clear_error(self):
        with self.assertRaisesMessage(MediaImportError, "not a valid WeTrakr export"):
            WeTrakrExport(BytesIO(b"not a zip"))

    def test_zip_without_wetrakr_files_raises_clear_error(self):
        with self.assertRaisesMessage(MediaImportError, "No WeTrakr data was found"):
            WeTrakrExport(_zip_bytes({"watched-history-1.json": "[]"}))

    def test_split_tracklog_files_are_combined(self):
        export = WeTrakrExport(
            _zip_bytes(
                {
                    "tracklog_1.csv": TRACKLOG_HEADER
                    + f"Coco,2017,movie,354912,tt2380307,,,,watched,,{UPDATED}\n",
                    "tracklog_2.csv": TRACKLOG_HEADER
                    + f"Loving,2016,movie,339419,tt4669986,,,,watched,,{UPDATED}\n",
                },
            ),
        )

        self.assertEqual(len(export.history()), 2)

    def test_multiline_list_description_survives(self):
        description = (
            "Official Star Trek productions.\n\n"
            'Sorted by production order, **not** "in-universe" chronology.'
        )
        csv_description = description.replace('"', '""')
        export = WeTrakrExport(
            _zip_bytes(
                {
                    "lists.csv": LISTS_HEADER
                    + f'Star Trek (canon),"{csv_description}",Star Trek,,show,253,'
                    f"tt0060028,1,{UPDATED}\n",
                },
            ),
        )

        [(name, parsed_description, entries)] = export.lists()
        self.assertEqual(name, "Star Trek (canon)")
        self.assertEqual(parsed_description, description)
        self.assertEqual(entries[0]["show"]["ids"]["tmdb"], 253)

    def test_history_is_served_newest_first_with_undated_plays_oldest(self):
        export = WeTrakrExport(
            _zip_bytes(
                {
                    "tracklog.csv": TRACKLOG_HEADER
                    + f"Old,2020,movie,1,,,,,watched,{_date('Wed Jul 26 2023 20:38:00')},{UPDATED}\n"
                    + f"Undated,2020,movie,2,,,,,watched,,{UPDATED}\n"
                    + f"New,2020,movie,3,,,,,watched,{_date('Thu Dec 28 2023 18:17:00')},{UPDATED}\n",
                },
            ),
        )

        titles = [entry["movie"]["title"] for entry in export.history()]
        self.assertEqual(titles, ["New", "Old", "Undated"])


@patch("integrations.imports.wetrakr.services.tmdb.find", side_effect=_find_episode)
@patch(
    "integrations.imports.trakt.TraktImporter._get_metadata",
    side_effect=_metadata_side_effect,
)
class WeTrakrImportTests(TestCase):
    """End-to-end imports with TMDB mocked out."""

    def setUp(self):
        """Create a user and clear cached provider payloads."""
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="test",
            password="12345",
        )

    def test_watched_movies_keep_their_dates(self, _metadata, _find):
        export = _zip_bytes(
            {
                "tracklog.csv": TRACKLOG_HEADER
                + "Snake Eyes: G.I. Joe Origins,2021,movie,568620,tt8404256,,,,watched,"
                + f"{_date('Wed Jul 26 2023 20:38:00')},{UPDATED}\n"
                + f"Rogue One: A Star Wars Story,2016,movie,330459,tt3748528,,,,watched,,{UPDATED}\n",
            },
        )

        counts, _ = importer(export, self.user, "new")

        self.assertEqual(counts[MediaTypes.MOVIE.value], 2)
        dated = Movie.objects.get(user=self.user, item__media_id="568620")
        self.assertEqual(dated.status, Status.COMPLETED.value)
        self.assertEqual(dated.end_date, datetime(2023, 7, 26, 20, 38, tzinfo=UTC))
        undated = Movie.objects.get(user=self.user, item__media_id="330459")
        self.assertEqual(undated.status, Status.COMPLETED.value)
        self.assertIsNone(undated.end_date)

    def test_episodes_find_their_show_through_imdb(self, _metadata, mock_find):
        """Episode rows name the show only by title; TMDB /find supplies its id."""
        export = _zip_bytes(
            {
                "tracklog.csv": TRACKLOG_HEADER
                + "Episode 1,,episode,3511866,tt13071520,Great Expectations,1,1,watched,"
                + f"{_date('Sun Mar 22 2026 19:34:29')},{UPDATED}\n"
                + "Episode 2,,episode,4218545,tt18396332,Great Expectations,1,2,watched,"
                + f"{_date('Mon Mar 23 2026 15:29:17')},{UPDATED}\n",
            },
        )

        importer(export, self.user, "new")

        episodes = Episode.objects.filter(related_season__user=self.user)
        self.assertEqual(
            sorted(episodes.values_list("item__media_id", "item__episode_number")),
            [("555", 1), ("555", 2)],
        )
        # One lookup per show, not per episode.
        self.assertEqual(mock_find.call_count, 1)

    def test_show_row_in_export_avoids_tmdb_lookup(self, _metadata, mock_find):
        export = _zip_bytes(
            {
                "tracklog.csv": TRACKLOG_HEADER
                + f"No Offence,,show,62620,tt3922704,,,,watched,,{UPDATED}\n"
                + "Episode 1,,episode,1060001,tt3952325,No Offence,1,1,watched,"
                + f"{_date('Wed Mar 21 2018 03:42:00')},{UPDATED}\n",
            },
        )

        importer(export, self.user, "new")

        self.assertTrue(
            Episode.objects.filter(
                related_season__user=self.user,
                item__media_id="62620",
            ).exists(),
        )
        mock_find.assert_not_called()

    def test_watchlist_and_discarded_statuses(self, _metadata, _find):
        export = _zip_bytes(
            {
                "tracklog.csv": TRACKLOG_HEADER
                + "Groundswell,2022,movie,990009,tt20562474,,,,plantowatch,"
                + f"{_date('Thu Jan 08 2026 14:32:27')},{UPDATED}\n"
                + "Marketplace,,show,12009,tt0251520,,,,discarded,"
                + f"{_date('Tue Jun 21 2022 05:57:00')},{UPDATED}\n"
                + f"Some Movie,2020,movie,4242,,,,,discarded,,{UPDATED}\n",
            },
        )

        importer(export, self.user, "new")

        self.assertEqual(
            Movie.objects.get(user=self.user, item__media_id="990009").status,
            Status.PLANNING.value,
        )
        self.assertEqual(
            Movie.objects.get(user=self.user, item__media_id="4242").status,
            Status.DROPPED.value,
        )
        self.assertEqual(
            TV.objects.get(user=self.user, item__media_id="12009").status,
            Status.DROPPED.value,
        )

    def test_ratings_and_skipped_season_rating(self, _metadata, _find):
        export = _zip_bytes(
            {
                "ratings.csv": RATINGS_HEADER
                + "12.12: The Day,2023,movie,919207,tt22507524,,,,7,"
                + f"{_date('Tue Feb 24 2026 02:36:31')}\n"
                + "Just Shoot Me!,,season,4576,tt0118364,,9352,,7,"
                + f"{_date('Thu May 21 2026 19:21:50')}\n",
            },
        )

        _, messages = importer(export, self.user, "new")

        self.assertEqual(
            Movie.objects.get(user=self.user, item__media_id="919207").score,
            7,
        )
        self.assertIn("Skipped 1 season rating(s)", messages)

    def test_rerun_does_not_duplicate_plays(self, _metadata, _find):
        files = {
            "tracklog.csv": TRACKLOG_HEADER
            + "Episode 1,,episode,3511866,tt13071520,Great Expectations,1,1,watched,"
            + f"{_date('Sun Mar 22 2026 19:34:29')},{UPDATED}\n",
        }

        importer(_zip_bytes(files), self.user, "new")
        importer(_zip_bytes(files), self.user, "new")

        self.assertEqual(
            Episode.objects.filter(related_season__user=self.user).count(),
            1,
        )

    @patch(
        "lists.imports.trakt._get_metadata",
        return_value={"title": "Item", "image": "item.jpg"},
    )
    def test_lists_keep_rank_order_and_resolve_episodes(
        self,
        _list_metadata,
        _metadata,
        _find,
    ):
        """List episodes carry no show, so it comes from the tracklog row."""
        list_name = "#001 \u2013 2026 watched all"  # the real sample uses an en dash
        export = {
            "tracklog.csv": TRACKLOG_HEADER
            + "Episode 1,,episode,3511866,tt13071520,Great Expectations,1,1,watched,"
            + f"{_date('Sun Mar 22 2026 19:34:29')},{UPDATED}\n",
            "lists.csv": LISTS_HEADER
            + f"{list_name},,Prom,2011,movie,51588,tt1604171,385,{UPDATED}\n"
            + f"{list_name},,Four Enchanted Sisters,2020,movie,639854,tt8875940,384,{UPDATED}\n"
            + f"{list_name},,Episode 1,,episode,3511866,,386,{UPDATED}\n"
            + f"{list_name},,The Acolyte,,season,114479,tt12262202,410,{UPDATED}\n",
        }

        counts, messages = importer(_zip_bytes(export), self.user, "new")

        self.assertEqual(counts["lists"], 1)
        custom_list = CustomList.objects.get(owner=self.user, source="wetrakr")
        self.assertEqual(custom_list.name, list_name)
        items = list(
            CustomListItem.objects.filter(custom_list=custom_list)
            .order_by("date_added", "pk")
            .values_list("item__media_id", "item__media_type"),
        )
        self.assertEqual(
            items,
            [
                ("639854", MediaTypes.MOVIE.value),
                ("51588", MediaTypes.MOVIE.value),
                ("555", MediaTypes.EPISODE.value),
            ],
        )
        self.assertIn("Skipped 1 list item(s)", messages)

        # A second import replaces the lists instead of duplicating them.
        importer(_zip_bytes(export), self.user, "new")
        self.assertEqual(
            CustomList.objects.filter(owner=self.user, source="wetrakr").count(),
            1,
        )

    def test_ratings_only_overwrite_keeps_watch_status(self, _metadata, _find):
        """Overwrite without a tracklog must not wipe an item's watch status."""
        item = Item.objects.create(
            media_id="919207",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="12.12: The Day",
            image="",
        )
        Movie.objects.create(item=item, user=self.user, status=Status.COMPLETED.value)
        export = _zip_bytes(
            {
                "ratings.csv": RATINGS_HEADER
                + "12.12: The Day,2023,movie,919207,tt22507524,,,,7,"
                + f"{_date('Tue Feb 24 2026 02:36:31')}\n",
            },
        )

        _, messages = importer(export, self.user, "overwrite")

        movie = Movie.objects.get(user=self.user, item=item)
        self.assertEqual(movie.status, Status.COMPLETED.value)
        self.assertIn("No tracklog.csv was uploaded", messages)

    def test_episode_notes_are_reported_as_skipped(self, _metadata, _find):
        export = _zip_bytes(
            {
                "notes.csv": "title,year,type,tmdb_id,imdb_id,show_title,season_number,"
                "episode_number,text,privacy,spoiler,created_at\n"
                "The Client,,episode,119005,tt0583063,The Fresh Prince of Bel-Air,5,1,"
                f"A two-parter.,private,0,{UPDATED}\n",
            },
        )

        _, messages = importer(export, self.user, "new")

        self.assertIn("Skipped 1 note(s) on episodes or seasons", messages)

    @patch(
        "lists.imports.trakt._get_metadata",
        return_value={"title": "Item", "image": "item.jpg"},
    )
    def test_upload_without_lists_file_keeps_earlier_lists(
        self,
        _list_metadata,
        _metadata,
        _find,
    ):
        importer(
            _zip_bytes(
                {"lists.csv": LISTS_HEADER + f"Faves,,Prom,2011,movie,51588,,1,{UPDATED}\n"},
            ),
            self.user,
            "new",
        )

        importer(
            _zip_bytes(
                {
                    "tracklog.csv": TRACKLOG_HEADER
                    + f"Coco,2017,movie,354912,tt2380307,,,,watched,,{UPDATED}\n",
                },
            ),
            self.user,
            "new",
        )

        self.assertTrue(
            CustomList.objects.filter(owner=self.user, source="wetrakr", name="Faves").exists(),
        )


class WeTrakrUploadViewTests(TestCase):
    """The upload view stages files and queues the import task."""

    def setUp(self):
        """Create and sign in a user."""
        self.user = get_user_model().objects.create_user(
            username="test",
            password="12345",
        )
        self.client.force_login(self.user)
        self.url = reverse("import_wetrakr")

    @patch("integrations.views.tasks.import_wetrakr_export.delay")
    def test_zip_upload_is_queued_as_is(self, mock_delay):
        payload = _zip_bytes({"tracklog.csv": TRACKLOG_HEADER}).getvalue()

        self.client.post(
            self.url,
            {
                "mode": "new",
                "wetrakr_export": SimpleUploadedFile(
                    "export.zip",
                    payload,
                    "application/zip",
                ),
            },
        )

        mock_delay.assert_called_once()
        queued = mock_delay.call_args.kwargs["file"]
        self.addCleanup(discard_staged_upload, queued)
        self.assertTrue(queued.endswith(".zip"))

    @patch("integrations.views.tasks.import_wetrakr_export.delay")
    def test_loose_csv_files_are_zipped(self, mock_delay):
        uploads = [
            SimpleUploadedFile("tracklog.csv", TRACKLOG_HEADER.encode(), "text/csv"),
            SimpleUploadedFile("lists.csv", LISTS_HEADER.encode(), "text/csv"),
        ]

        self.client.post(self.url, {"mode": "new", "wetrakr_export": uploads})

        queued = mock_delay.call_args.kwargs["file"]
        self.addCleanup(discard_staged_upload, queued)
        with zipfile.ZipFile(queued) as archive:
            self.assertEqual(sorted(archive.namelist()), ["lists.csv", "tracklog.csv"])

    @patch("integrations.views.tasks.import_wetrakr_export.delay")
    def test_missing_file_is_rejected(self, mock_delay):
        self.client.post(self.url, {"mode": "new"})

        mock_delay.assert_not_called()
