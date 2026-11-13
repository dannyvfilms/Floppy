from django.test import SimpleTestCase

from app.history_cache_utils import _coerce_genre_list as history_genres
from app.metadata_utils import apply_provider_episode_count, normalize_genres
from app.models import Item, MediaTypes
from app.stats_utils import _coerce_genre_list as statistics_genres


class GenreNormalizationTests(SimpleTestCase):
    """Keep provider genre shapes consistent across History and Statistics."""

    def test_supported_provider_shapes(self):
        cases = (
            (None, []),
            ("Jazz", ["Jazz"]),
            ({"name": "Jazz"}, ["Jazz"]),
            ({"tag": "jazz"}, ["jazz"]),
            ({"label": "Jazz"}, ["Jazz"]),
            ({"name": "", "tag": "jazz"}, ["jazz"]),
            ({"unknown": "Jazz"}, []),
            ([None, "", {}, "Jazz", {"name": "Blues"}], ["Jazz", "Blues"]),
            (("Jazz", {"tag": "Blues"}), ["Jazz", "Blues"]),
        )
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(history_genres(value), expected)
                self.assertEqual(statistics_genres(value), expected)
                self.assertEqual(normalize_genres(value), expected)

    def test_only_persistence_normalization_removes_duplicates(self):
        value = ["Jazz", {"name": "Jazz"}, "Blues"]

        self.assertEqual(history_genres(value), ["Jazz", "Jazz", "Blues"])
        self.assertEqual(statistics_genres(value), ["Jazz", "Jazz", "Blues"])
        self.assertEqual(normalize_genres(value), ["Jazz", "Blues"])


class ProviderEpisodeCountTests(SimpleTestCase):
    """Validate normalization of provider episode totals."""

    def test_applies_provider_count_from_details(self):
        item = Item(media_type=MediaTypes.SEASON.value)

        changed = apply_provider_episode_count(
            item,
            {"details": {"episodes": "8"}},
        )

        self.assertEqual(changed, ["provider_episode_count"])
        self.assertEqual(item.provider_episode_count, 8)

    def test_does_not_apply_episode_count_to_movies(self):
        item = Item(media_type=MediaTypes.MOVIE.value)

        changed = apply_provider_episode_count(item, {"max_progress": 1})

        self.assertEqual(changed, [])
        self.assertIsNone(item.provider_episode_count)
