"""Rating a podcast show must persist on its tracker (#1830)."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from app.models import Podcast, PodcastShow, PodcastShowTracker


class PodcastShowRatingTests(TestCase):
    """The detail page and media list rate the show tracker."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username="pod", password="x")
        self.client.force_login(self.user)
        self.show = PodcastShow.objects.create(
            podcast_uuid="uuid-1830", title="Show", image="/c.jpg"
        )
        self.tracker = PodcastShowTracker.objects.create(user=self.user, show=self.show)

    def test_list_rating_url_targets_the_show(self):
        listing = self.client.get(reverse("medialist", args=["podcast"]))
        self.assertContains(
            listing, reverse("update_podcast_show_score", args=[self.tracker.id])
        )

    def test_rating_response_chip_posts_to_the_show(self):
        response = self.client.post(
            reverse("update_podcast_show_score", args=[self.tracker.id]),
            {"score": "8"},
        )
        self.assertContains(
            response, reverse("update_podcast_show_score", args=[self.tracker.id])
        )

    def test_score_saved_on_tracker(self):
        response = self.client.post(
            reverse("update_podcast_show_score", args=[self.tracker.id]),
            {"score": "8"},
        )
        self.assertEqual(response.status_code, 200)
        self.tracker.refresh_from_db()
        self.assertEqual(self.tracker.score, Decimal(8))
        self.assertFalse(Podcast.objects.exists())
