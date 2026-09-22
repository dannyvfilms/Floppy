from types import SimpleNamespace

from django.test import SimpleTestCase

from users.media_type_chips import (
    media_type_chip_preferences,
    normalize_media_type_chip_colors,
)


class MediaTypeChipPreferenceTests(SimpleTestCase):
    def test_normalize_colors_keeps_only_known_safe_values(self):
        self.assertEqual(
            normalize_media_type_chip_colors(
                {
                    "movie": "#123abc",
                    "anime": "#ABCDEF",
                    "book": "javascript:alert(1)",
                    "unknown": "#123456",
                    "season": "#123456",
                }
            ),
            {"movie": "#123ABC", "anime": "#ABCDEF"},
        )

    def test_preferences_resolve_color_contrast_and_style_safely(self):
        user = SimpleNamespace(
            home_media_type_chip_colors={"movie": "#F0F0F0"},
            home_media_type_chip_style="outline",
        )

        self.assertEqual(
            media_type_chip_preferences(user, "movie"),
            {
                "color": "#F0F0F0",
                "contrast": "#111827",
                "style": "outline",
            },
        )

    def test_preferences_fall_back_to_safe_style_and_light_text(self):
        user = SimpleNamespace(
            home_media_type_chip_colors={"movie": "#101010"},
            home_media_type_chip_style="not-a-style",
        )

        self.assertEqual(
            media_type_chip_preferences(user, "movie"),
            {
                "color": "#101010",
                "contrast": "#FFFFFF",
                "style": "soft",
            },
        )
