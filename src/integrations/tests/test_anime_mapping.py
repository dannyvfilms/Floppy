from time import perf_counter
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings, tag

from integrations import anime_mapping


class AnimeMappingSnapshotTests(SimpleTestCase):
    """Verify bounded, versioned, reusable Anime-IDs snapshots."""

    def setUp(self):
        cache.clear()

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
