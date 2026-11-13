from datetime import UTC, datetime
from unittest.mock import MagicMock

from django.test import TestCase, override_settings
from django.utils import translation

from users.models import DateFormatChoices
from users.templatetags import user_tags


class UserDateFormatOverflowTests(TestCase):
    """user_date_format/time/datetime must not raise on the year-1 sentinel."""

    def setUp(self):
        self.user = MagicMock()
        self.user.date_format = DateFormatChoices.ISO_8601

    @override_settings(TIME_ZONE="UTC")
    def test_month_names_follow_interface_language_in_each_named_date_style(self):
        value = datetime(2026, 4, 27, tzinfo=UTC)
        for style, english, spanish in (
            (DateFormatChoices.MONTH_D_YYYY, "Apr 27, 2026", "Abr 27, 2026"),
            (DateFormatChoices.D_MON_YYYY, "27 Apr 2026", "27 Abr 2026"),
            (DateFormatChoices.LONG_EU, "27 Apr, 2026", "27 Abr, 2026"),
        ):
            self.user.date_format = style
            with self.subTest(style=style), translation.override("en"):
                self.assertEqual(user_tags.user_date_format(value, self.user), english)
            with self.subTest(style=style), translation.override("es"):
                self.assertEqual(user_tags.user_date_format(value, self.user), spanish)

    @override_settings(TIME_ZONE="America/New_York")
    def test_user_date_format_handles_year_one_sentinel(self):
        """A negative UTC offset underflows below datetime.MINYEAR for year 1.

        The filter must fall back to the default format instead of raising.
        """
        sentinel = datetime(1, 1, 1, tzinfo=UTC)
        result = user_tags.user_date_format(sentinel, self.user)
        self.assertIsInstance(result, str)
        self.assertTrue(result)

    @override_settings(TIME_ZONE="America/New_York")
    def test_user_time_format_handles_year_one_sentinel(self):
        sentinel = datetime(1, 1, 1, tzinfo=UTC)
        result = user_tags.user_time_format(sentinel, self.user)
        self.assertIsInstance(result, str)
        self.assertTrue(result)

    @override_settings(TIME_ZONE="America/New_York")
    def test_user_datetime_format_handles_year_one_sentinel(self):
        sentinel = datetime(1, 1, 1, tzinfo=UTC)
        result = user_tags.user_datetime_format(sentinel, self.user)
        self.assertIsInstance(result, str)
        self.assertTrue(result)
