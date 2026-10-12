import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class StaticCssContractTests(SimpleTestCase):
    """Protect the canonical compiled CSS path from drifting."""

    def setUp(self):
        """Resolve the shared asset paths used by the regression checks."""
        base_dir = Path(settings.BASE_DIR)
        self.tailwind_css_path = base_dir / "static" / "css" / "tailwind.css"
        self.base_template_path = base_dir / "templates" / "base.html"
        self.base_public_template_path = base_dir / "templates" / "base_public.html"
        self.service_worker_path = base_dir / "static" / "js" / "serviceworker.js"

    def test_source_static_tree_does_not_include_tailwind_css(self):
        """The source static tree should not ship the retired duplicate CSS file."""
        self.assertFalse(
            self.tailwind_css_path.exists(),
            (
                "static/css/tailwind.css should not exist; "
                "use static/css/main.css instead."
            ),
        )

    def test_shared_templates_and_service_worker_reference_main_css_only(self):
        """Shared entrypoints should reference main.css and never the retired path."""
        for path in (
            self.base_template_path,
            self.base_public_template_path,
            self.service_worker_path,
        ):
            content = path.read_text(encoding="utf-8")
            relative_path = path.relative_to(settings.BASE_DIR).as_posix()

            self.assertIn(
                "css/main.css",
                content,
                f"{relative_path} should reference css/main.css.",
            )
            self.assertNotIn(
                "css/tailwind.css",
                content,
                f"{relative_path} should not reference css/tailwind.css.",
            )


class IconSizingContractTests(SimpleTestCase):
    """Keep inline icons from rendering at container size (#442).

    WebKit stretches an <svg> that only carries a viewBox to fill its parent
    rather than falling back to a fixed intrinsic box, so an icon with no size
    renders enormous on iOS while looking merely wrong elsewhere.
    """

    SVG_TAG = re.compile(r"<svg\b[^>]*>", re.DOTALL)
    SIZE_CLASS = re.compile(r'class="[^"]*\b(?:w-|h-|size-)')

    def setUp(self):
        """Resolve the template tree scanned by the checks below."""
        self.templates_dir = Path(settings.BASE_DIR) / "templates"

    def test_icon_templates_declare_an_intrinsic_size_fallback(self):
        """Every icon partial keeps its width/height="1em" fallback."""
        for path in sorted((self.templates_dir / "app" / "icons").rglob("*.svg")):
            content = path.read_text(encoding="utf-8")
            relative_path = path.relative_to(settings.BASE_DIR).as_posix()

            self.assertIn(
                'width="1em"',
                content,
                f'{relative_path} must keep width="1em" so a call site that '
                "omits a size utility still renders a text-sized icon.",
            )
            self.assertIn('height="1em"', content, f"{relative_path} needs height.")
            self.assertIn(
                'class="{{ classes }}"',
                content,
                f"{relative_path} must expose a classes hook so call sites can "
                "size it.",
            )

    def test_inline_svgs_are_sized(self):
        """Inline <svg> markup carries either a size attribute or a size class."""
        unsized = []
        for path in sorted(self.templates_dir.rglob("*.html")):
            content = path.read_text(encoding="utf-8")
            for match in self.SVG_TAG.finditer(content):
                tag = match.group(0)
                if "width=" in tag or self.SIZE_CLASS.search(tag):
                    continue
                line = content[: match.start()].count("\n") + 1
                unsized.append(
                    f"{path.relative_to(settings.BASE_DIR).as_posix()}:{line}"
                )

        self.assertEqual(
            unsized,
            [],
            "Inline <svg> needs a width/height attribute or a w-/h-/size- "
            f"class or it fills its container on iOS: {unsized}",
        )


class PhoneLayoutCssContractTests(SimpleTestCase):
    """Phone and unfolded-phone rules that only exist in CSS.

    There is no browser in CI, so these pin the rules a simulator pass asked for.
    Each pattern must be in input.css and in the committed main.css, so editing
    the source without rebuilding the output fails here too.
    """

    RULES = {
        "hero logo centres on the content box, not the full-bleed hero": (
            r"left: calc\(50% \+ \(var\(--hero-gutter-l\) - var\(--hero-gutter-r\)\) / 2\)"
        ),
        "touch screens share phone card widths in either orientation": (
            r"\(pointer: coarse\) and \(max-width: 1600px\) and "
            r"\(max-height: 1100px\)"
        ),
        "compact cards keep the narrow phone size": r"--card-cap: 6\.75rem",
        "comfortable cards keep a fixed size": r"--card-cap: 10\.5rem",
        "grid tracks are fixed at the cap, not stretched with 1fr": (
            r"repeat\(auto-fill, min\(calc\([^;]*var\(--card-cap\)\)\) !important"
        ),
        "rating chips sit below the action row on phones": (
            r'"actions actions"\s+"chips chips"\s+"synopsis synopsis"'
        ),
        "chip row fades only on the side that has more to scroll to": (
            r"\.detail-score-card-row--fade-left \{\s+--row-fade-left: transparent"
        ),
        "phone chip cards only reveal on hover where hover exists": (
            r"@media \(hover: hover\) \{\s+:is\(\.detail-carousel-grid, \.detail-flat-top\) "
            r"\.detail-provider-score-card\.group:hover"
        ),
        "unfolded portrait keeps the poster beside the info": (
            r"@media \(min-width: 600px\) and \(max-width: 767\.98px\)"
        ),
    }

    def test_rules_are_in_source_and_build(self):
        css_dir = Path(settings.BASE_DIR) / "static" / "css"
        for name in ("input.css", "main.css"):
            css = (css_dir / name).read_text(encoding="utf-8")
            for rule, pattern in self.RULES.items():
                self.assertRegex(css, pattern, f"{name}: {rule}")
