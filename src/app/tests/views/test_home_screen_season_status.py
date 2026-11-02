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
from users.home_screen import build_home_page_groups
from users.models import HomeScreenRow, HomeScreenRowTypeChoices

User = get_user_model()

class HomeScreenSeasonStatusTests(TestCase):
    """Home screen keeps a caught-up season visible as in progress."""

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
    def test_home_screen_season_group_derivation_drops_caught_up_in_progress_season(
        self, mock_metadata
    ):
        """Home screen in-memory derivation keeps caught-up season as IN_PROGRESS."""
        mock_metadata.return_value = {"max_progress": 3}
        self.user.enabled_media_types = [MediaTypes.SEASON.value]
        self.user.save()

        HomeScreenRow.objects.create(
            user=self.user,
            media_type=MediaTypes.SEASON.value,
            position=0,
            enabled=True,
            row_type=HomeScreenRowTypeChoices.LIBRARY_QUERY,
            filters={"status": [Status.IN_PROGRESS.value]},
        )

        groups = build_home_page_groups(self.user, items_limit=10)
        items = [
            entry.item.title
            for group in groups
            for row in group["rows"]
            for entry in row["items"]
        ]
        self.assertIn("Alien: Earth Season 1", items)
