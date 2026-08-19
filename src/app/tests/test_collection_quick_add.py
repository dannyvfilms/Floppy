from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import CollectionEntry, Item, MediaTypes, Sources


class CollectionQuickAddTest(TestCase):
    """Test the one-click quick-collect endpoint."""

    def setUp(self):
        """Create a user and log in."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)
        self.episode_url = reverse(
            "collection_quick_add",
            kwargs={
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.EPISODE.value,
                "media_id": "1668",
            },
        )

    def _post_episode(self, **extra):
        return self.client.post(
            self.episode_url,
            {"season_number": "1", "episode_number": "1"},
            HTTP_HX_REQUEST="true",
            **extra,
        )

    @patch("app.collection_views.services.get_media_metadata")
    def test_quick_add_creates_item_and_entry(self, mock_metadata):
        """Quick add creates the episode Item and a bare collection entry."""
        mock_metadata.return_value = {
            "title": "Friends",
            "image": "https://image.url",
        }

        response = self._post_episode()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertTrue(data["created"])

        item = Item.objects.get(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
        )
        self.assertEqual(item.season_number, 1)
        self.assertEqual(item.episode_number, 1)

        entry = CollectionEntry.objects.get(user=self.user, item=item)
        self.assertEqual(entry.media_type, "")
        self.assertEqual(entry.resolution, "")

    @patch("app.collection_views.services.get_media_metadata")
    def test_quick_add_is_idempotent(self, mock_metadata):
        """A second quick add for the same episode does not duplicate entries."""
        mock_metadata.return_value = {
            "title": "Friends",
            "image": "https://image.url",
        }

        self._post_episode()
        response = self._post_episode()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["created"])
        self.assertEqual(
            CollectionEntry.objects.filter(user=self.user).count(),
            1,
        )

    def test_quick_add_requires_episode_numbers(self):
        """Episode quick add without season/episode numbers is rejected."""
        response = self.client.post(self.episode_url, {}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(CollectionEntry.objects.filter(user=self.user).exists())

    def test_quick_add_requires_login(self):
        """Anonymous htmx requests get HX-Redirect to login, not a 302.

        htmx would follow a 302 and swap the whole login page into the page
        (#386), so the redirect is handed to the client instead.
        """
        self.client.logout()
        response = self._post_episode()
        self.assertEqual(response.status_code, 204)
        self.assertIn("/accounts/login/", response.headers["HX-Redirect"])
        self.assertFalse(CollectionEntry.objects.exists())

    @patch("app.providers.services.get_media_metadata")
    @patch("app.providers.tmdb.process_episodes")
    def test_season_view_routes_episode_collection_through_tracker(
        self,
        mock_process_episodes,
        mock_get_metadata,
    ):
        """Episode rows expose collection through the shared tracker modal."""
        mock_get_metadata.side_effect = lambda *_args, **_kwargs: {
            "title": "Test TV Show",
            "media_id": "1668",
            "source": Sources.TMDB.value,
            "media_type": MediaTypes.TV.value,
            "image": "http://example.com/image.jpg",
            "season/1": {
                "title": "Season 1",
                "season_title": "Season 1",
                "media_id": "1668",
                "media_type": MediaTypes.SEASON.value,
                "source": Sources.TMDB.value,
                "image": "http://example.com/season.jpg",
                "episodes": [],
            },
        }
        mock_process_episodes.return_value = [
            {
                "media_id": "1668",
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.EPISODE.value,
                "season_number": 1,
                "episode_number": 1,
                "title": "Episode 1",
                "air_date": "2023-01-01",
                "actions_enabled": False,
            },
        ]

        response = self.client.get(
            reverse(
                "season_details",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_id": "1668",
                    "title": "test-tv-show",
                    "season_number": 1,
                },
            ),
            {"fragment": "secondary"},
        )

        self.assertEqual(response.status_code, 200)
        track_url = reverse(
            "track_modal",
            kwargs={
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.EPISODE.value,
                "media_id": "1668",
                "season_number": 1,
            },
        )
        self.assertContains(response, track_url)
        self.assertContains(response, '"is_create": "1"', html=False)
        self.assertNotContains(response, self.episode_url)
