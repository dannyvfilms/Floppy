from dataclasses import replace
from decimal import Decimal
from http import HTTPStatus as HTTP  # noqa: N814
from unittest import mock

from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from app import image_cache
from app.media_list_filters import MediaListFilters
from app.models import (
    TV,
    CollectionEntry,
    Episode,
    Game,
    Item,
    ItemTag,
    MediaTypes,
    Season,
    Sources,
    Status,
    Tag,
)
from events.models import Event
from lists.models import CustomListItem
from users import home_screen
from users.models import HomeScreenRow, HomeScreenRowTypeChoices

from .base import FloppyApiTestCase


class MediaListFilterParityTests(FloppyApiTestCase):
    """The API media lists share the web filter and next-episode semantics."""

    def setUp(self):
        """Create released, future, and dropped TV episode cases."""
        super().setUp()
        now = timezone.now()
        tv1 = self.tv_medias[0]
        tv2 = self.tv_medias[1]
        tv3 = self.tv_medias[2]
        TV.objects.filter(pk=tv1.pk).update(status=Status.IN_PROGRESS.value)
        TV.objects.filter(pk=tv2.pk).update(status=Status.COMPLETED.value)
        TV.objects.filter(pk=tv3.pk).update(status=Status.IN_PROGRESS.value)

        season1 = self.season_medias[0]
        season2 = self.season_medias[1]
        Season.objects.filter(pk=season1.pk).update(status=Status.IN_PROGRESS.value)
        Season.objects.filter(pk=season2.pk).update(status=Status.DROPPED.value)
        self.episode_medias[0].__class__.objects.filter(
            related_season=season1,
        ).update(status=Status.PLANNING.value, end_date=None)
        Event.objects.create(
            item=season1.item,
            content_number=1,
            datetime=now - timezone.timedelta(days=3),
        )
        Event.objects.create(
            item=season1.item,
            content_number=2,
            datetime=now - timezone.timedelta(days=1),
        )
        Event.objects.create(
            item=season1.item,
            content_number=3,
            datetime=now + timezone.timedelta(days=3),
        )
        Event.objects.create(
            item=season2.item,
            content_number=1,
            datetime=now - timezone.timedelta(days=1),
        )
        self.episode_medias[0].__class__.objects.filter(
            pk=self.episode_medias[0].pk,
        ).update(
            status=Status.COMPLETED.value,
            end_date=now - timezone.timedelta(hours=1),
        )

        future_item = Item.objects.create(
            media_id=tv3.item.media_id,
            source=tv3.item.source,
            media_type="season",
            title=tv3.item.title,
            image=tv3.item.image,
            season_number=1,
        )
        Season.objects.create(
            item=future_item,
            user=self.user1,
            related_tv=tv3,
            status=Status.IN_PROGRESS.value,
        )
        Event.objects.create(
            item=future_item,
            content_number=1,
            datetime=now + timezone.timedelta(days=10),
        )

    def _get_tv(self, **params):
        """Return a typed media-list response."""
        return self.client.get(
            "/api/v1/media/tv/",
            params,
            **self.auth_headers,
        )

    def test_not_caught_up_serializes_first_released_unwatched_episode(self):
        """Released episodes are returned while future-only episodes are not metadata."""
        response = self._get_tv(
            status="1",
            progress="not_caught_up",
            sort="next_episode_air_date",
            direction="asc",
        )
        self.assertEqual(response.status_code, HTTP.OK)
        results = {entry["item"]["media_id"]: entry for entry in response.json()["results"]}
        self.assertIn("1001", results, response.json())
        self.assertEqual(results["1001"]["next_episode"]["season_number"], 1)
        self.assertEqual(results["1001"]["next_episode"]["episode_number"], 2)
        self.assertIsNotNone(results["1001"]["next_episode"]["air_date"])
        self.assertIsNone(results["1003"]["next_episode"])
        # The base fixture has a real S01E02 Item (episode_medias), so
        # next_episode enriches from it instead of only carrying numbers.
        next_episode = results["1001"]["next_episode"]
        self.assertEqual(next_episode["image"], "https://example.com/episode-2.jpg")
        self.assertIn("ids", next_episode)
        self.assertIsNotNone(next_episode["url"])
        self.assertEqual(next_episode["episode_code"], "S01E02")
        # That Item carries the show's title as a placeholder, which is not
        # the episode's name, and nothing else knows the name (#1281).
        self.assertIsNone(next_episode["title"])

    def test_historical_repeats_do_not_lower_fully_watched_show_progress(self):
        """Uneven historical plays must agree across API, dashboard and Home (#1584)."""
        season = self.season_medias[0]
        watched_at = timezone.now() - timezone.timedelta(days=1)
        Event.objects.filter(item=season.item).update(datetime=watched_at)
        Episode.objects.filter(related_season=season).update(
            status=Status.COMPLETED.value,
            end_date=watched_at,
        )
        Episode.objects.bulk_create([
            Episode(
                item=episode.item,
                related_season=season,
                status=Status.COMPLETED.value,
                end_date=watched_at,
            )
            for episode in self.episode_medias[:2]
        ])

        response = self._get_tv(progress="caught_up")
        self.assertEqual(response.status_code, HTTP.OK)
        results = {entry["item"]["media_id"]: entry for entry in response.json()["results"]}
        self.assertIn("1001", results)
        self.assertEqual(results["1001"]["progress"], 3)
        self.assertEqual(results["1001"]["episodes_left"], 0)
        self.assertIsNone(results["1001"]["next_episode"])
        response = self._get_tv(progress="not_caught_up")
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertNotIn(
            "1001", [entry["item"]["media_id"] for entry in response.json()["results"]],
        )

        self.client.force_login(self.user1)
        response = self.client.get(
            reverse("medialist", args=["tv"]), {"progress": "not_caught_up"},
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertNotIn(
            "1001", [entry.item.media_id for entry in response.context["media_list"].object_list],
        )
        row = HomeScreenRow.objects.create(
            user=self.user1,
            media_type="tv",
            position=0,
            row_type=HomeScreenRowTypeChoices.LIBRARY_QUERY,
            filters={"progress": "not_caught_up"},
        )
        section = home_screen._build_row_section(self.user1, row, "tv", 14)
        self.assertNotIn(
            self.tv_medias[0].item_id, [entry.item.pk for entry in section["items"]],
        )
        row.filters = {"progress": "caught_up"}
        row.save()
        cache.clear()
        section = home_screen._build_row_section(self.user1, row, "tv", 14)
        caught_up = {
            entry.item.pk: entry for entry in section["items"]
        }
        self.assertIn(self.tv_medias[0].item_id, caught_up)
        self.assertEqual(caught_up[self.tv_medias[0].item_id].media.progress, 3)

    def _next_episode_1001(self):
        response = self._get_tv(
            status="1",
            progress="not_caught_up",
            sort="next_episode_air_date",
            direction="asc",
        )
        self.assertEqual(response.status_code, HTTP.OK)
        results = {entry["item"]["media_id"]: entry for entry in response.json()["results"]}
        return results["1001"]["next_episode"]

    def test_next_episode_title_is_the_stored_episode_name(self):
        """A stored episode name is returned as the next episode's title."""
        Item.objects.filter(
            media_id="1001",
            media_type="episode",
            season_number=1,
            episode_number=2,
        ).update(title="The Second One")
        self.assertEqual(self._next_episode_1001()["title"], "The Second One")

    def test_next_episode_title_prefers_a_named_duplicate_item(self):
        """A duplicate Item with the real name wins over the show-title placeholder."""
        Item.objects.create(
            media_id="1001",
            source=Sources.TMDB.value,
            media_type="episode",
            library_media_type="tv",
            title="The Second One",
            season_number=1,
            episode_number=2,
        )
        self.assertEqual(self._next_episode_1001()["title"], "The Second One")

    def test_next_episode_title_falls_back_to_cached_season(self):
        """The cached TMDB season names the episode when no Item does."""
        from django.core.cache import cache

        from app.providers.tmdb import _season_cache_key

        cache.set(
            _season_cache_key("1001", 1),
            {"episodes": [{"episode_number": 2, "name": "Cached Name"}]},
        )
        self.addCleanup(cache.delete, _season_cache_key("1001", 1))
        with mock.patch("app.providers.services.api_request") as api_request:
            self.assertEqual(self._next_episode_1001()["title"], "Cached Name")
        api_request.assert_not_called()

    def test_next_episode_cached_titles_are_read_once_per_page(self):
        """A page resolves every cached season in one get_many, not a get per row."""
        from django.core.cache import cache

        with (
            mock.patch.object(cache, "get_many", wraps=cache.get_many) as get_many,
            mock.patch.object(cache, "get", wraps=cache.get) as get,
        ):
            self._next_episode_1001()
        season_keys = [
            call.args[0]
            for call in get.call_args_list
            if "_season_" in str(call.args[0])
        ]
        self.assertEqual(season_keys, [])
        self.assertEqual(get_many.call_count, 1)

    def test_season_row_ignores_the_show_title_placeholder(self):
        """A season row titled "Season 1" still treats the show title as a placeholder."""
        from app.media_list_filters import next_episode_for_media

        season = self.season_medias[0]
        Item.objects.filter(pk=season.item.pk).update(title="Season 1")
        season.refresh_from_db()
        season.item.refresh_from_db()
        next_episode = next_episode_for_media(season)
        self.assertEqual(next_episode["episode_number"], 2)
        self.assertIsNone(next_episode["title"])

    def test_next_episode_missing_item_degrades_gracefully(self):
        """No matching local Item leaves enrichment fields None/empty, not a 500."""
        tv1 = self.tv_medias[0]
        Item.objects.filter(
            media_id=tv1.item.media_id,
            source=tv1.item.source,
            media_type="episode",
            season_number=1,
            episode_number=2,
        ).delete()
        response = self._get_tv(
            status="1",
            progress="not_caught_up",
            sort="next_episode_air_date",
            direction="asc",
        )
        self.assertEqual(response.status_code, HTTP.OK)
        results = {entry["item"]["media_id"]: entry for entry in response.json()["results"]}
        next_episode = results["1001"]["next_episode"]
        self.assertIsNone(next_episode["title"])
        self.assertIsNone(next_episode["image"])
        self.assertEqual(next_episode["ids"], {})
        self.assertIsNone(next_episode["url"])

    def test_repeated_statuses_and_pagination_are_backward_compatible(self):
        """Repeated status values and limit/offset pagination preserve the contract."""
        response = self._get_tv(
            status=["1", "3"],
            sort="title_desc",
            limit=1,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertGreaterEqual(response.json()["pagination"]["total"], 2)
        next_url = response.json()["pagination"]["next"]
        self.assertIn("status=1", next_url)
        self.assertIn("status=3", next_url)

    def test_statusless_collection_and_tag_filters(self):
        """Collection-backed statusless items participate in the shared filters."""
        movie_item = Item.objects.create(
            media_id="704",
            source="tmdb",
            media_type="movie",
            title="Collected only movie",
            image="https://example.com/movie-4.jpg",
        )
        CollectionEntry.objects.create(
            user=self.user1,
            item=movie_item,
            media_type="digital",
            resolution="1080p",
        )
        tag = Tag.objects.create(user=self.user1, name="favorite")
        ItemTag.objects.create(tag=tag, item=movie_item)
        response = self.client.get(
            "/api/v1/media/movie/",
            {
                "status": "no_status",
                "collection": "collected",
                "tag": "favorite",
            },
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["pagination"]["total"], 1, response.json())
        result = response.json()["results"][0]
        self.assertFalse(result["tracked"])
        self.assertIsNone(result["next_episode"])

    def test_metadata_and_type_specific_filters(self):
        """Metadata filters compose and platform modes remain type-specific."""
        movie_item = self.items_by_type["movie"][0]
        release_datetime = timezone.now() - timezone.timedelta(days=2)
        Item.objects.filter(pk=movie_item.pk).update(
            genres=["Drama"],
            release_datetime=release_datetime,
            country="US",
            languages=["en"],
            authors=[{"name": "A. Author"}],
            format="digital",
            status="released",
        )
        filter_params = {
            "search": "Movie 1",
            "genre": "Drama",
            "year": str(release_datetime.year),
            "release": "released",
            "source": "tmdb",
            "media_status": "released",
            "language": "en",
            "country": "US",
            "origin": "US",
            "format": "digital",
            "author": "A. Author",
            "rating": "rated",
        }
        for name, value in filter_params.items():
            single_response = self.client.get(
                "/api/v1/media/movie/",
                {name: value},
                **self.auth_headers,
            )
            self.assertEqual(
                single_response.status_code,
                HTTP.OK,
                {
                    name: single_response.json(),
                    "exc_info": getattr(single_response, "exc_info", None),
                },
            )
        response = self.client.get(
            "/api/v1/media/movie/",
            filter_params,
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK, response.json())
        self.assertEqual(response.json()["pagination"]["total"], 1)

        game_item = self.items_by_type["game"][0]
        Item.objects.filter(pk=game_item.pk).update(platforms=["PC", "Switch"])
        response = self.client.get(
            "/api/v1/media/game/",
            {
                "platform": ["PC", "Switch"],
                "platform_mode": "and",
            },
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["pagination"]["total"], 1)

    def test_completed_date_filter_differs_from_release_year(self):
        """completed_date_from/to matches end_date, independent of release year."""
        movie_item = self.items_by_type["movie"][0]
        movie = self.movie_medias[0]
        Item.objects.filter(pk=movie_item.pk).update(
            release_datetime=timezone.datetime(1999, 1, 1, tzinfo=timezone.get_default_timezone()),
        )
        movie.__class__.objects.filter(pk=movie.pk).update(
            end_date=timezone.datetime(2025, 6, 15, tzinfo=timezone.get_default_timezone()),
        )

        response = self.client.get(
            "/api/v1/media/movie/",
            {
                "completed_date_from": "2025-06-01",
                "completed_date_to": "2025-06-30",
            },
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK, response.json())
        result_media_ids = {
            entry["item"]["media_id"] for entry in response.json()["results"]
        }
        self.assertIn(movie_item.media_id, result_media_ids)

        response = self.client.get(
            "/api/v1/media/movie/",
            {
                "completed_date_from": "1999-01-01",
                "completed_date_to": "1999-12-31",
            },
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK, response.json())
        result_media_ids = {
            entry["item"]["media_id"] for entry in response.json()["results"]
        }
        self.assertNotIn(movie_item.media_id, result_media_ids)

    def test_invalid_filter_values_return_bad_request(self):
        """Invalid filter choices are explicit API errors instead of ignored filters."""
        for params in (
            {"status": "watched"},
            {"platform_mode": "xor"},
            {"tag_mode": "xor"},
            {"direction": "sideways"},
            {"year": "20"},
            {"completed_date_from": "not-a-date"},
            {"completed_date_to": "2025-13-40"},
        ):
            response = self._get_tv(**params)
            self.assertEqual(response.status_code, HTTP.BAD_REQUEST, params)


class MediaListQueryBudgetTests(FloppyApiTestCase):
    """Pin the query count for a paginated media-list page (#1004).

    Serializing a page must not scale with the size of the user's whole
    library — regression test for a per-page-item N+1 caused by Item fields
    that `get_media_list` defers for the list scan but `ItemSerializer`
    (via `MediaSerializer`) reads in full.
    """

    def _seed_extra_games(self, count, *, start=0):
        for index in range(start, start + count):
            item = Item.objects.create(
                media_id=f"query-budget-game-{index}",
                source=Sources.IGDB.value,
                media_type=MediaTypes.GAME.value,
                title=f"Query Budget Game {index}",
            )
            Game.objects.create(item=item, user=self.user1)

    def test_query_count_does_not_scale_with_library_size(self):
        self._seed_extra_games(5)
        # Warm the lazily cached image-caching toggle (5-minute TTL, shared
        # across tests) so neither count depends on which test ran before.
        image_cache.is_enabled()
        with CaptureQueriesContext(connection) as small_ctx:
            response = self.client.get(
                "/api/v1/media/game/",
                {"limit": 10},
                **self.auth_headers,
            )
        self.assertEqual(response.status_code, HTTP.OK)
        small_queries = len(small_ctx.captured_queries)

        self._seed_extra_games(120, start=5)
        # Warm the lazily cached image-caching toggle (5-minute TTL, shared
        # across tests) so neither count depends on which test ran before.
        image_cache.is_enabled()
        with CaptureQueriesContext(connection) as big_ctx:
            response = self.client.get(
                "/api/v1/media/game/",
                {"limit": 10},
                **self.auth_headers,
            )
        self.assertEqual(response.status_code, HTTP.OK)
        big_queries = len(big_ctx.captured_queries)

        self.assertEqual(len(response.json()["results"]), 10)
        self.assertLessEqual(
            big_queries,
            small_queries + 2,
            f"query count grew from {small_queries} to {big_queries} as the "
            "library grew — page serialization is scaling with library size "
            "again, not just the requested page.",
        )
        self.assertLessEqual(
            big_queries,
            30,
            f"{big_queries} queries for a 10-item page; budget is 30. If "
            "this increase is intentional, update the pin deliberately.",
        )

    def test_list_membership_lookup_is_batched(self):
        """build_lists_by_item_id must not issue one query per page item (#1004)."""
        self._seed_extra_games(10)
        game_items = list(
            Item.objects.filter(
                media_type=MediaTypes.GAME.value,
                media_id__startswith="query-budget-game-",
            ).order_by("media_id")[:10],
        )
        favorites = self.lists_by_name["favorites"]
        CustomListItem.objects.bulk_create(
            [CustomListItem(custom_list=favorites, item=item) for item in game_items],
        )

        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(
                "/api/v1/media/game/",
                {"limit": 10},
                **self.auth_headers,
            )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(len(response.json()["results"]), 10)

        list_membership_queries = [
            query
            for query in ctx.captured_queries
            if "lists_customlistitem" in query["sql"].lower()
        ]
        self.assertEqual(
            len(list_membership_queries),
            1,
            "list-membership lookup should be a single batched query "
            f"regardless of how many page items belong to a list; got "
            f"{len(list_membership_queries)}: {list_membership_queries}",
        )

    def test_collection_context_skipped_without_platform_or_format_filter(self):
        """No CollectionEntry queries fire unless platform/format filters are set (#1004)."""
        self._seed_extra_games(10)

        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(
                "/api/v1/media/game/",
                {"limit": 10},
                **self.auth_headers,
            )
        self.assertEqual(response.status_code, HTTP.OK)
        collection_queries = [
            query
            for query in ctx.captured_queries
            if "app_collectionentry" in query["sql"].lower()
        ]
        self.assertEqual(
            collection_queries,
            [],
            "unfiltered list request queried CollectionEntry despite no "
            "platform/format filter being requested.",
        )

        with CaptureQueriesContext(connection) as filtered_ctx:
            response = self.client.get(
                "/api/v1/media/game/",
                {"limit": 10, "platform": "PC"},
                **self.auth_headers,
            )
        self.assertEqual(response.status_code, HTTP.OK)
        filtered_collection_queries = [
            query
            for query in filtered_ctx.captured_queries
            if "app_collectionentry" in query["sql"].lower()
        ]
        self.assertGreater(
            len(filtered_collection_queries),
            0,
            "platform-filtered request should still query CollectionEntry.",
        )


class MediaListTagSqlFilterTests(FloppyApiTestCase):
    """Tag filtering is pushed to SQL for every media-list code path (#1004).

    Covers the bespoke Episode queryset, the primary BasicMedia queryset, and
    the anime-library "grouped" TV queryset — the three separate places tag
    filtering must apply now that it's no longer a single Python re-check
    shared by every entry regardless of which query produced it.
    """

    def test_episode_type_filters_by_tag(self):
        """The bespoke Episode queryset (no BasicMedia manager) still tag-filters."""
        tagged_item = self.episode_medias[0].item
        untagged_item = self.episode_medias[1].item
        tag = Tag.objects.create(user=self.user1, name="watch-again")
        ItemTag.objects.create(tag=tag, item=tagged_item)

        response = self.client.get(
            "/api/v1/media/episode/",
            {"tag": "watch-again"},
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        result_media_ids = {
            entry["item"]["media_id"] for entry in response.json()["results"]
        }
        self.assertIn(tagged_item.media_id, result_media_ids)
        # Untagged episode shares the same media_id/source (same show) — the
        # tag filter still narrows to the exact tagged Item row.
        untagged_ids = {
            entry["item"].get("id") for entry in response.json()["results"]
        }
        self.assertNotIn(untagged_item.id, untagged_ids)

    def test_anime_type_filters_grouped_entries_by_tag(self):
        """Tag filtering also applies to the anime-library "grouped" TV query."""
        library_mode_field = "anime_library_mode"
        self.user1.__class__.objects.filter(pk=self.user1.pk).update(
            **{library_mode_field: "both"},
        )
        tv_anime_item = self.items_by_type[MediaTypes.TV.value][0]
        tv_anime_item.library_media_type = MediaTypes.ANIME.value
        tv_anime_item.save(update_fields=["library_media_type"])
        native_anime_item = self.anime_medias[0].item

        tag = Tag.objects.create(user=self.user1, name="seasonal")
        ItemTag.objects.create(tag=tag, item=tv_anime_item)

        response = self.client.get(
            "/api/v1/media/anime/",
            {"tag": "seasonal"},
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        result_media_ids = {
            entry["item"]["media_id"] for entry in response.json()["results"]
        }
        self.assertIn(tv_anime_item.media_id, result_media_ids)
        self.assertNotIn(native_anime_item.media_id, result_media_ids)


class MediaListSqlPushdownTests(FloppyApiTestCase):
    """The SQL fast path for /api/v1/media/<type>/ (#1004).

    The reporter's own repro: ~2,500 games in one status, sorted by
    start_date, took 778ms and 75 queries because the whole status-filtered
    set was materialized (dedup window function + prefetch_related + a full
    Python filter/sort pass) before slicing to `limit`. These tests prove
    the fast path (a) actually slices in SQL instead of scanning the full
    set, and (b) produces identical ordering to the untouched Python path
    for sort keys that read cross-entry aggregates (start_date/end_date/
    score/progress), where a naive per-status window function would
    silently disagree with `_aggregate_item_data`'s "across all of the
    item's entries, any status" semantics.
    """

    def _seed_games(self, count, *, start=0, status=Status.IN_PROGRESS.value):
        for index in range(start, start + count):
            item = Item.objects.create(
                media_id=f"sql-pushdown-game-{index}",
                source=Sources.IGDB.value,
                media_type=MediaTypes.GAME.value,
                title=f"SQL Pushdown Game {index}",
            )
            Game.objects.create(item=item, user=self.user1, status=status)

    def test_fast_path_slices_in_sql_not_in_python(self):
        """A busy status doesn't get fully materialized to serve one page."""
        self._seed_games(300)

        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(
                "/api/v1/media/game/",
                {"status": "1", "limit": 10, "sort": "start_date", "direction": "asc"},
                **self.auth_headers,
            )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(len(response.json()["results"]), 10)
        self.assertEqual(response.json()["pagination"]["total"], 300)

        queries = len(ctx.captured_queries)
        self.assertLessEqual(
            queries,
            20,
            f"{queries} queries to serve a 10-item page out of a 300-row "
            "status — budget is 20. If this is intentional, update the pin.",
        )
        limited_queries = [
            query for query in ctx.captured_queries if "LIMIT 10" in query["sql"]
        ]
        self.assertTrue(
            limited_queries,
            "expected at least one captured query with a SQL LIMIT clause — "
            "pagination should happen in the database, not in Python after "
            "fetching every row. Captured SQL: "
            f"{[q['sql'] for q in ctx.captured_queries]}",
        )

    def test_fast_path_query_count_does_not_scale_with_library_size(self):
        """Same scaling proof as MediaListQueryBudgetTests, for an aggregated sort key."""
        self._seed_games(5)
        # Warm the lazily cached image-caching toggle (5-minute TTL, shared
        # across tests) so neither count depends on which test ran before.
        image_cache.is_enabled()
        with CaptureQueriesContext(connection) as small_ctx:
            response = self.client.get(
                "/api/v1/media/game/",
                {"status": "1", "limit": 10, "sort": "start_date"},
                **self.auth_headers,
            )
        self.assertEqual(response.status_code, HTTP.OK)
        small_queries = len(small_ctx.captured_queries)

        self._seed_games(200, start=5)
        # Warm the lazily cached image-caching toggle (5-minute TTL, shared
        # across tests) so neither count depends on which test ran before.
        image_cache.is_enabled()
        with CaptureQueriesContext(connection) as big_ctx:
            response = self.client.get(
                "/api/v1/media/game/",
                {"status": "1", "limit": 10, "sort": "start_date"},
                **self.auth_headers,
            )
        self.assertEqual(response.status_code, HTTP.OK)
        big_queries = len(big_ctx.captured_queries)

        self.assertLessEqual(
            big_queries,
            small_queries + 2,
            f"query count grew from {small_queries} to {big_queries} as the "
            "library grew — the SQL fast path is scaling with library size "
            "again, not just the requested page.",
        )

    def _make_item_with_plays(self, media_id, plays):
        """Create one Item with several Game rows (repeats/rewatches)."""
        item = Item.objects.create(
            media_id=media_id,
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            title=f"Repeats {media_id}",
        )
        for status, start_date, score in plays:
            Game.objects.create(
                item=item,
                user=self.user1,
                status=status,
                start_date=start_date,
                score=score,
            )
        return item

    def _ordering_for(self, params):
        response = self.client.get(
            "/api/v1/media/game/", params, **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        return [entry["item"]["media_id"] for entry in response.json()["results"]]

    def test_aggregated_start_date_sort_matches_python_baseline_with_repeats(self):
        """start_date sort reads the item's earliest entry across ALL statuses.

        Item A's earliest entry is an old DROPPED play; its IN_PROGRESS entry
        (the one visible under `status=1`) started much later. A naive
        per-status window function would see only the IN_PROGRESS row and
        rank Item A after Item B — the fast path must still use Item A's
        true earliest start_date (from the DROPPED row) to match
        `_aggregate_item_data`'s cross-status semantics, exactly like the
        untouched Python fallback path does.
        """
        item_a = self._make_item_with_plays(
            "repeats-a",
            [
                (Status.DROPPED.value, timezone.datetime(2020, 1, 1, tzinfo=timezone.get_default_timezone()), None),
                (Status.IN_PROGRESS.value, timezone.datetime(2023, 1, 1, tzinfo=timezone.get_default_timezone()), None),
            ],
        )
        item_b = self._make_item_with_plays(
            "repeats-b",
            [
                (Status.IN_PROGRESS.value, timezone.datetime(2022, 6, 1, tzinfo=timezone.get_default_timezone()), None),
            ],
        )

        params = {
            "status": "1",
            "limit": 10,
            "sort": "start_date",
            "direction": "asc",
        }
        fast_path_order = self._ordering_for(params)
        self.assertEqual(
            [item_a.media_id, item_b.media_id],
            fast_path_order,
            "Item A's aggregated start_date (2020, from its dropped play) "
            "should sort before Item B's (2022) even though only Item A's "
            "*visible* IN_PROGRESS row (2023) is later than Item B's.",
        )

    def test_aggregated_score_sort_matches_python_baseline(self):
        """Score sort uses the most-recently-active entry's score, any status."""
        item_a = self._make_item_with_plays(
            "repeats-score-a",
            [
                (
                    Status.DROPPED.value,
                    timezone.datetime(2020, 1, 1, tzinfo=timezone.get_default_timezone()),
                    Decimal("3.0"),
                ),
                (
                    Status.IN_PROGRESS.value,
                    timezone.datetime(2024, 1, 1, tzinfo=timezone.get_default_timezone()),
                    None,
                ),
            ],
        )
        item_b = self._make_item_with_plays(
            "repeats-score-b",
            [
                (
                    Status.IN_PROGRESS.value,
                    timezone.datetime(2022, 6, 1, tzinfo=timezone.get_default_timezone()),
                    Decimal("8.0"),
                ),
            ],
        )

        params = {"status": "1", "limit": 10, "sort": "score", "direction": "desc"}
        fast_path_order = self._ordering_for(params)
        # Item A's aggregated score falls back to its dropped play's score
        # (3.0) since its visible in_progress row has no score of its own —
        # still below Item B's 8.0.
        self.assertEqual([item_b.media_id, item_a.media_id], fast_path_order)

    def test_python_only_filters_answer_normally(self):
        """Rating, collection and author requests page like any other."""
        self._seed_games(3)
        for params in (
            {"status": "1", "rating": "rated"},
            {"status": "1", "collection": "collected"},
            {"status": "1", "sort": "author"},
        ):
            response = self.client.get(
                "/api/v1/media/game/", params, **self.auth_headers,
            )
            self.assertEqual(response.status_code, HTTP.OK, params)
