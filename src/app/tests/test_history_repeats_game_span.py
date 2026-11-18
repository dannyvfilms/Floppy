"""A repeats-style history day must only load the games that can reach it.

Every repeats day used to load the user's entire game and board-game library
and date-filter it in Python. With a few thousand days of history that made
the background day-cache repair the dominant CPU cost of an idle instance
(#1158). The SQL prefilter must stay a superset of the exact Python check, so
these tests pin the output against that check across the awkward spans.
"""

from datetime import UTC, date, datetime, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from app import history_cache
from app.history_cache_day_builder import _span_may_touch_day, build_history_day
from app.models import BoardGame, Game, Item, MediaTypes, Sources, Status


def _utc(day, hour=12, minute=0):
    return datetime(2026, 3, day, hour, minute, tzinfo=UTC)


def _expected_on_day(row, day):
    """The exact per-day rule the builder applies after the prefilter."""
    if (row.progress or 0) <= 0 and not (
        row.start_date and row.end_date and row.end_date > row.start_date
    ):
        return False
    start = row.start_date or row.end_date or row.created_at
    end = row.end_date or row.start_date or row.created_at
    start_day = timezone.localtime(start).date()
    end_day = timezone.localtime(end).date()
    if start_day > end_day:
        start_day, end_day = end_day, start_day
    return start_day <= day <= end_day


class RepeatsGameSpanTests(TestCase):
    """Repeats-day game entries match the full-scan rule exactly."""

    SPANS = {
        "range": (_utc(10, 10), _utc(12, 10), 300),
        "start_only": (_utc(11), None, 60),
        "end_only_late_utc": (None, _utc(11, 23, 30), 60),
        "start_early_utc": (_utc(11, 0, 30), None, 60),
        "created_fallback": (None, None, 45),
        "swapped": (_utc(13), _utc(9), 120),
        "no_progress": (_utc(10), _utc(12), 0),
        "far_away": (_utc(1) - timedelta(days=400), _utc(1) - timedelta(days=399), 90),
    }

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="span-user", password="12345"
        )
        for model, media_type in (
            (Game, MediaTypes.GAME.value),
            (BoardGame, MediaTypes.BOARDGAME.value),
        ):
            for name, (start, end, progress) in cls.SPANS.items():
                item = Item.objects.create(
                    media_id=f"{media_type}-{name}",
                    source=Sources.MANUAL.value,
                    media_type=media_type,
                    title=f"{media_type} {name}",
                )
                row = model.objects.create(
                    item=item,
                    user=cls.user,
                    status=Status.IN_PROGRESS.value,
                    progress=progress,
                    start_date=start,
                    end_date=end,
                )
                if name == "created_fallback":
                    model.objects.filter(id=row.id).update(created_at=_utc(11, 23))

    def test_entries_match_the_full_scan_rule_across_timezones(self):
        days = [date(2026, 3, 8) + timedelta(days=offset) for offset in range(7)]
        for tz_name in ("UTC", "Pacific/Kiritimati", "Pacific/Pago_Pago"):
            with timezone.override(tz_name):
                for model, media_type in (
                    (Game, MediaTypes.GAME.value),
                    (BoardGame, MediaTypes.BOARDGAME.value),
                ):
                    rows = list(model.objects.filter(user=self.user))
                    for day in days:
                        with self.subTest(tz=tz_name, media_type=media_type, day=day):
                            payload = build_history_day(
                                self.user,
                                day,
                                logging_style_override="repeats",
                                media_types=[media_type],
                            )
                            actual = {
                                entry["instance_id"]
                                for entry in (payload or {}).get("entries", [])
                                if entry["media_type"] == media_type
                            }
                            expected = {
                                row.id for row in rows if _expected_on_day(row, day)
                            }
                            self.assertEqual(actual, expected)

    def test_prefilter_drops_rows_that_cannot_reach_the_day(self):
        day_start = _utc(11, 0)
        candidates = _span_may_touch_day(
            Game.objects.filter(user=self.user),
            day_start,
            day_start + timedelta(days=1),
        )
        names = {
            game.item.media_id.removeprefix("game-")
            for game in candidates.select_related("item")
        }
        self.assertNotIn("far_away", names)
        self.assertIn("no_progress", names)
        self.assertIn("swapped", names)
        self.assertIn("created_fallback", names)

    def test_inferred_game_time_is_split_at_local_midnight(self):
        game = Game.objects.get(user=self.user, item__media_id="game-no_progress")
        Game.objects.filter(pk=game.pk).update(
            start_date=_utc(10, 23), end_date=_utc(11, 2)
        )
        with timezone.override("UTC"):
            amounts = []
            for day in (date(2026, 3, 10), date(2026, 3, 11)):
                payload = build_history_day(
                    self.user, day, logging_style_override="repeats",
                    media_types=[MediaTypes.GAME.value],
                )
                amounts.append(next(
                    entry["runtime_minutes"] for entry in payload["entries"]
                    if entry["instance_id"] == game.pk
                ))
        self.assertEqual(amounts, [60, 120])

    def test_inferred_only_entry_is_indexed_and_filtered_history_matches(self):
        game = Game.objects.get(user=self.user, item__media_id="game-no_progress")
        Game.objects.filter(pk=game.pk).update(
            start_date=datetime(2027, 1, 3, 23, tzinfo=UTC),
            end_date=datetime(2027, 1, 4, 2, tzinfo=UTC),
        )
        with timezone.override("UTC"):
            keys = history_cache.build_history_index(
                self.user, "repeats", media_types=[MediaTypes.GAME.value]
            )
            self.assertIn("20270103", keys)
            self.assertIn("20270104", keys)
            days = history_cache.build_history_days(
                self.user, filters={"media_type": "game"},
                date_filters={"start_date": "2027-01-03", "end_date": "2027-01-04"},
                logging_style_override="repeats",
            )
            amounts = {day["date"]: sum(entry["runtime_minutes"] for entry in day["entries"])
                       for day in days}
            self.assertEqual(amounts[date(2027, 1, 3)], 60)
            self.assertEqual(amounts[date(2027, 1, 4)], 120)
            first_day = history_cache.build_history_days(
                self.user, filters={"media_type": "game"},
                date_filters={"start_date": "2027-01-03", "end_date": "2027-01-03"},
                logging_style_override="repeats",
            )
            self.assertEqual([day["date"] for day in first_day], [date(2027, 1, 3)])
            self.assertEqual(first_day[0]["total_minutes"], 60)

    def test_inferred_boardgame_is_indexed_without_a_play_count(self):
        boardgame = BoardGame.objects.get(user=self.user, item__media_id="boardgame-no_progress")
        BoardGame.objects.filter(pk=boardgame.pk).update(
            start_date=datetime(2027, 2, 3, 10, tzinfo=UTC),
            end_date=datetime(2027, 2, 3, 12, tzinfo=UTC),
        )
        with timezone.override("UTC"):
            keys = history_cache.build_history_index(
                self.user, "repeats", media_types=[MediaTypes.BOARDGAME.value]
            )
            self.assertIn("20270203", keys)
            days = history_cache.build_history_days(
                self.user, filters={"media_type": "boardgame"},
                date_filters={"start_date": "2027-02-03", "end_date": "2027-02-03"},
                logging_style_override="repeats",
            )
            self.assertEqual(days[0]["total_minutes"], 120)

    def test_session_preserves_fractional_inferred_minutes(self):
        game = Game.objects.get(user=self.user, item__media_id="game-no_progress")
        Game.objects.filter(pk=game.pk).update(
            start_date=datetime(2027, 2, 4, 10, tzinfo=UTC),
            end_date=datetime(2027, 2, 4, 10, 0, 30, tzinfo=UTC),
        )
        with timezone.override("UTC"):
            payload = build_history_day(
                self.user, date(2027, 2, 4), logging_style_override="sessions",
                media_types=[MediaTypes.GAME.value],
            )
        self.assertEqual(payload["entries"][0]["runtime_minutes"], 0.5)
