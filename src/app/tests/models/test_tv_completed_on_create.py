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

    def test_completion_reuses_catalogue_items_and_keeps_metadata_save_hooks(self):
        from django.db import connection
        from django.db.models.signals import post_save
        from django.test.utils import CaptureQueriesContext

        season = Season.objects.create(
            item=self.season_item, user=self.user, related_tv=self.tv,
            status=Status.PLANNING.value,
        )
        metadata = {"episodes": [{"episode_number": number, "title": f"Episode {number}", "runtime": 45} for number in range(1, 11)]}
        providers = {"US": [{"provider_id": 1, "logo_path": "x" * 1000}]}
        items = Item.objects.bulk_create([
            Item(
                media_id="123", source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value, library_media_type=MediaTypes.EPISODE.value, season_number=1,
                episode_number=episode["episode_number"], runtime_minutes=45,
                watch_providers=providers,
                **Item.title_fields_from_episode_metadata(episode, fallback_title="Show"),
            ) for episode in metadata["episodes"]
        ])
        Item.objects.filter(pk=items[0].pk).update(runtime_minutes=None)
        saved_ids = []

        def recorded(sender, instance, **kwargs):
            saved_ids.append(instance.pk)

        post_save.connect(recorded, sender=Item, weak=False)
        try:
            with CaptureQueriesContext(connection) as captured:
                episodes = season.get_remaining_eps(metadata, end_date=None)
        finally:
            post_save.disconnect(recorded, sender=Item)
        self.assertEqual({episode.item_id for episode in episodes}, {item.pk for item in items})
        self.assertEqual(saved_ids, [items[0].pk])
        items[0].refresh_from_db()
        self.assertEqual(items[0].runtime_minutes, 45)
        self.assertEqual(len(episodes), 10)
        self.assertTrue(all("watch_providers" in episode.item.get_deferred_fields() for episode in episodes))
        self.assertEqual(items[0].watch_providers, providers)
        self.assertFalse(any('"watch_providers"' in query["sql"] for query in captured))
        individual_lookups = [query["sql"] for query in captured if '"app_item"."episode_number" =' in query["sql"]]
        self.assertEqual(individual_lookups, [])

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
