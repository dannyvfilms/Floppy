import json
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from PIL import Image

from users import branding
from users.appearance import DETAIL_LAYOUT_FAMILIES, THEME_PRESETS
from users.models import LogoStyleChoices, ThemeChoices
from users.templatetags.user_tags import detail_section_attrs


class AppearanceViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="appearance-user",
            password="testpass123",
        )
        self.client.force_login(self.user)

    def test_appearance_exposes_presets_and_distinct_detail_families(self):
        response = self.client.get(reverse("appearance"))

        self.assertContains(response, "Glass cinema")
        self.assertContains(response, "Catppuccin Mocha")
        self.assertContains(response, "Dracula")
        self.assertContains(response, "Nord")
        self.assertContains(response, "Gruvbox")
        self.assertContains(response, "OLED")
        self.assertContains(response, "Plex inspired")
        self.assertContains(response, "Projector")
        self.assertContains(response, "Video store")
        self.assertContains(response, "Custom palette")
        self.assertContains(response, "Episodes")
        self.assertContains(response, "Music albums")
        self.assertNotEqual(
            DETAIL_LAYOUT_FAMILIES["episode"]["zones"],
            DETAIL_LAYOUT_FAMILIES["music_album"]["zones"],
        )
        self.assertEqual(set(THEME_PRESETS), set(ThemeChoices.values))

    def test_appearance_owns_every_logo_control(self):
        response = self.client.get(reverse("appearance"))

        self.assertContains(response, 'enctype="multipart/form-data"')
        self.assertContains(response, 'name="logo_style"')
        for label in ("Original color", "Monochrome", "Text", "Custom image", "Hidden"):
            self.assertContains(response, label)
        self.assertEqual(
            set(LogoStyleChoices.values),
            {"colorful", "monochrome", "text", "custom", "hidden"},
        )

        preferences = self.client.get(reverse("preferences"))
        self.assertNotContains(preferences, 'name="logo_style"')

    def test_appearance_persists_text_wordmark(self):
        response = self.client.post(
            reverse("appearance"),
            {
                "theme": "system",
                "custom_theme": "{}",
                "detail_layouts": "{}",
                "logo_style": "text",
                "logo_text": "Nicolas Floppy",
            },
        )

        self.assertRedirects(response, reverse("appearance"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.logo_style, "text")
        self.assertEqual(self.user.logo_text, "Nicolas Floppy")

    def test_appearance_persists_text_typography(self):
        response = self.client.post(
            reverse("appearance"),
            {
                "theme": "system",
                "custom_theme": "{}",
                "detail_layouts": "{}",
                "logo_style": "text",
                "logo_text": "Floppy Cinema",
                "logo_text_font": "serif",
                "logo_text_size": "32",
                "logo_text_weight": "600",
                "logo_text_spacing": "3",
            },
        )

        self.assertRedirects(response, reverse("appearance"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.logo_text_font, "serif")
        self.assertEqual(self.user.logo_text_size, 32)
        self.assertEqual(self.user.logo_text_weight, 600)
        self.assertEqual(self.user.logo_text_spacing, 3)

        home = self.client.get(reverse("home"))
        self.assertContains(home, 'data-brand-font="serif"')
        self.assertContains(home, "--brand-font-size: 32px")
        self.assertContains(home, "--brand-font-weight: 600")
        self.assertContains(home, "--brand-letter-spacing: 3px")

    def test_appearance_rejects_invalid_text_typography_without_partial_save(self):
        self.client.post(
            reverse("appearance"),
            {
                "theme": "glass",
                "custom_theme": "{}",
                "detail_layouts": "{}",
                "logo_style": "text",
                "logo_text_font": "remote-font",
                "logo_text_size": "200",
                "logo_text_weight": "950",
                "logo_text_spacing": "20",
            },
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.theme, "system")
        self.assertEqual(self.user.logo_text_font, "display")
        self.assertEqual(self.user.logo_text_size, 23)

    def test_branding_is_centered_and_text_controls_are_conditional(self):
        response = self.client.get(reverse("appearance"))
        css = (Path(settings.BASE_DIR) / "static" / "css" / "input.css").read_text(
            encoding="utf-8"
        )
        public_template = (
            Path(settings.BASE_DIR) / "templates" / "base_public.html"
        ).read_text(encoding="utf-8")

        for field in (
            "logo_text_font",
            "logo_text_size",
            "logo_text_weight",
            "logo_text_spacing",
        ):
            self.assertContains(response, f'name="{field}"')
        self.assertContains(response, "logoStyle === 'text'")
        self.assertContains(response, "sidebar-brand-slot")
        self.assertNotIn("sidebar-brand-slot", public_template)
        self.assertIn("justify-content: center;", css)
        self.assertIn("transform-origin: center;", css)

    def test_appearance_normalizes_custom_logo_upload(self):
        source = BytesIO()
        Image.new("RGBA", (900, 300), (255, 0, 120, 180)).save(source, "PNG")
        upload = SimpleUploadedFile(
            "brand.png",
            source.getvalue(),
            content_type="image/png",
        )

        response = self.client.post(
            reverse("appearance"),
            {
                "theme": "system",
                "custom_theme": "{}",
                "detail_layouts": "{}",
                "logo_style": "custom",
                "logo_upload": upload,
            },
        )

        self.assertRedirects(response, reverse("appearance"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.logo_style, "custom")
        self.assertTrue(self.user.custom_logo_data.startswith("data:image/webp;base64,"))

    def test_appearance_rejects_non_image_custom_logo(self):
        upload = SimpleUploadedFile(
            "brand.svg",
            b"<svg onload=alert(1)></svg>",
            content_type="image/svg+xml",
        )

        self.client.post(
            reverse("appearance"),
            {
                "theme": "system",
                "custom_theme": "{}",
                "detail_layouts": "{}",
                "logo_style": "custom",
                "logo_upload": upload,
            },
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.logo_style, "colorful")
        self.assertEqual(self.user.custom_logo_data, "")

    def test_appearance_rejects_unknown_logo_style_without_partial_save(self):
        self.client.post(
            reverse("appearance"),
            {
                "theme": "glass",
                "custom_theme": "{}",
                "detail_layouts": "{}",
                "logo_style": "neon",
            },
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.logo_style, "colorful")
        self.assertEqual(self.user.theme, "system")

    def test_appearance_serializes_editor_data_once(self):
        response = self.client.get(reverse("appearance"))

        self.assertIsInstance(response.context["custom_theme_json"], dict)
        self.assertIsInstance(response.context["detail_layout_families_json"], dict)
        self.assertIsInstance(response.context["detail_layouts_json"], dict)
        self.assertNotContains(response, "overflow-x-auto")

    def test_appearance_persists_custom_palette_and_ordered_sections(self):
        layouts = {
            "media": {
                "sidebar": ["details", "genres"],
                "content": ["cast", "notes"],
            }
        }
        palette = {
            "page_bg": "#10141f",
            "surface": "#1b2233",
            "panel": "#202940",
            "text": "#f6f1df",
            "muted": "#adb7cc",
            "accent": "#ffb454",
            "radius": 18,
            "blur": 16,
            "surface_opacity": 72,
        }

        response = self.client.post(
            reverse("appearance"),
            {
                "theme": "custom",
                "custom_theme": json.dumps(palette),
                "detail_layouts": json.dumps(layouts),
            },
        )

        self.assertRedirects(response, reverse("appearance"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.theme, "custom")
        self.assertEqual(self.user.custom_theme, palette)
        self.assertEqual(self.user.detail_page_layouts["media"], layouts["media"])

    def test_appearance_rejects_invalid_custom_effect_values(self):
        response = self.client.post(
            reverse("appearance"),
            {
                "theme": "custom",
                "custom_theme": json.dumps({"radius": "20px; color: red"}),
                "detail_layouts": "{}",
            },
        )

        self.assertRedirects(response, reverse("appearance"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.theme, "system")

    def test_appearance_rejects_unknown_sections_without_partial_save(self):
        response = self.client.post(
            reverse("appearance"),
            {
                "theme": "projector",
                "custom_theme": "{}",
                "detail_layouts": json.dumps(
                    {"episode": {"content": ["notes", "not-a-section"]}}
                ),
            },
        )

        self.assertRedirects(response, reverse("appearance"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.theme, "system")
        self.assertEqual(self.user.detail_page_layouts, {})

    def test_custom_theme_is_rendered_as_safe_css_variables(self):
        self.user.theme = "custom"
        self.user.custom_theme = {
            "page_bg": "#10141f",
            "accent": "red; background:url(https://example.test)",
            "radius": 18,
            "blur": 16,
            "surface_opacity": 72,
        }
        self.user.save(update_fields=["theme", "custom_theme"])

        response = self.client.get(reverse("preferences"))

        self.assertContains(response, "--color-page-bg: #10141f")
        self.assertContains(response, "--theme-radius: 18px")
        self.assertContains(response, "--theme-blur: 16px")
        self.assertContains(response, "--theme-surface-opacity: 72%")
        self.assertNotContains(response, "background:url")

    def test_detail_section_attributes_apply_visibility_and_order(self):
        self.user.detail_page_layouts = {
            "episode": {"content": ["crew", "notes"]}
        }

        self.assertIn(
            'data-detail-section="crew" style="order: 0"',
            str(detail_section_attrs(self.user, "episode", "content", "crew")),
        )
        self.assertIn(
            'data-detail-section="notes" style="order: 1"',
            str(detail_section_attrs(self.user, "episode", "content", "notes")),
        )
        self.assertIn(
            'data-detail-section="cast" hidden',
            str(detail_section_attrs(self.user, "episode", "content", "cast")),
        )

    def test_comic_publishers_are_visible_by_default(self):
        attributes = str(
            detail_section_attrs(self.user, "comic", "sidebar", "studios")
        )

        self.assertIn('data-detail-section="studios" style="order:', attributes)
        self.assertNotIn("hidden", attributes)


class BrandingValidationTests(SimpleTestCase):
    def test_logo_dimensions_are_rejected_before_pixel_data_is_loaded(self):
        upload = SimpleUploadedFile("brand.png", b"png", content_type="image/png")
        source = MagicMock(format="PNG", width=8192, height=8192)
        source.__enter__.return_value = source

        with (
            patch.object(branding.Image, "open", return_value=source),
            self.assertRaisesMessage(
                ValidationError,
                "Logo image dimensions are too large.",
            ),
        ):
            branding.normalize_logo_upload(upload)

        source.load.assert_not_called()
