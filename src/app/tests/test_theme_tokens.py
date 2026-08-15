import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

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
            for number, line in enumerate(path.read_text().splitlines(), start=1):
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
            content = path.read_text()
            for utility in BANNED_TEXT_UTILITIES:
                if re.search(rf"(?<![\w:.-]){re.escape(utility)}(?![\w-])", content):
                    offenders.append(f"{path.name}: {utility}")

        self.assertEqual(
            offenders,
            [],
            "Replace with text-[var(--color-link)] or "
            f"text-[var(--color-text-muted)]. Found: {offenders}",
        )
