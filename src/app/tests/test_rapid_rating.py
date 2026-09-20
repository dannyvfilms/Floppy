from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import SimpleTestCase

from app import rapid_rating


def _user(scale=10):
    return SimpleNamespace(rating_scale_max=scale)


class RapidRatingTests(SimpleTestCase):
    def test_display_factor_respects_five_point_scale(self):
        self.assertEqual(rapid_rating._display_factor(_user(5)), Decimal(1) / 2)
        self.assertEqual(rapid_rating._display_factor(_user(10)), Decimal(1))

    def test_display_factor_falls_back_to_ten_point_scale(self):
        user = SimpleNamespace(rating_scale_max="bad")

        self.assertEqual(rapid_rating._display_factor(user), Decimal(1))

    def test_safe_int_rejects_invalid_filter_values(self):
        self.assertEqual(rapid_rating._safe_int("42"), 42)
        self.assertEqual(rapid_rating._safe_int(7), 7)
        self.assertIsNone(rapid_rating._safe_int(""))
        self.assertIsNone(rapid_rating._safe_int("not-an-id"))

    def test_show_aggregate_excludes_specials(self):
        user = _user()
        queryset = MagicMock()
        queryset.values.return_value = queryset
        queryset.annotate.return_value = []
        manager = MagicMock()
        manager.filter.return_value = queryset

        with patch.object(
            rapid_rating,
            "Episode",
            SimpleNamespace(objects=manager),
        ):
            rapid_rating._stats_by_show(user, {11, 12})

        manager.filter.assert_called_once_with(
            related_season__user=user,
            related_season__related_tv__user=user,
            related_season__related_tv_id__in={11, 12},
            status="Completed",
            item__season_number__gt=0,
        )

    def test_tv_queue_limit_remains_500(self):
        self.assertEqual(rapid_rating.TV_QUEUE_LIMIT, 500)

    def test_supported_filter_contracts_remain_stable(self):
        self.assertEqual(
            rapid_rating.VALID_RATING_STATES,
            {"unrated", "rated", "all"},
        )
        self.assertEqual(
            rapid_rating.VALID_ORDERS,
            {"recent", "oldest", "episode", "random"},
        )

    def test_rapid_rating_is_linked_from_sidebar(self):
        template = (
            settings.BASE_DIR / "templates" / "base.html"
        ).read_text(encoding="utf-8")

        self.assertIn("{% url 'rapid_rating' as rapid_rating_url %}", template)
        self.assertIn('<span>{% trans "Rapid Rating" %}</span>', template)
