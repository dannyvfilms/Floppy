"""The signed-in sidebar is mounted as the shared React component."""

import json
import re

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.sidebar_model import ICON_DIR, file_icon


class SidebarModelTest(TestCase):
    """The page carries the sidebar's props, and every icon it uses parses."""

    def setUp(self):
        """Sign in a user."""
        self.user = get_user_model().objects.create_user("sidebar-user", password="x")
        self.client.force_login(self.user)

    def props(self, path):
        """Return the sidebar props embedded in the page at ``path``."""
        html = self.client.get(path).content.decode()
        self.assertIn("data-sidebar-root", html)
        match = re.search(
            r'<script id="(sidebar-[0-9a-f]+)" type="application/json">(.*?)</script>',
            html,
            re.DOTALL,
        )
        return json.loads(match.group(2))

    def test_links_and_active_page(self):
        """The movie list is active on its own page, and settings stays inactive."""
        props = self.props(reverse("medialist", kwargs={"media_type": "movie"}))
        movie = next(item for item in props["primary"] if item["href"].endswith("/movie"))
        self.assertTrue(movie["active"])
        self.assertFalse(props["bottom"]["settings"]["active"])
        self.assertEqual(props["userId"], str(self.user.pk))
        self.assertIn("calendar", props["pinKeys"])

    def test_every_icon_parses(self):
        """Each shipped SVG file reduces to shapes the React icon can draw."""
        for path in ICON_DIR.glob("*.svg"):
            with self.subTest(icon=path.name):
                spec = file_icon(path.stem)
                self.assertTrue(spec["children"])
