"""The header theme toggle posts only `theme` to the preferences endpoint.

Any field the view reads with a fallback instead of a presence check would be
reset to that fallback on every toggle, so this pins the partial-post contract.
"""

from django.test import TestCase
from django.urls import reverse

from users.models import QuickSeasonUpdateChoices, User


class ThemeTogglePartialPostTests(TestCase):
    """A theme-only post must change the theme and nothing else."""

    def setUp(self):
        """Sign in a user carrying non-default preference values."""
        self.user = User.objects.create_user(username="toggler", password="p12345678")
        self.user.quick_season_update_mobile = QuickSeasonUpdateChoices.values[-1]
        self.user.book_comic_manga_progress_percentage = True
        self.user.progress_bar = True
        self.user.hide_zero_rating = True
        self.user.save()
        self.client.force_login(self.user)

    def test_theme_only_post_applies_the_theme(self):
        """The toggle still persists the theme it sends."""
        self.client.post(reverse("preferences"), {"theme": "light"})

        self.user.refresh_from_db()
        self.assertEqual(self.user.theme, "light")

    def test_theme_only_post_preserves_unrelated_preferences(self):
        """Absent fields keep their stored value instead of falling back."""
        expected = {
            "quick_season_update_mobile": self.user.quick_season_update_mobile,
            "book_comic_manga_progress_percentage": True,
            "progress_bar": True,
            "hide_zero_rating": True,
        }

        self.client.post(reverse("preferences"), {"theme": "light"})

        self.user.refresh_from_db()
        for field, value in expected.items():
            self.assertEqual(
                getattr(self.user, field),
                value,
                f"the theme toggle reset {field}",
            )

    def test_preferences_form_can_still_clear_a_boolean(self):
        """A real form post that omits a checkbox must still turn it off."""
        self.client.post(
            reverse("preferences"),
            {"theme": "dark", "book_comic_manga_progress_percentage": "0"},
        )

        self.user.refresh_from_db()
        self.assertFalse(self.user.book_comic_manga_progress_percentage)

    def test_toggle_is_visible_for_basic_themes(self):
        for theme in ("system", "light", "dark"):
            with self.subTest(theme=theme):
                self.user.theme = theme
                self.user.save(update_fields=["theme"])

                response = self.client.get(reverse("preferences"))

                self.assertContains(response, 'aria-label="Toggle theme"')

    def test_toggle_is_hidden_for_explicit_presets(self):
        for theme in ("glass", "plex", "catppuccin_mocha", "custom"):
            with self.subTest(theme=theme):
                self.user.theme = theme
                self.user.save(update_fields=["theme"])

                response = self.client.get(reverse("preferences"))

                self.assertNotContains(response, 'aria-label="Toggle theme"')
