"""The podcast show page must not re-download its feed on every view."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from app.models import PodcastShow


class PodcastDetailRssRefreshTests(TestCase):
    """Repeat views inside the refresh window render the stored episodes."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="podcastview")
        cls.user.podcast_enabled = True
        cls.user.save()
        cls.show = PodcastShow.objects.create(
            podcast_uuid="rss-gate-show",
            title="RSS Gate Show",
            rss_feed_url="https://feeds.example.com/gate.xml",
        )

    def setUp(self):
        cache.clear()
        self.client.force_login(self.user)

    @patch("app.fork_services_podcast.refresh_show_from_rss")
    def test_feed_is_read_once_across_repeat_views(self, mock_refresh):
        url = reverse(
            "media_details",
            args=["pocketcasts", "podcast", self.show.podcast_uuid, "rss-gate-show"],
        )

        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(url).status_code, 200)

        self.assertEqual(mock_refresh.call_count, 1)
