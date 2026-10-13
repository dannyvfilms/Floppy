"""Collection page: group by media type as Home-style scrolling rows (#1086)."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import CollectionEntry, Item, MediaTypes, Sources


class CollectionGroupingTest(TestCase):
    """``group=type`` renders one row per type; each row loads more on demand."""

    def setUp(self):
        """Create a user with 25 movies, 2 games and 1 other user's book."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        other = get_user_model().objects.create_user(username="other", password="1")
        self.client.login(**self.credentials)
        self.url = reverse("collection_list")

        for number in range(25):
            self._entry(self.user, MediaTypes.MOVIE.value, f"Movie {number:02d}")
        for number in range(2):
            self._entry(self.user, MediaTypes.GAME.value, f"Game {number}")
        self._entry(other, MediaTypes.BOOK.value, "Not Mine")

    def _entry(self, user, media_type, title):
        item = Item.objects.create(
            media_id=title,
            source=Sources.MANUAL.value,
            media_type=media_type,
            title=title,
            image="http://example.com/x.jpg",
        )
        return CollectionEntry.objects.create(user=user, item=item)

    def _rows(self, response):
        return [row["row_id"] for row in response.context["collection_rows"]]

    def test_off_by_default(self):
        """Without group=type the page is the usual paginated list."""
        response = self.client.get(self.url)
        self.assertEqual(response.context["collection_rows"], [])
        self.assertFalse(response.context["group_by_type"])
        self.assertEqual(len(response.context["collection_entries"]), 20)

    def test_one_row_per_owned_type_with_totals(self):
        """Only the user's own types get a row, each with its full total."""
        response = self.client.get(self.url, {"group": "type"})
        rows = response.context["collection_rows"]
        self.assertEqual(self._rows(response), ["collection-movie", "collection-game"])
        self.assertEqual([row["total"] for row in rows], [25, 2])
        self.assertEqual([row["loaded_count"] for row in rows], [20, 2])
        self.assertContains(response, "25 collected")

    def test_row_order_follows_home_screen_order(self):
        """The Home screen's type order decides which row comes first."""
        self.user.home_screen_media_type_order = [
            MediaTypes.GAME.value,
            MediaTypes.MOVIE.value,
        ]
        self.user.save(update_fields=["home_screen_media_type_order"])
        response = self.client.get(self.url, {"group": "type"})
        self.assertEqual(self._rows(response), ["collection-game", "collection-movie"])

    def test_row_order_keeps_disabled_type_position(self):
        """A type turned off in the sidebar keeps its saved place in the rows."""
        season_item = Item.objects.create(
            media_id="season-row",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.SEASON.value,
            title="Season Row",
            image="http://example.com/x.jpg",
            season_number=1,
        )
        CollectionEntry.objects.create(user=self.user, item=season_item)
        self.user.season_enabled = False
        self.user.home_screen_media_type_order = [
            MediaTypes.SEASON.value,
            MediaTypes.MOVIE.value,
        ]
        self.user.save(
            update_fields=["season_enabled", "home_screen_media_type_order"],
        )
        response = self.client.get(self.url, {"group": "type"})
        self.assertEqual(
            self._rows(response),
            ["collection-season", "collection-movie", "collection-game"],
        )

    def test_rows_use_selected_sort(self):
        """Cards inside a row follow the chosen sort."""
        response = self.client.get(
            self.url,
            {"group": "type", "sort": "title", "direction": "desc"},
        )
        movies = response.context["collection_rows"][0]["items"]
        self.assertEqual(movies[0].item.title, "Movie 24")

    def test_view_all_and_load_more_urls_keep_filters(self):
        """View all opens that type's page; load more keeps the same filters."""
        response = self.client.get(
            self.url,
            {"group": "type", "sort": "title", "q": "Movie"},
        )
        row = response.context["collection_rows"][0]
        self.assertTrue(row["view_all_url"].startswith("/collection/movie/?"))
        self.assertIn("sort=title", row["view_all_url"])
        self.assertNotIn("group=", row["view_all_url"])
        self.assertIn("row_type=movie", row["load_more_url"])
        self.assertIn("q=Movie", row["load_more_url"])
        self.assertContains(response, row["view_all_url"].replace("&", "&amp;"))

    def test_search_filter_applies_to_rows(self):
        """A search that matches one type leaves only that type's row."""
        response = self.client.get(self.url, {"group": "type", "q": "Game"})
        self.assertEqual(self._rows(response), ["collection-game"])

    def test_load_more_returns_next_batch_for_one_type(self):
        """The row's load-more request returns the cards after the first batch."""
        response = self.client.get(
            self.url,
            {"group": "type", "row_type": "movie", "offset": 20, "sort": "title"},
            HTTP_HX_REQUEST="true",
        )
        self.assertTemplateUsed(response, "app/components/collection_row_grid.html")
        titles = [entry.item.title for entry in response.context["media_list"]["items"]]
        self.assertEqual(titles, [f"Movie {number}" for number in range(20, 25)])
        self.assertNotContains(response, "Game 0")

    def test_load_more_past_the_end_is_empty(self):
        """Asking beyond the last card returns no cards instead of failing."""
        response = self.client.get(
            self.url,
            {"group": "type", "row_type": "game", "offset": 99},
        )
        self.assertEqual(response.context["media_list"]["items"], [])

    def test_bad_offset_is_treated_as_start(self):
        """A non-numeric offset falls back to the first batch."""
        response = self.client.get(
            self.url,
            {"group": "type", "row_type": "game", "offset": "x"},
        )
        self.assertEqual(len(response.context["media_list"]["items"]), 2)

    def test_ignored_for_single_type_and_table_layout(self):
        """Grouping needs several types and the grid layout; else it is a no-op."""
        single = self.client.get(self.url, {"group": "type", "type": "movie"})
        self.assertFalse(single.context["group_by_type"])
        table = self.client.get(self.url, {"group": "type", "layout": "table"})
        self.assertFalse(table.context["group_by_type"])
        self.assertEqual(table.context["collection_rows"], [])

    def test_empty_collection_shows_empty_state(self):
        """No entries means the normal empty message, not an empty page."""
        CollectionEntry.objects.filter(user=self.user).delete()
        response = self.client.get(self.url, {"group": "type"})
        self.assertContains(response, "Your collection is empty")

    def test_query_count_does_not_grow_with_entries(self):
        """Rows cost a fixed number of queries per type, not one per card."""
        with self.assertNumQueries(self._baseline_queries()):
            self.client.get(self.url, {"group": "type"})
        for number in range(10):
            self._entry(self.user, MediaTypes.MOVIE.value, f"Extra {number}")
        # Batch size caps the first row at 20 cards, so more entries add nothing.
        with self.assertNumQueries(self._baseline_queries()):
            self.client.get(self.url, {"group": "type"})

    def _baseline_queries(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            self.client.get(self.url, {"group": "type"})
        return len(ctx)
