"""Structural bounds on what a media-list request pulls into memory.

Production served two `GET /medialist/movie` requests in 108 and 125
seconds, using eleven SQL queries each, and retired the worker immediately
afterwards. Eleven queries is not an N+1 problem; it is a small number of
queries each returning far more than the page needs. So the regressions worth
pinning here are about *width* and *scale*, not about query count -- a count
budget stays green while one query quietly starts decoding hundreds of MiB of
JSON.

Two of those queries are covered here:

* the duplicate-entry aggregation, which filters by item id rather than by
  page and so touches every tracked title on a list that is not paginated in
  SQL;
* the separate-entries ("show each play") list, whose own copy of the
  deferred-field list had drifted from the grouped path's.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.utils import timezone

from app import media_list_entry_grouping
from app.media_list_entry_grouping import entry_grouping_mode
from app.models import BasicMedia, Item, MediaTypes, Movie, Sources, Status

# The widest Item column by a wide margin: TMDB's availability for every
# region it knows, around 146 KiB a title, which no media-list template
# renders. synopsis is deliberately not in this list -- an optional table
# column does render it, so the list queryset selects it by design.
_WIDE_ITEM_COLUMNS = ("watch_providers",)


def _captured_sql(queries):
    """Return one lowercased blob of every statement captured."""
    return "\n".join(entry["sql"] for entry in queries).lower()


class MediaListProjectionTestCase(TestCase):
    """A synthetic library big enough for scaling to be visible."""

    @classmethod
    def setUpTestData(cls):
        """Build a library whose rows carry real payload in the wide columns."""
        cls.user = get_user_model().objects.create_user(
            username="projection",
            password="12345",  # a test fixture
        )
        # A realistic watch_providers blob: the point of the deferral is that
        # this is large, so a test with {} would pass either way.
        providers = {
            f"R{region:02d}": {
                "flatrate": [
                    {"provider_id": index, "provider_name": f"Provider {index}"}
                    for index in range(20)
                ],
            }
            for region in range(40)
        }
        cls.items = Item.objects.bulk_create(
            [
                Item(
                    media_id=f"projection-{index}",
                    source=Sources.TMDB.value,
                    media_type=MediaTypes.MOVIE.value,
                    title=f"Projection Movie {index:04d}",
                    synopsis="x" * 4000,
                    watch_providers=providers,
                )
                for index in range(60)
            ],
        )
        now = timezone.now()
        # Two entries per item, so every row goes through the duplicate
        # aggregation path rather than short-circuiting on a single entry.
        Movie.objects.bulk_create(
            [
                Movie(
                    item=item,
                    user=cls.user,
                    status=Status.COMPLETED.value,
                    progress=1,
                    end_date=now - timedelta(days=offset + 1),
                )
                for item in cls.items
                for offset in range(2)
            ],
        )

    def media_list(self, **overrides):
        """Return the manager's media list for this fixture."""
        kwargs = {
            "user": self.user,
            "media_type": MediaTypes.MOVIE.value,
            "status_filter": None,
            "sort_filter": "title",
            "direction": "asc",
        }
        kwargs.update(overrides)
        return BasicMedia.objects.get_media_list(**kwargs)


class DuplicateAggregationProjectionTests(MediaListProjectionTestCase):
    """The aggregation pass reads scalars; it must not fetch a library of rows."""

    def test_aggregation_query_does_not_join_the_item_table(self):
        """The pass that touches every tracked title must fetch scalars only.

        This is the regression that made a few queries cost minutes. The
        filter is by item id, not by page, so on a list that is not paginated
        in SQL it returns a row per tracked title -- and it used to
        select_related("item") with no deferral, hydrating a full Item, wide
        JSON columns and all, for every one of them.

        Asserted against the aggregation directly rather than through the
        whole view: the display queryset legitimately joins app_item, so a
        blanket assertion over every statement would prove nothing about this
        one.
        """
        # select_related as every real caller does: _aggregate_item_data reads
        # media_type off the *displayed* row, so an unrelated row here would
        # fetch its own Item and the assertion would be about the fixture.
        display_rows = list(
            Movie.objects.filter(user=self.user).select_related("item"),
        )

        with self.settings(DEBUG=True):
            connection.queries_log.clear()
            BasicMedia.objects._aggregate_duplicate_data(
                display_rows,
                self.user,
                MediaTypes.MOVIE.value,
            )
            sql = _captured_sql(connection.queries_log)

        self.assertIn("app_movie", sql)
        self.assertNotIn("app_item", sql)

    def test_no_media_list_query_selects_watch_providers(self):
        """The widest column on the table stays out of every list query."""
        with self.settings(DEBUG=True):
            connection.queries_log.clear()
            list(self.media_list())
            sql = _captured_sql(connection.queries_log)

        for column in _WIDE_ITEM_COLUMNS:
            self.assertNotIn(
                f'"{column}"',
                sql,
                f"{column} must not be selected by a media-list query",
            )

    def test_aggregation_does_not_hydrate_item_rows(self):
        """Reading the aggregated result must not trigger deferred loads.

        `.only()` degrades to a lazy query rather than an error, so a future
        reader of ``entry.item`` would not fail -- it would silently reintroduce
        one query per duplicate group. Assert the absence instead.
        """
        entries = list(self.media_list())

        with self.assertNumQueries(0):
            for entry in entries:
                self.assertIsNotNone(entry.aggregated_progress)
                self.assertIsNotNone(entry.repeats)

    def test_aggregated_date_added_is_the_earliest_entry(self):
        """A grouped row's Date added is when the item was first tracked."""
        for entry in self.media_list():
            earliest = (
                Movie.objects.filter(user=self.user, item=entry.item)
                .order_by("created_at")
                .first()
                .created_at
            )
            self.assertEqual(entry.aggregated_created_at, earliest)

    def test_aggregation_result_is_unchanged_by_the_narrower_projection(self):
        """Narrowing the columns must not change a single aggregated value.

        The old projection is reconstructed here and the aggregation run
        against both, so this compares behaviour rather than restating it.
        """
        narrow = {
            entry.item_id: (
                entry.aggregated_progress,
                entry.aggregated_status,
                entry.aggregated_score,
                entry.aggregated_start_date,
                entry.aggregated_end_date,
                entry.repeats,
            )
            for entry in self.media_list()
        }

        manager = BasicMedia.objects
        display_rows = list(
            Movie.objects.filter(user=self.user).select_related("item"),
        )
        wide_groups = {}
        for row in Movie.objects.filter(user=self.user).select_related("item"):
            wide_groups.setdefault(row.item_id, []).append(row)
        seen = {}
        for row in display_rows:
            entries = wide_groups.get(row.item_id, [])
            if len(entries) > 1:
                manager._aggregate_item_data(row, entries)
            seen[row.item_id] = (
                row.aggregated_progress,
                row.aggregated_status,
                row.aggregated_score,
                row.aggregated_start_date,
                row.aggregated_end_date,
                row.repeats,
            )

        self.assertEqual(narrow, seen)

    def test_query_count_does_not_grow_with_library_size(self):
        """Adding titles must not add queries: the bound is width, not count."""
        with self.settings(DEBUG=True):
            connection.queries_log.clear()
            list(self.media_list())
            before = len(connection.queries_log)

        more = Item.objects.bulk_create(
            [
                Item(
                    media_id=f"projection-extra-{index}",
                    source=Sources.TMDB.value,
                    media_type=MediaTypes.MOVIE.value,
                    title=f"Projection Extra {index:04d}",
                )
                for index in range(60)
            ],
        )
        Movie.objects.bulk_create(
            [
                Movie(
                    item=item,
                    user=self.user,
                    status=Status.COMPLETED.value,
                    progress=1,
                    end_date=timezone.now() - timedelta(days=offset + 1),
                )
                for item in more
                for offset in range(2)
            ],
        )

        with self.settings(DEBUG=True):
            connection.queries_log.clear()
            list(self.media_list())
            after = len(connection.queries_log)

        self.assertEqual(before, after)


class SeparateEntriesProjectionTests(MediaListProjectionTestCase):
    """"Show each play separately" must defer the same columns as grouping."""

    def test_separate_mode_defers_watch_providers(self):
        """The drifted local copy of the deferral list is the regression.

        This mode is reachable only through the wrapper route -- the direct
        view calls the rest of the suite makes never enter it -- so nothing
        else covers it.
        """
        with self.settings(DEBUG=True), entry_grouping_mode(True):
            connection.queries_log.clear()
            rows = list(self.media_list())
            sql = _captured_sql(connection.queries_log)

        self.assertTrue(rows)
        for column in _WIDE_ITEM_COLUMNS:
            self.assertNotIn(f'"{column}"', sql)

    def test_separate_mode_still_loads_providers_when_the_filter_needs_them(self):
        """Deferral is per request: the provider filter is the one reader."""
        with self.settings(DEBUG=True), entry_grouping_mode(True):
            connection.queries_log.clear()
            list(self.media_list(needs_watch_providers=True))
            sql = _captured_sql(connection.queries_log)

        self.assertIn('"watch_providers"', sql)

    def test_separate_mode_returns_one_row_per_entry(self):
        """The projection change must not alter what the mode is for."""
        with entry_grouping_mode(True):
            separate = list(self.media_list())
        grouped = list(self.media_list())

        self.assertEqual(len(grouped), len(self.items))
        self.assertEqual(len(separate), len(self.items) * 2)

    def test_the_deferral_list_has_exactly_one_definition(self):
        """The copy that drifted is gone, not merely corrected."""
        self.assertFalse(
            hasattr(media_list_entry_grouping, "_DEFERRED_ITEM_FIELDS"),
            "entry grouping must read the manager's definition, not a copy",
        )
