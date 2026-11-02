"""Home cards must not hydrate the item columns they never render.

Provider availability can carry a large JSON payload for every region.
Neither paginated library/list cards nor recently-unrated episode shelves
render it; the latter still hydrate their full time window before slicing.
"""

import pickle
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, tag
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from app.models import (
    TV,
    BasicMedia,
    Episode,
    Item,
    MediaTypes,
    Movie,
    Season,
    Sources,
    Status,
)
from lists.models import CustomList, CustomListItem
from users.home_screen import _custom_list_row_window, _recently_unrated_episode_entries
from users.models import HomeScreenRow, HomeScreenRowTypeChoices

ITEM_COUNT = 10
PROVIDERS = {f"REGION{index}": [{"provider_id": index}] for index in range(139)}


class CompactEpisodeCardTests(TestCase):
    """Card summaries preserve derived values without retaining every watch."""

    def _fixture(self, repeats=8):
        with patch("app.providers.services.get_media_metadata", return_value={"max_progress": None}):
            user = get_user_model().objects.create_user(username="compact-card")
            show_item = Item.objects.create(media_id="compact", source="tmdb", media_type="tv", title="Show")
            season_item = Item.objects.create(media_id="compact", source="tmdb", media_type="season", season_number=1, title="Season")
            show = TV.objects.create(item=show_item, user=user, status=Status.IN_PROGRESS.value)
            season = Season.objects.create(item=season_item, user=user, related_tv=show, status=Status.IN_PROGRESS.value)
            anchor = timezone.now() - timedelta(days=10)
            rows = []
            for number in (1, 2):
                item = Item.objects.create(
                    media_id="compact", source="tmdb", media_type="episode", season_number=1,
                    episode_number=number, title=f"Episode {number}", release_datetime=anchor + timedelta(days=number),
                )
                rows.append(Episode(item=item, related_season=season, status=Status.PLANNING.value))
                rows.extend(Episode(
                    item=item, related_season=season, status=Status.COMPLETED.value,
                    end_date=anchor + timedelta(hours=index * 4),
                ) for index in range(repeats))
            Episode.objects.bulk_create(rows)
        return show, season

    def _load(self, pk, *, compact):
        return BasicMedia.objects._apply_prefetch_related(
            TV.objects.filter(pk=pk).select_related("item"), "tv", compact_episodes=compact,
        ).get()

    def _values(self, show):
        season = show.seasons.all()[0]
        return (
            show.progress, show.completed_episode_count, show.last_watched,
            show.start_date, show.end_date, show.progressed_at,
            season._get_episode_stats(), season.progress, season.start_date, season.end_date,
            BasicMedia.objects._next_episode_air_date_value(show),
        )

    def test_mixed_statuses_dates_and_next_air_date_match_full_graph(self):
        """A first planning row must not hide later completed watches."""
        show, _season = self._fixture()
        full = self._load(show.pk, compact=False)
        compact = self._load(show.pk, compact=True)
        self.assertEqual(self._values(compact), self._values(full))
        self.assertEqual(len(compact.seasons.all()[0].episodes.all()), 2)

    def test_active_rewatch_retains_date_only_pass_semantics(self):
        """Pass-aware seasons retain raw plays, including date-only fallback."""
        show, season = self._fixture()
        Season.objects.filter(pk=season.pk).update(rewatch_started_at=timezone.now() - timedelta(days=9))
        full = self._load(show.pk, compact=False)
        compact = self._load(show.pk, compact=True)
        self.assertEqual(self._values(compact), self._values(full))
        self.assertEqual(len(compact.seasons.all()[0].episodes.all()), len(full.seasons.all()[0].episodes.all()))

    def test_corrected_identity_ties_retain_original_watch_order(self):
        """Multiple Items sharing a coordinate cannot be reordered by grouping."""
        show, season = self._fixture()
        alternate = Item.objects.create(
            media_id="compact", source="tvdb", media_type="episode", season_number=1,
            episode_number=1, title="Migrated", release_datetime=timezone.now(),
        )
        Episode.objects.bulk_create([Episode(
            item=alternate, related_season=season, status=Status.COMPLETED.value,
            end_date=timezone.now(),
        )])
        self.assertEqual(self._values(self._load(show.pk, compact=True)), self._values(self._load(show.pk, compact=False)))

    def test_window_sorts_watch_columns_and_fetches_catalogue_after_selection(self):
        """Wide catalogue columns never enter the per-watch window sorter."""
        show, _season = self._fixture()
        with CaptureQueriesContext(connection) as captured:
            compact = self._load(show.pk, compact=True)
        windows = [row["sql"] for row in captured if " OVER " in row["sql"]]
        self.assertEqual(len(windows), 1)
        self.assertNotIn('"app_item"."synopsis"', windows[0])
        episodes = list(compact.seasons.all()[0].episodes.all())
        with self.assertNumQueries(0):
            self.assertEqual([row.item.title for row in episodes], ["Episode 1", "Episode 2"])

    def test_long_shows_load_past_the_sqlite_expression_limit(self):
        """A batch with over a thousand episodes must not build a >1000-term OR (#1452)."""
        show, season = self._fixture(repeats=1)
        items = Item.objects.bulk_create([
            Item(
                media_id="compact", source="tmdb", media_type="episode", season_number=1,
                episode_number=number, title=f"Episode {number}",
            )
            for number in range(3, 1203)
        ])
        Episode.objects.bulk_create([
            Episode(item=item, related_season=season, status=Status.COMPLETED.value, end_date=timezone.now())
            for item in items
        ])
        compact = self._load(show.pk, compact=True)
        episodes = list(compact.seasons.all()[0].episodes.all())
        with self.assertNumQueries(0):
            self.assertEqual(len({row.item.pk for row in episodes}), 1202)

    @tag("slow", "benchmark")
    def test_serialized_card_graph_scales_with_identities_not_watches(self):
        """A thousand same-coordinate plays produce two compact episode nodes."""
        show, _season = self._fixture(repeats=1000)
        full = self._load(show.pk, compact=False)
        compact = self._load(show.pk, compact=True)
        self.assertEqual(self._values(compact), self._values(full))
        self.assertLess(len(pickle.dumps(compact)), len(pickle.dumps(full)) / 10)


class HomeCardProjectionTests(TestCase):
    """The column no home card renders must not be selected."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="home-projection",
            password="12345",
        )
        cls.custom_list = CustomList.objects.create(
            name="Projection List", owner=cls.user,
        )
        for index in range(ITEM_COUNT):
            item = Item.objects.create(
                media_id=f"projection-movie-{index}",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title=f"Projection Movie {index}",
                watch_providers=PROVIDERS,
            )
            Movie.objects.create(
                item=item, user=cls.user, status=Status.COMPLETED.value,
            )
            CustomListItem.objects.create(custom_list=cls.custom_list, item=item)
        cls.row = HomeScreenRow.objects.create(
            user=cls.user,
            media_type=MediaTypes.MOVIE.value,
            row_type=HomeScreenRowTypeChoices.CUSTOM_LIST,
            custom_list=cls.custom_list,
        )

    def test_watch_providers_is_never_selected_for_a_custom_list_row(self):
        """Neither the item query nor the media query may load it."""
        with CaptureQueriesContext(connection) as captured:
            entries, _total = _custom_list_row_window(self.user, self.row, 0, 100, seed=0)

        self.assertEqual(len(entries), ITEM_COUNT)
        loading = [
            query["sql"]
            for query in captured.captured_queries
            if '"watch_providers"' in query["sql"]
        ]
        self.assertEqual(
            len(loading),
            0,
            f"{len(loading)} home-row queries loaded watch_providers",
        )

    def test_the_cards_still_carry_what_they_render(self):
        """Projection is invisible to the row: same items, same media."""
        entries, _total = _custom_list_row_window(self.user, self.row, 0, 100, seed=0)

        titles = sorted(entry.item.title for entry in entries)
        self.assertEqual(titles[0], "Projection Movie 0")
        self.assertTrue(all(entry.media is not None for entry in entries))
        self.assertTrue(all(entry.show_progress_controls for entry in entries))

    def test_recent_episode_cards_do_not_select_provider_payloads(self):
        from django.utils import timezone

        show_item = Item.objects.create(
            media_id="recent-show", source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value, title="Recent Show", watch_providers=PROVIDERS,
        )
        show = TV.objects.create(item=show_item, user=self.user, status=Status.PLANNING.value)
        season_item = Item.objects.create(
            media_id="recent-show", source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value, library_media_type=MediaTypes.TV.value,
            season_number=1, title="Recent Season", watch_providers=PROVIDERS,
        )
        season = Season.objects.create(
            item=season_item, user=self.user, related_tv=show, status=Status.PLANNING.value,
        )
        episode_item = Item.objects.create(
            media_id="recent-show", source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value, season_number=1, episode_number=1,
            title="Recent Episode", watch_providers=PROVIDERS,
        )
        Episode.objects.create(item=episode_item, related_season=season, end_date=timezone.now())
        with CaptureQueriesContext(connection) as captured:
            entries = _recently_unrated_episode_entries(self.user, MediaTypes.TV.value)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].subtitle_override, "Recent Show • S01E01")
        self.assertFalse(any('"watch_providers"' in query["sql"] for query in captured))

    @tag("slow", "benchmark")
    def test_populated_recent_episode_projection_profile(self):
        """Compare the same populated shelf with and without its card projection."""
        import cProfile
        import json
        import os
        import pstats
        import time
        import tracemalloc
        from pathlib import Path
        from unittest.mock import patch

        from django.core.cache import cache
        from django.urls import reverse
        from django.utils import timezone

        show_item = Item.objects.create(
            media_id="profile-show", source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value, title="Profile Show",
        )
        show = TV.objects.create(item=show_item, user=self.user, status=Status.PLANNING.value)
        season_item = Item.objects.create(
            media_id="profile-show", source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value, library_media_type=MediaTypes.TV.value,
            season_number=1, title="Profile Season",
        )
        season = Season.objects.create(
            item=season_item, user=self.user, related_tv=show, status=Status.PLANNING.value,
        )
        payload = {f"REGION{i}": [{"provider_id": i, "logo_path": "x" * 500}] for i in range(139)}
        items = Item.objects.bulk_create([
            Item(
                media_id="profile-show", source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value, season_number=1, episode_number=i + 1,
                title=f"Episode {i + 1}", watch_providers=payload,
            ) for i in range(1000)
        ])
        Episode.objects.bulk_create([
            Episode(item=item, related_season=season, end_date=timezone.now()) for item in items
        ])
        tv_row = HomeScreenRow.objects.create(
            user=self.user, media_type=MediaTypes.TV.value,
            row_type=HomeScreenRowTypeChoices.RECENTLY_UNRATED,
        )
        self.client.force_login(self.user)
        row_fragment_url = reverse("home_row_fragment", args=[tv_row.id])
        results = []
        for projection in (False, True, False, True):
            with patch("users.home_screen.HOME_CARD_UNREAD_ITEM_FIELDS", ("watch_providers",) if projection else ()):
                profile = cProfile.Profile()
                tracemalloc.start()
                started = time.perf_counter()
                profile.enable()
                with CaptureQueriesContext(connection) as captured:
                    entries = _recently_unrated_episode_entries(self.user, MediaTypes.TV.value)
                profile.disable()
                elapsed = time.perf_counter() - started
                _current, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
            self.assertEqual(len(entries), 1000)
            stats = pstats.Stats(profile)
            hot = sorted(stats.stats.items(), key=lambda row: row[1][3], reverse=True)[:12]
            results.append({
                "projection": projection, "elapsed_seconds": elapsed,
                "peak_bytes": peak, "queries": len(captured),
                "hot_functions": [{"file": key[0], "line": key[1], "function": key[2], "cumulative_seconds": value[3]} for key, value in hot],
            })
            del entries
        request_results = []
        # Prime persistent configuration and template compilation equally;
        # every measured request still rebuilds the row from a cold cache.
        self.client.get(reverse("home"))
        self.client.get(row_fragment_url)
        for projection in (False, True, False, True):
            cache.clear()
            with patch("users.home_screen.HOME_CARD_UNREAD_ITEM_FIELDS", ("watch_providers",) if projection else ()):
                profile = cProfile.Profile()
                tracemalloc.start()
                started = time.perf_counter()
                profile.enable()
                with CaptureQueriesContext(connection) as captured:
                    home = self.client.get(reverse("home"))
                    rest = self.client.get(row_fragment_url)
                profile.disable()
                elapsed = time.perf_counter() - started
                _current, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
            self.assertEqual(home.status_code, 200)
            self.assertEqual(rest.status_code, 200)
            hot = sorted(pstats.Stats(profile).stats.items(), key=lambda row: row[1][3], reverse=True)[:12]
            request_results.append({
                "projection": projection, "elapsed_seconds": elapsed,
                "peak_bytes": peak, "queries": len(captured),
                "hot_functions": [{"file": key[0], "line": key[1], "function": key[2], "cumulative_seconds": value[3]} for key, value in hot],
            })
        untraced_requests = []
        for projection in (False, True, False, True):
            cache.clear()
            with patch("users.home_screen.HOME_CARD_UNREAD_ITEM_FIELDS", ("watch_providers",) if projection else ()):
                started = time.perf_counter()
                started_cpu = time.thread_time()
                with CaptureQueriesContext(connection) as captured:
                    home = self.client.get(reverse("home"))
                    rest = self.client.get(row_fragment_url)
                untraced_requests.append({
                    "projection": projection, "elapsed_seconds": time.perf_counter() - started,
                    "thread_cpu_seconds": time.thread_time() - started_cpu,
                    "queries": len(captured),
                })
            self.assertEqual(home.status_code, 200)
            self.assertEqual(rest.status_code, 200)
        if output_path := os.environ.get("FLOPPY_HOME_PROFILE_OUTPUT"):
            Path(output_path).write_text(json.dumps({"shelf": results, "requests": request_results, "untraced_requests": untraced_requests}, indent=2))
        self.assertLess(results[1]["peak_bytes"], results[0]["peak_bytes"] / 2)
