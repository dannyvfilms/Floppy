from datetime import UTC

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
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

User = get_user_model()

class RewatchPassWindowTests(TestCase):
    """Which plays count towards an open rewatch pass."""

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
    @override_settings(TIME_ZONE="Europe/Brussels", USE_TZ=True)
    def test_date_only_play_counts_for_pass_outside_utc(self):
        """A date-only play on the pass start day counts on a non-UTC deployment."""
        self.season.rewatch_started_at = timezone.localtime(timezone.now()).replace(
            hour=15,
            minute=0,
            second=0,
            microsecond=0,
        )
        self.season.save()

        local_midnight = timezone.localtime(self.season.rewatch_started_at).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        episode = self.season.episodes.first()
        episode.end_date = local_midnight
        episode.save()

        self.assertTrue(self.season.play_counts_for_pass(episode))
