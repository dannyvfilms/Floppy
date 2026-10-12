from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.template.loader import render_to_string
from django.test import SimpleTestCase

from app.models import MediaTypes
from app.templatetags import derived_tv_ratings


def _user(*, scale=10, authenticated=True):
    return SimpleNamespace(
        is_authenticated=authenticated,
        rating_scale_max=scale,
    )


class DerivedTVRatingsTests(SimpleTestCase):
    def test_tv_rating_deduplicates_rewatches_and_uses_newest_row(self):
        with patch.object(
            derived_tv_ratings,
            "_episode_rows",
            return_value=[
                {"item_id": 1, "score": Decimal(8)},
                {"item_id": 1, "score": Decimal(2)},
                {"item_id": 2, "score": None},
            ],
        ):
            result = derived_tv_ratings.derived_tv_rating(
                _user(),
                MediaTypes.TV.value,
                {"media_id": "123", "source": "tmdb"},
            )

        self.assertEqual(result["score"], "8.00")
        self.assertEqual(result["raw_score"], 8.0)
        self.assertEqual(result["rated"], 1)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["coverage_percent"], 50.0)
        self.assertTrue(result["specials_excluded"])

    def test_rating_uses_five_point_display_scale(self):
        with patch.object(
            derived_tv_ratings,
            "_episode_rows",
            return_value=[{"item_id": 1, "score": Decimal(8)}],
        ):
            result = derived_tv_ratings.derived_tv_rating(
                _user(scale=5),
                MediaTypes.TV.value,
                {"media_id": "123", "source": "tmdb"},
            )

        self.assertEqual(result["score"], "4.00")

    def test_unrated_completed_episodes_return_coverage_without_average(self):
        with patch.object(
            derived_tv_ratings,
            "_episode_rows",
            return_value=[
                {"item_id": 1, "score": None},
                {"item_id": 2, "score": None},
            ],
        ):
            result = derived_tv_ratings.derived_tv_rating(
                _user(),
                MediaTypes.SEASON.value,
                {"media_id": "123", "source": "tmdb", "season_number": 2},
            )

        self.assertIsNone(result["score"])
        self.assertEqual(result["rated"], 0)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["coverage_percent"], 0.0)
        self.assertEqual(str(result["label"]), "Season 2")

    def test_specials_mapping_uses_specials_label(self):
        with patch.object(
            derived_tv_ratings,
            "_episode_rows",
            return_value=[{"item_id": 1, "score": Decimal(7)}],
        ):
            result = derived_tv_ratings.derived_tv_rating(
                _user(),
                MediaTypes.SEASON.value,
                {"media_id": "123", "source": "tmdb", "season_number": "0"},
            )

        self.assertEqual(str(result["label"]), "Specials")

    def test_anonymous_and_non_tv_media_are_not_supported(self):
        with patch.object(derived_tv_ratings, "_episode_rows", return_value=[]):
            self.assertIsNone(
                derived_tv_ratings.derived_tv_rating(
                    _user(authenticated=False),
                    MediaTypes.TV.value,
                    {"media_id": "123", "source": "tmdb"},
                )
            )
            self.assertIsNone(
                derived_tv_ratings.derived_tv_rating(
                    _user(),
                    MediaTypes.MOVIE.value,
                    {"media_id": "123", "source": "tmdb"},
                )
            )

    def test_episode_rows_excludes_specials_for_tv(self):
        qs = MagicMock()
        qs.filter.return_value = qs
        qs.order_by.return_value = qs
        expected = object()
        qs.values.return_value = expected

        manager = MagicMock()
        manager.filter.return_value = qs
        fake_episode = SimpleNamespace(objects=manager)

        with patch.object(derived_tv_ratings, "Episode", fake_episode):
            result = derived_tv_ratings._episode_rows(
                _user(),
                MediaTypes.TV.value,
                {"media_id": "123", "source": "tmdb"},
            )

        self.assertIs(result, expected)
        qs.filter.assert_called_once_with(item__season_number__gt=0)
        qs.order_by.assert_called_once_with(
            "item_id",
            "-end_date",
            "-created_at",
            "-id",
        )

    def test_episode_rows_filters_exact_season_from_mapping(self):
        qs = MagicMock()
        qs.filter.return_value = qs
        qs.order_by.return_value = qs
        expected = object()
        qs.values.return_value = expected

        manager = MagicMock()
        manager.filter.return_value = qs
        fake_episode = SimpleNamespace(objects=manager)

        with patch.object(derived_tv_ratings, "Episode", fake_episode):
            result = derived_tv_ratings._episode_rows(
                _user(),
                MediaTypes.SEASON.value,
                {"media_id": "123", "source": "tmdb", "season_number": "3"},
            )

        self.assertIs(result, expected)
        qs.filter.assert_called_once_with(item__season_number=3)

    def test_detail_score_slot_renders_derived_rating_for_tv_and_season(self):
        template = (
            settings.BASE_DIR
            / "templates"
            / "app"
            / "components"
            / "detail_score_chip_slot.html"
        ).read_text(encoding="utf-8")

        self.assertIn("{% load derived_tv_ratings %}", template)
        self.assertIn(
            "{% derived_tv_rating user media_type media as derived_tv_score %}",
            template,
        )
        self.assertIn(
            'include "app/components/derived_tv_rating_detail.html"',
            template,
        )


class DetailScoreChipStatesTests(SimpleTestCase):
    """The detail rating chip merges the manual score with the derived one."""

    derived = {
        "score": "7.60",
        "rated": 5,
        "total": 8,
        "label": "Season 1",
        "title": "Derived from rated episodes.",
    }
    no_data = {**derived, "score": None, "rated": 0}

    def _render(self, *, score=None, derived=None):
        """Return the chip button's markup, whitespace-collapsed, without the popup."""
        html = render_to_string(
            "app/components/detail_score_chip.html",
            {
                "current_instance": SimpleNamespace(id=7, score=score),
                "media_type": MediaTypes.SEASON.value,
                "user": _user(),
                "csrf_token": "token",
                "derived_tv_score": derived,
            },
        )
        self.assertIn("/update-score/season/7", html)
        button = html.split('x-show="showRatingPopup"')[0]
        return " ".join(button.split()).replace("> ", ">").replace(" <", "<")

    def test_blank_rating_when_neither_score_exists(self):
        for derived in (None, self.no_data):
            html = self._render(derived=derived)
            self.assertIn("Add rating", html)
            self.assertNotIn("episodes", html)

    def test_manual_score_only(self):
        html = self._render(score=Decimal(8), derived=self.no_data)
        self.assertIn(">8.0</span>", html)
        self.assertIn("Edit rating", html)
        self.assertNotIn("episodes", html)

    def test_whole_and_fractional_scores_both_show_one_decimal(self):
        """9 reads 9.0 so the card matches the provider cards (8.7)."""
        self.assertIn(">9.0</span>", self._render(score=Decimal(9)))
        self.assertIn(">8.5</span>", self._render(score=Decimal("8.5")))

    def test_derived_only_shows_score_and_coverage(self):
        html = self._render(derived=self.derived)
        self.assertIn(">7.6</span>", html)
        self.assertIn(">5/8 episodes</span>", html)
        self.assertNotIn("Derived ·", html)
        self.assertNotIn("Add rating", html)
        # Still the popup button, so a manual rating can be set from here.
        self.assertIn('@click="showRatingPopup = !showRatingPopup"', html)

    def test_both_scores_show_coverage_only_on_hover(self):
        html = self._render(score=Decimal(8), derived=self.derived)
        self.assertRegex(
            html,
            r">8.0</span><span[^>]*>\|</span>"
            r'<span class="sr-only">Derived rating</span><span[^>]*>7\.6<span',
        )
        # Coverage starts collapsed and slides open while hovered.
        self.assertRegex(
            html,
            r'data-derived-coverage[^>]*style="max-width: 0; opacity: 0;[^"]*transition'
            r'[^>]*:style="showCoverage \? \{ maxWidth[^>]*>&nbsp;· 5/8 episodes</span>',
        )
        self.assertIn('@mouseenter="showCoverage = true"', html)
        self.assertNotIn("Edit rating", html)

    def test_screen_readers_can_tell_the_two_scores_apart(self):
        both = self._render(score=Decimal(8), derived=self.derived)
        self.assertRegex(
            both,
            r'<span class="sr-only">Your score</span><span[^>]*>8\.0</span>.*'
            r'<span class="sr-only">Derived rating</span><span[^>]*>7\.6',
        )
        self.assertEqual(both.count('class="sr-only"'), 2)

        derived_only = self._render(derived=self.derived)
        self.assertIn('<span class="sr-only">Derived rating</span>', derived_only)
        self.assertNotIn("Your score", derived_only)

        manual_only = self._render(score=Decimal(8), derived=self.no_data)
        self.assertIn('<span class="sr-only">Your score</span>', manual_only)
        self.assertNotIn("Derived rating", manual_only)
