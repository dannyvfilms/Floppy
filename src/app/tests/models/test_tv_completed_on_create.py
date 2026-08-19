from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import TV, Item, MediaTypes, Season, Sources, Status

# Patch the provider lookup used by app.models.tv (imported there as `providers`).
METADATA_PATH = "app.providers.services.get_media_metadata"


class SeasonCompletedOnCreateTests(TestCase):
    """A season created directly as COMPLETED must still create its episodes."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="u", password="x")
        self.tv_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Show",
        )
        self.tv = TV.objects.create(
            item=self.tv_item,
            user=self.user,
            status=Status.PLANNING.value,
        )
        self.season_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Show",
            season_number=1,
        )

    @patch(METADATA_PATH)
    def test_season_created_completed_creates_episodes(self, mock_meta):
        mock_meta.return_value = {
            "episodes": [
                {"episode_number": 1},
                {"episode_number": 2},
                {"episode_number": 3},
            ],
            "image": "s.jpg",
            "max_progress": 3,
        }
        season = Season.objects.create(
            item=self.season_item,
            user=self.user,
            related_tv=self.tv,
            status=Status.COMPLETED.value,
        )
        self.assertEqual(season.episodes.count(), 3)

    @patch(METADATA_PATH)
    def test_season_created_planning_creates_no_episodes(self, mock_meta):
        # Guard against regressions: non-completed create must not fan out.
        mock_meta.return_value = {
            "episodes": [{"episode_number": 1}],
            "max_progress": 1,
        }
        season = Season.objects.create(
            item=self.season_item,
            user=self.user,
            related_tv=self.tv,
            status=Status.PLANNING.value,
        )
        self.assertEqual(season.episodes.count(), 0)

    @patch(METADATA_PATH)
    def test_season_transition_to_completed_still_creates_episodes(self, mock_meta):
        # The pre-existing transition path must keep working alongside the new
        # create-as-completed handling.
        mock_meta.return_value = {
            "episodes": [{"episode_number": 1}, {"episode_number": 2}],
            "max_progress": 2,
        }
        season = Season.objects.create(
            item=self.season_item,
            user=self.user,
            related_tv=self.tv,
            status=Status.PLANNING.value,
        )
        self.assertEqual(season.episodes.count(), 0)
        season.status = Status.COMPLETED.value
        season.save()
        self.assertEqual(season.episodes.count(), 2)


class TVCompletedOnCreateTests(TestCase):
    """A show created directly as COMPLETED must fan out to seasons/episodes."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="u2", password="x")
        self.tv_item = Item.objects.create(
            media_id="777",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Show",
        )

    @patch(METADATA_PATH)
    def test_tv_created_completed_creates_seasons_and_episodes(self, mock_meta):
        # One dict serves both the tv metadata and the per-season lookups.
        mock_meta.return_value = {
            "max_progress": 6,
            "related": {
                "seasons": [
                    {"season_number": 1, "image": "i1.jpg"},
                    {"season_number": 2, "image": "i2.jpg"},
                ]
            },
            "season/1": {
                "season_number": 1,
                "image": "i1.jpg",
                "episodes": [
                    {"episode_number": 1},
                    {"episode_number": 2},
                    {"episode_number": 3},
                ],
            },
            "season/2": {
                "season_number": 2,
                "image": "i2.jpg",
                "episodes": [
                    {"episode_number": 1},
                    {"episode_number": 2},
                    {"episode_number": 3},
                ],
            },
        }
        tv = TV.objects.create(
            item=self.tv_item,
            user=self.user,
            status=Status.COMPLETED.value,
        )
        self.assertEqual(tv.seasons.filter(status=Status.COMPLETED.value).count(), 2)
        for season in tv.seasons.all():
            self.assertTrue(season.episodes.exists())
