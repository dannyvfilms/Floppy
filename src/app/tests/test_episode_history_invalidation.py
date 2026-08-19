import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.test import TransactionTestCase
from django.utils import timezone

from app import history_cache, signals
from app.models import TV, Episode, Item, MediaTypes, Season, Sources, Status


def _episode_metadata(media_type, *_args, **_kwargs):
    episodes = [{"episode_number": 1, "name": "One", "still_path": None}]
    if media_type == "tv_with_seasons":
        return {"season/1": {"episodes": episodes}}
    return {
        "season_number": 1,
        "episodes": episodes,
        "_tvdb_episode_image_map": {},
    }


class EpisodeHistoryInvalidationTests(TransactionTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.provider_patcher = patch(
            "app.models.providers.services.get_media_metadata",
            side_effect=_episode_metadata,
        )
        self.provider_patcher.start()
        self.addCleanup(self.provider_patcher.stop)
        history_refresh_patcher = patch(
            "app.history_cache_lifecycle.schedule_history_refresh",
            return_value=True,
        )
        history_refresh_patcher.start()
        self.addCleanup(history_refresh_patcher.stop)
        statistics_refresh_patcher = patch(
            "app.signals.statistics_cache.schedule_all_ranges_refresh",
        )
        statistics_refresh_patcher.start()
        self.addCleanup(statistics_refresh_patcher.stop)

        self.user = get_user_model().objects.create_user(username="history-move")
        tv_item = Item.objects.create(
            media_id="history-move",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="History Move",
        )
        tv = TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        season_item = Item.objects.create(
            media_id="history-move",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="History Move",
            season_number=1,
        )
        season = Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=tv,
            status=Status.IN_PROGRESS.value,
        )
        episode_item = Item.objects.create(
            media_id="history-move",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="One",
            season_number=1,
            episode_number=1,
        )
        previous_month = (timezone.now().replace(day=1) - datetime.timedelta(days=1)).replace(
            day=10,
            microsecond=0,
        )
        self.old_date = previous_month
        self.new_date = previous_month.replace(day=11)
        self.episode = Episode.objects.create(
            item=episode_item,
            related_season=season,
            end_date=self.old_date,
        )
        cache.clear()
        self.logging_style = "repeats"

    def _warm_old_and_new_days(self):
        history_cache.refresh_history_cache(
            self.user.id,
            logging_style=self.logging_style,
        )
        old_day = history_cache.history_day_key(self.old_date)
        new_day = history_cache.history_day_key(self.new_date)
        old_cache_key = history_cache._day_cache_key(
            self.user.id,
            self.logging_style,
            old_day,
        )
        new_cache_key = history_cache._day_cache_key(
            self.user.id,
            self.logging_style,
            new_day,
        )
        old_payload = cache.get(old_cache_key)
        index_key = history_cache._cache_key(self.user.id, self.logging_style)
        index_entry = cache.get(index_key)
        index_entry["days"] = list(dict.fromkeys([*index_entry["days"], new_day]))
        cache.set(index_key, index_entry)
        new_payload = {"stale": True}
        cache.set(new_cache_key, new_payload)
        return old_cache_key, new_cache_key, old_payload, new_payload

    def _assert_current_history(self):
        history_days, _meta = history_cache.get_month_history(
            self.user,
            self.new_date.year,
            self.new_date.month,
            logging_style_override=self.logging_style,
        )
        episode_days = {
            day["date"]: {
                entry["instance_id"]
                for entry in day["entries"]
                if entry["media_type"] == MediaTypes.EPISODE.value
            }
            for day in history_days
        }
        self.assertNotIn(
            self.episode.id,
            episode_days.get(self.old_date.date(), set()),
        )
        self.assertIn(
            self.episode.id,
            episode_days.get(self.new_date.date(), set()),
        )

    def test_moving_episode_evicts_both_warm_history_days(self):
        old_key, new_key, _old_payload, _new_payload = self._warm_old_and_new_days()

        self.episode.end_date = self.new_date
        self.episode.save(update_fields=["end_date"])

        self.assertIsNone(cache.get(old_key))
        self.assertIsNone(cache.get(new_key))
        self._assert_current_history()

    def test_episode_invalidation_runs_only_after_outer_transaction_commits(self):
        old_key, new_key, old_payload, new_payload = self._warm_old_and_new_days()

        with transaction.atomic():
            self.episode.end_date = self.new_date
            self.episode.save(update_fields=["end_date"])
            self.assertEqual(cache.get(old_key), old_payload)
            self.assertEqual(cache.get(new_key), new_payload)

        self.assertIsNone(cache.get(old_key))
        self.assertIsNone(cache.get(new_key))
        self._assert_current_history()

    @patch("app.signals._invalidate_episode_history_changes")
    def test_bulk_suppression_prevents_deferred_episode_invalidation(
        self,
        mock_invalidate,
    ):
        """Bulk tracking should schedule one consolidated refresh only."""
        with transaction.atomic(), signals.suppress_media_change_side_effects():
            self.episode.end_date = self.new_date
            self.episode.save(update_fields=["end_date"])
            self.episode.delete()

        mock_invalidate.assert_not_called()
