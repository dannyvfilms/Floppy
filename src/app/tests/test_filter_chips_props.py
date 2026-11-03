"""The Discover media-type row is mounted as the shared React chip row."""

import json
import re

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class FilterChipsPropsTest(TestCase):
    """The page carries the chip props, plus the Alpine buttons as the fallback."""

    def setUp(self):
        """Sign in a user."""
        self.user = get_user_model().objects.create_user("chips-user", password="x")
        self.client.force_login(self.user)

    def test_discover_chip_props(self):
        """Discover lists every media option as a chip, with the buttons kept."""
        html = self.client.get(reverse("discover")).content.decode()
        self.assertIn("data-filter-chips-root", html)
        match = re.search(
            r'<script id="(filter-chips-[0-9a-f]+)" type="application/json">(.*?)</script>',
            html,
            re.S,
        )
        props = json.loads(match.group(2))
        values = [item["value"] for item in props["items"]]
        self.assertIn("all", values)
        self.assertIn("movie", values)
        self.assertIn("switchMedia('all')", html)
