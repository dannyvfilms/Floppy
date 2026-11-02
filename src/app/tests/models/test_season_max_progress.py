"""Season episode counts are read per show, and a failed show is not retried."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from app.models import MediaManager, MediaTypes, Season
from app.tests.test_query_counts import SEASONS_PER_SHOW, seed_tv_library

SHOWS = 2


class SeasonMaxProgressTests(TestCase):
    """Rendering a season list must not make one provider call per season."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="seasons")
        seed_tv_library(cls.user, show_count=SHOWS)

    def setUp(self):
        cache.clear()

    def _seasons(self):
        return list(Season.objects.filter(user=self.user).select_related("item"))

    @patch("app.providers.services.get_media_metadata")
    def test_one_bundle_call_per_show(self, mock_metadata):
        def bundle(media_type, media_id, source, season_numbers, **_kwargs):
            self.assertEqual(media_type, "tv_with_seasons")
            return {
                f"season/{number}": {"max_progress": 42} for number in season_numbers
            }

        mock_metadata.side_effect = bundle
        seasons = self._seasons()
        self.assertEqual(len(seasons), SHOWS * SEASONS_PER_SHOW)

        MediaManager().annotate_max_progress(seasons, MediaTypes.SEASON.value)

        self.assertEqual(mock_metadata.call_count, SHOWS)
        self.assertEqual({season.max_progress for season in seasons}, {42})

    @patch("app.providers.services.get_media_metadata")
    def test_failed_show_is_not_retried_on_the_next_render(self, mock_metadata):
        mock_metadata.side_effect = ConnectionError("provider unreachable")

        first = self._seasons()
        MediaManager().annotate_max_progress(first, MediaTypes.SEASON.value)
        calls_after_first_render = mock_metadata.call_count

        second = self._seasons()
        MediaManager().annotate_max_progress(second, MediaTypes.SEASON.value)

        self.assertEqual(calls_after_first_render, SHOWS)
        self.assertEqual(mock_metadata.call_count, SHOWS)
        # The database count still gives every season a value.
        self.assertTrue(all(hasattr(season, "max_progress") for season in second))
