"""List search and add flows must honor the user's metadata language (#1579)."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from app.models import Item, MediaTypes, Sources
from lists.models import CustomList


def _tmdb_search_payload(title):
    return {
        "results": [
            {
                "id": 328425,
                "title": title,
                "original_title": "Riot",
                "poster_path": "/riot.jpg",
                "release_date": "2015-01-01",
            },
        ],
        "total_results": 1,
    }


class ListMetadataLanguageTests(TestCase):
    """The list pages should request the language set in preferences."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            "owner", "owner@example.com", "pw"
        )
        self.user.metadata_language = "es-ES"
        self.user.save(update_fields=["metadata_language"])
        self.client = Client()
        self.client.force_login(self.user)
        self.custom_list = CustomList.objects.create(name="Mi lista", owner=self.user)

    @patch("app.providers.services.api_request")
    def test_quick_add_search_requests_user_language(self, mock_api):
        """Searching from a list sends es-ES to TMDB and shows the Spanish title."""
        mock_api.return_value = _tmdb_search_payload("Venganza en la prisión")

        response = self.client.get(
            reverse("list_add_item_search", args=[self.custom_list.id]),
            {"q": "venganza en la prision", "media_type": MediaTypes.MOVIE.value},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Venganza en la prisión")
        languages = {
            call.kwargs["params"].get("language")
            for call in mock_api.mock_calls
            if "params" in call.kwargs
        }
        self.assertIn("es-ES", languages)

    @patch("app.providers.services.api_request")
    def test_recommend_search_requests_owner_language_for_visitors(self, mock_api):
        """Anonymous recommenders get the list owner's language."""
        self.custom_list.visibility = "public"
        self.custom_list.allow_recommendations = True
        self.custom_list.save()
        mock_api.return_value = _tmdb_search_payload("Venganza en la prisión")

        response = Client().get(
            reverse("recommend_search", args=[self.custom_list.id]),
            {"q": "venganza en la prision", "media_type": MediaTypes.MOVIE.value},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Venganza en la prisión")
        languages = {
            call.kwargs["params"].get("language")
            for call in mock_api.mock_calls
            if "params" in call.kwargs
        }
        self.assertIn("es-ES", languages)

    @patch("lists.views_add_reorder.services.get_media_metadata")
    def test_preview_requests_user_language(self, mock_metadata):
        mock_metadata.return_value = {
            "title": "Venganza en la prisión",
            "image": "https://example.com/p.jpg",
            "details": {},
            "genres": [],
            "synopsis": "",
        }

        self.client.get(
            reverse("list_add_item_search", args=[self.custom_list.id]),
            {
                "show_preview": "true",
                "media_id": "328425",
                "media_type": MediaTypes.MOVIE.value,
                "source": Sources.TMDB.value,
            },
        )

        self.assertEqual(mock_metadata.call_args.kwargs["language"], "es-ES")

    @patch("lists.views_add_reorder.services.get_media_metadata")
    def test_adding_to_list_stores_localized_title(self, mock_metadata):
        """A new item is requested in the user's language, so it saves in Spanish."""

        def fake(media_type, media_id, source, *args, language=None, **kwargs):
            title = "Venganza en la prisión" if language == "es-ES" else "Riot"
            return {"title": title, "localized_title": title, "image": "x.jpg"}

        mock_metadata.side_effect = fake

        self.client.post(
            reverse("list_add_item_submit", args=[self.custom_list.id]),
            {
                "media_id": "328425",
                "media_type": MediaTypes.MOVIE.value,
                "source": Sources.TMDB.value,
            },
        )

        item = Item.objects.get(media_id="328425", source=Sources.TMDB.value)
        self.assertEqual(item.title, "Venganza en la prisión")

    @patch("lists.views_recommendations.services.get_media_metadata")
    def test_recommendation_item_uses_language(self, mock_metadata):
        mock_metadata.return_value = {"title": "x", "image": "x.jpg"}
        from lists.views_recommendations import get_or_create_recommendation_item

        get_or_create_recommendation_item(
            "328425", MediaTypes.MOVIE.value, Sources.TMDB.value, language="es-ES"
        )

        self.assertEqual(mock_metadata.call_args.kwargs["language"], "es-ES")

    def test_default_language_when_no_preference(self):
        from django.conf import settings

        from lists.views_helpers import list_metadata_language

        self.user.metadata_language = ""
        self.assertEqual(list_metadata_language(self.user), settings.TMDB_LANG)
