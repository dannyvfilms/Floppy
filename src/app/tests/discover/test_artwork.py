"""Tests for Discover artwork hydration semantics."""

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from app.discover.artwork import (
    LEGACY_IMG_NONE_VALUES,
    _hydrate_trakt_ranked_artwork,
    _is_missing_image,
)
from app.discover.schemas import CandidateItem
from app.models import MediaTypes, Sources


class MissingArtworkTests(SimpleTestCase):
    def test_runtime_legacy_values_match_frozen_migration_values(self):
        migration = import_module(
            "app.migrations.0155_rewrite_old_img_none_placeholder",
        )

        self.assertIn(migration.OLD_IMG_NONE, LEGACY_IMG_NONE_VALUES)
        self.assertIn(migration.NEW_IMG_NONE, LEGACY_IMG_NONE_VALUES)

    @override_settings(IMG_NONE="https://example.invalid/custom-placeholder.svg")
    def test_custom_placeholder_still_recognises_migrated_builtin_value(self):
        migration = import_module(
            "app.migrations.0155_rewrite_old_img_none_placeholder",
        )
        candidate = CandidateItem(
            media_type=MediaTypes.TV.value,
            source=Sources.TMDB.value,
            media_id="123",
            title="Example",
            image=migration.NEW_IMG_NONE,
        )

        self.assertTrue(_is_missing_image(candidate))

    @override_settings(IMG_NONE="https://example.invalid/custom-placeholder.svg")
    def test_configured_placeholder_is_missing_but_real_artwork_is_not(self):
        candidate = CandidateItem(
            media_type=MediaTypes.TV.value,
            source=Sources.TMDB.value,
            media_id="123",
            title="Example",
            image=settings.IMG_NONE,
        )
        self.assertTrue(_is_missing_image(candidate))

        candidate.image = "https://images.example.test/poster.jpg"
        self.assertFalse(_is_missing_image(candidate))


class ProviderNeutralArtworkHydrationTests(SimpleTestCase):
    @override_settings(IMG_NONE="https://example.invalid/custom-placeholder.svg")
    @patch("app.discover.artwork.services.get_media_metadata")
    @patch("app.discover.artwork.Item.objects.filter")
    def test_trakt_ranked_hydration_uses_candidate_metadata_source(
        self,
        filter_mock,
        metadata_mock,
    ):
        migration = import_module(
            "app.migrations.0155_rewrite_old_img_none_placeholder",
        )
        filter_mock.return_value.only.return_value = []
        metadata_mock.return_value = {
            "image": "https://images.example.test/tvdb-poster.jpg",
        }
        candidate = CandidateItem(
            media_type=MediaTypes.TV.value,
            source=Sources.TVDB.value,
            media_id="456",
            title="Mapped show",
            image=migration.NEW_IMG_NONE,
        )

        _hydrate_trakt_ranked_artwork(MediaTypes.TV.value, [candidate])

        metadata_mock.assert_called_once_with(
            MediaTypes.TV.value,
            "456",
            Sources.TVDB.value,
        )
        self.assertEqual(
            candidate.image,
            "https://images.example.test/tvdb-poster.jpg",
        )

    @override_settings(IMG_NONE="https://example.invalid/custom-placeholder.svg")
    @patch("app.discover.artwork.services.get_media_metadata")
    @patch("app.discover.artwork.Item.objects.filter")
    def test_offline_hydration_uses_matching_local_provider_identity(
        self,
        filter_mock,
        metadata_mock,
    ):
        migration = import_module(
            "app.migrations.0155_rewrite_old_img_none_placeholder",
        )
        filter_mock.return_value.only.return_value = [
            SimpleNamespace(
                media_type=MediaTypes.TV.value,
                source=Sources.TVDB.value,
                media_id="456",
                image="https://images.example.test/local-poster.jpg",
            ),
        ]
        candidate = CandidateItem(
            media_type=MediaTypes.TV.value,
            source=Sources.TVDB.value,
            media_id="456",
            title="Mapped show",
            image=migration.NEW_IMG_NONE,
        )

        _hydrate_trakt_ranked_artwork(
            MediaTypes.TV.value,
            [candidate],
            allow_remote=False,
        )

        metadata_mock.assert_not_called()
        self.assertEqual(
            candidate.image,
            "https://images.example.test/local-poster.jpg",
        )

    @patch("app.discover.artwork.services.get_media_metadata")
    @patch("app.discover.artwork.Item.objects.filter")
    def test_remote_missing_placeholder_does_not_replace_missing_state(
        self,
        filter_mock,
        metadata_mock,
    ):
        filter_mock.return_value.only.return_value = []
        metadata_mock.return_value = {"image": settings.IMG_NONE}
        candidate = CandidateItem(
            media_type=MediaTypes.MOVIE.value,
            source=Sources.TMDB.value,
            media_id="789",
            title="Example movie",
            image=settings.IMG_NONE,
        )

        _hydrate_trakt_ranked_artwork(MediaTypes.MOVIE.value, [candidate])

        self.assertEqual(candidate.image, settings.IMG_NONE)
