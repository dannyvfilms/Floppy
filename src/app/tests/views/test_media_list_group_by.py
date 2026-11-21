"""Group By on every library: genre, status and author, as lanes or tiles."""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, TestCase
from django.urls import reverse

from app.filter_bar import build_filter_bar_props
from app.media_list_views import GROUP_LANE_LIMIT, group_by_choices_for
from app.models import Book, Item, MediaTypes, Sources, Status


class LibraryGroupByViewTests(TestCase):
    """Any library can be grouped by genre or status, and reading types by author."""

    def setUp(self):
        cache.clear()
        self.credentials = {"username": "groupby", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)
        self.url = reverse("medialist", kwargs={"media_type": MediaTypes.BOOK.value})

    def _book(
        self,
        media_id,
        title,
        *,
        genres=(),
        authors=(),
        status=Status.IN_PROGRESS.value,
        image="",
    ):
        item = Item.objects.create(
            media_id=str(media_id),
            source=Sources.MANUAL.value,
            media_type=MediaTypes.BOOK.value,
            title=title,
            image=image,
            genres=list(genres),
            authors=list(authors),
        )
        Book.objects.create(item=item, user=self.user, status=status, progress=0)
        return item

    def _groups(self, response):
        return {
            group["name"]: sorted(entry.item.title for entry in group["entries"])
            for group in response.context["media_groups"]
        }

    def test_choices_follow_the_media_type(self):
        self.assertEqual(
            [value for value, _label in group_by_choices_for(MediaTypes.BOOK.value)],
            ["item", "genre", "status", "author"],
        )
        self.assertEqual(
            [value for value, _label in group_by_choices_for(MediaTypes.TV.value)],
            ["item", "genre", "status"],
        )
        self.assertEqual(
            [value for value, _label in group_by_choices_for(MediaTypes.GAME.value)],
            ["item", "series", "franchise", "genre", "status"],
        )

    def test_a_choice_the_type_does_not_offer_falls_back_to_item(self):
        url = reverse("medialist", kwargs={"media_type": MediaTypes.TV.value})

        response = self.client.get(url, {"group_by": "author"})

        self.assertEqual(response.context["current_group_by"], "item")

    def test_a_title_with_two_genres_sits_in_both_groups(self):
        self._book(1, "Dune", genres=["Sci-Fi", "Fantasy"])
        self._book(2, "Neuromancer", genres=["Sci-Fi"])

        response = self.client.get(self.url, {"group_by": "genre"})

        self.assertEqual(
            self._groups(response),
            {"Sci-Fi": ["Dune", "Neuromancer"], "Fantasy": ["Dune"]},
        )

    def test_genres_match_without_regard_to_case(self):
        self._book(1, "Dune", genres=["Sci-Fi"])
        self._book(2, "Neuromancer", genres=["sci-fi"])

        response = self.client.get(self.url, {"group_by": "genre"})

        groups = response.context["media_groups"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["game_count"], 2)

    def test_titles_without_a_value_are_ungrouped(self):
        self._book(1, "Dune", genres=["Sci-Fi"])
        self._book(2, "Untitled Notes")

        response = self.client.get(self.url, {"group_by": "genre"})

        self.assertEqual(
            self._groups(response),
            {"Sci-Fi": ["Dune"], "Ungrouped": ["Untitled Notes"]},
        )

    def test_status_groups_follow_the_life_of_an_entry(self):
        self._book(1, "Done", status=Status.COMPLETED.value)
        self._book(2, "Later", status=Status.PLANNING.value)
        self._book(3, "Now", status=Status.IN_PROGRESS.value)

        response = self.client.get(
            self.url, {"group_by": "status", "sort": "title", "direction": "asc"},
        )

        self.assertEqual(
            [group["name"] for group in response.context["media_groups"]],
            ["In Progress", "Planning", "Completed"],
        )

    def test_books_group_by_each_author(self):
        self._book(1, "Good Omens", authors=["Terry Pratchett", "Neil Gaiman"])
        self._book(2, "Mort", authors=["Terry Pratchett"])

        response = self.client.get(self.url, {"group_by": "author"})

        self.assertEqual(
            self._groups(response),
            {
                "Terry Pratchett": ["Good Omens", "Mort"],
                "Neil Gaiman": ["Good Omens"],
            },
        )

    def test_opening_a_genre_shows_its_titles(self):
        self._book(1, "Dune", genres=["Sci-Fi", "Fantasy"])
        self._book(2, "Mort", genres=["Fantasy"])

        response = self.client.get(
            self.url, {"group_by": "genre", "group": "genre:sci-fi"},
        )

        self.assertEqual(response.context["current_game_group_name"], "Sci-Fi")
        self.assertEqual(
            [entry.item.title for entry in response.context["media_list"]],
            ["Dune"],
        )

    def test_opening_ungrouped_shows_the_titles_without_a_value(self):
        self._book(1, "Dune", genres=["Sci-Fi"])
        self._book(2, "Untitled Notes")

        response = self.client.get(
            self.url, {"group_by": "genre", "group": "__ungrouped__"},
        )

        self.assertEqual(response.context["current_game_group_name"], "Ungrouped")
        self.assertEqual(
            [entry.item.title for entry in response.context["media_list"]],
            ["Untitled Notes"],
        )

    def test_groups_show_as_lanes_by_default(self):
        self._book(1, "Dune", genres=["Sci-Fi"])

        response = self.client.get(self.url, {"group_by": "genre"})

        self.assertEqual(response.context["current_group_style"], "lanes")
        self.assertTemplateUsed(response, "app/components/grouped_lanes.html")
        self.assertTemplateNotUsed(response, "app/components/group_cover_tile.html")

    def test_a_long_lane_stops_and_links_to_its_group(self):
        for index in range(GROUP_LANE_LIMIT + 3):
            self._book(index + 1, f"Book {index + 1:02}", genres=["Sci-Fi"])

        response = self.client.get(self.url, {"group_by": "genre"})

        group = response.context["media_groups"][0]
        self.assertEqual(len(group["lane_entries"]), GROUP_LANE_LIMIT)
        self.assertTrue(group["lane_has_more"])
        self.assertContains(response, f"See all {GROUP_LANE_LIMIT + 3}")

    def test_tiles_show_up_to_four_different_covers(self):
        for index in range(6):
            self._book(
                index + 1,
                f"Book {index + 1}",
                genres=["Sci-Fi"],
                image=f"https://example.com/{index % 5}.jpg",
            )

        response = self.client.get(
            self.url, {"group_by": "genre", "group_style": "tiles"},
        )

        group = response.context["media_groups"][0]
        self.assertEqual(len(group["covers"]), 4)
        self.assertEqual(len(set(group["covers"])), 4)
        self.assertTemplateUsed(response, "app/components/group_cover_tile.html")

    def test_an_unknown_style_falls_back_to_lanes(self):
        response = self.client.get(
            self.url, {"group_by": "genre", "group_style": "carousel"},
        )

        self.assertEqual(response.context["current_group_style"], "lanes")


class GroupByFilterBarPropsTests(TestCase):
    """Group By is its own toolbar control, not a section of the Filters menu."""

    def _props(self, **context):
        request = RequestFactory().get("/")
        return build_filter_bar_props(
            {"request": request, **context},
            endpoint="/medialist/book",
            target="#media",
            form_id="filter-form",
            surface="library",
        )

    def test_group_choices_and_styles_are_toolbar_options(self):
        props = self._props(
            filter_data={"show_group_by": True},
            group_by_choices=group_by_choices_for(MediaTypes.BOOK.value),
            group_style_choices=(("lanes", "Lanes"), ("tiles", "Tiles")),
            current_group_by="genre",
            current_group_style="tiles",
        )

        self.assertEqual(
            [option["value"] for option in props["options"]["groupBy"]],
            ["item", "genre", "status", "author"],
        )
        self.assertEqual(
            [option["value"] for option in props["options"]["groupStyles"]],
            ["lanes", "tiles"],
        )
        self.assertEqual(props["filters"]["groupBy"], "genre")
        self.assertEqual(props["filters"]["groupStyle"], "tiles")
        self.assertNotIn(
            "groupBy",
            [section["key"] for section in props["options"]["sections"]],
        )

    def test_pages_without_grouping_get_no_group_control(self):
        props = self._props(filter_data={})

        self.assertEqual(props["options"]["groupBy"], [])
