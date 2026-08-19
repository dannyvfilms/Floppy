from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from app.models import Item, ItemStudioCredit, MediaTypes, Sources, Studio


class StudioDetailViewTests(TestCase):
    """Test studio/company profile pages."""

    def setUp(self):
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    @patch("app.providers.igdb.company_profile", return_value=None)
    def test_studio_detail_falls_back_to_local_credits(self, _mock_company_profile):
        """Studio profiles should fall back to local credits when no profile exists."""
        studio = Studio.objects.create(
            source=Sources.IGDB.value,
            source_studio_id="1",
            name="CD Projekt Red",
            logo="https://images.igdb.com/igdb/image/upload/t_logo_med/logo123.png",
        )
        item = Item.objects.create(
            media_id="1942",
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            title="The Witcher 3: Wild Hunt",
            image="http://example.com/witcher3.jpg",
            release_datetime=timezone.now(),
        )
        ItemStudioCredit.objects.create(item=item, studio=studio)

        response = self.client.get(
            reverse(
                "studio_detail",
                kwargs={
                    "source": Sources.IGDB.value,
                    "studio_id": "1",
                    "name": "cd-projekt-red",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/studio_detail.html")
        self.assertContains(response, "CD Projekt Red")
        self.assertContains(response, "Internet Game Database")
        self.assertContains(response, "Games")
        self.assertContains(response, "Studio profile generated from local credits.")
        self.assertContains(response, "The Witcher 3: Wild Hunt")
        self.assertContains(
            response,
            reverse(
                "media_details",
                kwargs={
                    "source": Sources.IGDB.value,
                    "media_type": MediaTypes.GAME.value,
                    "media_id": "1942",
                    "title": "the-witcher-3-wild-hunt",
                },
            ),
        )
        self.assertEqual(response.context["studio"], studio)
        self.assertEqual(len(response.context["credited_titles"]), 1)

    def test_studio_detail_movie_studio_shows_movie_label(self):
        """Movie studio pages should label credits as movies, not games (#713)."""
        studio = Studio.objects.create(
            source=Sources.TMDB.value,
            source_studio_id="1",
            name="Warner Bros. Pictures",
            logo="https://image.tmdb.org/t/p/original/logo.png",
        )
        item = Item.objects.create(
            media_id="155",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Dark Knight",
            image="http://example.com/dark-knight.jpg",
            release_datetime=timezone.now(),
        )
        ItemStudioCredit.objects.create(item=item, studio=studio)

        response = self.client.get(
            reverse(
                "studio_detail",
                kwargs={
                    "source": Sources.TMDB.value,
                    "studio_id": "1",
                    "name": "warner-bros-pictures",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/studio_detail.html")
        self.assertContains(response, "Warner Bros. Pictures")
        self.assertContains(response, "Movies")
        self.assertContains(response, "The Dark Knight")
        self.assertContains(
            response,
            reverse(
                "media_details",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.MOVIE.value,
                    "media_id": "155",
                    "title": "the-dark-knight",
                },
            ),
        )
        self.assertEqual(response.context["credited_media_type"], MediaTypes.MOVIE.value)

    @patch("app.providers.igdb.company_profile")
    def test_studio_detail_renders_provider_catalog(self, mock_company_profile):
        """Studio profiles should expand to the provider catalog when available."""
        studio = Studio.objects.create(
            source=Sources.IGDB.value,
            source_studio_id="1",
            name="CD Projekt Red",
            logo="https://images.igdb.com/igdb/image/upload/t_logo_med/logo123.png",
        )
        item = Item.objects.create(
            media_id="1942",
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            title="The Witcher 3: Wild Hunt",
            image="http://example.com/witcher3.jpg",
            release_datetime=timezone.now(),
        )
        ItemStudioCredit.objects.create(item=item, studio=studio)

        mock_company_profile.return_value = {
            "media_id": "1",
            "source": Sources.IGDB.value,
            "source_url": "https://www.cdprojekt.com/",
            "title": "CD Projekt Red",
            "name": "CD Projekt Red",
            "image": "https://images.igdb.com/igdb/image/upload/t_logo_med/logo123.png",
            "description": "We make role-playing games.",
            "details": {
                "founded": "1994-03-01",
                "country": 616,
                "status": 0,
                "developed_count": 1,
                "published_count": 2,
            },
            "games": [
                {
                    "media_id": "2077",
                    "source": Sources.IGDB.value,
                    "media_type": MediaTypes.GAME.value,
                    "title": "Cyberpunk 2077",
                    "image": "http://example.com/cyberpunk.jpg",
                    "year": 2020,
                    "role": "Developer, Publisher",
                    "department": "",
                    "credit_type": "game",
                    "sort_order": 0,
                },
                {
                    "media_id": "1942",
                    "source": Sources.IGDB.value,
                    "media_type": MediaTypes.GAME.value,
                    "title": "The Witcher 3: Wild Hunt",
                    "image": "http://example.com/witcher3.jpg",
                    "year": 2015,
                    "role": "Developer",
                    "department": "",
                    "credit_type": "game",
                    "sort_order": 1,
                },
            ],
        }

        response = self.client.get(
            reverse(
                "studio_detail",
                kwargs={
                    "source": Sources.IGDB.value,
                    "studio_id": "1",
                    "name": "cd-projekt-red",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/studio_detail.html")
        self.assertContains(response, "CD Projekt Red")
        self.assertContains(response, "Internet Game Database")
        self.assertContains(response, "Games")
        self.assertContains(response, "Visit Website")
        self.assertContains(response, "We make role-playing games.")
        self.assertContains(response, "Cyberpunk 2077")
        self.assertContains(response, "The Witcher 3: Wild Hunt")
        self.assertContains(response, "Developer, Publisher")
        self.assertContains(response, "2 games")
        self.assertEqual(response.context["studio"], studio)
        self.assertEqual(
            response.context["studio_source_url"], "https://www.cdprojekt.com/"
        )
        self.assertEqual(response.context["studio_games_count"], 2)
        self.assertEqual(len(response.context["credited_titles"]), 2)
        self.assertEqual(
            response.context["credited_titles"][0]["title"], "Cyberpunk 2077"
        )
