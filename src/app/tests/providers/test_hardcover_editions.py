from unittest.mock import patch

from django.test import TestCase

from app.models import MediaTypes, Sources
from app.providers import hardcover


class HardcoverEditionsTests(TestCase):
    """Coverage for Hardcover edition selection (#539)."""

    @patch("app.providers.hardcover.services.api_request")
    def test_editions_returns_normalized_list(self, mock_api_request):
        media_id = "778811"
        hardcover.cache.delete(f"{Sources.HARDCOVER.value}_editions_{media_id}")
        mock_api_request.return_value = {
            "data": {
                "books_by_pk": {
                    "editions": [
                        {
                            "id": 24008419,
                            "title": "Die Nadel",
                            "cached_image": {"url": "https://example.com/de.jpg"},
                            "edition_format": "Paperback",
                            "isbn_13": "9783000000000",
                            "isbn_10": None,
                            "release_date": "1980-01-01",
                            "publisher": {"name": "Bastei"},
                            "language": {"language": "German"},
                        },
                    ],
                },
            },
        }

        result = hardcover.editions(media_id)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "24008419")
        self.assertEqual(result[0]["title"], "Die Nadel")
        self.assertEqual(result[0]["image"], "https://example.com/de.jpg")
        self.assertEqual(result[0]["language"], "German")
        self.assertEqual(result[0]["format"], "Paperback")

    @patch("app.providers.hardcover.services.api_request")
    def test_editions_handles_missing_book(self, mock_api_request):
        media_id = "778813"
        hardcover.cache.delete(f"{Sources.HARDCOVER.value}_editions_{media_id}")
        mock_api_request.return_value = {"data": {"books_by_pk": None}}

        result = hardcover.editions(media_id)

        self.assertEqual(result, [])

    @patch("app.providers.hardcover.services.api_request")
    def test_book_overlays_title_and_image_from_selected_edition(
        self,
        mock_api_request,
    ):
        media_id = "778812"
        edition_id = "24008419"
        for suffix in ("", f"_{edition_id}"):
            hardcover.cache.delete(
                f"{Sources.HARDCOVER.value}_{MediaTypes.BOOK.value}_{media_id}{suffix}",
            )

        def api_request_side_effect(*_args, **kwargs):
            query = kwargs.get("params", {}).get("query", "")
            if "editions_by_pk" in query:
                return {
                    "data": {
                        "editions_by_pk": {
                            "id": int(edition_id),
                            "title": "Die Nadel",
                            "cached_image": {"url": "https://example.com/de.jpg"},
                            "edition_format": "Paperback",
                            "isbn_13": "9783000000000",
                            "isbn_10": None,
                            "release_date": "1980-01-01",
                            "publisher": {"name": "Bastei"},
                        },
                    },
                }
            return {
                "data": {
                    "books_by_pk": {
                        "id": int(media_id),
                        "title": "Eye of the Needle",
                        "cached_image": "https://example.com/en.jpg",
                        "description": "A spy thriller.",
                        "cached_tags": None,
                        "rating": None,
                        "ratings_count": 0,
                        "pages": 320,
                        "release_date": "1978-01-01",
                        "slug": "eye-of-the-needle",
                        "cached_contributors": [],
                        "default_cover_edition": {
                            "edition_format": "Hardcover",
                            "isbn_13": "9780000000000",
                            "isbn_10": None,
                            "release_date": "1978-01-01",
                        },
                        "featured_book_series": [],
                    },
                },
            }

        mock_api_request.side_effect = api_request_side_effect

        default_data = hardcover.book(media_id)
        self.assertEqual(default_data["title"], "Eye of the Needle")
        self.assertEqual(default_data["image"], "https://example.com/en.jpg")

        edition_data = hardcover.book(media_id, edition_id=edition_id)
        self.assertEqual(edition_data["title"], "Die Nadel")
        self.assertEqual(edition_data["image"], "https://example.com/de.jpg")
        self.assertEqual(edition_data["edition_id"], edition_id)
        # Book-level fields (synopsis, series, authors) are unaffected by the edition.
        self.assertEqual(edition_data["synopsis"], "A spy thriller.")
