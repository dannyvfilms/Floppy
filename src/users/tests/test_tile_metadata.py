"""Parser and default profile for per-type tile metadata."""

from types import SimpleNamespace

from django.test import SimpleTestCase

from app.models.choices import MediaTypes
from users.tile_metadata import (
    ABSORBED_PREFERENCE_FIELDS,
    OMIT,
    absorbed_preference_value,
    apply_absorbed_preference,
    default_profile,
    parse_tile_metadata,
    profiles_from_legacy,
)


class TileMetadataTests(SimpleTestCase):
    """The registry round-trips a save and reproduces the movie tile."""

    def test_default_movie_profile_matches_today(self):
        """A movie tile shows the year and progress until the user edits it."""
        profile = default_profile(MediaTypes.MOVIE.value)
        self.assertEqual(profile["fields"], ["release_year", "progress"])
        self.assertEqual(profile["display"], "hover")
        self.assertFalse(profile["options"]["rating"]["hide_zero"])

    def test_parser_drops_unknown_fields(self):
        """A stale field id cannot land in the stored profile."""
        parsed = parse_tile_metadata(
            {
                "version": 1,
                "types": {
                    "movie": {
                        "display": "always",
                        "fields": ["genres", "not_a_field", "release_year"],
                        "options": {"rating": {"hide_zero": True}},
                    }
                },
            }
        )
        movie = parsed["types"]["movie"]
        self.assertEqual(movie["fields"], ["genres", "release_year"])
        self.assertEqual(movie["display"], "always")
        self.assertTrue(movie["options"]["rating"]["hide_zero"])

    def test_legacy_seed_removes_progress_when_the_bar_is_off(self):
        """progress_bar false drops the progress field on every type."""
        seeded = profiles_from_legacy("always", False, True)
        movie = seeded["types"]["movie"]
        self.assertNotIn("progress", movie["fields"])
        self.assertEqual(movie["display"], "always")
        self.assertTrue(movie["options"]["rating"]["hide_zero"])

    def test_progress_bar_ignores_types_that_have_no_progress_field(self):
        """Person tiles do not vote, so a fresh profile still reports the bar on."""
        user = SimpleNamespace(tile_metadata={})
        apply_absorbed_preference(user, "progress_bar", True)
        self.assertTrue(absorbed_preference_value(user, "progress_bar"))

    def test_mixed_display_omits_the_legacy_name(self):
        """GET drops a name when two types disagree."""
        user = SimpleNamespace(tile_metadata={})
        display_field = next(iter(ABSORBED_PREFERENCE_FIELDS))
        apply_absorbed_preference(user, display_field, "hover")
        user.tile_metadata["types"]["movie"]["display"] = "always"
        self.assertIs(absorbed_preference_value(user, display_field), OMIT)
