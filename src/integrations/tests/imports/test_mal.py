import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, tag

from app.models import (
    Anime,
    DeletedMedia,
    Item,
    Manga,
    MediaTypes,
    Movie,
    Sources,
    Status,
)
from integrations.imports import (
    helpers,
    mal,
)

mock_path = Path(__file__).resolve().parent.parent / "mock_data"
app_mock_path = (
    Path(__file__).resolve().parent.parent.parent.parent / "app" / "tests" / "mock_data"
)


class ImportMAL(TestCase):
    """Test importing media from MyAnimeList."""

    def setUp(self):
        """Create user for the tests."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

    @patch("requests.Session.get")
    def test_unrated_entries_and_repeats_have_no_score(self, mock_request):
        responses = []
        for media_type in ("anime", "manga"):
            with Path(mock_path / f"import_mal_{media_type}.json").open() as file:
                response = json.load(file)
            status = response["data"][0]["list_status"]
            status["score"] = 0
            repeat_field = "num_times_rewatched" if media_type == "anime" else "num_times_reread"
            status[repeat_field] = 1
            mock_response = MagicMock()
            mock_response.json.return_value = response
            responses.append(mock_response)
        mock_request.side_effect = responses

        mal.importer("bloodthirstiness", self.user, "new")

        for model in (Anime, Manga):
            self.assertGreaterEqual(
                model.objects.filter(user=self.user, score__isnull=True).count(), 2
            )

    @patch("integrations.webhooks.anime_mappings.fetch_mapping_data")
    def test_unrated_anime_synced_to_movie_has_no_score(self, mock_mapping):
        mock_mapping.return_value = {"tmdb_movie:99999": {"mal:32253": {}}}
        item = Item.objects.create(
            media_id="99999",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Movie",
        )
        Movie.objects.create(user=self.user, item=item, score=5)
        importer = mal.MyAnimeListImporter("test", self.user, "overwrite")
        with Path(mock_path / "import_mal_anime.json").open() as file:
            entry = json.load(file)["data"][0]
        entry["list_status"]["score"] = 0

        importer._process_entry(entry, MediaTypes.ANIME.value)

        self.assertIsNone(importer.bulk_media[MediaTypes.MOVIE.value][0].score)

    @patch("requests.Session.get")
    def test_import_animelist(self, mock_request):
        """Basic test importing anime and manga from MyAnimeList."""
        with Path(mock_path / "import_mal_anime.json").open(encoding="utf-8") as file:
            anime_response = json.load(file)
        with Path(mock_path / "import_mal_manga.json").open(encoding="utf-8") as file:
            manga_response = json.load(file)

        anime_mock = MagicMock()
        anime_mock.json.return_value = anime_response
        manga_mock = MagicMock()
        manga_mock.json.return_value = manga_response
        mock_request.side_effect = [anime_mock, manga_mock]

        mal.importer("bloodthirstiness", self.user, "new")
        self.assertEqual(Anime.objects.filter(user=self.user).count(), 6)
        self.assertEqual(Manga.objects.filter(user=self.user).count(), 3)

        self.assertEqual(
            Anime.objects.filter(
                user=self.user,
                item__title="Ama Gli Animali",
            )
            .first()
            .item.image,
            settings.IMG_NONE,
        )
        self.assertEqual(
            Anime.objects.get(user=self.user, item__title="FLCL").status,
            Status.PAUSED.value,
        )
        self.assertEqual(
            Manga.objects.get(user=self.user, item__title="Fire Punch").score,
            7,
        )

        self.assertEqual(
            Anime.objects.filter(
                user=self.user,
                item__title="Chainsaw Man",
            )
            .first()
            .history.first()
            .history_date,
            datetime(2022, 12, 28, 19, 20, 54, tzinfo=UTC),
        )

        erased_item = Item.objects.get(
            media_id="31043",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
        )
        self.assertEqual(erased_item.title, "Erased")
        self.assertEqual(erased_item.localized_title, "Erased")
        self.assertEqual(erased_item.original_title, "Boku dake ga Inai Machi")

    @patch("requests.Session.get")
    def test_import_does_not_bring_back_a_deleted_anime(self, mock_request):
        """An anime the user deleted by hand stays deleted across syncs (#1133)."""
        with Path(mock_path / "import_mal_anime.json").open(encoding="utf-8") as file:
            anime_response = json.load(file)
        with Path(mock_path / "import_mal_manga.json").open(encoding="utf-8") as file:
            manga_response = json.load(file)
        anime_mock = MagicMock()
        anime_mock.json.return_value = anime_response
        manga_mock = MagicMock()
        manga_mock.json.return_value = manga_response
        mock_request.side_effect = [anime_mock, manga_mock]
        DeletedMedia.objects.create(
            user=self.user,
            media_type=MediaTypes.ANIME.value,
            source=Sources.MAL.value,
            media_id="31043",
        )

        mal.importer("bloodthirstiness", self.user, "new")

        self.assertEqual(Anime.objects.filter(user=self.user).count(), 5)
        self.assertFalse(
            Anime.objects.filter(user=self.user, item__media_id="31043").exists(),
        )

    @tag("network")
    def test_user_not_found(self):
        """Test that an error is raised if the user is not found."""
        self.assertRaises(
            helpers.MediaImportError,
            mal.importer,
            "fhdsufdsu",
            self.user,
            "new",
        )

    @patch("integrations.imports.mal.MyAnimeListImporter._get_whole_response")
    def test_private_manga_list_is_skipped_with_warning(self, mock_get_response):
        """A private manga list is skipped with a warning, anime still imports."""
        with Path(mock_path / "import_mal_anime.json").open(encoding="utf-8") as file:
            anime_response = json.load(file)

        forbidden_response = MagicMock()
        forbidden_response.status_code = requests.codes.forbidden
        forbidden_error = requests.exceptions.HTTPError(response=forbidden_response)

        mock_get_response.side_effect = [anime_response, forbidden_error]

        imported_counts, warnings = mal.importer("bloodthirstiness", self.user, "new")

        self.assertEqual(Anime.objects.filter(user=self.user).count(), 6)
        self.assertEqual(Manga.objects.filter(user=self.user).count(), 0)
        self.assertNotIn(MediaTypes.MANGA.value, imported_counts)
        self.assertIn("manga", warnings)
        self.assertIn("private", warnings)

    @patch("app.models.media.Media.process_status")
    @patch("integrations.webhooks.anime_mappings.fetch_mapping_data")
    @patch("requests.Session.get")
    def test_overwrite_syncs_to_existing_movie_entry(
        self, mock_request, mock_mapping, _mock_ps
    ):
        """MAL overwrite import also updates a corresponding Movie entry."""
        # MAL ID 32253 ("Ama Gli Animali", completed, score=7) maps to TMDB movie 99999
        mock_mapping.return_value = {"tmdb_movie:99999": {"mal:32253": {}}}

        movie_item = Item.objects.create(
            media_id="99999",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Ama Gli Animali",
            image="http://example.com/img.jpg",
        )
        Movie.objects.create(
            item=movie_item,
            user=self.user,
            progress=1,
            status=Status.COMPLETED.value,
            score=5,  # stale score — should be overwritten
        )

        with Path(mock_path / "import_mal_anime.json").open(encoding="utf-8") as file:
            anime_response = json.load(file)
        with Path(mock_path / "import_mal_manga.json").open(encoding="utf-8") as file:
            manga_response = json.load(file)

        anime_mock = MagicMock()
        anime_mock.json.return_value = anime_response
        manga_mock = MagicMock()
        manga_mock.json.return_value = manga_response
        mock_request.side_effect = [anime_mock, manga_mock]

        mal.importer("bloodthirstiness", self.user, "overwrite")

        movie = Movie.objects.get(item=movie_item, user=self.user)
        self.assertEqual(int(movie.score), 7)  # updated from MAL (was 5)
        self.assertEqual(movie.status, Status.IN_PROGRESS.value)  # is_rewatching=True


class ImportMALExistingTitles(TestCase):
    """Import New brings titles Floppy already tracks forward, never back (#1942)."""

    def setUp(self):
        """Create a user and the MAL fixtures' shape."""
        self.user = get_user_model().objects.create_user(
            username="test",
            password="12345",
        )

    def _track(self, media_type, media_id="1", **fields):
        item = Item.objects.create(
            media_id=media_id,
            source=Sources.MAL.value,
            media_type=media_type,
            title=f"Title {media_id}",
        )
        model = Anime if media_type == MediaTypes.ANIME.value else Manga
        return model.objects.create(user=self.user, item=item, **fields)

    def _entry(self, media_type, media_id="1", **list_status):
        is_anime = media_type == MediaTypes.ANIME.value
        status = {
            "status": "watching" if is_anime else "reading",
            "score": 0,
            "comments": "",
            "updated_at": "2026-11-12T16:46:00+00:00",
            "num_times_rewatched" if is_anime else "num_times_reread": 0,
            "is_rewatching" if is_anime else "is_rereading": False,
            "num_episodes_watched" if is_anime else "num_chapters_read": 0,
        }
        status.update(list_status)
        return {
            "node": {
                "id": int(media_id),
                "title": f"Title {media_id}",
                "main_picture": {"large": "https://example.com/a.jpg"},
            },
            "list_status": status,
        }

    def _run(self, anime=(), manga=(), mode="new"):
        responses = [
            {"data": list(anime), "paging": {}},
            {"data": list(manga), "paging": {}},
        ]
        with patch(
            "integrations.imports.mal.MyAnimeListImporter._get_whole_response",
            side_effect=responses,
        ):
            return mal.importer("test", self.user, mode)[0]

    def test_anime_behind_advances_progress_and_status(self):
        row = self._track(
            MediaTypes.ANIME.value,
            progress=3,
            status=Status.PLANNING.value,
        )

        counts = self._run(anime=[self._entry("anime", num_episodes_watched=7)])

        row.refresh_from_db()
        self.assertEqual(row.progress, 7)
        self.assertEqual(row.status, Status.IN_PROGRESS.value)
        self.assertEqual(Anime.objects.filter(user=self.user).count(), 1)
        self.assertEqual(counts["updated"], 1)
        self.assertEqual(counts["created"], 0)
        self.assertEqual(
            row.history.order_by("-history_id").first().history_change_reason,
            "MyAnimeList import",
        )

    def test_manga_behind_advances_progress(self):
        row = self._track(MediaTypes.MANGA.value, progress=10, status=Status.IN_PROGRESS.value)

        self._run(manga=[self._entry("manga", num_chapters_read=15)])

        row.refresh_from_db()
        self.assertEqual(row.progress, 15)
        self.assertEqual(Manga.objects.filter(user=self.user).count(), 1)

    def test_completed_on_mal_completes_local(self):
        row = self._track(MediaTypes.ANIME.value, progress=3, status=Status.IN_PROGRESS.value)

        self._run(
            anime=[self._entry("anime", status="completed", num_episodes_watched=12)],
        )

        row.refresh_from_db()
        self.assertEqual(row.status, Status.COMPLETED.value)
        self.assertEqual(row.progress, 12)

    def test_local_ahead_is_left_alone(self):
        row = self._track(MediaTypes.ANIME.value, progress=9, status=Status.COMPLETED.value)

        counts = self._run(anime=[self._entry("anime", num_episodes_watched=4)])

        row.refresh_from_db()
        self.assertEqual((row.progress, row.status), (9, Status.COMPLETED.value))
        self.assertNotIn("updated", counts)
        self.assertEqual(counts["unchanged"], 1)
        self.assertEqual(row.history.count(), 1)

    def test_paused_and_dropped_keep_their_status_but_gain_progress(self):
        paused = self._track(
            MediaTypes.ANIME.value, "1", progress=3, status=Status.PAUSED.value,
        )
        dropped = self._track(
            MediaTypes.MANGA.value, "2", progress=3, status=Status.DROPPED.value,
        )

        self._run(
            anime=[self._entry("anime", "1", num_episodes_watched=6)],
            manga=[self._entry("manga", "2", num_chapters_read=6, status="completed")],
        )

        paused.refresh_from_db()
        dropped.refresh_from_db()
        self.assertEqual((paused.progress, paused.status), (6, Status.PAUSED.value))
        self.assertEqual((dropped.progress, dropped.status), (6, Status.DROPPED.value))

    def test_status_never_regresses(self):
        completed = self._track(
            MediaTypes.ANIME.value, "1", progress=12, status=Status.COMPLETED.value,
        )
        in_progress = self._track(
            MediaTypes.ANIME.value, "2", progress=5, status=Status.IN_PROGRESS.value,
        )

        counts = self._run(
            anime=[
                self._entry("anime", "1", status="plan_to_watch"),
                self._entry("anime", "2", status="plan_to_watch"),
            ],
        )

        completed.refresh_from_db()
        in_progress.refresh_from_db()
        self.assertEqual(completed.status, Status.COMPLETED.value)
        self.assertEqual(in_progress.status, Status.IN_PROGRESS.value)
        self.assertNotIn("updated", counts)

    def test_local_score_notes_and_dates_are_kept_and_gaps_filled(self):
        kept_date = datetime(2025, 1, 2, tzinfo=UTC)
        kept = self._track(
            MediaTypes.ANIME.value,
            "1",
            progress=1,
            status=Status.IN_PROGRESS.value,
            score=9,
            notes="mine",
            start_date=kept_date,
        )
        empty = self._track(
            MediaTypes.ANIME.value,
            "2",
            progress=1,
            status=Status.IN_PROGRESS.value,
        )
        remote = {
            "num_episodes_watched": 4,
            "score": 6,
            "comments": "from MAL",
            "start_date": "2024-03-04",
            "finish_date": "2024-05-06",
        }

        self._run(
            anime=[
                self._entry("anime", "1", **remote),
                self._entry("anime", "2", **remote),
            ],
        )

        kept.refresh_from_db()
        empty.refresh_from_db()
        self.assertEqual((kept.score, kept.notes, kept.start_date), (9, "mine", kept_date))
        self.assertEqual(kept.end_date.date().isoformat(), "2024-05-06")
        self.assertEqual((empty.score, empty.notes), (6, "from MAL"))
        self.assertEqual(empty.start_date.date().isoformat(), "2024-03-04")
        self.assertIsNotNone(empty.scored_at)

    def test_blank_mal_fields_do_not_erase_local_values(self):
        row = self._track(
            MediaTypes.MANGA.value,
            progress=2,
            status=Status.IN_PROGRESS.value,
            score=8,
            notes="mine",
        )

        self._run(manga=[self._entry("manga", num_chapters_read=5)])

        row.refresh_from_db()
        self.assertEqual((row.progress, row.score, row.notes), (5, 8, "mine"))

    def test_importing_the_same_snapshot_twice_writes_nothing_more(self):
        row = self._track(MediaTypes.ANIME.value, progress=3, status=Status.PLANNING.value)
        entry = self._entry("anime", num_episodes_watched=7, score=7)

        self._run(anime=[entry])
        history_after_first = row.history.count()
        second = self._run(anime=[entry])

        self.assertNotIn("updated", second)
        self.assertEqual(row.history.count(), history_after_first)
        self.assertEqual(Anime.objects.filter(user=self.user).count(), 1)

    def test_deleted_titles_are_not_updated_or_recreated(self):
        row = self._track(MediaTypes.ANIME.value, progress=3, status=Status.PLANNING.value)
        DeletedMedia.objects.create(
            user=self.user,
            media_type=MediaTypes.ANIME.value,
            source=Sources.MAL.value,
            media_id="1",
        )

        self._run(anime=[self._entry("anime", num_episodes_watched=7)])

        row.refresh_from_db()
        self.assertEqual(row.progress, 3)

    def test_new_titles_still_import_alongside_updates(self):
        self._track(MediaTypes.ANIME.value, "1", progress=1, status=Status.IN_PROGRESS.value)

        counts = self._run(
            anime=[
                self._entry("anime", "1", num_episodes_watched=5),
                self._entry("anime", "2", num_episodes_watched=2),
            ],
        )

        self.assertEqual(Anime.objects.filter(user=self.user).count(), 2)
        self.assertEqual((counts["created"], counts["updated"]), (1, 1))

    def test_rewatch_rows_are_compared_against_the_furthest_one(self):
        finished = self._track(
            MediaTypes.ANIME.value, progress=12, status=Status.COMPLETED.value,
        )
        Anime.objects.create(
            user=self.user, item=finished.item, progress=2, status=Status.IN_PROGRESS.value,
        )

        counts = self._run(anime=[self._entry("anime", num_episodes_watched=12, status="completed")])

        self.assertNotIn("updated", counts)
        self.assertEqual(Anime.objects.filter(user=self.user).count(), 2)

    def test_update_does_not_queue_a_push_back_to_mal(self):
        self._track(MediaTypes.ANIME.value, progress=3, status=Status.PLANNING.value)

        with (
            patch("integrations.mal_sync.per_item_sync_active", return_value=True),
            patch("integrations.tasks.sync_mal_status.delay") as mock_delay,
        ):
            self._run(anime=[self._entry("anime", num_episodes_watched=7)])

        mock_delay.assert_not_called()

    def test_overwrite_still_replaces_the_existing_row(self):
        row = self._track(MediaTypes.ANIME.value, progress=9, status=Status.COMPLETED.value)

        self._run(anime=[self._entry("anime", num_episodes_watched=4)], mode="overwrite")

        self.assertFalse(Anime.objects.filter(pk=row.pk).exists())
        replaced = Anime.objects.get(user=self.user, item__media_id="1")
        self.assertEqual(replaced.progress, 4)
