"""Self-tests for the shared library-query engine.

These pin the engine's own contract - the SQL path and the batched scan agree,
pages tile the full ordering without gaps or repeats, and the cost of a page
does not grow with the library - independent of any surface that uses it.
"""

from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from app.library_query import FilterValues, LibraryQuery, LibraryQueryExecutor, SortSpec
from app.library_query import executor as executor_module
from app.library_query.sorts import SORTS
from app.library_query.spec import STATUS_MATCH_ANY
from app.models import (
    TV,
    CollectionEntry,
    Item,
    ItemTag,
    MediaTypes,
    Movie,
    Sources,
    Status,
    Tag,
)

MOVIE = MediaTypes.MOVIE.value
SQL_SORT_KEYS = [d.keys[0] for d in SORTS if d.sql is not None]


def _query(**kwargs):
    filters = kwargs.pop("filters", FilterValues())
    sort = kwargs.pop("sort", SortSpec())
    return LibraryQuery(media_types=(MOVIE,), filters=filters, sort=sort, **kwargs)


class LibraryQueryTestCase(TestCase):
    """Builds a small movie library with varied, partly tied, sort values."""

    def setUp(self):
        """Create a user and a movie library."""
        self.user = get_user_model().objects.create_user(username="lq", password="x")
        self.now = timezone.now()

    def make_movie(self, index, **overrides):
        """Create one movie item and its tracker row."""
        item = Item.objects.create(
            media_id=str(1000 + index),
            source=Sources.TMDB.value,
            media_type=MOVIE,
            title=overrides.pop("title", f"Movie {index % 7}"),
            image="https://example.com/i.jpg",
            release_datetime=overrides.pop(
                "release_datetime",
                None if index % 5 == 0 else self.now - timedelta(days=index),
            ),
            provider_rating=overrides.pop(
                "provider_rating",
                None if index % 4 == 0 else Decimal(index % 3),
            ),
            genres=overrides.pop("genres", ["Drama"] if index % 2 else ["Comedy"]),
        )
        movie = self.track(
            item,
            status=overrides.pop("status", Status.COMPLETED.value),
            score=overrides.pop("score", None if index % 3 == 0 else Decimal(index % 10)),
            start_date=self.now - timedelta(days=index % 6),
            end_date=self.now - timedelta(days=index % 4),
        )
        return item, movie

    def track(self, item, model=Movie, **fields):
        """Create a tracker row without the save signals' provider refresh."""
        return model.objects.bulk_create([model(item=item, user=self.user, **fields)])[0]

    def library(self, size, start=0):
        """Create ``size`` movies."""
        return [self.make_movie(index)[0] for index in range(start, start + size)]

    def run_query(self, query, offset=0, limit=100):
        """Return one page."""
        return LibraryQueryExecutor(self.user, query).page(offset, limit)


class SqlAndScanAgreeTests(LibraryQueryTestCase):
    """Every SQL sort orders identically on the scan path."""

    def test_every_sql_sort_matches_the_scan_order(self):
        """SQL ORDER BY and the Python comparator agree, both directions."""
        self.library(30)
        for key in SQL_SORT_KEYS:
            for direction in ("asc", "desc"):
                with self.subTest(key=key, direction=direction):
                    query = _query(sort=SortSpec(key=key, direction=direction, seed=7))
                    executor = LibraryQueryExecutor(self.user, query)
                    sql_ids = [item.pk for item in executor.page(0, 100).items]
                    scan_ids = [row[-1] for row in executor._scan_ranked]
                    self.assertEqual(sql_ids, scan_ids)

    def test_pages_tile_the_full_order_without_gaps_or_repeats(self):
        """Consecutive pages concatenate to the full ordering."""
        self.library(23)
        for key in ("title", "score", "random"):
            with self.subTest(key=key):
                query = _query(sort=SortSpec(key=key, direction="desc", seed=3))
                full = [item.pk for item in self.run_query(query).items]
                paged = []
                for offset in range(0, 23, 5):
                    page = self.run_query(query, offset, 5)
                    self.assertEqual(page.total, 23)
                    paged.extend(item.pk for item in page.items)
                self.assertEqual(paged, full)
                self.assertEqual(len(set(paged)), 23)

    def test_random_order_is_fixed_per_seed(self):
        """The same seed repeats; another seed shuffles differently."""
        self.library(20)
        first = [i.pk for i in self.run_query(_query(sort=SortSpec("random", seed=1))).items]
        again = [i.pk for i in self.run_query(_query(sort=SortSpec("random", seed=1))).items]
        other = [i.pk for i in self.run_query(_query(sort=SortSpec("random", seed=2))).items]
        self.assertEqual(first, again)
        self.assertNotEqual(first, other)


class StatusSemanticsTests(LibraryQueryTestCase):
    """``latest`` follows the newest row; ``any`` accepts any row."""

    def setUp(self):
        """Create an item completed once, then re-watched and dropped."""
        super().setUp()
        self.item, first = self.make_movie(1, status=Status.COMPLETED.value)
        Movie.objects.filter(pk=first.pk).update(end_date=self.now - timedelta(days=30))
        self.track(self.item, status=Status.DROPPED.value, end_date=self.now)

    def ids(self, **filter_kwargs):
        """Return matching ids."""
        query = _query(filters=FilterValues(**filter_kwargs))
        return LibraryQueryExecutor(self.user, query).ids()

    def test_latest_uses_the_newest_row(self):
        """The item's status is Dropped now."""
        self.assertEqual(self.ids(statuses=(Status.DROPPED.value,)), {self.item.pk})
        self.assertEqual(self.ids(statuses=(Status.COMPLETED.value,)), set())

    def test_any_accepts_an_older_row(self):
        """Smart lists saved before the engine match any row."""
        self.assertEqual(
            self.ids(statuses=(Status.COMPLETED.value,), status_match=STATUS_MATCH_ANY),
            {self.item.pk},
        )

    def test_statusless_rows_are_not_in_all(self):
        """An imported rating with no status only appears with "no status"."""
        rated_only = Item.objects.create(
            media_id="9", source=Sources.TMDB.value, media_type=MOVIE, title="Rated",
            image="https://example.com/i.jpg",
        )
        self.track(rated_only, status=None, score=7)
        self.assertNotIn(rated_only.pk, self.ids())
        self.assertEqual(self.ids(include_no_status=True), {rated_only.pk})
        self.assertIn(
            rated_only.pk,
            self.ids(statuses=(Status.DROPPED.value,), include_no_status=True),
        )


class FilterSemanticsTests(LibraryQueryTestCase):
    """Representative filters from each evaluation form."""

    def ids(self, **kwargs):
        """Return matching ids."""
        return LibraryQueryExecutor(self.user, _query(**kwargs)).ids()

    def test_rating_uses_the_latest_scored_row(self):
        """A later unscored rewatch keeps the earlier score."""
        item, movie = self.make_movie(1, score=Decimal(8))
        self.track(item, status=Status.COMPLETED.value)
        unrated, _ = self.make_movie(3, score=None)
        self.assertIn(item.pk, self.ids(filters=FilterValues(rating="rated")))
        self.assertIn(unrated.pk, self.ids(filters=FilterValues(rating="not_rated")))
        self.assertEqual(
            self.ids(filters=FilterValues(rating_min="7.5", rating_max="9")),
            {item.pk},
        )

    def test_tags_modes(self):
        """Tag modes and, or and not match names case-insensitively."""
        a, _ = self.make_movie(1)
        b, _ = self.make_movie(2)
        c, _ = self.make_movie(3)
        red = Tag.objects.create(user=self.user, name="Red")
        blue = Tag.objects.create(user=self.user, name="Blue")
        ItemTag.objects.create(tag=red, item=a)
        ItemTag.objects.create(tag=blue, item=a)
        ItemTag.objects.create(tag=red, item=b)
        tags = ("red", "BLUE")
        self.assertEqual(self.ids(filters=FilterValues(tags=tags, tag_mode="and")), {a.pk})
        self.assertEqual(
            self.ids(filters=FilterValues(tags=tags, tag_mode="or")),
            {a.pk, b.pk},
        )
        self.assertEqual(self.ids(filters=FilterValues(tags=tags, tag_mode="not")), {c.pk})

    def test_genre_matches_case_insensitively(self):
        """JSON-array filters compile to SQL."""
        drama, _ = self.make_movie(1, genres=["Drama"])
        self.make_movie(2, genres=["Comedy"])
        self.assertEqual(self.ids(filters=FilterValues(genre="drama")), {drama.pk})

    def test_collected_platform_overrides_item_platforms(self):
        """A collected copy's platform wins over the provider's list, for every type."""
        item, _ = self.make_movie(1)
        Item.objects.filter(pk=item.pk).update(platforms=["Blu-ray"])
        other, _ = self.make_movie(2)
        Item.objects.filter(pk=other.pk).update(platforms=["Blu-ray"])
        CollectionEntry.objects.create(user=self.user, item=item, resolution="4K UHD")
        self.assertEqual(
            self.ids(filters=FilterValues(platforms=("blu-ray",))),
            {other.pk},
        )
        self.assertEqual(
            self.ids(filters=FilterValues(platforms=("4k uhd",))),
            {item.pk},
        )

    def test_collection_only_items_join_only_when_allowed(self):
        """Untracked collected items appear unless a status or rating is asked for."""
        tracked, _ = self.make_movie(1)
        untracked = Item.objects.create(
            media_id="77", source=Sources.TMDB.value, media_type=MOVIE, title="Shelf",
            image="https://example.com/i.jpg",
        )
        CollectionEntry.objects.create(user=self.user, item=untracked)
        self.assertEqual(
            self.ids(include_collection_only=True, filters=FilterValues(include_no_status=True)),
            {untracked.pk},
        )
        self.assertEqual(
            self.ids(
                include_collection_only=True,
                filters=FilterValues(
                    statuses=(Status.COMPLETED.value,),
                    include_no_status=True,
                ),
            ),
            {tracked.pk, untracked.pk},
        )
        self.assertEqual(
            self.ids(
                include_collection_only=True,
                filters=FilterValues(statuses=(Status.COMPLETED.value,)),
            ),
            {tracked.pk},
        )

    def test_author_predicate_uses_the_scan_path(self):
        """A Python-only filter narrows correctly and pages from the scan."""
        items = self.library(6)
        Item.objects.filter(pk=items[2].pk).update(authors=[{"name": "Le Guin"}])
        executor = LibraryQueryExecutor(self.user, _query(filters=FilterValues(author="le guin")))
        page = executor.page(0, 10)
        self.assertFalse(page.used_sql)
        self.assertEqual([item.pk for item in page.items], [items[2].pk])
        self.assertEqual(page.total, 1)

    def test_union_lists_bypass_filters(self):
        """The smart-list ``list`` rule adds members whatever the filters say."""
        from lists.models import CustomList, CustomListItem

        item, _ = self.make_movie(1, genres=["Comedy"])
        pinned, _ = self.make_movie(2, genres=["Horror"])
        linked = CustomList.objects.create(owner=self.user, name="Linked")
        CustomListItem.objects.create(custom_list=linked, item=pinned)
        self.assertEqual(
            self.ids(filters=FilterValues(genre="comedy"), union_list_ids=(linked.pk,)),
            {item.pk, pinned.pk},
        )


class CrossProviderAliasTests(LibraryQueryTestCase):
    """A TMDB show whose TVDB alias is also listed is hidden (#639)."""

    def test_single_provider_does_not_materialize_alias_candidates(self):
        items = [
            Item.objects.create(
                media_id=str(9000 + index),
                source=Sources.TMDB.value,
                media_type=MediaTypes.TV.value,
                title=f"Show {index}",
                provider_external_ids={"tvdb_id": str(index)},
            )
            for index in range(25)
        ]
        query = LibraryQuery(media_types=(MediaTypes.TV.value,))
        executor = LibraryQueryExecutor(self.user, query)
        with mock.patch.object(Item, "from_db", wraps=Item.from_db) as hydrate:
            hidden = executor._cross_provider_hidden_ids(
                Item.objects.filter(pk__in=[item.pk for item in items])
            )
        self.assertEqual(hidden, set())
        hydrate.assert_not_called()

    def test_tmdb_alias_is_hidden(self):
        """Only the preferred provider's identity is listed."""
        tvdb = Item.objects.create(
            media_id="555", source=Sources.TVDB.value, media_type=MediaTypes.TV.value,
            title="Show", image="https://example.com/i.jpg",
        )
        tmdb = Item.objects.create(
            media_id="42", source=Sources.TMDB.value, media_type=MediaTypes.TV.value,
            title="Show", image="https://example.com/i.jpg",
            provider_external_ids={"tvdb_id": "555"},
        )
        for item in (tvdb, tmdb):
            self.track(item, model=TV, status=Status.IN_PROGRESS.value)
        self.user.tv_metadata_source_default = Sources.TVDB.value
        query = LibraryQuery(media_types=(MediaTypes.TV.value,))
        self.assertEqual(LibraryQueryExecutor(self.user, query).ids(), {tvdb.pk})
        query = LibraryQuery(media_types=(MediaTypes.TV.value,), dedupe_cross_provider=False)
        self.assertEqual(LibraryQueryExecutor(self.user, query).ids(), {tvdb.pk, tmdb.pk})


class PageCostTests(LibraryQueryTestCase):
    """A page costs the same however large the library is."""

    def _queries_for_page(self, query):
        with CaptureQueriesContext(connection) as ctx:
            LibraryQueryExecutor(self.user, query).page(0, 10)
        return ctx.captured_queries

    def test_sql_path_query_count_does_not_scale(self):
        """Filtering, ordering, COUNT and LIMIT all run in the database."""
        query = _query(
            filters=FilterValues(statuses=(Status.COMPLETED.value,), genre="drama"),
            sort=SortSpec("score", "desc"),
        )
        self.library(12)
        small = self._queries_for_page(query)
        self.library(120, start=12)
        big = self._queries_for_page(query)
        self.assertEqual(len(small), len(big))
        self.assertTrue(any("LIMIT 10" in q["sql"] for q in big))

    def test_scan_path_hydrates_only_batches_and_the_page(self):
        """Tracker rows are loaded per batch, never for the whole library at once."""
        self.library(60)
        seen_batch_sizes = []
        original = executor_module._attach_media

        def spy(user, batch, needs):
            seen_batch_sizes.append(len(batch))
            return original(user, batch, needs)

        query = _query(sort=SortSpec("time_to_beat", "asc"))
        with mock.patch.object(executor_module, "_attach_media", spy):
            page = LibraryQueryExecutor(self.user, query, batch_size=16).page(0, 10)
        self.assertFalse(page.used_sql)
        self.assertEqual(page.total, 60)
        self.assertEqual(len(page.items), 10)
        self.assertTrue(seen_batch_sizes)
        self.assertLessEqual(max(seen_batch_sizes), 16)
