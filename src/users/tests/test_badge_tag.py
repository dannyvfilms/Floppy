import re

from django.template import Context, Template
from django.test import SimpleTestCase


class BadgeTagTests(SimpleTestCase):
    """The shared badge renders a React host with a matching server fallback."""

    def render(self, source, **context):
        return Template("{% load ui_tags %}" + source).render(Context(context))

    def test_default_badge_is_a_host_with_props_and_fallback(self):
        html = self.render('{% badge "Mapped" %}')
        self.assertIn("data-badge-root", html)
        self.assertIn('"label": "Mapped"', html)
        self.assertIn('class="ui-badge ui-badge-sm" data-tone="outline">Mapped</span>', html)

    def test_size_and_tone_reach_markup_and_props(self):
        html = self.render('{% badge "Album" "md" "rose" %}')
        self.assertIn("ui-badge-md", html)
        self.assertIn('data-tone="rose"', html)
        self.assertIn('"size": "md"', html)

    def test_unknown_size_and_tone_fall_back(self):
        html = self.render('{% badge "x" "huge" "pink" %}')
        self.assertIn("ui-badge-sm", html)
        self.assertIn('data-tone="outline"', html)

    def test_label_is_escaped_in_markup_and_props(self):
        html = self.render("{% badge label %}", label="<b>R&B</b>")
        self.assertNotIn("<b>R&B</b>", html)
        self.assertIn("&lt;b&gt;R&amp;B&lt;/b&gt;", html)
        self.assertIn("\\u003Cb\\u003ER\\u0026B", html)

    def test_href_makes_a_link_and_nowrap_is_kept(self):
        html = self.render('{% badge "Drama" "sm" "genre" href="/movies/?genre=Drama" nowrap=True %}')
        self.assertIn('<a href="/movies/?genre=Drama" class="ui-badge ui-badge-sm ui-badge-nowrap"', html)

    def test_only_local_hrefs_become_links(self):
        for href in ("javascript:alert(1)", "https://example.com/"):
            html = self.render("{% badge 'x' href=href %}", href=href)
            self.assertNotIn("<a ", html)
            self.assertIn('"href": ""', html)

    def test_each_badge_gets_its_own_props_id(self):
        html = self.render('{% badge "a" %}{% badge "b" %}')
        self.assertEqual(len(set(re.findall(r'data-props-id="([^"]+)"', html))), 2)
