from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import (
    Book,
    HardcoverEditionPreference,
    Item,
    MediaTypes,
    Sources,
    Status,
)


class HardcoverEditionViewTests(TestCase):
    """Coverage for the Hardcover edition picker views (#539)."""

    def setUp(self):
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        self.item = Item.objects.create(
            media_id="778812",
            source=Sources.HARDCOVER.value,
            media_type=MediaTypes.BOOK.value,
            title="Eye of the Needle",
            image="http://example.com/en.jpg",
            number_of_pages=354,
        )

    @patch("app.metadata_sync_views.hardcover.editions")
    def test_list_hardcover_editions_renders_results(self, mock_editions):
        mock_editions.return_value = [
            {
                "id": "24008419",
                "title": "Die Nadel",
                "image": "http://example.com/de.jpg",
                "format": "Paperback",
                "language": "German",
                "publisher": "Bastei",
                "release_date": "1980-01-01",
            },
        ]

        response = self.client.get(
            reverse("list_hardcover_editions", kwargs={"media_id": "778812"}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Die Nadel")
        self.assertContains(
            response,
            reverse("set_hardcover_edition", kwargs={"item_id": self.item.id}),
        )

    @patch("app.metadata_sync_views.hardcover.editions")
    def test_list_hardcover_editions_filters_by_query(self, mock_editions):
        mock_editions.return_value = [
            {
                "id": "24008419",
                "title": "Die Nadel",
                "image": "http://example.com/de.jpg",
                "format": "Paperback",
                "language": "German",
                "publisher": "Bastei",
                "release_date": "1980-01-01",
            },
            {
                "id": "1",
                "title": "Eye of the Needle",
                "image": "http://example.com/en.jpg",
                "format": "Hardcover",
                "language": "English",
                "publisher": "Storm",
                "release_date": "1978-01-01",
            },
        ]

        response = self.client.get(
            reverse("list_hardcover_editions", kwargs={"media_id": "778812"}),
            {"q": "german"},
        )

        self.assertContains(response, "Die Nadel")
        self.assertNotContains(response, "Eye of the Needle")

    def test_set_hardcover_edition_persists_preference(self):
        response = self.client.post(
            reverse("set_hardcover_edition", kwargs={"item_id": self.item.id}),
            {"edition_id": "24008419", "return_url": "/home"},
        )

        self.assertEqual(response.status_code, 302)
        preference = HardcoverEditionPreference.objects.get(
            user=self.user,
            item=self.item,
        )
        self.assertEqual(preference.edition_id, "24008419")

    def test_set_hardcover_edition_requires_edition_id(self):
        response = self.client.post(
            reverse("set_hardcover_edition", kwargs={"item_id": self.item.id}),
            {"return_url": "/home"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            HardcoverEditionPreference.objects.filter(
                user=self.user,
                item=self.item,
            ).exists(),
        )

    @patch("app.media_details_views.services.get_media_metadata")
    def test_media_details_applies_stored_edition_preference(
        self,
        mock_get_media_metadata,
    ):
        HardcoverEditionPreference.objects.create(
            user=self.user,
            item=self.item,
            edition_id="24008419",
        )
        mock_get_media_metadata.return_value = {
            "media_id": "778812",
            "source": Sources.HARDCOVER.value,
            "media_type": MediaTypes.BOOK.value,
            "title": "Die Nadel",
            "image": "http://example.com/de.jpg",
            "synopsis": "A spy thriller.",
            "details": {},
            "related": {},
        }

        self.client.get(
            reverse(
                "media_details",
                kwargs={
                    "source": Sources.HARDCOVER.value,
                    "media_type": MediaTypes.BOOK.value,
                    "media_id": "778812",
                    "title": "eye-of-the-needle",
                },
            ),
        )

        self.assertEqual(
            mock_get_media_metadata.call_args.kwargs.get("edition_id"),
            "24008419",
        )

    @patch("app.track_modal_views.hardcover.editions")
    def test_track_modal_shows_selected_edition_row(self, mock_editions):
        Book.objects.create(
            item=self.item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        HardcoverEditionPreference.objects.create(
            user=self.user,
            item=self.item,
            edition_id="24008419",
        )
        mock_editions.return_value = [
            {
                "id": "24008419",
                "title": "Die Nadel",
                "image": "http://example.com/de.jpg",
                "format": "Paperback",
                "language": "German",
                "publisher": "Bastei",
                "release_date": "1980-01-01",
            },
        ]

        response = self.client.get(
            reverse(
                "track_modal",
                kwargs={
                    "source": Sources.HARDCOVER.value,
                    "media_type": MediaTypes.BOOK.value,
                    "media_id": "778812",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Selected edition")
        self.assertContains(response, "Die Nadel")

    def test_track_modal_hides_selected_edition_row_without_preference(self):
        Book.objects.create(
            item=self.item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

        response = self.client.get(
            reverse(
                "track_modal",
                kwargs={
                    "source": Sources.HARDCOVER.value,
                    "media_type": MediaTypes.BOOK.value,
                    "media_id": "778812",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Selected edition")
