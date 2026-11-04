from django.template import Context, Template
from django.test import SimpleTestCase


class SpinnerTagTests(SimpleTestCase):
    """The shared loading ring renders a React host with a matching server fallback."""

    def render(self, source):
        return Template("{% load ui_tags %}" + source).render(Context())

    def test_default_ring_is_a_host_with_props_and_fallback(self):
        html = self.render("{% spinner %}")
        self.assertIn("data-spinner-root", html)
        self.assertIn('"size": 16', html)
        self.assertIn('data-tone="accent"', html)
        self.assertIn("width:16px;height:16px", html)

    def test_small_rings_use_the_thin_border(self):
        self.assertIn("ui-spinner-thin", self.render('{% spinner 12 "white" %}'))
        self.assertNotIn("ui-spinner-thin", self.render("{% spinner 16 %}"))

    def test_unknown_tone_and_size_fall_back(self):
        html = self.render('{% spinner 999 "red" %}')
        self.assertIn('data-tone="accent"', html)
        self.assertIn("width:16px", html)

    def test_each_ring_gets_its_own_props_id(self):
        html = self.render("{% spinner %}{% spinner %}")
        self.assertEqual(len(set(__import__("re").findall(r'data-props-id="([^"]+)"', html))), 2)
