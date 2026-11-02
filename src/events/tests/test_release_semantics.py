"""Release-state semantics for precise and date-only release datetimes."""

from datetime import UTC, datetime, timedelta

from django.test import TestCase
from django.utils import timezone

from app.models import Item, MediaTypes, Sources
from events.calendar.helpers import date_parser
from events.models import Event, is_released_datetime, released_q


class ReleaseSemanticsTests(TestCase):
    """A date-only release is an all-day date, not a midday instant."""

    def setUp(self):
        self.item = Item.objects.create(
            media_id="release-semantics",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Release Semantics",
            season_number=1,
        )

    def test_precise_datetime_uses_the_instant(self):
        now = datetime(2026, 10, 20, 14, 0, tzinfo=UTC)
        Event.objects.create(
            item=self.item,
            content_number=3,
            datetime=now - timedelta(minutes=1),
        )

        self.assertTrue(is_released_datetime(now - timedelta(minutes=1), now))
        self.assertFalse(is_released_datetime(now + timedelta(minutes=1), now))
        self.assertTrue(Event.objects.filter(released_q("datetime", now)).exists())

    def test_unknown_time_is_not_released_on_its_listed_date(self):
        sentinel = date_parser("2026-10-20")
        now = datetime(2026, 10, 20, 14, 0, tzinfo=UTC)
        Event.objects.create(
            item=self.item,
            content_number=3,
            datetime=sentinel,
        )

        self.assertFalse(is_released_datetime(sentinel, now))
        self.assertFalse(Event.objects.filter(released_q("datetime", now)).exists())

    def test_unknown_time_is_released_once_the_listed_date_ends(self):
        sentinel = date_parser("2026-10-20")
        now = datetime(2026, 10, 21, 0, 0, tzinfo=UTC)
        Event.objects.create(
            item=self.item,
            content_number=3,
            datetime=sentinel,
        )

        self.assertTrue(is_released_datetime(sentinel, now))
        self.assertTrue(Event.objects.filter(released_q("datetime", now)).exists())

    def test_local_timezone_decides_when_the_listed_date_ends(self):
        """A user east of UTC must not see the episode on the listed day."""
        sentinel = date_parser("2026-10-20")
        Event.objects.create(
            item=self.item,
            content_number=3,
            datetime=sentinel,
        )
        with timezone.override("Europe/Lisbon"):
            before_midnight = datetime(2026, 10, 20, 14, 41, tzinfo=UTC)
            after_midnight = datetime(2026, 10, 21, 0, 30, tzinfo=UTC)

            self.assertFalse(is_released_datetime(sentinel, before_midnight))
            self.assertTrue(is_released_datetime(sentinel, after_midnight))
            # The SQL path extracts datetime parts in the active timezone,
            # so the sentinel must still be recognized outside UTC.
            self.assertFalse(
                Event.objects.filter(released_q("datetime", before_midnight)).exists(),
            )
            self.assertTrue(
                Event.objects.filter(released_q("datetime", after_midnight)).exists(),
            )

    def test_year_one_unknown_date_is_never_released(self):
        """The year-1 sentinel stays out of queries west of UTC (#1717)."""
        Event.objects.create(
            item=self.item,
            content_number=3,
            datetime=datetime(1, 1, 1, tzinfo=UTC),
        )
        now = datetime(2026, 10, 20, 14, 0, tzinfo=UTC)

        with timezone.override("America/Toronto"):
            self.assertFalse(
                Event.objects.filter(released_q("datetime", now)).exists(),
            )

    def test_issue_1588_visionquest_is_not_released_on_its_listed_day(self):
        """The VisionQuest report: listed Oct 20, airs early Oct 21 in Europe."""
        sentinel = date_parser("2026-10-20")
        with timezone.override("Europe/Lisbon"):
            comment_time = datetime(2026, 10, 20, 12, 41, tzinfo=UTC)
            last_minute_of_day = datetime(2026, 10, 20, 22, 59, tzinfo=UTC)
            next_local_midnight = datetime(2026, 10, 20, 23, 0, tzinfo=UTC)

            # The old predicate treated the sentinel as a midday instant.
            self.assertLessEqual(sentinel, comment_time)
            self.assertFalse(is_released_datetime(sentinel, comment_time))
            self.assertFalse(is_released_datetime(sentinel, last_minute_of_day))
            self.assertTrue(is_released_datetime(sentinel, next_local_midnight))

    def test_issue_1588_greys_anatomy_precise_us_airtime_stays_precise(self):
        """Grey's Anatomy airs 22:00 New York, which is 02:00 UTC next day."""
        us_airtime = datetime(2026, 10, 16, 2, 0, tzinfo=UTC)
        with timezone.override("Europe/Lisbon"):
            early_morning = datetime(2026, 10, 16, 1, 0, tzinfo=UTC)

            self.assertFalse(is_released_datetime(us_airtime, early_morning))
            self.assertTrue(is_released_datetime(us_airtime, us_airtime))
