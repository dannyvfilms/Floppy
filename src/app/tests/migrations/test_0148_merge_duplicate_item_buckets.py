import importlib

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import (
    TV,
    CollectionEntry,
    Episode,
    Item,
    MediaTypes,
    Season,
    Sources,
    Status,
)
from integrations.models import CollectionSourceState

migration = importlib.import_module(
    "app.migrations.0148_merge_duplicate_item_buckets",
)


class _RealAppsRegistry:
    """Minimal stand-in for the historical `apps` migrations pass in."""

    def get_model(self, app_label, model_name):
        del app_label
        return {
            "Item": Item,
            "TV": TV,
            "Season": Season,
            "Episode": Episode,
        }[model_name]


class MergeDuplicateItemBucketsMigration(TestCase):
    """Test the corrective data migration for split library buckets."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="test",
            password="12345",
        )
        show_item = Item.objects.create(
            media_id="95396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Severance",
        )
        season_item = Item.objects.create(
            media_id="95396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Severance Season 1",
            season_number=1,
        )
        self.tv = TV.objects.create(
            item=show_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        self.season = Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=self.tv,
            status=Status.IN_PROGRESS.value,
        )

    def _episode_item(self, episode_number, bucket):
        return Item.objects.create(
            media_id="95396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            library_media_type=bucket,
            title=f"Severance S1E{episode_number}",
            season_number=1,
            episode_number=episode_number,
        )

    def _run(self):
        migration.merge_duplicate_item_buckets(_RealAppsRegistry(), None)

    def test_keeps_the_row_carrying_watch_history(self):
        """The tracked row survives and the stray importer row is deleted."""
        tracked = self._episode_item(1, MediaTypes.TV.value)
        stray = self._episode_item(1, MediaTypes.EPISODE.value)
        Episode.objects.create(item=tracked, related_season=self.season)

        self._run()

        self.assertTrue(Item.objects.filter(pk=tracked.pk).exists())
        self.assertFalse(Item.objects.filter(pk=stray.pk).exists())

    def test_moves_collection_state_onto_the_survivor(self):
        """Ownership recorded against the stray row follows it to the keeper."""
        tracked = self._episode_item(1, MediaTypes.TV.value)
        stray = self._episode_item(1, MediaTypes.EPISODE.value)
        Episode.objects.create(item=tracked, related_season=self.season)
        entry = CollectionEntry.objects.create(
            user=self.user,
            item=stray,
            media_type="digital",
        )
        state = CollectionSourceState.objects.create(
            user=self.user,
            item=stray,
            source="sonarr",
        )

        self._run()

        entry.refresh_from_db()
        state.refresh_from_db()
        self.assertEqual(entry.item_id, tracked.pk)
        self.assertEqual(state.item_id, tracked.pk)

    def test_collapses_a_whole_season_to_one_bucket(self):
        """Episodes of one title share a bucket regardless of insertion order.

        Only the first episode carries history here, and the second episode's
        rows were inserted in the opposite order. Choosing per row would keep
        E1 on 'tv' and E2 on 'episode' - the very split being undone.
        """
        tracked = self._episode_item(1, MediaTypes.TV.value)
        self._episode_item(1, MediaTypes.EPISODE.value)
        Episode.objects.create(item=tracked, related_season=self.season)

        self._episode_item(2, MediaTypes.EPISODE.value)
        self._episode_item(2, MediaTypes.TV.value)

        self._run()

        survivors = Item.objects.filter(
            media_id="95396",
            media_type=MediaTypes.EPISODE.value,
        ).order_by("episode_number")
        self.assertEqual(
            [(item.episode_number, item.library_media_type) for item in survivors],
            [(1, MediaTypes.TV.value), (2, MediaTypes.TV.value)],
        )

    def test_leaves_single_rows_in_odd_buckets_alone(self):
        """A lone row in a non-canonical bucket is not a duplicate."""
        lone = self._episode_item(3, MediaTypes.TV.value)

        self._run()

        lone.refresh_from_db()
        self.assertEqual(lone.library_media_type, MediaTypes.TV.value)


class MergeDuplicateItemBucketsPreservesHistory(TestCase):
    """Merging must never cascade-delete a user's watch history.

    TV is unique on (user, item) and Season on (related_tv, item), and both
    cascade into Episode. Repointing a duplicate's TV/Season row onto the
    keeper therefore collides, and deleting the loser on that collision takes
    the episode history down with it.
    """

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="history-owner",
            password="12345",
        )
        self.media_id = "129412"

    def _item(self, media_type, bucket, season_number=None, episode_number=None):
        return Item.objects.create(
            media_id=self.media_id,
            source=Sources.TMDB.value,
            media_type=media_type,
            library_media_type=bucket,
            season_number=season_number,
            episode_number=episode_number,
            title="Game Changer",
        )

    def _tracked_show(self, show_bucket, season_bucket, episode_numbers):
        """Build one fully tracked show: TV -> Season -> Episodes."""
        tv_record = TV.objects.create(
            item=self._item(MediaTypes.TV.value, show_bucket),
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        season = Season.objects.create(
            item=self._item(MediaTypes.SEASON.value, season_bucket, season_number=1),
            user=self.user,
            related_tv=tv_record,
            status=Status.IN_PROGRESS.value,
        )
        for episode_number in episode_numbers:
            Episode.objects.create(
                item=self._item(
                    MediaTypes.EPISODE.value,
                    MediaTypes.EPISODE.value,
                    season_number=1,
                    episode_number=episode_number,
                ),
                related_season=season,
            )
        return tv_record

    def test_history_survives_merging_a_show_tracked_in_two_buckets(self):
        """No episode history may be lost when both duplicates are tracked."""
        self._tracked_show(MediaTypes.TV.value, MediaTypes.SEASON.value, [1, 2, 3])
        self._tracked_show(MediaTypes.SEASON.value, MediaTypes.TV.value, [4, 5])

        episodes_before = Episode.objects.filter(
            item__media_id=self.media_id,
        ).count()
        self.assertEqual(episodes_before, 5)

        migration.merge_duplicate_item_buckets(_RealAppsRegistry(), None)

        self.assertEqual(
            Episode.objects.filter(item__media_id=self.media_id).count(),
            episodes_before,
        )
        # The duplicates still collapse: one show, one season.
        self.assertEqual(
            Item.objects.filter(
                media_id=self.media_id,
                media_type=MediaTypes.TV.value,
            ).count(),
            1,
        )
        self.assertEqual(
            Item.objects.filter(
                media_id=self.media_id,
                media_type=MediaTypes.SEASON.value,
            ).count(),
            1,
        )
        # And the surviving season owns every episode.
        surviving_season = Season.objects.get(item__media_id=self.media_id)
        self.assertEqual(surviving_season.episodes.count(), 5)
