"""Display-level selection, mixed ranking, and bounded Home card loading."""

import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from django.utils import timezone

from app.library_query import FilterValues, LibraryQuery, LibraryQueryExecutor, SortSpec
from app.library_query.executor import order_rows
from app.models import (
    TV,
    Album,
    AlbumTracker,
    Artist,
    ArtistTracker,
    CollectionEntry,
    Episode,
    Item,
    ItemTag,
    Movie,
    Music,
    Podcast,
    PodcastEpisode,
    PodcastShow,
    PodcastShowTracker,
    Season,
    Sources,
    Status,
    Tag,
)
from users import home_mixed_rows, home_screen
from users.models import HomeScreenRow, HomeScreenRowTypeChoices


class MixedDisplayLevelTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = get_user_model().objects.create_user(username="mixed-levels")
        self.now = timezone.now()
        self.artist = Artist.objects.create(name="Artist A")
        self.album = Album.objects.create(title="Album B", artist=self.artist)
        self.artist_tracker = ArtistTracker.objects.bulk_create(
            [
                ArtistTracker(
                    user=self.user,
                    artist=self.artist,
                    status=Status.COMPLETED,
                    score=8,
                    end_date=self.now,
                ),
            ]
        )[0]
        self.album_tracker = AlbumTracker.objects.bulk_create(
            [
                AlbumTracker(
                    user=self.user,
                    album=self.album,
                    status=Status.COMPLETED,
                    score=7,
                    end_date=self.now - timedelta(days=1),
                ),
            ]
        )[0]
        self.show = PodcastShow.objects.create(title="Podcast C", podcast_uuid="show-c")
        self.show_tracker = PodcastShowTracker.objects.bulk_create(
            [
                PodcastShowTracker(
                    user=self.user,
                    show=self.show,
                    status=Status.COMPLETED,
                    score=6,
                    end_date=self.now - timedelta(days=2),
                ),
            ]
        )[0]
        tv_item = self.item("TV D", "tv")
        self.tv = TV.objects.bulk_create(
            [TV(user=self.user, item=tv_item, status=Status.IN_PROGRESS)]
        )[0]
        self.season_item = self.item("Season E", "season", season_number=1)
        self.season = Season.objects.bulk_create(
            [
                Season(
                    user=self.user,
                    item=self.season_item,
                    related_tv=self.tv,
                    status=Status.IN_PROGRESS,
                ),
            ]
        )[0]
        self.episode_item = self.item(
            "Episode F", "episode", season_number=1, episode_number=1
        )
        self.episode = Episode.objects.bulk_create(
            [
                Episode(
                    related_season=self.season,
                    item=self.episode_item,
                    status=Status.COMPLETED,
                    score=9,
                    end_date=self.now - timedelta(days=3),
                ),
            ]
        )[0]
        self.movie_item = self.item("Movie G", "movie")
        Movie.objects.bulk_create(
            [
                Movie(
                    user=self.user,
                    item=self.movie_item,
                    status=Status.COMPLETED,
                    score=5,
                    end_date=self.now - timedelta(days=4),
                )
            ]
        )
        self.track_item = self.item("Track H", "music")
        Music.objects.bulk_create(
            [
                Music(
                    user=self.user,
                    item=self.track_item,
                    album=self.album,
                    status=Status.COMPLETED,
                    end_date=self.now,
                )
            ]
        )
        episode = PodcastEpisode.objects.create(
            show=self.show, episode_uuid="podcast-ep", title="Podcast Episode"
        )
        self.podcast_item = self.item("Podcast Episode I", "podcast")
        Podcast.objects.bulk_create(
            [
                Podcast(
                    user=self.user,
                    item=self.podcast_item,
                    show=self.show,
                    episode=episode,
                    status=Status.COMPLETED,
                    end_date=self.now,
                )
            ]
        )
        # These tests exercise membership/ranking without provider metadata.
        for target in ("annotate_max_progress", "_annotate_next_event"):
            mock = patch.object(home_screen.BasicMedia.objects, target)
            mock.start()
            self.addCleanup(mock.stop)

    def item(self, title, media_type, **kwargs):
        if media_type in ("season", "episode"):
            kwargs.setdefault("season_number", 1)
        if media_type == "episode":
            kwargs.setdefault("episode_number", 1)
        return Item.objects.create(
            title=title,
            media_id=title,
            media_type=media_type,
            source=Sources.MANUAL,
            **kwargs,
        )

    def row(
        self, levels=None, *, families=None, sort="title", direction="asc", **filters
    ):
        return HomeScreenRow.objects.create(
            user=self.user,
            media_type="all",
            row_type=HomeScreenRowTypeChoices.LIBRARY_QUERY,
            sort_by=sort,
            direction=direction,
            filters={
                "media_types": families or ["tv", "movie", "music", "podcast"],
                "media_subviews": levels
                or {"tv": "episodes", "music": "albums", "podcast": "shows"},
                "status": [Status.COMPLETED],
                "progress": "all",
                **filters,
            },
        )

    def window(self, row, offset=0, limit=20, seed=0):
        return home_screen._library_row_window(self.user, row, offset, limit, seed=seed)

    def test_configuration_round_trip_defaults_and_validation(self):
        for levels in (
            {"tv": "shows", "music": "tracks", "podcast": "episodes"},
            {"tv": "seasons", "music": "artists", "podcast": "shows"},
            {"tv": "episodes", "music": "albums", "podcast": "shows"},
        ):
            with self.subTest(levels=levels):
                home_screen.save_home_screen_configuration(
                    self.user,
                    json.dumps(
                        [
                            {
                                "media_type": "all",
                                "rows": [
                                    {
                                        "row_type": "library_query",
                                        "sort_by": "title",
                                        "filters": {
                                            "media_types": ["movie"],
                                            "media_subviews": levels,
                                        },
                                    }
                                ],
                            }
                        ]
                    ),
                )
                row = HomeScreenRow.objects.get(user=self.user, media_type="all")
                self.assertEqual(row.filters["media_subviews"], levels)
                serialized = home_screen._serialize_settings_row(self.user, row, "all")
                self.assertEqual(serialized["filters"]["media_subviews"], levels)
        self.assertEqual(
            home_screen._normalized_filter_payload({}, "all")["media_subviews"],
            {
                "tv": "shows",
                "music": "tracks",
                "podcast": "episodes",
            },
        )
        for invalid in (
            [],
            None,
            "albums",
            {"tv": "tracks"},
            {"movie": "episodes"},
            {"music": []},
        ):
            with (
                self.subTest(invalid=invalid),
                self.assertRaises(home_screen.HomeScreenValidationError),
            ):
                home_screen.validate_library_row_filters(
                    {"media_subviews": invalid}, "all", user=self.user
                )

    def test_mixed_levels_use_the_displayed_trackers(self):
        entries, total = self.window(self.row())
        self.assertEqual(total, 4)
        self.assertEqual(
            [entry.item.title for entry in entries],
            ["Album B", "Episode F", "Movie G", "Podcast C"],
        )
        episode = next(
            entry for entry in entries if entry.item.pk == self.episode_item.pk
        )
        self.assertEqual(episode.media.status, Status.COMPLETED)
        self.assertFalse(episode.show_progress_controls)
        entries, total = self.window(self.row(rating="not_rated"))
        self.assertEqual((entries, total), ([], 0))
        self.album_tracker.score = None
        self.album_tracker.save(update_fields=["score"])
        entries, total = self.window(self.row(rating="not_rated"))
        self.assertEqual(total, 1)
        self.assertEqual(entries[0].item.title, "Album B")

    def test_each_family_level_and_tv_without_seasons_sidebar(self):
        self.user.season_enabled = False
        self.user.save(update_fields=["season_enabled"])
        for family, level, title, status in (
            ("tv", "shows", "TV D", Status.IN_PROGRESS),
            ("tv", "seasons", "Season E", Status.IN_PROGRESS),
            ("tv", "episodes", "Episode F", Status.COMPLETED),
            ("music", "artists", "Artist A", Status.COMPLETED),
            ("music", "albums", "Album B", Status.COMPLETED),
            ("music", "tracks", "Track H", Status.COMPLETED),
            ("podcast", "shows", "Podcast C", Status.COMPLETED),
            ("podcast", "episodes", "Podcast Episode I", Status.COMPLETED),
        ):
            with self.subTest(family=family, level=level):
                entries, total = self.window(
                    self.row({family: level}, families=[family], status=[status])
                )
                self.assertEqual(total, 1)
                self.assertEqual(entries[0].item.title, title)

    def test_episode_scope_deduplication_archives_and_other_owners(self):
        Episode.objects.bulk_create(
            [
                Episode(
                    related_season=self.season,
                    item=self.episode_item,
                    status=Status.COMPLETED,
                    end_date=self.now,
                ),
                Episode(
                    related_season=self.season,
                    item=self.item("Archived", "episode"),
                    order_archived=True,
                ),
                Episode(
                    related_season=self.season,
                    item=self.item("Rating only", "episode"),
                    rating_only=True,
                ),
            ]
        )
        other = get_user_model().objects.create_user(username="other")
        other_tv = TV.objects.bulk_create(
            [TV(user=other, item=self.item("Other TV", "tv"))]
        )[0]
        other_season = Season.objects.bulk_create(
            [
                Season(
                    user=other,
                    item=self.item("Other Season", "season"),
                    related_tv=other_tv,
                )
            ]
        )[0]
        Episode.objects.bulk_create(
            [
                Episode(
                    related_season=other_season,
                    item=self.item("Other Episode", "episode"),
                )
            ]
        )
        entries, total = self.window(self.row(families=["tv"]))
        self.assertEqual(total, 1)
        self.assertEqual(entries[0].item.pk, self.episode_item.pk)

    def test_global_sort_and_pages_for_every_choice(self):
        for choice in home_screen.get_allowed_sort_choices("all", "library_query"):
            for direction in ("asc", "desc"):
                with self.subTest(sort=choice["value"], direction=direction):
                    row = self.row(sort=choice["value"], direction=direction)
                    whole, total = self.window(row, seed=83)
                    pages = [
                        entry
                        for offset in range(total)
                        for entry in self.window(row, offset, 1, seed=83)[0]
                    ]
                    self.assertEqual(total, 4)
                    self.assertEqual(
                        [entry.item.pk for entry in pages],
                        [entry.item.pk for entry in whole],
                    )
                    self.assertEqual(len({entry.item.pk for entry in pages}), total)
        row = self.row(sort="end_date", direction="desc")
        self.assertEqual(
            [entry.item.title for entry in self.window(row)[0]],
            ["Album B", "Podcast C", "Episode F", "Movie G"],
        )

    def test_only_visible_shells_are_persisted_and_warm_pages_skip_ranking(self):
        row = self.row({"music": "artists", "podcast": "shows", "tv": "episodes"})
        self.assertFalse(
            Item.objects.filter(media_id=f"artist_{self.artist.pk}").exists()
        )
        with patch.object(
            home_screen, "_row_entries", wraps=home_screen._row_entries
        ) as decorate:
            entries, total = self.window(row, limit=1)
            self.assertEqual([entry.item.title for entry in entries], ["Artist A"])
            self.assertEqual(decorate.call_args.args[1], [])
        self.assertTrue(
            Item.objects.filter(media_id=f"artist_{self.artist.pk}").exists()
        )
        self.assertFalse(Item.objects.filter(media_id=self.show.podcast_uuid).exists())
        with patch.object(
            home_mixed_rows, "_item_executors", side_effect=AssertionError("re-ranked")
        ):
            self.assertEqual(len(self.window(row, offset=1, limit=1)[0]), 1)
        self.artist_tracker.status = Status.DROPPED
        self.artist_tracker.save(update_fields=["status"])
        self.assertEqual(self.window(row)[1], total - 1)

    def test_projection_ranking_stays_batched_for_a_larger_library(self):
        albums = Album.objects.bulk_create(
            [
                Album(title=f"Album {index:03}", artist=self.artist)
                for index in range(home_mixed_rows.BATCH_SIZE + 5)
            ]
        )
        AlbumTracker.objects.bulk_create(
            [
                AlbumTracker(user=self.user, album=album, status=Status.COMPLETED)
                for album in albums
            ]
        )
        row = self.row(families=["music"])
        with patch.object(
            home_screen,
            "_music_shell_items_bulk",
            wraps=home_screen._music_shell_items_bulk,
        ) as shells:
            entries, total = self.window(row, limit=1)
        self.assertEqual(total, home_mixed_rows.BATCH_SIZE + 6)
        self.assertEqual(len(entries), 1)
        self.assertTrue(
            all(
                len(call.args[0]) <= home_mixed_rows.BATCH_SIZE
                for call in shells.call_args_list
            )
        )
        self.assertEqual(Item.objects.filter(media_id__startswith="album_").count(), 1)

    def test_projection_collection_tags_and_release_filters(self):
        shell = home_screen._music_shell_item(
            f"album_{self.album.pk}", self.album.title, ""
        )
        tag = Tag.objects.create(user=self.user, name="Favorite")
        ItemTag.objects.create(item=shell, tag=tag)
        CollectionEntry.objects.create(user=self.user, item=shell)
        row = self.row(families=["music"], collection="collected", tag=["Favorite"])
        self.assertEqual(
            [entry.item.title for entry in self.window(row)[0]], ["Album B"]
        )
        self.assertEqual(
            self.window(self.row(families=["music"], collection="not_collected"))[1], 0
        )
        self.assertEqual(
            self.window(self.row(families=["music"], release="released"))[1], 0
        )
        self.assertEqual(
            self.window(self.row(families=["music"], release="not_released"))[1], 1
        )

    def test_episode_sql_scan_state_and_activity_agree(self):
        Episode.objects.bulk_create(
            [
                Episode(
                    related_season=self.season,
                    item=self.episode_item,
                    status=Status.IN_PROGRESS,
                    start_date=self.now,
                    score=4,
                ),
            ]
        )
        other_item = self.item("Undated Episode", "episode")
        Episode.objects.bulk_create(
            [Episode(related_season=self.season, item=other_item)]
        )
        for key in ("last_watched", "score", "date_added", "title"):
            for direction in ("asc", "desc"):
                with self.subTest(key=key, direction=direction):
                    executor = LibraryQueryExecutor(
                        self.user,
                        LibraryQuery(
                            media_types=("episode",),
                            sort=SortSpec(key=key, direction=direction),
                        ),
                    )
                    expected = [item.pk for item in executor.page(0, 20).items]
                    executor._sort_expressions = None
                    actual = [
                        rank[-1]
                        for rank in order_rows(
                            executor.rank_rows(), descending=direction == "desc"
                        )
                    ]
                    self.assertEqual(actual, expected)
        executor = LibraryQueryExecutor(
            self.user,
            LibraryQuery(
                media_types=("episode",),
                filters=FilterValues(statuses=(Status.IN_PROGRESS,)),
            ),
        )
        self.assertEqual(executor.ranked_ids(), [self.episode_item.pk])
        entries, total = self.window(
            self.row(families=["tv"], status=[Status.IN_PROGRESS], sort="recent")
        )
        self.assertEqual(total, 1)
        self.assertEqual(entries[0].media.status, Status.IN_PROGRESS)
        self.assertEqual(entries[0].media.aggregated_score, 4)

    def test_tv_children_follow_anime_library_visibility(self):
        self.tv.item.library_media_type = "anime"
        self.tv.item.save(update_fields=["library_media_type"])
        row = self.row(families=["tv"])
        for visibility, expected in (("anime", 0), ("tv", 1), ("both", 1)):
            self.user.anime_library_mode = visibility
            self.user.save(update_fields=["anime_library_mode"])
            self.assertEqual(self.window(row)[1], expected)
        self.user.tv_enabled = False
        self.user.save(update_fields=["tv_enabled"])
        self.assertEqual(self.window(self.row(families=["tv"]))[1], 0)

    def test_null_dates_last_and_random_stable_after_shell_creation(self):
        AlbumTracker.objects.filter(pk=self.album_tracker.pk).update(end_date=None)
        for direction in ("asc", "desc"):
            entries, _ = self.window(self.row(sort="end_date", direction=direction))
            self.assertEqual(entries[-1].item.title, "Album B")
        row = self.row(sort="random")
        initial = [entry.item.title for entry in self.window(row, seed=123)[0]]
        cache.clear()
        rebuilt = [entry.item.title for entry in self.window(row, seed=123)[0]]
        self.assertEqual(initial, rebuilt)

    def test_episode_and_podcast_episode_cards_render_the_selected_entity(self):
        row = self.row(
            {"tv": "episodes", "podcast": "episodes"}, families=["tv", "podcast"]
        )
        entries, _ = self.window(row)
        request = RequestFactory().get("/")
        request.user = self.user
        content = render_to_string(
            "app/components/home_grid.html",
            {
                "media_list": {"items": entries, "mixed_media": True},
                "user": self.user,
            },
            request=request,
        )
        self.assertIn("Episode F", content)
        self.assertIn("TV D • S01E01", content)
        self.assertIn("Podcast Episode I", content)
        self.assertFalse(
            next(
                entry for entry in entries if entry.item.pk == self.podcast_item.pk
            ).use_podcast_show
        )
