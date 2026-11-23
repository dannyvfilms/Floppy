import json
import re
from datetime import date
from unittest.mock import patch

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from app.anime_seasons_views import ANIME_SEASON_MIN_YEAR
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
    def _card_models(response):
        """Return the React card models the page embeds via json_script."""
        scripts = re.findall(
            r'<script id="media-card-[0-9a-f]+" type="application/json">(.*?)</script>',
            response.content.decode(),
            re.DOTALL,
        )
        return [json.loads(script)["model"] for script in scripts]

    @staticmethod
    def _track_action(model):
        return next(
            action
            for action in model["actions"]["items"]
            if action.get("modal") == "track"
        )

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

    @patch("app.anime_seasons_views.credentials.is_configured", return_value=True)
    @patch("app.anime_seasons_views.mal.seasonal_anime")
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

    @patch("app.anime_seasons_views.credentials.is_configured", return_value=True)
    @patch("app.anime_seasons_views.mal.seasonal_anime")
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
        (model,) = self._card_models(response)
        self.assertEqual(model["statusChip"]["status"], Status.PLANNING.value)
        self.assertEqual(
            self._track_action(model)["vals"]["instance_id"],
            str(tracked.id),
        )

    @patch("app.anime_seasons_views.credentials.is_configured", return_value=True)
    @patch("app.anime_seasons_views.mal.seasonal_anime")
    def test_untracked_card_explicitly_opens_create_mode(
        self,
        mock_seasonal_anime,
        _mock_is_configured,
    ):
        mock_seasonal_anime.return_value = [self._anime(1, "Untracked Anime")]

        response = self.client.get(reverse("anime_seasons"))

        # No instance_id (not even an empty one) so the track modal opens in
        # create mode instead of editing some other entry.
        (model,) = self._card_models(response)
        self.assertIsNone(model["statusChip"])
        self.assertNotIn("instance_id", self._track_action(model)["vals"])

    @override_settings(DEBUG=True)
    @patch("app.anime_seasons_views.credentials.is_configured", return_value=True)
    @patch("app.anime_seasons_views.mal.seasonal_anime")
    def test_untracked_card_renders_in_debug_mode(
        self,
        mock_seasonal_anime,
        _mock_is_configured,
    ):
        mock_seasonal_anime.return_value = [self._anime(1, "Untracked Anime")]

        response = self.client.get(reverse("anime_seasons"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'alt="Untracked Anime"')

    @patch("app.anime_seasons_views.credentials.is_configured", return_value=False)
    def test_missing_credentials_render_useful_empty_state(self, _mock_is_configured):
        response = self.client.get(reverse("anime_seasons"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Add a MyAnimeList client ID")
        self.assertContains(
            response, reverse("provider_detail", kwargs={"slug": "mal"})
        )

    @patch("app.anime_seasons_views.credentials.is_configured", return_value=True)
    @patch("app.anime_seasons_views.mal.seasonal_anime")
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
        self.assertContains(page, reverse("provider_detail", kwargs={"slug": "mal"}))

    @patch("app.anime_seasons_views.credentials.is_configured", return_value=True)
    @patch("app.anime_seasons_views.mal.seasonal_anime", return_value=[])
    @patch("app.anime_seasons_views.timezone.localdate")
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
            response.context["previous_link"],
            {"year": 2026, "season": "spring"},
        )
        self.assertEqual(
            response.context["next_link"],
            {"year": 2026, "season": "fall"},
        )

    @patch("app.anime_seasons_views.credentials.is_configured", return_value=True)
    @patch("app.anime_seasons_views.mal.seasonal_anime", return_value=[])
    @patch("app.anime_seasons_views.timezone.localdate")
    def test_navigation_wraps_years_and_stops_at_the_range_ends(
        self,
        mock_localdate,
        _mock_seasonal_anime,
        _mock_is_configured,
    ):
        mock_localdate.return_value = date(2026, 1, 10)

        winter = self.client.get(
            reverse("anime_seasons"),
            {"year": 2026, "season": "winter"},
        )
        oldest = self.client.get(
            reverse("anime_seasons"),
            {"year": ANIME_SEASON_MIN_YEAR, "season": "winter"},
        )
        newest = self.client.get(
            reverse("anime_seasons"),
            {"year": 2028, "season": "fall"},
        )

        self.assertEqual(
            winter.context["previous_link"],
            {"year": 2025, "season": "fall"},
        )
        self.assertIsNone(oldest.context["previous_link"])
        self.assertEqual(oldest.context["year"], ANIME_SEASON_MIN_YEAR)
        self.assertEqual(newest.context["year"], 2028)
        self.assertIsNone(newest.context["next_link"])
        self.assertNotContains(newest, 'aria-label="Next season"')

    @patch("app.anime_seasons_views.credentials.is_configured", return_value=True)
    @patch("app.anime_seasons_views.mal.seasonal_anime", return_value=[])
    def test_empty_season_explains_itself(
        self, _mock_seasonal_anime, _mock_is_configured
    ):
        response = self.client.get(reverse("anime_seasons"))

        self.assertContains(
            response, "MyAnimeList has no anime listed for this season yet."
        )
        self.assertNotContains(response, "No anime found for these filters.")

    @patch("app.anime_seasons_views.credentials.is_configured", return_value=True)
    @patch("app.anime_seasons_views.mal.seasonal_anime")
    def test_filters_do_not_mutate_the_cached_listing(
        self,
        mock_seasonal_anime,
        _mock_is_configured,
    ):
        listing = [
            self._anime(1, "Zeta", popularity=2),
            self._anime(2, "Alpha", "movie", popularity=1),
        ]
        mock_seasonal_anime.return_value = listing

        self.client.get(reverse("anime_seasons"), {"sort": "title", "format": "tv"})

        self.assertEqual([entry["title"] for entry in listing], ["Zeta", "Alpha"])
        self.assertNotIn("item", listing[0])

    def test_discover_page_links_to_anime_seasons(self):
        response = self.client.get(reverse("discover"))

        self.assertContains(response, reverse("anime_seasons"))

    def test_anime_seasons_requires_login(self):
        self.client.logout()

        response = self.client.get(reverse("anime_seasons"))

        self.assertEqual(response.status_code, 302)

    @patch("app.anime_seasons_views.credentials.is_configured", return_value=True)
    @patch("app.anime_seasons_views.mal.seasonal_anime", return_value=[])
    def test_filters_mount_the_shared_toolbar_over_a_get_form(
        self,
        _mock_seasonal_anime,
        _mock_is_configured,
    ):
        response = self.client.get(
            reverse("anime_seasons"),
            {"year": 2024, "season": "spring", "format": "ova", "sort": "title"},
        )

        props = json.loads(
            re.search(
                r'<script id="anime-season-filters-props" type="application/json">'
                r"(.*?)</script>",
                response.content.decode(),
                re.DOTALL,
            ).group(1),
        )
        self.assertEqual(
            {item["name"]: item["value"] for item in props["filters"]},
            {"season": "spring", "year": "2024", "format": "ova", "sort": "title"},
        )
        year = next(item for item in props["filters"] if item["name"] == "year")
        self.assertEqual(year["options"][-1], {"value": "1917", "label": "1917"})
        self.assertContains(response, "data-discover-season-filters-root")
        self.assertContains(response, '<form method="get"')
        self.assertRegex(response.content.decode(), r'<option value="ova"\s+selected>')
