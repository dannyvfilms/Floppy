from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.shortcuts import resolve_url
from django.test import TestCase
from django.urls import reverse

from app.models import MediaTypes, PodcastEpisode, PodcastShow, Sources


class PodcastShowDetailWebsiteLinkTests(TestCase):
    """website_url renders as a link on the podcast show detail page."""

    def setUp(self):
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    def test_anonymous_show_requests_require_login(self):
        show = PodcastShow.objects.create(
            podcast_uuid="private-tracker-show",
            title="Private Tracker Show",
        )
        self.client.logout()

        for show_id in (show.id, show.id + 1):
            with self.subTest(show_id=show_id):
                url = reverse("podcast_show_detail", args=[show_id])
                response = self.client.get(url)
                self.assertRedirects(
                    response,
                    f"{resolve_url(settings.LOGIN_URL)}?next={url}",
                    fetch_redirect_response=False,
                )

    def test_renders_show_and_episode_website_links(self):
        show = PodcastShow.objects.create(
            podcast_uuid="show-website-link",
            title="Website Link Podcast",
            website_url="https://example.com/show",
        )
        PodcastEpisode.objects.create(
            show=show,
            episode_uuid="episode-website-link",
            title="Episode With A Link",
            website_url="https://example.com/show/episode-one",
        )

        response = self.client.get(reverse("podcast_show_detail", args=[show.id]))

        self.assertContains(response, "https://example.com/show")
        self.assertContains(response, "https://example.com/show/episode-one")

    def test_omits_links_when_website_url_is_blank(self):
        show = PodcastShow.objects.create(
            podcast_uuid="show-no-website-link",
            title="No Link Podcast",
        )
        PodcastEpisode.objects.create(
            show=show,
            episode_uuid="episode-no-website-link",
            title="Episode Without A Link",
        )

        response = self.client.get(reverse("podcast_show_detail", args=[show.id]))

        self.assertNotContains(response, "Visit show website")
        self.assertNotContains(response, "Episode website")


class CompletedPlaysByPodcastIdTests(TestCase):
    """The shared history read can be bounded per podcast in SQL."""

    def test_limit_keeps_only_the_newest_plays_of_each_podcast(self):
        from datetime import UTC, datetime, timedelta

        from django.contrib.auth import get_user_model

        from app.models import Item, MediaTypes, Podcast, Sources, Status
        from app.podcast_views import completed_plays_by_podcast_id

        user = get_user_model().objects.create_user(username="plays", password="x")
        item = Item.objects.create(
            media_id="plays-episode",
            source=Sources.POCKETCASTS.value,
            media_type=MediaTypes.PODCAST.value,
            title="Episode",
            image="https://example.com/i.jpg",
        )
        podcast = Podcast.objects.create(
            item=item,
            user=user,
            status=Status.COMPLETED.value,
            progress=30,
            end_date=datetime(2024, 1, 1, tzinfo=UTC),
        )
        for day in range(2, 26):
            podcast.end_date = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=day)
            podcast.save()

        everything = completed_plays_by_podcast_id({podcast.id})[podcast.id]
        newest = completed_plays_by_podcast_id({podcast.id}, limit=10)[podcast.id]

        self.assertGreater(len(everything), 10)
        self.assertEqual(len(newest), 10)
        self.assertEqual(
            [record.end_date for record in newest],
            [record.end_date for record in everything[:10]],
        )


class PodcastShowDetailRssRefreshTests(TestCase):
    """The feed refresh is queued, never run inside the render."""

    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.credentials = {"username": "rss", "password": "12345"}
        get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)
        self.show = PodcastShow.objects.create(
            podcast_uuid="rss-queue-show",
            title="Queued Feed Show",
            rss_feed_url="https://example.com/feed.xml",
        )
        self.url = reverse(
            "media_details",
            kwargs={
                "source": Sources.POCKETCASTS.value,
                "media_type": MediaTypes.PODCAST.value,
                "media_id": self.show.podcast_uuid,
                "title": "queued-feed-show",
            },
        )

    def test_refresh_is_queued_once_per_window_without_fetching_inline(self):
        with (
            patch(
                "app.tasks_podcast.refresh_podcast_show_from_rss_task.delay"
            ) as delay,
            patch("integrations.podcast_rss.fetch_feed_from_rss") as fetch,
        ):
            first = self.client.get(self.url)
            second = self.client.get(self.url)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        delay.assert_called_once_with(self.show.id)
        fetch.assert_not_called()

    def test_queue_failure_still_renders(self):
        with patch(
            "app.tasks_podcast.refresh_podcast_show_from_rss_task.delay",
            side_effect=OSError("broker down"),
        ):
            response = self.client.get(self.url)

        self.assertContains(response, "Queued Feed Show")

    def test_task_refreshes_the_show_from_its_feed(self):
        from app.tasks_podcast import refresh_podcast_show_from_rss_task

        with patch(
            "app.fork_services_podcast.refresh_show_from_rss"
        ) as refresh:
            refresh_podcast_show_from_rss_task(self.show.id)
            refresh_podcast_show_from_rss_task(self.show.id + 999)

        refresh.assert_called_once()
