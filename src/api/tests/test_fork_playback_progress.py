# FORK: tests for the durable playback progress endpoint used by third-party
# clients doing bidirectional resume sync (issue #429).
import hashlib
import hmac
import json
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch

import requests
from django.test import override_settings
from django.utils import timezone

from api.fork_views_playback import upsert_playback_progress
from app import live_playback
from app.models import (
    Item,
    MediaTypes,
    Movie,
    PlaybackProgress,
    Podcast,
    PodcastEpisode,
    PodcastShow,
    ProgressChange,
    Sources,
    Status,
    WatchStateSequence,
)

from .base import FloppyApiTestCase


class PlaybackProgressWriteTests(FloppyApiTestCase):
    """PUT sets an absolute resume position for movies and episodes."""

    def _put(self, payload, headers=None):
        return self.call_api(
            "put",
            "api_playback_progress",
            payload=payload,
            headers=self.auth_headers if headers is None else headers,
        )

    def test_movie_position_created_then_updated(self):
        """A second PUT overwrites the stored position rather than adding one."""
        first = self._put(
            {
                "media_type": "movie",
                "ids": {"tmdb": "701"},
                "position_seconds": 900,
                "duration_seconds": 8160,
            },
        )
        self.assertEqual(first.status_code, HTTP.OK)
        self.assertEqual(first.json()["position_seconds"], 900)
        self.assertEqual(first.json()["duration_seconds"], 8160)
        self.assertFalse(first.json()["completed"])

        second = self._put(
            {
                "media_type": "movie",
                "ids": {"tmdb": "701"},
                "position_seconds": 1800,
                "completed": True,
            },
        )
        self.assertEqual(second.status_code, HTTP.OK)

        progress = PlaybackProgress.objects.get(
            user=self.user1,
            item__media_id="701",
        )
        self.assertEqual(progress.position_seconds, 1800)
        self.assertTrue(progress.completed)

    def test_episode_position_reports_series_and_show_ids(self):
        """Episode entries carry the show title and the show's external ids."""
        show = self.items_by_type[MediaTypes.TV.value][0]
        show.provider_external_ids = {"tmdb_id": "1001", "imdb_id": "tt0001"}
        show.save(update_fields=["provider_external_ids"])

        response = self._put(
            {
                "media_type": "episode",
                "ids": {"tmdb": "1001"},
                "season_number": 1,
                "episode_number": 2,
                "position_seconds": 300,
            },
        )

        self.assertEqual(response.status_code, HTTP.OK)
        body = response.json()
        self.assertEqual(body["media_type"], "episode")
        self.assertEqual(body["season_number"], 1)
        self.assertEqual(body["episode_number"], 2)
        self.assertEqual(body["series_title"], "TV Show 1")
        self.assertEqual(body["ids"], {"tmdb": "1001", "imdb": "tt0001"})
        self.assertEqual(body["image"], "https://example.com/episode-2.jpg")
        self.assertIsNotNone(body["url"])

    def test_unknown_movie_creates_item_without_watch_record(self):
        """Positions for untracked media create metadata only, never history."""
        new_item = Item.objects.create(
            media_id="99999",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Brand New Movie",
            image="https://example.com/new.jpg",
        )
        with patch(
            "api.fork_views_playback.ensure_item_metadata",
        ) as mock_ensure:
            mock_ensure.return_value.item = new_item
            response = self._put(
                {
                    "media_type": "movie",
                    "ids": {"tmdb": "99999"},
                    "position_seconds": 120,
                },
            )

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertTrue(
            PlaybackProgress.objects.filter(user=self.user1, item=new_item).exists(),
        )
        self.assertFalse(Movie.objects.filter(item=new_item).exists())

    def test_unresolvable_media_returns_404(self):
        """An id that resolves to nothing is a 404, not a silent no-op."""
        with patch(
            "api.fork_views_playback.app.providers.tmdb.find",
            return_value={},
        ):
            response = self._put(
                {
                    "media_type": "movie",
                    "ids": {"imdb": "tt-unknown"},
                    "position_seconds": 120,
                },
            )

        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    def test_positions_are_per_user(self):
        """Two users can hold different positions for the same item."""
        self._put(
            {"media_type": "movie", "ids": {"tmdb": "701"}, "position_seconds": 100},
        )
        self._put(
            {"media_type": "movie", "ids": {"tmdb": "701"}, "position_seconds": 200},
            headers=self.auth_headers2,
        )

        self.assertEqual(
            PlaybackProgress.objects.get(
                user=self.user1,
                item__media_id="701",
            ).position_seconds,
            100,
        )
        self.assertEqual(
            PlaybackProgress.objects.get(
                user=self.user2,
                item__media_id="701",
            ).position_seconds,
            200,
        )


class PlaybackProgressValidationTests(FloppyApiTestCase):
    """400s for malformed write payloads."""

    def _put(self, payload):
        return self.call_api(
            "put",
            "api_playback_progress",
            payload=payload,
            headers=self.auth_headers,
        )

    def test_invalid_media_type_rejected(self):
        """Only movie/episode/podcast are accepted."""
        response = self._put(
            {"media_type": "book", "ids": {"tmdb": "701"}, "position_seconds": 10},
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_missing_ids_rejected(self):
        """At least one of tmdb/imdb/tvdb is required."""
        response = self._put(
            {"media_type": "movie", "ids": {}, "position_seconds": 10},
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_episode_without_season_episode_rejected(self):
        """Episode writes require season_number/episode_number."""
        response = self._put(
            {"media_type": "episode", "ids": {"tmdb": "1001"}, "position_seconds": 10},
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_missing_position_rejected(self):
        """Omitting position_seconds entirely is an error, unlike sending null."""
        response = self._put({"media_type": "movie", "ids": {"tmdb": "701"}})
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_negative_position_rejected(self):
        """position_seconds must be a non-negative integer."""
        response = self._put(
            {"media_type": "movie", "ids": {"tmdb": "701"}, "position_seconds": -5},
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_podcast_without_episode_uuid_rejected(self):
        """Podcasts identify by episode_uuid."""
        response = self._put(
            {"media_type": "podcast", "ids": {"tmdb": "1"}, "position_seconds": 10},
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)


class PlaybackProgressClearTests(FloppyApiTestCase):
    """DELETE and a null position both clear a saved position."""

    def setUp(self):
        """Seed a stored movie position."""
        super().setUp()
        self.progress = PlaybackProgress.objects.create(
            user=self.user1,
            item=self.items_by_type[MediaTypes.MOVIE.value][0],
            position_seconds=900,
        )

    def test_delete_clears_position(self):
        """A DELETE with the identifying body removes the row."""
        response = self.call_api(
            "delete",
            "api_playback_progress",
            payload={"media_type": "movie", "ids": {"tmdb": "701"}},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.NO_CONTENT)
        self.assertFalse(PlaybackProgress.objects.filter(id=self.progress.id).exists())

    def test_null_position_clears_position(self):
        """PUT with position_seconds null is equivalent to DELETE."""
        response = self.call_api(
            "put",
            "api_playback_progress",
            payload={
                "media_type": "movie",
                "ids": {"tmdb": "701"},
                "position_seconds": None,
            },
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.NO_CONTENT)
        self.assertFalse(PlaybackProgress.objects.filter(id=self.progress.id).exists())

    def test_delete_does_not_touch_other_users(self):
        """Clearing only affects the requesting user's row."""
        other = PlaybackProgress.objects.create(
            user=self.user2,
            item=self.items_by_type[MediaTypes.MOVIE.value][0],
            position_seconds=500,
        )
        self.call_api(
            "delete",
            "api_playback_progress",
            payload={"media_type": "movie", "ids": {"tmdb": "701"}},
            headers=self.auth_headers,
        )
        self.assertTrue(PlaybackProgress.objects.filter(id=other.id).exists())


class PlaybackProgressListTests(FloppyApiTestCase):
    """GET lists saved positions with delta-sync friendly filters."""

    def setUp(self):
        """Seed movie, episode and podcast positions for user1."""
        super().setUp()
        self.movie_progress = PlaybackProgress.objects.create(
            user=self.user1,
            item=self.items_by_type[MediaTypes.MOVIE.value][0],
            position_seconds=900,
            duration_seconds=8160,
        )
        self.episode_progress = PlaybackProgress.objects.create(
            user=self.user1,
            item=self.items_by_type[MediaTypes.EPISODE.value][0],
            position_seconds=300,
            completed=True,
        )
        self.podcast = self._create_podcast(played_up_to_seconds=450)

    def _create_podcast(self, played_up_to_seconds):
        """Create a tracked podcast episode carrying a resume position."""
        show = PodcastShow.objects.create(
            podcast_uuid="show-uuid-1",
            title="Podcast Show 1",
        )
        episode = PodcastEpisode.objects.create(
            show=show,
            episode_uuid="episode-uuid-1",
            title="Podcast Episode 1",
            duration=3600,
        )
        item = Item.objects.create(
            media_id="episode-uuid-1",
            source=Sources.POCKETCASTS.value,
            media_type=MediaTypes.PODCAST.value,
            title="Podcast Episode 1",
            image="https://example.com/podcast-1.jpg",
        )
        return Podcast.objects.create(
            user=self.user1,
            item=item,
            show=show,
            episode=episode,
            status=Status.IN_PROGRESS.value,
            played_up_to_seconds=played_up_to_seconds,
            position_updated_at=timezone.now(),
        )

    def _get(self, params=None, headers=None):
        return self.call_api(
            "get",
            "api_playback_progress",
            params=params,
            headers=self.auth_headers if headers is None else headers,
        )

    def test_lists_all_media_types(self):
        """Movies, episodes and podcasts appear in one merged feed."""
        response = self._get()

        self.assertEqual(response.status_code, HTTP.OK)
        body = response.json()
        self.assertEqual(body["pagination"]["total"], 3)
        self.assertEqual(
            {entry["media_type"] for entry in body["results"]},
            {"movie", "episode", "podcast"},
        )
        for entry in body["results"]:
            self.assertIn("image", entry)
            self.assertIn("url", entry)
        podcast_entry = next(
            entry for entry in body["results"] if entry["media_type"] == "podcast"
        )
        self.assertEqual(podcast_entry["image"], "https://example.com/podcast-1.jpg")

    def test_media_type_filter(self):
        """?media_type= accepts a comma separated subset."""
        response = self._get({"media_type": "movie,episode"})

        body = response.json()
        self.assertEqual(body["pagination"]["total"], 2)
        self.assertNotIn(
            "podcast",
            {entry["media_type"] for entry in body["results"]},
        )

    def test_invalid_media_type_filter_rejected(self):
        """An unknown media_type filter is a 400."""
        response = self._get({"media_type": "book"})
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_completed_filter(self):
        """?completed= splits finished from in-progress positions."""
        completed = self._get({"completed": "true"}).json()
        in_progress = self._get({"completed": "false"}).json()

        self.assertEqual(
            [entry["media_type"] for entry in completed["results"]],
            ["episode"],
        )
        self.assertEqual(
            {entry["media_type"] for entry in in_progress["results"]},
            {"movie", "podcast"},
        )

    def test_updated_since_filter(self):
        """?updated_since= returns only rows touched after the cutoff."""
        cutoff = timezone.now()
        self.movie_progress.position_seconds = 1200
        self.movie_progress.save()

        response = self._get({"updated_since": cutoff.isoformat()})

        body = response.json()
        self.assertEqual(body["pagination"]["total"], 1)
        self.assertEqual(body["results"][0]["media_type"], "movie")

    def test_invalid_updated_since_rejected(self):
        """An unparseable updated_since is a 400."""
        response = self._get({"updated_since": "not-a-date"})
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_pagination(self):
        """limit/offset slice the merged feed and report the true total."""
        first = self._get({"limit": 2}).json()

        self.assertEqual(len(first["results"]), 2)
        self.assertEqual(first["pagination"]["total"], 3)
        self.assertIsNotNone(first["pagination"]["next"])

        second = self._get({"limit": 2, "offset": 2}).json()
        self.assertEqual(len(second["results"]), 1)

    def test_podcast_entry_shape(self):
        """Podcast entries report seconds, episode duration and episode_uuid."""
        response = self._get({"media_type": "podcast"})

        entry = response.json()["results"][0]
        self.assertEqual(entry["position_seconds"], 450)
        self.assertEqual(entry["duration_seconds"], 3600)
        self.assertEqual(entry["ids"], {"episode_uuid": "episode-uuid-1"})
        self.assertEqual(entry["series_title"], "Podcast Show 1")
        self.assertFalse(entry["completed"])

    def test_other_users_positions_are_hidden(self):
        """user2 sees none of user1's positions."""
        response = self._get(headers=self.auth_headers2)
        self.assertEqual(response.json()["pagination"]["total"], 0)


class PlaybackProgressPodcastWriteTests(FloppyApiTestCase):
    """Podcast writes land on the field the podcast UI already reads."""

    def setUp(self):
        """Seed a tracked podcast episode with no position yet."""
        super().setUp()
        self.show = PodcastShow.objects.create(
            podcast_uuid="show-uuid-2",
            title="Podcast Show 2",
        )
        self.episode = PodcastEpisode.objects.create(
            show=self.show,
            episode_uuid="episode-uuid-2",
            title="Podcast Episode 2",
            duration=1800,
        )
        self.item = Item.objects.create(
            media_id="episode-uuid-2",
            source=Sources.POCKETCASTS.value,
            media_type=MediaTypes.PODCAST.value,
            title="Podcast Episode 2",
            image="https://example.com/podcast-2.jpg",
        )
        self.podcast = Podcast.objects.create(
            user=self.user1,
            item=self.item,
            show=self.show,
            episode=self.episode,
            status=Status.IN_PROGRESS.value,
        )

    def test_write_sets_played_up_to_and_timestamp(self):
        """The position lands on played_up_to_seconds with a fresh timestamp."""
        response = self.call_api(
            "put",
            "api_playback_progress",
            payload={
                "media_type": "podcast",
                "ids": {"episode_uuid": "episode-uuid-2"},
                "position_seconds": 600,
            },
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.OK)
        self.podcast.refresh_from_db()
        self.assertEqual(self.podcast.played_up_to_seconds, 600)
        self.assertIsNotNone(self.podcast.position_updated_at)

    def test_untracked_episode_returns_404(self):
        """A resume position never creates podcast tracking from scratch."""
        response = self.call_api(
            "put",
            "api_playback_progress",
            payload={
                "media_type": "podcast",
                "ids": {"episode_uuid": "unknown-uuid"},
                "position_seconds": 600,
            },
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    def test_delete_clears_played_up_to(self):
        """Clearing nulls the stored seconds."""
        self.podcast.played_up_to_seconds = 600
        self.podcast.save(update_fields=["played_up_to_seconds"])

        response = self.call_api(
            "delete",
            "api_playback_progress",
            payload={
                "media_type": "podcast",
                "ids": {"episode_uuid": "episode-uuid-2"},
            },
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.NO_CONTENT)
        self.podcast.refresh_from_db()
        self.assertIsNone(self.podcast.played_up_to_seconds)


class PlaybackProgressScrobbleTests(FloppyApiTestCase):
    """Scrobble 'stop' leaves a durable position behind."""

    def _stop(self, position_seconds, duration_seconds):
        """Send a stop event with the processor's durable write mocked out."""
        with patch(
            "integrations.webhooks.generic_scrobble.GenericScrobbleProcessor"
            ".process_payload",
        ):
            return self.call_api(
                "post",
                "api_scrobble",
                payload={
                    "action": "stop",
                    "media_type": "movie",
                    "ids": {"tmdb": "701"},
                    "position_seconds": position_seconds,
                    "duration_seconds": duration_seconds,
                },
                headers=self.auth_headers,
            )

    @patch("api.fork_views_scrobble.live_playback.apply_playback_event")
    def test_stop_near_end_stores_completed_position(self, _mock_apply_event):
        """Stopping inside the completion buffer marks the position complete."""
        response = self._stop(8150, 8160)

        self.assertEqual(response.status_code, HTTP.OK)
        progress = PlaybackProgress.objects.get(
            user=self.user1,
            item__media_id="701",
        )
        self.assertEqual(progress.position_seconds, 8150)
        self.assertTrue(progress.completed)

    @patch("api.fork_views_scrobble.live_playback.apply_playback_event")
    def test_stop_mid_playback_stores_resumable_position(self, _mock_apply_event):
        """Stopping partway through leaves a resumable, incomplete position."""
        response = self._stop(900, 8160)

        self.assertEqual(response.status_code, HTTP.OK)
        progress = PlaybackProgress.objects.get(
            user=self.user1,
            item__media_id="701",
        )
        self.assertEqual(progress.position_seconds, 900)
        self.assertFalse(progress.completed)

    @patch("api.fork_views_scrobble.live_playback.apply_playback_event")
    def test_start_stores_nothing(self, _mock_apply_event):
        """'start' stays a no-op for durable storage."""
        response = self.call_api(
            "post",
            "api_scrobble",
            payload={
                "action": "start",
                "media_type": "movie",
                "ids": {"tmdb": "701"},
                "position_seconds": 60,
            },
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertFalse(PlaybackProgress.objects.filter(user=self.user1).exists())

    @patch("api.fork_views_scrobble.live_playback.apply_playback_event")
    def test_progress_failure_does_not_fail_scrobble(self, _mock_apply_event):
        """A progress-write failure never surfaces as a scrobble error."""
        with (
            patch(
                "integrations.webhooks.generic_scrobble.GenericScrobbleProcessor"
                ".process_payload",
            ),
            patch(
                "api.fork_views_playback.upsert_playback_progress",
                side_effect=RuntimeError("db down"),
            ),
        ):
            response = self.call_api(
                "post",
                "api_scrobble",
                payload={
                    "action": "stop",
                    "media_type": "movie",
                    "ids": {"tmdb": "701"},
                    "position_seconds": 8000,
                },
                headers=self.auth_headers,
            )

        self.assertEqual(response.status_code, HTTP.OK)


class PlaybackProgressEventOrderTests(FloppyApiTestCase):
    """Webhook writes are ordered by receipt time, not by when they ran."""

    def setUp(self):
        """Use one movie item and a whole-second receipt clock."""
        super().setUp()
        self.item = self.items_by_type[MediaTypes.MOVIE.value][0]
        self.now_ts = int(timezone.now().timestamp())

    def _write(self, position, *, completed=False, event_at=None):
        return upsert_playback_progress(
            self.user1,
            self.item,
            position,
            3000,
            completed=completed,
            event_at=event_at,
        )

    def _stored(self):
        return PlaybackProgress.objects.get(user=self.user1, item=self.item)

    def test_backlogged_events_apply_in_receipt_order(self):
        """A queue backlog processes both events after they were received."""
        self._write(1200, event_at=self.now_ts - 10)
        self._write(2990, completed=True, event_at=self.now_ts - 5)

        progress = self._stored()
        self.assertEqual(progress.position_seconds, 2990)
        self.assertTrue(progress.completed)

    def test_older_event_in_the_same_second_is_dropped(self):
        """Receipt time keeps its fraction, so one second can hold two events."""
        self._write(2990, completed=True, event_at=self.now_ts + 0.9)
        self._write(0, event_at=self.now_ts + 0.1)

        progress = self._stored()
        self.assertEqual(progress.position_seconds, 2990)
        self.assertTrue(progress.completed)

    def test_equal_receipt_time_applies_in_processing_order(self):
        """An identical time is not evidence of disorder, so it applies."""
        self._write(1200, event_at=self.now_ts + 0.5)
        self._write(1300, event_at=self.now_ts + 0.5)

        self.assertEqual(self._stored().position_seconds, 1300)

    def test_whole_second_event_times_still_order(self):
        """Integer epochs from older callers compare against fractional ones."""
        self._write(1200, event_at=self.now_ts)
        self._write(0, event_at=self.now_ts - 1)
        self.assertEqual(self._stored().position_seconds, 1200)

        self._write(1300, event_at=self.now_ts + 0.5)
        self._write(1250, event_at=self.now_ts)
        self.assertEqual(self._stored().position_seconds, 1300)

    def test_dropped_event_saves_nothing(self):
        """A stale write neither touches the row nor publishes a change."""
        self._write(2990, completed=True, event_at=self.now_ts)
        before = self._stored()
        changes = ProgressChange.objects.filter(user=self.user1, item=self.item)
        change_count = changes.count()

        self._write(0, event_at=self.now_ts - 1)

        after = self._stored()
        self.assertEqual(after.updated_at, before.updated_at)
        self.assertEqual(after.last_event_at, before.last_event_at)
        self.assertEqual(changes.count(), change_count)

    def test_repeated_position_publishes_no_change(self):
        """A newer event with the same values advances the clock only."""
        self._write(1200, event_at=self.now_ts)
        changes = ProgressChange.objects.filter(user=self.user1, item=self.item)
        change_count = changes.count()

        self._write(1200, event_at=self.now_ts + 1)

        self.assertEqual(changes.count(), change_count)
        self.assertEqual(self._stored().last_event_at.timestamp(), self.now_ts + 1)

    def test_clock_only_write_keeps_updated_at(self):
        """With every field preserved, a newer event moves only the clock."""
        self._write(1200, event_at=self.now_ts)
        before = self._stored()
        changes = ProgressChange.objects.filter(user=self.user1, item=self.item)
        change_count = changes.count()

        upsert_playback_progress(
            self.user1,
            self.item,
            None,
            None,
            preserve_position=True,
            preserve_duration=True,
            preserve_completed=True,
            event_at=self.now_ts + 1.25,
        )

        after = self._stored()
        self.assertEqual(after.last_event_at.timestamp(), self.now_ts + 1.25)
        self.assertEqual(after.updated_at, before.updated_at)
        self.assertEqual(after.position_seconds, 1200)
        self.assertEqual(changes.count(), change_count)

    def test_row_with_unknown_clock_takes_the_next_event(self):
        """Rows from before the clock existed are not dated by ``updated_at``.

        ``updated_at`` is processing time, so using it would drop a valid
        backlogged event; the first event applies and starts the clock.
        """
        PlaybackProgress.objects.create(
            user=self.user1,
            item=self.item,
            position_seconds=600,
            duration_seconds=3000,
        )
        self._write(1200, event_at=self.now_ts - 60)

        progress = self._stored()
        self.assertEqual(progress.position_seconds, 1200)
        self.assertEqual(progress.last_event_at.timestamp(), self.now_ts - 60)

        self._write(0, event_at=self.now_ts - 61)
        self.assertEqual(self._stored().position_seconds, 1200)

    def test_older_event_processed_later_is_dropped(self):
        """A late play must not reset a completed scrobble (#1708)."""
        self._write(2990, completed=True, event_at=self.now_ts)
        self._write(0, event_at=self.now_ts - 1)

        progress = self._stored()
        self.assertEqual(progress.position_seconds, 2990)
        self.assertTrue(progress.completed)

    def test_write_without_event_time_keeps_the_event_clock(self):
        """An API write applies but does not reorder webhook events."""
        self._write(1200, event_at=self.now_ts)
        self._write(1500)
        self.assertEqual(self._stored().position_seconds, 1500)

        self._write(0, event_at=self.now_ts - 1)
        self.assertEqual(self._stored().position_seconds, 1500)
        self._write(1600, event_at=self.now_ts + 1)
        self.assertEqual(self._stored().position_seconds, 1600)


class PlaybackProgressCompletionOrderTests(FloppyApiTestCase):
    """Marking a title watched closes its resume point in receipt order."""

    def setUp(self):
        """Use one tracked movie whose progress changes are recorded."""
        super().setUp()
        self.movie = self.movie_medias[0]
        self.item = self.movie.item
        self.now_ts = int(timezone.now().timestamp())
        WatchStateSequence.objects.update_or_create(
            user=self.user1,
            defaults={"emit_changes": True},
        )

    def _write(self, position, *, event_at=None):
        return upsert_playback_progress(
            self.user1,
            self.item,
            position,
            3000,
            event_at=event_at,
        )

    def _stored(self):
        return PlaybackProgress.objects.get(user=self.user1, item=self.item)

    def _changes(self):
        return ProgressChange.objects.filter(user=self.user1, item=self.item)

    def _mark_watched(self, event_at=None):
        self.movie.status = Status.COMPLETED.value
        if event_at is None:
            self.movie.save()
            return
        with live_playback.webhook_event_time(event_at):
            self.movie.save()

    def test_stale_webhook_completion_leaves_newer_progress_alone(self):
        """A completion received before newer progress changes nothing."""
        self._write(1200, event_at=self.now_ts)
        before = self._stored()
        change_count = self._changes().count()

        self._mark_watched(event_at=self.now_ts - 0.5)

        after = self._stored()
        self.assertFalse(after.completed)
        self.assertEqual(after.position_seconds, 1200)
        self.assertEqual(after.duration_seconds, 3000)
        self.assertEqual(after.last_event_at, before.last_event_at)
        self.assertEqual(after.updated_at, before.updated_at)
        self.assertEqual(self._changes().count(), change_count)

    def test_webhook_completion_takes_its_receipt_time(self):
        """An older pause processed after the completion cannot reopen it."""
        self._write(1200, event_at=self.now_ts - 10)
        change_count = self._changes().count()

        self._mark_watched(event_at=self.now_ts + 0.25)

        progress = self._stored()
        self.assertTrue(progress.completed)
        self.assertEqual(progress.position_seconds, 1200)
        self.assertEqual(progress.duration_seconds, 3000)
        self.assertEqual(progress.last_event_at.timestamp(), self.now_ts + 0.25)
        self.assertEqual(self._changes().count(), change_count + 1)
        self.assertTrue(self._changes().order_by("-sequence").first().completed)

        self._write(0, event_at=self.now_ts)

        progress = self._stored()
        self.assertTrue(progress.completed)
        self.assertEqual(progress.position_seconds, 1200)

    def test_webhook_completion_of_a_closed_row_moves_only_the_clock(self):
        """Nothing a client reads changed, so nothing is published."""
        upsert_playback_progress(
            self.user1,
            self.item,
            2990,
            3000,
            completed=True,
            event_at=self.now_ts - 10,
        )
        before = self._stored()
        change_count = self._changes().count()

        self._mark_watched(event_at=self.now_ts)

        after = self._stored()
        self.assertEqual(after.last_event_at.timestamp(), self.now_ts)
        self.assertEqual(after.updated_at, before.updated_at)
        self.assertEqual(self._changes().count(), change_count)

    def test_timestamp_free_completion_keeps_the_event_clock(self):
        """A UI or API mark has no receipt time, so it neither sets nor checks one.

        The documented tradeoff: a newer webhook still applies over it.
        """
        self._write(1200, event_at=self.now_ts)
        change_count = self._changes().count()

        self._mark_watched()

        progress = self._stored()
        self.assertTrue(progress.completed)
        self.assertEqual(progress.position_seconds, 1200)
        self.assertEqual(progress.duration_seconds, 3000)
        self.assertEqual(progress.last_event_at.timestamp(), self.now_ts)
        self.assertGreater(self._changes().count(), change_count)

        self._write(0, event_at=self.now_ts - 1)
        self.assertTrue(self._stored().completed)
        self._write(600, event_at=self.now_ts + 1)
        self.assertFalse(self._stored().completed)

    def test_timestamp_free_episode_completion_keeps_an_unknown_clock(self):
        """An episode closes the same way and a row without a clock keeps none."""
        episode = self.episode_medias[0]
        PlaybackProgress.objects.create(
            user=self.user1,
            item=episode.item,
            position_seconds=900,
            duration_seconds=1300,
        )

        episode.status = Status.COMPLETED.value
        episode.end_date = timezone.now()
        episode.save()

        progress = PlaybackProgress.objects.get(user=self.user1, item=episode.item)
        self.assertTrue(progress.completed)
        self.assertEqual(progress.position_seconds, 900)
        self.assertEqual(progress.duration_seconds, 1300)
        self.assertIsNone(progress.last_event_at)


class PlaybackWebhookTests(FloppyApiTestCase):
    """A state change POSTs the now-playing body to a configured webhook."""

    def _play(self, user, **overrides):
        """Write an active movie state, which is what triggers the webhook."""
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        now_ts = live_playback._now_ts()
        state = {
            "event_type": "media.play",
            "media_type": MediaTypes.MOVIE.value,
            "media_id": movie_item.media_id,
            "source": movie_item.source,
            "rating_key": "rk-1",
            "title": movie_item.title,
            "image": "https://example.com/now-playing.jpg",
            "image_source": "primary",
            "view_offset_seconds": 60,
            "duration_seconds": 3000,
            "started_at_ts": now_ts,
            "status": live_playback.PLAYBACK_STATUS_PLAYING,
            "updated_at_ts": now_ts,
            "expires_at_ts": now_ts + 3600,
            "pause_expires_at_ts": None,
            "scrobble_expires_at_ts": None,
        }
        state.update(overrides)
        live_playback.set_user_playback_state(user.id, state)
        self.addCleanup(live_playback.clear_user_playback_state, user.id)

    def test_no_webhook_configured_sends_nothing(self):
        """The default is blank, and a blank URL must cost no outbound call."""
        with patch("requests.post") as post:
            self._play(self.user1)
        post.assert_not_called()

    def test_configured_webhook_receives_the_now_playing_body(self):
        """The POST body is the same shape /playback/now-playing/ returns."""
        self.user1.playback_webhook_url = "https://example.com/playback"
        self.user1.save(update_fields=["playback_webhook_url"])

        with patch("requests.post") as post:
            self._play(self.user1)

        post.assert_called_once()
        self.assertEqual(post.call_args.args[0], "https://example.com/playback")
        body = json.loads(post.call_args.kwargs["data"])
        self.assertTrue(body["active"])
        self.assertEqual(body["media_type"], MediaTypes.MOVIE.value)
        self.assertEqual(body["status"], live_playback.PLAYBACK_STATUS_PLAYING)
        # The fields a client needs to render and to tick between events.
        for key in ("title", "progress_percent", "duration_seconds", "updated_at"):
            self.assertIn(key, body)

    def test_a_pause_is_delivered_as_its_own_event(self):
        """Pause is the state change the whole feature exists to deliver."""
        self.user1.playback_webhook_url = "https://example.com/playback"
        self.user1.save(update_fields=["playback_webhook_url"])

        with patch("requests.post") as post:
            self._play(self.user1, status=live_playback.PLAYBACK_STATUS_PAUSED)

        body = json.loads(post.call_args.kwargs["data"])
        self.assertEqual(body["status"], live_playback.PLAYBACK_STATUS_PAUSED)

    def test_only_the_configured_user_is_notified(self):
        """One user's webhook must never receive another user's playback."""
        self.user1.playback_webhook_url = "https://example.com/playback"
        self.user1.save(update_fields=["playback_webhook_url"])

        with patch("requests.post") as post:
            self._play(self.user2)
        post.assert_not_called()

    def test_signature_verifies_against_the_exact_bytes_sent(self):
        """The receiver must be able to reproduce the HMAC from the body."""
        self.user1.playback_webhook_url = "https://example.com/playback"
        self.user1.set_playback_webhook_secret("s3cret")
        self.user1.save(
            update_fields=["playback_webhook_url", "playback_webhook_secret"],
        )

        with patch("requests.post") as post:
            self._play(self.user1)

        sent = post.call_args.kwargs["data"]
        header = post.call_args.kwargs["headers"]["X-Floppy-Signature"]
        expected = hmac.new(b"s3cret", sent, hashlib.sha256).hexdigest()
        self.assertEqual(header, f"sha256={expected}")
        # Signed over raw bytes, so the body must go out as `data`, not `json`
        # — `requests` re-encoding a dict would produce bytes the receiver
        # cannot reproduce from what it was given.
        self.assertNotIn("json", post.call_args.kwargs)
        self.assertEqual(json.loads(sent)["status"], live_playback.PLAYBACK_STATUS_PLAYING)

    def test_no_secret_sends_no_signature(self):
        """Signing is optional; without a secret the header is absent."""
        self.user1.playback_webhook_url = "https://example.com/playback"
        self.user1.save(update_fields=["playback_webhook_url"])

        with patch("requests.post") as post:
            self._play(self.user1)

        self.assertNotIn("X-Floppy-Signature", post.call_args.kwargs["headers"])

    def test_redirects_are_not_followed(self):
        """A user-supplied URL must not redirect the server onto another host."""
        self.user1.playback_webhook_url = "https://example.com/playback"
        self.user1.save(update_fields=["playback_webhook_url"])

        with patch("requests.post") as post:
            self._play(self.user1)

        self.assertFalse(post.call_args.kwargs["allow_redirects"])

    def test_a_failing_endpoint_does_not_break_the_state_write(self):
        """A dead relay must not take the playback state down with it."""
        self.user1.playback_webhook_url = "https://example.com/playback"
        self.user1.save(update_fields=["playback_webhook_url"])

        with patch("requests.post", side_effect=requests.ConnectionError("down")):
            self._play(self.user1)

        # The state is still readable, which is what the web card renders from.
        state = live_playback.get_user_playback_state(self.user1.id)
        self.assertIsNotNone(state)
        self.assertEqual(state["status"], live_playback.PLAYBACK_STATUS_PLAYING)

    @override_settings(ROOT_URLCONF="config.celery_urls")
    def test_delivers_from_a_worker_with_no_url_routes(self):
        """The task runs in a Celery worker, whose URLconf is deliberately empty.

        Tests run tasks eagerly under the full URLconf, so without pinning the
        worker's one here, a `reverse()` on the payload path passes every other
        test and fails on every real delivery.
        """
        self.user1.playback_webhook_url = "https://example.com/playback"
        self.user1.save(update_fields=["playback_webhook_url"])
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]

        # One state per URL shape the card can link to.
        cases = {
            "media details": ({}, f"/{movie_item.media_id}/"),
            "season details": (
                {
                    "media_type": MediaTypes.EPISODE.value,
                    "series_title": "Some Show",
                    "season_number": 2,
                    "episode_number": 5,
                },
                "/season/2",
            ),
            "home, when the item is unresolved": ({"media_id": None}, None),
        }
        for label, (overrides, url_part) in cases.items():
            with self.subTest(label), patch("requests.post") as post:
                self._play(self.user1, **overrides)

                post.assert_called_once()
                body = json.loads(post.call_args.kwargs["data"])
                self.assertTrue(body["active"])
                if url_part is None:
                    self.assertEqual(body["url"], "/")
                else:
                    self.assertIn(url_part, body["url"])

    @override_settings(ROOT_URLCONF="config.celery_urls", FORCE_SCRIPT_NAME="/floppy")
    def test_worker_delivery_keeps_the_base_url_subpath(self):
        """A worker never handles a request, so BASE_URL has to be applied by hand."""
        self.user1.playback_webhook_url = "https://example.com/playback"
        self.user1.save(update_fields=["playback_webhook_url"])

        with patch("requests.post") as post:
            self._play(self.user1)

        body = json.loads(post.call_args.kwargs["data"])
        self.assertTrue(body["url"].startswith("/floppy/details/"), body["url"])


class NowPlayingTests(FloppyApiTestCase):
    """GET /playback/now-playing/ projects the live_playback cache as JSON."""

    def _get(self, headers=None):
        return self.call_api(
            "get",
            "api_playback_now_playing",
            headers=self.auth_headers if headers is None else headers,
        )

    def test_no_active_state_reports_inactive(self):
        """No cached playback state returns {"active": false}."""
        response = self._get()
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json(), {"active": False})

    def test_active_movie_state_is_projected(self):
        """An active movie state surfaces title/image/progress/url/ids."""
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        now_ts = live_playback._now_ts()
        live_playback.set_user_playback_state(
            self.user1.id,
            {
                "event_type": "media.play",
                "media_type": MediaTypes.MOVIE.value,
                "media_id": movie_item.media_id,
                "source": movie_item.source,
                "rating_key": "rk-1",
                "title": movie_item.title,
                "image": "https://example.com/now-playing.jpg",
                "image_source": "primary",
                "view_offset_seconds": 60,
                "duration_seconds": 3000,
                "started_at_ts": now_ts,
                "status": live_playback.PLAYBACK_STATUS_PLAYING,
                "updated_at_ts": now_ts,
                "expires_at_ts": now_ts + 3600,
                "pause_expires_at_ts": None,
                "scrobble_expires_at_ts": None,
            },
        )
        self.addCleanup(live_playback.clear_user_playback_state, self.user1.id)

        response = self._get()
        self.assertEqual(response.status_code, HTTP.OK)
        body = response.json()
        self.assertTrue(body["active"])
        self.assertEqual(body["media_type"], MediaTypes.MOVIE.value)
        self.assertEqual(body["title"], movie_item.title)
        self.assertEqual(body["image"], "https://example.com/now-playing.jpg")
        self.assertEqual(body["status"], live_playback.PLAYBACK_STATUS_PLAYING)
        self.assertIsNotNone(body["url"])
        self.assertIn("ids", body)
        self.assertIsNotNone(body["updated_at"])

    def test_release_year_is_serialized(self):
        """A film has no subtitle, so the year is what a client can show."""
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        movie_item.release_datetime = timezone.now()
        movie_item.save(update_fields=["release_datetime"])
        now_ts = live_playback._now_ts()
        live_playback.set_user_playback_state(
            self.user1.id,
            {
                "event_type": "media.play",
                "media_type": MediaTypes.MOVIE.value,
                "media_id": movie_item.media_id,
                "source": movie_item.source,
                "title": movie_item.title,
                "image": "https://example.com/np.jpg",
                "view_offset_seconds": 60,
                "duration_seconds": 3000,
                "started_at_ts": now_ts,
                "status": live_playback.PLAYBACK_STATUS_PLAYING,
                "updated_at_ts": now_ts,
                "expires_at_ts": now_ts + 3600,
                "pause_expires_at_ts": None,
                "scrobble_expires_at_ts": None,
            },
        )
        self.addCleanup(live_playback.clear_user_playback_state, self.user1.id)

        body = self._get().json()
        self.assertEqual(body["release_year"], timezone.now().year)
        # And a film still carries no subtitle, which is why the year is here.
        self.assertIsNone(body["subtitle"])

    def test_release_year_is_null_when_undated(self):
        """An undated item must not invent a year."""
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        movie_item.release_datetime = None
        movie_item.save(update_fields=["release_datetime"])
        now_ts = live_playback._now_ts()
        live_playback.set_user_playback_state(
            self.user1.id,
            {
                "event_type": "media.play",
                "media_type": MediaTypes.MOVIE.value,
                "media_id": movie_item.media_id,
                "source": movie_item.source,
                "title": movie_item.title,
                "duration_seconds": 3000,
                "started_at_ts": now_ts,
                "status": live_playback.PLAYBACK_STATUS_PLAYING,
                "updated_at_ts": now_ts,
                "expires_at_ts": now_ts + 3600,
                "pause_expires_at_ts": None,
                "scrobble_expires_at_ts": None,
            },
        )
        self.addCleanup(live_playback.clear_user_playback_state, self.user1.id)
        self.assertIsNone(self._get().json()["release_year"])

    def test_requires_authentication(self):
        """An unauthenticated request is rejected."""
        response = self._get(headers={})
        self.assertIn(
            response.status_code,
            (HTTP.UNAUTHORIZED, HTTP.FORBIDDEN),
        )
