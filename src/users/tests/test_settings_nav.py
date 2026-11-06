"""The shared settings navigation stays in step with the Django settings pages."""

from types import SimpleNamespace

from django.test import SimpleTestCase
from django.urls import reverse

from users.settings_nav import settings_view_model


def settings_request(url_name, superuser=False):
    """Build the small request surface the settings model reads."""
    return SimpleNamespace(
        resolver_match=SimpleNamespace(url_name=url_name),
        user=SimpleNamespace(is_superuser=superuser),
    )


class SettingsViewModelTests(SimpleTestCase):
    """Navigation order, URLs, permissions and page mapping."""

    def test_preferences_page_and_navigation_order(self):
        model = settings_view_model(settings_request("preferences"))
        self.assertEqual(model["page"], "settingsPreferences")
        self.assertEqual(model["active"], "preferences")
        self.assertEqual(
            [group["id"] for group in model["navigation"]],
            ["general", "display", "providers-data", "system"],
        )
        self.assertEqual(
            [item["label"] for item in model["navigation"][0]["items"]],
            ["Account", "Preferences", "Notifications"],
        )
        self.assertEqual(
            model["navigation"][0]["items"][1]["url"],
            reverse("preferences"),
        )

    def test_cards_type_still_highlights_media_cards(self):
        model = settings_view_model(settings_request("cards_type"))
        self.assertEqual(model["page"], "settingsCards")
        self.assertEqual(model["active"], "cards")

    def test_users_item_requires_superuser(self):
        regular = settings_view_model(settings_request("about"))
        self.assertFalse(
            [
                item
                for group in regular["navigation"]
                for item in group["items"]
                if item["id"] == "users"
            ]
        )
        self.assertFalse(regular["permissions"]["superuser"])

        superuser = settings_view_model(settings_request("about", superuser=True))
        users = next(
            item
            for group in superuser["navigation"]
            for item in group["items"]
            if item["id"] == "users"
        )
        self.assertEqual(users["permission"], "superuser")
        self.assertTrue(superuser["permissions"]["superuser"])

    def test_icons_are_parsed_shapes_not_markup(self):
        model = settings_view_model(settings_request("account"))
        icon = model["navigation"][0]["items"][0]["iconSpec"]
        self.assertIn("viewBox", icon)
        self.assertTrue(icon["children"])
        self.assertNotIn("<svg", str(icon))

    def test_provider_detail_highlights_providers(self):
        model = settings_view_model(settings_request("provider_detail"))
        self.assertEqual(model["page"], "providers")
        self.assertEqual(model["active"], "providers")
