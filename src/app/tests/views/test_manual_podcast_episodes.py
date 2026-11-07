from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import (
    MediaTypes,
    Movie,
    Podcast,
    PodcastEpisode,
    PodcastShow,
    PodcastShowTracker,
    Sources,
    Status,
)


class ManualPodcastEpisodeViewsTests(TestCase):
    """Manually managed episodes on custom podcast shows."""

    def setUp(self):
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)
        self.show = PodcastShow.objects.create(
            podcast_uuid="manual-show",
            source=Sources.MANUAL.value,
            title="Manual Show",
        )
        PodcastShowTracker.objects.create(
            user=self.user,
            show=self.show,
            status=Status.IN_PROGRESS.value,
        )

    def test_manage_page_renders_form_and_episodes(self):
        PodcastEpisode.objects.create(
            show=self.show,
            episode_uuid="manual-episode",
            title="Existing Episode",
        )

        response = self.client.get(
            reverse("podcast_episodes_manage", args=[self.show.id]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Existing Episode")
        self.assertContains(response, "Add episode")

    def test_manage_json_lists_episodes_for_the_manager(self):
        PodcastEpisode.objects.create(
            show=self.show,
            episode_uuid="manual-episode",
            title="Existing Episode",
            description="A description",
            duration=2700,
            episode_number=2,
            image="https://example.com/episode.jpg",
        )

        response = self.client.get(
            reverse("podcast_episodes_manage", args=[self.show.id]),
            {"format": "json"},
            headers={"Accept": "application/json"},
        )

        self.assertEqual(response.status_code, 200)
        episode = response.json()["episodes"][0]
        self.assertEqual(episode["title"], "Existing Episode")
        self.assertEqual(episode["description"], "A description")
        self.assertEqual(episode["duration"], "45:00")
        self.assertEqual(episode["episodeNumber"], 2)
        self.assertEqual(episode["imageUrl"], "https://example.com/episode.jpg")
        self.assertTrue(episode["editUrl"].endswith("/edit/"))
        self.assertTrue(episode["deleteUrl"].endswith("/delete/"))

    def test_add_episode_creates_manual_episode(self):
        response = self.client.post(
            reverse("podcast_episode_add", args=[self.show.id]),
            {
                "format": "json",
                "title": "New Episode",
                "description": "An audio drama",
                "episode_number": 3,
                "season_number": 1,
                "published": "2026-01-02T20:00",
                "duration": "45:30",
                "audio_url": "https://example.com/episode.mp3",
                "website_url": "https://example.com/episode",
                "image": "https://example.com/episode.jpg",
            },
            headers={"Accept": "application/json"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

        episode = PodcastEpisode.objects.get(show=self.show, title="New Episode")
        self.assertTrue(episode.episode_uuid.startswith("manual-"))
        self.assertEqual(episode.description, "An audio drama")
        self.assertEqual(episode.duration, 2730)
        self.assertEqual(episode.episode_number, 3)
        self.assertEqual(episode.season_number, 1)
        self.assertEqual(episode.audio_url, "https://example.com/episode.mp3")
        self.assertEqual(episode.website_url, "https://example.com/episode")
        self.assertEqual(episode.image, "https://example.com/episode.jpg")

    def test_add_episode_rejects_invalid_duration(self):
        response = self.client.post(
            reverse("podcast_episode_add", args=[self.show.id]),
            {"format": "json", "title": "Bad Episode", "duration": "not a time"},
            headers={"Accept": "application/json"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("duration", response.json()["errors"])
        self.assertFalse(PodcastEpisode.objects.filter(title="Bad Episode").exists())

    def test_edit_episode_updates_fields(self):
        episode = PodcastEpisode.objects.create(
            show=self.show,
            episode_uuid="manual-episode",
            title="Old Title",
            duration=60,
        )

        response = self.client.post(
            reverse("podcast_episode_edit", args=[episode.id]),
            {
                "format": "json",
                "title": "New Title",
                "duration": "1:30",
                "episode_number": 4,
            },
            headers={"Accept": "application/json"},
        )

        self.assertEqual(response.status_code, 200)
        episode.refresh_from_db()
        self.assertEqual(episode.title, "New Title")
        self.assertEqual(episode.duration, 90)
        self.assertEqual(episode.episode_number, 4)

    def test_edit_form_shows_duration_in_seconds_text(self):
        episode = PodcastEpisode.objects.create(
            show=self.show,
            episode_uuid="manual-episode",
            title="Episode",
            duration=2730,
        )

        response = self.client.get(
            reverse("podcast_episodes_manage", args=[self.show.id]),
            {"episode": episode.id},
        )

        self.assertContains(response, 'value="45:30"')

    def test_delete_episode_removes_it(self):
        episode = PodcastEpisode.objects.create(
            show=self.show,
            episode_uuid="manual-episode",
            title="Delete Me",
        )

        response = self.client.post(
            reverse("podcast_episode_delete", args=[episode.id]),
            {"format": "json"},
            headers={"Accept": "application/json"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertFalse(PodcastEpisode.objects.filter(id=episode.id).exists())

    def test_provider_show_is_not_manageable(self):
        show = PodcastShow.objects.create(
            podcast_uuid="provider-show",
            source=Sources.POCKETCASTS.value,
            title="Provider Show",
        )
        PodcastShowTracker.objects.create(user=self.user, show=show)

        response = self.client.get(
            reverse("podcast_episodes_manage", args=[show.id]),
        )

        self.assertEqual(response.status_code, 404)

    def test_show_without_viewer_tracker_is_not_manageable(self):
        show = PodcastShow.objects.create(
            podcast_uuid="someone-elses-show",
            source=Sources.MANUAL.value,
            title="Someone Else's Show",
        )

        response = self.client.get(
            reverse("podcast_episodes_manage", args=[show.id]),
        )

        self.assertEqual(response.status_code, 404)

    def test_media_details_offers_manager_for_manual_show(self):
        response = self.client.get(
            reverse(
                "media_details",
                kwargs={
                    "source": Sources.MANUAL.value,
                    "media_type": MediaTypes.PODCAST.value,
                    "media_id": self.show.podcast_uuid,
                    "title": "manual-show",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-podcast-episode-manager-root")
        self.assertContains(response, "Manage episodes")
        self.assertContains(response, "No episodes yet.")

    def test_media_details_renders_manual_episode_metadata(self):
        PodcastEpisode.objects.create(
            show=self.show,
            episode_uuid="manual-episode",
            title="Episode With Artwork",
            description="An episode description",
            image="https://example.com/episode-art.jpg",
        )

        response = self.client.get(
            reverse(
                "media_details",
                kwargs={
                    "source": Sources.MANUAL.value,
                    "media_type": MediaTypes.PODCAST.value,
                    "media_id": self.show.podcast_uuid,
                    "title": "manual-show",
                },
            ),
        )

        self.assertContains(response, "An episode description")
        self.assertContains(response, "https://example.com/episode-art.jpg")

    def test_manual_episode_accepts_a_normal_play(self):
        """A manually added episode is the same trackable unit as an imported one."""
        episode = PodcastEpisode.objects.create(
            show=self.show,
            episode_uuid="manual-episode",
            title="Manual Episode",
        )

        response = self.client.post(
            reverse("podcast_save"),
            {"show_id": self.show.id, "episode_id": episode.id},
        )

        self.assertEqual(response.status_code, 302)
        play = Podcast.objects.get(user=self.user, show=self.show)
        self.assertEqual(play.episode, episode)
        self.assertEqual(play.item.media_id, episode.episode_uuid)

    def test_podcast_episodes_api_includes_new_metadata(self):
        PodcastEpisode.objects.create(
            show=self.show,
            episode_uuid="manual-episode",
            title="Episode With Artwork",
            description="An episode description",
            image="https://example.com/episode-art.jpg",
        )

        response = self.client.get(
            reverse("podcast_episodes_api", args=[self.show.id]),
        )

        episode = response.json()["episodes"][0]
        self.assertEqual(episode["description"], "An episode description")
        self.assertEqual(episode["image"], "https://example.com/episode-art.jpg")


class ManualPodcastCreateEntryTests(TestCase):
    """The custom podcast form can store an RSS feed for episode import."""

    def setUp(self):
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    @patch("app.tasks_podcast.refresh_podcast_show_from_rss_task.delay")
    def test_create_entry_stores_rss_feed_and_queues_import(self, delay):
        response = self.client.post(
            reverse("create_entry"),
            {
                "title": "Feed Podcast",
                "media_type": MediaTypes.PODCAST.value,
                "status": Status.IN_PROGRESS.value,
                "rss_feed_url": "https://example.com/feed.xml",
            },
        )

        self.assertRedirects(response, reverse("create_entry"))
        show = PodcastShow.objects.get(title="Feed Podcast")
        self.assertEqual(show.rss_feed_url, "https://example.com/feed.xml")
        delay.assert_called_once_with(show.id)

    def test_rss_feed_is_ignored_for_other_media_types(self):
        self.client.post(
            reverse("create_entry"),
            {
                "title": "Feed Movie",
                "media_type": MediaTypes.MOVIE.value,
                "rss_feed_url": "https://example.com/feed.xml",
            },
        )

        self.assertFalse(PodcastShow.objects.filter(title="Feed Movie").exists())
        self.assertTrue(Movie.objects.filter(item__title="Feed Movie").exists())
