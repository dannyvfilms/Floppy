"""The settings-card boundary must not expose Django body data as React props."""

import json

from bs4 import BeautifulSoup
from django.template import Context, Template, TemplateSyntaxError
from django.test import SimpleTestCase


class SettingsCardBoundaryTests(SimpleTestCase):
    """Exercise escaping, fallback and the legacy/server-content ownership seam."""

    def test_presentation_props_are_escaped_and_never_contain_body_values(self):
        html = Template(
            '{% load ui_tags %}{% settings_card title=title tone="unknown" %}'
            '<input name="secret" value="{{ secret }}">{% endsettings_card %}'
        ).render(Context({"title": '</script><script>alert("x")</script>', "secret": 'private"<key>'}))
        soup = BeautifulSoup(html, "html.parser")
        script = soup.find("script", type="application/json")
        self.assertEqual(json.loads(script.string)["title"], '</script><script>alert("x")</script>')
        self.assertEqual(json.loads(script.string)["tone"], "neutral")
        self.assertNotIn("private", script.string)
        self.assertNotIn("</script>", script.string)
        self.assertEqual(soup.select_one(".settings-card-body input")["value"], 'private"<key>')
        self.assertIsNone(soup.select_one("[data-settings-card-root] input"))
        self.assertTrue(soup.select_one("[data-settings-card-root]").has_attr("x-ignore"))

    def test_disabled_card_renders_only_the_original_legacy_content(self):
        html = Template(
            '{% load ui_tags %}{% settings_card title="Options" enabled=False %}'
            '<form method="post"><input name="username"></form>{% endsettings_card %}'
        ).render(Context())
        self.assertEqual(html, '<form method="post"><input name="username"></form>')

    def test_props_ids_are_unique_for_multiple_cards_on_a_page(self):
        html = Template(
            "{% load ui_tags %}{% for title in titles %}{% settings_card title=title %}"
            "body{% endsettings_card %}{% endfor %}"
        ).render(Context({"titles": ["Instance", "Personal"]}))
        soup = BeautifulSoup(html, "html.parser")
        ids = [host["data-props-id"] for host in soup.select("[data-settings-card-root]")]
        self.assertEqual(len(set(ids)), 2)
        self.assertTrue(all(soup.find(id=props_id) for props_id in ids))

    def test_unknown_presentation_options_are_rejected(self):
        with self.assertRaises(TemplateSyntaxError):
            Template('{% load ui_tags %}{% settings_card title="A" html="unsafe" %}{% endsettings_card %}')
