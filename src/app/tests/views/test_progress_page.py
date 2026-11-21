from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string

from app.models import Status
from app.tests.views import test_time_left_sort as fixtures


class ProgressPageApiTests(TestCase):
    """The Progress page read: shows with something left, ordered and totalled."""

    _create_tv = fixtures.TVTimeLeftSortTests._create_tv

    def setUp(self):
        """Sign in and track a long, a short and a finished show."""
        self.user = get_user_model().objects.create_user(
            username="progress",
            password=get_random_string(16),
        )
        self.client.force_login(self.user)
        self.now = timezone.now()
        season = {"season_number": 1, "status": Status.IN_PROGRESS.value}
        self._create_tv(
            "Long Show",
            "tv-long",
            [{**season, "released_episodes": 10, "watched_episodes": 2}],
        )
        self._create_tv(
            "Short Show",
            "tv-short",
            [{**season, "released_episodes": 4, "watched_episodes": 3}],
        )
        self._create_tv(
            "Done Show",
            "tv-done",
            [{**season, "released_episodes": 3, "watched_episodes": 3}],
        )

    def _get(self, **params):
        response = self.client.get(reverse("api_progress_page"), params)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_default_hides_finished_and_sorts_by_least_time(self):
        """Caught-up shows are hidden, and the shortest backlog comes first."""
        data = self._get()
        self.assertEqual(
            [row["title"] for row in data["results"]], ["Short Show", "Long Show"]
        )
        short = data["results"][0]
        self.assertEqual(
            (short["watched"], short["total"], short["left"], short["percent"]),
            (3, 4, 1, 75),
        )
        self.assertEqual(data["summary"]["shows"], 2)
        self.assertEqual(data["summary"]["left"], 9)
        self.assertGreater(data["summary"]["minutes_left"], 0)

    def test_show_finished_and_most_sort(self):
        """Finished shows appear on request and a most-first sort reverses the order."""
        data = self._get(statuses="in_progress,finished", sort="most_episodes")
        self.assertEqual(
            [row["title"] for row in data["results"]],
            ["Long Show", "Short Show", "Done Show"],
        )

    def test_finished_group_alone(self):
        """The Finished group shows only caught-up shows."""
        data = self._get(statuses="finished")
        self.assertEqual([row["title"] for row in data["results"]], ["Done Show"])

    def test_paging(self):
        """A page reports whether more shows follow."""
        first = self._get(limit=1)
        self.assertEqual(len(first["results"]), 1)
        self.assertTrue(first["pagination"]["has_more"])
        last = self._get(limit=1, offset=1)
        self.assertFalse(last["pagination"]["has_more"])

    def test_requires_login(self):
        """A signed-out request is refused."""
        self.client.logout()
        self.assertIn(
            self.client.get(reverse("api_progress_page")).status_code, (401, 403)
        )
