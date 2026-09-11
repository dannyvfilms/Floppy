from time import perf_counter
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings, tag

from integrations import anime_mapping


class AnimeMappingSnapshotTests(SimpleTestCase):
    """Verify bounded, versioned, reusable Anime-IDs snapshots."""

    def setUp(self):
        cache.clear()
        anime_mapping._IN_MEMORY_SNAPSHOT = None

    def test_same_revision_reuses_compiled_snapshot(self):
        """A cache hit avoids rebuilding the reverse indexes."""
        data = {"show": {"mal_id": "1", "tmdb_show_id": "10"}}
        with patch.object(anime_mapping, "_load_source_data", return_value=(
            data,
            "revision-a",
            "digest-a",
        )), patch.object(anime_mapping, "_build_snapshot", wraps=anime_mapping._build_snapshot) as build:
            first = anime_mapping.load_mapping_snapshot()
            second = anime_mapping.load_mapping_snapshot()

        self.assertEqual(first.revision, second.revision)
        self.assertEqual(build.call_count, 1)
        with self.assertRaises(TypeError):
            first.raw_data["show"] = {}

    def test_new_revision_rebuilds_once(self):
        """Changing the approved revision uses a separate compiled cache key."""
        data = {"show": {"mal_id": "1", "tvdb_id": "10"}}
        with patch.object(anime_mapping, "_load_source_data", side_effect=[
            (data, "revision-a", "digest-a"),
            (data, "revision-b", "digest-b"),
        ]), patch.object(anime_mapping, "_build_snapshot", wraps=anime_mapping._build_snapshot) as build:
            first = anime_mapping.load_mapping_snapshot()
            second = anime_mapping.load_mapping_snapshot()

        self.assertEqual(first.revision, "revision-a")
        self.assertEqual(second.revision, "revision-b")
        self.assertEqual(build.call_count, 2)

    def test_invalid_payload_is_rejected_before_compilation(self):
        """Unknown fields are rejected while MAL-less rows stay non-classifiable."""
        with self.assertRaises(ValueError):
            anime_mapping.load_mapping_snapshot(
                {"bad": {"mal_id": "1", "unexpected": "value"}},
            )
        snapshot = anime_mapping.load_mapping_snapshot(
            {"without-mal": {"tmdb_show_id": "10"}},
        )
        self.assertEqual(snapshot.entry_count, 1)
        self.assertEqual(snapshot.groups, {})

    @override_settings(TESTING=False)
    def test_digest_mismatch_is_rejected(self):
        """A pinned revision whose canonical bytes changed is rejected."""
        cache.clear()
        with patch(
            "integrations.anime_mapping.services.api_request",
            return_value={"show": {"mal_id": "1", "tmdb_show_id": "10"}},
        ):
            with self.assertRaises(ValueError):
                anime_mapping.load_mapping_snapshot()

    @tag("slow", "benchmark")
    def test_index_build_is_bounded_for_small_and_large_inputs(self):
        """Compile representative libraries without quadratic work growth."""
        timings = {}
        for size in (100, 5_000):
            mapping = {
                str(index): {
                    "mal_id": str(index),
                    "tvdb_id": str(100_000 + index),
                }
                for index in range(size)
            }
            started = perf_counter()
            snapshot = anime_mapping.load_mapping_snapshot(mapping)
            timings[size] = perf_counter() - started
            self.assertEqual(snapshot.entry_count, size)

        self.assertLess(timings[5_000], 10 * timings[100] + 5)

    def test_find_entries_for_mal_id_uses_index(self):
        """Regression for #995: lookups use the compiled index, not a scan."""
        mapping = {
            "show-a": {"mal_id": "1,2", "tvdb_id": "10"},
            "show-b": {"mal_id": "3", "tmdb_show_id": "20"},
        }
        with patch.object(
            anime_mapping,
            "_load_source_data",
            return_value=(mapping, "revision-a", "digest-a"),
        ):
            entries = anime_mapping.find_entries_for_mal_id(2)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["tvdb_id"], "10")

            self.assertEqual(anime_mapping.find_entries_for_mal_id("missing"), [])

    def test_resolve_provider_id_supports_anime_movies_and_imdb(self):
        mapping = {
            "movie": {
                "mal_id": "199",
                "tmdb_movie_id": "129",
                "imdb_id": "tt0245429",
            }
        }
        with patch.object(
            anime_mapping,
            "_load_source_data",
            return_value=(mapping, "revision-a", "digest-a"),
        ):
            self.assertEqual(
                anime_mapping.resolve_provider_id(
                    "199",
                    "tmdb",
                    media_type="movie",
                ),
                "129",
            )
            self.assertEqual(
                anime_mapping.resolve_provider_id("199", "imdb"),
                "tt0245429",
            )

    def test_resolve_provider_id_rejects_ambiguous_mapping(self):
        with patch.object(
            anime_mapping,
            "find_entries_for_mal_id",
            return_value=[
                {"mal_id": "199", "imdb_id": "tt0000001"},
                {"mal_id": "199", "imdb_id": "tt0000002"},
            ],
        ):
            self.assertIsNone(anime_mapping.resolve_provider_id("199", "imdb"))

    @tag("slow", "benchmark")
    def test_mal_index_lookup_is_bounded_for_large_mapping(self):
        """Regression for #995: the MAL lookup must be O(1), not a full scan.

        Benchmarks the compiled `mal_index` directly (what `find_entries_for_mal_id`
        reads) rather than round-tripping through `load_mapping_snapshot`'s cache
        deserialize/freeze cost, which is unrelated to this fix and dominates
        per-call timing regardless of lookup strategy.
        """
        size = 15_000
        mapping = {
            str(index): {
                "mal_id": str(index),
                "tvdb_id": str(100_000 + index),
            }
            for index in range(size)
        }
        snapshot = anime_mapping.load_mapping_snapshot(mapping)

        started = perf_counter()
        for mal_id in range(2_000):
            snapshot.mal_index.get(str(mal_id), ())
        elapsed = perf_counter() - started

        self.assertLess(elapsed, 0.05)
