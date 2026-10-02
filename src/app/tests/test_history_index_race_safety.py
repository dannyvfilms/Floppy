"""Race-safety regression tests for History index invalidation (F15).

The typed-index registry used to be maintained with a read/append/write
cycle, so two builders could lose registrations and a builder could
re-create a registry that an invalidation had just deleted — leaving a
pre-invalidation typed index reachable as the "current" one. The era-token
protocol (see `docs/architecture/history-memory.md`) makes those stale
publishes unreachable instead of trying to delete them first.

Every schedule here is deterministic: interleavings are driven by patched
cache/build calls, never by sleeps.
"""

import datetime
import random
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from app import history_cache
from app.history_cache_reader import get_cached_history_window
from app.history_cache_utils import expand_history_media_types
from app.models import (
    TV,
    Episode,
    Item,
    MediaTypes,
    Movie,
    Season,
    Sources,
    Status,
)

MOVIE_TYPES = expand_history_media_types("movie")
TV_TYPES = expand_history_media_types("tv")


class HistoryIndexRaceSafetyTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        # Keep cache state under the test's control: object creation fires
        # real invalidations, and eager Celery would otherwise run refresh
        # tasks inline and repopulate indexes mid-schedule.
        refresh_patcher = patch(
            "app.history_cache_lifecycle.schedule_history_refresh",
            return_value=True,
        )
        refresh_patcher.start()
        self.addCleanup(refresh_patcher.stop)
        coverage_patcher = patch(
            "app.history_cache_lifecycle.schedule_history_day_cache_coverage",
            return_value=True,
        )
        coverage_patcher.start()
        self.addCleanup(coverage_patcher.stop)

        self.user = get_user_model().objects.create_user(username="race-safety")
        self.logging_style = "sessions"
        self._create_movie("race-movie-1", datetime.date(2026, 8, 20))
        cache.clear()

    def _create_movie(self, media_id, watched_date):
        item = Item.objects.create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title=media_id,
        )
        return Movie.objects.create(
            item=item,
            user=self.user,
            status=Status.COMPLETED.value,
            progress=1,
            start_date=timezone.make_aware(
                datetime.datetime(
                    watched_date.year, watched_date.month, watched_date.day, 12
                ),
            ),
            end_date=timezone.make_aware(
                datetime.datetime(
                    watched_date.year, watched_date.month, watched_date.day, 13
                ),
            ),
        )

    def _current_typed_entry(self, media_types):
        era = history_cache._current_history_era(self.user.id, self.logging_style)
        key = history_cache._typed_history_index_key(
            self.user.id,
            self.logging_style,
            media_types,
            era,
        )
        return era, cache.get(key)

    def _reader_day_keys(self, media_type=None):
        filters = {"media_type": media_type} if media_type else {}
        days, _total = get_cached_history_window(
            self.user,
            limit=100,
            offset=0,
            filters=filters,
            logging_style_override=self.logging_style,
        )
        return sorted(day["date"].strftime("%Y%m%d") for day in days)

    def _truth_day_keys(self, media_type=None):
        media_types = expand_history_media_types(media_type) if media_type else None
        return sorted(
            history_cache.build_history_index(
                self.user,
                logging_style_override=self.logging_style,
                media_types=media_types,
            ),
        )

    def test_concurrent_typed_builders_and_invalidation_leave_no_stale_index(self):
        """The original F15 schedule: a second typed index publishes between
        the first builder's registry read and write, then invalidation runs.
        No typed index may remain reachable as current afterwards.
        """
        registry_key = history_cache._typed_history_index_registry_key(
            self.user.id,
            self.logging_style,
        )
        original_get = cache.get
        interleaved = False

        def interleave(key, *args, **kwargs):
            nonlocal interleaved
            previous = original_get(key, *args, **kwargs)
            if key == registry_key and not interleaved:
                interleaved = True
                history_cache.cache_history_index(
                    self.user.id,
                    self.logging_style,
                    ["20260820"],
                    media_types=["tv"],
                )
            return previous

        with patch.object(cache, "get", side_effect=interleave):
            history_cache.cache_history_index(
                self.user.id,
                self.logging_style,
                ["20260820"],
                media_types=["movie"],
            )

        history_cache.invalidate_history_days(
            self.user.id,
            [datetime.date(2026, 8, 20)],
            logging_styles=[self.logging_style],
            refresh_index=False,
        )

        for media_types in (MOVIE_TYPES, TV_TYPES):
            era, entry = self._current_typed_entry(media_types)
            self.assertIsNone(
                entry,
                f"typed index for {media_types} must not be current after invalidation",
            )

        # Readers rebuild both filters from current rows under the new era.
        self.assertEqual(self._reader_day_keys("movie"), self._truth_day_keys("movie"))
        self.assertEqual(self._reader_day_keys("tv"), self._truth_day_keys("tv"))
        for media_types in (MOVIE_TYPES, TV_TYPES):
            _era, entry = self._current_typed_entry(media_types)
            self.assertIsNotNone(entry)

    def test_invalidation_during_typed_build_cannot_replace_current_index(self):
        """Rows are read, then data changes and invalidation lands before the
        publish. The stale publish must be unreachable and the new day must
        be discoverable by the next reader.
        """
        from app.history_cache_reader import build_history_index as real_build

        def build_then_invalidate(*args, **kwargs):
            day_keys = real_build(*args, **kwargs)
            self._create_movie("race-movie-2", datetime.date(2026, 8, 21))
            history_cache.invalidate_history_days(
                self.user.id,
                [datetime.date(2026, 8, 21)],
                logging_styles=[self.logging_style],
                refresh_index=False,
            )
            return day_keys

        with patch(
            "app.history_cache_reader.build_history_index",
            side_effect=build_then_invalidate,
        ):
            first_days = self._reader_day_keys("movie")

        # The first reader linearized before the invalidation, so it may see
        # the older rows — but its publish must not survive as current.
        era, entry = self._current_typed_entry(MOVIE_TYPES)
        self.assertIsNone(
            entry,
            "index published after invalidation must not be the current index",
        )

        # The next reader rebuilds and the new day is discoverable.
        self.assertNotIn("20260821", first_days)
        second_days = self._reader_day_keys("movie")
        self.assertIn("20260821", second_days)
        self.assertEqual(second_days, self._truth_day_keys("movie"))
        _era, entry = self._current_typed_entry(MOVIE_TYPES)
        self.assertIsNotNone(entry)

    def test_publication_with_retired_era_is_unreachable(self):
        """A builder holding an era token that invalidation has retired
        (check-then-publish) can write its index, but no reader selects it.
        """
        era = history_cache._current_history_era(self.user.id, self.logging_style)
        history_cache.invalidate_history_days(
            self.user.id,
            None,
            logging_styles=[self.logging_style],
            refresh_index=False,
        )
        new_era = history_cache._current_history_era(self.user.id, self.logging_style)
        self.assertNotEqual(era, new_era)

        history_cache.cache_history_index(
            self.user.id,
            self.logging_style,
            ["20260820"],
            media_types=["movie"],
            era=era,
        )

        current_key = history_cache._typed_history_index_key(
            self.user.id,
            self.logging_style,
            MOVIE_TYPES,
            new_era,
        )
        self.assertIsNone(cache.get(current_key))
        # And the main index payload embeds the retired token, so readers
        # treat it as stale rather than fresh.
        history_cache.cache_history_index(
            self.user.id,
            self.logging_style,
            ["20260820"],
            era=era,
        )
        main_entry = cache.get(
            history_cache._cache_key(self.user.id, self.logging_style)
        )
        self.assertEqual(main_entry.get("era"), era)
        self.assertNotEqual(main_entry.get("era"), new_era)

    def test_era_key_eviction_never_adopts_old_typed_index(self):
        """Deleting the era key (expiry/eviction) must seed a brand-new
        identity — an orphaned typed index can never become current again.
        """
        era = history_cache._current_history_era(self.user.id, self.logging_style)
        history_cache.cache_history_index(
            self.user.id,
            self.logging_style,
            ["20260820"],
            media_types=["movie"],
            era=era,
        )
        old_key = history_cache._typed_history_index_key(
            self.user.id,
            self.logging_style,
            MOVIE_TYPES,
            era,
        )
        self.assertIsNotNone(cache.get(old_key))

        cache.delete(history_cache._history_era_key(self.user.id, self.logging_style))
        reseeded = history_cache._current_history_era(self.user.id, self.logging_style)
        self.assertNotEqual(era, reseeded)
        _new_era, entry = self._current_typed_entry(MOVIE_TYPES)
        self.assertIsNone(entry, "orphaned typed index must not be adopted")
        # The reader still answers correctly from rows.
        self.assertEqual(self._reader_day_keys("movie"), self._truth_day_keys("movie"))

    def test_registry_deletion_alone_does_not_break_typed_reads(self):
        """The registry is cleanup bookkeeping; losing it costs an early
        delete, not correctness.
        """
        self.assertEqual(self._reader_day_keys("movie"), self._truth_day_keys("movie"))
        cache.delete(
            history_cache._typed_history_index_registry_key(
                self.user.id,
                self.logging_style,
            )
        )
        era, entry = self._current_typed_entry(MOVIE_TYPES)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.get("era"), era)
        self.assertEqual(self._reader_day_keys("movie"), self._truth_day_keys("movie"))

    def test_full_and_day_invalidation_retire_typed_and_keep_day_payloads(self):
        day_key = "20260820"
        # Day payloads are persisted by untyped reads (typed reads build
        # filtered payloads without caching them).
        self.assertEqual(self._reader_day_keys(), self._truth_day_keys())
        day_payload_key = history_cache._day_cache_key(
            self.user.id,
            self.logging_style,
            day_key,
        )
        self.assertIsNotNone(cache.get(day_payload_key))

        # Ordinary day invalidation retires typed indexes but deliberately
        # keeps day payloads readable (stale-while-refresh).
        history_cache.invalidate_history_days(
            self.user.id,
            [datetime.date(2026, 8, 20)],
            logging_styles=[self.logging_style],
            refresh_index=False,
        )
        _era, entry = self._current_typed_entry(MOVIE_TYPES)
        self.assertIsNone(entry)
        self.assertIsNotNone(cache.get(day_payload_key))

        # Full force invalidation clears payloads and the main index too.
        history_cache.invalidate_history_cache(
            self.user.id,
            force=True,
            logging_styles=[self.logging_style],
        )
        self.assertIsNone(cache.get(day_payload_key))
        self.assertIsNone(
            cache.get(history_cache._cache_key(self.user.id, self.logging_style))
        )
        self.assertEqual(self._reader_day_keys("movie"), self._truth_day_keys("movie"))

    def test_logging_styles_and_users_have_independent_eras(self):
        other = get_user_model().objects.create_user(username="race-safety-other")

        era_sessions = history_cache._current_history_era(self.user.id, "sessions")
        era_repeats = history_cache._current_history_era(self.user.id, "repeats")
        era_other = history_cache._current_history_era(other.id, "sessions")
        self.assertEqual(len({era_sessions, era_repeats, era_other}), 3)

        history_cache.invalidate_history_days(
            self.user.id,
            None,
            logging_styles=["sessions"],
            refresh_index=False,
        )
        self.assertNotEqual(
            history_cache._current_history_era(self.user.id, "sessions"),
            era_sessions,
        )
        self.assertEqual(
            history_cache._current_history_era(self.user.id, "repeats"),
            era_repeats,
        )
        self.assertEqual(
            history_cache._current_history_era(other.id, "sessions"),
            era_other,
        )

    def test_empty_index_publish_and_invalidate(self):
        empty_user = get_user_model().objects.create_user(username="race-safety-empty")
        era = history_cache._current_history_era(empty_user.id, self.logging_style)
        history_cache.cache_history_index(
            empty_user.id,
            self.logging_style,
            [],
            media_types=["movie"],
            era=era,
        )
        _e, entry = self._current_typed_entry_for(empty_user, MOVIE_TYPES)
        self.assertEqual(entry.get("days"), [])
        history_cache.invalidate_history_days(
            empty_user.id,
            None,
            logging_styles=[self.logging_style],
            refresh_index=False,
        )
        _e, entry = self._current_typed_entry_for(empty_user, MOVIE_TYPES)
        self.assertIsNone(entry)

    def _current_typed_entry_for(self, user, media_types):
        era = history_cache._current_history_era(user.id, self.logging_style)
        key = history_cache._typed_history_index_key(
            user.id,
            self.logging_style,
            media_types,
            era,
        )
        return era, cache.get(key)

    def test_repeated_interleaved_schedule_converges(self):
        """A bounded, seeded schedule of interleaved publishes, invalidations,
        era/registry deletions and reads: after the final invalidation and a
        quiet read, current-era indexes must hold the database truth.
        """
        rng = random.Random(20260928)  # noqa: S311  # deterministic schedule sampling, not cryptographic
        media_type_sets = {
            "movie": MOVIE_TYPES,
            "tv": TV_TYPES,
        }
        for _ in range(25):
            op = rng.choice(
                [
                    "publish_typed",
                    "publish_untyped",
                    "day_invalidate",
                    "full_invalidate",
                    "delete_era",
                    "delete_registry",
                    "read_typed",
                    "read_untyped",
                ]
            )
            if op == "publish_typed":
                media_types = media_type_sets[rng.choice(["movie", "tv"])]
                era = history_cache._current_history_era(
                    self.user.id, self.logging_style
                )
                history_cache.cache_history_index(
                    self.user.id,
                    self.logging_style,
                    self._truth_day_keys(),
                    media_types=media_types,
                    era=era,
                )
            elif op == "publish_untyped":
                era = history_cache._current_history_era(
                    self.user.id, self.logging_style
                )
                history_cache.cache_history_index(
                    self.user.id,
                    self.logging_style,
                    self._truth_day_keys(),
                    era=era,
                )
            elif op == "day_invalidate":
                history_cache.invalidate_history_days(
                    self.user.id,
                    [datetime.date(2026, 8, 20)],
                    logging_styles=[self.logging_style],
                    refresh_index=False,
                )
            elif op == "full_invalidate":
                history_cache.invalidate_history_cache(
                    self.user.id,
                    force=True,
                    logging_styles=[self.logging_style],
                )
            elif op == "delete_era":
                cache.delete(
                    history_cache._history_era_key(self.user.id, self.logging_style)
                )
            elif op == "delete_registry":
                cache.delete(
                    history_cache._typed_history_index_registry_key(
                        self.user.id,
                        self.logging_style,
                    )
                )
            elif op == "read_typed":
                self._reader_day_keys(rng.choice(["movie", "tv"]))
            else:
                self._reader_day_keys()

        # Invariant after quiescence: readers return database truth and the
        # current-era typed caches hold it.
        history_cache.invalidate_history_days(
            self.user.id,
            None,
            logging_styles=[self.logging_style],
            refresh_index=False,
        )
        for media_type, media_types in media_type_sets.items():
            self.assertEqual(
                self._reader_day_keys(media_type), self._truth_day_keys(media_type)
            )
            era, entry = self._current_typed_entry(media_types)
            self.assertIsNotNone(entry)
            self.assertEqual(entry.get("era"), era)
            self.assertEqual(
                sorted(entry.get("days", [])),
                self._truth_day_keys(media_type),
            )
        self.assertEqual(self._reader_day_keys(), self._truth_day_keys())
