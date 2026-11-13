import json
import re

from django.template.loader import render_to_string
from django.test import SimpleTestCase


class DateTimePickerTagTests(SimpleTestCase):
    """The tracking field keeps its form value and hands explicit props to React."""

    def render(self, **overrides):
        context = {
            "field_name": "start_date",
            "field_id": "id_start_date",
            "field_value": "2024-01-15T20:30",
            "field_label": "Start date",
            "track_time": True,
            "week_start": "monday",
            "use_12_hour": True,
            "suggestion_label": "Release Date",
            "suggestion_date": "2024-01-15",
            "suggestion_runtime_minutes": "95",
            "runtime_minutes": "95",
            "quick_action_mode": "start",
            "copy_from": "end_date",
            "copy_from_label": "End",
        }
        context.update(overrides)
        return render_to_string("app/components/date_time_picker.html", context)

    def props(self, html):
        match = re.search(
            r'<script id="[^"]+" type="application/json">(.*?)</script>',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        return json.loads(match.group(1))

    def test_renders_a_react_host_and_the_existing_hidden_value(self):
        html = self.render()
        self.assertIn("data-date-time-picker-root", html)
        self.assertIn('name="start_date"', html)
        self.assertIn('id="id_start_date"', html)
        self.assertIn('value="2024-01-15T20:30"', html)
        self.assertNotIn('x-data="dateTimePicker(', html)

    def test_props_carry_preferences_suggestion_and_quick_action_mode(self):
        props = self.props(self.render())
        self.assertTrue(props["trackTime"])
        self.assertTrue(props["use12Hour"])
        self.assertEqual(props["weekStart"], "monday")
        self.assertEqual(props["suggestionDate"], "2024-01-15")
        self.assertEqual(props["suggestionRuntimeMinutes"], "95")
        self.assertEqual(props["copyFrom"], "end_date")
        self.assertEqual(props["copyLabel"], "End")
        self.assertEqual(
            [action["id"] for action in props["quickActions"]],
            ["start-now", "release-date"],
        )
        self.assertEqual(props["labels"]["field"], "Start date")

    def test_dynamic_suggestion_expressions_keep_the_legacy_alpine_markup(self):
        html = self.render(
            suggestion_date_expr="selectedEpisodeAirDate('first')",
        )
        self.assertIn('x-data="dateTimePicker(', html)
        self.assertNotIn("data-date-time-picker-root", html)
