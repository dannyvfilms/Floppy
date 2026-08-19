from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.discover.schemas import CandidateItem
from app.models import MediaTypes, Sources


class RssSettingsTests(TestCase):
    """Tests for the RSS settings page and its HTMX preview endpoint."""

    def setUp(self):
        self.credentials = {"username": "rss-settings-user", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    def test_rss_settings_get(self):
        """The settings page renders with the media type/row data and feed URL."""
        response = self.client.get(reverse("rss_settings"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "users/rss.html")
        self.assertIn("media_types", response.context)
        self.assertIn(self.user.token, response.context["feed_url_template"])
        self.assertIn("MEDIA_TYPE_PLACEHOLDER", response.context["feed_url_template"])
        self.assertIn("ROW_KEY_PLACEHOLDER", response.context["feed_url_template"])

    @patch("app.discover.service.get_or_compute_taste_profile", return_value={})
    @patch("app.discover.service._build_row_candidates")
    def test_preview_renders_discover_row(self, mock_build, _mock_profile):
        mock_build.return_value = [
            CandidateItem(
                media_type=MediaTypes.MOVIE.value,
                source=Sources.TMDB.value,
                media_id="7",
                title="Preview Movie",
                image="http://example.com/7.jpg",
            ),
        ]

        response = self.client.get(
            reverse("discover_row_feed_preview"),
            {
                "media_type": MediaTypes.MOVIE.value,
                "row_key": "trending_right_now",
                "skip_planning": "1",
                "skip_collected": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Preview Movie")

    def test_preview_invalid_row_shows_empty_state(self):
        response = self.client.get(
            reverse("discover_row_feed_preview"),
            {"media_type": MediaTypes.MOVIE.value, "row_key": "not_a_real_row"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No items matched this row right now.")
