"""History day payloads are built ahead of a visit only where a visit is likely.

The recent window of the style the user reads is kept warm. Older days and the
other style are built when a page asks for them; a write still invalidates both
styles, and the style that is not rebuilt is deleted so it is never served
from before the write.
"""

from datetime import datetime, time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from app import history_cache, tasks
from app.history_cache_index import build_history_index, cache_history_index
from app.history_cache_utils import (
    HISTORY_DAYS_PER_PAGE,
    _cache_key,
    _current_history_era,
    _day_cache_key,
    history_coverage_day_keys,
)
from app.models import Game, Item, MediaTypes, Movie, Sources, Status
from app.tasks_discover import warm_history_day_cache_coverage


def _at(day):
    return timezone.make_aware(datetime.combine(day, time(12)))


class HistoryCoverageScopeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        # Keep cache state under the test's control (eager Celery would run
        # refreshes inline); record what would have been scheduled.
        self.mocks = {}
        for target in (
            "app.history_cache_lifecycle.schedule_history_refresh",
            "app.history_cache_reader.schedule_history_refresh",
            "app.history_cache_lifecycle.schedule_history_day_cache_coverage",
            "app.history_cache_reader.schedule_history_day_cache_coverage",
        ):
            patcher = patch(target, return_value=True)
            self.mocks[target] = patcher.start()
            self.addCleanup(patcher.stop)
        self.user = get_user_model().objects.create_user(
            username="coverage", game_logging_style="repeats"
        )
        self.today = timezone.localdate()
        self.recent_days = [self.today - timedelta(days=n) for n in range(0, 40, 4)]
        self.old_days = [self.today - timedelta(days=400 + n) for n in range(40)]
        for number, day in enumerate(self.recent_days + self.old_days):
            self._movie(f"movie-{number}", day)
        cache.clear()

    def _item(self, media_id, media_type):
        return Item.objects.create(
            media_id=media_id,
            source=Sources.MANUAL.value,
            media_type=media_type,
            title=media_id,
        )

    def _movie(self, media_id, day):
        Movie.objects.create(
            item=self._item(media_id, MediaTypes.MOVIE.value),
            user=self.user,
            status=Status.COMPLETED.value,
            end_date=_at(day),
        )

    def _publish_index(self, style):
        keys = build_history_index(self.user, style)
        cache_history_index(self.user.id, style, keys)
        return keys

    def _cached(self, style, day):
        return cache.get(_day_cache_key(self.user.id, style, day.strftime("%Y%m%d")))

    def test_coverage_window_is_recent_days_and_at_least_one_page(self):
        keys = self._publish_index("repeats")
        window = history_coverage_day_keys(keys)
        # 10 recent days fall in the window; a page is 30 days, so the newest
        # 30 indexed days are kept even though 20 of them are old.
        self.assertEqual(window, keys[:HISTORY_DAYS_PER_PAGE])
        with patch("app.history_cache_utils.HISTORY_COVERAGE_WINDOW_DAYS", 0):
            self.assertEqual(history_coverage_day_keys(keys), keys)
        with patch("app.history_cache_utils.HISTORY_COVERAGE_WINDOW_DAYS", 500):
            self.assertEqual(history_coverage_day_keys(keys), keys)

    def test_repair_builds_only_the_window_and_then_stops(self):
        keys = self._publish_index("repeats")
        result = history_cache.repair_history_day_cache_coverage(
            self.user.id, "repeats", batch_size=0
        )
        self.assertEqual(result["rebuilt"], HISTORY_DAYS_PER_PAGE)
        self.assertEqual(result["remaining"], 0)
        built = cache.get_many(
            [_day_cache_key(self.user.id, "repeats", key) for key in keys]
        )
        self.assertEqual(len(built), HISTORY_DAYS_PER_PAGE)
        self.assertIsNone(self._cached("repeats", self.old_days[-1]))

        # Covered: the task does nothing and does not requeue itself.
        with patch.object(
            tasks.repair_history_day_cache_coverage_task, "apply_async"
        ) as requeue:
            again = tasks.repair_history_day_cache_coverage_task(
                self.user.id, "repeats", batch_size=0
            )
        self.assertEqual(again["rebuilt"], 0)
        requeue.assert_not_called()

    def test_repair_skips_the_style_the_user_does_not_read(self):
        self._publish_index("sessions")
        result = history_cache.repair_history_day_cache_coverage(
            self.user.id, "sessions", batch_size=0
        )
        self.assertEqual(result, {"rebuilt": 0, "remaining": 0, "days": 0})
        self.assertIsNone(self._cached("sessions", self.recent_days[0]))
        with patch("app.history_cache_utils.HISTORY_COVERAGE_BOTH_STYLES", True):
            result = history_cache.repair_history_day_cache_coverage(
                self.user.id, "sessions", batch_size=0
            )
        self.assertEqual(result["rebuilt"], HISTORY_DAYS_PER_PAGE)

    def test_warmer_queues_only_the_users_style(self):
        other = get_user_model().objects.create_user(
            username="coverage-sessions", game_logging_style="sessions"
        )
        with (
            patch("app.tasks_discover.interactive_request_active", return_value=False),
            patch.object(
                history_cache, "schedule_history_day_cache_coverage", return_value=True
            ) as schedule,
        ):
            result = warm_history_day_cache_coverage(user_ids=[self.user.id, other.id])
            calls = {
                (call.args[0], call.kwargs["logging_style"])
                for call in schedule.call_args_list
            }
            self.assertEqual(
                calls, {(self.user.id, "repeats"), (other.id, "sessions")}
            )
            self.assertEqual(result["scheduled"], 2)

            schedule.reset_mock()
            with patch("app.history_cache_utils.HISTORY_COVERAGE_BOTH_STYLES", True):
                warm_history_day_cache_coverage(user_ids=[self.user.id])
            self.assertEqual(schedule.call_count, 2)

    def test_game_write_invalidates_both_styles_and_rebuilds_only_the_users(self):
        day = self.recent_days[1]
        for style in ("sessions", "repeats"):
            self._publish_index(style)
            history_cache.get_cached_history_day(self.user, day, style)
            self.assertIsNotNone(self._cached(style, day))
        repeats_era = _current_history_era(self.user.id, "repeats")
        lifecycle_refresh = self.mocks[
            "app.history_cache_lifecycle.schedule_history_refresh"
        ]
        lifecycle_refresh.reset_mock()

        with patch.object(history_cache, "schedule_history_refresh") as prioritized:
            Game.objects.create(
                item=self._item("game-1", MediaTypes.GAME.value),
                user=self.user,
                status=Status.COMPLETED.value,
                progress=90,
                start_date=_at(day - timedelta(days=2)),
                end_date=_at(day),
            )

        scheduled_styles = {
            call.args[1]
            for mock in (lifecycle_refresh, prioritized)
            for call in mock.call_args_list
        }
        self.assertEqual(scheduled_styles, {"repeats"})
        # The style the user reads stays readable until its rebuild lands...
        self.assertNotEqual(_current_history_era(self.user.id, "repeats"), repeats_era)
        self.assertIsNotNone(self._cached("repeats", day))
        # ...and the other style cannot serve anything from before the write.
        self.assertIsNone(self._cached("sessions", day))
        self.assertIsNone(cache.get(_cache_key(self.user.id, "sessions")))

        # Switching styles reads correct, cold days.
        self.user.game_logging_style = "sessions"
        self.user.save(update_fields=["game_logging_style"])
        days, _meta = history_cache.get_month_history(self.user, day.year, day.month)
        titles = {
            entry["title"]
            for history_day in days
            if history_day["date"] == day
            for entry in history_day["entries"]
        }
        self.assertIn("game-1", titles)

    def test_old_month_is_built_on_demand_and_then_cached(self):
        self._publish_index("repeats")
        old = self.old_days[0]
        self.assertIsNone(self._cached("repeats", old))
        days, _meta = history_cache.get_month_history(self.user, old.year, old.month)
        self.assertIn(old, [history_day["date"] for history_day in days])
        self.assertIsNotNone(self._cached("repeats", old))
