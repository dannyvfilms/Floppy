"""Scanning a volume's barcode on the Manga and Comics search pages (#809)."""

from unittest.mock import patch

from django.test import TestCase

from app.models import MediaTypes, Sources
from app.providers import services

# A valid ISBN-13 and a valid ISBN-10 ending in X.
ISBN_13 = "9784088736211"
ISBN_10_X = "097522980X"


def open_library_hit(title):
    """Return an Open Library search response with one book."""
    return {
        "page": 1,
        "total_results": 1,
        "total_pages": 1,
        "results": [{"media_id": "OL1M", "title": title}],
    }


class SeriesBarcodeSearchTests(TestCase):
    """A book barcode searches the series, not the barcode digits."""

    @patch("app.providers.services.search_by_id", return_value=None)
    @patch("app.providers.services.mangabaka.search")
    @patch("app.providers.services.openlibrary.search")
    def test_manga_isbn_searches_the_series_title(self, ol_search, baka_search, _):
        """The volume suffix is dropped so the series itself is found."""
        ol_search.return_value = open_library_hit("Death Note, Vol. 1: Boredom")
        baka_search.return_value = {"results": []}

        services.search(
            MediaTypes.MANGA.value,
            ISBN_13,
            1,
            source=Sources.MANGABAKA.value,
        )

        ol_search.assert_called_once_with(ISBN_13, 1)
        baka_search.assert_called_once_with("Death Note", 1)

    @patch("app.providers.services.search_by_id", return_value=None)
    @patch("app.providers.services.comicvine.search")
    @patch("app.providers.services.openlibrary.search")
    def test_comic_isbn_with_x_check_digit(self, ol_search, comicvine_search, _):
        """An ISBN-10 ending in X is a barcode, and a hash issue number is cut."""
        ol_search.return_value = open_library_hit("Saga #5")
        comicvine_search.return_value = {"results": []}

        services.search(
            MediaTypes.COMIC.value,
            ISBN_10_X,
            1,
            source=Sources.COMICVINE.value,
        )

        comicvine_search.assert_called_once_with("Saga", 1, user=None)

    @patch("app.providers.services.search_by_id", return_value=None)
    @patch("app.providers.services.mangabaka.search")
    @patch("app.providers.services.openlibrary.search")
    def test_unknown_isbn_is_searched_as_typed(self, ol_search, baka_search, _):
        """With no title found the digits are searched, so nothing is lost."""
        ol_search.return_value = {"results": []}
        baka_search.return_value = {"results": []}

        services.search(
            MediaTypes.MANGA.value,
            ISBN_13,
            1,
            source=Sources.MANGABAKA.value,
        )

        baka_search.assert_called_once_with(ISBN_13, 1)

    @patch("app.providers.services.search_by_id", return_value=None)
    @patch("app.providers.services.mangabaka.search")
    @patch("app.providers.services.openlibrary.search")
    def test_typed_titles_never_look_up_an_isbn(self, ol_search, baka_search, _):
        """Only a checksum-valid ISBN triggers the lookup."""
        baka_search.return_value = {"results": []}

        services.search(
            MediaTypes.MANGA.value,
            "1984",
            1,
            source=Sources.MANGABAKA.value,
        )

        ol_search.assert_not_called()
        baka_search.assert_called_once_with("1984", 1)

    @patch("app.providers.services.search_by_id", return_value=None)
    @patch("app.providers.services.openlibrary.search")
    def test_lookup_failure_falls_back_to_the_typed_query(self, ol_search, _):
        """A provider outage on the ISBN lookup does not break the search."""
        ol_search.side_effect = RuntimeError("down")

        with patch("app.providers.services.mangabaka.search") as baka_search:
            baka_search.return_value = {"results": []}
            services.search(
                MediaTypes.MANGA.value,
                ISBN_13,
                1,
                source=Sources.MANGABAKA.value,
            )

        baka_search.assert_called_once_with(ISBN_13, 1)

    @patch("app.providers.services.search_by_id", return_value=None)
    @patch("app.providers.services.googlebooks.search")
    @patch("app.providers.services.googlebooks.enabled", return_value=True)
    @patch("app.providers.services.mangabaka.search")
    @patch("app.providers.services.openlibrary.search")
    def test_google_books_answers_when_open_library_is_down(
        self,
        ol_search,
        baka_search,
        _enabled,
        google_search,
        _id,
    ):
        """An Open Library outage still lets Google Books name the series."""
        ol_search.side_effect = RuntimeError("down")
        google_search.return_value = {
            "results": [{"title": "Death Note, Vol. 2: Confluence"}],
        }
        baka_search.return_value = {"results": []}

        services.search(
            MediaTypes.MANGA.value,
            ISBN_13,
            1,
            source=Sources.MANGABAKA.value,
        )

        google_search.assert_called_once_with(f"isbn:{ISBN_13}", 1)
        baka_search.assert_called_once_with("Death Note", 1)
