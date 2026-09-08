from datetime import date
from unittest.mock import patch

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from app.models import Anime, Item, MediaTypes, Sources, Status
from app.providers.services import ProviderAPIError


class AnimeSeasonsViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="anime-seasons-user",
            password="secret123",
        )
        self.client.login(username=self.user.username, password="secret123")

    @staticmethod
    def _anime(media_id, title, anime_format="tv", score=8.0, popularity=10):
        return {
            "media_id": str(media_id),
            "source": Sources.MAL.value,
            "media_type": MediaTypes.ANIME.value,
            "title": title,
            "original_title": title,
            "localized_title": title,
            "image": f"https://example.com/{media_id}.jpg",
            "release_date": "2026-01-01",
            "format": anime_format,
            "score": score,
            "popularity_rank": popularity,
        }

    @patch("app.discover_views.credentials.is_configured", return_value=True)
    @patch("app.discover_views.mal.seasonal_anime")
    def test_page_filters_sorts_and_links_to_mal_details(
        self,
        mock_seasonal_anime,
        _mock_is_configured,
    ):
        mock_seasonal_anime.return_value = [
            self._anime(2, "TV Second", score=7.0, popularity=1),
            self._anime(1, "Movie First", "movie", score=9.0, popularity=2),
        ]

        response = self.client.get(
            reverse("anime_seasons"),
            {"year": 2026, "season": "winter", "format": "movie", "sort": "score"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [card["title"] for card in response.context["cards"]],
            ["Movie First"],
        )
        self.assertContains(response, "/details/mal/anime/1/movie-first")
        self.assertContains(response, "Add to tracker")
        self.assertContains(response, "All Media")
        self.assertContains(response, 'aria-current="page"')
        self.assertContains(response, '<div class="media-grid">')
        mock_seasonal_anime.assert_called_once_with(2026, "winter")

    @patch("app.discover_views.credentials.is_configured", return_value=True)
    @patch("app.discover_views.mal.seasonal_anime")
    def test_page_resolves_existing_tracking_state_in_bulk(
        self,
        mock_seasonal_anime,
        _mock_is_configured,
    ):
        item = Item.objects.create(
            media_id="1",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Planned Anime",
        )
        tracked = Anime.objects.create(
            user=self.user,
            item=item,
            status=Status.PLANNING.value,
        )
        mock_seasonal_anime.return_value = [self._anime(1, "Planned Anime")]

        response = self.client.get(reverse("anime_seasons"))

        self.assertEqual(response.context["cards"][0]["media"], tracked)
        self.assertContains(response, 'id="media-status-chip-1"')

    @patch("app.discover_views.credentials.is_configured", return_value=True)
    @patch("app.discover_views.mal.seasonal_anime")
    def test_untracked_card_explicitly_opens_create_mode(
        self,
        mock_seasonal_anime,
        _mock_is_configured,
    ):
        mock_seasonal_anime.return_value = [self._anime(1, "Untracked Anime")]

        response = self.client.get(reverse("anime_seasons"))

        self.assertContains(response, '"is_create": "1"')

    @override_settings(DEBUG=True)
    @patch("app.discover_views.credentials.is_configured", return_value=True)
    @patch("app.discover_views.mal.seasonal_anime")
    def test_untracked_card_renders_in_debug_mode(
        self,
        mock_seasonal_anime,
        _mock_is_configured,
    ):
        mock_seasonal_anime.return_value = [self._anime(1, "Untracked Anime")]

        response = self.client.get(reverse("anime_seasons"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'alt="Untracked Anime"')

    @patch("app.discover_views.credentials.is_configured", return_value=False)
    def test_missing_credentials_render_useful_empty_state(self, _mock_is_configured):
        response = self.client.get(reverse("anime_seasons"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "MyAnimeList credentials are not configured")

    @patch("app.discover_views.credentials.is_configured", return_value=True)
    @patch("app.discover_views.mal.seasonal_anime")
    def test_invalid_credentials_render_provider_error(
        self,
        mock_seasonal_anime,
        _mock_is_configured,
    ):
        response = requests.Response()
        response.status_code = 400
        response._content = b"{}"
        error = requests.HTTPError(response=response)
        mock_seasonal_anime.side_effect = ProviderAPIError(
            Sources.MAL.value,
            error,
            "Invalid API key",
        )

        page = self.client.get(reverse("anime_seasons"))

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Invalid API key")

    @patch("app.discover_views.credentials.is_configured", return_value=True)
    @patch("app.discover_views.mal.seasonal_anime", return_value=[])
    @patch("app.discover_views.timezone.localdate")
    def test_invalid_params_fall_back_to_current_cour(
        self,
        mock_localdate,
        _mock_seasonal_anime,
        _mock_is_configured,
    ):
        mock_localdate.return_value = date(2026, 7, 15)

        response = self.client.get(
            reverse("anime_seasons"),
            {
                "year": "bad",
                "season": "monsoon",
                "format": "invalid",
                "sort": "new",
            },
        )

        self.assertEqual(response.context["year"], 2026)
        self.assertEqual(response.context["season"], "summer")
        self.assertEqual(response.context["selected_format"], "all")
        self.assertEqual(response.context["selected_sort"], "popularity")
        self.assertEqual(
            (
                response.context["previous_year"],
                response.context["previous_season"],
            ),
            (2026, "spring"),
        )
        self.assertEqual(
            (response.context["next_year"], response.context["next_season"]),
            (2026, "fall"),
        )
