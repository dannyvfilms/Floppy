"""The header search form is mounted as the shared React component."""

import json
import re

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class GlobalSearchPropsTest(TestCase):
    """The page carries the props the React form needs, plus the server fallback."""

    def setUp(self):
        """Sign in a user."""
        self.user = get_user_model().objects.create_user("search-user", password="x")
        self.client.force_login(self.user)

    def test_header_search_props(self):
        """A page has the React host, its props and the plain form fallback."""
        response = self.client.get(reverse("search"), {"q": "dune", "media_type": "book"})
        html = response.content.decode()
        self.assertIn("data-global-search-root", html)
        match = re.search(
            r'<script id="(global-search-[0-9a-f]+)" type="application/json">(.*?)</script>',
            html,
            re.DOTALL,
        )
        props = json.loads(match.group(2))
        self.assertEqual(props["query"], "dune")
        self.assertEqual(props["action"], reverse("search"))
        self.assertIn("book", {option["value"] for option in props["mediaTypes"]})
        self.assertIn('id="global-search"', html)
