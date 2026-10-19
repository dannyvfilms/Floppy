from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase, override_settings
from django.urls import reverse

from app.models import MediaTypes
from app.templatetags.app_tags import get_sidebar_media_types
from users.models import AnimeLibraryModeChoices, MetadataSourceDefaultChoices


class SidebarViewTests(TestCase):
    """Tests for the sidebar view."""

    def setUp(self):
        """Create user for the tests."""
        self.credentials = {"username": "testuser", "password": "testpass123"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    def test_sidebar_no_longer_contains_feed_settings(self):
        response = self.client.get(reverse("sidebar"))
        self.assertNotContains(response, 'name="show_up_next"')
        self.assertNotContains(response, 'name="episode_feed_columns"')
        self.assertNotContains(response, 'href="/up-next"')

    def test_preferences_get(self):
        """Test GET request to preferences view."""
        response = self.client.get(reverse("preferences"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "users/preferences.html")
        self.assertNotContains(response, "Show Progress Bar")

        self.assertIn("media_types", response.context)
        self.assertIn(MediaTypes.TV.value, response.context["media_types"])
        self.assertIn(MediaTypes.MOVIE.value, response.context["media_types"])
        self.assertNotIn(MediaTypes.EPISODE.value, response.context["media_types"])

    def test_sidebar_get_excludes_comic_issues(self):
        """Sidebar settings should not expose derived comic issue navigation."""
        response = self.client.get(reverse("sidebar"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "users/sidebar.html")
        self.assertIn("media_types", response.context)
        self.assertNotIn(MediaTypes.COMIC_ISSUE.value, response.context["media_types"])
        self.assertNotContains(response, "Comic Issues")

    def test_sidebar_post_updates_without_comic_issue_field(self):
        """Sidebar POST should only save persisted user sidebar fields."""
        self.user.tv_enabled = True
        self.user.movie_enabled = True
        self.user.save(update_fields=["tv_enabled", "movie_enabled"])

        response = self.client.post(
            reverse("sidebar"),
            {
                "media_types_checkboxes": [MediaTypes.TV.value],
            },
        )

        self.assertRedirects(response, reverse("sidebar"))

        self.user.refresh_from_db()
        self.assertTrue(self.user.tv_enabled)
        self.assertFalse(self.user.movie_enabled)

    def test_sidebar_post_updates_media_type_order(self):
        """Sidebar media type order should persist independently of enabled types."""
        self.user.tv_enabled = True
        self.user.movie_enabled = True
        self.user.anime_enabled = True
        self.user.save(update_fields=["tv_enabled", "movie_enabled", "anime_enabled"])

        response = self.client.post(
            reverse("sidebar"),
            {
                "media_types_checkboxes": [
                    MediaTypes.TV.value,
                    MediaTypes.MOVIE.value,
                    MediaTypes.ANIME.value,
                ],
                "sidebar_media_type_order": ",".join(
                    [
                        MediaTypes.ANIME.value,
                        MediaTypes.TV.value,
                        MediaTypes.MOVIE.value,
                    ],
                ),
            },
        )

        self.assertRedirects(response, reverse("sidebar"))
        self.user.refresh_from_db()
        self.assertEqual(
            self.user.get_sidebar_media_types()[:3],
            [MediaTypes.ANIME.value, MediaTypes.TV.value, MediaTypes.MOVIE.value],
        )
        self.assertEqual(
            [item["media_type"] for item in get_sidebar_media_types(self.user)][:3],
            [MediaTypes.ANIME.value, MediaTypes.TV.value, MediaTypes.MOVIE.value],
        )

    def test_sidebar_post_update_preferences(self):
        """Test POST request to update preferences."""
        self.user.tv_enabled = True
        self.user.movie_enabled = True
        self.user.anime_enabled = True
        self.user.save()

        response = self.client.post(
            reverse("preferences"),
            {
                "media_types_checkboxes": [MediaTypes.TV.value, MediaTypes.ANIME.value],
                "hide_completed_recommendations": "1",
            },
        )
        self.assertRedirects(response, reverse("preferences"))

        self.user.refresh_from_db()
        self.assertTrue(self.user.tv_enabled)
        self.assertFalse(self.user.movie_enabled)
        self.assertTrue(self.user.anime_enabled)
        self.assertTrue(self.user.hide_completed_recommendations)

        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertIn("Settings updated", str(messages[0]))

    def test_sidebar_post_turns_discover_off_and_on(self):
        """The Show Discover switch is saved from the Sidebar settings page."""
        self.assertTrue(self.user.show_discover)

        response = self.client.post(reverse("sidebar"), {})
        self.assertRedirects(response, reverse("sidebar"))
        self.user.refresh_from_db()
        self.assertFalse(self.user.show_discover)

        self.client.post(reverse("sidebar"), {"show_discover": "on"})
        self.user.refresh_from_db()
        self.assertTrue(self.user.show_discover)

    def test_sidebar_link_hidden_when_discover_off(self):
        """The sidebar shows the Discover link only while Discover is on."""
        discover_link = f'href="{reverse("discover")}"'
        self.assertContains(self.client.get(reverse("home")), discover_link)

        self.user.show_discover = False
        self.user.save(update_fields=["show_discover"])
        self.assertNotContains(self.client.get(reverse("home")), discover_link)

    def test_preferences_post_turns_recommendations_off(self):
        """The Recommendations preference is saved from the Preferences page."""
        self.assertTrue(self.user.show_recommendations)

        self.client.post(reverse("preferences"), {"show_recommendations": "0"})
        self.user.refresh_from_db()
        self.assertFalse(self.user.show_recommendations)

        # A post that omits the field (e.g. the theme toggle) leaves it alone.
        self.client.post(reverse("preferences"), {"theme": "dark"})
        self.user.refresh_from_db()
        self.assertFalse(self.user.show_recommendations)

    def test_sidebar_post_demo_user(self):
        """Test POST request from a demo user to preferences."""
        self.user.is_demo = True
        self.user.tv_enabled = True
        self.user.movie_enabled = False
        self.user.save()

        response = self.client.post(
            reverse("preferences"),
            {
                "media_types_checkboxes": [MediaTypes.TV.value, MediaTypes.MOVIE.value],
            },
        )
        self.assertRedirects(response, reverse("preferences"))

        self.user.refresh_from_db()
        self.assertTrue(self.user.tv_enabled)
        self.assertFalse(self.user.movie_enabled)

        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertIn("view-only for demo accounts", str(messages[0]))

    @override_settings(TVDB_API_KEY="")
    def test_metadata_settings_flags_tvdb_as_not_configured(self):
        """TVDB should still be listed for TV, just flagged as not configured."""
        response = self.client.get(reverse("metadata_settings"))

        self.assertEqual(response.status_code, 200)
        tv_entry = next(
            entry
            for entry in response.context["provider_summary"]
            if entry["media_type"] == MediaTypes.TV.value
        )
        self.assertTrue(tv_entry["configurable"])
        self.assertEqual(tv_entry["current_label"], "The Movie Database")
        tvdb_choice = next(
            choice
            for choice in tv_entry["choices"]
            if choice["value"] == MetadataSourceDefaultChoices.TVDB.value
        )
        self.assertFalse(tvdb_choice["configured"])

    def test_metadata_settings_lists_every_enabled_media_type(self):
        """Media types without a per-user provider preference still show their source."""
        self.user.movie_enabled = True
        self.user.save(update_fields=["movie_enabled"])

        response = self.client.get(reverse("metadata_settings"))

        media_types = [
            entry["media_type"] for entry in response.context["provider_summary"]
        ]
        self.assertIn(MediaTypes.MOVIE.value, media_types)
        movie_entry = next(
            entry
            for entry in response.context["provider_summary"]
            if entry["media_type"] == MediaTypes.MOVIE.value
        )
        self.assertFalse(movie_entry["configurable"])
        self.assertEqual(movie_entry["current_label"], "The Movie Database")

    @override_settings(TVDB_API_KEY="test-tvdb-key")
    def test_set_media_type_provider_updates_defaults_and_library_mode(self):
        """Posting a provider default should persist it, and anime can also set library mode."""
        response = self.client.post(
            reverse("set_media_type_provider", args=[MediaTypes.TV.value]),
            {"source": MetadataSourceDefaultChoices.TVDB},
        )
        self.assertRedirects(response, reverse("metadata_settings"))

        response = self.client.post(
            reverse("set_media_type_provider", args=[MediaTypes.ANIME.value]),
            {
                "source": MetadataSourceDefaultChoices.TMDB,
                "anime_library_mode": AnimeLibraryModeChoices.BOTH,
            },
        )
        self.assertRedirects(response, reverse("metadata_settings"))

        self.user.refresh_from_db()
        self.assertEqual(
            self.user.tv_metadata_source_default, MetadataSourceDefaultChoices.TVDB
        )
        self.assertEqual(
            self.user.anime_metadata_source_default, MetadataSourceDefaultChoices.TMDB
        )
        self.assertEqual(self.user.anime_library_mode, AnimeLibraryModeChoices.BOTH)
