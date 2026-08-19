import json
import time
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from app.models import (
    TV,
    CollectionEntry,
    Episode,
    Game,
    Item,
    ItemTag,
    MediaTypes,
    Movie,
    Season,
    Sources,
    Status,
    Tag,
)
from app.services.item_merge import dedupe_cross_provider_items
from lists import smart_rules
from lists.models import CustomList
from users import home_screen
from users.models import (
    DirectionChoices,
    HomeScreenRow,
    HomeScreenRowTypeChoices,
    HomeSortChoices,
    MediaSortChoices,
)


class HomeScreenViewTests(TestCase):
    """Tests for the Home Screen settings page."""

    def setUp(self):
        self.credentials = {"username": "testuser", "password": "testpass123"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    def _set_enabled_media_types(self, *enabled_media_types):
        enabled_set = set(enabled_media_types)
        update_fields = []
        for media_type in MediaTypes.values:
            if media_type in (
                MediaTypes.EPISODE.value,
                MediaTypes.COMIC_ISSUE.value,
            ):
                continue
            field_name = f"{media_type}_enabled"
            setattr(self.user, field_name, media_type in enabled_set)
            update_fields.append(field_name)
        self.user.save(update_fields=update_fields)

    def test_home_screen_get_only_serializes_enabled_media_types(self):
        self._set_enabled_media_types(MediaTypes.TV.value, MediaTypes.MOVIE.value)

        response = self.client.get(reverse("home_screen"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "users/home_screen.html")

        sections = json.loads(response.context["home_screen_sections_json"])
        # Season stays configurable even when its library type is disabled.
        self.assertEqual(
            [section["media_type"] for section in sections],
            ["tv", "movie", "season"],
        )
        self.assertContains(response, "Home Screen")
        self.assertContains(response, "sections: JSON.parse(")
        self.assertContains(response, "directionChoices: JSON.parse(")
        self.assertNotContains(response, 'sections: [{"media_type":')
        self.assertContains(response, "expanded: false")
        self.assertContains(response, 'x-html="section.icon_svg"')
        self.assertContains(response, "ensureSortable()")
        self.assertNotContains(
            response,
            'src="https://cdn.jsdelivr.net/npm/sortablejs@1.15.3/Sortable.min.js"',
        )
        self.assertNotContains(response, "section.rows.length === 1")
        self.assertContains(response, "Add Row")
        self.assertContains(response, "Add List")
        self.assertNotContains(response, "Add Library Row")
        self.assertNotContains(response, "Add List / Smart List")
        self.assertNotContains(response, "Add Recently Played Row")
        self.assertNotContains(response, "Enabled")

    def test_home_rows_progress_filter_ignores_dropped_tv_seasons(self):
        """Home not-caught-up rows should ignore dropped TV seasons."""
        self._set_enabled_media_types(MediaTypes.TV.value)

        dropped_caught_up_item = Item.objects.create(
            title="Dropped Seasons Caught Up",
            media_id="home-tv-dropped-caught-up",
            media_type=MediaTypes.TV.value,
            source=Sources.TMDB.value,
            image="https://example.com/tv-caught-up.jpg",
        )
        dropped_caught_up_tv = TV.objects.create(
            item=dropped_caught_up_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        still_in_progress_item = Item.objects.create(
            title="Still In Progress TV",
            media_id="home-tv-still-in-progress",
            media_type=MediaTypes.TV.value,
            source=Sources.TMDB.value,
            image="https://example.com/tv-in-progress.jpg",
        )
        still_in_progress_tv = TV.objects.create(
            item=still_in_progress_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

        now = timezone.now()
        for tv, title, season_configs in (
            (
                dropped_caught_up_tv,
                "Dropped Seasons Caught Up",
                [
                    {
                        "season_number": 1,
                        "status": Status.DROPPED.value,
                        "released_episodes": 2,
                        "watched_episodes": 0,
                    },
                    {
                        "season_number": 2,
                        "status": Status.DROPPED.value,
                        "released_episodes": 2,
                        "watched_episodes": 0,
                    },
                    {
                        "season_number": 3,
                        "status": Status.COMPLETED.value,
                        "released_episodes": 3,
                        "watched_episodes": 3,
                    },
                    {
                        "season_number": 4,
                        "status": Status.IN_PROGRESS.value,
                        "released_episodes": 2,
                        "watched_episodes": 2,
                    },
                ],
            ),
            (
                still_in_progress_tv,
                "Still In Progress TV",
                [
                    {
                        "season_number": 1,
                        "status": Status.IN_PROGRESS.value,
                        "released_episodes": 3,
                        "watched_episodes": 1,
                    },
                ],
            ),
        ):
            for season_config in season_configs:
                season_number = season_config["season_number"]
                season_item = Item.objects.create(
                    media_id=tv.item.media_id,
                    source=Sources.TMDB.value,
                    media_type=MediaTypes.SEASON.value,
                    title=f"{title} Season {season_number}",
                    image="https://example.com/tv-season.jpg",
                    season_number=season_number,
                )
                season = Season.objects.create(
                    item=season_item,
                    user=self.user,
                    related_tv=tv,
                    status=season_config["status"],
                )

                for episode_number in range(1, season_config["released_episodes"] + 1):
                    episode_item = Item.objects.create(
                        media_id=tv.item.media_id,
                        source=Sources.TMDB.value,
                        media_type=MediaTypes.EPISODE.value,
                        title=f"{title} S{season_number:02d}E{episode_number:02d}",
                        image="https://example.com/tv-episode.jpg",
                        season_number=season_number,
                        episode_number=episode_number,
                        release_datetime=now - timedelta(days=episode_number),
                    )
                    if episode_number <= season_config["watched_episodes"]:
                        Episode.objects.create(
                            item=episode_item,
                            related_season=season,
                            end_date=now - timedelta(days=episode_number),
                        )

        HomeScreenRow.objects.create(
            user=self.user,
            media_type=MediaTypes.TV.value,
            position=0,
            enabled=True,
            row_type=HomeScreenRowTypeChoices.LIBRARY_QUERY,
            sort_by=MediaSortChoices.TITLE,
            direction=DirectionChoices.ASC,
            filters={
                "status": Status.IN_PROGRESS.value,
                "progress": "not_caught_up",
            },
        )

        groups = home_screen.build_home_page_groups(self.user, items_limit=10)

        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["rows"]), 1)
        self.assertEqual(
            [entry.item.title for entry in groups[0]["rows"][0]["items"]],
            ["Still In Progress TV"],
        )

    def test_home_tv_row_with_status_all_ignores_collected_episode_items(self):
        """A TV row with status "all" shouldn't crash on collected-but-untracked episodes.

        Episodes tracked under a plain TV show carry `library_media_type="tv"`. A
        row's "status: all" library query falls back to including collection-only
        items, whose lookup matched those episode items directly by
        `library_media_type` even though the Episode model has no `user` field,
        crashing the whole home page with a 500 (issue #397).
        """
        self._set_enabled_media_types(MediaTypes.TV.value)

        tv_item = Item.objects.create(
            media_id="home-tv-episode-tracked",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.TV.value,
            title="Episode Tracked Show",
            image="https://example.com/tv-show.jpg",
        )
        TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        untracked_episode_item = Item.objects.create(
            media_id="home-tv-episode-tracked-untracked",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            library_media_type=MediaTypes.TV.value,
            title="Untracked Episode",
            image="https://example.com/tv-episode.jpg",
        )
        CollectionEntry.objects.create(user=self.user, item=untracked_episode_item)

        HomeScreenRow.objects.create(
            user=self.user,
            media_type=MediaTypes.TV.value,
            position=0,
            enabled=True,
            row_type=HomeScreenRowTypeChoices.LIBRARY_QUERY,
            sort_by=MediaSortChoices.TITLE,
            direction=DirectionChoices.ASC,
            filters={"status": "all", "progress": "all"},
        )

        groups = home_screen.build_home_page_groups(self.user, items_limit=10)

        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["rows"]), 1)
        self.assertEqual(
            [entry.item.title for entry in groups[0]["rows"][0]["items"]],
            ["Episode Tracked Show"],
        )

    @patch("app.models.providers.services.get_media_metadata")
    def test_home_in_progress_row_hides_fully_watched_stale_seasons(
        self,
        mock_get_metadata,
    ):
        """Home should derive completed status for fully watched season rows."""
        self._set_enabled_media_types(MediaTypes.SEASON.value)

        stale_season_item = Item.objects.create(
            title="Home Completed Season 1",
            media_id="home-season-stale-complete",
            media_type=MediaTypes.SEASON.value,
            source=Sources.TMDB.value,
            image="https://example.com/home-season-complete.jpg",
            season_number=1,
        )
        stale_tv_item = Item.objects.create(
            title="Home Completed Show",
            media_id="home-season-stale-complete",
            media_type=MediaTypes.TV.value,
            source=Sources.TMDB.value,
            image="https://example.com/home-season-complete.jpg",
        )
        stale_tv = TV.objects.create(
            item=stale_tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        stale_season = Season.objects.create(
            item=stale_season_item,
            user=self.user,
            related_tv=stale_tv,
            status=Status.IN_PROGRESS.value,
        )

        active_season_item = Item.objects.create(
            title="Home Active Season 1",
            media_id="home-season-active",
            media_type=MediaTypes.SEASON.value,
            source=Sources.TMDB.value,
            image="https://example.com/home-season-active.jpg",
            season_number=1,
        )
        active_tv_item = Item.objects.create(
            title="Home Active Show",
            media_id="home-season-active",
            media_type=MediaTypes.TV.value,
            source=Sources.TMDB.value,
            image="https://example.com/home-season-active.jpg",
        )
        active_tv = TV.objects.create(
            item=active_tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        active_season = Season.objects.create(
            item=active_season_item,
            user=self.user,
            related_tv=active_tv,
            status=Status.IN_PROGRESS.value,
        )

        now = timezone.now()
        for episode_number in range(1, 4):
            stale_episode_item = Item.objects.create(
                media_id=stale_season_item.media_id,
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title=f"Home Completed Season S01E{episode_number:02d}",
                image="https://example.com/home-season-episode.jpg",
                season_number=1,
                episode_number=episode_number,
                release_datetime=now - timedelta(days=episode_number),
            )
            Episode.objects.create(
                item=stale_episode_item,
                related_season=stale_season,
                end_date=now - timedelta(days=episode_number),
            )

            active_episode_item = Item.objects.create(
                media_id=active_season_item.media_id,
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title=f"Home Active Season S01E{episode_number:02d}",
                image="https://example.com/home-active-episode.jpg",
                season_number=1,
                episode_number=episode_number,
                release_datetime=now - timedelta(days=episode_number),
            )
            if episode_number == 1:
                Episode.objects.create(
                    item=active_episode_item,
                    related_season=active_season,
                    end_date=now - timedelta(days=episode_number),
                )

        mock_get_metadata.return_value = {"max_progress": 3}

        HomeScreenRow.objects.create(
            user=self.user,
            media_type=MediaTypes.SEASON.value,
            position=0,
            enabled=True,
            row_type=HomeScreenRowTypeChoices.LIBRARY_QUERY,
            sort_by=MediaSortChoices.TITLE,
            direction=DirectionChoices.ASC,
            filters={"status": Status.IN_PROGRESS.value},
        )

        groups = home_screen.build_home_page_groups(self.user, items_limit=10)

        self.assertEqual(
            [entry.item.title for entry in groups[0]["rows"][0]["items"]],
            ["Home Active Season 1"],
        )
        stale_season.refresh_from_db()
        # Rewatch protection: an in-progress season is never auto-promoted to
        # Completed in the DB; Home only derives the status for display.
        self.assertEqual(stale_season.status, Status.IN_PROGRESS.value)

    def test_library_row_status_all_includes_collected_untracked_items(self):
        self._set_enabled_media_types(MediaTypes.MOVIE.value)

        tracked_item = Item.objects.create(
            title="Home Library Tracked Movie",
            media_id="home-library-tracked-movie",
            media_type=MediaTypes.MOVIE.value,
            source=Sources.TMDB.value,
            image="https://example.com/home-library-tracked.jpg",
        )
        Movie.objects.create(
            item=tracked_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
            progress=0,
        )

        untracked_item = Item.objects.create(
            title="Home Library Untracked Movie",
            media_id="home-library-untracked-movie",
            media_type=MediaTypes.MOVIE.value,
            source=Sources.TMDB.value,
            image="https://example.com/home-library-untracked.jpg",
        )
        CollectionEntry.objects.create(
            user=self.user,
            item=untracked_item,
            media_type="digital",
        )

        HomeScreenRow.objects.create(
            user=self.user,
            media_type=MediaTypes.MOVIE.value,
            position=0,
            enabled=True,
            row_type=HomeScreenRowTypeChoices.LIBRARY_QUERY,
            sort_by=MediaSortChoices.TITLE,
            direction=DirectionChoices.ASC,
            filters={"status": "all"},
        )

        groups = home_screen.build_home_page_groups(self.user, items_limit=10)

        self.assertEqual(
            [entry.item.title for entry in groups[0]["rows"][0]["items"]],
            [
                "Home Library Tracked Movie",
                "Home Library Untracked Movie",
            ],
        )

    def test_empty_library_query_rows_build_quickly_on_cold_cache(self):
        """Regression test for #621: empty rows must not stall the home page.

        Mirrors the issue's repro (enable several default media-type rows,
        clear the cache, load the home page) but also stresses the
        collection-only-untracked resolution path with a "status: all" row
        and a sizeable CollectionEntry table across *other* media types, so
        an unscoped/per-row-repeated collection scan would show up as
        elapsed time here.
        """
        enabled_media_types = [
            MediaTypes.MOVIE.value,
            MediaTypes.TV.value,
            MediaTypes.GAME.value,
            MediaTypes.BOOK.value,
            MediaTypes.MANGA.value,
        ]
        self._set_enabled_media_types(*enabled_media_types)

        # A sizeable collection in media types unrelated to the empty rows,
        # so any unscoped CollectionEntry scan has real work to do.
        for index in range(200):
            collected_item = Item.objects.create(
                title=f"Collected Anime {index}",
                media_id=f"home-cold-cache-collected-{index}",
                media_type=MediaTypes.ANIME.value,
                source=Sources.TMDB.value,
                image="https://example.com/collected.jpg",
            )
            CollectionEntry.objects.create(user=self.user, item=collected_item)

        for media_type in enabled_media_types:
            HomeScreenRow.objects.create(
                user=self.user,
                media_type=media_type,
                position=0,
                enabled=True,
                row_type=HomeScreenRowTypeChoices.LIBRARY_QUERY,
                sort_by=MediaSortChoices.TITLE,
                direction=DirectionChoices.ASC,
                filters={"status": "all"},
            )

        start = time.perf_counter()
        groups = home_screen.build_home_page_groups(self.user, items_limit=10)
        elapsed = time.perf_counter() - start

        self.assertEqual(groups, [])
        self.assertLess(
            elapsed,
            2.0,
            f"Building only-empty home rows took {elapsed:.2f}s, "
            "which would 504 the home page after a cache clear (#621).",
        )

    def test_library_query_rows_share_one_collection_scan_per_request(self):
        """`_collection_filter_context` should run once per request, not per row.

        `_library_query_entries` always calls `collect_matching_item_ids`
        with `include_collection_only_untracked=True`, which needs the
        user's collection context whenever a row's status filter is empty.
        Building several such rows in one `build_home_page_groups` call
        must not re-scan `CollectionEntry` once per row/media type.
        """
        enabled_media_types = [
            MediaTypes.MOVIE.value,
            MediaTypes.TV.value,
            MediaTypes.GAME.value,
        ]
        self._set_enabled_media_types(*enabled_media_types)
        for media_type in enabled_media_types:
            HomeScreenRow.objects.create(
                user=self.user,
                media_type=media_type,
                position=0,
                enabled=True,
                row_type=HomeScreenRowTypeChoices.LIBRARY_QUERY,
                sort_by=MediaSortChoices.TITLE,
                direction=DirectionChoices.ASC,
                filters={"status": "all"},
            )

        with patch(
            "lists.smart_rules._collection_filter_context",
            wraps=smart_rules._collection_filter_context,
        ) as spy:
            home_screen.build_home_page_groups(self.user, items_limit=10)

        self.assertEqual(
            spy.call_count,
            1,
            "Expected one shared CollectionEntry scan per request, "
            f"got {spy.call_count} calls across {len(enabled_media_types)} rows.",
        )

    def test_cached_row_section_skips_rebuild_after_empty_sentinel(self):
        """A warm empty-row cache hit must not re-invoke the row builder."""
        self._set_enabled_media_types(MediaTypes.MOVIE.value)
        row = HomeScreenRow.objects.create(
            user=self.user,
            media_type=MediaTypes.MOVIE.value,
            position=0,
            enabled=True,
            row_type=HomeScreenRowTypeChoices.LIBRARY_QUERY,
            sort_by=MediaSortChoices.TITLE,
            direction=DirectionChoices.ASC,
            filters={"status": [Status.IN_PROGRESS.value]},
        )

        first = home_screen._cached_row_section(
            self.user, row, MediaTypes.MOVIE.value, items_limit=10,
        )
        self.assertIsNone(first)

        with patch.object(
            home_screen,
            "_build_row_section",
            side_effect=AssertionError("row builder should not run on a warm hit"),
        ):
            second = home_screen._cached_row_section(
                self.user, row, MediaTypes.MOVIE.value, items_limit=10,
            )

        self.assertIsNone(second)

    def test_home_progress_filter_excludes_collected_untracked_items(self):
        self._set_enabled_media_types(MediaTypes.TV.value)

        tracked_item = Item.objects.create(
            title="Home Progress Tracked TV",
            media_id="home-progress-tracked-tv",
            media_type=MediaTypes.TV.value,
            source=Sources.TMDB.value,
            image="https://example.com/home-progress-tracked.jpg",
        )
        tracked_tv = TV.objects.create(
            item=tracked_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        tracked_season_item = Item.objects.create(
            media_id=tracked_item.media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Home Progress Tracked TV Season 1",
            image="https://example.com/home-progress-season.jpg",
            season_number=1,
        )
        tracked_season = Season.objects.create(
            item=tracked_season_item,
            user=self.user,
            related_tv=tracked_tv,
            status=Status.IN_PROGRESS.value,
        )
        for episode_number in range(1, 4):
            episode_item = Item.objects.create(
                media_id=tracked_item.media_id,
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title=f"Home Progress Tracked TV Episode {episode_number}",
                image="https://example.com/home-progress-episode.jpg",
                season_number=1,
                episode_number=episode_number,
                release_datetime=timezone.now() - timedelta(days=episode_number),
            )
            if episode_number == 1:
                Episode.objects.create(
                    item=episode_item,
                    related_season=tracked_season,
                    end_date=timezone.now() - timedelta(days=episode_number),
                )

        Item.objects.create(
            title="Home Progress Untracked TV",
            media_id="home-progress-untracked-tv",
            media_type=MediaTypes.TV.value,
            source=Sources.TMDB.value,
            image="https://example.com/home-progress-untracked.jpg",
        )
        untracked_episode = Item.objects.create(
            media_id="home-progress-untracked-tv",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Home Progress Untracked TV Episode 1",
            image="https://example.com/home-progress-untracked-ep.jpg",
            season_number=1,
            episode_number=1,
        )
        CollectionEntry.objects.create(
            user=self.user,
            item=untracked_episode,
            media_type="digital",
        )

        HomeScreenRow.objects.create(
            user=self.user,
            media_type=MediaTypes.TV.value,
            position=0,
            enabled=True,
            row_type=HomeScreenRowTypeChoices.LIBRARY_QUERY,
            sort_by=MediaSortChoices.TITLE,
            direction=DirectionChoices.ASC,
            filters={"status": "all", "progress": "not_caught_up"},
        )

        groups = home_screen.build_home_page_groups(self.user, items_limit=10)

        self.assertEqual(
            [entry.item.title for entry in groups[0]["rows"][0]["items"]],
            ["Home Progress Tracked TV"],
        )

    def test_home_rows_support_multi_status_and_tag_filters(self):
        """Home rows use OR status matching and mode-aware tag matching."""
        self._set_enabled_media_types(MediaTypes.MOVIE.value)
        both_item = Item.objects.create(
            title="Home Action Comedy",
            media_id="home-multi-1",
            media_type=MediaTypes.MOVIE.value,
            source=Sources.TMDB.value,
        )
        action_item = Item.objects.create(
            title="Home Action",
            media_id="home-multi-2",
            media_type=MediaTypes.MOVIE.value,
            source=Sources.TMDB.value,
        )
        comedy_item = Item.objects.create(
            title="Home Comedy",
            media_id="home-multi-3",
            media_type=MediaTypes.MOVIE.value,
            source=Sources.TMDB.value,
        )
        Movie.objects.create(
            item=both_item, user=self.user, status=Status.COMPLETED.value
        )
        Movie.objects.create(
            item=action_item, user=self.user, status=Status.DROPPED.value
        )
        Movie.objects.create(
            item=comedy_item, user=self.user, status=Status.COMPLETED.value
        )
        action_tag = Tag.objects.create(user=self.user, name="Action")
        comedy_tag = Tag.objects.create(user=self.user, name="Comedy")
        ItemTag.objects.create(item=both_item, tag=action_tag)
        ItemTag.objects.create(item=both_item, tag=comedy_tag)
        ItemTag.objects.create(item=action_item, tag=action_tag)
        ItemTag.objects.create(item=comedy_item, tag=comedy_tag)

        row = HomeScreenRow.objects.create(
            user=self.user,
            media_type=MediaTypes.MOVIE.value,
            position=0,
            enabled=True,
            row_type=HomeScreenRowTypeChoices.LIBRARY_QUERY,
            sort_by=MediaSortChoices.TITLE,
            direction=DirectionChoices.ASC,
            filters={
                "status": [Status.COMPLETED.value, Status.DROPPED.value],
                "tag": ["Action", "Comedy"],
                "tag_mode": "and",
            },
        )

        entries = home_screen._library_query_entries(self.user, row)

        self.assertEqual(
            [entry.item.title for entry in entries], ["Home Action Comedy"]
        )

    def test_home_screen_settings_do_not_expose_no_status_option(self):
        self._set_enabled_media_types(MediaTypes.MOVIE.value)

        response = self.client.get(reverse("home_screen"))

        self.assertEqual(response.status_code, 200)
        sections = json.loads(response.context["home_screen_sections_json"])
        movie_section = next(
            section
            for section in sections
            if section["media_type"] == MediaTypes.MOVIE.value
        )
        status_field = next(
            field
            for field in movie_section["filter_fields"]
            if field["key"] == "status"
        )
        self.assertNotIn(
            "no_status",
            [option["value"] for option in status_field["options"]],
        )

    def test_home_filter_fields_include_collected_only_untracked_authors(self):
        self._set_enabled_media_types(MediaTypes.BOOK.value)
        untracked_book = Item.objects.create(
            title="Home Untracked Author Book",
            media_id="home-untracked-author-book",
            media_type=MediaTypes.BOOK.value,
            source=Sources.OPENLIBRARY.value,
            image="https://example.com/home-untracked-author-book.jpg",
            authors=["Author Only In Collection"],
        )
        CollectionEntry.objects.create(
            user=self.user,
            item=untracked_book,
            media_type="audiobook",
        )

        filter_fields = home_screen.build_filter_field_data(
            self.user,
            MediaTypes.BOOK.value,
        )
        author_field = next(
            field for field in filter_fields if field["key"] == "author"
        )
        self.assertIn(
            {
                "value": "Author Only In Collection",
                "label": "Author Only In Collection",
            },
            author_field["options"],
        )

    def test_planning_library_row_excludes_duplicate_item_with_newer_in_progress_status(
        self,
    ):
        self._set_enabled_media_types(MediaTypes.GAME.value)
        stale_planning_item = Item.objects.create(
            title="Multi-Session Game",
            media_id="multi-session-game",
            media_type=MediaTypes.GAME.value,
            source=Sources.IGDB.value,
            image="https://example.com/game.jpg",
        )
        visible_planning_item = Item.objects.create(
            title="Planning Only Game",
            media_id="planning-only-game",
            media_type=MediaTypes.GAME.value,
            source=Sources.IGDB.value,
            image="https://example.com/planning-game.jpg",
        )
        planning_game = Game.objects.create(
            item=stale_planning_item,
            user=self.user,
            status=Status.PLANNING.value,
        )
        in_progress_game = Game.objects.create(
            item=stale_planning_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
            progress=30,
        )
        visible_planning_game = Game.objects.create(
            item=visible_planning_item,
            user=self.user,
            status=Status.PLANNING.value,
        )
        now = timezone.now()
        Game.objects.filter(id=planning_game.id).update(
            created_at=now - timedelta(days=1),
        )
        Game.objects.filter(id=in_progress_game.id).update(created_at=now)
        Game.objects.filter(id=visible_planning_game.id).update(
            created_at=now - timedelta(days=2)
        )

        HomeScreenRow.objects.create(
            user=self.user,
            media_type=MediaTypes.GAME.value,
            position=0,
            enabled=True,
            row_type=HomeScreenRowTypeChoices.LIBRARY_QUERY,
            sort_by=MediaSortChoices.TITLE,
            direction=DirectionChoices.ASC,
            filters={"status": Status.PLANNING.value},
        )

        groups = home_screen.build_home_page_groups(self.user, items_limit=10)

        row_items = groups[0]["rows"][0]["items"]
        self.assertEqual(len(row_items), 1)
        self.assertEqual(row_items[0].item.id, visible_planning_item.id)
        self.assertEqual(row_items[0].media.id, visible_planning_game.id)
        self.assertEqual(row_items[0].media.status, Status.PLANNING.value)
        self.assertEqual(
            getattr(row_items[0].media, "aggregated_status", row_items[0].media.status),
            Status.PLANNING.value,
        )

    def test_home_screen_get_seeds_default_rows_for_show_libraries(self):
        self._set_enabled_media_types(
            MediaTypes.TV.value,
            MediaTypes.SEASON.value,
            MediaTypes.MOVIE.value,
            MediaTypes.ANIME.value,
        )

        response = self.client.get(reverse("home_screen"))

        sections = {
            section["media_type"]: section
            for section in json.loads(response.context["home_screen_sections_json"])
        }
        self.assertEqual(len(sections[MediaTypes.TV.value]["rows"]), 1)
        self.assertEqual(len(sections[MediaTypes.ANIME.value]["rows"]), 1)
        self.assertEqual(len(sections[MediaTypes.SEASON.value]["rows"]), 1)
        self.assertEqual(
            sections[MediaTypes.SEASON.value]["rows"][0]["sort_by"],
            HomeSortChoices.UPCOMING,
        )
        self.assertEqual(len(sections[MediaTypes.MOVIE.value]["rows"]), 1)
        self.assertEqual(
            sections[MediaTypes.MOVIE.value]["rows"][0]["sort_by"],
            HomeSortChoices.RECENT,
        )
        self.assertEqual(
            sections[MediaTypes.TV.value]["rows"][0]["sort_by"],
            MediaSortChoices.NEXT_EPISODE_AIR_DATE,
        )
        self.assertEqual(
            sections[MediaTypes.TV.value]["rows"][0]["direction"],
            DirectionChoices.DESC,
        )
        self.assertEqual(
            sections[MediaTypes.TV.value]["rows"][0]["filters"]["status"],
            [Status.IN_PROGRESS.value],
        )
        self.assertEqual(
            sections[MediaTypes.TV.value]["rows"][0]["filters"]["progress"],
            "not_caught_up",
        )
        self.assertEqual(
            sections[MediaTypes.TV.value]["rows"][0]["title"],
            "In Progress • Not Caught Up",
        )
        self.assertEqual(
            sections[MediaTypes.TV.value]["rows"][0]["summary"],
            "Sorted by Episode Air Date • Descending",
        )
        self.assertEqual(
            sections[MediaTypes.ANIME.value]["rows"][0]["sort_by"],
            MediaSortChoices.NEXT_EPISODE_AIR_DATE,
        )
        self.assertEqual(
            sections[MediaTypes.ANIME.value]["rows"][0]["direction"],
            DirectionChoices.DESC,
        )
        self.assertEqual(
            sections[MediaTypes.ANIME.value]["rows"][0]["filters"]["progress"],
            "not_caught_up",
        )
        self.assertIn(
            {
                "value": MediaSortChoices.NEXT_EPISODE_AIR_DATE,
                "label": "Episode Air Date",
            },
            sections[MediaTypes.TV.value]["sort_choices"][
                HomeScreenRowTypeChoices.LIBRARY_QUERY
            ],
        )
        self.assertFalse(
            HomeScreenRow.objects.filter(
                user=self.user,
                row_type=HomeScreenRowTypeChoices.RECENTLY_UNRATED,
            ).exists(),
        )

    def test_home_screen_get_upgrades_legacy_seeded_defaults(self):
        self._set_enabled_media_types(
            MediaTypes.SEASON.value,
            MediaTypes.MOVIE.value,
        )
        default_filters = {
            "status": Status.IN_PROGRESS.value,
            "rating": "all",
            "collection": "all",
            "genre": "",
            "year": "",
            "release": "all",
            "source": "",
            "language": "",
            "country": "",
            "platform": "",
            "origin": "",
            "format": "",
            "author": "",
            "tag": "",
            "tag_exclude": "",
        }
        for position, row_type in enumerate(
            [
                HomeScreenRowTypeChoices.LIBRARY_QUERY,
                HomeScreenRowTypeChoices.RECENTLY_UNRATED,
            ],
        ):
            HomeScreenRow.objects.create(
                user=self.user,
                media_type=MediaTypes.SEASON.value,
                position=position,
                enabled=True,
                row_type=row_type,
                sort_by=HomeSortChoices.UPCOMING
                if row_type == HomeScreenRowTypeChoices.LIBRARY_QUERY
                else HomeSortChoices.RECENT,
                direction="asc"
                if row_type == HomeScreenRowTypeChoices.LIBRARY_QUERY
                else "desc",
                filters=default_filters
                if row_type == HomeScreenRowTypeChoices.LIBRARY_QUERY
                else {},
            )
            HomeScreenRow.objects.create(
                user=self.user,
                media_type=MediaTypes.MOVIE.value,
                position=position,
                enabled=True,
                row_type=row_type,
                sort_by=HomeSortChoices.UPCOMING
                if row_type == HomeScreenRowTypeChoices.LIBRARY_QUERY
                else HomeSortChoices.RECENT,
                direction="asc"
                if row_type == HomeScreenRowTypeChoices.LIBRARY_QUERY
                else "desc",
                filters=default_filters
                if row_type == HomeScreenRowTypeChoices.LIBRARY_QUERY
                else {},
            )

        response = self.client.get(reverse("home_screen"))

        self.assertEqual(response.status_code, 200)
        rows = list(
            HomeScreenRow.objects.filter(user=self.user).order_by(
                "media_type", "position", "id"
            ),
        )
        self.assertEqual(
            [(row.media_type, row.row_type, row.sort_by) for row in rows],
            [
                (
                    MediaTypes.MOVIE.value,
                    HomeScreenRowTypeChoices.LIBRARY_QUERY,
                    HomeSortChoices.RECENT,
                ),
                (
                    MediaTypes.SEASON.value,
                    HomeScreenRowTypeChoices.LIBRARY_QUERY,
                    HomeSortChoices.UPCOMING,
                ),
            ],
        )

    def test_home_screen_get_upgrades_legacy_tv_and_anime_defaults(self):
        self._set_enabled_media_types(
            MediaTypes.TV.value,
            MediaTypes.ANIME.value,
        )
        default_filters = {
            "status": Status.IN_PROGRESS.value,
            "rating": "all",
            "collection": "all",
            "genre": "",
            "year": "",
            "release": "all",
            "source": "",
            "language": "",
            "country": "",
            "platform": "",
            "origin": "",
            "format": "",
            "author": "",
            "tag": "",
            "tag_exclude": "",
        }
        for media_type in (MediaTypes.TV.value, MediaTypes.ANIME.value):
            HomeScreenRow.objects.create(
                user=self.user,
                media_type=media_type,
                position=0,
                enabled=True,
                row_type=HomeScreenRowTypeChoices.LIBRARY_QUERY,
                sort_by=MediaSortChoices.TITLE,
                direction="asc",
                filters=default_filters,
            )
            HomeScreenRow.objects.create(
                user=self.user,
                media_type=media_type,
                position=1,
                enabled=True,
                row_type=HomeScreenRowTypeChoices.RECENTLY_UNRATED,
                sort_by=HomeSortChoices.RECENT,
                direction="desc",
                filters={},
            )

        response = self.client.get(reverse("home_screen"))

        self.assertEqual(response.status_code, 200)
        tv_row = HomeScreenRow.objects.get(
            user=self.user,
            media_type=MediaTypes.TV.value,
            row_type=HomeScreenRowTypeChoices.LIBRARY_QUERY,
        )
        self.assertEqual(tv_row.sort_by, MediaSortChoices.NEXT_EPISODE_AIR_DATE)
        self.assertEqual(tv_row.direction, DirectionChoices.DESC)
        self.assertEqual(tv_row.filters["status"], [Status.IN_PROGRESS.value])
        self.assertEqual(tv_row.filters["progress"], "not_caught_up")

        anime_row = HomeScreenRow.objects.get(
            user=self.user,
            media_type=MediaTypes.ANIME.value,
            row_type=HomeScreenRowTypeChoices.LIBRARY_QUERY,
        )
        self.assertEqual(anime_row.sort_by, MediaSortChoices.NEXT_EPISODE_AIR_DATE)
        self.assertEqual(anime_row.direction, DirectionChoices.DESC)
        self.assertEqual(anime_row.filters["status"], [Status.IN_PROGRESS.value])
        self.assertEqual(anime_row.filters["progress"], "not_caught_up")

    def test_home_screen_get_upgrades_single_row_legacy_tv_and_anime_defaults(self):
        self._set_enabled_media_types(
            MediaTypes.TV.value,
            MediaTypes.ANIME.value,
        )
        default_filters = {
            "status": Status.IN_PROGRESS.value,
            "rating": "all",
            "collection": "all",
            "genre": "",
            "year": "",
            "release": "all",
            "source": "",
            "language": "",
            "country": "",
            "platform": "",
            "origin": "",
            "format": "",
            "author": "",
            "tag": "",
            "tag_exclude": "",
        }
        for media_type in (MediaTypes.TV.value, MediaTypes.ANIME.value):
            HomeScreenRow.objects.create(
                user=self.user,
                media_type=media_type,
                position=0,
                enabled=True,
                row_type=HomeScreenRowTypeChoices.LIBRARY_QUERY,
                sort_by=MediaSortChoices.TITLE,
                direction=DirectionChoices.DESC,
                filters=default_filters,
            )

        response = self.client.get(reverse("home_screen"))

        self.assertEqual(response.status_code, 200)
        for media_type in (MediaTypes.TV.value, MediaTypes.ANIME.value):
            row = HomeScreenRow.objects.get(
                user=self.user,
                media_type=media_type,
                row_type=HomeScreenRowTypeChoices.LIBRARY_QUERY,
            )
            self.assertEqual(row.sort_by, MediaSortChoices.NEXT_EPISODE_AIR_DATE)
            self.assertEqual(row.direction, DirectionChoices.DESC)
            self.assertEqual(row.filters["status"], [Status.IN_PROGRESS.value])
            self.assertEqual(row.filters["progress"], "not_caught_up")

    def test_home_screen_get_upgrades_original_single_row_seeded_anime_defaults(self):
        self._set_enabled_media_types(MediaTypes.ANIME.value)

        HomeScreenRow.objects.create(
            user=self.user,
            media_type=MediaTypes.ANIME.value,
            position=0,
            enabled=True,
            row_type=HomeScreenRowTypeChoices.LIBRARY_QUERY,
            sort_by=HomeSortChoices.RECENT,
            direction=DirectionChoices.DESC,
            filters={
                "status": Status.IN_PROGRESS.value,
                "rating": "all",
                "collection": "all",
                "genre": "",
                "year": "",
                "release": "all",
                "source": "",
                "language": "",
                "country": "",
                "platform": "",
                "origin": "",
                "format": "",
                "author": "",
                "tag": "",
                "tag_exclude": "",
            },
        )

        response = self.client.get(reverse("home_screen"))

        self.assertEqual(response.status_code, 200)
        anime_row = HomeScreenRow.objects.get(
            user=self.user,
            media_type=MediaTypes.ANIME.value,
            row_type=HomeScreenRowTypeChoices.LIBRARY_QUERY,
        )
        self.assertEqual(anime_row.sort_by, MediaSortChoices.NEXT_EPISODE_AIR_DATE)
        self.assertEqual(anime_row.direction, DirectionChoices.DESC)
        self.assertEqual(anime_row.filters["status"], [Status.IN_PROGRESS.value])
        self.assertEqual(anime_row.filters["progress"], "not_caught_up")

    def test_describe_library_query_uses_static_summary_labels(self):
        """Home row summaries should not rebuild full filter-field option data."""
        filters = {
            "status": "all",
            "rating": "rated",
            "year": "unknown",
            "source": "tmdb",
            "tag_exclude": "rewatch",
        }

        with patch(
            "users.home_screen.build_filter_field_data",
            side_effect=AssertionError("summary labels should not build filter fields"),
        ):
            summary = home_screen.describe_library_query(
                filters,
                self.user,
                MediaTypes.MOVIE.value,
            )

        self.assertEqual(
            summary,
            "Library • Rated • Unknown Year • The Movie Database",
        )

    def test_home_screen_post_persists_row_configuration(self):
        self._set_enabled_media_types(MediaTypes.MOVIE.value)
        custom_list = CustomList.objects.create(name="Friday Night", owner=self.user)

        payload = [
            {
                "media_type": MediaTypes.MOVIE.value,
                "rows": [
                    {
                        "enabled": True,
                        "row_type": HomeScreenRowTypeChoices.LIBRARY_QUERY,
                        "sort_by": "title",
                        "direction": "asc",
                        "filters": {
                            "status": Status.COMPLETED.value,
                            "rating": "rated",
                            "tag": "favorite",
                        },
                    },
                    {
                        "enabled": False,
                        "row_type": HomeScreenRowTypeChoices.CUSTOM_LIST,
                        "custom_list_id": custom_list.id,
                        "sort_by": "date_added",
                        "direction": "desc",
                        "filters": {},
                    },
                    {
                        "enabled": True,
                        "row_type": HomeScreenRowTypeChoices.RECENTLY_UNRATED,
                    },
                ],
            },
        ]

        response = self.client.post(
            reverse("home_screen"),
            {"home_screen_sections": json.dumps(payload)},
        )

        self.assertRedirects(response, reverse("home_screen"))

        rows = list(
            HomeScreenRow.objects.filter(
                user=self.user,
                media_type=MediaTypes.MOVIE.value,
            ).order_by("position", "id"),
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual(
            [row.row_type for row in rows],
            [
                HomeScreenRowTypeChoices.LIBRARY_QUERY,
                HomeScreenRowTypeChoices.CUSTOM_LIST,
                HomeScreenRowTypeChoices.RECENTLY_UNRATED,
            ],
        )
        self.assertEqual(rows[0].sort_by, "title")
        self.assertEqual(rows[0].direction, "asc")
        self.assertEqual(rows[0].filters["status"], [Status.COMPLETED.value])
        self.assertEqual(rows[0].filters["rating"], "rated")
        self.assertEqual(rows[0].filters["tag"], ["favorite"])
        self.assertFalse(rows[1].enabled)
        self.assertEqual(rows[1].custom_list_id, custom_list.id)
        self.assertEqual(rows[1].sort_by, "date_added")
        self.assertEqual(rows[2].sort_by, HomeSortChoices.RECENT)

    def test_home_screen_post_persists_custom_title_and_headers_toggle(self):
        self._set_enabled_media_types(MediaTypes.MOVIE.value)

        payload = [
            {
                "media_type": MediaTypes.MOVIE.value,
                "rows": [
                    {
                        "enabled": True,
                        "custom_title": "  Rewatch Soon  ",
                        "row_type": HomeScreenRowTypeChoices.LIBRARY_QUERY,
                        "sort_by": "title",
                        "direction": "asc",
                        "filters": {"status": Status.PLANNING.value},
                    },
                ],
            },
        ]

        response = self.client.post(
            reverse("home_screen"),
            {
                "home_screen_sections": json.dumps(payload),
                "show_media_type_headers": "1",
            },
        )

        self.assertRedirects(response, reverse("home_screen"))

        row = HomeScreenRow.objects.get(
            user=self.user,
            media_type=MediaTypes.MOVIE.value,
        )
        # Stored trimmed; display title prefers the custom name.
        self.assertEqual(row.title, "Rewatch Soon")
        self.assertEqual(home_screen.row_title(row, self.user), "Rewatch Soon")
        title_main, title_detail = home_screen.home_row_header_title_parts(
            row,
            self.user,
        )
        self.assertEqual(title_main, "Rewatch Soon")
        self.assertIsNone(title_detail)

        self.user.refresh_from_db()
        self.assertTrue(self.user.home_show_media_type_headers)

    def test_home_screen_post_without_headers_checkbox_clears_toggle(self):
        self._set_enabled_media_types(MediaTypes.MOVIE.value)
        self.user.home_show_media_type_headers = True
        self.user.save(update_fields=["home_show_media_type_headers"])

        payload = [{"media_type": MediaTypes.MOVIE.value, "rows": []}]
        self.client.post(
            reverse("home_screen"),
            {"home_screen_sections": json.dumps(payload)},
        )

        self.user.refresh_from_db()
        self.assertFalse(self.user.home_show_media_type_headers)

    def test_home_screen_deleted_last_row_does_not_reseed(self):
        self._set_enabled_media_types(MediaTypes.TV.value)

        payload = [{"media_type": MediaTypes.TV.value, "rows": []}]
        self.client.post(
            reverse("home_screen"),
            {"home_screen_sections": json.dumps(payload)},
        )
        self.assertEqual(
            HomeScreenRow.objects.filter(
                user=self.user,
                media_type=MediaTypes.TV.value,
            ).count(),
            0,
        )

        response = self.client.get(reverse("home_screen"))

        self.assertEqual(
            HomeScreenRow.objects.filter(
                user=self.user,
                media_type=MediaTypes.TV.value,
            ).count(),
            0,
        )
        sections = {
            section["media_type"]: section
            for section in json.loads(response.context["home_screen_sections_json"])
        }
        self.assertEqual(sections[MediaTypes.TV.value]["rows"], [])

    def test_serialize_sections_includes_custom_title(self):
        self._set_enabled_media_types(MediaTypes.MOVIE.value)
        HomeScreenRow.objects.create(
            user=self.user,
            media_type=MediaTypes.MOVIE.value,
            position=0,
            title="My Movies",
            row_type=HomeScreenRowTypeChoices.LIBRARY_QUERY,
            sort_by="title",
            direction=DirectionChoices.ASC,
            filters={"status": Status.IN_PROGRESS.value},
        )

        response = self.client.get(reverse("home_screen"))
        sections = json.loads(response.context["home_screen_sections_json"])
        movie_section = next(
            section
            for section in sections
            if section["media_type"] == MediaTypes.MOVIE.value
        )
        first_row = movie_section["rows"][0]
        self.assertEqual(first_row["custom_title"], "My Movies")
        self.assertEqual(first_row["title"], "My Movies")

    def test_home_screen_row_direction_toggle_persists_to_settings(self):
        self._set_enabled_media_types(MediaTypes.SEASON.value)

        self.client.get(reverse("home_screen"))
        row = HomeScreenRow.objects.get(
            user=self.user,
            media_type=MediaTypes.SEASON.value,
            row_type=HomeScreenRowTypeChoices.LIBRARY_QUERY,
            position=0,
        )
        self.assertEqual(row.direction, DirectionChoices.ASC)

        response = self.client.post(
            reverse("toggle_home_screen_row_direction", args=[row.id]),
        )

        self.assertRedirects(response, reverse("home"))
        row.refresh_from_db()
        self.assertEqual(row.direction, DirectionChoices.DESC)

        settings_response = self.client.get(reverse("home_screen"))
        sections = {
            section["media_type"]: section
            for section in json.loads(
                settings_response.context["home_screen_sections_json"]
            )
        }
        self.assertEqual(
            sections[MediaTypes.SEASON.value]["rows"][0]["direction"],
            DirectionChoices.DESC,
        )

    def test_home_screen_row_direction_toggle_htmx_swaps_row_in_place(self):
        """An HTMX toggle request updates the row without a full-page redirect."""
        self._set_enabled_media_types(MediaTypes.SEASON.value)

        season_item = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Test TV Show",
            image="http://example.com/image.jpg",
            season_number=1,
        )
        season = Season.objects.create(
            item=season_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        episode_item = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Test TV Show",
            image="http://example.com/image.jpg",
            season_number=1,
            episode_number=1,
        )
        Episode.objects.create(
            item=episode_item,
            related_season=season,
            end_date=timezone.now(),
        )

        self.client.get(reverse("home_screen"))
        row = HomeScreenRow.objects.get(
            user=self.user,
            media_type=MediaTypes.SEASON.value,
            row_type=HomeScreenRowTypeChoices.LIBRARY_QUERY,
            position=0,
        )
        self.assertEqual(row.direction, DirectionChoices.ASC)

        response = self.client.post(
            reverse("toggle_home_screen_row_direction", args=[row.id]),
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("HX-Redirect", response.headers)
        self.assertContains(response, 'data-home-row-wrapper="true"')
        self.assertContains(response, 'data-home-row-sort-toggle="true"')

        row.refresh_from_db()
        self.assertEqual(row.direction, DirectionChoices.DESC)

    def test_home_screen_post_rejects_unsupported_filter_for_media_type(self):
        self._set_enabled_media_types(MediaTypes.MOVIE.value)
        self.client.get(reverse("home_screen"))
        existing_rows = HomeScreenRow.objects.filter(user=self.user).count()

        payload = [
            {
                "media_type": MediaTypes.MOVIE.value,
                "rows": [
                    {
                        "enabled": True,
                        "row_type": HomeScreenRowTypeChoices.LIBRARY_QUERY,
                        "sort_by": "title",
                        "direction": "asc",
                        "filters": {"platform": "Steam"},
                    },
                ],
            },
        ]

        response = self.client.post(
            reverse("home_screen"),
            {"home_screen_sections": json.dumps(payload)},
        )

        self.assertRedirects(response, reverse("home_screen"))
        self.assertEqual(
            HomeScreenRow.objects.filter(user=self.user).count(),
            existing_rows,
        )
        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertIn("not available for movie", str(messages[0]))

    def test_home_screen_post_rejects_inaccessible_list_reference(self):
        self._set_enabled_media_types(MediaTypes.MOVIE.value)
        other_user = get_user_model().objects.create_user(
            username="other",
            password="secret123",
        )
        other_list = CustomList.objects.create(name="Private Movies", owner=other_user)

        payload = [
            {
                "media_type": MediaTypes.MOVIE.value,
                "rows": [
                    {
                        "enabled": True,
                        "row_type": HomeScreenRowTypeChoices.CUSTOM_LIST,
                        "custom_list_id": other_list.id,
                        "sort_by": "title",
                        "direction": "asc",
                        "filters": {},
                    },
                ],
            },
        ]

        response = self.client.post(
            reverse("home_screen"),
            {"home_screen_sections": json.dumps(payload)},
        )

        self.assertRedirects(response, reverse("home_screen"))
        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertIn("Choose an accessible list", str(messages[0]))

    def test_home_screen_list_search_only_returns_accessible_lists(self):
        self._set_enabled_media_types(MediaTypes.MOVIE.value)
        owned = CustomList.objects.create(name="Weekend Watch", owner=self.user)
        smart = CustomList.objects.create(
            name="Weekend Smart",
            owner=self.user,
            is_smart=True,
            smart_media_types=[MediaTypes.MOVIE.value],
        )
        other_user = get_user_model().objects.create_user(
            username="hidden",
            password="secret123",
        )
        CustomList.objects.create(name="Weekend Hidden", owner=other_user)

        response = self.client.get(
            reverse("home_screen_list_search"),
            {"q": "Weekend", "media_type": MediaTypes.MOVIE.value},
        )

        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        returned_ids = {result["id"] for result in results}

        self.assertIn(owned.id, returned_ids)
        self.assertIn(smart.id, returned_ids)
        self.assertTrue(
            next(result for result in results if result["id"] == smart.id)["is_smart"]
        )
        self.assertEqual(len(returned_ids), 2)


class HomeScreenRandomSortTests(TestCase):
    """Tests for the Random sort option."""

    def test_get_allowed_sort_choices_includes_random(self):
        for row_type in HomeScreenRowTypeChoices.values:
            choices = home_screen.get_allowed_sort_choices(
                MediaTypes.GAME.value, row_type
            )
            self.assertIn(
                HomeSortChoices.RANDOM.value,
                {choice["value"] for choice in choices},
            )

    def test_sort_home_entries_random_returns_same_entries(self):
        items = [
            Item.objects.create(
                title=f"Random Game {i}",
                media_id=f"home-random-game-{i}",
                media_type=MediaTypes.GAME.value,
                source=Sources.IGDB.value,
                image="https://example.com/game.jpg",
            )
            for i in range(5)
        ]
        entries = [home_screen.HomeRowEntry(item=item) for item in items]

        result = home_screen.sort_home_entries(
            entries, HomeSortChoices.RANDOM.value, DirectionChoices.DESC
        )

        self.assertCountEqual(result, entries)

    def test_resolve_home_row_direction_random_does_not_raise(self):
        direction = home_screen.resolve_home_row_direction(HomeSortChoices.RANDOM.value)

        self.assertIn(direction, DirectionChoices.values)


class CrossProviderDedupTests(TestCase):
    """Home rows must not show duplicate tiles for a verified TMDB/TVDB pair (#620)."""

    def setUp(self):
        self.credentials = {"username": "dedup-user", "password": "testpass123"}
        self.user = get_user_model().objects.create_user(**self.credentials)

    def _tv_pair(self):
        tmdb_item = Item.objects.create(
            title="Breaking Bad",
            media_id="1396",
            media_type=MediaTypes.TV.value,
            source=Sources.TMDB.value,
            image="",
            provider_external_ids={"tvdb_id": "81189"},
        )
        tvdb_item = Item.objects.create(
            title="Breaking Bad",
            media_id="81189",
            media_type=MediaTypes.TV.value,
            source=Sources.TVDB.value,
            image="",
        )
        TV.objects.create(item=tmdb_item, user=self.user, status=Status.IN_PROGRESS.value)
        TV.objects.create(item=tvdb_item, user=self.user, status=Status.IN_PROGRESS.value)
        return tmdb_item, tvdb_item

    def test_prefers_tvdb_item_for_tvdb_preferring_user(self):
        tmdb_item, tvdb_item = self._tv_pair()

        result = dedupe_cross_provider_items(
            [tmdb_item, tvdb_item],
            Sources.TVDB.value,
        )

        self.assertEqual([item.pk for item in result], [tvdb_item.pk])

    def test_prefers_tmdb_item_for_tmdb_preferring_user(self):
        tmdb_item, tvdb_item = self._tv_pair()

        result = dedupe_cross_provider_items(
            [tmdb_item, tvdb_item],
            Sources.TMDB.value,
        )

        self.assertEqual([item.pk for item in result], [tmdb_item.pk])

    def test_never_collapses_on_title_alone(self):
        """Two unrelated items that merely share a title must both survive."""
        remake_item = Item.objects.create(
            title="Breaking Bad",
            media_id="999999",
            media_type=MediaTypes.TV.value,
            source=Sources.TMDB.value,
            image="",
        )
        tvdb_item = Item.objects.create(
            title="Breaking Bad",
            media_id="81189",
            media_type=MediaTypes.TV.value,
            source=Sources.TVDB.value,
            image="",
        )

        result = dedupe_cross_provider_items(
            [remake_item, tvdb_item],
            Sources.TVDB.value,
        )

        self.assertCountEqual(
            [item.pk for item in result],
            [remake_item.pk, tvdb_item.pk],
        )

    def test_library_query_entries_returns_one_entry_for_verified_pair(self):
        tmdb_item, tvdb_item = self._tv_pair()
        self.user.tv_metadata_source_default = Sources.TVDB.value
        self.user.save()

        row = HomeScreenRow.objects.create(
            user=self.user,
            media_type=MediaTypes.TV.value,
            position=0,
            enabled=True,
            row_type=HomeScreenRowTypeChoices.LIBRARY_QUERY,
            sort_by=MediaSortChoices.TITLE,
            direction=DirectionChoices.ASC,
            filters={"status": [Status.IN_PROGRESS.value]},
        )

        entries = home_screen._library_query_entries(self.user, row)

        self.assertEqual([entry.item.pk for entry in entries], [tvdb_item.pk])
