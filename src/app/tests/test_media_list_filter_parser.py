"""One filter parser for the web media list and the API (#806)."""

from datetime import UTC, datetime, timedelta

from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.request import Request

from app.media_list_filters import MediaListFilterError, parse_media_list_filters
from app.models import Item, MediaTypes, Movie, Sources, Status
from lists.models import CustomList, CustomListItem


def _api_request(query):
    return Request(RequestFactory().get("/api/v1/media/", query))


def _web_request(query):
    return RequestFactory().get("/medialist/movie", query)


class ParserContractTests(SimpleTestCase):
    """The API is strict; the web list falls back to "not filtering"."""

    def test_api_rejects_an_invalid_value(self):
        for query in (
            {"year": "20x0"},
            {"rating": "sometimes"},
            {"rating_min": "eleven"},
            {"date_added_from": "yesterday"},
        ):
            with self.subTest(query=query), self.assertRaises(MediaListFilterError):
                parse_media_list_filters(_api_request(query))

    def test_api_rejects_an_invalid_relative_window(self):
        for query in (
            {"date_added_within": "abc"},
            {"date_added_within": "0"},
            {"date_added_within": "7", "date_added_within_unit": "fortnights"},
        ):
            with self.subTest(query=query), self.assertRaises(MediaListFilterError):
                parse_media_list_filters(_api_request(query))

    def test_web_ignores_an_invalid_relative_window(self):
        filters = parse_media_list_filters(
            _web_request({"date_added_within": "abc"}),
            strict=False,
        )

        self.assertEqual(filters.date_added_within, "")
        self.assertEqual(filters.date_added_from, "")

    def test_web_ignores_an_invalid_value(self):
        filters = parse_media_list_filters(
            _web_request(
                {
                    "year": "20x0",
                    "rating": "sometimes",
                    "rating_min": "eleven",
                    "date_added_from": "yesterday",
                    "status": "Bogus",
                },
            ),
            strict=False,
        )

        self.assertEqual(filters.year, "")
        self.assertEqual(filters.rating, "all")
        self.assertEqual(filters.rating_min, "")
        self.assertEqual(filters.date_added_from, "")
        self.assertEqual(filters.statuses, ())

    def test_both_read_ranges_the_same(self):
        query = {
            "rating_min": "7.5",
            "rating_max": "9",
            "release_date_from": "2020-01-01",
            "release_date_to": "2020-12-31",
            "date_added_from": "2024-02-01",
        }
        api = parse_media_list_filters(_api_request(query))
        web = parse_media_list_filters(_web_request(query), strict=False)

        for filters in (api, web):
            self.assertEqual(filters.rating_min, "7.5")
            self.assertEqual(filters.rating_max, "9.0")
            self.assertEqual(filters.release_date_from, "2020-01-01")
            self.assertEqual(filters.release_date_to, "2020-12-31")
            self.assertEqual(filters.date_added_from, "2024-02-01")

    def test_relative_window_resolves_to_dates(self):
        filters = parse_media_list_filters(
            _web_request({"date_added_within": "7", "date_added_within_unit": "days"}),
            strict=False,
        )

        today = timezone.localdate()
        self.assertEqual(filters.date_added_from, (today - timedelta(days=7)).isoformat())
        self.assertEqual(filters.date_added_to, today.isoformat())
        self.assertEqual(filters.date_added_within, "7")

    def test_web_keeps_commas_in_tag_names(self):
        filters = parse_media_list_filters(
            _web_request({"tag": "Rock, Paper"}),
            strict=False,
        )

        self.assertEqual(filters.tags, ("Rock, Paper",))


class MediaListRangeFilterTests(TestCase):
    """Rating and date ranges now work on the media list page."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="viewer",
            password="pw-12345",
        )
        self.client.force_login(self.user)
        self.url = reverse("medialist", args=[MediaTypes.MOVIE.value])
        self.movies = {}
        for index, (score, year) in enumerate(((9, 2020), (6, 2020), (8, 2015))):
            item = Item.objects.create(
                media_id=str(index),
                source=Sources.MANUAL.value,
                media_type=MediaTypes.MOVIE.value,
                title=f"Movie {index}",
                release_datetime=datetime(year, 6, 1, tzinfo=UTC),
            )
            Movie.objects.create(
                item=item,
                user=self.user,
                status=Status.COMPLETED.value,
                score=score,
            )
            self.movies[(score, year)] = item.id

    def _ids(self, params):
        response = self.client.get(self.url, params)
        self.assertEqual(response.status_code, 200)
        return {entry.item.id for entry in response.context["media_list"]}

    def test_rating_range(self):
        self.assertEqual(
            self._ids({"rating_min": "8"}),
            {self.movies[(9, 2020)], self.movies[(8, 2015)]},
        )
        self.assertEqual(self._ids({"rating_max": "7"}), {self.movies[(6, 2020)]})

    def test_release_date_range(self):
        self.assertEqual(
            self._ids({"release_date_from": "2019-01-01"}),
            {self.movies[(9, 2020)], self.movies[(6, 2020)]},
        )

    def test_date_added_range(self):
        old = self.movies[(8, 2015)]
        Movie.objects.filter(item_id=old).update(
            created_at=timezone.now() - timedelta(days=60),
        )

        self.assertNotIn(old, self._ids({"date_added_within": "30"}))
        self.assertEqual(len(self._ids({"date_added_within": "30"})), 2)

    def test_separate_entry_mode_applies_ranges(self):
        """The Python-built path (one card per play) filters ranges too."""
        self.user.movie_show_each_play = True
        self.user.save(update_fields=["movie_show_each_play"])

        self.assertEqual(self._ids({"rating_max": "7"}), {self.movies[(6, 2020)]})
        # A cached page for one range must not answer for another.
        self.assertEqual(
            self._ids({"rating_min": "8"}),
            {self.movies[(9, 2020)], self.movies[(8, 2015)]},
        )

    def test_separate_entry_mode_filters_each_row(self):
        """A title's low-rated play stays hidden when another play scores high."""
        self.user.movie_show_each_play = True
        self.user.save(update_fields=["movie_show_each_play"])
        item_id = self.movies[(9, 2020)]
        Movie.objects.create(
            item_id=item_id,
            user=self.user,
            status=Status.COMPLETED.value,
            score=5,
        )

        response = self.client.get(self.url, {"rating_min": "8"})

        scores = sorted(
            entry.media.score
            for entry in response.context["media_list"]
            if entry.item_id == item_id
        )
        self.assertEqual(scores, [9])

    def test_range_does_not_narrow_the_menu_options(self):
        """Filter-menu options are cached per user, so a range must not shape them."""
        self.client.get(self.url, {"rating_min": "9"})

        response = self.client.get(self.url)

        years = {year["value"] for year in response.context["filter_data"]["years"]}
        self.assertEqual(years, {"2020", "2015"})

    def test_filter_state_reaches_the_page(self):
        response = self.client.get(self.url, {"rating_min": "8", "release_date_within": "2"})

        state = response.context["media_list_filter_state"]
        self.assertEqual(state["rating_min"], "8.0")
        self.assertEqual(state["release_date_within"], "2")
        # A relative window is shown as chosen, not as the dates it resolved to.
        self.assertEqual(state["release_date_from"], "")
        self.assertContains(response, 'id="media-list-filter-state"')
        self.assertContains(response, 'name="rating_min"')


class ListAndMediaListRangesAgreeTests(TestCase):
    """The same range filters give the same items on a list and the media list."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="owner",
            password="pw-12345",
        )
        self.client.force_login(self.user)
        self.custom_list = CustomList.objects.create(name="Everything", owner=self.user)
        for index, (score, year) in enumerate(
            ((9, 2020), (6, 2020), (8, 2015), (None, 2021), (3, 2010)),
        ):
            item = Item.objects.create(
                media_id=str(index),
                source=Sources.MANUAL.value,
                media_type=MediaTypes.MOVIE.value,
                title=f"Movie {index}",
                release_datetime=datetime(year, 6, 1, tzinfo=UTC),
            )
            Movie.objects.create(
                item=item,
                user=self.user,
                status=Status.COMPLETED.value,
                score=score,
            )
            CustomListItem.objects.create(custom_list=self.custom_list, item=item)

    def test_same_ranges_same_items(self):
        list_url = reverse("list_detail", args=[self.custom_list.public_reference])
        media_url = reverse("medialist", args=[MediaTypes.MOVIE.value])
        for params in (
            {"rating_min": "6"},
            {"rating_max": "8"},
            {"rating_min": "4", "rating_max": "8.5"},
            {"release_date_from": "2015-01-01", "release_date_to": "2020-12-31"},
            {"date_added_within": "3", "date_added_within_unit": "days"},
        ):
            with self.subTest(params=params):
                on_list = {
                    item.id for item in self.client.get(list_url, params).context["items"]
                }
                on_media_list = {
                    entry.item.id
                    for entry in self.client.get(media_url, params).context["media_list"]
                }
                self.assertEqual(on_list, on_media_list)
                self.assertTrue(on_list)
