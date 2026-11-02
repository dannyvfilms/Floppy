"""The media-list API hydrates one page whatever the filters and sort need."""

from http import HTTPStatus as HTTP  # noqa: N814
from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext

from app import image_cache, media_list_filters
from app.models import Item, MediaTypes, Movie, Sources, Status

from .base import FloppyApiTestCase

LIMIT = 10


class MediaListPageCostTests(FloppyApiTestCase):
    """Requests that used to fall back to loading the whole list stay bounded."""

    def add_movies(self, start, count):
        """Add rated, completed movies without the save signals' provider calls."""
        items = Item.objects.bulk_create(
            [
                Item(
                    media_id=f"cost-{index}",
                    source=Sources.TMDB.value,
                    media_type=MediaTypes.MOVIE.value,
                    title=f"Cost Movie {index:04d}",
                    image="https://example.com/m.jpg",
                )
                for index in range(start, start + count)
            ],
        )
        Movie.objects.bulk_create(
            [
                Movie(item=item, user=self.user1, status=Status.COMPLETED.value, score=7)
                for item in items
            ],
        )

    def request(self, params):
        """Return (response, query count, page sizes hydrated)."""
        hydrated = []
        original = media_list_filters.media_list_entries_for_items

        def spy(user, items):
            hydrated.append(len(items))
            return original(user, items)

        # The image-caching toggle is loaded lazily and cached for 5 minutes in a
        # cache other tests share, so warm it first or the count depends on
        # which test ran before this one.
        image_cache.is_enabled()
        with (
            mock.patch.object(media_list_filters, "media_list_entries_for_items", spy),
            CaptureQueriesContext(connection) as ctx,
        ):
            response = self.client.get(
                "/api/v1/media/movie/",
                {"limit": LIMIT, **params},
                **self.auth_headers,
            )
        self.assertEqual(response.status_code, HTTP.OK)
        return response, len(ctx.captured_queries), hydrated

    def test_rating_filter_and_python_sort_hydrate_one_page(self):
        """A rating filter and a Python-only sort no longer load every movie."""
        params = {"rating": "rated", "sort": "runtime"}
        self.add_movies(0, 20)
        response, small_queries, hydrated = self.request(params)
        self.assertEqual(hydrated, [LIMIT])
        small_total = response.json()["pagination"]["total"]

        self.add_movies(20, 180)
        response, big_queries, hydrated = self.request(params)
        self.assertEqual(hydrated, [LIMIT])
        self.assertEqual(response.json()["pagination"]["total"], small_total + 180)
        self.assertEqual(len(response.json()["results"]), LIMIT)
        # The first page's composition changes with the library, so allow the
        # same slack as the fast-path scaling test; growth with size is the bug.
        self.assertLessEqual(big_queries, small_queries + 2)
