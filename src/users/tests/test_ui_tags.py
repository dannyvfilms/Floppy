"""The settings-card boundary must not expose Django body data as React props."""

import json
from types import SimpleNamespace

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

    def test_cast_person_role_can_be_always_visible_on_the_card(self):
        """The person-card line setting carries role visibility to cast cards."""
        from users.card_metadata import parse_card_metadata
        from users.templatetags.ui_tags import _people_cast_props

        user = SimpleNamespace(
            card_metadata=parse_card_metadata(
                {
                    "version": 1,
                    "types": {
                        "person": {
                            "fields": ["role"],
                            "lines": [{"fields": ["role"], "display": "dormant"}],
                            "options": {
                                "title": {
                                    "overflow": "wrap",
                                    "lines": 2,
                                    "hover": "stay",
                                    "hover_lines": 3,
                                },
                            },
                        },
                    },
                },
            ),
        )
        props = _people_cast_props(
            {"user": user},
            {
                "title": "Cast",
                "items": [{"person_id": "123", "name": "Jane", "role": "Rae"}],
                "credit_event_date": "2020-01-01",
                "credit_event_label": "release",
                "credit_event_media_type": "movie",
            },
            "tmdb",
            "",
        )

        self.assertEqual(
            props["items"][0]["cardLines"],
            [{"text": "Rae", "dormant": True}],
        )
        self.assertEqual(
            props["titleOptions"],
            {"overflow": "wrap", "lines": 2, "hover": "stay", "hover_lines": 3},
        )
        self.assertIn("event_date=2020-01-01", props["items"][0]["ageUrl"])
        self.assertIn("event_label=release", props["items"][0]["ageUrl"])
        self.assertIn("media_type=movie", props["items"][0]["ageUrl"])
        self.assertTrue(props["items"][0]["showCreditAge"])

        user.card_metadata = parse_card_metadata({
            "version": 1,
            "types": {
                "person": {
                    "fields": ["role"],
                    "options": {"show_credit_age": False},
                },
            },
        })
        hidden_props = _people_cast_props(
            {"user": user},
            {
                "title": "Cast",
                "items": [{"person_id": "123", "name": "Jane", "role": "Rae"}],
                "credit_event_date": "2020-01-01",
                "credit_event_label": "release",
                "credit_event_media_type": "movie",
            },
            "tmdb",
            "",
        )
        self.assertFalse(hidden_props["items"][0]["showCreditAge"])
        self.assertEqual(hidden_props["items"][0]["ageUrl"], "")
