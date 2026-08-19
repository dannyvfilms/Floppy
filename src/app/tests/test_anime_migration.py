from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from app import history_cache
from app.models import (
    TV,
    Anime,
    BasicMedia,
    Episode,
    Item,
    ItemProviderLink,
    MediaTypes,
    MetadataProviderPreference,
    Season,
    Sources,
    Status,
)
from app.services import anime_migration
from app.services.tracking_hydration import HydratedItemResult


class AnimeMigrationTests(TestCase):
    """Tests for explicit flat-anime to grouped-series migration."""

    def setUp(self):
        self.metadata_patcher = patch(
            "app.models.providers.services.get_media_metadata",
            return_value={
                "max_progress": 12,
                "details": {"episodes": 12},
            },
        )
        self.metadata_patcher.start()
        self.addCleanup(self.metadata_patcher.stop)
        self.user = get_user_model().objects.create_user(
            username="anime-migrate",
            password="pw12345",
        )
        self.flat_item = Item.objects.create(
            media_id="52991",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Frieren",
            image="https://example.com/frieren.jpg",
        )
        self.flat_entry = Anime.objects.create(
            item=self.flat_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
            progress=3,
            score=9,
            notes="Great adaptation",
            start_date=timezone.now() - timedelta(days=3),
            end_date=timezone.now(),
        )
        self.grouped_item = Item.objects.create(
            media_id="9350138",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.ANIME.value,
            title="Frieren: Beyond Journey's End",
            image="https://example.com/grouped.jpg",
        )

    @patch("app.services.anime_migration.anime_mapping.find_entries_for_mal_id")
    @patch("app.services.anime_migration.anime_mapping.resolve_provider_series_id")
    @patch("app.services.anime_migration.services.get_media_metadata")
    @patch("app.services.anime_migration.ensure_item_metadata")
    def test_migrate_flat_anime_to_grouped_series(
        self,
        mock_ensure_item_metadata,
        mock_get_media_metadata,
        mock_resolve_provider_series_id,
        mock_find_entries_for_mal_id,
    ):
        """Migration should create grouped TV/season/episode records and archive flat rows."""
        mock_resolve_provider_series_id.return_value = "9350138"
        mock_find_entries_for_mal_id.return_value = [
            {
                "mal_id": "52991",
                "tvdb_id": "9350138",
                "tvdb_season": 1,
                "tvdb_epoffset": 0,
            },
        ]
        mock_ensure_item_metadata.return_value = HydratedItemResult(
            item=self.grouped_item,
            metadata={
                "media_id": "9350138",
                "source": Sources.TVDB.value,
                "media_type": MediaTypes.ANIME.value,
                "identity_media_type": MediaTypes.TV.value,
                "library_media_type": MediaTypes.ANIME.value,
                "title": "Frieren: Beyond Journey's End",
                "image": "https://example.com/grouped.jpg",
                "related": {"seasons": [{"season_number": 1}]},
            },
            created=False,
        )
        mock_get_media_metadata.return_value = {
            "related": {"seasons": [{"season_number": 1}]},
            "season/1": {
                "title": "Frieren: Beyond Journey's End",
                "image": "https://example.com/season1.jpg",
                "season_number": 1,
                "episodes": [
                    {"episode_number": 1, "air_date": "2023-09-29", "runtime": 24},
                    {"episode_number": 2, "air_date": "2023-10-06", "runtime": 24},
                    {"episode_number": 3, "air_date": "2023-10-13", "runtime": 24},
                ],
            },
        }

        result = anime_migration.migrate_flat_anime_to_grouped(
            self.user,
            self.flat_item,
            Sources.TVDB.value,
        )

        grouped_tv = TV.objects.get(item=self.grouped_item, user=self.user)
        grouped_season = Season.objects.get(
            item__media_id="9350138",
            item__source=Sources.TVDB.value,
            item__season_number=1,
            user=self.user,
        )
        watched_episodes = list(
            Episode.objects.filter(related_season=grouped_season).order_by(
                "item__episode_number"
            )
        )

        self.assertEqual(result.grouped_tv, grouped_tv)
        self.assertEqual(len(watched_episodes), 3)
        self.assertEqual(grouped_tv.status, Status.IN_PROGRESS.value)
        self.assertEqual(grouped_tv.score, 9)
        self.assertEqual(grouped_tv.notes, "Great adaptation")
        self.assertEqual(
            watched_episodes[0].item.library_media_type, MediaTypes.ANIME.value
        )
        self.assertEqual(watched_episodes[0].end_date, self.flat_entry.start_date)
        self.assertLessEqual(
            abs(watched_episodes[-1].end_date - self.flat_entry.end_date),
            timedelta(milliseconds=1),
        )
        self.assertFalse(
            Anime.objects.filter(user=self.user, item=self.flat_item).exists(),
        )
        self.flat_entry.refresh_from_db()
        self.assertEqual(self.flat_entry.migrated_to_item, self.grouped_item)
        self.assertTrue(
            MetadataProviderPreference.objects.filter(
                user=self.user,
                item=self.grouped_item,
                provider=Sources.TVDB.value,
            ).exists(),
        )
        self.assertTrue(
            ItemProviderLink.objects.filter(
                item=self.flat_item,
                provider=Sources.TVDB.value,
                provider_media_id="9350138",
                provider_media_type=MediaTypes.TV.value,
                season_number=1,
                episode_offset=0,
            ).exists(),
        )

    @patch("app.services.anime_migration.anime_mapping.find_entries_for_mal_id")
    @patch("app.services.anime_migration.anime_mapping.resolve_provider_series_id")
    @patch("app.services.anime_migration.services.get_media_metadata")
    @patch("app.services.anime_migration.ensure_item_metadata")
    def test_grouped_anime_progress_appears_in_warm_history_immediately(
        self,
        mock_ensure_item_metadata,
        mock_get_media_metadata,
        mock_resolve_provider_series_id,
        mock_find_entries_for_mal_id,
    ):
        """A grouped anime progress update should appear in warm History immediately."""
        cache.clear()
        self.addCleanup(cache.clear)
        self.enterContext(
            patch(
                "app.history_cache_lifecycle.schedule_history_refresh",
                return_value=True,
            ),
        )
        self.enterContext(
            patch("app.history_cache.schedule_history_refresh", return_value=True),
        )
        self.enterContext(
            patch("app.signals.statistics_cache.schedule_all_ranges_refresh"),
        )
        Anime.all_objects.filter(id=self.flat_entry.id).update(progress=1)
        self.flat_entry.refresh_from_db()
        original_data = {
            field: getattr(self.flat_entry, field)
            for field in (
                "item_id",
                "user_id",
                "progressed_at",
                "import_run_id",
                "progress",
                "status",
                "score",
                "notes",
                "start_date",
                "end_date",
            )
        }
        episodes = [
            {"episode_number": 1, "air_date": "2023-09-29", "runtime": 24},
            {"episode_number": 2, "air_date": "2023-10-06", "runtime": 24},
            {"episode_number": 3, "air_date": "2023-10-13", "runtime": 24},
        ]
        mock_resolve_provider_series_id.return_value = "9350138"
        mock_find_entries_for_mal_id.return_value = [
            {
                "mal_id": "52991",
                "tvdb_id": "9350138",
                "tvdb_season": 1,
                "tvdb_epoffset": 0,
            },
        ]
        mock_ensure_item_metadata.return_value = HydratedItemResult(
            item=self.grouped_item,
            metadata={
                "media_id": "9350138",
                "source": Sources.TVDB.value,
                "media_type": MediaTypes.ANIME.value,
                "identity_media_type": MediaTypes.TV.value,
                "library_media_type": MediaTypes.ANIME.value,
                "title": "Frieren: Beyond Journey's End",
                "image": "https://example.com/grouped.jpg",
                "related": {"seasons": [{"season_number": 1}]},
            },
            created=False,
        )

        def media_metadata(media_type, *_args, **_kwargs):
            if media_type == MediaTypes.SEASON.value:
                return {
                    "season_number": 1,
                    "episodes": episodes,
                    "max_progress": 3,
                }
            if media_type == MediaTypes.TV.value:
                return {
                    "max_progress": 3,
                    "related": {"seasons": [{"season_number": 1}]},
                }
            if media_type == "tv_with_seasons":
                return {
                    "related": {"seasons": [{"season_number": 1}]},
                    "season/1": {
                        "title": "Frieren: Beyond Journey's End",
                        "image": "https://example.com/season1.jpg",
                        "season_number": 1,
                        "episodes": episodes,
                    },
                }
            raise AssertionError(f"Unexpected media type: {media_type}")

        mock_get_media_metadata.side_effect = media_metadata
        result = anime_migration.migrate_flat_anime_to_grouped(
            self.user,
            self.flat_item,
            Sources.TVDB.value,
        )

        grouped_tv = result.grouped_tv
        grouped_season = Season.objects.get(related_tv=grouped_tv)
        archived_anime = Anime.all_objects.get(id=self.flat_entry.id)
        self.assertFalse(Anime.objects.filter(id=archived_anime.id).exists())
        self.assertEqual(
            {field: getattr(archived_anime, field) for field in original_data},
            original_data,
        )
        self.assertEqual(archived_anime.migrated_to_item, self.grouped_item)
        self.assertIsNotNone(archived_anime.migrated_at)
        self.assertEqual(grouped_tv.item.source, Sources.TVDB.value)
        self.assertEqual(grouped_tv.item.media_type, MediaTypes.TV.value)
        self.assertEqual(
            grouped_tv.item.library_media_type,
            MediaTypes.ANIME.value,
        )
        self.assertEqual(
            BasicMedia.objects.get_media(
                self.user,
                MediaTypes.ANIME.value,
                grouped_tv.id,
            ),
            grouped_tv,
        )
        self.assertEqual(
            BasicMedia.objects.get_media_prefetch(
                self.user,
                MediaTypes.ANIME.value,
                grouped_tv.id,
            ),
            grouped_tv,
        )
        self.assertTrue(
            ItemProviderLink.objects.filter(
                item=self.flat_item,
                provider=Sources.TVDB.value,
                provider_media_id="9350138",
                provider_media_type=MediaTypes.TV.value,
                season_number=1,
                episode_offset=0,
            ).exists(),
        )

        self.client.force_login(self.user)
        logging_style = "repeats"
        history_cache.refresh_history_cache(
            self.user.id,
            logging_style=logging_style,
        )
        progress_url = reverse(
            "progress_edit",
            kwargs={
                "media_type": MediaTypes.TV.value,
                "instance_id": grouped_tv.id,
            },
        )

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(progress_url, {"operation": "increase"})

        self.assertEqual(response.status_code, 200)
        watched_episodes = Episode.objects.filter(
            related_season=grouped_season,
        ).order_by("item__episode_number")
        self.assertEqual(watched_episodes.count(), 2)
        episode_two = watched_episodes.get(item__episode_number=2)
        episode_one = watched_episodes.get(item__episode_number=1)
        migrated_episode_one_end_date = episode_one.end_date
        self.assertEqual(migrated_episode_one_end_date, original_data["end_date"])
        activity_date = timezone.localtime(episode_two.end_date)
        day_key = history_cache.history_day_key(activity_date)
        direct_day = history_cache.build_history_day(
            self.user,
            day_key,
            logging_style_override=logging_style,
        )
        self.assertIn(
            episode_two.id,
            [entry["instance_id"] for entry in direct_day["entries"]],
        )

        month_days, _ = history_cache.get_month_history(
            self.user,
            activity_date.year,
            activity_date.month,
            logging_style_override=logging_style,
        )
        warm_episode_ids = {
            entry["instance_id"]
            for day in month_days
            for entry in day["entries"]
            if entry["media_type"] == MediaTypes.EPISODE.value
        }
        self.assertIn(
            episode_two.id,
            warm_episode_ids,
            "Warm History should include the episode added by progress_edit.",
        )

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(progress_url, {"operation": "increase"})
        self.assertEqual(response.status_code, 200)
        watched_episodes = Episode.objects.filter(
            related_season=grouped_season,
        ).order_by("item__episode_number")
        self.assertEqual(watched_episodes.count(), 3)
        self.assertEqual(
            list(watched_episodes.values_list("item__episode_number", flat=True)),
            [1, 2, 3],
        )
        episode_three = watched_episodes.get(item__episode_number=3)
        final_activity_date = timezone.localtime(episode_three.end_date)
        final_month_days, _ = history_cache.get_month_history(
            self.user,
            final_activity_date.year,
            final_activity_date.month,
            logging_style_override=logging_style,
        )
        final_warm_episode_ids = {
            entry["instance_id"]
            for day in final_month_days
            for entry in day["entries"]
            if entry["media_type"] == MediaTypes.EPISODE.value
        }
        self.assertEqual(
            final_warm_episode_ids - warm_episode_ids,
            {episode_three.id},
            "Final progress should add only episode 3 to warm History.",
        )
        episode_one.refresh_from_db()
        self.assertEqual(episode_one.end_date, migrated_episode_one_end_date)
        grouped_season.refresh_from_db()
        grouped_tv.refresh_from_db()
        self.assertEqual(grouped_season.status, Status.COMPLETED.value)
        self.assertEqual(grouped_tv.status, Status.COMPLETED.value)

    @patch("app.services.anime_migration.anime_mapping.find_entries_for_mal_id")
    @patch("app.services.anime_migration.anime_mapping.resolve_provider_series_id")
    @patch("app.services.anime_migration.services.get_media_metadata")
    @patch("app.services.anime_migration.ensure_item_metadata")
    def test_migration_blocks_when_progress_exceeds_mapped_season(
        self,
        mock_ensure_item_metadata,
        mock_get_media_metadata,
        mock_resolve_provider_series_id,
        mock_find_entries_for_mal_id,
    ):
        """Migration should stop instead of truncating episode progress."""
        Anime.all_objects.filter(id=self.flat_entry.id).update(progress=4)
        self.flat_entry.refresh_from_db()
        mock_resolve_provider_series_id.return_value = "9350138"
        mock_find_entries_for_mal_id.return_value = [
            {
                "mal_id": "52991",
                "tvdb_id": "9350138",
                "tvdb_season": 1,
                "tvdb_epoffset": 0,
            },
        ]
        mock_ensure_item_metadata.return_value = HydratedItemResult(
            item=self.grouped_item,
            metadata={
                "media_id": "9350138",
                "source": Sources.TVDB.value,
                "media_type": MediaTypes.ANIME.value,
                "identity_media_type": MediaTypes.TV.value,
                "library_media_type": MediaTypes.ANIME.value,
                "title": "Frieren: Beyond Journey's End",
                "image": "https://example.com/grouped.jpg",
                "related": {"seasons": [{"season_number": 1}]},
            },
            created=False,
        )
        mock_get_media_metadata.return_value = {
            "related": {"seasons": [{"season_number": 1}]},
            "season/1": {
                "title": "Frieren: Beyond Journey's End",
                "image": "https://example.com/season1.jpg",
                "season_number": 1,
                "episodes": [
                    {"episode_number": 1, "air_date": "2023-09-29", "runtime": 24},
                    {"episode_number": 2, "air_date": "2023-10-06", "runtime": 24},
                    {"episode_number": 3, "air_date": "2023-10-13", "runtime": 24},
                ],
            },
        }

        with self.assertRaises(anime_migration.AnimeMigrationError):
            anime_migration.migrate_flat_anime_to_grouped(
                self.user,
                self.flat_item,
                Sources.TVDB.value,
            )

        self.flat_entry.refresh_from_db()
        self.assertIsNone(self.flat_entry.migrated_to_item)
        self.assertEqual(Episode.objects.count(), 0)
