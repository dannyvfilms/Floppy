"""A missing History index must not cost a whole-history build in the request.

With no index cached, the month view answers from a month-bounded build,
schedules the full build in the background and never publishes the month list
as the index (readers treat that key as every day that exists).
"""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from app import history_cache_index, history_cache_reader
from app.history_cache_index import build_history_index
from app.history_cache_utils import _cache_key
from app.models import (
    TV,
    BoardGame,
    Episode,
    Game,
    Item,
    MediaTypes,
    Movie,
    Season,
    Sources,
    Status,
)


def _utc(month, day, hour=12, minute=0):
    return datetime(2026, month, day, hour, minute, tzinfo=UTC)


class HistoryMonthWindowTests(TestCase):
    """The month window lists exactly the days a full index lists there."""

    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.user = user_model.objects.create_user(username="window", password="x")
        cls.other = user_model.objects.create_user(username="other", password="x")
        counter = iter(range(10_000))

        def item(media_type, **extra):
            return Item.objects.create(
                media_id=f"{media_type}-{next(counter)}",
                source=Sources.MANUAL.value,
                media_type=media_type,
                title=f"{media_type}",
                **extra,
            )

        def movie(user, end):
            Movie.objects.create(
                item=item(MediaTypes.MOVIE.value),
                user=user,
                status=Status.COMPLETED.value,
                end_date=end,
            )

        # Month edges in UTC, plus late-evening plays that move across a
        # month boundary in time zones east or west of UTC.
        for end in (
            _utc(3, 1, 0, 30),
            _utc(3, 31, 23, 30),
            _utc(2, 28, 23, 30),
            _utc(4, 1, 0, 30),
            _utc(3, 15),
            _utc(1, 10),
            _utc(5, 10),
        ):
            movie(cls.user, end)
        movie(cls.other, _utc(3, 20))

        tv = TV.objects.create(
            item=item(MediaTypes.TV.value),
            user=cls.user,
            status=Status.IN_PROGRESS.value,
        )
        season = Season.objects.create(
            item=item(MediaTypes.SEASON.value, season_number=1),
            user=cls.user,
            related_tv=tv,
            status=Status.IN_PROGRESS.value,
        )
        # bulk_create: Episode.save() looks up show metadata.
        Episode.objects.bulk_create(
            [
                Episode(
                    item=item(
                        MediaTypes.EPISODE.value,
                        season_number=1,
                        episode_number=number,
                    ),
                    related_season=season,
                    end_date=end,
                )
                for number, end in enumerate((_utc(3, 7), _utc(6, 7)), start=1)
            ],
        )

        # Games: spans entering, leaving and covering March, a swapped span
        # and a created-at fallback. Repeats lists every day of a span;
        # sessions lists only the end (or start, or created) day.
        spans = (
            (_utc(2, 26), _utc(3, 2), 120),
            (_utc(3, 29), _utc(4, 3), 60),
            (_utc(2, 20), _utc(4, 10), 600),
            (_utc(3, 12), _utc(3, 10), 30),
            (None, None, 45),
            (_utc(1, 1), _utc(1, 3), 60),
        )
        for model, media_type in (
            (Game, MediaTypes.GAME.value),
            (BoardGame, MediaTypes.BOARDGAME.value),
        ):
            for start, end, progress in spans:
                row = model.objects.create(
                    item=item(media_type),
                    user=cls.user,
                    status=Status.IN_PROGRESS.value,
                    progress=progress,
                    start_date=start,
                    end_date=end,
                )
                if start is None and end is None:
                    model.objects.filter(id=row.id).update(created_at=_utc(3, 22))

    def setUp(self):
        cache.clear()

    def test_window_matches_the_full_index_for_both_styles_and_zones(self):
        for tz_name in ("UTC", "Pacific/Kiritimati", "Pacific/Pago_Pago"):
            with timezone.override(tz_name):
                for style in ("sessions", "repeats"):
                    for year, month in ((2026, 2), (2026, 3), (2026, 4)):
                        first = date(year, month, 1)
                        last = (first + timedelta(days=32)).replace(day=1) - (
                            timedelta(days=1)
                        )
                        prefix = f"{year}{month:02d}"
                        full = [
                            key
                            for key in build_history_index(self.user, style)
                            if key.startswith(prefix)
                        ]
                        window = build_history_index(
                            self.user, style, window=(first, last)
                        )
                        with self.subTest(tz=tz_name, style=style, month=month):
                            if month == 3:
                                self.assertTrue(full)
                            self.assertEqual(window, full)

    def test_repeats_window_includes_every_day_of_a_span_crossing_months(self):
        window = build_history_index(
            self.user, "repeats", window=(date(2026, 3, 1), date(2026, 3, 31))
        )
        # The Feb 20 - Apr 10 span covers the whole month.
        self.assertEqual(len(window), 31)

    def test_window_never_lists_another_users_days(self):
        window = build_history_index(
            self.other, "repeats", window=(date(2026, 3, 1), date(2026, 3, 31))
        )
        self.assertEqual(window, ["20260320"])

    @patch("app.history_cache_reader.schedule_history_day_cache_coverage")
    @patch("app.history_cache_reader.schedule_history_refresh", return_value=True)
    def test_missing_index_answers_from_the_month_and_refreshes_once(
        self, mock_refresh, _mock_coverage
    ):
        with patch.object(
            history_cache_reader,
            "build_history_index",
            wraps=history_cache_index.build_history_index,
        ) as spy:
            days, _meta = history_cache_reader.get_month_history(
                self.user, 2026, 3, logging_style_override="sessions"
            )

        self.assertEqual(len(spy.call_args_list), 1)
        self.assertEqual(
            spy.call_args.kwargs["window"], (date(2026, 3, 1), date(2026, 3, 31))
        )
        mock_refresh.assert_called_once_with(
            self.user.id, "sessions", warm_days=0, allow_inline=False
        )
        self.assertIsNone(cache.get(_cache_key(self.user.id, "sessions")))
        expected = [
            key
            for key in build_history_index(self.user, "sessions")
            if key.startswith("202603")
        ]
        self.assertEqual(
            [day["date"].strftime("%Y%m%d") for day in days],
            expected,
        )

    @patch("app.history_cache_reader.schedule_history_day_cache_coverage")
    def test_refresh_in_flight_is_not_scheduled_again(self, _mock_coverage):
        with patch(
            "app.history_cache_reader.schedule_history_refresh", return_value=True
        ) as first:
            history_cache_reader.get_month_history(
                self.user, 2026, 3, logging_style_override="repeats"
            )
        first.assert_called_once()
        # A real schedule leaves the refresh lock in place until the task runs.
        with patch("app.tasks.refresh_history_cache_task.apply_async"):
            history_cache_reader.schedule_history_refresh(
                self.user.id, "repeats", warm_days=0, allow_inline=False
            )
        with patch(
            "app.history_cache_reader.schedule_history_refresh"
        ) as second:
            history_cache_reader.get_month_history(
                self.user, 2026, 4, logging_style_override="repeats"
            )
        second.assert_not_called()

    @patch("app.history_cache_reader.schedule_history_day_cache_coverage")
    def test_page_renders_from_the_window_when_the_queue_is_down(
        self, _mock_coverage
    ):
        with (
            patch(
                "app.tasks.refresh_history_cache_task.apply_async",
                side_effect=RuntimeError("broker down"),
            ),
            patch.object(
                history_cache_reader,
                "build_history_index",
                wraps=history_cache_index.build_history_index,
            ) as spy,
        ):
            for _ in range(2):
                days, _meta = history_cache_reader.get_month_history(
                    self.user, 2026, 3, logging_style_override="repeats"
                )
                self.assertEqual(len(days), 31)

        # No inline whole-history fallback, and no index published.
        self.assertTrue(all(call.kwargs.get("window") for call in spy.call_args_list))
        self.assertIsNone(cache.get(_cache_key(self.user.id, "repeats")))

    @patch("app.history_cache_reader.schedule_history_day_cache_coverage")
    @patch("app.history_cache_reader.schedule_history_refresh", return_value=True)
    def test_a_write_after_the_window_read_reaches_the_refreshed_index(
        self, _mock_refresh, _mock_coverage
    ):
        history_cache_reader.get_month_history(
            self.user, 2026, 5, logging_style_override="sessions"
        )
        Movie.objects.create(
            item=Item.objects.create(
                media_id="late-write",
                source=Sources.MANUAL.value,
                media_type=MediaTypes.MOVIE.value,
                title="Late",
            ),
            user=self.user,
            status=Status.COMPLETED.value,
            end_date=_utc(5, 20),
        )
        history_cache_reader.refresh_history_cache(self.user.id, "sessions")

        days, _meta = history_cache_reader.get_month_history(
            self.user, 2026, 5, logging_style_override="sessions"
        )
        self.assertIn("20260520", [day["date"].strftime("%Y%m%d") for day in days])
        self.assertIn(
            "20260520", cache.get(_cache_key(self.user.id, "sessions"))["days"]
        )
