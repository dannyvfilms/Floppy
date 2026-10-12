"""Cross-source duplicate-play tests for issue #642.

A user who imports their Trakt history and then connects Plex is describing the
same plays twice. Every existing dedupe test seeds a row and re-runs the *same*
importer, so nothing covered Trakt-then-Plex, the reverse order, or the webhook
firing over an already-imported play. These do.

Movies are deliberately exercised at the unit level: both importers bail out on
a blanket "new mode and this movie is already tracked" shortcut long before the
duplicate check, so an end-to-end movie assertion would pass for the wrong
reason. Episodes carry no such shortcut and are where the reporter's history
actually duplicates.
"""

import logging
import random
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase, tag
from django.utils import timezone

from app import fork_services_play_dedupe as play_dedupe
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
from integrations.imports.plex import PlexHistoryImporter
from integrations.imports.trakt import TraktImporter
from integrations.models import PlexAccount
from integrations.webhooks.plex import PlexWebhookProcessor

NO_MAX_PROGRESS = {"max_progress": None}


def setUpModule():
    """Silence importer log noise for this module only."""
    logging.getLogger("integrations.imports.plex").setLevel(logging.CRITICAL)
    logging.getLogger("integrations.imports.trakt").setLevel(logging.CRITICAL)


def tearDownModule():
    """Restore the importer logger levels for other modules."""
    logging.getLogger("integrations.imports.plex").setLevel(logging.NOTSET)
    logging.getLogger("integrations.imports.trakt").setLevel(logging.NOTSET)


def tv_metadata_side_effect(media_type, _media_id, _title, _season=None):
    """Return two-episode season metadata for the Trakt importer.

    Two episodes keeps the season from completing on the first play, which
    would otherwise send the model layer looking for the next season.
    """
    if media_type == MediaTypes.TV.value:
        return {
            "title": "Dedupe Show",
            "image": "tv_image.jpg",
            "last_episode_season": 1,
            "max_progress": 2,
        }
    if media_type == MediaTypes.SEASON.value:
        return {
            "title": "Season 1",
            "image": "season_image.jpg",
            "episodes": [
                {"episode_number": 1, "still_path": "/1.jpg", "title": "One"},
                {"episode_number": 2, "still_path": "/2.jpg", "title": "Two"},
            ],
            "max_progress": 2,
        }
    return None


class DuplicatePlayWindow(TestCase):
    """The window that decides whether two plays are the same play."""

    def test_unknown_runtime_falls_back_to_default(self):
        """Items without a runtime get the flat three hour window."""
        self.assertEqual(
            play_dedupe.duplicate_play_window(None),
            play_dedupe.DEFAULT_DUPLICATE_PLAY_WINDOW,
        )
        self.assertEqual(
            play_dedupe.duplicate_play_window(0),
            play_dedupe.DEFAULT_DUPLICATE_PLAY_WINDOW,
        )

    def test_window_is_sized_by_runtime_within_bounds(self):
        """A 90 minute film gets a 90 minute window."""
        self.assertEqual(
            play_dedupe.duplicate_play_window(90),
            timedelta(minutes=90),
        )

    def test_window_is_clamped(self):
        """A short episode floors at 15 minutes; a long feature caps at 3 hours."""
        self.assertEqual(
            play_dedupe.duplicate_play_window(5),
            play_dedupe.MIN_DUPLICATE_PLAY_WINDOW,
        )
        self.assertEqual(
            play_dedupe.duplicate_play_window(600),
            play_dedupe.MAX_DUPLICATE_PLAY_WINDOW,
        )

    def test_runtime_sized_window_keeps_a_back_to_back_rewatch(self):
        """A 22 minute episode finished twice 30 minutes apart is two plays.

        A flat three hour window would swallow the second one.
        """
        times = play_dedupe.PlayTimes()
        first = timezone.now()
        times.add("key", first, runtime_minutes=22)
        self.assertFalse(times.is_duplicate("key", first + timedelta(minutes=30)))
        self.assertTrue(times.is_duplicate("key", first + timedelta(minutes=10)))

    def test_measures_against_the_nearest_play_not_the_newest(self):
        """A replayed 2020 play is measured against the stored 2020 play."""
        times = play_dedupe.PlayTimes()
        old = timezone.now() - timedelta(days=1000)
        times.add("key", old, runtime_minutes=120)
        times.add("key", timezone.now(), runtime_minutes=120)
        self.assertTrue(times.is_duplicate("key", old + timedelta(minutes=5)))

    def test_index_matches_scan_for_unordered_sources_and_boundaries(self):
        """Indexing retains strict windows, runtime changes and identity isolation."""
        randomizer = random.Random(642)  # noqa: S311 -- deterministic test history
        anchor = datetime(2020, 1, 1, tzinfo=UTC)
        watches = [anchor + timedelta(minutes=n * 17) for n in range(300)]
        randomizer.shuffle(watches)
        times = play_dedupe.PlayTimes()
        for watch in watches:
            times.add("original", watch)
        self.assertEqual(times.times_for("original"), watches)
        for runtime in (None, 5, 22, 120, 600):
            times = play_dedupe.PlayTimes()
            for watch in watches:
                times.add("migrated", watch, runtime)
            window = play_dedupe.duplicate_play_window(runtime)
            for candidate in [None, anchor - window, watches[-1] + window] + [
                anchor + timedelta(seconds=randomizer.randrange(-15000, 400000))
                for _ in range(300)
            ]:
                expected = candidate is not None and any(
                    abs(candidate - watch) < window for watch in watches
                )
                self.assertEqual(times.is_duplicate("migrated", candidate), expected)
                self.assertFalse(times.is_duplicate("unrelated", candidate))
        times = play_dedupe.PlayTimes()
        times.add("key", anchor)
        times.record_runtime("key", 22)
        self.assertFalse(times.is_duplicate("key", anchor + timedelta(minutes=22)))
        self.assertTrue(times.is_duplicate("key", anchor))

    def test_fallback_index_matches_scan_when_sortedcontainers_is_missing(self):
        """A source install that missed `uv sync` (#1522) still dedupes correctly."""
        randomizer = random.Random(1522)  # noqa: S311 -- deterministic test history
        anchor = datetime(2020, 1, 1, tzinfo=UTC)
        watches = [anchor + timedelta(minutes=n * 17) for n in range(100)]
        randomizer.shuffle(watches)
        window = play_dedupe.duplicate_play_window(None)
        with patch.object(play_dedupe, "SortedList", play_dedupe._PlainSortedList):
            times = play_dedupe.PlayTimes()
            for watch in watches:
                times.add("key", watch)
            self.assertEqual(times.times_for("key"), watches)
            for candidate in [anchor - window, watches[-1] + window] + [
                anchor + timedelta(seconds=randomizer.randrange(-15000, 110000))
                for _ in range(200)
            ]:
                expected = any(abs(candidate - watch) < window for watch in watches)
                self.assertEqual(times.is_duplicate("key", candidate), expected)

    def test_dst_and_mixed_awareness_keep_original_comparison_semantics(self):
        """DST fold ordering and early duplicate matches retain scan behavior."""
        zone = ZoneInfo("America/New_York")
        watches = [
            datetime(2020, 11, 1, 1, 20, tzinfo=zone, fold=1),
            datetime(2020, 11, 1, 1, 30, tzinfo=zone, fold=0),
        ]
        times = play_dedupe.PlayTimes()
        for watch in watches:
            times.add("dst", watch, 15)
        self.assertTrue(times.is_duplicate("dst", datetime(2020, 11, 1, 5, 32, tzinfo=UTC)))
        anchor = datetime(2020, 1, 1, tzinfo=UTC)
        times.add("mixed", anchor)
        times.add("mixed", datetime(2020, 1, 1))
        self.assertTrue(times.is_duplicate("mixed", anchor))
        with self.assertRaises(TypeError):
            times.is_duplicate("mixed", anchor + timedelta(days=2))

    @tag("slow", "benchmark")
    def test_large_same_identity_lookup_has_bounded_timestamp_comparisons(self):
        """Growing repeated histories must not scan all earlier timestamps."""
        class CountedDateTime(datetime):
            comparisons = 0

            def __sub__(self, other):
                type(self).comparisons += 1
                return super().__sub__(other)

        anchor = CountedDateTime(1980, 1, 1, tzinfo=UTC)
        size = 80849
        for descending in (False, True):
            times = play_dedupe.PlayTimes()
            CountedDateTime.comparisons = 0
            indexes = range(size - 1, -1, -1) if descending else range(size)
            for n in indexes:
                candidate = anchor + timedelta(hours=4 * n)
                self.assertFalse(times.is_duplicate("same", candidate))
                times.add("same", candidate, 30)
            self.assertLessEqual(CountedDateTime.comparisons, size * 2)
            self.assertEqual(len(times.times_for("same")), size)


class ExistingPlayTimes(TestCase):
    """The query helpers must see every shape a play is stored in."""

    def setUp(self):
        """Create a user and a movie item."""
        self.user = get_user_model().objects.create_user(
            username="dedupe",
            password="12345",
        )
        self.item = Item.objects.get_or_create(
            media_id="500",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={"title": "Dedupe Movie", "runtime_minutes": 100},
        )[0]

    @patch("app.providers.services.get_media_metadata", return_value=NO_MAX_PROGRESS)
    def test_movie_play_rows_are_visible(self, _mock_metadata):
        """MoviePlay rows count as plays, not just Movie.end_date.

        Movie.watch() records a rewatch as a MoviePlay row while the importers
        create an extra Movie row, and before #642 neither side looked at the
        former.
        """
        first = timezone.now() - timedelta(days=10)
        rewatch = timezone.now()
        movie = Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.COMPLETED.value,
            end_date=first,
        )
        movie.watch(rewatch)

        play_times = play_dedupe.existing_movie_play_times(self.user)
        stored = play_times.times_for("500")
        self.assertIn(first, stored)
        self.assertIn(rewatch, stored)
        self.assertTrue(play_times.is_duplicate("500", first + timedelta(minutes=20)))

    @patch("app.providers.services.get_media_metadata", return_value=NO_MAX_PROGRESS)
    def test_scoped_by_user(self, _mock_metadata):
        """Another user's plays are not consulted."""
        other = get_user_model().objects.create_user(
            username="other",
            password="12345",
        )
        Movie.objects.create(
            item=self.item,
            user=other,
            status=Status.COMPLETED.value,
            end_date=timezone.now(),
        )
        play_times = play_dedupe.existing_movie_play_times(self.user)
        self.assertEqual(play_times.times_for("500"), [])


class TraktAfterPlex(TestCase):
    """A Trakt import must not duplicate an episode play Plex already recorded."""

    def setUp(self):
        """Seed a show with one episode play, as a Plex sync would leave it."""
        self.user = get_user_model().objects.create_user(
            username="dedupe",
            password="12345",
        )
        tv_item = Item.objects.get_or_create(
            media_id="12345",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            defaults={"title": "Dedupe Show"},
        )[0]
        tv_obj = TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        season_item = Item.objects.get_or_create(
            media_id="12345",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            defaults={"title": "Season 1"},
        )[0]
        self.season = Season.objects.create(
            item=season_item,
            related_tv=tv_obj,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        self.episode_item = Item.objects.get_or_create(
            media_id="12345",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            defaults={"title": "One", "runtime_minutes": 45},
        )[0]
        Episode.objects.create(
            item=self.episode_item,
            related_season=self.season,
            end_date=timezone.datetime.fromisoformat("2023-01-01T00:00:00+00:00"),
        )

    def _entry(self, watched_at):
        return {
            "type": "episode",
            "episode": {"season": 1, "number": 1, "title": "One"},
            "show": {"title": "Dedupe Show", "ids": {"tmdb": 12345}},
            "watched_at": watched_at,
        }

    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_skips_play_30_minutes_from_an_existing_row(self, mock_get_metadata):
        """30 minutes sat inside Plex's window but outside Trakt's old 15 minutes.

        Which importer ran first decided whether the play survived twice. The
        episode runs 45 minutes, so 30 is inside its window and 45 would sit
        exactly on the boundary.
        """
        mock_get_metadata.side_effect = tv_metadata_side_effect

        trakt_importer = TraktImporter("testuser", self.user, "new")
        trakt_importer.process_watched_episode(self._entry("2023-01-01T00:30:00.000Z"))

        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.EPISODE.value]), 0)

    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_keeps_a_genuine_rewatch(self, mock_get_metadata):
        """A play outside the runtime-sized window is still imported."""
        mock_get_metadata.side_effect = tv_metadata_side_effect

        trakt_importer = TraktImporter("testuser", self.user, "new")
        trakt_importer.process_watched_episode(self._entry("2023-01-02T00:00:00.000Z"))

        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.EPISODE.value]), 1)


class PlexAfterTrakt(TestCase):
    """A Plex import must not duplicate a play Trakt already recorded.

    The mirror of TraktAfterPlex: with one shared window the outcome no longer
    depends on which source was imported first.
    """

    def setUp(self):
        """Create the user, the Plex account and the movie item."""
        self.user = get_user_model().objects.create_user(
            username="dedupe",
            password="12345",
        )
        self.account = PlexAccount.objects.create(
            user=self.user,
            plex_token="token",
        )
        self.item = Item.objects.get_or_create(
            media_id="900",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={"title": "Dedupe Movie", "runtime_minutes": 120},
        )[0]
        self.watched_at = timezone.now() - timedelta(days=2)

    def _importer(self):
        importer = PlexHistoryImporter(
            user=self.user,
            account=self.account,
            mode="new",
            library="machine::1",
        )
        importer._movie_ids.add("900")
        importer._build_existing_dedupe_sets()
        return importer

    @patch("app.providers.services.get_media_metadata", return_value=NO_MAX_PROGRESS)
    def test_skips_play_45_minutes_from_a_trakt_imported_row(self, _mock_metadata):
        """A gap Trakt's old 15 minute window would have let through."""
        Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.COMPLETED.value,
            end_date=self.watched_at,
        )

        importer = self._importer()
        record = {
            "tmdb_id": "900",
            "watched_at": self.watched_at + timedelta(minutes=45),
        }
        self.assertTrue(importer._should_skip_movie_record(record))

    @patch("app.providers.services.get_media_metadata", return_value=NO_MAX_PROGRESS)
    def test_skips_play_recorded_as_a_movie_play_row(self, _mock_metadata):
        """A rewatch stored via Movie.watch() suppresses the Plex duplicate."""
        movie = Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.COMPLETED.value,
            end_date=self.watched_at - timedelta(days=400),
        )
        movie.watch(self.watched_at)

        importer = self._importer()
        record = {
            "tmdb_id": "900",
            "watched_at": self.watched_at + timedelta(minutes=45),
        }
        self.assertTrue(importer._should_skip_movie_record(record))

    @patch("app.providers.services.get_media_metadata", return_value=NO_MAX_PROGRESS)
    def test_keeps_a_genuine_rewatch(self, _mock_metadata):
        """A play outside the runtime-sized window is still imported."""
        Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.COMPLETED.value,
            end_date=self.watched_at,
        )

        importer = self._importer()
        record = {
            "tmdb_id": "900",
            "watched_at": self.watched_at + timedelta(hours=5),
        }
        self.assertFalse(importer._should_skip_movie_record(record))


class WebhookAfterImport(TestCase):
    """A live Plex webhook must not duplicate an already-imported play."""

    def setUp(self):
        """Create the user and pin the playback timestamp."""
        self.user = get_user_model().objects.create_user(
            username="dedupe",
            password="12345",
        )
        self.played_at = timezone.now().replace(second=0, microsecond=0)

    def _movie_payload(self):
        return {
            "event": "media.scrobble",
            "Metadata": {
                "type": "movie",
                "title": "Dedupe Movie",
                "viewedAt": int(self.played_at.timestamp()),
                "Guid": [{"id": "tmdb://900"}],
            },
        }

    def _seed_movie(self, end_date):
        item = Item.objects.get_or_create(
            media_id="900",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={"title": "Dedupe Movie", "runtime_minutes": 120},
        )[0]
        Movie.objects.create(
            item=item,
            user=self.user,
            status=Status.COMPLETED.value,
            progress=1,
            end_date=end_date,
        )
        return item

    @patch("app.providers.services.get_media_metadata", return_value=NO_MAX_PROGRESS)
    @patch("app.services.metadata_resolution.upsert_provider_links")
    @patch("app.providers.tmdb.movie")
    def test_movie_webhook_skips_an_already_imported_play(
        self,
        mock_movie,
        _mock_links,
        _mock_metadata,
    ):
        """The COMPLETED branch created a second Movie row unconditionally."""
        mock_movie.return_value = {
            "title": "Dedupe Movie",
            "image": "https://example.com/m.jpg",
        }
        item = self._seed_movie(self.played_at - timedelta(minutes=20))

        PlexWebhookProcessor()._handle_movie("900", self._movie_payload(), self.user)

        self.assertEqual(Movie.objects.filter(item=item, user=self.user).count(), 1)

    @patch("app.providers.services.get_media_metadata", return_value=NO_MAX_PROGRESS)
    @patch("app.services.metadata_resolution.upsert_provider_links")
    @patch("app.providers.tmdb.movie")
    def test_movie_webhook_still_records_a_genuine_rewatch(
        self,
        mock_movie,
        _mock_links,
        _mock_metadata,
    ):
        """A rewatch outside the window still creates the second row."""
        mock_movie.return_value = {
            "title": "Dedupe Movie",
            "image": "https://example.com/m.jpg",
        }
        item = self._seed_movie(self.played_at - timedelta(days=3))

        PlexWebhookProcessor()._handle_movie("900", self._movie_payload(), self.user)

        self.assertEqual(Movie.objects.filter(item=item, user=self.user).count(), 2)

    @patch("app.providers.services.get_media_metadata", return_value=NO_MAX_PROGRESS)
    @patch("integrations.webhooks.anime_mappings.fetch_mapping_data", return_value={})
    @patch("app.services.metadata_resolution.upsert_provider_links")
    @patch("app.providers.tmdb.tv_with_seasons")
    def test_episode_webhook_skips_a_play_imported_ten_minutes_earlier(
        self,
        mock_tv_with_seasons,
        _mock_links,
        _mock_mapping_data,
        _mock_metadata,
    ):
        """The old guard compared the newest row within 5 seconds only."""
        mock_tv_with_seasons.return_value = {
            "title": "Dedupe Show",
            "image": "https://example.com/t.jpg",
            "synopsis": "",
            "external_links": {},
            "related": {"seasons": [{"season_number": 1}]},
            "season/1": {
                "image": "",
                "episodes": [
                    {"episode_number": 1, "runtime": 45},
                    {"episode_number": 2, "runtime": 45},
                ],
            },
        }
        tv_item = Item.objects.get_or_create(
            media_id="901",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            defaults={"title": "Dedupe Show"},
        )[0]
        tv_row = TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        season_item = Item.objects.get_or_create(
            media_id="901",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            defaults={"title": "Season 1"},
        )[0]
        season_row = Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=tv_row,
            status=Status.IN_PROGRESS.value,
        )
        episode_item = Item.objects.get_or_create(
            media_id="901",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            defaults={"title": "One", "runtime_minutes": 45},
        )[0]
        Episode.objects.create(
            item=episode_item,
            related_season=season_row,
            end_date=self.played_at - timedelta(minutes=10),
        )

        payload = {
            "event": "media.scrobble",
            "Metadata": {
                "type": "episode",
                "grandparentTitle": "Dedupe Show",
                "parentTitle": "Season 1",
                "title": "One",
                "index": 1,
                "parentIndex": 1,
                "viewedAt": int(self.played_at.timestamp()),
                "Guid": [{"id": "tmdb://901"}],
            },
        }

        PlexWebhookProcessor()._handle_tv_episode("901", 1, 1, payload, self.user)

        self.assertEqual(
            Episode.objects.filter(
                item__media_id="901",
                related_season__user=self.user,
            ).count(),
            1,
        )
