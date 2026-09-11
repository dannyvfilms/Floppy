from django.test import TestCase

from app.models import MediaTypes
from app.providers import tmdb


class TmdbGetRelatedTests(TestCase):
    """Tests for tmdb.get_related's season episode_count normalization."""

    def _season_media(self, episode_count):
        return {
            "poster_path": None,
            "season_number": 1,
            "name": "Season 1",
            "air_date": "2020-01-01",
            "vote_average": 8.0,
            "vote_count": 100,
            "episode_count": episode_count,
        }

    def _parent_response(self):
        return {
            "id": 123,
            "name": "Example Show",
            "original_name": "Example Show",
            "poster_path": None,
        }

    def test_get_related_coerces_numeric_string_episode_count(self):
        """A numeric string episode_count should normalize to an int."""
        result = tmdb.get_related(
            [self._season_media("10")],
            MediaTypes.SEASON.value,
            parent_response=self._parent_response(),
        )

        self.assertEqual(result[0]["episode_count"], 10)
        self.assertEqual(result[0]["max_progress"], 10)
        self.assertIsInstance(result[0]["max_progress"], int)

    def test_get_related_coerces_non_numeric_episode_count_to_none(self):
        """A non-numeric episode_count should normalize to None, not a raw string."""
        result = tmdb.get_related(
            [self._season_media("TBA")],
            MediaTypes.SEASON.value,
            parent_response=self._parent_response(),
        )

        self.assertIsNone(result[0]["episode_count"])
        self.assertIsNone(result[0]["max_progress"])
