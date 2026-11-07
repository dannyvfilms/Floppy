"""The shared shell top bar keeps its server values and fallback."""

import json
import re

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse


class ShellTopbarTest(TestCase):
    """Signed-in and public shells carry props plus a usable fallback."""

    def setUp(self):
        """Sign in a user."""
        self.user = get_user_model().objects.create_user("shell-user", password="x")
        self.client.force_login(self.user)

    def props(self, html):
        """Return the shell props embedded in a rendered page."""
        self.assertIn("data-shell-root", html)
        match = re.search(
            r'<script id="(shell-[0-9a-f]+)" type="application/json">(.*?)</script>',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        return json.loads(match.group(2))

    def test_signed_in_shell_props_and_fallback(self):
        """The app shell carries its labels, menu/search flags and fallback."""
        response = self.client.get(reverse("home"))
        html = response.content.decode()
        props = self.props(html)
        self.assertEqual(props["variant"], "app")
        self.assertTrue(props["showMenu"])
        self.assertTrue(props["showSearch"])
        self.assertTrue(props["themeToggle"])
        self.assertIn("menu", props["labels"])
        self.assertIn("data-global-search-root", html)
        self.assertIn('aria-label="Toggle navigation menu"', html)
        self.assertIn("floppy:mobile-menu", html)

    def test_public_shell_props_and_sign_in(self):
        """The public header keeps the registration-gated sign-in destination."""
        html = render_to_string(
            "base_public.html",
            {"REGISTRATION": True, "user": AnonymousUser()},
        )
        props = self.props(html)
        self.assertEqual(props["variant"], "public")
        self.assertFalse(props["showMenu"])
        self.assertEqual(props["signIn"]["href"], reverse("account_login"))
        self.assertIn("Sign In", html)
