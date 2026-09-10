from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from app.models import (
    TV,
    Episode,
    Item,
    MediaTypes,
    Season,
    Sources,
    Status,
)
from integrations.imports import stremio
from integrations.models import StremioAccount

User = get_user_model()

class StremioStatusSyncTests(TestCase):
    """A recurring Stremio sync must not overwrite a tracked show's status."""

    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )
        self.tv_item = Item.objects.create(
            media_id="1001",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Alien: Earth",
        )
        self.season_item = Item.objects.create(
            media_id="1001",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Alien: Earth Season 1",
            season_number=1,
        )
        self.tv = TV.objects.create(
            item=self.tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        self.season = Season.objects.create(
            item=self.season_item,
            user=self.user,
            related_tv=self.tv,
            status=Status.IN_PROGRESS.value,
        )
        # Create 3 episodes for Season 1
        for i in range(1, 4):
            ep_item = Item.objects.create(
                media_id="1001",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title=f"Episode {i}",
                season_number=1,
                episode_number=i,
            )
            Episode.objects.create(
                item=ep_item,
                related_season=self.season,
                end_date=timezone.now(),
                status=Status.COMPLETED.value,
            )
    @patch("integrations.imports.helpers.decrypt_or_raise", return_value="dummy-key")
    @patch("app.providers.tmdb.tv_with_seasons")
    def test_stremio_recurring_sync_overwrites_in_progress_tv_status(
        self, mock_tv_with_seasons, mock_decrypt
    ):
        """Stremio sync does NOT promote IN_PROGRESS show to COMPLETED (season is marked COMPLETED)."""
        StremioAccount.objects.create(
            user=self.user,
            auth_key="encrypted-key",
        )
        mock_tv_with_seasons.return_value = {
            "title": "Alien: Earth",
            "max_progress": 3,
            "image": "",
            "seasons": [{"season_number": 1}],
            "season/1": {
                "title": "Alien: Earth Season 1",
                "max_progress": 3,
                "episodes": [
                    {"episode_number": 1, "title": "Ep 1", "image": "", "release_datetime": None, "end_date": None},
                    {"episode_number": 2, "title": "Ep 2", "image": "", "release_datetime": None, "end_date": None},
                    {"episode_number": 3, "title": "Ep 3", "image": "", "release_datetime": None, "end_date": None},
                ],
            },
        }
        importer = stremio.StremioImporter(self.user, mode="new")
        importer.existing_media[MediaTypes.TV.value][Sources.TMDB.value][self.tv_item.media_id] = self.tv
        importer.existing_media[MediaTypes.SEASON.value][Sources.TMDB.value][(self.season_item.media_id, 1)] = self.season

        entry = {
            "_id": "series:1001",
            "name": "Alien: Earth",
            "state": {
                "video_id": "1001:1:3",
                "timeOffset": 0,
                "duration": 1000,
            },
        }
        video_ids = ["1001:1:1", "1001:1:2", "1001:1:3"]
        watched_videos = {"1001:1:1": {}, "1001:1:2": {}, "1001:1:3": {}}

        with patch.object(importer, "_watched_videos", return_value=watched_videos), \
             patch.object(importer, "_resolve_tmdb_id", return_value="1001"):
            importer._process_series(
                entry=entry,
                video_ids=video_ids,
            )

        self.tv.refresh_from_db()
        self.assertEqual(self.tv.status, Status.IN_PROGRESS.value)
        self.season.refresh_from_db()
        self.assertEqual(self.season.status, Status.COMPLETED.value)
    @patch("integrations.imports.helpers.decrypt_or_raise", return_value="dummy-key")
    @patch("app.providers.tmdb.tv_with_seasons")
    def test_stremio_sync_advances_planning_season_to_in_progress(
        self, mock_tv_with_seasons, mock_decrypt
    ):
        """Stremio sync advances PLANNING season to IN_PROGRESS when partially watched."""
        StremioAccount.objects.create(
            user=self.user,
            auth_key="encrypted-key-2",
        )
        self.season.status = Status.PLANNING.value
        self.season.save()

        mock_tv_with_seasons.return_value = {
            "title": "Alien: Earth",
            "max_progress": 3,
            "image": "",
            "seasons": [{"season_number": 1}],
            "season/1": {
                "title": "Alien: Earth Season 1",
                "max_progress": 3,
                "episodes": [
                    {"episode_number": 1, "title": "Ep 1", "image": "", "release_datetime": None, "end_date": None},
                    {"episode_number": 2, "title": "Ep 2", "image": "", "release_datetime": None, "end_date": None},
                    {"episode_number": 3, "title": "Ep 3", "image": "", "release_datetime": None, "end_date": None},
                ],
            },
        }
        importer = stremio.StremioImporter(self.user, mode="new")
        importer.existing_media[MediaTypes.TV.value][Sources.TMDB.value][self.tv_item.media_id] = self.tv
        importer.existing_media[MediaTypes.SEASON.value][Sources.TMDB.value][(self.season_item.media_id, 1)] = self.season

        entry = {
            "_id": "series:1001",
            "name": "Alien: Earth",
            "state": {
                "video_id": "1001:1:1",
                "timeOffset": 0,
                "duration": 1000,
            },
        }
        video_ids = ["1001:1:1", "1001:1:2", "1001:1:3"]
        watched_videos = {"1001:1:1": {}}

        with patch.object(importer, "_watched_videos", return_value=watched_videos), \
             patch.object(importer, "_resolve_tmdb_id", return_value="1001"):
            importer._process_series(
                entry=entry,
                video_ids=video_ids,
            )

        self.season.refresh_from_db()
        self.assertEqual(self.season.status, Status.IN_PROGRESS.value)
    @patch("integrations.imports.helpers.decrypt_or_raise", return_value="dummy-key")
    @patch("app.models.providers.services.get_media_metadata")
    def test_stremio_sync_does_not_complete_show_with_unknown_status(
        self, mock_metadata, mock_decrypt
    ):
        """An unrecognized status is not the positive evidence the sync requires."""
        mock_metadata.return_value = {
            "title": "Alien: Earth",
            "details": {"status": "Terminada"},
        }
        self.tv.status = Status.PLANNING.value
        self.tv.save()
        StremioAccount.objects.create(user=self.user, auth_key="encrypted-key")

        importer = stremio.StremioImporter(self.user, mode="new")
        advanced = importer._advance_status_in_place(
            self.tv,
            Status.COMPLETED.value,
        )

        self.assertFalse(advanced)
        self.tv.refresh_from_db()
        self.assertEqual(self.tv.status, Status.PLANNING.value)
    @patch("integrations.imports.helpers.decrypt_or_raise", return_value="dummy-key")
    @patch("app.models.providers.services.get_media_metadata")
    def test_stremio_sync_completes_show_the_provider_calls_ended(
        self, mock_metadata, mock_decrypt
    ):
        """A positively ended show still completes, from Planning or In progress."""
        mock_metadata.return_value = {
            "title": "Alien: Earth",
            "details": {"status": "Ended"},
        }
        self.tv.status = Status.IN_PROGRESS.value
        self.tv.save()
        StremioAccount.objects.create(user=self.user, auth_key="encrypted-key")

        importer = stremio.StremioImporter(self.user, mode="new")
        advanced = importer._advance_status_in_place(
            self.tv,
            Status.COMPLETED.value,
        )

        self.assertTrue(advanced)
        self.tv.refresh_from_db()
        self.assertEqual(self.tv.status, Status.COMPLETED.value)
