# FORK: podcast episode listen lifecycle (issue #1874). One PodcastPlay is one
# listen: it is created, updated and deleted on its own, whichever surface
# writes it.
import datetime
from http import HTTPStatus as HTTP  # noqa: N814

from django.urls import reverse

from api.helpers import get_media_status
from app import history_cache
from app.models import Podcast, PodcastPlay, Status

from .test_fork_podcast import PodcastApiTestCase

START = "2024-03-01T09:00:00"
END = "2024-03-01T10:00:00"


class PodcastPlayLifecycleTests(PodcastApiTestCase):
    """The API workflow from the issue: In Progress, update, Completed."""

    def _post(self, **payload):
        body = {"show_id": self.show.id, "episode_id": self.episode1.id, **payload}
        return self.call_api(
            "post",
            "api_podcast_episode_play",
            payload=body,
            headers=self.auth_headers,
        )

    def _detail(self, method, consumption_id, payload=None):
        return self.call_api(
            method,
            "api_podcast_episode_play_detail",
            args=(consumption_id,),
            payload=payload,
            headers=self.auth_headers,
        )

    def test_in_progress_play_has_no_end_date_and_a_stable_id(self):
        """An In Progress play keeps its start date and progress, with no end date."""
        response = self._post(
            status="In progress",
            start_date=START,
            progress=7,
            played_up_to_seconds=425,
        )

        self.assertEqual(response.status_code, HTTP.CREATED)
        body = response.json()
        self.assertEqual(body["status"], get_media_status(Status.IN_PROGRESS.value))
        self.assertIsNone(body["end_date"])
        self.assertEqual(body["progress"], 7)
        self.assertEqual(body["played_up_to_seconds"], 425)
        play = PodcastPlay.objects.get(id=body["consumption_id"])
        self.assertEqual(play.status, Status.IN_PROGRESS.value)
        self.assertEqual(play.podcast.status, Status.IN_PROGRESS.value)
        self.assertIsNone(play.podcast.end_date)

    def test_one_listening_session_is_one_consumption(self):
        """Progress updates then completion change the same play, never add one."""
        created = self._post(status="In progress", start_date=START, progress=5)
        consumption_id = created.json()["consumption_id"]

        progressed = self._detail("patch", consumption_id, {"progress": 18})
        self.assertEqual(progressed.status_code, HTTP.OK)
        self.assertEqual(progressed.json()["progress"], 18)

        completed = self._detail(
            "patch",
            consumption_id,
            {"status": "Completed", "end_date": END},
        )

        self.assertEqual(completed.status_code, HTTP.OK)
        body = completed.json()
        self.assertEqual(body["consumption_id"], consumption_id)
        self.assertEqual(body["status"], get_media_status(Status.COMPLETED.value))
        # Leaving In Progress for Completed defaults progress to the runtime.
        self.assertEqual(body["progress"], 30)
        self.assertEqual(PodcastPlay.objects.count(), 1)
        podcast = Podcast.objects.get(user=self.user1, episode=self.episode1)
        self.assertEqual(podcast.status, Status.COMPLETED.value)
        self.assertEqual(podcast.end_date, PodcastPlay.objects.get().end_date)
        self.assertEqual(podcast.completed_play_count, 1)

    def test_second_in_progress_request_returns_the_open_play(self):
        """A scrobbler that posts again does not start a second session."""
        first = self._post(status="In progress", start_date=START)
        second = self._post(status="In progress", start_date=START)

        self.assertEqual(second.status_code, HTTP.OK)
        self.assertTrue(second.json()["duplicate"])
        self.assertEqual(
            first.json()["consumption_id"],
            second.json()["consumption_id"],
        )
        self.assertEqual(PodcastPlay.objects.count(), 1)

    def test_completed_play_accepts_start_and_end_date_together(self):
        """Both timestamps can be supplied in the one request."""
        response = self._post(start_date=START, end_date=END)

        self.assertEqual(response.status_code, HTTP.CREATED)
        play = PodcastPlay.objects.get(id=response.json()["consumption_id"])
        self.assertEqual(play.start_date.hour, 9)
        self.assertEqual(play.end_date.hour, 10)
        self.assertEqual(play.progress, 30)

    def test_repeat_listen_is_a_separate_consumption(self):
        """A later, explicit play of the same episode is its own consumption."""
        first = self._post(end_date=END)
        second = self._post(end_date="2024-04-01T10:00:00")

        self.assertEqual(second.status_code, HTTP.CREATED)
        self.assertNotEqual(
            first.json()["consumption_id"],
            second.json()["consumption_id"],
        )
        self.assertEqual(PodcastPlay.objects.count(), 2)

    def test_delete_removes_only_that_play(self):
        """Deleting one listen leaves the other and the tracker."""
        first = self._post(end_date=END).json()["consumption_id"]
        second = self._post(end_date="2024-04-01T10:00:00").json()["consumption_id"]

        response = self._detail("delete", second)

        self.assertEqual(response.status_code, HTTP.NO_CONTENT)
        self.assertEqual(
            list(PodcastPlay.objects.values_list("id", flat=True)),
            [first],
        )
        podcast = Podcast.objects.get(user=self.user1, episode=self.episode1)
        self.assertEqual(podcast.end_date.month, 3)

    def test_invalid_requests_are_rejected(self):
        """A bad status, an end date on an open play or reversed dates are 400s."""
        self.assertEqual(self._post(status="Dropped").status_code, HTTP.BAD_REQUEST)
        self.assertEqual(
            self._post(status="In progress", end_date=END).status_code,
            HTTP.BAD_REQUEST,
        )
        self.assertEqual(
            self._post(start_date=END, end_date=START).status_code,
            HTTP.BAD_REQUEST,
        )
        self.assertEqual(PodcastPlay.objects.count(), 0)

    def test_other_users_play_is_not_found(self):
        """A consumption_id from another account is a 404."""
        play = PodcastPlay.objects.create(
            podcast=Podcast.objects.create(
                item=self._item(),
                user=self.user2,
                status=Status.COMPLETED.value,
            ),
            end_date=datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC),
        )

        self.assertEqual(self._detail("get", play.id).status_code, HTTP.NOT_FOUND)
        self.assertEqual(self._detail("delete", play.id).status_code, HTTP.NOT_FOUND)

    def test_generic_history_routes_address_the_same_play(self):
        """The media history routes list and edit plays by consumption_id."""
        created = self._post(end_date=END).json()
        item = Podcast.objects.get(id=created["tracker_id"]).item
        history = self.call_api(
            "get",
            "api_media_consumption_history",
            args=("podcast", item.source, item.media_id),
            headers=self.auth_headers,
        )

        self.assertEqual(history.status_code, HTTP.OK)
        self.assertEqual(
            [row["consumption_id"] for row in history.json()["results"]],
            [created["consumption_id"]],
        )

    def _item(self):
        from app.services import podcast_plays

        return podcast_plays.ensure_episode_item(self.show, self.episode2)[0]


class PodcastEditDoesNotDuplicateTests(PodcastApiTestCase):
    """Issue #1874: editing a completed entry used to show it twice."""

    def test_adding_a_start_date_keeps_one_play(self):
        """Track, then edit the entry to add a start date: still one listen."""
        from app.services import podcast_plays

        play, _ = podcast_plays.create_play(
            self.user1,
            self.show,
            episode=self.episode1,
            end_date=datetime.datetime(2024, 3, 1, 10, tzinfo=datetime.UTC),
        )
        podcast = play.podcast

        # The web edit form saves the tracker row.
        podcast.start_date = datetime.datetime(2024, 3, 1, 9, tzinfo=datetime.UTC)
        podcast.save()

        self.assertEqual(PodcastPlay.objects.count(), 1)
        play.refresh_from_db()
        self.assertEqual(play.start_date.hour, 9)
        self.assertEqual(podcast.completed_play_count, 1)

        days = history_cache.build_history_days(self.user1)
        podcast_entries = [
            entry
            for day in days
            for entry in day["entries"]
            if entry["media_type"] == "podcast"
        ]
        self.assertEqual(len(podcast_entries), 1)

    def test_reopening_a_completed_play_updates_the_same_play(self):
        """Completed -> In progress with no end date reopens that listen."""
        from app.services import podcast_plays

        play, _ = podcast_plays.create_play(
            self.user1,
            self.show,
            episode=self.episode1,
            end_date=datetime.datetime(2024, 3, 1, 10, tzinfo=datetime.UTC),
        )
        podcast = play.podcast
        podcast.status = Status.IN_PROGRESS.value
        podcast.end_date = None
        podcast.progress = 12
        podcast.save()

        play.refresh_from_db()
        self.assertEqual(PodcastPlay.objects.count(), 1)
        self.assertEqual(play.status, Status.IN_PROGRESS.value)
        self.assertIsNone(play.end_date)
        self.assertEqual(play.progress, 12)

    def test_deleting_the_history_entry_removes_only_that_play(self):
        """The History delete route takes the play id."""
        from app.services import podcast_plays

        first, _ = podcast_plays.create_play(
            self.user1,
            self.show,
            episode=self.episode1,
            end_date=datetime.datetime(2024, 3, 1, 10, tzinfo=datetime.UTC),
        )
        second, _ = podcast_plays.create_play(
            self.user1,
            self.show,
            episode=self.episode1,
            end_date=datetime.datetime(2024, 4, 1, 10, tzinfo=datetime.UTC),
        )
        self.client.force_login(self.user1)

        response = self.client.delete(
            reverse("delete_history_record", args=("podcast", second.id)),
        )

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(
            list(PodcastPlay.objects.values_list("id", flat=True)),
            [first.id],
        )
