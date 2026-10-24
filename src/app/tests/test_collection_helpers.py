from django.contrib.auth import get_user_model
from django.test import TestCase

from app.helpers import (
    get_collection_completeness_map,
    get_collection_stats,
    get_season_collection_metadata,
    get_season_collection_stats,
    get_tv_show_collection_stats,
    get_user_collection,
    is_item_collected,
)
from app.models import CollectionEntry, Item, MediaTypes, Sources


class CollectionHelpersTest(TestCase):
    """Test collection helper functions."""

    def setUp(self):
        """Set up test data."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

        self.movie_item = Item.objects.create(
            media_id="movie1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Test Movie",
            image="http://example.com/movie.jpg",
        )

        self.tv_item = Item.objects.create(
            media_id="tv1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Test TV",
            image="http://example.com/tv.jpg",
        )

    def test_get_user_collection_all(self):
        """Test get_user_collection returns all entries."""
        CollectionEntry.objects.create(user=self.user, item=self.movie_item)
        CollectionEntry.objects.create(user=self.user, item=self.tv_item)

        collection = get_user_collection(self.user)
        self.assertEqual(collection.count(), 2)

    def test_get_user_collection_filtered(self):
        """Test get_user_collection with media_type filter."""
        CollectionEntry.objects.create(user=self.user, item=self.movie_item)
        CollectionEntry.objects.create(user=self.user, item=self.tv_item)

        collection = get_user_collection(self.user, media_type=MediaTypes.MOVIE.value)
        self.assertEqual(collection.count(), 1)
        self.assertEqual(collection.first().item.media_type, MediaTypes.MOVIE.value)

    def test_is_item_collected_found(self):
        """Test is_item_collected returns CollectionEntry when found."""
        entry = CollectionEntry.objects.create(user=self.user, item=self.movie_item)

        result = is_item_collected(self.user, self.movie_item)
        self.assertEqual(result, entry)

    def test_is_item_collected_returns_latest_when_multiple_exist(self):
        """Test is_item_collected returns most recent copy for an item."""
        first_entry = CollectionEntry.objects.create(
            user=self.user,
            item=self.movie_item,
            media_type="dvd",
        )
        latest_entry = CollectionEntry.objects.create(
            user=self.user,
            item=self.movie_item,
            media_type="bluray",
        )

        result = is_item_collected(self.user, self.movie_item)
        self.assertNotEqual(result, first_entry)
        self.assertEqual(result, latest_entry)

    def test_is_item_collected_not_found(self):
        """Test is_item_collected returns None when not found."""
        result = is_item_collected(self.user, self.movie_item)
        self.assertIsNone(result)

    def test_get_collection_stats(self):
        """Test get_collection_stats returns correct statistics."""
        CollectionEntry.objects.create(
            user=self.user,
            item=self.movie_item,
            media_type="bluray",
        )
        CollectionEntry.objects.create(
            user=self.user,
            item=self.tv_item,
            media_type="dvd",
        )

        stats = get_collection_stats(self.user)

        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["by_media_type"][MediaTypes.MOVIE.value], 1)
        self.assertEqual(stats["by_media_type"][MediaTypes.TV.value], 1)
        self.assertEqual(stats["by_format"]["bluray"], 1)
        self.assertEqual(stats["by_format"]["dvd"], 1)

    def test_get_tv_show_collection_stats_uses_show_level_entry_as_fallback(self):
        """Show-level collection entries should fill show totals when no granular rows exist."""
        Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title="Test TV Season 1",
            image="http://example.com/season1.jpg",
        )
        Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title="Test TV Episode 1",
            image="http://example.com/episode1.jpg",
        )
        Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=2,
            title="Test TV Episode 2",
            image="http://example.com/episode2.jpg",
        )
        CollectionEntry.objects.create(
            user=self.user, item=self.tv_item, media_type="digital"
        )

        stats = get_tv_show_collection_stats(self.user, self.tv_item)

        self.assertEqual(
            stats,
            {
                "collected_seasons": 1,
                "total_seasons": 1,
                "collected_episodes": 2,
                "total_episodes": 2,
            },
        )

    def test_get_tv_show_collection_stats_prefers_granular_entries_over_show_level_entry(
        self,
    ):
        """Granular collection rows should win over the show-level fallback."""
        Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title="Test TV Season 1",
            image="http://example.com/season1.jpg",
        )
        Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.SEASON.value,
            season_number=2,
            title="Test TV Season 2",
            image="http://example.com/season2.jpg",
        )
        first_episode = Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title="Test TV Episode 1",
            image="http://example.com/episode1.jpg",
        )
        Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=2,
            title="Test TV Episode 2",
            image="http://example.com/episode2.jpg",
        )
        Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=2,
            episode_number=1,
            title="Test TV Episode 3",
            image="http://example.com/episode3.jpg",
        )
        CollectionEntry.objects.create(
            user=self.user, item=self.tv_item, media_type="digital"
        )
        CollectionEntry.objects.create(
            user=self.user, item=first_episode, media_type="digital"
        )

        stats = get_tv_show_collection_stats(self.user, self.tv_item)

        self.assertEqual(
            stats,
            {
                "collected_seasons": 1,
                "total_seasons": 2,
                "collected_episodes": 1,
                "total_episodes": 3,
            },
        )

    def test_get_tv_show_collection_stats_excludes_specials_from_show_level_fallback(
        self,
    ):
        """Season 0 items should not affect fallback totals."""
        Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title="Test TV Season 1",
            image="http://example.com/season1.jpg",
        )
        Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.SEASON.value,
            season_number=0,
            title="Test TV Specials",
            image="http://example.com/specials.jpg",
        )
        Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title="Test TV Episode 1",
            image="http://example.com/episode1.jpg",
        )
        Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=2,
            title="Test TV Episode 2",
            image="http://example.com/episode2.jpg",
        )
        Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=0,
            episode_number=1,
            title="Test TV Special 1",
            image="http://example.com/special1.jpg",
        )
        CollectionEntry.objects.create(
            user=self.user, item=self.tv_item, media_type="digital"
        )

        stats = get_tv_show_collection_stats(self.user, self.tv_item)

        self.assertEqual(
            stats,
            {
                "collected_seasons": 1,
                "total_seasons": 1,
                "collected_episodes": 2,
                "total_episodes": 2,
            },
        )

    def test_get_tv_show_collection_stats_counts_season_entry_as_full_season_episode_rollup(
        self,
    ):
        """Collected seasons should contribute all of their episodes on the show page."""
        season_item = Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title="Test TV Season 1",
            image="http://example.com/season1.jpg",
        )
        Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.SEASON.value,
            season_number=2,
            title="Test TV Season 2",
            image="http://example.com/season2.jpg",
        )
        Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title="Test TV Episode 1",
            image="http://example.com/episode1.jpg",
        )
        Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=2,
            title="Test TV Episode 2",
            image="http://example.com/episode2.jpg",
        )
        Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=2,
            episode_number=1,
            title="Test TV Episode 3",
            image="http://example.com/episode3.jpg",
        )
        CollectionEntry.objects.create(
            user=self.user, item=season_item, media_type="digital"
        )

        stats = get_tv_show_collection_stats(self.user, self.tv_item)

        self.assertEqual(
            stats,
            {
                "collected_seasons": 1,
                "total_seasons": 2,
                "collected_episodes": 2,
                "total_episodes": 3,
            },
        )

    def test_get_tv_show_collection_stats_unions_season_and_episode_rollups(self):
        """Season-level rollups should merge with explicit episode rows without double counting."""
        season_one_item = Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title="Test TV Season 1",
            image="http://example.com/season1.jpg",
        )
        Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.SEASON.value,
            season_number=2,
            title="Test TV Season 2",
            image="http://example.com/season2.jpg",
        )
        season_one_episode_one = Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title="Test TV Episode 1",
            image="http://example.com/episode1.jpg",
        )
        Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=2,
            title="Test TV Episode 2",
            image="http://example.com/episode2.jpg",
        )
        season_two_episode_one = Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=2,
            episode_number=1,
            title="Test TV Episode 3",
            image="http://example.com/episode3.jpg",
        )
        CollectionEntry.objects.create(
            user=self.user, item=season_one_item, media_type="digital"
        )
        CollectionEntry.objects.create(
            user=self.user,
            item=season_one_episode_one,
            media_type="digital",
        )
        CollectionEntry.objects.create(
            user=self.user,
            item=season_two_episode_one,
            media_type="digital",
        )

        stats = get_tv_show_collection_stats(self.user, self.tv_item)

        self.assertEqual(
            stats,
            {
                "collected_seasons": 2,
                "total_seasons": 2,
                "collected_episodes": 3,
                "total_episodes": 3,
            },
        )

    def test_get_season_collection_stats_uses_season_level_entry_as_fallback(self):
        """Season entries should count as a fully collected season without episode rows."""
        season_item = Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title="Test TV Season 1",
            image="http://example.com/season1.jpg",
        )
        Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title="Test TV Episode 1",
            image="http://example.com/episode1.jpg",
        )
        Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=2,
            title="Test TV Episode 2",
            image="http://example.com/episode2.jpg",
        )
        CollectionEntry.objects.create(
            user=self.user, item=season_item, media_type="digital"
        )

        stats = get_season_collection_stats(self.user, season_item)

        self.assertEqual(
            stats,
            {
                "collected_episodes": 2,
                "total_episodes": 2,
            },
        )

    def test_get_season_collection_stats_counts_an_episode_once(self):
        """Two copies of one episode count as one collected episode."""
        season_item = Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title="Test TV Season 1",
            image="http://example.com/season1.jpg",
        )
        episode_one = Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title="Test TV Episode 1",
            image="http://example.com/episode1.jpg",
        )
        Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=2,
            title="Test TV Episode 2",
            image="http://example.com/episode2.jpg",
        )
        CollectionEntry.objects.create(
            user=self.user, item=episode_one, media_type="Blu-ray"
        )
        CollectionEntry.objects.create(
            user=self.user, item=episode_one, media_type="digital"
        )

        stats = get_season_collection_stats(self.user, season_item)

        self.assertEqual(
            stats,
            {
                "collected_episodes": 1,
                "total_episodes": 2,
            },
        )

    def test_get_season_collection_stats_prefers_episode_rows_over_season_level_entry(
        self,
    ):
        """Episode rows should remain the source of truth when they exist."""
        season_item = Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title="Test TV Season 1",
            image="http://example.com/season1.jpg",
        )
        first_episode = Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title="Test TV Episode 1",
            image="http://example.com/episode1.jpg",
        )
        Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=2,
            title="Test TV Episode 2",
            image="http://example.com/episode2.jpg",
        )
        CollectionEntry.objects.create(
            user=self.user, item=season_item, media_type="digital"
        )
        CollectionEntry.objects.create(
            user=self.user, item=first_episode, media_type="digital"
        )

        stats = get_season_collection_stats(self.user, season_item)

        self.assertEqual(
            stats,
            {
                "collected_episodes": 1,
                "total_episodes": 2,
            },
        )

    def test_get_season_collection_stats_ignores_show_fallback_after_granular_collection_exists(
        self,
    ):
        """Show-level fallback should stop once any granular collection rows exist for the show."""
        season_one_item = Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title="Test TV Season 1",
            image="http://example.com/season1.jpg",
        )
        season_two_item = Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.SEASON.value,
            season_number=2,
            title="Test TV Season 2",
            image="http://example.com/season2.jpg",
        )
        first_episode = Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title="Test TV Episode 1",
            image="http://example.com/episode1.jpg",
        )
        Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=2,
            episode_number=1,
            title="Test TV Episode 2",
            image="http://example.com/episode2.jpg",
        )
        CollectionEntry.objects.create(
            user=self.user, item=self.tv_item, media_type="digital"
        )
        CollectionEntry.objects.create(
            user=self.user, item=season_one_item, media_type="digital"
        )
        CollectionEntry.objects.create(
            user=self.user, item=first_episode, media_type="digital"
        )

        stats = get_season_collection_stats(self.user, season_two_item)

        self.assertEqual(
            stats,
            {
                "collected_episodes": 0,
                "total_episodes": 1,
            },
        )

    def test_get_season_collection_metadata_ignores_show_fallback_after_granular_collection_exists(
        self,
    ):
        """Season metadata should not borrow a show-level row once episode/season rows exist."""
        season_one_item = Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title="Test TV Season 1",
            image="http://example.com/season1.jpg",
        )
        season_two_item = Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.SEASON.value,
            season_number=2,
            title="Test TV Season 2",
            image="http://example.com/season2.jpg",
        )
        first_episode = Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title="Test TV Episode 1",
            image="http://example.com/episode1.jpg",
        )
        Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=2,
            episode_number=1,
            title="Test TV Episode 2",
            image="http://example.com/episode2.jpg",
        )
        CollectionEntry.objects.create(
            user=self.user,
            item=self.tv_item,
            media_type="digital",
            resolution="1080p",
        )
        CollectionEntry.objects.create(
            user=self.user, item=season_one_item, media_type="digital"
        )
        CollectionEntry.objects.create(
            user=self.user, item=first_episode, media_type="digital"
        )

        metadata = get_season_collection_metadata(self.user, season_two_item)

        self.assertIsNone(metadata)

    def test_get_season_collection_stats_survives_duplicate_tv_bucket_items(self):
        """A stray second TV-media-type Item in another bucket must not crash stats."""
        Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.SEASON.value,
            title="Test TV (stray season bucket)",
            image="http://example.com/tv-stray.jpg",
        )
        season_item = Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.SEASON.value,
            library_media_type=self.tv_item.library_media_type,
            season_number=1,
            title="Test TV Season 1",
            image="http://example.com/season1.jpg",
        )
        Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title="Test TV Episode 1",
            image="http://example.com/episode1.jpg",
        )
        CollectionEntry.objects.create(
            user=self.user, item=self.tv_item, media_type="digital"
        )

        stats = get_season_collection_stats(self.user, season_item)

        self.assertEqual(
            stats,
            {
                "collected_episodes": 1,
                "total_episodes": 1,
            },
        )

    def test_get_season_collection_metadata_survives_duplicate_tv_bucket_items(self):
        """A stray second TV-media-type Item in another bucket must not crash metadata."""
        Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.SEASON.value,
            title="Test TV (stray season bucket)",
            image="http://example.com/tv-stray.jpg",
        )
        season_item = Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.SEASON.value,
            library_media_type=self.tv_item.library_media_type,
            season_number=1,
            title="Test TV Season 1",
            image="http://example.com/season1.jpg",
        )
        Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title="Test TV Episode 1",
            image="http://example.com/episode1.jpg",
        )
        CollectionEntry.objects.create(
            user=self.user,
            item=self.tv_item,
            media_type="digital",
            resolution="1080p",
        )

        metadata = get_season_collection_metadata(self.user, season_item)

        self.assertIsNotNone(metadata)
        self.assertEqual(metadata["resolution"], "1080p")

    def test_get_collection_completeness_map_empty_input(self):
        """Passing no shows returns an empty map."""
        self.assertEqual(get_collection_completeness_map(self.user, []), {})

    def test_get_collection_completeness_map_partial_show(self):
        """A show with some but not all episodes collected is flagged partial."""
        season_item = Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title="Test TV Season 1",
            image="http://example.com/season1.jpg",
        )
        collected_episode = Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title="Test TV Episode 1",
            image="http://example.com/episode1.jpg",
        )
        Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=2,
            title="Test TV Episode 2",
            image="http://example.com/episode2.jpg",
        )
        CollectionEntry.objects.create(
            user=self.user, item=collected_episode, media_type="digital"
        )

        completeness = get_collection_completeness_map(self.user, [self.tv_item])

        self.assertEqual(
            completeness[self.tv_item.id],
            {"collected": 1, "total": 2, "is_partial": True},
        )
        self.assertEqual(
            completeness[season_item.id],
            {"collected": 1, "total": 2, "is_partial": True},
        )

    def test_get_collection_completeness_map_fully_collected_show(self):
        """A show with every episode collected is not flagged partial."""
        episode_one = Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title="Test TV Episode 1",
            image="http://example.com/episode1.jpg",
        )
        episode_two = Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=2,
            title="Test TV Episode 2",
            image="http://example.com/episode2.jpg",
        )
        CollectionEntry.objects.create(user=self.user, item=episode_one)
        CollectionEntry.objects.create(user=self.user, item=episode_two)

        completeness = get_collection_completeness_map(self.user, [self.tv_item])

        self.assertEqual(
            completeness[self.tv_item.id],
            {"collected": 2, "total": 2, "is_partial": False},
        )

    def test_get_collection_completeness_map_zero_collected_is_not_partial(self):
        """A show with no collected episodes is not flagged partial."""
        Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title="Test TV Episode 1",
            image="http://example.com/episode1.jpg",
        )

        completeness = get_collection_completeness_map(self.user, [self.tv_item])

        self.assertEqual(
            completeness[self.tv_item.id],
            {"collected": 0, "total": 1, "is_partial": False},
        )

    def test_get_collection_completeness_map_batches_multiple_shows(self):
        """Stats for several shows are computed with a fixed number of queries."""
        second_show = Item.objects.create(
            media_id="tv2",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Second TV Show",
            image="http://example.com/tv2.jpg",
        )
        first_show_episode_collected = Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title="Test TV Episode 1",
            image="http://example.com/episode1.jpg",
        )
        Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=2,
            title="Test TV Episode 2",
            image="http://example.com/episode2.jpg",
        )
        second_show_episode = Item.objects.create(
            media_id=second_show.media_id,
            source=second_show.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title="Second Show Episode 1",
            image="http://example.com/second-episode1.jpg",
        )
        CollectionEntry.objects.create(
            user=self.user, item=first_show_episode_collected
        )
        CollectionEntry.objects.create(user=self.user, item=second_show_episode)

        with self.assertNumQueries(4):
            completeness = get_collection_completeness_map(
                self.user,
                [self.tv_item, second_show],
            )

        self.assertEqual(
            completeness[self.tv_item.id],
            {"collected": 1, "total": 2, "is_partial": True},
        )
        self.assertEqual(
            completeness[second_show.id],
            {"collected": 1, "total": 1, "is_partial": False},
        )
