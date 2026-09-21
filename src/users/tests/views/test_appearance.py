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

from app.models import ApplicationSettings
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

    def test_appearance_rejects_long_wordmark_without_saving_theme(self):
        self.client.post(
            reverse("appearance"),
            {
                "theme": "glass",
                "custom_theme": "{}",
                "detail_layouts": "{}",
                "logo_style": "text",
                "logo_text": "M" * 21,
            },
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.logo_style, "colorful")
        self.assertEqual(self.user.theme, "system")

    def test_existing_long_wordmark_survives_unrelated_appearance_save(self):
        previous_name = "My Very Long Media Shelf Name"
        self.user.logo_style = "text"
        self.user.logo_text = previous_name
        self.user.save(update_fields=["logo_style", "logo_text"])

        self.client.post(
            reverse("appearance"),
            {
                "theme": "glass",
                "custom_theme": "{}",
                "detail_layouts": "{}",
                "logo_style": "text",
                "logo_text": previous_name,
            },
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.logo_text, previous_name)
        self.assertEqual(self.user.theme, "glass")

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

    def test_custom_logo_upload_has_a_live_preview(self):
        response = self.client.get(reverse("appearance"))

        self.assertContains(response, '@change="previewLogoUpload($event)"')
        self.assertContains(response, ':src="customLogoPreview"')
        self.assertContains(response, "previewLogoUpload(event)")

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
        self.assertLessEqual(
            len(self.user.custom_logo_data), branding.MAX_LOGO_DATA_URL_LENGTH
        )
        home = self.client.get(reverse("home"))
        self.assertContains(home, 'data-brand-mode="custom"')
        self.assertContains(home, f'src="{self.user.custom_logo_data}"')

    def test_text_fill_is_saved_and_rendered_in_navigation(self):
        response = self.client.post(
            reverse("appearance"),
            {
                "theme": "system",
                "custom_theme": "{}",
                "detail_layouts": "{}",
                "logo_style": "text",
                "logo_text": "Media Shelf",
                "logo_text_fill": "custom_gradient",
                "logo_text_color_start": "#e8f8ff",
                "logo_text_color_end": "#638bff",
            },
        )

        self.assertRedirects(response, reverse("appearance"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.logo_text_fill, "custom_gradient")
        self.assertEqual(self.user.logo_text_color_start, "#e8f8ff")
        self.assertEqual(self.user.logo_text_color_end, "#638bff")
        home = self.client.get(reverse("home"))
        self.assertContains(home, 'data-brand-fill="custom_gradient"')
        self.assertContains(home, "--brand-color-start: #e8f8ff")
        self.assertContains(home, "--brand-color-end: #638bff")

    def test_custom_gradient_defaults_are_readable_on_light_theme(self):
        self.assertEqual(self.user.logo_text_color_start, "#1f2937")
        self.assertEqual(self.user.logo_text_color_end, "#2563eb")

    def test_invalid_text_fill_rejects_entire_appearance_post(self):
        response = self.client.post(
            reverse("appearance"),
            {
                "theme": "glass",
                "custom_theme": "{}",
                "detail_layouts": "{}",
                "logo_style": "text",
                "logo_text_fill": "custom_gradient",
                "logo_text_color_start": "red; background:url(https://example.test)",
                "logo_text_color_end": "#638bff",
            },
        )

        self.assertRedirects(response, reverse("appearance"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.theme, "system")
        self.assertEqual(self.user.logo_style, "colorful")

    def test_superuser_can_publish_a_snapshot_to_the_sign_in_page(self):
        self.user.is_superuser = True
        self.user.logo_style = "text"
        self.user.logo_text = "Media Shelf"
        self.user.save(update_fields=["is_superuser", "logo_style", "logo_text"])

        response = self.client.post(
            reverse("appearance"), {"public_branding_action": "publish"}
        )

        self.assertRedirects(response, reverse("appearance"))
        published = ApplicationSettings.objects.get(pk=1).public_branding
        self.assertEqual(published["logo_text"], "Media Shelf")

        self.client.logout()
        sign_in = self.client.get(reverse("account_login"))
        self.assertContains(sign_in, 'data-brand-mode="text"')
        self.assertContains(sign_in, "Media Shelf")

        self.user.logo_text = "Private rename"
        self.user.save(update_fields=["logo_text"])
        sign_in = self.client.get(reverse("account_login"))
        self.assertContains(sign_in, "Media Shelf")
        self.assertNotContains(sign_in, "Private rename")

    def test_instance_owner_save_also_publishes_the_sign_in_appearance(self):
        response = self.client.post(
            reverse("appearance"),
            {
                "theme": "dracula",
                "custom_theme": "{}",
                "detail_layouts": "{}",
                "logo_style": "text",
                "logo_text": "Media Shelf",
            },
            follow=True,
        )

        published = ApplicationSettings.objects.get(pk=1).public_branding
        self.assertEqual(published["theme"], "dracula")
        self.assertEqual(published["logo_style"], "text")
        self.assertEqual(published["logo_text"], "Media Shelf")
        self.assertContains(response, "Appearance and sign-in updated")
        self.assertNotContains(response, "Publish sign-in appearance")

    def test_publish_saves_submitted_branding_before_snapshotting_it(self):
        self.user.is_superuser = True
        self.user.logo_style = "custom"
        self.user.logo_text = "Old branding"
        self.user.custom_logo_data = "data:image/webp;base64,UklGRg=="
        self.user.save(
            update_fields=[
                "is_superuser",
                "logo_style",
                "logo_text",
                "custom_logo_data",
            ]
        )

        response = self.client.post(
            reverse("appearance"),
            {
                "public_branding_action": "publish",
                "theme": "system",
                "custom_theme": "{}",
                "detail_layouts": "{}",
                "logo_style": "text",
                "logo_text": "New branding",
            },
            follow=True,
        )

        self.user.refresh_from_db()
        published = ApplicationSettings.objects.get(pk=1).public_branding
        self.assertEqual(self.user.logo_style, "text")
        self.assertEqual(self.user.logo_text, "New branding")
        self.assertEqual(published["logo_style"], "text")
        self.assertEqual(published["logo_text"], "New branding")
        self.assertContains(response, "Sign-in branding updated")
        self.assertNotContains(response, "Appearance updated")

    def test_publish_applies_the_submitted_theme_to_the_sign_in_page(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])

        self.client.post(
            reverse("appearance"),
            {
                "public_branding_action": "publish",
                "theme": "dracula",
                "custom_theme": "{}",
                "detail_layouts": "{}",
                "logo_style": "text",
                "logo_text": "Media Shelf",
            },
        )
        self.client.logout()

        sign_in = self.client.get(reverse("account_login"))
        self.assertContains(sign_in, 'class="dracula bg-[var(--color-page-bg)]"')
        self.assertContains(sign_in, 'data-brand-mode="text"')
        self.assertContains(sign_in, "Media Shelf")

    def test_publish_applies_custom_theme_tokens_to_the_sign_in_page(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])

        self.client.post(
            reverse("appearance"),
            {
                "public_branding_action": "publish",
                "theme": "custom",
                "custom_theme": json.dumps(
                    {"page_bg": "#112233", "accent": "#abcdef"}
                ),
                "detail_layouts": "{}",
                "logo_style": "text",
                "logo_text": "Media Shelf",
            },
        )
        self.client.logout()

        sign_in = self.client.get(reverse("account_login"))
        self.assertContains(sign_in, 'class="custom bg-[var(--color-page-bg)]"')
        self.assertContains(sign_in, "--color-page-bg: #112233")
        self.assertContains(sign_in, "--color-accent: #abcdef")

    def test_existing_long_wordmark_can_still_be_published(self):
        previous_name = "My Very Long Media Shelf Name"
        self.user.is_superuser = True
        self.user.logo_style = "text"
        self.user.logo_text = previous_name
        self.user.save(update_fields=["is_superuser", "logo_style", "logo_text"])

        self.client.post(reverse("appearance"), {"public_branding_action": "publish"})
        self.client.logout()

        sign_in = self.client.get(reverse("account_login"))
        self.assertContains(sign_in, previous_name)

    def test_published_image_reaches_sign_in_without_changing_other_users(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        source = BytesIO()
        Image.new("RGBA", (400, 100), (30, 80, 220, 255)).save(source, "PNG")
        upload = SimpleUploadedFile("brand.png", source.getvalue(), content_type="image/png")
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
        self.client.post(reverse("appearance"), {"public_branding_action": "publish"})
        self.client.logout()

        sign_in = self.client.get(reverse("account_login"))
        self.assertContains(sign_in, 'data-brand-mode="custom"')
        self.assertContains(sign_in, f'src="{self.user.custom_logo_data}"')

        other = get_user_model().objects.create_user(username="other", password="testpass123")
        self.client.force_login(other)
        home = self.client.get(reverse("home"))
        self.assertContains(home, 'data-brand-mode="colorful"')
        self.assertNotContains(home, self.user.custom_logo_data)

    def test_superuser_can_restore_original_public_branding(self):
        self.user.is_superuser = True
        self.user.logo_style = "text"
        self.user.logo_text = "Media Shelf"
        self.user.save(update_fields=["is_superuser", "logo_style", "logo_text"])
        self.client.post(reverse("appearance"), {"public_branding_action": "publish"})

        self.client.post(reverse("appearance"), {"public_branding_action": "reset"})

        self.assertEqual(ApplicationSettings.objects.get(pk=1).public_branding, {})
        self.client.logout()
        sign_in = self.client.get(reverse("account_login"))
        self.assertContains(sign_in, 'data-brand-mode="colorful"')
        self.assertNotContains(sign_in, "Media Shelf")

    def test_non_superuser_cannot_change_public_branding(self):
        other = get_user_model().objects.create_user(
            username="other-user",
            password="testpass123",
        )
        self.client.force_login(other)

        response = self.client.post(
            reverse("appearance"), {"public_branding_action": "publish"}
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ApplicationSettings.objects.filter(pk=1).exists())

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

    def test_explicit_preset_is_rendered_on_the_root_element(self):
        self.user.theme = "glass"
        self.user.save(update_fields=["theme"])

        response = self.client.get(reverse("appearance"))

        self.assertContains(
            response,
            'class="glass bg-[var(--color-page-bg)]"',
        )

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
    def test_wordmark_is_limited_to_twenty_characters(self):
        self.assertEqual(branding.normalize_logo_text("M" * 20), "M" * 20)
        with self.assertRaisesMessage(ValidationError, "20 characters"):
            branding.normalize_logo_text("M" * 21)

    def test_logo_dimensions_are_rejected_before_pixel_data_is_loaded(self):
        upload = SimpleUploadedFile("brand.png", b"png", content_type="image/png")
        source = MagicMock(format="PNG", width=8192, height=8192)
        source.__enter__.return_value = source

        with (
            patch.object(Image, "open", return_value=source),
            self.assertRaisesMessage(
                ValidationError,
                "Logo image dimensions are too large.",
            ),
        ):
            branding.normalize_logo_upload(upload)

        source.load.assert_not_called()
