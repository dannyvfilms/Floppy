"""Template-level accessibility contracts for the app shell.

Static checks only: they pin the specific defects fixed in the shell (the
mobile navigation toggle's name/state/controls wiring and visible focus on
the global-search buttons) so they cannot silently regress. They are not
screen-reader or keyboard-traversal evidence — that needs a browser pass.
"""

from pathlib import Path

from django.test import SimpleTestCase

APP_ROOT = Path(__file__).resolve().parents[2]
BASE_TEMPLATE = APP_ROOT / "templates" / "base.html"
COMMITTED_CSS = APP_ROOT / "static" / "css" / "main.css"


class ShellAccessibilityTests(SimpleTestCase):
    def test_mobile_nav_toggle_is_named_and_reports_its_state(self):
        source = BASE_TEMPLATE.read_text()
        self.assertIn("aria-label=\"{% translate 'Toggle navigation menu' %}\"", source)
        self.assertIn(':aria-expanded="isMobileMenuOpen"', source)
        # The state it reports must control the element it names.
        self.assertIn('aria-controls="sidebar-nav"', source)
        self.assertIn('id="sidebar-nav"', source)

    def test_search_and_toggle_buttons_keep_a_visible_focus_ring(self):
        """The three shell buttons that suppressed outlines must replace them.

        The ring color uses the Tailwind v4 variable shorthand
        ``ring-(--color-accent)``: the arbitrary-bracket form is never
        emitted by the compiler (verified the hard way — see the P11 receipt).
        """
        source = BASE_TEMPLATE.read_text()
        self.assertEqual(
            source.count("focus:ring-(--color-accent)"),
            5,
            "hamburger + search submit + barcode scan + the two search field "
            "segments must all keep a visible focus ring",
        )
        self.assertNotIn("focus:ring-[var(--color-accent)]", source)

    def test_the_ring_rule_is_present_in_the_committed_css(self):
        """The class must exist in the compiled output, not just the markup."""
        css = COMMITTED_CSS.read_text()
        self.assertIn("ring-\\(--color-accent\\)", css)
