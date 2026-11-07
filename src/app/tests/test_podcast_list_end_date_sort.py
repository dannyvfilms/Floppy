"""The podcast list must render when sorted by end date (#1828)."""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from app.models import PodcastShow, PodcastShowTracker


class PodcastListEndDateSortTests(TestCase):
    """PodcastShowAdapter has no progressed_at; the grid must not 500."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username="pod", password="x")
        self.client.force_login(self.user)
        show = PodcastShow.objects.create(
            podcast_uuid="uuid-1828", title="Show", image="/c.jpg"
        )
        PodcastShowTracker.objects.create(user=self.user, show=show)

    def test_list_sorted_by_end_date_renders(self):
        response = self.client.get(
            reverse("medialist", args=["podcast"]), {"sort": "end_date"}
        )
        self.assertEqual(response.status_code, 200)
