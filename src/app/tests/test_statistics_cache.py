from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import call, patch
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from app import (
    statistics_aggregator,
    statistics_cache,
    statistics_refresh,
    statistics_refresh_run,
)
from app.models import Item, MediaTypes, Movie, Sources, Status
from app.statistics_aggregator import (
    _aggregate_minutes_per_media_type_from_days,
    _build_combined_hours_charts,
    _build_platform_breakdown,
    _build_weekday_hour_charts,
)
from app.statistics_day_cache import _normalize_day_value


class StatisticsDayBatchingTests(SimpleTestCase):
    @patch("app.statistics_aggregator.cache.get_many", return_value={})
    def test_thousands_of_days_are_fetched_in_fixed_batches(self, get_many):
        days = [date(2020, 1, 1) + timedelta(days=index) for index in range(1000)]

        result = _aggregate_minutes_per_media_type_from_days(
            SimpleNamespace(id=42),
            days,
        )

        self.assertEqual(result, {})
        self.assertEqual(get_many.call_count, 20)
        self.assertTrue(
            all(len(call_args.args[0]) <= 50 for call_args in get_many.call_args_list)
        )


class StatisticsRefreshPayloadRetentionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="stats-refresh-payloads",
            password="secret123",
        )
        self.days = []
        for offset in (1, 3):
            item = Item.objects.create(
                media_id=f"stats-refresh-payload-{offset}",
                source=Sources.MANUAL.value,
                media_type=MediaTypes.MOVIE.value,
                title=f"Statistics payload movie {offset}",
                runtime_minutes=90,
            )
            watched_at = timezone.now() - timedelta(days=offset)
            Movie.objects.create(
                user=self.user,
                item=item,
                status=Status.COMPLETED.value,
                end_date=watched_at,
            )
            self.days.append(_normalize_day_value(watched_at))

    def tearDown(self):
        cache.clear()

    def test_refresh_rebuilds_days_whose_cache_write_failed(self):
        """A run cannot carry day payloads across Celery task boundaries.

        The single-shot refresh kept a failed day's payload in Python and
        handed it to the aggregator as ``prebuilt_days``. A chunked run records
        the day identifier instead and lets the aggregator's existing
        ``build_missing`` path rebuild it, so the published numbers are
        unchanged while nothing unbounded is retained between chunks.
        """
        failed_key = statistics_refresh._day_cache_key(self.user.id, self.days[0])
        # Creating the fixture already warmed these through the eager refresh
        # signal; drop them so the run genuinely has to rebuild them.
        cache.delete_many(
            [statistics_refresh._day_cache_key(self.user.id, day) for day in self.days]
        )
        original_set_many = cache.set_many

        def set_many_dropping_one_day(values, timeout=None, version=None):
            original_set_many(
                {key: value for key, value in values.items() if key != failed_key},
                timeout=timeout,
                version=version,
            )
            return [failed_key] if failed_key in values else []

        with (
            patch.object(
                statistics_refresh_run.cache,
                "set_many",
                side_effect=set_many_dropping_one_day,
            ),
            patch(
                "app.statistics_aggregator.build_stats_for_day",
                wraps=statistics_aggregator.build_stats_for_day,
            ) as rebuild,
        ):
            result = statistics_refresh.refresh_statistics_cache(
                self.user.id,
                "All Time",
            )

        self.assertIsNotNone(result)
        self.assertIn(
            self.days[0],
            [call_args.args[1] for call_args in rebuild.call_args_list],
        )
        self.assertEqual(
            result["hours_per_media_type"],
            statistics_cache.get_statistics_data(self.user, None, None, "All Time")[
                "hours_per_media_type"
            ],
        )


class StatisticsRefreshSchedulingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="stats-refresh-user",
            password="secret123",
        )

    def tearDown(self):
        cache.clear()

    @patch("app.tasks.refresh_statistics_cache_task.apply_async")
    def test_schedule_statistics_refresh_uses_interactive_priority_by_default(
        self,
        mock_apply_async,
    ):
        scheduled = statistics_cache.schedule_statistics_refresh(
            self.user.id,
            "This Month",
            allow_inline=False,
        )

        self.assertTrue(scheduled)
        mock_apply_async.assert_called_once()
        self.assertEqual(
            mock_apply_async.call_args.kwargs["priority"],
            settings.CELERY_TASK_PRIORITY_INTERACTIVE,
        )

    @patch("app.statistics_refresh.schedule_statistics_refresh")
    def test_schedule_all_ranges_refresh_prioritizes_preferred_and_cached_all_time(
        self,
        mock_schedule_statistics_refresh,
    ):
        self.user.statistics_default_range = "This Month"
        self.user.save(update_fields=["statistics_default_range"])
        cache.set(
            statistics_cache._cache_key(self.user.id, "All Time"),
            {"history_version": "cached"},
            timeout=60,
        )

        statistics_cache.schedule_all_ranges_refresh(
            self.user.id,
            debounce_seconds=0,
            countdown=3,
        )

        mock_schedule_statistics_refresh.assert_has_calls(
            [
                call(
                    self.user.id,
                    "This Month",
                    debounce_seconds=0,
                    countdown=3,
                    allow_inline=False,
                    priority=settings.CELERY_TASK_PRIORITY_FOLLOWUP,
                ),
                call(
                    self.user.id,
                    "All Time",
                    debounce_seconds=0,
                    countdown=3 + statistics_cache.STATISTICS_ALL_TIME_REFRESH_DELAY,
                    allow_inline=False,
                    priority=settings.CELERY_TASK_PRIORITY_BACKGROUND,
                ),
            ],
        )
        self.assertEqual(mock_schedule_statistics_refresh.call_count, 2)

    @patch("app.statistics_refresh.schedule_statistics_refresh")
    def test_schedule_all_ranges_refresh_skips_uncached_all_time(
        self,
        mock_schedule_statistics_refresh,
    ):
        self.user.statistics_default_range = "Last 90 Days"
        self.user.save(update_fields=["statistics_default_range"])

        statistics_cache.schedule_all_ranges_refresh(
            self.user.id,
            debounce_seconds=0,
            countdown=5,
        )

        mock_schedule_statistics_refresh.assert_called_once_with(
            self.user.id,
            "Last 90 Days",
            debounce_seconds=0,
            countdown=5,
            allow_inline=False,
            priority=settings.CELERY_TASK_PRIORITY_FOLLOWUP,
        )


@override_settings(CELERY_TASK_ALWAYS_EAGER=False, TESTING=False)
class StatisticsStaleResultTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username="stats-stale-user")
        self.data = statistics_cache._get_empty_statistics_data()
        self.data["hours_per_media_type"]["movie"] = "2h"
        statistics_cache.cache_statistics_data(self.user.id, "This Month", self.data)

    def tearDown(self):
        cache.clear()

    @patch("app.tasks.refresh_statistics_cache_task.apply_async")
    def test_invalidation_serves_previous_result_and_schedules_refresh(self, enqueue):
        for range_name in ("This Month", None):
            with self.subTest(range_name=range_name):
                cache.delete(
                    statistics_cache._refresh_lock_key(self.user.id, "This Month")
                )
                enqueue.reset_mock()
                statistics_cache.invalidate_statistics_cache(self.user.id, range_name)

                result = statistics_cache.get_statistics_data(
                    self.user, None, None, "This Month"
                )

                self.assertEqual(result, self.data)
                enqueue.assert_called_once()

    @patch("app.statistics_cache.refresh_statistics_cache")
    @patch(
        "app.tasks.refresh_statistics_cache_task.apply_async",
        side_effect=OSError("offline"),
    )
    def test_unavailable_worker_keeps_previous_result_without_inline_rebuild(
        self, enqueue, rebuild
    ):
        statistics_cache.invalidate_statistics_cache(self.user.id)

        result = statistics_cache.get_statistics_data(
            self.user, None, None, "This Month"
        )

        self.assertEqual(result, self.data)
        enqueue.assert_called_once()
        rebuild.assert_not_called()
        self.assertIsNone(
            cache.get(statistics_cache._refresh_lock_key(self.user.id, "This Month"))
        )

    def test_completed_refresh_replaces_previous_result(self):
        statistics_cache.invalidate_statistics_cache(self.user.id)
        updated = statistics_cache._get_empty_statistics_data()
        statistics_cache.cache_statistics_data(self.user.id, "This Month", updated)

        with patch("app.tasks.refresh_statistics_cache_task.apply_async") as enqueue:
            result = statistics_cache.get_statistics_data(
                self.user, None, None, "This Month"
            )

        self.assertEqual(result, updated)
        enqueue.assert_not_called()

    @patch("app.tasks.refresh_statistics_cache_task.apply_async")
    def test_previous_day_result_refreshes_even_without_new_activity(self, enqueue):
        later = timezone.now() + timedelta(days=1)
        with patch("app.statistics_cache.timezone.now", return_value=later):
            result = statistics_cache.get_statistics_data(
                self.user, None, None, "This Month"
            )
            # Repeat visits while the task waits must not multiply the work.
            statistics_cache.get_statistics_data(self.user, None, None, "This Month")

        self.assertEqual(result, self.data)
        enqueue.assert_called_once()

    @patch("app.tasks.refresh_statistics_cache_task.apply_async")
    def test_local_midnight_refreshes_a_recent_today_snapshot(self, enqueue):
        # UTC is still the same date, but Tokyo has crossed midnight.
        before = datetime(2026, 6, 1, 14, 59, tzinfo=UTC)
        after = before + timedelta(minutes=2)
        with timezone.override(ZoneInfo("Asia/Tokyo")):
            with patch("app.statistics_cache.timezone.now", return_value=before):
                statistics_cache.cache_statistics_data(self.user.id, "Today", self.data)
            with patch("app.statistics_cache.timezone.now", return_value=after):
                result = statistics_cache.get_statistics_data(
                    self.user, None, None, "Today"
                )

        self.assertEqual(result, self.data)
        enqueue.assert_called_once()

    @patch("app.tasks.refresh_statistics_cache_task.apply_async")
    def test_polling_refreshes_previous_day_results_with_matching_history_version(
        self, enqueue
    ):
        self.client.force_login(self.user)
        later = timezone.now() + timedelta(days=1)
        with patch("app.statistics_cache.timezone.now", return_value=later):
            response = self.client.get(
                reverse("cache_status"),
                {"cache_type": "statistics", "range_name": "This Month"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["exists"])
        self.assertTrue(response.json()["is_stale"])
        self.assertTrue(response.json()["refresh_scheduled"])
        enqueue.assert_called_once()

    @patch("app.tasks.refresh_statistics_cache_task.apply_async")
    def test_unchanged_same_day_snapshot_does_not_rebuild_every_fifteen_minutes(
        self, enqueue
    ):
        before = datetime(2026, 6, 1, 12, tzinfo=UTC)
        with timezone.override(ZoneInfo("UTC")):
            with patch("app.statistics_cache.timezone.now", return_value=before):
                statistics_cache.cache_statistics_data(self.user.id, "Today", self.data)
            with patch(
                "app.statistics_cache.timezone.now",
                return_value=before + timedelta(hours=2),
            ):
                result = statistics_cache.get_statistics_data(
                    self.user, None, None, "Today"
                )
        self.assertEqual(result, self.data)
        enqueue.assert_not_called()

    @patch("app.tasks.refresh_statistics_cache_task.apply_async")
    def test_lightweight_statistics_reads_refresh_retained_stale_results(self, enqueue):
        for reader, key in (
            (statistics_cache.get_statistics_minutes_by_type, "minutes_per_media_type"),
            (statistics_cache.get_statistics_media_count, "media_count"),
            (statistics_cache.get_top_talent_data, "top_talent"),
        ):
            with self.subTest(reader=reader.__name__):
                cache.delete(
                    statistics_cache._refresh_lock_key(self.user.id, "This Month")
                )
                enqueue.reset_mock()
                statistics_cache.invalidate_statistics_cache(self.user.id)
                result = reader(self.user, None, None, "This Month")
                self.assertEqual(result, self.data[key])
                enqueue.assert_called_once()

    def test_page_snapshot_survives_between_daily_visits(self):
        ttl = cache.ttl(statistics_cache._cache_key(self.user.id, "This Month"))
        self.assertGreater(ttl, 24 * 60 * 60)

    def test_stale_covering_range_cannot_publish_a_fresh_derived_snapshot(self):
        statistics_cache.cache_statistics_data(self.user.id, "All Time", self.data)
        start, end = statistics_cache._get_predefined_range_dates("This Month")
        later = timezone.now() + timedelta(days=1)
        with patch("app.statistics_cache.timezone.now", return_value=later):
            covers = statistics_cache._has_covering_range_cache(
                self.user.id,
                "This Month",
                start,
                end,
                statistics_cache.get_history_version(self.user.id),
            )
        self.assertFalse(covers)


class StatisticsHourBucketTests(TestCase):
    """Time-of-day statistics omit date-only midnight placeholders."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="stats-hour-user",
            password="secret123",
        )

    def tearDown(self):
        cache.clear()

    def test_exact_midnight_is_excluded_but_later_midnight_activity_remains(self):
        """Only exact 00:00 placeholders are omitted from hour buckets."""
        midnight = timezone.make_aware(datetime(2025, 1, 15))
        for index, (watched_at, runtime) in enumerate(
            ((midnight, 120), (midnight + timedelta(minutes=30), 90)),
            start=1,
        ):
            item = Item.objects.create(
                media_id=f"midnight-movie-{index}",
                source=Sources.MANUAL.value,
                media_type=MediaTypes.MOVIE.value,
                title=f"Midnight Movie {index}",
                runtime_minutes=runtime,
            )
            Movie.objects.create(
                item=item,
                user=self.user,
                status=Status.COMPLETED.value,
                progress=1,
                start_date=watched_at,
                end_date=watched_at,
            )

        day_stats = statistics_cache.build_stats_for_day(
            self.user.id,
            midnight.date(),
        )

        self.assertEqual(day_stats["hour_counts"][MediaTypes.MOVIE.value], {"0": 1})
        self.assertEqual(
            day_stats["hour_minutes"][MediaTypes.MOVIE.value],
            {"0": 90},
        )
        self.assertEqual(
            day_stats["totals"]["minutes_by_type"][MediaTypes.MOVIE.value],
            210,
        )
        self.assertEqual(
            day_stats["totals"]["plays_by_type"][MediaTypes.MOVIE.value],
            2,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PORTRAIT_POSTER = "https://image.tmdb.org/t/p/w500/poster.jpg"
BACKDROP_URL = "https://image.tmdb.org/t/p/w1280/backdrop.jpg"
IGDB_BACKDROP_URL = "https://images.igdb.com/igdb/image/upload/t_screenshot_big/abc.jpg"


def _tv_item_dict(media_id="1396", title="Breaking Bad"):
    """Serialised TMDB TV show dict (as stored in history day cache)."""
    return {
        "id": 1,
        "media_type": MediaTypes.TV.value,
        "media_id": str(media_id),
        "source": Sources.TMDB.value,
        "title": title,
    }


def _movie_item_dict(
    media_id="1865", title="Pirates of the Caribbean: On Stranger Tides"
):
    """Serialised TMDB movie dict."""
    return {
        "id": 2,
        "media_type": MediaTypes.MOVIE.value,
        "media_id": str(media_id),
        "source": Sources.TMDB.value,
        "title": title,
    }


def _episode_item_dict(media_id="1399", title="Game of Thrones S01E01"):
    """Serialised TMDB episode dict. media_id matches the parent TV show."""
    return {
        "id": 3,
        "media_type": MediaTypes.EPISODE.value,
        "media_id": str(media_id),
        "source": Sources.TMDB.value,
        "title": title,
    }


def _anime_item_dict(media_id="94954", title="Devil May Cry"):
    """Serialised TMDB anime dict.

    Anime has its own MediaTypes.ANIME ("anime") value distinct from "tv".
    When sourced from TMDB the item carries source=tmdb + media_type=anime,
    and the TMDB API still exposes it via the /tv/{id} endpoint.
    """
    return {
        "id": 4,
        "media_type": MediaTypes.ANIME.value,
        "media_id": str(media_id),
        "source": Sources.TMDB.value,
        "title": title,
    }


def _mal_anime_item_dict(media_id="40591", title="Jujutsu Kaisen"):
    """Serialised MAL-sourced anime dict (no backdrop available)."""
    return {
        "id": 6,
        "media_type": MediaTypes.ANIME.value,
        "media_id": str(media_id),
        "source": Sources.MAL.value,
        "title": title,
    }


def _tvdb_tv_item_dict(tvdb_id="121361", tmdb_id="1399", title="Game of Thrones"):
    """
    Serialised TVDB TV show dict with a TMDB cross-reference.

    TVDB items carry provider_external_ids populated by the TVDB provider
    when it finds a TMDB counterpart. A user who added GoT / Breaking Bad /
    HIMYM / Murdock Mysteries via TVDB ends up with source=tvdb, and the
    only way to get a backdrop is to use the tmdb_id cross-reference.
    """
    return {
        "id": 7,
        "media_type": MediaTypes.TV.value,
        "media_id": str(tvdb_id),
        "source": Sources.TVDB.value,
        "title": title,
        "provider_external_ids": {"tmdb_id": tmdb_id, "tvdb_id": tvdb_id},
    }


def _tvdb_episode_item_dict(tvdb_id="121361", tmdb_id="1399", title="GoT S01E01"):
    """Serialised TVDB episode — provider_external_ids carries show-level tmdb_id."""
    return {
        "id": 8,
        "media_type": MediaTypes.EPISODE.value,
        "media_id": str(tvdb_id),
        "source": Sources.TVDB.value,
        "title": title,
        "provider_external_ids": {"tmdb_id": tmdb_id, "tvdb_id": tvdb_id},
    }


def _game_item_dict(media_id="9630", title="Devil May Cry 5"):
    """Serialised IGDB game dict."""
    return {
        "id": 5,
        "media_type": MediaTypes.GAME.value,
        "media_id": str(media_id),
        "source": Sources.IGDB.value,
        "title": title,
    }


def _highlight_entry(item_dict, image=PORTRAIT_POSTER):
    """Minimal history highlight payload as produced by _history_entry_card_payload."""
    return {
        "item": item_dict,
        "title": item_dict.get("title", ""),
        "media_type": item_dict.get("media_type"),
        "image": image,
        "played_at": None,
    }


# ---------------------------------------------------------------------------
# _get_horizontal_history_image
# ---------------------------------------------------------------------------


class GetHorizontalHistoryImageTests(TestCase):
    """
    Tests for statistics_cache._get_horizontal_history_image.

    Every test mocks CustomList._get_tmdb_backdrop / _get_igdb_backdrop so no
    real network calls are made. The Redis cache is cleared before each test so
    _cached_horizontal_backdrop always starts cold unless explicitly primed.
    """

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    # ------------------------------------------------------------------
    # None / missing item
    # ------------------------------------------------------------------

    def test_none_item_returns_fallback(self):
        result = statistics_cache._get_horizontal_history_image(None, PORTRAIT_POSTER)
        self.assertEqual(result, PORTRAIT_POSTER)

    def test_none_item_and_no_fallback_returns_img_none(self):
        result = statistics_cache._get_horizontal_history_image(None, "")
        self.assertEqual(result, settings.IMG_NONE)

    def test_dict_item_missing_source_returns_fallback(self):
        """Items without a provider (e.g. manual entries) fall back to the poster."""
        item = {"media_type": MediaTypes.MOVIE.value, "media_id": "999"}
        result = statistics_cache._get_horizontal_history_image(item, PORTRAIT_POSTER)
        self.assertEqual(result, PORTRAIT_POSTER)

    def test_dict_item_missing_media_id_returns_fallback(self):
        item = {"media_type": MediaTypes.MOVIE.value, "source": Sources.TMDB.value}
        result = statistics_cache._get_horizontal_history_image(item, PORTRAIT_POSTER)
        self.assertEqual(result, PORTRAIT_POSTER)

    # ------------------------------------------------------------------
    # Cached backdrop already in Redis — no network call needed
    # ------------------------------------------------------------------

    @patch("lists.models.CustomList._get_tmdb_backdrop")
    def test_tv_show_uses_redis_cache_without_network_call(self, mock_backdrop):
        item = _tv_item_dict()  # Breaking Bad, media_id=1396
        cache.set("tmdb_backdrop_tv_1396", BACKDROP_URL, 60)

        result = statistics_cache._get_horizontal_history_image(item, PORTRAIT_POSTER)

        self.assertEqual(result, BACKDROP_URL)
        mock_backdrop.assert_not_called()

    @patch("lists.models.CustomList._get_tmdb_backdrop")
    def test_movie_uses_redis_cache_without_network_call(self, mock_backdrop):
        item = _movie_item_dict()  # On Stranger Tides, media_id=1865
        cache.set("tmdb_backdrop_movie_1865", BACKDROP_URL, 60)

        result = statistics_cache._get_horizontal_history_image(item, PORTRAIT_POSTER)

        self.assertEqual(result, BACKDROP_URL)
        mock_backdrop.assert_not_called()

    # ------------------------------------------------------------------
    # Network fetch — TMDB TV (Breaking Bad)
    # ------------------------------------------------------------------

    @patch("lists.models.CustomList._get_tmdb_backdrop", return_value=BACKDROP_URL)
    def test_tv_show_fetches_tmdb_backdrop_when_cache_cold(self, mock_backdrop):
        """Breaking Bad (tv, 1396): cold Redis → should call TMDB and return backdrop."""
        item = _tv_item_dict(media_id="1396", title="Breaking Bad")

        result = statistics_cache._get_horizontal_history_image(
            item, PORTRAIT_POSTER, allow_network=True
        )

        self.assertEqual(result, BACKDROP_URL)
        mock_backdrop.assert_called_once_with(MediaTypes.TV.value, "1396")

    @patch("lists.models.CustomList._get_tmdb_backdrop", return_value=BACKDROP_URL)
    def test_anime_tmdb_fetches_backdrop_via_tv_endpoint(self, mock_backdrop):
        """
        Devil May Cry (media_type=anime, source=tmdb): cold Redis → backdrop fetched.

        This is the core edge case from issue #211. MediaTypes.ANIME ("anime") is
        distinct from MediaTypes.TV ("tv"), so without the fix the two TMDB blocks
        (`media_type in ("movie","tv")` and the episode/season block) both miss it
        and fall through to the portrait poster.
        """
        item = _anime_item_dict(media_id="94954", title="Devil May Cry")

        result = statistics_cache._get_horizontal_history_image(
            item, PORTRAIT_POSTER, allow_network=True
        )

        self.assertEqual(result, BACKDROP_URL)
        # Anime from TMDB must use the /tv/{id} endpoint
        mock_backdrop.assert_called_once_with(MediaTypes.TV.value, "94954")

    @patch("lists.models.CustomList._get_tmdb_backdrop")
    def test_anime_tmdb_redis_cache_hit_skips_network(self, mock_backdrop):
        """TMDB anime whose backdrop is already in Redis must not re-fetch."""
        item = _anime_item_dict(media_id="94954")
        # Backdrops for anime are stored under the "tv" key (same endpoint)
        cache.set("tmdb_backdrop_tv_94954", BACKDROP_URL, 60)

        result = statistics_cache._get_horizontal_history_image(item, PORTRAIT_POSTER)

        self.assertEqual(result, BACKDROP_URL)
        mock_backdrop.assert_not_called()

    @patch("lists.models.CustomList._get_tmdb_backdrop")
    def test_anime_mal_source_falls_back_to_portrait(self, mock_backdrop):
        """
        MAL-sourced anime has no backdrop provider, so the portrait poster is
        the correct fallback. No TMDB call should be attempted.
        """
        item = _mal_anime_item_dict()

        result = statistics_cache._get_horizontal_history_image(
            item, PORTRAIT_POSTER, allow_network=True
        )

        self.assertEqual(result, PORTRAIT_POSTER)
        mock_backdrop.assert_not_called()

    # ------------------------------------------------------------------
    # Network fetch — TMDB movie (Pirates of the Caribbean: On Stranger Tides)
    # ------------------------------------------------------------------

    @patch("lists.models.CustomList._get_tmdb_backdrop", return_value=BACKDROP_URL)
    def test_movie_fetches_tmdb_backdrop_when_cache_cold(self, mock_backdrop):
        """On Stranger Tides (movie, 1865): cold Redis → should call TMDB."""
        item = _movie_item_dict(
            media_id="1865",
            title="Pirates of the Caribbean: On Stranger Tides",
        )

        result = statistics_cache._get_horizontal_history_image(
            item, PORTRAIT_POSTER, allow_network=True
        )

        self.assertEqual(result, BACKDROP_URL)
        mock_backdrop.assert_called_once_with(MediaTypes.MOVIE.value, "1865")

    # ------------------------------------------------------------------
    # Network fetch — TMDB episode (Game of Thrones)
    # ------------------------------------------------------------------

    @patch("lists.models.CustomList._get_tmdb_backdrop", return_value=BACKDROP_URL)
    def test_episode_fetches_show_backdrop_via_tv_path(self, mock_backdrop):
        """
        Game of Thrones episode (media_type=episode, media_id=1399).
        Episodes share the parent show's media_id and should use the TV backdrop path.
        """
        item = _episode_item_dict(media_id="1399", title="Game of Thrones S01E01")

        result = statistics_cache._get_horizontal_history_image(
            item, PORTRAIT_POSTER, allow_network=True
        )

        self.assertEqual(result, BACKDROP_URL)
        # Must request the TV backdrop, not an episode-specific path
        mock_backdrop.assert_called_once_with(MediaTypes.TV.value, "1399")

    @patch("lists.models.CustomList._get_tmdb_backdrop", return_value=BACKDROP_URL)
    def test_season_fetches_show_backdrop_via_tv_path(self, mock_backdrop):
        """Season items (media_type=season) also resolve via the TV backdrop path."""
        item = {
            "media_type": MediaTypes.SEASON.value,
            "media_id": "1396",
            "source": Sources.TMDB.value,
            "title": "Breaking Bad S1",
        }

        result = statistics_cache._get_horizontal_history_image(
            item, PORTRAIT_POSTER, allow_network=True
        )

        self.assertEqual(result, BACKDROP_URL)
        mock_backdrop.assert_called_once_with(MediaTypes.TV.value, "1396")

    # ------------------------------------------------------------------
    # Network fetch — IGDB game
    # ------------------------------------------------------------------

    @patch("lists.models.CustomList._get_igdb_backdrop", return_value=IGDB_BACKDROP_URL)
    def test_game_fetches_igdb_backdrop(self, mock_igdb):
        item = _game_item_dict(media_id="9630")

        result = statistics_cache._get_horizontal_history_image(
            item, PORTRAIT_POSTER, allow_network=True
        )

        self.assertEqual(result, IGDB_BACKDROP_URL)
        mock_igdb.assert_called_once_with("9630")

    # ------------------------------------------------------------------
    # Media types that have no backdrop path — should fall back gracefully
    # ------------------------------------------------------------------

    @patch("lists.models.CustomList._get_tmdb_backdrop")
    def test_music_media_type_falls_back_to_portrait(self, mock_backdrop):
        """Music has no backdrop source; portrait poster should be returned."""
        item = {
            "media_type": MediaTypes.MUSIC.value,
            "media_id": "12345",
            "source": Sources.TMDB.value,
            "title": "Some Album",
        }

        result = statistics_cache._get_horizontal_history_image(
            item, PORTRAIT_POSTER, allow_network=True
        )

        self.assertEqual(result, PORTRAIT_POSTER)
        mock_backdrop.assert_not_called()

    # ------------------------------------------------------------------
    # allow_network=False — must NOT make network calls
    # ------------------------------------------------------------------

    @patch("lists.models.CustomList._get_tmdb_backdrop")
    def test_allow_network_false_returns_fallback_without_network_call(
        self, mock_backdrop
    ):
        """
        When allow_network=False and Redis is cold, the portrait poster must be
        returned without any TMDB call. This is the pre-fix behaviour for the
        serve-time normaliser — verified here to confirm it was always a dead end.
        """
        item = _tv_item_dict(media_id="1396", title="Breaking Bad")

        result = statistics_cache._get_horizontal_history_image(
            item, PORTRAIT_POSTER, allow_network=False
        )

        self.assertEqual(result, PORTRAIT_POSTER)
        mock_backdrop.assert_not_called()

    # ------------------------------------------------------------------
    # TMDB returns IMG_NONE — fall back to portrait
    # ------------------------------------------------------------------

    @patch("lists.models.CustomList._get_tmdb_backdrop", return_value=settings.IMG_NONE)
    def test_tmdb_returns_img_none_falls_back_to_portrait(self, mock_backdrop):
        item = _tv_item_dict()

        result = statistics_cache._get_horizontal_history_image(
            item, PORTRAIT_POSTER, allow_network=True
        )

        self.assertEqual(result, PORTRAIT_POSTER)

    # ------------------------------------------------------------------
    # TMDB raises an exception — fall back gracefully
    # ------------------------------------------------------------------

    @patch(
        "lists.models.CustomList._get_tmdb_backdrop",
        side_effect=Exception("network error"),
    )
    def test_tmdb_exception_falls_back_to_portrait(self, mock_backdrop):
        item = _tv_item_dict()

        result = statistics_cache._get_horizontal_history_image(
            item, PORTRAIT_POSTER, allow_network=True
        )

        self.assertEqual(result, PORTRAIT_POSTER)

    # ------------------------------------------------------------------
    # Model instance (not dict) — Breaking Bad as a real Item object
    # ------------------------------------------------------------------

    @patch("lists.models.CustomList._get_tmdb_backdrop", return_value=BACKDROP_URL)
    def test_model_instance_tv_fetches_backdrop(self, mock_backdrop):
        """_get_horizontal_history_image must work with Django Item instances too."""
        item = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Breaking Bad",
            image=PORTRAIT_POSTER,
        )

        result = statistics_cache._get_horizontal_history_image(
            item, PORTRAIT_POSTER, allow_network=True
        )

        self.assertEqual(result, BACKDROP_URL)
        mock_backdrop.assert_called_once_with(MediaTypes.TV.value, "1396")

    # ------------------------------------------------------------------
    # TVDB source — cross-reference to TMDB via provider_external_ids
    # ------------------------------------------------------------------

    @patch("lists.models.CustomList._get_tmdb_backdrop", return_value=BACKDROP_URL)
    def test_tvdb_tv_show_uses_tmdb_cross_reference(self, mock_backdrop):
        """
        Game of Thrones / Breaking Bad / HIMYM added via TVDB:
        source=tvdb, no TMDB backdrop path unless we use provider_external_ids.

        The TVDB provider stores a tmdb_id in provider_external_ids when it
        finds a TMDB counterpart. _get_horizontal_history_image must use that
        to fetch the TMDB backdrop.
        """
        item = _tvdb_tv_item_dict(
            tvdb_id="121361", tmdb_id="1399", title="Game of Thrones"
        )

        result = statistics_cache._get_horizontal_history_image(
            item, PORTRAIT_POSTER, allow_network=True
        )

        self.assertEqual(result, BACKDROP_URL)
        mock_backdrop.assert_called_once_with(MediaTypes.TV.value, "1399")

    @patch("lists.models.CustomList._get_tmdb_backdrop", return_value=BACKDROP_URL)
    def test_tvdb_episode_uses_tmdb_cross_reference(self, mock_backdrop):
        """TVDB episodes carry the show-level provider_external_ids tmdb_id."""
        item = _tvdb_episode_item_dict(tvdb_id="121361", tmdb_id="1399")

        result = statistics_cache._get_horizontal_history_image(
            item, PORTRAIT_POSTER, allow_network=True
        )

        self.assertEqual(result, BACKDROP_URL)
        mock_backdrop.assert_called_once_with(MediaTypes.TV.value, "1399")

    @patch("lists.models.CustomList._get_tmdb_backdrop")
    def test_tvdb_tv_redis_cache_hit_skips_network(self, mock_backdrop):
        """TVDB show whose TMDB backdrop is already cached avoids a network call."""
        item = _tvdb_tv_item_dict(tvdb_id="121361", tmdb_id="1399")
        cache.set("tmdb_backdrop_tv_1399", BACKDROP_URL, 60)

        result = statistics_cache._get_horizontal_history_image(item, PORTRAIT_POSTER)

        self.assertEqual(result, BACKDROP_URL)
        mock_backdrop.assert_not_called()

    @patch("lists.models.CustomList._get_tmdb_backdrop")
    def test_tvdb_tv_without_tmdb_cross_reference_falls_back_to_portrait(
        self, mock_backdrop
    ):
        """
        TVDB show with no tmdb_id in provider_external_ids (e.g. obscure show
        not indexed on TMDB) must fall back to the portrait poster gracefully.
        """
        item = {
            "id": 9,
            "media_type": MediaTypes.TV.value,
            "media_id": "99999",
            "source": Sources.TVDB.value,
            "title": "Obscure Local Show",
            "provider_external_ids": {"tvdb_id": "99999"},  # no tmdb_id
        }

        result = statistics_cache._get_horizontal_history_image(
            item, PORTRAIT_POSTER, allow_network=True
        )

        self.assertEqual(result, PORTRAIT_POSTER)
        mock_backdrop.assert_not_called()

    @patch("lists.models.CustomList._get_tmdb_backdrop")
    def test_tvdb_tv_missing_provider_external_ids_falls_back_to_portrait(
        self, mock_backdrop
    ):
        """Old serialised history entries that pre-date the provider_external_ids
        field must not crash and must fall back to the portrait poster.
        """
        item = {
            "id": 10,
            "media_type": MediaTypes.TV.value,
            "media_id": "121361",
            "source": Sources.TVDB.value,
            "title": "Game of Thrones",
            # provider_external_ids absent (old cache entry)
        }

        result = statistics_cache._get_horizontal_history_image(
            item, PORTRAIT_POSTER, allow_network=True
        )

        self.assertEqual(result, PORTRAIT_POSTER)
        mock_backdrop.assert_not_called()


# ---------------------------------------------------------------------------
# _normalize_history_highlight_images  (the serve-time fix — issue #211)
# ---------------------------------------------------------------------------


class NormalizeHistoryHighlightImagesTests(TestCase):
    """
    Tests for statistics_cache._normalize_history_highlight_images.

    This function runs on every stats page serve. Pre-fix it used
    allow_network=False, meaning a cold Redis cache always produced portrait
    posters even when the stats cache was built correctly. Post-fix it uses
    allow_network=True so the first page load after the fix immediately
    upgrades portrait posters to backdrops.
    """

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch("lists.models.CustomList._get_tmdb_backdrop", return_value=BACKDROP_URL)
    def test_portrait_poster_upgraded_to_backdrop_on_serve(self, mock_backdrop):
        """
        Core regression test for issue #211.

        Scenario: stats cache was built with the old code and stores a portrait
        poster in highlights[*].image. Redis has no cached backdrop. On the next
        serve, _normalize_history_highlight_images must call TMDB and swap in
        the backdrop.
        """
        highlights = {
            "first_play": _highlight_entry(_tv_item_dict(), image=PORTRAIT_POSTER),
            "last_play": _highlight_entry(_movie_item_dict(), image=PORTRAIT_POSTER),
            "today_card": {
                "entry": _highlight_entry(_episode_item_dict(), image=PORTRAIT_POSTER),
            },
            "today_month": 5,
            "today_day": 20,
        }

        statistics_cache._normalize_history_highlight_images(highlights)

        for key in ("first_play", "last_play"):
            self.assertEqual(
                highlights[key]["image"],
                BACKDROP_URL,
                msg=f"{key} still has portrait poster after normalization",
            )
        self.assertEqual(
            highlights["today_card"]["entry"]["image"],
            BACKDROP_URL,
            msg="today_card entry still has portrait poster after normalization",
        )

    @patch("lists.models.CustomList._get_tmdb_backdrop", return_value=BACKDROP_URL)
    def test_all_highlight_slots_normalized(self, mock_backdrop):
        """All named highlight slots are processed independently."""
        entries = {
            "first_play": _highlight_entry(_tv_item_dict(media_id="1396")),
            "last_play": _highlight_entry(_movie_item_dict(media_id="1865")),
            "today_card": {
                "entry": _highlight_entry(_episode_item_dict(media_id="1399")),
            },
        }
        highlights = {**entries, "today_month": 5, "today_day": 20}

        statistics_cache._normalize_history_highlight_images(highlights)

        # TMDB should have been consulted for each distinct item
        self.assertEqual(mock_backdrop.call_count, 3)

    @patch("lists.models.CustomList._get_tmdb_backdrop", return_value=BACKDROP_URL)
    def test_none_entries_are_skipped_without_error(self, mock_backdrop):
        """Partial highlights (some slots empty) must not raise."""
        highlights = {
            "first_play": _highlight_entry(_tv_item_dict()),
            "last_play": None,
            "today_in_history": None,
            "today_in_user_history": None,
        }

        statistics_cache._normalize_history_highlight_images(
            highlights
        )  # must not raise

        self.assertEqual(highlights["first_play"]["image"], BACKDROP_URL)

    def test_non_dict_highlights_returns_without_error(self):
        """Passing None or non-dict must be a no-op."""
        statistics_cache._normalize_history_highlight_images(None)
        statistics_cache._normalize_history_highlight_images("not-a-dict")
        statistics_cache._normalize_history_highlight_images([])

    @patch("lists.models.CustomList._get_tmdb_backdrop", return_value=BACKDROP_URL)
    def test_entry_with_none_item_uses_existing_image(self, mock_backdrop):
        """
        If the serialised item is missing (e.g. old cache format), the function
        should return whatever image is already stored rather than crashing.
        """
        highlights = {
            "first_play": {"item": None, "image": PORTRAIT_POSTER, "title": "Unknown"},
            "last_play": None,
            "today_in_history": None,
            "today_in_user_history": None,
        }

        statistics_cache._normalize_history_highlight_images(highlights)

        # item is None so no TMDB call; existing image is preserved
        self.assertEqual(highlights["first_play"]["image"], PORTRAIT_POSTER)
        mock_backdrop.assert_not_called()

    @patch("lists.models.CustomList._get_tmdb_backdrop", return_value=BACKDROP_URL)
    def test_backdrop_already_stored_in_cache_is_reused(self, mock_backdrop):
        """
        If the TMDB Redis cache was already populated (e.g. Lists Hub visit),
        _normalize must use the cached value and make no extra network calls.
        """
        cache.set("tmdb_backdrop_tv_1396", BACKDROP_URL, 60)
        highlights = {
            "first_play": _highlight_entry(_tv_item_dict(media_id="1396")),
            "last_play": None,
            "today_in_history": None,
            "today_in_user_history": None,
        }

        statistics_cache._normalize_history_highlight_images(highlights)

        self.assertEqual(highlights["first_play"]["image"], BACKDROP_URL)
        mock_backdrop.assert_not_called()


class RequestPathDayBuildTests(TestCase):
    """Custom-range statistics never build day caches inline in a request."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="stats-daybuild-user",
            password="secret123",
        )
        self.start = timezone.make_aware(datetime(2024, 1, 1))
        self.end = timezone.make_aware(datetime(2024, 1, 31, 23, 59, 59))

    def tearDown(self):
        cache.clear()

    @patch("app.tasks.build_statistics_days_task.apply_async")
    @patch("app.statistics_aggregator.build_stats_for_day")
    @patch("app.statistics_cache._eager_statistics_mode", return_value=False)
    def test_minutes_by_type_schedules_background_build(
        self,
        _mock_eager,
        mock_build_day,
        mock_apply_async,
    ):
        result = statistics_cache.get_statistics_minutes_by_type(
            self.user,
            self.start,
            self.end,
            range_name="Custom",
        )

        self.assertEqual(result, {})
        mock_build_day.assert_not_called()
        mock_apply_async.assert_called_once()

    @patch("app.tasks.build_statistics_days_task.apply_async")
    @patch("app.statistics_aggregator.build_stats_for_day")
    @patch("app.statistics_cache._eager_statistics_mode", return_value=False)
    def test_schedule_is_debounced(
        self,
        _mock_eager,
        mock_build_day,
        mock_apply_async,
    ):
        for _ in range(2):
            statistics_cache.get_statistics_minutes_by_type(
                self.user,
                self.start,
                self.end,
                range_name="Custom",
            )

        mock_build_day.assert_not_called()
        mock_apply_async.assert_called_once()

    def test_eager_mode_still_builds_inline(self):
        with patch(
            "app.statistics_aggregator.build_stats_for_day",
            return_value={"totals": {"minutes_by_type": {"movie": 60}}},
        ) as mock_build_day:
            result = statistics_cache.get_statistics_minutes_by_type(
                self.user,
                self.start,
                self.end,
                range_name="Custom",
            )

        self.assertEqual(result, {"movie": 60 * 31})
        self.assertEqual(mock_build_day.call_count, 31)


class DayCacheContractTests(SimpleTestCase):
    def test_cache_key_preserves_supported_day_formats(self):
        for day in (date(2026, 9, 5), "2026-09-05", "20260905"):
            with self.subTest(day=day):
                self.assertEqual(
                    statistics_cache._day_cache_key(42, day),
                    "stats:day:v7:42:2026-09-05",
                )
        self.assertEqual(statistics_cache._day_cache_key(42, "invalid"), "")

    def test_aware_datetime_uses_local_day(self):
        with timezone.override("America/Chicago"):
            self.assertEqual(
                _normalize_day_value(
                    datetime.fromisoformat("2026-09-05T01:00:00+00:00")
                ),
                date(2026, 9, 4),
            )

    def test_history_version_round_trips_through_cache_facade(self):
        cache.clear()
        self.addCleanup(cache.clear)
        initial = statistics_cache.get_history_version(42)
        self.assertEqual(statistics_cache.get_history_version(42), initial)
        statistics_cache._set_history_version(42, "changed")
        self.assertEqual(statistics_cache.get_history_version(42), "changed")


class PlatformBreakdownTests(SimpleTestCase):
    def test_collection_choice_wins_and_repeated_games_count_once(self):
        result = _build_platform_breakdown(
            [
                {"item_id": 1, "hours": 2},
                {"item_id": 1, "hours": 3},
                {"item_id": 2, "hours": 1},
            ],
            {1: "Steam Deck"},
            {1: {"platforms": ["PC"]}, 2: {"platforms": ["  Switch  "]}},
        )
        self.assertEqual(
            [(entry["name"], entry["games"], entry["hours"]) for entry in result],
            [("Steam Deck", 1, 5), ("Switch", 1, 1)],
        )

    def test_ambiguous_or_missing_platforms_are_omitted(self):
        self.assertEqual(
            _build_platform_breakdown(
                [{"item_id": item_id, "hours": 1} for item_id in (1, 2, 3, None)],
                {},
                {1: {"platforms": ["PC", "Switch"]}, 2: {"platforms": "PC"}},
            ),
            [],
        )


class StatisticsChartPreparationTests(SimpleTestCase):
    def test_heatmap_combines_types_and_preserves_empty_cells(self):
        counts = {
            "movie": defaultdict(lambda: defaultdict(int)),
            "tv": defaultdict(lambda: defaultdict(int)),
        }
        counts["movie"][2][13] = 2
        counts["tv"][2][13] = 3
        result = _build_weekday_hour_charts(counts)
        self.assertEqual(result["all"][2][13], 5)
        self.assertEqual(result["movie"][2][13], 2)
        self.assertEqual(result["all"][0][0], 0)
        self.assertEqual(len(result["all"]), 7)
        self.assertTrue(all(len(row) == 24 for row in result["all"]))

    def test_hour_charts_combine_elapsed_time_without_reading_units(self):
        result = _build_combined_hours_charts(
            {
                "movie": {"2026-09-05": 90},
                "tv": {"2026-09-05": 30},
                "book": {"2026-09-05": 600},
            },
            {"movie": {"13": 90}, "tv": {"13": 30}, "book": {"13": 600}},
        )
        self.assertEqual(result["by_month"]["all"]["datasets"][0]["data"][8], 2)
        self.assertEqual(result["by_time_of_day"]["all"]["datasets"][0]["data"][13], 2)
        self.assertEqual(result["by_month"]["movie"]["datasets"][0]["data"][8], 1.5)
        self.assertNotIn("book", result["by_month"])
