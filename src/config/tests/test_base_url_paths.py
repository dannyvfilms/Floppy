from django.template import Context, Template
from django.test import SimpleTestCase
from django.urls import set_script_prefix

from config.settings import prefix_base_url


class PrefixBaseUrlTests(SimpleTestCase):
    def test_root_absolute_path_keeps_the_base(self):
        self.assertEqual(
            prefix_base_url("/accounts/login/?loggedout=1", "/track"),
            "/track/accounts/login/?loggedout=1",
        )

    def test_trailing_slash_base_is_not_doubled(self):
        self.assertEqual(prefix_base_url("/accounts/login/", "/track/"), "/track/accounts/login/")

    def test_value_that_already_has_the_base_is_unchanged(self):
        self.assertEqual(
            prefix_base_url("/track/accounts/login/?loggedout=1", "/track"),
            "/track/accounts/login/?loggedout=1",
        )

    def test_full_url_is_unchanged(self):
        self.assertEqual(prefix_base_url("https://sso.test/out", "/track"), "https://sso.test/out")


class ScriptPrefixTagTests(SimpleTestCase):
    def render(self):
        return Template("{% load app_tags %}{% script_prefix %}").render(Context())

    def tearDown(self):
        set_script_prefix("/")

    def test_empty_at_the_root(self):
        set_script_prefix("/")
        self.assertEqual(self.render(), "")

    def test_mount_path_under_base_url(self):
        set_script_prefix("/track/")
        self.assertEqual(self.render(), "/track")
