"""The custom list page accepts the same filters as the media list (#806)."""

from datetime import UTC, datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import Item, MediaTypes, Movie, Sources, Status
from lists.models import CustomList, CustomListItem


def _movie(media_id, year, genres=("Drama",)):
    return Item.objects.create(
        media_id=str(media_id),
        source=Sources.MANUAL.value,
        media_type=MediaTypes.MOVIE.value,
        title=f"Movie {media_id}",
        release_datetime=datetime(year, 6, 1, tzinfo=UTC),
        genres=list(genres),
    )


class ListDetailFilterTests(TestCase):
    """Genre, year, rating and the other media-list filters work on list pages."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="owner",
            password="pw-12345",
        )
        self.client.force_login(self.user)
        self.custom_list = CustomList.objects.create(name="Films", owner=self.user)
        self.url = reverse("list_detail", args=[self.custom_list.public_reference])

    def _add(self, item, *, score=None, status=Status.COMPLETED.value):
        if status is not None:
            Movie.objects.create(item=item, user=self.user, status=status, score=score)
        CustomListItem.objects.create(custom_list=self.custom_list, item=item)
        return item

    def _item_ids(self, response):
        return {item.id for item in response.context["items"]}

    def test_year_filter_keeps_only_that_years_items(self):
        old = self._add(_movie(1, 2019))
        new = self._add(_movie(2, 2020))

        response = self.client.get(self.url, {"year": "2020"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._item_ids(response), {new.id})
        self.assertNotIn(old.id, self._item_ids(response))

    def test_genre_and_rating_range_filters_apply(self):
        drama_high = self._add(_movie(1, 2020, ["Drama"]), score=9)
        self._add(_movie(2, 2020, ["Drama"]), score=4)
        self._add(_movie(3, 2020, ["Comedy"]), score=9)

        response = self.client.get(self.url, {"genre": "Drama", "rating_min": "8"})

        self.assertEqual(self._item_ids(response), {drama_high.id})

    def test_untracked_list_items_still_show_without_filters(self):
        untracked = self._add(_movie(1, 2020), status=None)

        response = self.client.get(self.url)

        self.assertEqual(self._item_ids(response), {untracked.id})

    def test_next_page_keeps_the_filter(self):
        """Infinite scroll asks for page 2 with the same filters; it must honour them."""
        matching = {self._add(_movie(i, 2020)).id for i in range(20)}
        for i in range(20, 25):
            self._add(_movie(i, 2019))

        first = self.client.get(self.url, {"year": "2020"})
        second = self.client.get(
            self.url,
            {"year": "2020", "page": 2},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(first.context["filtered_items_count"], 20)
        self.assertTrue(first.context["has_next"])
        self.assertEqual(len(first.context["items"]), 16)
        self.assertEqual(len(second.context["items"]), 4)
        self.assertFalse(second.context["has_next"])
        self.assertEqual(self._item_ids(first) | self._item_ids(second), matching)

    def test_menu_offers_only_the_lists_own_years(self):
        self._add(_movie(1, 2020))
        # In the library but not on the list: its year must not be offered.
        Movie.objects.create(
            item=_movie(2, 1999),
            user=self.user,
            status=Status.COMPLETED.value,
        )

        response = self.client.get(self.url)

        years = [option["value"] for option in response.context["list_filter_data"]["years"]]
        self.assertEqual(years, ["2020"])
        self.assertContains(response, 'id="list-filter-data"')
        self.assertContains(response, "mediaFilterMenu('list-filter-data')")

    def test_active_filters_are_handed_back_to_the_page(self):
        self._add(_movie(1, 2020))

        response = self.client.get(self.url, {"year": "2020", "genre": "Drama"})

        state = response.context["list_filter_state"]
        self.assertEqual(state["year"], "2020")
        self.assertEqual(state["genre"], "Drama")

    def test_media_types_come_from_the_filter_menu(self):
        movie = self._add(_movie(1, 2020))
        show = self._add(
            Item.objects.create(
                media_id="10",
                source=Sources.MANUAL.value,
                media_type=MediaTypes.TV.value,
                title="Show",
            ),
            status=None,
        )

        response = self.client.get(self.url)
        # One type picker: the menu's Media Types pane, not a separate dropdown.
        self.assertContains(response, "view = 'mediaTypes'")
        self.assertNotContains(response, "getMediaTypeLabel")
        self.assertEqual(self._item_ids(response), {movie.id, show.id})

        only_movies = self.client.get(
            self.url,
            {"type_mode": "subset", "type": MediaTypes.MOVIE.value},
        )
        self.assertEqual(self._item_ids(only_movies), {movie.id})
        self.assertEqual(
            only_movies.context["list_filter_state"]["media_types"],
            [MediaTypes.MOVIE.value],
        )

        # "Hide all" submits a subset with no types.
        hidden = self.client.get(self.url, {"type_mode": "subset"})
        self.assertEqual(self._item_ids(hidden), set())
        self.assertEqual(
            self._item_ids(self.client.get(self.url, {"type_mode": "all"})),
            {movie.id, show.id},
        )

    def test_public_view_filters_by_year_and_hides_owner_tags(self):
        from app.models import Tag

        Tag.objects.create(user=self.user, name="private-tag")
        self.custom_list.visibility = "public"
        self.custom_list.save(update_fields=["visibility"])
        new = self._add(_movie(2, 2020))
        self._add(_movie(1, 2019))
        self.client.logout()

        response = self.client.get(self.url, {"year": "2020"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._item_ids(response), {new.id})
        self.assertEqual(response.context["list_filter_data"]["tags"], [])
        self.assertNotContains(response, "private-tag")


class ListAndMediaListAgreeTests(TestCase):
    """A list holding the whole library filters exactly like the media list.

    Both pages run the same library-query engine; this guards the step in front
    of it, turning the URL into filters, against drifting apart again.
    """

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="owner",
            password="pw-12345",
        )
        self.client.force_login(self.user)
        self.custom_list = CustomList.objects.create(name="Everything", owner=self.user)
        specs = [
            (2019, ["Drama"], 8),
            (2020, ["Drama"], None),
            (2020, ["Comedy"], 6),
            (2020, ["Drama", "Comedy"], 9),
            (2021, ["Horror"], 3),
        ]
        for index, (year, genres, score) in enumerate(specs):
            item = _movie(index, year, genres)
            Movie.objects.create(
                item=item,
                user=self.user,
                status=Status.COMPLETED.value,
                score=score,
            )
            CustomListItem.objects.create(custom_list=self.custom_list, item=item)

    def _ids(self, url, params, context_key):
        response = self.client.get(url, params)
        self.assertEqual(response.status_code, 200)
        return {getattr(entry, "item", entry).id for entry in response.context[context_key]}

    def test_same_filters_same_items(self):
        list_url = reverse("list_detail", args=[self.custom_list.public_reference])
        media_url = reverse("medialist", args=[MediaTypes.MOVIE.value])
        for params in (
            {"year": "2020"},
            {"genre": "Drama"},
            {"rating": "rated"},
            {"rating": "not_rated"},
            {"year": "2020", "genre": "Comedy"},
            {"year": "unknown"},
        ):
            with self.subTest(params=params):
                self.assertEqual(
                    self._ids(list_url, params, "items"),
                    self._ids(media_url, params, "media_list"),
                )
