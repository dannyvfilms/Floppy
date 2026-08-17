# FORK: tests for the first-class podcast API endpoints.
import datetime
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch

from django.contrib.messages import get_messages
from django.urls import reverse

from app import fork_services_podcast
from app.models import (
    Podcast,
    PodcastEpisode,
    PodcastShow,
    PodcastShowTracker,
    Status,
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

    def test_blank_date_uses_current_server_time(self):
        """A blank date records a completed play at the current server time."""
        completed_at = datetime.datetime(2025, 1, 15, 12, tzinfo=datetime.UTC)

        with patch(
            "app.fork_services_podcast.timezone.now",
            return_value=completed_at,
        ):
            response = self.call_api(
                "post",
                "api_podcast_episode_play",
                payload={
                    "show_id": self.show.id,
                    "episode_id": self.episode1.id,
                    "end_date": "",
                },
                headers=self.auth_headers,
            )

        self.assertEqual(response.status_code, HTTP.CREATED)
        podcast = Podcast.objects.get(user=self.user1, episode=self.episode1)
        self.assertEqual(podcast.status, Status.COMPLETED.value)
        self.assertEqual(podcast.end_date, completed_at)

    def test_blank_and_omitted_dates_share_duplicate_protection(self):
        """Repeated date-free plays create one completed activity entry."""
        completed_at = datetime.datetime(2025, 1, 15, 12, tzinfo=datetime.UTC)

        with patch(
            "app.fork_services_podcast.timezone.now",
            return_value=completed_at,
        ):
            first = self.call_api(
                "post",
                "api_podcast_episode_play",
                payload={
                    "show_id": self.show.id,
                    "episode_uuid": self.episode2.episode_uuid,
                    "end_date": "",
                },
                headers=self.auth_headers,
            )
            second = self.call_api(
                "post",
                "api_podcast_episode_play",
                payload={
                    "show_id": self.show.id,
                    "episode_uuid": self.episode2.episode_uuid,
                },
                headers=self.auth_headers,
            )

        self.assertEqual(first.status_code, HTTP.CREATED)
        self.assertEqual(second.status_code, HTTP.OK)
        self.assertTrue(second.json()["duplicate"])
        self.assertEqual(
            Podcast.objects.filter(user=self.user1, episode=self.episode2).count(),
            1,
        )

    def test_legacy_null_date_play_can_be_deleted(self):
        """A legacy completed row with no date does not crash on deletion."""
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
        Podcast.objects.filter(pk=podcast.pk).update(end_date=None)

        self.client.force_login(self.user1)
        deleted = self.client.post(
            reverse("media_delete"),
            {"instance_id": podcast.pk, "media_type": "podcast"},
            HTTP_REFERER="/",
        )

        self.assertEqual(deleted.status_code, HTTP.FOUND)
        self.assertFalse(Podcast.objects.filter(pk=podcast.pk).exists())

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


class PodcastPlayDeduplicationTests(PodcastApiTestCase):
    """Duplicate suppression across imports, replays, and the window edge."""

    def _record(self, end_date=None):
        return fork_services_podcast.record_podcast_play(
            self.user1,
            self.show,
            episode=self.episode1,
            episode_uuid=self.episode1.episode_uuid,
            end_date=end_date,
        )

    def test_reimported_play_stays_a_duplicate_after_a_dateless_play(self):
        """A play recorded "now" must not unmask an already-imported old play.

        Duplicate detection once compared against the newest play only. One
        dateless play then sat at the top of the history and every re-imported
        old play looked new, so a repeated import multiplied the play count.
        """
        old = datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)
        now = datetime.datetime(2025, 6, 1, 12, tzinfo=datetime.UTC)

        self._record(end_date=old)
        with patch("app.fork_services_podcast.timezone.now", return_value=now):
            self._record()
        _, duplicate = self._record(end_date=old)

        podcast = Podcast.objects.get(user=self.user1, episode=self.episode1)
        self.assertTrue(duplicate)
        self.assertEqual(podcast.completed_play_count, 2)

    def test_play_just_outside_the_window_is_a_new_play(self):
        """A play five minutes and one second later counts separately."""
        first = datetime.datetime(2025, 6, 1, 12, 0, 0, tzinfo=datetime.UTC)
        outside = first + datetime.timedelta(seconds=301)

        self._record(end_date=first)
        _, duplicate = self._record(end_date=outside)

        podcast = Podcast.objects.get(user=self.user1, episode=self.episode1)
        self.assertFalse(duplicate)
        self.assertEqual(podcast.completed_play_count, 2)

    def test_play_just_inside_the_window_is_a_duplicate(self):
        """A play four minutes and fifty-nine seconds later is suppressed."""
        first = datetime.datetime(2025, 6, 1, 12, 0, 0, tzinfo=datetime.UTC)
        inside = first + datetime.timedelta(seconds=299)

        self._record(end_date=first)
        _, duplicate = self._record(end_date=inside)

        podcast = Podcast.objects.get(user=self.user1, episode=self.episode1)
        self.assertTrue(duplicate)
        self.assertEqual(podcast.completed_play_count, 1)


class PodcastWebPlayDateTests(PodcastApiTestCase):
    """The web form and the REST API must read a date the same way."""

    def _post(self, end_date):
        self.client.force_login(self.user1)
        return self.client.post(
            reverse("podcast_save"),
            {
                "show_id": self.show.id,
                "episode_id": self.episode1.id,
                "episode_uuid": self.episode1.episode_uuid,
                "end_date": end_date,
            },
            HTTP_REFERER="/",
        )

    def test_blank_date_records_the_current_server_time(self):
        """A blank date on the web form behaves like a blank date on the API."""
        completed_at = datetime.datetime(2025, 1, 15, 12, tzinfo=datetime.UTC)

        with patch(
            "app.fork_services_podcast.timezone.now",
            return_value=completed_at,
        ):
            response = self._post("")

        podcast = Podcast.objects.get(user=self.user1, episode=self.episode1)
        self.assertEqual(response.status_code, HTTP.FOUND)
        self.assertEqual(podcast.status, Status.COMPLETED.value)
        self.assertEqual(podcast.end_date, completed_at)

    def test_unreadable_date_records_nothing_and_reports_the_problem(self):
        """An unreadable date must not become "now" behind the user's back.

        The API answers 400 for the same input. The web form used to discard
        the value and record the current time under a success message, so the
        user kept a timestamp they never chose.
        """
        response = self._post("not-a-date")

        self.assertEqual(response.status_code, HTTP.FOUND)
        self.assertFalse(
            Podcast.objects.filter(user=self.user1, episode=self.episode1).exists(),
        )
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("YYYY-MM-DD" in message for message in messages))

    def test_unreadable_date_keeps_the_modal_open_for_htmx(self):
        """The modal must survive the error so the typed date can be fixed."""
        self.client.force_login(self.user1)
        response = self.client.post(
            reverse("podcast_save"),
            {
                "show_id": self.show.id,
                "episode_id": self.episode1.id,
                "episode_uuid": self.episode1.episode_uuid,
                "end_date": "not-a-date",
            },
            HTTP_REFERER="/",
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response["HX-Reswap"], "none")
        self.assertNotIn("closeModal", response["HX-Trigger"])
        self.assertIn("showToast", response["HX-Trigger"])
        self.assertFalse(
            Podcast.objects.filter(user=self.user1, episode=self.episode1).exists(),
        )

    def test_explicit_date_is_kept_exactly(self):
        """An explicit date must survive unchanged."""
        response = self._post("2024-03-01T10:00:00")

        podcast = Podcast.objects.get(user=self.user1, episode=self.episode1)
        self.assertEqual(response.status_code, HTTP.FOUND)
        self.assertEqual(
            podcast.end_date,
            datetime.datetime(2024, 3, 1, 10, tzinfo=datetime.UTC),
        )
