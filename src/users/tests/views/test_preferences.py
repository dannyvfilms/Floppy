from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class PreferencesViewTests(TestCase):
    """Tests for the preferences view."""

    def setUp(self):
        """Create user for the tests."""
        self.credentials = {"username": "testuser", "password": "testpass123"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    def test_preferences_post_persists_date_format(self):
        """POSTing a new date_format should persist to the DB, not just render."""
        response = self.client.post(
            reverse("preferences"),
            {"date_format": "m_d_yyyy", "time_format": "hh_mm"},
        )
        self.assertRedirects(response, reverse("preferences"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.date_format, "m_d_yyyy")
        self.assertEqual(self.user.time_format, "hh_mm")

    def test_preferences_post_persists_theme(self):
        """POSTing a new theme should persist to the DB."""
        response = self.client.post(reverse("preferences"), {"theme": "light"})
        self.assertRedirects(response, reverse("preferences"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.theme, "light")

    def test_hidden_logo_keeps_an_accessible_home_link(self):
        self.user.logo_style = "hidden"
        self.user.save(update_fields=["logo_style"])

        response = self.client.get(reverse("preferences"))

        self.assertContains(response, 'data-brand-mode="hidden"')
        self.assertContains(response, 'aria-label="Floppy home"')

    def test_preferences_post_rejects_invalid_theme(self):
        """POSTing an invalid theme value should be ignored, not persisted."""
        response = self.client.post(reverse("preferences"), {"theme": "solarized"})
        self.assertRedirects(response, reverse("preferences"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.theme, "system")

    def test_preferences_display_labels_and_logo(self):
        """The display cards expose the simplified labels and logo choice."""
        response = self.client.get(reverse("preferences"))

        self.assertNotContains(response, 'name="logo_style"')
        self.assertContains(response, "System default — Aug 12, 2025 / 12 Aug 2025")
        self.assertContains(response, "System default — 6:45 PM / 18:45")
        self.assertNotContains(response, "System default (locale)")
        self.assertContains(response, "/static/img/floppy-logo.png")
        self.assertNotContains(response, "/static/img/floppy-logo-white.png")

    def test_preferences_uses_monochrome_logo_for_authenticated_user(self):
        """Authenticated branding should follow the saved logo style."""
        self.user.logo_style = "monochrome"
        self.user.save(update_fields=["logo_style"])

        response = self.client.get(reverse("preferences"))

        self.assertContains(response, "/static/img/floppy-logo-white.png")
        self.assertNotContains(response, "/static/img/floppy-logo@2x.png")

    def test_preferences_save_button_is_inside_form(self):
        """Regression test for #345.

        A stray closing </div> in the template caused browsers to implicitly
        close the <form> before the submit button, making Save a silent
        no-op. Django's test client posts form data directly and never
        catches this, so assert on parsed HTML structure instead.
        """
        response = self.client.get(reverse("preferences"))
        soup = BeautifulSoup(response.content, "html.parser")

        forms = soup.find_all("form")
        preferences_form = next(
            (f for f in forms if f.find("input", {"name": "date_format"})),
            None,
        )
        self.assertIsNotNone(preferences_form, "preferences form not found")

        save_button = preferences_form.find("button", {"type": "submit"})
        self.assertIsNotNone(
            save_button,
            "Save button must be inside the preferences <form> or clicking "
            "it silently does nothing",
        )

    def test_tracking_dropdown_labels_are_valid_alpine_expressions(self):
        """Choice labels must not contain template whitespace in x-data."""
        self.user.quick_season_update_mobile = "next_episode"
        self.user.save(update_fields=["quick_season_update_mobile"])

        response = self.client.get(reverse("preferences"))
        soup = BeautifulSoup(response.content, "html.parser")

        quick_input = soup.find("input", {"name": "quick_season_update_mobile"})
        quick_control = quick_input.find_parent("div", class_="relative")
        self.assertIn(
            "selectedValue: 'next_episode', selectedLabel: 'Next Episode button only'",
            quick_control["x-data"],
        )
        self.assertNotIn("selectedLabel: '\n", quick_control["x-data"])

        session_input = soup.find("input", {"name": "session_duration"})
        session_control = session_input.find_parent("div", class_="relative")
        self.assertIn(
            "selectedLabel: '2 weeks'",
            session_control["x-data"],
        )
        self.assertNotIn("selectedLabel: '\n", session_control["x-data"])

    def test_preferences_save_bar_renders_with_dirty_tracking_and_a11y(self):
        """Regression test for #796.

        The save bar must dynamically track dirty state, initialize with clean
        text ('All changes saved'), and expose an aria-live region for accessibility.
        """
        response = self.client.get(reverse("preferences"))
        self.assertContains(response, "formDirtyTracker()")
        self.assertContains(response, 'aria-live="polite"')
        self.assertContains(response, "All changes saved")
        self.assertContains(response, "Your preferences are up to date.")

        soup = BeautifulSoup(response.content, "html.parser")
        preferences_form = soup.find("form", {"x-data": "formDirtyTracker()"})
        self.assertIsNotNone(preferences_form, "formDirtyTracker form not found")
        self.assertEqual(preferences_form.get("@input"), "onFormChange()")
        self.assertEqual(preferences_form.get("@change"), "onFormChange()")
        self.assertEqual(preferences_form.get("@click"), "onFormChange()")

        save_bar = preferences_form.find("div", class_="preferences-actions")
        self.assertIsNotNone(save_bar, "preferences-actions save bar not found")
        live_region = save_bar.find("div", attrs={"aria-live": "polite"})
        self.assertIsNotNone(live_region, "aria-live region not found in save bar")
        self.assertEqual(live_region.get("aria-atomic"), "true")

