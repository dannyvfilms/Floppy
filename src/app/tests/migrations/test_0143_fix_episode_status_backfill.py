import importlib

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from app.models import (
    TV,
    Episode,
    Item,
    MediaTypes,
    Season,
    Sources,
)

migration = importlib.import_module(
    "app.migrations.0143_fix_episode_status_backfill",
)


class _RealAppsRegistry:
    """Minimal stand-in for the historical `apps` migrations pass in."""

    def get_model(self, app_label, model_name):
        del app_label
        return {"Episode": Episode}[model_name]


class FixEpisodeStatusBackfillMigration(TestCase):
    """Test the issue #496 corrective data migration."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="test",
            password="12345",
        )
        item_tv = Item.objects.create(
            media_id="990496",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Friends",
        )
        self.tv = TV.objects.create(item=item_tv, user=self.user)
        item_season = Item.objects.create(
            media_id="990496",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Friends",
            season_number=1,
        )
        self.season = Season.objects.create(
            item=item_season,
            user=self.user,
            related_tv=self.tv,
        )

    def _episode(self, episode_number):
        item = Item.objects.create(
            media_id="990496",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Friends",
            season_number=1,
            episode_number=episode_number,
        )
        return Episode.objects.create(item=item, related_season=self.season)

    def test_flips_backfill_artifact_to_completed(self):
        episode = self._episode(1)
        Episode.objects.filter(pk=episode.pk).update(
            status="In progress",
            end_date=None,
            start_date=None,
            notes="",
        )

        migration.fix_incorrectly_flipped_episodes(_RealAppsRegistry(), None)

        episode.refresh_from_db()
        self.assertEqual(episode.status, "Completed")

    def test_leaves_real_in_progress_episode_alone(self):
        episode = self._episode(2)
        Episode.objects.filter(pk=episode.pk).update(
            status="In progress",
            end_date=None,
            start_date=timezone.now(),
            notes="",
        )

        migration.fix_incorrectly_flipped_episodes(_RealAppsRegistry(), None)

        episode.refresh_from_db()
        self.assertEqual(episode.status, "In progress")

    def test_leaves_dropped_episode_alone(self):
        episode = self._episode(3)
        Episode.objects.filter(pk=episode.pk).update(
            dropped=True,
            status="Dropped",
            end_date=None,
            start_date=None,
            notes="",
        )

        migration.fix_incorrectly_flipped_episodes(_RealAppsRegistry(), None)

        episode.refresh_from_db()
        self.assertEqual(episode.status, "Dropped")
