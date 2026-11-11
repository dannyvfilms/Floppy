"""The header search form is mounted as the shared React component."""

import json
import re
from unittest.mock import patch

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

    def _search_props(self, response):
        match = re.search(
            r'<script id="(search-results-[0-9a-f]+)" type="application/json">(.*?)</script>',
            response.content.decode(),
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        return json.loads(match.group(2))

    @patch("app.providers.services.search")
    def test_search_results_props_are_rows_like_homes(self, mock_search):
        """The results page carries one row per provider with results, in Home's row shape."""
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
        props = self._search_props(response)
        self.assertEqual(props["title"], "Search results")
        self.assertEqual(props["mediaType"], MediaTypes.MOVIE.value)
        self.assertEqual(props["query"], "dune")
        self.assertEqual(props["state"], "ready")
        for retired in ("layout", "layoutOptions", "scope", "paging", "sections"):
            self.assertNotIn(retired, props)
        # Provider rows stream in: the page lists them and each loads from the row endpoint.
        self.assertEqual(props["rows"], [])
        self.assertIn("online:tmdb", [source["rowId"] for source in props["onlineSources"]])
        row = self.client.get(
            reverse("search_results_json"),
            {"q": "dune", "media_type": MediaTypes.MOVIE.value, "row": "online:tmdb", "page": 1},
        ).json()["row"]
        self.assertEqual(row["rowId"], "online:tmdb")
        self.assertEqual(row["titleMain"], "Online Results")
        self.assertEqual(row["titleDetail"], "The Movie Database")
        self.assertEqual(row["items"][0]["card"]["title"], "Dune")
        self.assertEqual(row["items"][0]["card"]["mediaType"], MediaTypes.MOVIE.value)
        for key in ("emptyTitle", "loadMore", "altTitle"):
            self.assertIn(key, props["labels"])

    @patch("app.providers.services.search")
    def test_each_provider_with_results_gets_its_own_row(self, mock_search):
        """A provider that is not set up, or finds nothing, has no row."""
        from app.providers import services

        def answer(media_type, query, page, source, **_kwargs):
            if source == Sources.TVDB.value:
                raise services.ProviderNotConfiguredError(Sources.TVDB, "TheTVDB is not configured")
            return {
                "page": 1,
                "total_results": 1,
                "total_pages": 1,
                "results": [
                    {
                        "media_id": "1",
                        "title": "Task",
                        "media_type": MediaTypes.TV.value,
                        "source": source,
                        "image": "http://example.com/task.jpg",
                    },
                ],
            }

        mock_search.side_effect = answer

        rows = {}
        for row_id in ("online:tmdb", "online:tvdb"):
            payload = self.client.get(
                reverse("search_results_json"),
                {"q": "task", "media_type": MediaTypes.TV.value, "row": row_id, "page": 1},
            ).json()
            rows[row_id] = payload["row"]
        self.assertIsNotNone(rows["online:tmdb"])
        self.assertIsNone(rows["online:tvdb"])

    @patch("app.providers.services.search")
    def test_search_row_pages_come_from_the_json_endpoint(self, mock_search):
        """Load more asks for one row's next provider page and gets only that page."""
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
            reverse("search_results_json"),
            {"q": "dune", "media_type": MediaTypes.MOVIE.value, "row": "online:tmdb", "page": 2},
        )

        row = response.json()["row"]
        self.assertEqual(row["rowId"], "online:tmdb")
        self.assertEqual(row["page"], 2)
        self.assertEqual(row["total"], 21)
        self.assertEqual([item["card"]["title"] for item in row["items"]], ["Dune"])
        self.assertEqual(mock_search.call_args.args[2], 2)

    def test_search_results_json_needs_a_signed_in_user(self):
        """The JSON endpoint does not search for strangers."""
        self.client.logout()

        response = self.client.get(reverse("search_results_json"), {"q": "dune", "media_type": "movie"})

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])
