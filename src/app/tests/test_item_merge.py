"""Tests for the live Item merge service (#620)."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import (
    TV,
    CollectionEntry,
    Episode,
    Item,
    ItemTag,
    MediaTypes,
    PlaybackProgress,
    Season,
    Sources,
    Status,
    Tag,
)
from app.services import item_merge


class MergeItemTests(TestCase):
    """`merge_item` repoints every reference and deletes the loser."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="merge-user",
            password="pw12345",
        )

    def test_rejects_merging_an_item_into_itself(self):
        item = Item.objects.create(
            media_id="1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Solo",
            image="",
        )
        with self.assertRaises(ValueError):
            item_merge.merge_item(item, item)

    @patch("app.models.tv.TV._start_next_available_season")
    def test_tv_row_repoints_when_keeper_has_no_tv_row(self, _mock_start_next_season):
        loser = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Breaking Bad",
            image="",
        )
        keeper = Item.objects.create(
            media_id="81189",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            title="Breaking Bad",
            image="",
        )
        tv = TV.objects.create(item=loser, user=self.user, status=Status.IN_PROGRESS.value)

        item_merge.merge_item(loser, keeper)

        tv.refresh_from_db()
        self.assertEqual(tv.item_id, keeper.pk)
        self.assertFalse(Item.objects.filter(pk=loser.pk).exists())

    def test_tv_row_folds_onto_survivor_when_both_are_tracked(self):
        """Merging must not destroy the keeper's own TV row/history."""
        loser = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Breaking Bad",
            image="",
        )
        keeper = Item.objects.create(
            media_id="81189",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            title="Breaking Bad",
            image="",
        )
        loser_tv = TV.objects.create(
            item=loser,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        keeper_tv = TV.objects.create(
            item=keeper,
            user=self.user,
            status=Status.COMPLETED.value,
        )
        loser_season_item = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title="Breaking Bad",
            image="",
        )
        loser_season = Season.objects.create(
            item=loser_season_item,
            user=self.user,
            related_tv=loser_tv,
            status=Status.IN_PROGRESS.value,
        )

        item_merge.merge_item(loser, keeper)

        self.assertFalse(TV.objects.filter(pk=loser_tv.pk).exists())
        self.assertTrue(TV.objects.filter(pk=keeper_tv.pk).exists())
        loser_season.refresh_from_db()
        self.assertEqual(loser_season.related_tv_id, keeper_tv.pk)

    def test_season_row_folds_episodes_onto_survivor(self):
        loser_season_item = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title="S1",
            image="",
        )
        keeper_season_item = Item.objects.create(
            media_id="81189",
            source=Sources.TVDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title="S1",
            image="",
        )
        tv_item = Item.objects.create(
            media_id="81189",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            title="Breaking Bad",
            image="",
        )
        tv = TV.objects.create(item=tv_item, user=self.user, status=Status.IN_PROGRESS.value)
        loser_season = Season.objects.create(
            item=loser_season_item,
            user=self.user,
            related_tv=tv,
            status=Status.IN_PROGRESS.value,
        )
        keeper_season = Season.objects.create(
            item=keeper_season_item,
            user=self.user,
            related_tv=tv,
            status=Status.IN_PROGRESS.value,
        )
        loser_episode_item = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title="Pilot",
            image="",
        )
        episode = Episode.objects.create(
            item=loser_episode_item,
            related_season=loser_season,
            end_date=None,
        )

        item_merge.merge_item(loser_season_item, keeper_season_item)

        episode.refresh_from_db()
        self.assertEqual(episode.related_season_id, keeper_season.pk)
        self.assertFalse(Season.objects.filter(pk=loser_season.pk).exists())
        self.assertTrue(Season.objects.filter(pk=keeper_season.pk).exists())

    def test_owned_data_survives_and_collisions_are_dropped(self):
        """Tags/collection entries repoint; a colliding duplicate is dropped."""
        loser = Item.objects.create(
            media_id="1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Movie",
            image="",
        )
        keeper = Item.objects.create(
            media_id="2",
            source=Sources.TVDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Movie",
            image="",
        )
        tag = Tag.objects.create(user=self.user, name="Favorites")
        ItemTag.objects.create(item=loser, tag=tag)
        CollectionEntry.objects.create(user=self.user, item=loser)
        loser_progress = PlaybackProgress.objects.create(
            user=self.user,
            item=loser,
            position_seconds=120,
            duration_seconds=3600,
        )

        item_merge.merge_item(loser, keeper)

        self.assertTrue(ItemTag.objects.filter(item=keeper, tag=tag).exists())
        self.assertTrue(CollectionEntry.objects.filter(item=keeper, user=self.user).exists())
        loser_progress.refresh_from_db()
        self.assertEqual(loser_progress.item_id, keeper.pk)

    def test_playback_progress_collision_keeps_keepers_row(self):
        loser = Item.objects.create(
            media_id="1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Movie",
            image="",
        )
        keeper = Item.objects.create(
            media_id="2",
            source=Sources.TVDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Movie",
            image="",
        )
        PlaybackProgress.objects.create(
            user=self.user,
            item=loser,
            position_seconds=60,
            duration_seconds=3600,
        )
        keeper_progress = PlaybackProgress.objects.create(
            user=self.user,
            item=keeper,
            position_seconds=900,
            duration_seconds=3600,
        )

        item_merge.merge_item(loser, keeper)

        self.assertEqual(PlaybackProgress.objects.filter(item=keeper).count(), 1)
        keeper_progress.refresh_from_db()
        self.assertEqual(keeper_progress.position_seconds, 900)


class FindCrossProviderDuplicateTests(TestCase):
    """Verified-identity lookup only - never title matching."""

    def test_returns_none_for_non_tmdb_item(self):
        item = Item.objects.create(
            media_id="81189",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            title="Breaking Bad",
            image="",
        )
        self.assertIsNone(item_merge.find_cross_provider_duplicate(item))

    def test_returns_none_when_no_tvdb_counterpart_tracked(self):
        item = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Breaking Bad",
            image="",
            provider_external_ids={"tvdb_id": "81189"},
        )
        self.assertIsNone(item_merge.find_cross_provider_duplicate(item))

    def test_finds_verified_tvdb_counterpart_via_cached_id(self):
        item = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Breaking Bad",
            image="",
            provider_external_ids={"tvdb_id": "81189"},
        )
        counterpart = Item.objects.create(
            media_id="81189",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            title="Breaking Bad",
            image="",
        )
        self.assertEqual(
            item_merge.find_cross_provider_duplicate(item).pk,
            counterpart.pk,
        )

    def test_never_matches_purely_on_title(self):
        """A same-titled TVDB item with no verified id link must not match."""
        item = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Breaking Bad",
            image="",
        )
        Item.objects.create(
            media_id="99999",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            title="Breaking Bad",
            image="",
        )
        with patch(
            "app.services.item_merge.tmdb.resolve_tvdb_id_for_tmdb_show",
            return_value=None,
        ):
            self.assertIsNone(item_merge.find_cross_provider_duplicate(item))


class FindTvdbCounterpartTests(TestCase):
    """`find_tvdb_counterpart` is the pre-creation lookup used by importers."""

    def test_returns_none_for_non_tv_season_media_type(self):
        result = item_merge.find_tvdb_counterpart(
            "1",
            MediaTypes.MOVIE.value,
            library_media_type=MediaTypes.MOVIE.value,
        )
        self.assertIsNone(result)

    @patch("app.services.item_merge.tmdb.resolve_tvdb_id_for_tmdb_show")
    def test_finds_existing_tvdb_item(self, mock_resolve):
        mock_resolve.return_value = "81189"
        existing = Item.objects.create(
            media_id="81189",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            title="Breaking Bad",
            image="",
        )

        result = item_merge.find_tvdb_counterpart(
            "1396",
            MediaTypes.TV.value,
            library_media_type=MediaTypes.TV.value,
        )

        self.assertEqual(result.pk, existing.pk)

    @patch("app.services.item_merge.tmdb.resolve_tvdb_id_for_tmdb_show")
    def test_returns_none_when_unresolvable(self, mock_resolve):
        mock_resolve.return_value = None

        result = item_merge.find_tvdb_counterpart(
            "1396",
            MediaTypes.TV.value,
            library_media_type=MediaTypes.TV.value,
        )

        self.assertIsNone(result)
