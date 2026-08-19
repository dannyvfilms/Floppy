# FORK: tests for the first-class podcast API endpoints.
import datetime
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch

from app.models import (
    Podcast,
    PodcastEpisode,
    PodcastShow,
    PodcastShowTracker,
)

from .base import FloppyApiTestCase


class PodcastApiTestCase(FloppyApiTestCase):
    """Shared podcast catalog fixtures."""

    def setUp(self):
        """Create a show with two catalog episodes."""
        super().setUp()
        self.show = PodcastShow.objects.create(
            podcast_uuid="show-uuid-1",
            title="Test Show",
            image="https://example.com/show.jpg",
        )
        self.episode1 = PodcastEpisode.objects.create(
            show=self.show,
            episode_uuid="ep-uuid-1",
            title="Episode One",
            published=datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC),
            duration=1800,
        )
        self.episode2 = PodcastEpisode.objects.create(
            show=self.show,
            episode_uuid="ep-uuid-2",
            title="Episode Two",
            published=datetime.datetime(2024, 2, 1, tzinfo=datetime.UTC),
            duration=2400,
        )


class ShowTrackerTests(PodcastApiTestCase):
    """Show tracker CRUD."""

    def test_track_list_patch_delete(self):
        """Full tracker lifecycle."""
        created = self.call_api(
            "post",
            "api_podcast_shows",
            payload={"show_id": self.show.id, "score": "8.0"},
            headers=self.auth_headers,
        )
        self.assertEqual(created.status_code, HTTP.CREATED)
        self.assertEqual(created.json()["tracker"]["score"], "8.0")

        listed = self.call_api("get", "api_podcast_shows", headers=self.auth_headers)
        self.assertEqual(listed.json()["pagination"]["total"], 1)

        patched = self.call_api(
            "patch",
            "api_podcast_show_detail",
            args=(self.show.id,),
            payload={"notes": "great show"},
            headers=self.auth_headers,
        )
        self.assertEqual(patched.status_code, HTTP.OK)
        tracker = PodcastShowTracker.objects.get(user=self.user1, show=self.show)
        self.assertEqual(tracker.notes, "great show")
        self.assertEqual(str(tracker.score), "8.0")

        deleted = self.call_api(
            "delete",
            "api_podcast_show_detail",
            args=(self.show.id,),
            headers=self.auth_headers,
        )
        self.assertEqual(deleted.status_code, HTTP.NO_CONTENT)
        self.assertFalse(
            PodcastShowTracker.objects.filter(
                user=self.user1,
                show=self.show,
            ).exists(),
        )

    def test_unknown_show_not_found(self):
        """Unknown show ids 404."""
        response = self.call_api(
            "get",
            "api_podcast_show_detail",
            args=(999999,),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)


class ShowEpisodesTests(PodcastApiTestCase):
    """GET podcasts/shows/{id}/episodes delegates to the web JSON view."""

    def test_episodes_listing(self):
        """Episodes are returned with pagination, newest first."""
        response = self.call_api(
            "get",
            "api_podcast_show_episodes",
            args=(self.show.id,),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        payload = response.json()
        self.assertEqual(payload["pagination"]["total_count"], 2)
        self.assertEqual(payload["episodes"][0]["title"], "Episode Two")


class EpisodePlayTests(PodcastApiTestCase):
    """POST podcasts/episodes/plays records plays."""

    def test_play_creates_podcast_row(self):
        """The first play creates a Completed Podcast row."""
        response = self.call_api(
            "post",
            "api_podcast_episode_play",
            payload={
                "show_id": self.show.id,
                "episode_id": self.episode1.id,
                "end_date": "2024-03-01T10:00:00",
            },
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.CREATED)
        podcast = Podcast.objects.get(user=self.user1, episode=self.episode1)
        self.assertEqual(podcast.item.media_id, "ep-uuid-1")
        self.assertEqual(podcast.progress, 30)

    def test_duplicate_play_within_window(self):
        """A second play within five minutes reports duplicate."""
        for _ in range(2):
            response = self.call_api(
                "post",
                "api_podcast_episode_play",
                payload={
                    "show_id": self.show.id,
                    "episode_uuid": "ep-uuid-2",
                    "end_date": "2024-03-01T10:00:00",
                },
                headers=self.auth_headers,
            )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertTrue(response.json()["duplicate"])

    def test_missing_identifiers_rejected(self):
        """A play without episode identifiers returns 400."""
        response = self.call_api(
            "post",
            "api_podcast_episode_play",
            payload={"show_id": self.show.id},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)


class MarkAllPlayedTests(PodcastApiTestCase):
    """POST podcasts/shows/{id}/mark-all-played."""

    @patch("app.fork_services_podcast.refresh_show_episodes_from_rss")
    def test_marks_unplayed_episodes(self, _mock_rss):
        """All catalog episodes without plays are marked completed."""
        response = self.call_api(
            "post",
            "api_podcast_mark_all_played",
            args=(self.show.id,),
            payload={},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["marked_played"], 2)
        self.assertEqual(
            Podcast.objects.filter(user=self.user1, show=self.show).count(),
            2,
        )

        again = self.call_api(
            "post",
            "api_podcast_mark_all_played",
            args=(self.show.id,),
            payload={},
            headers=self.auth_headers,
        )
        self.assertEqual(again.json()["marked_played"], 0)
