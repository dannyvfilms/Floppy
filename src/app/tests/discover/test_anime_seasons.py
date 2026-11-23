import json
import re
from datetime import date
from unittest.mock import patch

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from app.anime_seasons import ANIME_SEASON_MIN_YEAR
from app.models import Anime, Item, MediaTypes, Sources, Status
from app.providers.services import ProviderAPIError

CONFIGURED = "app.anime_seasons.credentials.is_configured"
SEASONAL = "app.anime_seasons.mal.seasonal_anime"
LOCALDATE = "app.anime_seasons.timezone.localdate"


def anime(media_id, title, anime_format="tv", score=8.0, popularity=10):
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


class AnimeSeasonsTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="anime-seasons-user",
            password="secret123",
        )
        self.client.login(username=self.user.username, password="secret123")

    @staticmethod
    def _track_action(model):
        return next(
            action
            for action in model["actions"]["items"]
            if action.get("modal") == "track"
        )


class AnimeSeasonsPageTests(AnimeSeasonsTestCase):
    """The web page: the shared page model as props over server media cards."""

    @staticmethod
    def _props(response):
        return json.loads(
            re.search(
                r'<script id="anime-seasons-page-props" type="application/json">'
                r"(.*?)</script>",
                response.content.decode(),
                re.DOTALL,
            ).group(1),
        )

    @staticmethod
    def _card_models(response):
        """Return the React card models the page embeds via json_script."""
        scripts = re.findall(
            r'<script id="media-card-[0-9a-f]+" type="application/json">(.*?)</script>',
            response.content.decode(),
            re.DOTALL,
        )
        return [json.loads(script)["model"] for script in scripts]

    @patch(CONFIGURED, return_value=True)
    @patch(SEASONAL)
    def test_page_mounts_the_shared_view_over_the_server_card_grid(
        self,
        mock_seasonal_anime,
        _mock_is_configured,
    ):
        mock_seasonal_anime.return_value = [
            anime(2, "TV Second", score=7.0, popularity=1),
            anime(1, "Movie First", "movie", score=9.0, popularity=2),
        ]

        response = self.client.get(
            reverse("anime_seasons"),
            {"year": 2026, "season": "winter", "format": "movie", "sort": "score"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-anime-seasons-page-root")
        self.assertContains(response, 'data-page-slot="anime-seasons-content"')
        self.assertContains(response, '<div class="media-grid">')
        self.assertEqual(
            [entry["title"] for entry in response.context["entries"]],
            ["Movie First"],
        )
        self.assertContains(response, "/details/mal/anime/1/movie-first")
        props = self._props(response)
        self.assertEqual(props["state"], "ready")
        self.assertEqual(props["count"], 1)
        self.assertEqual(props["season"]["label"], "Winter 2026")
        self.assertEqual(
            props["filters"]["fields"],
            {"season": "winter", "season_year": "2026", "format": "movie"},
        )
        self.assertEqual(props["filters"]["sort"], "score")
        self.assertEqual(props["filters"]["direction"], "desc")
        mock_seasonal_anime.assert_called_once_with(2026, "winter")

    @patch(CONFIGURED, return_value=True)
    @patch(SEASONAL)
    def test_tracked_cards_show_their_status_and_edit_the_entry(
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
        mock_seasonal_anime.return_value = [anime(1, "Planned Anime")]

        response = self.client.get(reverse("anime_seasons"))

        (model,) = self._card_models(response)
        self.assertEqual(model["statusChip"]["status"], Status.PLANNING.value)
        self.assertEqual(
            self._track_action(model)["vals"]["instance_id"],
            str(tracked.id),
        )

    @patch(CONFIGURED, return_value=True)
    @patch(SEASONAL)
    def test_untracked_card_explicitly_opens_create_mode(
        self,
        mock_seasonal_anime,
        _mock_is_configured,
    ):
        mock_seasonal_anime.return_value = [anime(1, "Untracked Anime")]

        response = self.client.get(reverse("anime_seasons"))

        # No instance_id (not even an empty one) so the track modal opens in
        # create mode instead of editing some other entry.
        (model,) = self._card_models(response)
        self.assertIsNone(model["statusChip"])
        self.assertNotIn("instance_id", self._track_action(model)["vals"])

    @override_settings(DEBUG=True)
    @patch(CONFIGURED, return_value=True)
    @patch(SEASONAL)
    def test_untracked_card_renders_in_debug_mode(
        self,
        mock_seasonal_anime,
        _mock_is_configured,
    ):
        mock_seasonal_anime.return_value = [anime(1, "Untracked Anime")]

        response = self.client.get(reverse("anime_seasons"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'alt="Untracked Anime"')

    @patch(CONFIGURED, return_value=False)
    def test_missing_credentials_link_to_the_provider_settings(
        self,
        _mock_is_configured,
    ):
        props = self._props(self.client.get(reverse("anime_seasons")))

        self.assertEqual(props["state"], "error")
        self.assertIn("Add a MyAnimeList client ID", props["error"]["body"])
        self.assertEqual(
            props["error"]["settingsUrl"],
            reverse("provider_detail", kwargs={"slug": "mal"}),
        )

    @patch(CONFIGURED, return_value=True)
    @patch(SEASONAL)
    def test_rejected_credentials_show_the_provider_error(
        self,
        mock_seasonal_anime,
        _mock_is_configured,
    ):
        response = requests.Response()
        response.status_code = 400
        response._content = b"{}"
        mock_seasonal_anime.side_effect = ProviderAPIError(
            Sources.MAL.value,
            requests.HTTPError(response=response),
            "Invalid API key",
        )

        page = self.client.get(reverse("anime_seasons"))

        self.assertEqual(page.status_code, 200)
        props = self._props(page)
        self.assertIn("Invalid API key", props["error"]["body"])
        self.assertEqual(
            props["error"]["settingsUrl"],
            reverse("provider_detail", kwargs={"slug": "mal"}),
        )

    @patch(CONFIGURED, return_value=True)
    @patch(SEASONAL, return_value=[])
    @patch(LOCALDATE)
    def test_invalid_params_fall_back_to_the_current_cour(
        self,
        mock_localdate,
        _mock_seasonal_anime,
        _mock_is_configured,
    ):
        mock_localdate.return_value = date(2026, 7, 15)

        props = self._props(
            self.client.get(
                reverse("anime_seasons"),
                {
                    "year": "bad",
                    "season": "monsoon",
                    "format": "invalid",
                    "sort": "new",
                    "direction": "sideways",
                    "statuses": "Planning,bogus",
                },
            ),
        )

        self.assertEqual(
            props["query"],
            {
                "year": 2026,
                "season": "summer",
                "format": "all",
                "sort": "popularity",
                "direction": "desc",
                "statuses": ["Planning"],
            },
        )
        self.assertEqual(props["previous"]["label"], "Spring 2026")
        self.assertEqual(props["next"]["label"], "Fall 2026")

    @patch(CONFIGURED, return_value=True)
    @patch(SEASONAL, return_value=[])
    @patch(LOCALDATE)
    def test_navigation_wraps_years_and_stops_at_the_range_ends(
        self,
        mock_localdate,
        _mock_seasonal_anime,
        _mock_is_configured,
    ):
        mock_localdate.return_value = date(2026, 1, 10)

        def page(year, season):
            return self._props(
                self.client.get(
                    reverse("anime_seasons"),
                    {"year": year, "season": season},
                ),
            )

        winter = page(2026, "winter")
        oldest = page(ANIME_SEASON_MIN_YEAR, "winter")
        newest = page(2028, "fall")

        self.assertEqual(
            winter["previous"],
            {"year": 2025, "season": "fall", "label": "Fall 2025"},
        )
        self.assertIsNone(oldest["previous"])
        self.assertEqual(oldest["season"]["year"], ANIME_SEASON_MIN_YEAR)
        self.assertEqual(newest["season"]["year"], 2028)
        self.assertIsNone(newest["next"])
        year = next(
            section
            for section in winter["options"]["sections"]
            if section["key"] == "season_year"
        )
        self.assertEqual(year["options"][0]["value"], "2028")
        self.assertEqual(year["options"][-1], {"value": "1917", "label": "1917"})
        # The current season is the default, so it does not count as a filter.
        self.assertEqual(year["clearValue"], "2026")

    @patch(CONFIGURED, return_value=True)
    @patch(SEASONAL)
    def test_empty_states_tell_an_empty_season_from_filters_that_match_nothing(
        self,
        mock_seasonal_anime,
        _mock_is_configured,
    ):
        mock_seasonal_anime.return_value = []
        empty = self._props(self.client.get(reverse("anime_seasons")))
        mock_seasonal_anime.return_value = [anime(1, "TV Only")]
        filtered = self._props(
            self.client.get(reverse("anime_seasons"), {"format": "movie"}),
        )

        self.assertEqual(empty["state"], "empty")
        self.assertEqual(
            empty["empty"]["body"],
            "MyAnimeList has no anime listed for this season yet.",
        )
        self.assertEqual(filtered["state"], "empty")
        self.assertEqual(filtered["empty"]["body"], "No anime match these filters.")

    @patch(CONFIGURED, return_value=True)
    @patch(SEASONAL)
    def test_status_filter_and_sort_directions(
        self,
        mock_seasonal_anime,
        _mock_is_configured,
    ):
        item = Item.objects.create(
            media_id="3",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Gamma",
        )
        Anime.objects.create(user=self.user, item=item, status=Status.PLANNING.value)
        mock_seasonal_anime.return_value = [
            anime(1, "Alpha", score=None, popularity=3),
            anime(2, "Beta", score=7.5, popularity=1),
            anime(3, "Gamma", score=9.0, popularity=None),
        ]

        def titles(**params):
            response = self.client.get(reverse("anime_seasons"), params)
            return [entry["title"] for entry in response.context["entries"]]

        self.assertEqual(titles(), ["Beta", "Alpha", "Gamma"])
        self.assertEqual(titles(direction="asc"), ["Alpha", "Beta", "Gamma"])
        self.assertEqual(titles(sort="score"), ["Gamma", "Beta", "Alpha"])
        self.assertEqual(
            titles(sort="title", direction="desc"), ["Gamma", "Beta", "Alpha"]
        )
        self.assertEqual(titles(statuses="untracked"), ["Beta", "Alpha"])
        self.assertEqual(titles(statuses="Planning"), ["Gamma"])

    @patch(CONFIGURED, return_value=True)
    @patch(SEASONAL)
    def test_filters_do_not_mutate_the_cached_listing(
        self,
        mock_seasonal_anime,
        _mock_is_configured,
    ):
        listing = [
            anime(1, "Zeta", popularity=2),
            anime(2, "Alpha", "movie", popularity=1),
        ]
        mock_seasonal_anime.return_value = listing

        self.client.get(reverse("anime_seasons"), {"sort": "title", "format": "tv"})

        self.assertEqual([entry["title"] for entry in listing], ["Zeta", "Alpha"])
        self.assertNotIn("item", listing[0])

    def test_discover_page_links_to_anime_seasons(self):
        response = self.client.get(reverse("discover"))

        self.assertContains(response, reverse("anime_seasons"))

    def test_discover_hides_the_chip_when_anime_is_disabled(self):
        self.user.anime_enabled = False
        self.user.save(update_fields=["anime_enabled"])

        response = self.client.get(reverse("discover"))

        self.assertNotContains(response, reverse("anime_seasons"))

    def test_anime_seasons_requires_login(self):
        self.client.logout()

        response = self.client.get(reverse("anime_seasons"))

        self.assertEqual(response.status_code, 302)


class AnimeSeasonsAPITests(AnimeSeasonsTestCase):
    """/api/v1/discover/anime-seasons/: the same page model plus card models."""

    url = "/api/v1/discover/anime-seasons/"

    @patch(CONFIGURED, return_value=True)
    @patch(SEASONAL)
    def test_returns_the_page_model_with_native_card_models(
        self,
        mock_seasonal_anime,
        _mock_is_configured,
    ):
        mock_seasonal_anime.return_value = [
            anime(1, "First", popularity=2),
            anime(2, "Second", "movie", popularity=1),
        ]

        response = self.client.get(
            self.url,
            {"year": 2025, "season": "spring", "format": "tv"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["season"]["label"], "Spring 2025")
        self.assertEqual(payload["count"], 1)
        (result,) = payload["results"]
        self.assertEqual(result["key"], "mal-1")
        self.assertEqual(result["card"]["title"], "First")
        identity = result["card"]["quickStatus"]["identity"]
        self.assertEqual(
            (identity["source"], identity["mediaId"]),
            (Sources.MAL.value, "1"),
        )
        self.assertNotIn("instance_id", self._track_action(result["card"])["vals"])

    @patch(CONFIGURED, return_value=False)
    def test_missing_credentials_return_the_error_state(self, _mock_is_configured):
        payload = self.client.get(self.url).json()

        self.assertEqual(payload["state"], "error")
        self.assertEqual(payload["results"], [])
        self.assertEqual(
            payload["error"]["settingsUrl"],
            reverse("provider_detail", kwargs={"slug": "mal"}),
        )

    def test_is_hidden_when_discover_is_off(self):
        self.user.show_discover = False
        self.user.save(update_fields=["show_discover"])

        self.assertEqual(self.client.get(self.url).status_code, 404)
