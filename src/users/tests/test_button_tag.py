import json
import re

from django.template import Context, Template
from django.test import SimpleTestCase


class ButtonTagTests(SimpleTestCase):
    """The shared button renders a React host with a matching server fallback."""

    def render(self, source, **context):
        return Template("{% load ui_tags i18n %}" + source).render(Context(context))

    def props(self, html):
        return json.loads(re.search(r'<script id="[^"]+" type="application/json">(.*?)</script>', html).group(1))

    def test_default_button_is_a_host_with_props_and_fallback(self):
        html = self.render('{% button "Save" %}')
        self.assertIn("data-button-root", html)
        self.assertIn(
            '<button type="button" class="ui-button ui-button-flat ui-button-small ui-button-auto">Save</button>',
            html,
        )
        props = self.props(html)
        self.assertEqual(props["label"], "Save")
        self.assertEqual(props["type"], "button")
        self.assertTrue(props["small"])
        self.assertTrue(props["auto"])
        self.assertIsNone(props["tone"])

    def test_submit_button_still_submits_without_the_script(self):
        html = self.render('{% button "Save" submit=True name="action" value="1" %}')
        self.assertIn('<button type="submit" class="ui-button', html)
        self.assertIn(' name="action" value="1">Save</button>', html)
        self.assertEqual(self.props(html)["attrs"], {"name": "action", "value": "1"})

    def test_full_width_base_size_and_tone_reach_markup_and_props(self):
        html = self.render('{% button "Delete" "danger-solid" "base" "full" %}')
        self.assertIn("ui-button-tone-danger-solid", html)
        self.assertNotIn("ui-button-small", html)
        self.assertNotIn("ui-button-auto", html)
        props = self.props(html)
        self.assertEqual(props["tone"], "danger-solid")
        self.assertFalse(props["small"])
        self.assertFalse(props["auto"])

    def test_unknown_tone_falls_back_to_primary(self):
        html = self.render('{% button "x" "pink" %}')
        self.assertNotIn("ui-button-tone-", html)
        self.assertIsNone(self.props(html)["tone"])

    def test_ghost_tone_is_always_small(self):
        self.assertIn("ui-button-small", self.render('{% button "x" "ghost-danger" "base" %}'))

    def test_label_is_escaped_in_markup_and_props(self):
        html = self.render("{% button label %}", label='<b onclick="x()">&')
        self.assertNotIn("<b onclick", html)
        self.assertIn("&lt;b onclick=&quot;x()&quot;&gt;&amp;</button>", html)
        self.assertEqual(self.props(html)["label"], '<b onclick="x()">&')

    def test_translated_label(self):
        html = self.render('{% button _("Save") %}')
        self.assertIn(">Save</button>", html)

    def test_htmx_data_and_aria_attributes_pass_through_unchanged(self):
        html = self.render(
            '{% button "Load" hx_get=url hx_target="closest .day" hx_swap="outerHTML" '
            'data_row=3 aria_label="More" %}',
            url="/day/?a=1&b=2",
        )
        self.assertIn(' hx-get="/day/?a=1&amp;b=2" hx-target="closest .day" hx-swap="outerHTML"', html)
        self.assertIn(' data-row="3" aria-label="More">', html)
        self.assertEqual(self.props(html)["attrs"]["hx-get"], "/day/?a=1&b=2")

    def test_unsupported_attributes_are_dropped(self):
        html = self.render('{% button "x" onclick="steal()" style="x" hx_on__click="y" class="evil" %}')
        self.assertNotIn("onclick", html)
        self.assertNotIn("steal", html)
        self.assertNotIn("evil", html)
        self.assertNotIn("hx-on", html)
        self.assertEqual(self.props(html)["attrs"], {})

    def test_attribute_values_are_escaped(self):
        html = self.render('{% button "x" title=t %}', t='" onfocus="x')
        self.assertIn('title="&quot; onfocus=&quot;x"', html)
        self.assertEqual(self.props(html)["attrs"]["title"], '" onfocus="x')

    def test_disabled_reaches_markup_and_props(self):
        html = self.render('{% button "x" disabled=True %}')
        self.assertIn(" disabled>", html)
        self.assertTrue(self.props(html)["disabled"])

    def test_every_host_gets_its_own_props_id(self):
        html = self.render('{% button "a" %}{% button "b" %}')
        ids = re.findall(r'data-props-id="(button-[0-9a-f]+)"', html)
        self.assertEqual(len(set(ids)), 2)
