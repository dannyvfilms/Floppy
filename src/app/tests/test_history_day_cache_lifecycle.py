"""Why history day payloads go missing, and the saves that must not drop them."""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from app import history_cache, history_cache_lifecycle
from app.history_cache_utils import HISTORY_DAY_CACHE_TIMEOUT, _day_cache_key
from app.models import Game, Item, MediaTypes, Movie, Sources, Status

STYLE = "repeats"


def _item(media_id, media_type=MediaTypes.MOVIE.value):
    return Item.objects.create(
        media_id=media_id,
        source=Sources.MANUAL.value,
        media_type=media_type,
        title=f"Title {media_id}",
    )


class HistoryDayCacheTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username="watcher")
        now = timezone.now()
        self.watched = Movie.objects.create(
            user=self.user,
            item=_item("watched"),
            status=Status.COMPLETED.value,
            end_date=now - timedelta(days=3),
        )
        Movie.objects.create(
            user=self.user,
            item=_item("watched-2"),
            status=Status.COMPLETED.value,
            end_date=now - timedelta(days=9),
        )
        self.repair()

    def repair(self):
        return history_cache.repair_history_day_cache_coverage(
            self.user.id, logging_style=STYLE
        )

    def day_keys(self):
        entry = cache.get(history_cache._cache_key(self.user.id, STYLE))
        return entry["days"]

    def cached_days(self):
        return [
            key
            for key in self.day_keys()
            if cache.get(_day_cache_key(self.user.id, STYLE, key)) is not None
        ]

    def repair_log(self):
        with self.assertLogs("app.history_cache_reader", level="INFO") as logs:
            self.repair()
        return next(
            line for line in logs.output if "history_day_coverage_repair" in line
        )


class UndatedSavesKeepHistoryDaysTests(HistoryDayCacheTestCase):
    def test_setup_cached_every_indexed_day(self):
        self.assertEqual(len(self.day_keys()), 2)
        self.assertEqual(self.cached_days(), self.day_keys())

    def test_adding_a_planning_entry_keeps_every_cached_day(self):
        Movie.objects.create(
            user=self.user, item=_item("planned"), status=Status.PLANNING.value
        )
        Game.objects.create(
            user=self.user,
            item=_item("planned-game", MediaTypes.GAME.value),
            status=Status.PLANNING.value,
        )

        self.assertEqual(len(self.cached_days()), 2)
        self.assertIsNotNone(cache.get(history_cache._cache_key(self.user.id, STYLE)))

    def test_updating_or_deleting_an_undated_entry_keeps_every_cached_day(self):
        planned = Movie.objects.create(
            user=self.user, item=_item("planned"), status=Status.PLANNING.value
        )
        planned.status = Status.PAUSED.value
        planned.save()
        planned.delete()

        self.assertEqual(len(self.cached_days()), 2)

    def test_clearing_a_date_still_drops_the_cached_days(self):
        days = self.day_keys()
        self.watched.end_date = None
        with patch("app.history_cache_lifecycle.schedule_history_refresh"):
            self.watched.save()

        self.assertEqual(
            [
                key
                for key in days
                if cache.get(_day_cache_key(self.user.id, STYLE, key)) is not None
            ],
            [],
        )


class MissingDayReasonTests(HistoryDayCacheTestCase):
    def drop_payloads(self):
        cache.delete_many(
            [_day_cache_key(self.user.id, STYLE, key) for key in self.day_keys()]
        )

    def test_days_deleted_on_purpose_are_reported_as_invalidated(self):
        with patch("app.history_cache_lifecycle.schedule_history_refresh"):
            history_cache.invalidate_history_cache(
                self.user.id, force=True, reason="media_import"
            )
        # The index goes with the payloads; rebuild it as a page view would.
        history_cache.cache_history_index(
            self.user.id,
            STYLE,
            history_cache.build_history_index(self.user, logging_style_override=STYLE),
        )

        line = self.repair_log()

        self.assertIn("missing_reason=invalidated", line)
        self.assertIn("missing_detail=media_import", line)

    def test_days_gone_after_a_complete_repair_are_reported_as_evicted(self):
        self.drop_payloads()

        line = self.repair_log()

        self.assertIn("missing_reason=evicted", line)
        self.assertIn("missing=2", line)

    def test_days_gone_after_their_ttl_are_reported_as_expired(self):
        self.drop_payloads()
        done_key = history_cache_lifecycle._repair_done_key(
            self.user.id, STYLE
        )
        done = cache.get(done_key)
        done["at"] = timezone.now() - timedelta(seconds=HISTORY_DAY_CACHE_TIMEOUT + 60)
        cache.set(done_key, done, timeout=None)

        self.assertIn("missing_reason=expired", self.repair_log())

    def test_days_never_built_are_reported_as_absent(self):
        cache.clear()
        history_cache.cache_history_index(
            self.user.id,
            STYLE,
            history_cache.build_history_index(self.user, logging_style_override=STYLE),
        )

        self.assertIn("missing_reason=absent", self.repair_log())
