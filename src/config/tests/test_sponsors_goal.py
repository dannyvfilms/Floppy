"""Cover the Sponsors goal card updater, which lives outside the Django tree.

The daily workflow opens a PR whenever the script rewrites the card, so the
script must rewrite it only when the goal figures change (a new sponsor or a new
target), never because the wording or layout differs.
"""

import importlib.util
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

_ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "update_sponsors_goal",
    _ROOT / "scripts" / "update_sponsors_goal.py",
)
updater = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(updater)

CARD = _ROOT / "docs" / "brand" / "sponsors-goal.svg"


def goal(percent=12, target=100):
    return {
        "kind": "MONTHLY_SPONSORSHIP_AMOUNT",
        "targetValue": target,
        "percentComplete": percent,
    }


class SponsorsGoalCardTests(SimpleTestCase):
    def use_card(self, text):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "card.svg"
        if text is not None:
            path.write_text(text, encoding="utf-8")
        patcher = patch.object(updater, "OUTPUT", path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_committed_card_matches_the_script_template(self):
        # Hand edits to the SVG that the script does not reproduce would show up
        # as a spurious update PR the next time the goal changes.
        match = updater.LABEL.search(CARD.read_text(encoding="utf-8"))
        committed = goal(int(match[1]), int(match[2].replace(",", "")))

        self.assertEqual(CARD.read_text(encoding="utf-8"), updater.render(committed))

    def test_same_figures_are_current(self):
        self.use_card(updater.render(goal()))

        self.assertTrue(updater.card_is_current(goal()))

    def test_wording_or_layout_differences_are_still_current(self):
        edited = updater.render(goal()).replace("community needs", "everyone").replace("54.0", "54")
        self.use_card(edited)

        self.assertTrue(updater.card_is_current(goal()))

    def test_new_percent_is_a_change(self):
        self.use_card(updater.render(goal(12)))

        self.assertFalse(updater.card_is_current(goal(15)))

    def test_new_target_is_a_change(self):
        self.use_card(updater.render(goal(12, 100)))

        self.assertFalse(updater.card_is_current(goal(12, 250)))

    def test_thousands_separator_target_round_trips(self):
        self.use_card(updater.render(goal(40, 1500)))

        self.assertTrue(updater.card_is_current(goal(40, 1500)))

    def test_missing_or_unreadable_card_is_a_change(self):
        self.use_card(None)
        self.assertFalse(updater.card_is_current(goal()))

        self.use_card("<svg></svg>")
        self.assertFalse(updater.card_is_current(goal()))
