# FORK: tests for the durable playback progress endpoint used by third-party
# clients doing bidirectional resume sync (issue #429).
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch

from django.utils import timezone

from app.models import (
    Item,
    MediaTypes,
    Movie,
    PlaybackProgress,
    Podcast,
    PodcastEpisode,
    PodcastShow,
    Sources,
    Status,
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
