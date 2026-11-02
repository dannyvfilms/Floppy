"""Home library shelves cost one page, not the library (#1248)."""

from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from app.models import Item, MediaTypes, Movie, Sources, Status
from users import home_screen
from users.models import (
    DirectionChoices,
    HomeScreenRow,
    HomeScreenRowTypeChoices,
    HomeSortChoices,
    MediaSortChoices,
)

PAGE = 14


class ShelfFixtures:
    """Movies and shelves for the paging tests."""

    def setUp(self):
        """Create a user with one movie shelf."""
        cache.clear()
        self.user = get_user_model().objects.create_user(username="paging", password="x")
        self.user.movie_enabled = True
        self.user.save()
        self.next_index = 0

    def add_movies(self, count):
        """Add ``count`` completed movies without the save signals' provider calls."""
        items = Item.objects.bulk_create(
            [
                Item(
                    media_id=str(10_000 + index),
                    source=Sources.TMDB.value,
                    media_type=MediaTypes.MOVIE.value,
                    title=f"Movie {index:04d}",
                    image="https://example.com/m.jpg",
                )
                for index in range(self.next_index, self.next_index + count)
            ],
        )
        Movie.objects.bulk_create(
            [
                Movie(item=item, user=self.user, status=Status.COMPLETED.value, score=5)
                for item in items
            ],
        )
        self.next_index += count

    def row(self, sort_by, direction=DirectionChoices.ASC):
        """Create a library shelf over completed movies."""
        return HomeScreenRow.objects.create(
            user=self.user,
            media_type=MediaTypes.MOVIE.value,
            position=0,
            enabled=True,
            row_type=HomeScreenRowTypeChoices.LIBRARY_QUERY,
            sort_by=sort_by,
            direction=direction,
            filters={"status": [Status.COMPLETED.value]},
        )



class HomeRowPagingTests(ShelfFixtures, TestCase):
    """A shelf loads the requested window; its cost does not grow with the library."""

    def queries_for(self, row, offset):
        """Return (query count, section) for one window, checking it is cut in SQL."""
        with CaptureQueriesContext(connection) as ctx:
            section = home_screen._build_row_section(
                self.user, row, row.media_type, PAGE, batch_start=offset, seed=0,
            )
        self.assertTrue(
            any(f"LIMIT {PAGE}" in query["sql"] for query in ctx.captured_queries),
            "the shelf window was not cut in SQL",
        )
        return len(ctx.captured_queries), section

    def test_page_query_count_does_not_grow_with_the_library(self):
        """First page and a load-more page cost the same at 20 and 200 movies."""
        row = self.row(MediaSortChoices.SCORE, DirectionChoices.DESC)
        self.add_movies(20)
        small_first, section = self.queries_for(row, 0)
        small_more, _ = self.queries_for(row, PAGE)
        self.assertEqual(section["total"], 20)

        self.add_movies(180)
        big_first, section = self.queries_for(row, 0)
        big_more, _ = self.queries_for(row, PAGE)
        self.assertEqual(section["total"], 200)
        self.assertEqual(len(section["items"]), PAGE)
        self.assertEqual((big_first, big_more), (small_first, small_more))

    def test_only_the_visible_window_is_decorated(self):
        """Home's card lookup sees one page of items, never the whole shelf."""
        self.add_movies(120)
        row = self.row(MediaSortChoices.TITLE)
        seen = []
        original = home_screen._media_lookup_for_items

        def spy(user, items, **kwargs):
            seen.append(len(items))
            return original(user, items, **kwargs)

        with mock.patch.object(home_screen, "_media_lookup_for_items", spy):
            section = home_screen._build_row_section(
                self.user, row, row.media_type, PAGE, batch_start=PAGE,
            )
        self.assertEqual(seen, [PAGE])
        self.assertEqual(section["loaded_count"], 2 * PAGE)
        self.assertEqual(
            [entry.item.title for entry in section["items"]][:2],
            ["Movie 0014", "Movie 0015"],
        )

    def test_random_shelf_pages_without_repeats_or_gaps(self):
        """One seed is one order: consecutive windows tile the whole shelf."""
        self.add_movies(40)
        row = self.row(HomeSortChoices.RANDOM)
        seen = []
        for offset in range(0, 40, PAGE):
            section = home_screen._build_row_section(
                self.user, row, row.media_type, PAGE, batch_start=offset, seed=12345,
            )
            seen.extend(entry.item.pk for entry in section["items"])
        self.assertEqual(len(seen), 40)
        self.assertEqual(len(set(seen)), 40)

    def test_load_more_carries_the_random_seed(self):
        """The first render hands out a seed; load-more requests reuse it."""
        self.add_movies(30)
        row = self.row(HomeSortChoices.RANDOM)
        self.client.force_login(self.user)
        first = home_screen._build_row_section(self.user, row, row.media_type, PAGE)
        seed = first["seed"]
        response = self.client.get(
            reverse("home"),
            {"load_row": row.id, "offset": PAGE, "seed": seed},
            headers={"hx-request": "true"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Home-Row-Seed"], str(seed))
        expected = home_screen._build_row_section(
            self.user, row, row.media_type, PAGE, batch_start=PAGE, seed=seed,
        )
        self.assertEqual(
            [entry.item.pk for entry in response.context["media_list"]["items"]],
            [entry.item.pk for entry in expected["items"]],
        )


    def test_expired_section_reuses_the_cached_python_order(self):
        """A warm render reloads one page, not the whole shelf (#1603)."""
        from app import cache_utils
        from app.library_query.executor import LibraryQueryExecutor

        self.add_movies(20)
        row = self.row(HomeSortChoices.COMPLETION, DirectionChoices.DESC)
        home_screen._cached_row_section(self.user, row, row.media_type, PAGE)
        cache.delete(
            cache_utils.build_home_row_cache_key(self.user.id, row.id, PAGE),
        )

        with mock.patch.object(
            LibraryQueryExecutor,
            "ranked_ids",
            side_effect=AssertionError("the shelf was ranked again"),
        ):
            section = home_screen._cached_row_section(
                self.user, row, row.media_type, PAGE,
            )

        self.assertEqual(section["total"], 20)
        self.assertEqual(len(section["items"]), PAGE)

    def test_python_orders_outlive_the_rendered_section(self):
        """A deterministic order is kept for the long order TTL."""
        from app import cache_utils

        self.add_movies(20)
        row = self.row(HomeSortChoices.COMPLETION, DirectionChoices.DESC)
        with mock.patch.object(cache, "set", wraps=cache.set) as cache_set:
            home_screen._build_row_section(
                self.user, row, row.media_type, PAGE, seed=7,
            )
        order_calls = [
            call for call in cache_set.call_args_list if "_order_" in call.args[0]
        ]
        self.assertEqual(len(order_calls), 1)
        self.assertEqual(
            order_calls[0].args[2], cache_utils.HOME_ROW_ORDER_CACHE_TTL,
        )

    def test_recent_sql_order_matches_the_scan(self):
        """Tracked items by activity, then collected ones: released, upcoming, undated."""
        from datetime import timedelta

        from django.utils import timezone

        from app.models import CollectionEntry

        now = timezone.now()
        self.add_movies(8)
        for index, movie in enumerate(Movie.objects.filter(user=self.user)):
            Movie.objects.filter(pk=movie.pk).update(
                progress=index % 2,
                progressed_at=now - timedelta(hours=index % 3),
            )
        for index, release in enumerate(
            [now - timedelta(days=3), now - timedelta(days=9), now + timedelta(days=4), None],
        ):
            item = Item.objects.create(
                media_id=f"collected-{index}",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title=f"Collected {index}",
                image="https://example.com/m.jpg",
                release_datetime=release,
            )
            CollectionEntry.objects.create(user=self.user, item=item)
        for direction in (DirectionChoices.DESC, DirectionChoices.ASC):
            with self.subTest(direction=direction):
                row = self.row(HomeSortChoices.RECENT, direction)
                row.filters = {"status": []}
                normalized = home_screen._normalized_filter_payload(row.filters, row.media_type)
                executor = home_screen._library_row_executor(
                    self.user, row, normalized, seed=0,
                )
                self.assertTrue(executor.uses_sql)
                ranked = executor.ranked_ids()
                self.assertEqual(len(ranked), 12)
                self.assertEqual(ranked, [row[-1] for row in executor._scan_ranked])


class HomeListShelfTests(ShelfFixtures, TestCase):
    """List shelves page saved membership; smart ones never re-run their rules."""

    def list_row(self, *, smart):
        """Create a list shelf over every movie."""
        from lists.models import CustomList, CustomListItem

        custom_list = CustomList.objects.create(
            name="Shelf",
            owner=self.user,
            is_smart=smart,
            smart_media_types=[MediaTypes.MOVIE.value] if smart else [],
        )
        CustomListItem.objects.bulk_create(
            [
                CustomListItem(custom_list=custom_list, item=item, added_by=self.user)
                for item in Item.objects.filter(media_type=MediaTypes.MOVIE.value)
            ],
        )
        return HomeScreenRow.objects.create(
            user=self.user,
            media_type=MediaTypes.MOVIE.value,
            row_type=HomeScreenRowTypeChoices.CUSTOM_LIST,
            custom_list=custom_list,
            sort_by=MediaSortChoices.TITLE,
            direction=DirectionChoices.ASC,
        )

    def test_smart_shelf_reads_saved_membership(self):
        """Rules are evaluated by the background sync, never by the Home render."""
        self.add_movies(30)
        row = self.list_row(smart=True)
        with (
            mock.patch("lists.tasks.sync_smart_list_task.delay"),
            mock.patch(
                "lists.smart_rules.collect_matching_item_ids",
                side_effect=AssertionError("Home re-ran the smart-list rules"),
            ),
        ):
            section = home_screen._build_row_section(
                self.user, row, row.media_type, PAGE,
            )
        self.assertEqual(section["total"], 30)
        self.assertEqual(section["items"][0].item.title, "Movie 0000")

    def test_list_shelf_decorates_only_the_window(self):
        """A long list's shelf loads one page of cards."""
        self.add_movies(60)
        row = self.list_row(smart=False)
        seen = []
        original = home_screen._media_lookup_for_items

        def spy(user, items, **kwargs):
            seen.append(len(items))
            return original(user, items, **kwargs)

        with mock.patch.object(home_screen, "_media_lookup_for_items", spy):
            section = home_screen._build_row_section(
                self.user, row, row.media_type, PAGE, batch_start=PAGE,
            )
        self.assertEqual(seen, [PAGE])
        self.assertEqual(section["total"], 60)
        self.assertEqual(section["items"][0].item.title, "Movie 0014")
