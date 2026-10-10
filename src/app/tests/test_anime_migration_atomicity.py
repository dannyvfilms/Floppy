from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import close_old_connections, connection
from django.db.utils import OperationalError
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from app import cache_utils
from app.models import (
    TV,
    Anime,
    Episode,
    Item,
    ItemPersonCredit,
    ItemProviderLink,
    ItemStudioCredit,
    MediaTypes,
    MetadataProviderPreference,
    Season,
    Sources,
    Status,
)
from app.services import anime_migration
from lists.models import CustomList


class AnimeMigrationAtomicityTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = get_user_model().objects.create_user(username="atomic-migrate")
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
            progress=2,
            score=9,
            notes="Great adaptation",
            start_date=timezone.now(),
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
        self.mapping = {
            "mal_id": "52991",
            "tvdb_id": "9350138",
            "tvdb_season": 1,
            "tvdb_epoffset": 0,
        }
        self.provider_patches = (
            patch(
                "app.services.anime_migration.anime_mapping.resolve_provider_series_id",
                return_value="9350138",
            ),
            patch(
                "app.services.anime_migration.anime_mapping.find_entries_for_mal_id",
                return_value=[self.mapping],
            ),
            patch(
                "app.services.anime_migration.services.get_media_metadata",
                side_effect=self._metadata,
            ),
        )
        for provider_patch in self.provider_patches:
            provider_patch.start()
            self.addCleanup(provider_patch.stop)
        for task_patch in (
            patch(
                "app.signals.discover_tab_cache.schedule_tab_refresh",
                return_value=True,
            ),
            patch(
                "app.history_cache_lifecycle.schedule_history_refresh",
                return_value=True,
            ),
            patch("app.signals.statistics_cache.schedule_all_ranges_refresh"),
        ):
            task_patch.start()
            self.addCleanup(task_patch.stop)

    def _metadata(self, media_type, *_args, **_kwargs):
        episodes = [
            {"episode_number": 1, "air_date": "2023-09-29", "runtime": 24},
            {"episode_number": 2, "air_date": "2023-10-06", "runtime": 24},
            {"episode_number": 3, "air_date": "2023-10-13", "runtime": 24},
        ]
        if media_type == MediaTypes.ANIME.value:
            return {
                "title": "Frieren: Beyond Journey's End",
                "image": "https://example.com/grouped.jpg",
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
        raise AssertionError(f"Unexpected provider request: {media_type}")

    def _preflight(self):
        return anime_migration.preflight_flat_anime_to_grouped(
            self.user,
            self.flat_item,
            Sources.TVDB.value,
        )

    def _table_snapshot(self):
        return {
            "items": list(Item.objects.order_by("id").values()),
            "tv": list(TV.objects.order_by("id").values()),
            "seasons": list(Season.objects.order_by("id").values()),
            "episodes": list(Episode.objects.order_by("id").values()),
            "links": list(ItemProviderLink.objects.order_by("id").values()),
            "preferences": list(
                MetadataProviderPreference.objects.order_by("id").values()
            ),
            "anime": list(Anime.all_objects.order_by("id").values()),
            "historical_tv": list(TV.history.order_by("history_id").values()),
            "historical_seasons": list(
                Season.history.order_by("history_id").values()
            ),
            "historical_episodes": list(
                Episode.history.order_by("history_id").values()
            ),
        }

    def test_preflight_is_immutable_and_does_not_write_tables(self):
        before = self._table_snapshot()

        preflight = self._preflight()

        self.assertEqual(preflight.state, anime_migration.AnimeMigrationState.READY)
        self.assertEqual(self._table_snapshot(), before)
        with self.assertRaises(TypeError):
            preflight.series_metadata["title"] = "Changed"
        with self.assertRaises(TypeError):
            preflight.entries[0].season_metadata["episodes"] = []

    def test_persistence_makes_no_provider_or_episode_save_call(self):
        preflight = self._preflight()

        with (
            patch(
                "app.services.anime_migration.services.get_media_metadata",
                side_effect=AssertionError("provider call inside persistence"),
            ),
            patch(
                "app.services.anime_migration.providers.tmdb.get_tvdb_episode_image_map",
                side_effect=AssertionError("provider call inside persistence"),
            ),
            patch(
                "app.services.anime_migration.anime_mapping.resolve_provider_series_id",
                side_effect=AssertionError("mapping call inside persistence"),
            ),
            patch(
                "app.services.anime_migration.anime_mapping.find_entries_for_mal_id",
                side_effect=AssertionError("mapping call inside persistence"),
            ),
            patch.object(
                Episode,
                "save",
                side_effect=AssertionError("Episode.save inside persistence"),
            ),
            patch.object(
                anime_migration.signals,
                "_invalidate_episode_history_changes",
            ) as invalidate,
        ):
            result = anime_migration.persist_flat_anime_migration(preflight)

        self.assertEqual(result.grouped_tv.item_id, self.grouped_item.id)
        self.assertEqual(Episode.objects.count(), 2)
        invalidate.assert_called_once()
        self.assertEqual(set(invalidate.call_args.args[0]), {self.user.id})

    @override_settings(TESTING=False)
    def test_item_backfills_are_not_enqueued_inside_transaction(self):
        self.grouped_item.delete()
        preflight = self._preflight()

        with (
            patch("app.tasks.enqueue_runtime_backfill_items") as runtime_backfill,
            patch("app.tasks.enqueue_episode_runtime_backfill") as episode_backfill,
            patch("app.tasks.enqueue_genre_backfill_items") as genre_backfill,
            patch("app.tasks.enqueue_credits_backfill_items") as credits_backfill,
        ):
            anime_migration.persist_flat_anime_migration(preflight)

        runtime_backfill.assert_not_called()
        episode_backfill.assert_not_called()
        genre_backfill.assert_not_called()
        credits_backfill.assert_not_called()

    def test_absent_target_preserves_metadata_external_ids_and_credits(self):
        self.grouped_item.delete()
        mapping = {
            **self.mapping,
            "tmdb_show_id": "209867",
            "tmdb_season": 1,
            "tmdb_epoffset": 0,
        }
        rich_metadata = {
            "title": "Frieren: Beyond Journey's End",
            "image": "https://example.com/grouped.jpg",
            "genres": ["Animation", "Drama"],
            "details": {
                "runtime": "24 min",
                "country": "JP",
                "languages": ["ja"],
                "studios": ["Madhouse"],
            },
            "provider_external_ids": {
                "tmdb_id": "209867",
                "tvdb_id": "9350138",
            },
            "cast": [
                {
                    "id": "1",
                    "name": "Voice Actor",
                    "character": "Frieren",
                }
            ],
            "crew": [],
            "studios_full": [{"id": "2", "name": "Madhouse"}],
        }

        def metadata(media_type, *_args, **_kwargs):
            if media_type == MediaTypes.ANIME.value:
                return rich_metadata
            return self._metadata(media_type)

        with (
            patch(
                "app.services.anime_migration.anime_mapping.resolve_provider_series_id",
                return_value="209867",
            ),
            patch(
                "app.services.anime_migration.anime_mapping.find_entries_for_mal_id",
                return_value=[mapping],
            ),
            patch(
                "app.services.anime_migration.services.get_media_metadata",
                side_effect=metadata,
            ),
            patch(
                "app.services.anime_migration.providers.tmdb.get_tvdb_episode_image_map",
                return_value={},
            ),
        ):
            preflight = anime_migration.preflight_flat_anime_to_grouped(
                self.user,
                self.flat_item,
                Sources.TMDB.value,
            )

        with (
            patch(
                "app.services.anime_migration.services.get_media_metadata",
                side_effect=AssertionError("provider call inside persistence"),
            ),
            patch(
                "app.services.anime_migration.providers.tmdb.get_tvdb_episode_image_map",
                side_effect=AssertionError("provider call inside persistence"),
            ),
        ):
            result = anime_migration.persist_flat_anime_migration(preflight)

        grouped_item = result.grouped_tv.item
        self.assertEqual(grouped_item.runtime_minutes, 24)
        self.assertEqual(grouped_item.genres, ["Animation", "Drama"])
        self.assertEqual(grouped_item.country, "JP")
        self.assertEqual(grouped_item.languages, ["ja"])
        self.assertEqual(grouped_item.studios, ["Madhouse"])
        self.assertEqual(
            grouped_item.provider_external_ids,
            {"tmdb_id": "209867", "tvdb_id": "9350138"},
        )
        self.assertTrue(
            ItemProviderLink.objects.filter(
                item=grouped_item,
                provider=Sources.TVDB.value,
                provider_media_id="9350138",
            ).exists()
        )
        self.assertEqual(ItemPersonCredit.objects.filter(item=grouped_item).count(), 1)
        self.assertEqual(ItemStudioCredit.objects.filter(item=grouped_item).count(), 1)

    def test_late_failure_rolls_back_every_migration_write(self):
        preflight = self._preflight()
        before = self._table_snapshot()

        with (
            patch.object(
                MetadataProviderPreference.objects,
                "update_or_create",
                side_effect=RuntimeError("late failure"),
            ),
            patch.object(
                anime_migration,
                "_reconcile_committed_migration",
            ) as reconcile,
            self.assertRaisesRegex(RuntimeError, "late failure"),
        ):
            anime_migration.persist_flat_anime_migration(preflight)

        self.assertEqual(self._table_snapshot(), before)
        reconcile.assert_not_called()

    def test_retry_after_lock_uses_fresh_transaction(self):
        preflight = self._preflight()
        persist_once = anime_migration._persist_preflight_once
        attempts = 0

        def locked_once(payload):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OperationalError("database is locked")
            return persist_once(payload)

        with patch.object(
            anime_migration,
            "_persist_preflight_once",
            side_effect=locked_once,
        ):
            result = anime_migration.persist_flat_anime_migration(preflight)

        self.assertEqual(attempts, 2)
        self.assertEqual(result.grouped_tv.item_id, self.grouped_item.id)
        self.assertEqual(Episode.objects.count(), 2)

    def test_completed_retry_is_a_noop(self):
        first = anime_migration.migrate_flat_anime_to_grouped(
            self.user,
            self.flat_item,
            Sources.TVDB.value,
        )
        first_episode_ids = list(Episode.objects.values_list("id", flat=True))

        second = anime_migration.migrate_flat_anime_to_grouped(
            self.user,
            self.flat_item,
            Sources.TVDB.value,
        )

        self.assertEqual(second.grouped_tv.id, first.grouped_tv.id)
        self.assertEqual(
            list(Episode.objects.values_list("id", flat=True)), first_episode_ids
        )
        self.assertEqual(
            anime_migration.preflight_flat_anime_to_grouped(
                self.user,
                self.flat_item,
                Sources.TVDB.value,
            ).state,
            anime_migration.AnimeMigrationState.COMPLETE,
        )

    def test_cross_provider_retry_returns_existing_completed_target(self):
        mapping = {
            **self.mapping,
            "tmdb_show_id": "209867",
            "tmdb_season": 1,
            "tmdb_epoffset": 0,
        }

        def resolve(_mal_id, provider):
            return "9350138" if provider == Sources.TVDB.value else "209867"

        with (
            patch(
                "app.services.anime_migration.anime_mapping.resolve_provider_series_id",
                side_effect=resolve,
            ),
            patch(
                "app.services.anime_migration.anime_mapping.find_entries_for_mal_id",
                return_value=[mapping],
            ),
            patch(
                "app.services.anime_migration.providers.tmdb.get_tvdb_episode_image_map",
                return_value={},
            ),
        ):
            tvdb_preflight = anime_migration.preflight_flat_anime_to_grouped(
                self.user,
                self.flat_item,
                Sources.TVDB.value,
            )
            tmdb_preflight = anime_migration.preflight_flat_anime_to_grouped(
                self.user,
                self.flat_item,
                Sources.TMDB.value,
            )
            tvdb_result = anime_migration.persist_flat_anime_migration(
                tvdb_preflight
            )
            tmdb_result = anime_migration.persist_flat_anime_migration(
                tmdb_preflight
            )
            completed = anime_migration.preflight_flat_anime_to_grouped(
                self.user,
                self.flat_item,
                Sources.TMDB.value,
            )

        self.assertEqual(tmdb_result.grouped_tv.id, tvdb_result.grouped_tv.id)
        self.assertEqual(completed.state, anime_migration.AnimeMigrationState.COMPLETE)
        self.assertEqual(completed.completed_target_item_id, self.grouped_item.id)
        self.assertEqual(TV.objects.count(), 1)
        self.assertEqual(Episode.objects.count(), 2)

    def test_commit_reconciles_warm_caches_and_smart_lists_once(self):
        warm_keys = {
            "media": "anime-migration-media-cache",
            "home": "anime-migration-home-cache",
            "time": "anime-migration-time-cache",
        }
        for key in warm_keys.values():
            cache.set(key, {"stale": True})
        cache_utils.register_media_list_cache_key(self.user.id, warm_keys["media"])
        cache_utils.register_home_row_cache_key(self.user.id, warm_keys["home"])
        cache_utils.register_time_left_cache_key(self.user.id, warm_keys["time"])
        smart_list = CustomList.objects.create(
            owner=self.user,
            name="All tracked media",
            is_smart=True,
        )

        with patch.object(
            anime_migration,
            "_reconcile_committed_migration",
            wraps=anime_migration._reconcile_committed_migration,
        ) as reconcile:
            result = anime_migration.persist_flat_anime_migration(self._preflight())

        reconcile.assert_called_once()
        for key in warm_keys.values():
            self.assertIsNone(cache.get(key))
        self.assertTrue(smart_list.items.filter(pk=result.grouped_tv.item_id).exists())

    def test_stale_preflight_aborts_without_mutation(self):
        preflight = self._preflight()
        Anime.all_objects.filter(pk=self.flat_entry.pk).update(progress=1)

        with self.assertRaises(anime_migration.AnimeMigrationError) as raised:
            anime_migration.persist_flat_anime_migration(preflight)

        self.assertEqual(raised.exception.state, anime_migration.AnimeMigrationState.STALE)
        self.assertEqual(raised.exception.code, anime_migration.STALE_CODE)
        self.assertFalse(TV.objects.exists())
        self.assertFalse(Episode.objects.exists())

    def test_inconsistent_marker_is_provably_partial_and_not_repaired(self):
        Anime.all_objects.filter(pk=self.flat_entry.pk).update(
            migrated_to_item=self.grouped_item,
            migrated_at=None,
        )
        before = self._table_snapshot()

        with self.assertRaises(anime_migration.AnimeMigrationError) as raised:
            self._preflight()

        self.assertEqual(
            raised.exception.state,
            anime_migration.AnimeMigrationState.PROVABLY_PARTIAL,
        )
        self.assertEqual(raised.exception.code, anime_migration.PARTIAL_CODE)
        self.assertEqual(self._table_snapshot(), before)

    def test_grouped_rewatches_are_ambiguous_and_preserved(self):
        grouped_tv = TV.objects.create(
            item=self.grouped_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        season_item = Item.objects.create(
            media_id="9350138",
            source=Sources.TVDB.value,
            media_type=MediaTypes.SEASON.value,
            library_media_type=MediaTypes.ANIME.value,
            season_number=1,
            title="Frieren",
            image="https://example.com/season.jpg",
        )
        season = Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=grouped_tv,
            status=Status.IN_PROGRESS.value,
        )
        episode_item = Item.objects.create(
            media_id="9350138",
            source=Sources.TVDB.value,
            media_type=MediaTypes.EPISODE.value,
            library_media_type=MediaTypes.ANIME.value,
            season_number=1,
            episode_number=1,
            title="Episode 1",
            image="https://example.com/episode.jpg",
        )
        Episode.objects.bulk_create(
            [
                Episode(item=episode_item, related_season=season, end_date=timezone.now()),
                Episode(item=episode_item, related_season=season, end_date=timezone.now()),
            ]
        )
        before = self._table_snapshot()

        with self.assertRaises(anime_migration.AnimeMigrationError) as raised:
            self._preflight()

        self.assertEqual(
            raised.exception.state,
            anime_migration.AnimeMigrationState.AMBIGUOUS,
        )
        self.assertEqual(raised.exception.code, anime_migration.AMBIGUOUS_CODE)
        self.assertEqual(self._table_snapshot(), before)

    def _track_under_tmdb(self):
        tmdb_item = Item.objects.create(
            media_id="209867",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.ANIME.value,
            title="Frieren: Beyond Journey's End",
        )
        TV.objects.create(item=tmdb_item, user=self.user, status=Status.IN_PROGRESS.value)
        return tmdb_item

    def _assert_preflight_refused_without_writes(self):
        before = self._table_snapshot()

        with self.assertRaises(anime_migration.AnimeMigrationError) as raised:
            self._preflight()

        self.assertEqual(raised.exception.code, anime_migration.AMBIGUOUS_CODE)
        self.assertEqual(self._table_snapshot(), before)

    def test_show_tracked_under_the_mapped_tmdb_id_is_not_duplicated(self):
        """Regression: migrating to TVDB created a second, TVDB-sourced show
        beside the TMDB-sourced grouped show the user already tracked.
        """
        self._track_under_tmdb()
        series_ids = {Sources.TVDB.value: "9350138", Sources.TMDB.value: "209867"}

        with patch(
            "app.services.anime_migration.anime_mapping.resolve_provider_series_id",
            side_effect=lambda _mal_id, provider: series_ids[provider],
        ):
            self._assert_preflight_refused_without_writes()

    def test_show_linked_to_the_tvdb_series_is_not_duplicated(self):
        """A TMDB show linked to the TVDB series counts even without a mapping."""
        tmdb_item = self._track_under_tmdb()
        ItemProviderLink.objects.create(
            item=tmdb_item,
            provider=Sources.TVDB.value,
            provider_media_id="9350138",
            provider_media_type=MediaTypes.TV.value,
        )
        series_ids = {Sources.TVDB.value: "9350138", Sources.TMDB.value: None}

        with patch(
            "app.services.anime_migration.anime_mapping.resolve_provider_series_id",
            side_effect=lambda _mal_id, provider: series_ids[provider],
        ):
            self._assert_preflight_refused_without_writes()

    def _concurrent_submit(self, preflight):
        barrier = Barrier(2)

        def migrate():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                return anime_migration.persist_flat_anime_migration(preflight)
            finally:
                close_old_connections()

        with (
            patch.object(
                signals := anime_migration.signals,
                "_invalidate_episode_history_changes",
            ),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            results = list(executor.map(lambda _index: migrate(), range(2)))
        self.assertIsNotNone(signals)
        return results

    @skipUnless(connection.vendor == "sqlite", "SQLite concurrency coverage")
    def test_sqlite_double_submit_returns_one_completed_migration(self):
        results = self._concurrent_submit(self._preflight())

        self.assertEqual(
            {result.grouped_tv.id for result in results},
            {results[0].grouped_tv.id},
        )
        self.assertEqual(TV.objects.count(), 1)
        self.assertEqual(Episode.objects.count(), 2)

    @skipUnless(connection.vendor == "postgresql", "PostgreSQL locking coverage")
    def test_postgresql_double_submit_waits_on_source_row_lock(self):
        results = self._concurrent_submit(self._preflight())

        self.assertEqual(
            {result.grouped_tv.id for result in results},
            {results[0].grouped_tv.id},
        )
        self.assertEqual(TV.objects.count(), 1)
        self.assertEqual(Episode.objects.count(), 2)
