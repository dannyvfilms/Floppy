# FORK: query-cost regressions for the list item endpoints.
#
# Both endpoints used to hydrate every item in a list - one media lookup per
# item - before paginating, so returning twenty rows from a 4,683-item list
# cost 4,683 queries and 4,683 hydrated objects. The page is now taken at the
# database layer whenever no aggregated sort is requested.
from http import HTTPStatus as HTTP  # noqa: N814

from django.db import connection
from django.test.utils import CaptureQueriesContext

from app.models import TV, Item, MediaTypes, Movie, Sources
from lists.models import CustomList, CustomListItem

from .base import FloppyApiTestCase

LIST_SIZE = 40
PAGE_SIZE = 5


class ListPaginationCostTests(FloppyApiTestCase):
    def setUp(self):
        """Build a list big enough that per-item work is visible."""
        super().setUp()
        self.custom_list = CustomList.objects.create(
            name="Big List",
            owner=self.user1,
        )
        for index in range(LIST_SIZE):
            item = Item.objects.create(
                media_id=f"pagination-movie-{index:03d}",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title=f"Pagination Movie {index:03d}",
            )
            CustomListItem.objects.create(custom_list=self.custom_list, item=item)

    def _get(self, url_name, **params):
        return self.call_api(
            "get",
            url_name,
            args=(self.custom_list.id,),
            params={"limit": PAGE_SIZE, **params},
            headers=self.auth_headers,
        )

    def test_items_endpoint_returns_the_requested_page(self):
        response = self._get("api_list_add_item")

        self.assertEqual(response.status_code, HTTP.OK)
        payload = response.json()
        self.assertEqual(payload["pagination"]["total"], LIST_SIZE)
        self.assertEqual(len(payload["results"]), PAGE_SIZE)
        self.assertEqual(
            [result["item"]["title"] for result in payload["results"]],
            [f"Pagination Movie {index:03d}" for index in range(PAGE_SIZE)],
        )

    def test_items_endpoint_offset_page_matches_list_order(self):
        response = self._get("api_list_add_item", offset=PAGE_SIZE)

        payload = response.json()
        self.assertEqual(payload["pagination"]["total"], LIST_SIZE)
        self.assertEqual(
            [result["item"]["title"] for result in payload["results"]],
            [
                f"Pagination Movie {index:03d}"
                for index in range(PAGE_SIZE, PAGE_SIZE * 2)
            ],
        )

    def test_items_endpoint_query_count_does_not_scale_with_list_size(self):
        """The contract: cost follows the page, not the library."""
        with CaptureQueriesContext(connection) as queries:
            self._get("api_list_add_item")

        self.assertLess(len(queries), LIST_SIZE)

    def test_detail_endpoint_query_count_does_not_scale_with_list_size(self):
        with CaptureQueriesContext(connection) as queries:
            self._get("api_list_detail")

        self.assertLess(len(queries), LIST_SIZE)

    def test_detail_endpoint_still_reports_the_full_item_count(self):
        response = self._get("api_list_detail")

        self.assertEqual(response.status_code, HTTP.OK)
        payload = response.json()
        self.assertEqual(payload["items_count"], LIST_SIZE)
        self.assertEqual(len(payload["items"]["results"]), PAGE_SIZE)

    def test_search_narrows_the_page_and_the_total(self):
        response = self._get("api_list_add_item", search="Movie 007")

        payload = response.json()
        self.assertEqual(payload["pagination"]["total"], 1)
        self.assertEqual(payload["results"][0]["item"]["title"], "Pagination Movie 007")

    def test_aggregated_sort_still_ranks_the_whole_list(self):
        """Sorting has to see every item, so that path keeps hydrating them."""
        response = self._get("api_list_add_item", sort="title")

        self.assertEqual(response.status_code, HTTP.OK)
        payload = response.json()
        self.assertEqual(payload["pagination"]["total"], LIST_SIZE)
        self.assertEqual(len(payload["results"]), PAGE_SIZE)

    def test_invalid_sort_is_rejected(self):
        response = self._get("api_list_add_item", sort="not-a-sort")

        self.assertEqual(response.status_code, HTTP.NOT_FOUND)


class ListItemsTrackedMixCostTests(FloppyApiTestCase):
    """Tracked shows/movies/anime used to cost ~5 queries per item on a page."""

    def test_page_of_tracked_media_batches_its_prefetches(self):
        custom_list = CustomList.objects.create(name="Mixed", owner=self.user1)
        for index in range(10):
            show = Item.objects.create(
                media_id=f"mix-tv-{index}",
                source=Sources.TMDB.value,
                media_type=MediaTypes.TV.value,
                title=f"Mix Show {index}",
            )
            TV.objects.create(item=show, user=self.user1)
            movie = Item.objects.create(
                media_id=f"mix-movie-{index}",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title=f"Mix Movie {index}",
            )
            Movie.objects.create(item=movie, user=self.user1)
            for item in (show, movie):
                CustomListItem.objects.create(custom_list=custom_list, item=item)

        with CaptureQueriesContext(connection) as queries:
            response = self.call_api(
                "get",
                "api_list_add_item",
                args=(custom_list.id,),
                params={"limit": 20},
                headers=self.auth_headers,
            )

        self.assertEqual(response.status_code, HTTP.OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 20)
        self.assertTrue(all(result["tracked"] for result in results))
        # Was 4 prefetch queries per item (~110 here); now one per media type.
        self.assertLess(len(queries), 60)
