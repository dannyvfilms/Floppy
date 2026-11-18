from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from app.play_duration import elapsed_minutes, elapsed_minutes_by_hour, play_minutes


class PlayDurationTests(SimpleTestCase):
    def test_recorded_duration_takes_precedence(self):
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 2, tzinfo=UTC)
        self.assertEqual(play_minutes(start, end, 45), 45)
        self.assertEqual(play_minutes(start, end), 1440)

    def test_missing_equal_and_reversed_dates_have_no_duration(self):
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 2, tzinfo=UTC)
        self.assertEqual(elapsed_minutes(None, end), 0)
        self.assertEqual(elapsed_minutes(start, start), 0)
        self.assertEqual(elapsed_minutes(end, start), 0)

    def test_daylight_saving_and_range_clipping_measure_real_time(self):
        zone = ZoneInfo("America/Chicago")
        start = datetime(2026, 3, 7, 23, tzinfo=zone)
        end = datetime(2026, 3, 8, 4, tzinfo=zone)
        midnight = datetime(2026, 3, 8, tzinfo=zone)
        self.assertEqual(elapsed_minutes(start, end), 240)
        self.assertEqual(elapsed_minutes(start, end, range_end=midnight), 60)
        self.assertEqual(elapsed_minutes(start, end, range_start=midnight), 180)

    def test_hour_buckets_follow_skipped_and_repeated_hours(self):
        zone = ZoneInfo("America/Chicago")
        spring_start = datetime(2026, 3, 8, 1, 30, tzinfo=zone)
        spring_end = datetime(2026, 3, 8, 3, 30, tzinfo=zone)
        self.assertEqual(
            dict(elapsed_minutes_by_hour(spring_start, spring_end, spring_start, spring_end, zone)),
            {1: 30, 3: 30},
        )
        fall_start = datetime(2026, 11, 1, 0, 30, tzinfo=zone)
        fall_end = datetime(2026, 11, 1, 2, 30, tzinfo=zone)
        self.assertEqual(
            dict(elapsed_minutes_by_hour(fall_start, fall_end, fall_start, fall_end, zone)),
            {0: 30, 1: 120, 2: 30},
        )
        zone = ZoneInfo("Australia/Lord_Howe")
        start = datetime(2026, 10, 4, 1, 30, tzinfo=zone)
        end = datetime(2026, 10, 4, 3, tzinfo=zone)
        self.assertEqual(
            dict(elapsed_minutes_by_hour(start, end, start, end, zone)),
            {1: 30, 2: 30},
        )
