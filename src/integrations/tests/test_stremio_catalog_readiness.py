"""The Stremio settings page should say how much of a catalog can be published.

project_catalog() already counts the items it drops for want of an IMDb ID and
only logs the number, so a user whose movies were all silently unpublishable had
no way to tell that from an empty list (issue #1066).
"""

from unittest.mock import patch

from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from app.models import Item, MediaTypes, Sources
from integrations import stremio_catalog
from lists.models import CustomList, CustomListItem
from users.models import User


class CatalogReadinessTests(TestCase):
    """Counts come from the same local_imdb_id() rule the projection uses."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="reader",
            email="reader@example.com",
            password="pw",  # test-only credential
        )
        self.movies = CustomList.objects.create(name="Movies", owner=self.user)

    def add_movie(self, media_id, provider_external_ids=None):
        item = Item.objects.create(
            media_id=str(media_id),
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title=f"Movie {media_id}",
            provider_external_ids=provider_external_ids or {},
        )
        CustomListItem.objects.create(custom_list=self.movies, item=item)
        return item

    def test_counts_split_publishable_from_unresolved(self):
        self.add_movie(550, {"imdb_id": "tt0137523"})
        self.add_movie(551)
        self.add_movie(552, {"tmdb_id": "552"})

        readiness = stremio_catalog.catalog_readiness(self.user)

        self.assertEqual(len(readiness), 1)
        row = readiness[0]
        self.assertEqual(row["noun"], "movies")
        self.assertEqual(row["list_name"], "Movies")
        self.assertEqual(row["total"], 3)
        self.assertEqual(row["publishable"], 1)
        self.assertEqual(row["unresolved"], 2)

    def test_a_fully_resolved_list_reports_no_unresolved(self):
        self.add_movie(550, {"imdb_id": "tt0137523"})

        row = stremio_catalog.catalog_readiness(self.user)[0]

        self.assertEqual(row["unresolved"], 0)
        self.assertEqual(row["publishable"], 1)

    def test_empty_lists_are_omitted(self):
        self.assertEqual(stremio_catalog.catalog_readiness(self.user), [])

    def test_counts_agree_with_the_projection(self):
        """The status line must not claim more than the catalog would serve."""
        self.add_movie(550, {"imdb_id": "tt0137523"})
        self.add_movie(551)

        spec = next(
            spec
            for spec in stremio_catalog.CATALOG_SPECS
            if spec.stremio_type == "movie"
        )
        metas, unresolved_count = stremio_catalog.project_catalog(self.user, spec, 0)
        row = stremio_catalog.catalog_readiness(self.user)[0]

        self.assertEqual(row["publishable"], len(metas))
        self.assertEqual(row["unresolved"], unresolved_count)


class CatalogStatusLoadingTests(TestCase):
    """The scan runs after the settings page paints, not while it renders."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="reader",
            password="pw",  # test-only credential
        )
        self.client.force_login(self.user)
        self.movies = CustomList.objects.create(name="Movies", owner=self.user)

    def add_movie(self, media_id, provider_external_ids=None):
        item = Item.objects.create(
            media_id=str(media_id),
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title=f"Movie {media_id}",
            provider_external_ids=provider_external_ids or {},
        )
        CustomListItem.objects.create(custom_list=self.movies, item=item)

    def test_settings_page_does_not_scan_the_library(self):
        with patch(
            "integrations.stremio_catalog.catalog_readiness",
            side_effect=AssertionError("scanned during page render"),
        ):
            response = self.client.get(
                reverse("provider_detail", args=["stremio"]) + "?tab=connection"
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("stremio_catalog_status"))

    def test_settings_page_queries_do_not_grow_with_the_library(self):
        # Provider settings resolve shared credentials on first use. Compare
        # equally warm requests so initialization does not skew library cost.
        self.client.get(
            reverse("provider_detail", args=["stremio"]) + "?tab=connection"
        )
        with CaptureQueriesContext(connection) as small:
            self.client.get(
                reverse("provider_detail", args=["stremio"]) + "?tab=connection"
            )
        for media_id in range(60):
            self.add_movie(media_id, {"imdb_id": f"tt{1000000 + media_id}"})
        with CaptureQueriesContext(connection) as large:
            self.client.get(
                reverse("provider_detail", args=["stremio"]) + "?tab=connection"
            )

        self.assertEqual(len(large), len(small))

    def test_status_fragment_reports_the_counts(self):
        self.add_movie(550, {"imdb_id": "tt0137523"})
        self.add_movie(551)

        response = self.client.get(reverse("stremio_catalog_status"))

        self.assertContains(response, "Catalog Status")
        self.assertContains(response, "1 of 2")

    def test_status_fragment_is_empty_without_catalogs(self):
        response = self.client.get(reverse("stremio_catalog_status"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Catalog Status")

    def test_status_fragment_is_cached_briefly(self):
        self.add_movie(550, {"imdb_id": "tt0137523"})

        with patch(
            "integrations.stremio_catalog.catalog_readiness",
            wraps=stremio_catalog.catalog_readiness,
        ) as scan:
            self.client.get(reverse("stremio_catalog_status"))
            self.client.get(reverse("stremio_catalog_status"))

        self.assertEqual(scan.call_count, 1)
