"""The release-year endpoint remembers items the provider has no date for."""

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from app.models import Item, MediaTypes, Sources


class FetchReleaseYearCostTests(TestCase):
    """A repeat page view must not repeat a provider call that already came up empty."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.item = Item.objects.create(
            media_id="year-miss-1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="No Date Movie",
        )
        self.url = reverse("fetch_release_year")

    def _get(self):
        return self.client.get(self.url, {"item_id": self.item.id})

    @patch("lists.views_list_actions.services.get_media_metadata", return_value={})
    def test_missing_release_date_is_looked_up_once(self, mock_metadata):
        self.assertEqual(self._get().json(), {"year": None})
        self.assertEqual(self._get().json(), {"year": None})

        self.assertEqual(mock_metadata.call_count, 1)

    @patch(
        "lists.views_list_actions.services.get_media_metadata",
        side_effect=RuntimeError("provider down"),
    )
    def test_provider_error_is_not_retried_on_every_view(self, mock_metadata):
        self.assertEqual(self._get().json(), {"year": None})
        self.assertEqual(self._get().json(), {"year": None})

        self.assertEqual(mock_metadata.call_count, 1)

    @patch("lists.views_list_actions.services.get_media_metadata")
    def test_found_release_date_is_stored_and_returned(self, mock_metadata):
        mock_metadata.return_value = {"details": {"release_date": "1999-03-31"}}

        response = self._get().json()

        self.assertEqual(response, {"year": 1999})
        self.item.refresh_from_db()
        self.assertEqual(self.item.release_datetime.year, 1999)
