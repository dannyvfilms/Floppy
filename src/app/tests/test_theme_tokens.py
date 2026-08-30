import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from users.appearance import THEME_PRESETS
from users.models import ThemeChoices

# Tailwind's stock `dark:` variant compiles to `@media (prefers-color-scheme:
# dark)`. Floppy instead resolves the theme server-side and stamps `light` or
# `dark` on <html> from user.theme, so the two disagree for anyone whose chosen
# theme differs from their OS setting. Colours must come from the --color-*
# tokens, which are defined for all four combinations in input.css.
DARK_VARIANT = re.compile(r'(?:^|[\s"\'])dark:')

# Roles that used to be spelled as raw palette utilities. Each has a token that
# resolves per theme, so a literal here renders the same colour on both canvases
# and fails contrast on one of them.
# Assembled from parts on purpose. Tailwind scans this directory for class
# names, so a literal here would put the banned utility back into main.css.
BANNED_TEXT_UTILITIES = (
    "text-indigo-" + "400",
    "text-gray-" + "500",
    "placeholder-gray-" + "500",
)


def _template_files():
    return sorted(Path(settings.BASE_DIR).joinpath("templates").rglob("*.html"))


class ThemeTokenContractTests(SimpleTestCase):
    """Keep theme-dependent colour out of hardcoded palette utilities."""

    def test_templates_avoid_the_prefers_color_scheme_dark_variant(self):
        """`dark:` tracks the OS, not the user's chosen theme, so it must not appear."""
        offenders = []
        for path in _template_files():
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if DARK_VARIANT.search(line):
                    offenders.append(f"{path.name}:{number}")

        self.assertEqual(
            offenders,
            [],
            "Use a --color-* token instead of the dark: variant; it ignores "
            f"the html.light / html.dark class the app sets. Found: {offenders}",
        )

    def test_templates_use_tokens_for_theme_dependent_text(self):
        """Link and muted-copy colours must resolve through --color-* tokens."""
        offenders = []
        for path in _template_files():
            content = path.read_text(encoding="utf-8")
            for utility in BANNED_TEXT_UTILITIES:
                if re.search(rf"(?<![\w:.-]){re.escape(utility)}(?![\w-])", content):
                    offenders.append(f"{path.name}: {utility}")

        self.assertEqual(
            offenders,
            [],
            "Replace with text-[var(--color-link)] or "
            f"text-[var(--color-text-muted)]. Found: {offenders}",
        )

    def test_system_light_tokens_exclude_every_explicit_theme(self):
        """An OS light preference must not override a saved theme preset."""
        css = Path(settings.BASE_DIR, "static", "css", "input.css").read_text(
            encoding="utf-8"
        )
        explicit_themes = [theme for theme in THEME_PRESETS if theme != "system"]
        selector = ":root" + "".join(
            f":not(.{theme})" for theme in explicit_themes
        )

        self.assertIn(selector, css)

    def test_curated_theme_registry_matches_persisted_choices(self):
        """Every displayed preset must be accepted and persistable."""
        expected = {
            "catppuccin_mocha",
            "dracula",
            "nord",
            "gruvbox",
            "oled",
            "plex",
        }

        self.assertLessEqual(expected, set(THEME_PRESETS))
        self.assertEqual(set(THEME_PRESETS), set(ThemeChoices.values))

    def test_header_toggle_treats_explicit_presets_as_dark(self):
        """A light OS must not make the toggle misread a dark preset as light."""
        template = Path(settings.BASE_DIR, "templates", "base.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("(!hasExplicitTheme && systemPrefersLight)", template)
        self.assertIn("html.classList.remove(...explicitThemes)", template)

    def test_every_explicit_theme_defines_shape_and_motion(self):
        """Radius and movement are part of each preset's identity."""
        css = Path(settings.BASE_DIR, "static", "css", "input.css").read_text(
            encoding="utf-8"
        )

        for theme in (theme for theme in THEME_PRESETS if theme != "system"):
            block = re.search(rf"html\.{theme}\s*\{{(?P<body>.*?)\n\}}", css, re.DOTALL)
            self.assertIsNotNone(block, theme)
            for token in (
                "--theme-radius",
                "--motion-duration",
                "--motion-distance",
                "--motion-ease",
            ):
                self.assertIn(token, block.group("body"), f"{theme}: {token}")

    def test_motion_has_an_accessibility_killswitch(self):
        css = Path(settings.BASE_DIR, "static", "css", "input.css").read_text(
            encoding="utf-8"
        )

        self.assertIn("@media (prefers-reduced-motion: reduce)", css)
        self.assertIn("animation-duration: 0.01ms", css)

    def test_sidebar_logo_keeps_its_full_brand_dimensions(self):
        css = Path(settings.BASE_DIR, "static", "css", "input.css").read_text(
            encoding="utf-8"
        )
        logo_rule = re.search(
            r"\.brand-built-in-image\s*\{(?P<body>.*?)\n\}",
            css,
            re.DOTALL,
        )

        self.assertIsNotNone(logo_rule)
        self.assertIn("width: 9.875rem", logo_rule.group("body"))
        self.assertIn("height: 3rem", logo_rule.group("body"))
        self.assertIn("flex-shrink: 0", logo_rule.group("body"))

    def test_home_rows_reserve_hover_lift_clearance(self):
        css = Path(settings.BASE_DIR, "static", "css", "input.css").read_text(
            encoding="utf-8"
        )
        row_rule = re.search(
            r"\.home-row-scrollbar-hidden\s*\{(?P<body>.*?)\n\}",
            css,
            re.DOTALL,
        )

        self.assertIsNotNone(row_rule)
        self.assertIn("var(--motion-distance)", row_rule.group("body"))
        self.assertIn(
            "padding-top: var(--home-row-hover-clearance)",
            row_rule.group("body"),
        )
        self.assertNotIn("padding-left:", row_rule.group("body"))
        self.assertNotIn("margin-left:", row_rule.group("body"))

    def test_media_card_hover_outline_stays_inside_above_progress(self):
        css = Path(settings.BASE_DIR, "static", "css", "input.css").read_text(
            encoding="utf-8"
        )
        template = Path(
            settings.BASE_DIR, "templates", "app", "components", "media_card.html"
        ).read_text(encoding="utf-8")
        outline_rule = re.search(
            r"\.media-card-hover-outline::after\s*\{(?P<body>.*?)\n\}",
            css,
            re.DOTALL,
        )

        self.assertIn("media-card-hover-outline", template)
        self.assertNotIn("hover:ring-2 hover:ring-indigo-500", template)
        self.assertIsNotNone(outline_rule)
        self.assertIn("inset: 0", outline_rule.group("body"))
        self.assertIn("z-index: 30", outline_rule.group("body"))

    def test_completed_appearance_animations_release_fixed_modals(self):
        css = Path(settings.BASE_DIR, "static", "css", "input.css").read_text(
            encoding="utf-8"
        )

        for animation in ("theme-reveal", "theme-soft-pop"):
            keyframes = re.search(
                rf"@keyframes {animation}\s*\{{(?P<body>.*?)\n\}}",
                css,
                re.DOTALL,
            )
            self.assertIsNotNone(keyframes, animation)
            self.assertIn("transform: none", keyframes.group("body"), animation)

    def test_fullscreen_overlays_are_portaled_to_the_viewport(self):
        base = Path(settings.BASE_DIR, "templates", "base.html").read_text(
            encoding="utf-8"
        )
        portal = Path(
            settings.BASE_DIR, "static", "js", "modalPortal.js"
        ).read_text(encoding="utf-8")
        modal_handler = Path(
            settings.BASE_DIR, "static", "js", "mediaStatusDateHandler.js"
        ).read_text(encoding="utf-8")

        self.assertIn("js/modalPortal.js", base)
        self.assertIn('document.querySelectorAll(".fixed.inset-0")', portal)
        self.assertIn("Alpine.closestDataStack(overlay)", portal)
        self.assertIn("overlay._modalDataStack", portal)
        self.assertIn("overlay._modalOriginParent", portal)
        self.assertIn("overlay._modalStateHost", portal)
        self.assertIn("overlay._x_dataStack", portal)
        self.assertIn("document.body.appendChild(overlay)", portal)
        self.assertIn("htmx:afterSettle", portal)
        self.assertIn("node._modalDataStack", modal_handler)
        self.assertIn("node._modalStateHost", modal_handler)
        self.assertIn("stateKey in data", modal_handler)
        self.assertIn("stateTarget.data[stateTarget.stateKey] = isOpen", modal_handler)
        self.assertIn("overlay._modalOriginParent.appendChild(overlay)", modal_handler)
        self.assertIn('overlay.style.display = "none"', modal_handler)
        self.assertIn("overlay.remove()", modal_handler)

    def test_home_screen_row_controls_wrap_inside_their_panel(self):
        template = Path(
            settings.BASE_DIR, "templates", "users", "home_screen.html"
        ).read_text(encoding="utf-8")

        self.assertIn("min-h-10", template)
        self.assertIn("flex-wrap", template)
        self.assertIn("min-w-0 flex-1 flex-wrap", template)

    def test_episode_picker_truncates_long_titles(self):
        template = Path(
            settings.BASE_DIR, "templates", "app", "episode_details.html"
        ).read_text(encoding="utf-8")

        self.assertIn('class="relative min-w-0 flex-1 md:max-w-xs"', template)
        self.assertIn('class="block min-w-0 flex-1 truncate text-sm font-medium"', template)
