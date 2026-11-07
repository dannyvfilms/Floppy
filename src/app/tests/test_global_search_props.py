"""The header search form is mounted as the shared React component."""

import json
import re
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import MediaTypes, Sources


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
        self.assertIn("suggestionsUrl", props)
        for key in (
            "suggestionsLoading",
            "suggestionsSeeAll",
            "suggestionsEmptyAll",
            "barcodeUnavailable",
        ):
            self.assertIn(key, props["labels"])
        self.assertIn('id="global-search"', html)

    @patch("app.providers.services.search")
    def test_search_results_props_and_fallback(self, mock_search):
        """The results page carries the shared props and keeps server results."""
        mock_search.return_value = {
            "page": 1,
            "total_results": 1,
            "total_pages": 1,
            "results": [
                {
                    "media_id": "438631",
                    "title": "Dune",
                    "media_type": MediaTypes.MOVIE.value,
                    "source": Sources.TMDB.value,
                    "image": "http://example.com/dune.jpg",
                },
            ],
        }

        response = self.client.get(
            reverse("search"),
            {"q": "dune", "media_type": MediaTypes.MOVIE.value},
        )

        html = response.content.decode()
        self.assertIn("data-search-results-root", html)
        self.assertIn("Dune", html)
        match = re.search(
            r'<script id="(search-results-[0-9a-f]+)" type="application/json">(.*?)</script>',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        props = json.loads(match.group(2))
        self.assertEqual(props["mediaType"], MediaTypes.MOVIE.value)
        self.assertEqual(props["query"], "dune")
        self.assertEqual(props["state"], "ready")
        self.assertEqual(props["layout"], "grid")
        section = next(
            item for item in props["sections"] if item["key"] == "online"
        )
        card = section["subsections"][0]["items"][0]
        self.assertEqual(card["title"], "Dune")
        self.assertEqual(card["mediaType"], MediaTypes.MOVIE.value)
        for key in ("searchOnline", "emptyTitle", "loadMore", "previous"):
            self.assertIn(key, props["labels"])

    @patch("app.providers.services.search")
    def test_search_results_paging_props_carry_web_urls(self, mock_search):
        """The shared pager gets page numbers and hrefs the browser adapter follows."""
        mock_search.return_value = {
            "page": 2,
            "total_results": 21,
            "total_pages": 3,
            "results": [
                {
                    "media_id": "438631",
                    "title": "Dune",
                    "media_type": MediaTypes.MOVIE.value,
                    "source": Sources.TMDB.value,
                    "image": "http://example.com/dune.jpg",
                },
            ],
        }

        response = self.client.get(
            reverse("search"),
            {"q": "dune", "media_type": MediaTypes.MOVIE.value, "page": 2},
        )

        html = response.content.decode()
        match = re.search(
            r'<script id="(search-results-[0-9a-f]+)" type="application/json">(.*?)</script>',
            html,
            re.DOTALL,
        )
        paging = json.loads(match.group(2))["paging"]
        self.assertEqual(paging["page"], 2)
        self.assertEqual(paging["totalPages"], 3)
        self.assertEqual(paging["totalResults"], 21)
        self.assertEqual([page["number"] for page in paging["pages"]], [1, 2, 3])
        self.assertTrue(paging["pages"][1]["current"])

        previous = parse_qs(urlparse(paging["previous"]["href"]).query)
        next_page = parse_qs(urlparse(paging["next"]["href"]).query)
        self.assertEqual(previous["page"], ["1"])
        self.assertEqual(next_page["page"], ["3"])
        self.assertEqual(previous["q"], ["dune"])
        self.assertEqual(previous["media_type"], [MediaTypes.MOVIE.value])
