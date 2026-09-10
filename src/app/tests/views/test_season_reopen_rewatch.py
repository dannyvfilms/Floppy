from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
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
from app.save_views import media_save

User = get_user_model()

class SeasonReopenRewatchTests(TestCase):
    """Reopening a completed season starts a rewatch pass."""

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
    @patch("app.models.providers.services.get_media_metadata")
    def test_media_save_reopening_completed_season_fails_to_start_rewatch_pass(
        self, mock_metadata
    ):
        """Setting COMPLETED season to IN_PROGRESS starts rewatch pass and stays IN_PROGRESS."""
        mock_metadata.return_value = {"max_progress": 3}
        self.season.status = Status.COMPLETED.value
        self.season.save()

        request = self.factory.post(
            "/save/",
            {
                "media_id": self.tv_item.media_id,
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.SEASON.value,
                "season_number": 1,
                "instance_id": str(self.season.id),
                "status": Status.IN_PROGRESS.value,
            },
        )
        request.user = self.user
        SessionMiddleware(lambda req: None).process_request(request)
        MessageMiddleware(lambda req: None).process_request(request)

        response = media_save(request)
        self.season.refresh_from_db()
        self.assertIsNotNone(self.season.rewatch_started_at)
        self.assertEqual(self.season.status, Status.IN_PROGRESS.value)
        self.assertEqual(
            self.season.derived_status_from_episode_progress(max_progress=3),
            Status.IN_PROGRESS.value,
        )
    @patch("app.models.providers.services.get_media_metadata")
    def test_media_save_reopening_second_rewatch_pass(self, mock_metadata):
        """Reopening a season that already had a previous rewatch pass starts a new pass."""
        mock_metadata.return_value = {"max_progress": 3}
        self.season.status = Status.COMPLETED.value
        self.season.rewatch_started_at = timezone.now() - timezone.timedelta(days=30)
        self.season.save()

        request = self.factory.post(
            "/save/",
            {
                "media_id": self.tv_item.media_id,
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.SEASON.value,
                "season_number": 1,
                "instance_id": str(self.season.id),
                "status": Status.IN_PROGRESS.value,
            },
        )
        request.user = self.user
        SessionMiddleware(lambda req: None).process_request(request)
        MessageMiddleware(lambda req: None).process_request(request)

        response = media_save(request)
        self.season.refresh_from_db()
        self.assertIsNotNone(self.season.rewatch_started_at)
        self.assertEqual(self.season.status, Status.IN_PROGRESS.value)
