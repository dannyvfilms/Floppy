from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.db.utils import OperationalError
from django.test import TestCase, override_settings
from django.utils import timezone

from app.models import (
    TV,
    Episode,
    Item,
    ItemProviderLink,
    MediaTypes,
    MetadataProviderPreference,
    Season,
    Sources,
    Status,
)
from app.providers import credentials
from app.services import metadata_resolution


class MetadataResolutionTests(TestCase):
    """Tests for per-user metadata provider resolution."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="resolver",
            password="pw12345",
        )

    def test_metadata_language_default_falls_back_to_global_without_item(self):
        """No item should mean the user's global language preference applies."""
        self.user.metadata_language = "fr"

        language = metadata_resolution.metadata_language_default(self.user)

        self.assertEqual(language, "fr")

    def test_metadata_language_default_falls_back_to_global_without_preference(self):
        """An item with no stored language preference should use the global default."""
        self.user.metadata_language = "fr"
        item = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Breaking Bad",
        )

        language = metadata_resolution.metadata_language_default(self.user, item)

        self.assertEqual(language, "fr")

    def test_metadata_language_default_uses_item_override(self):
        """A per-item language preference should win over the global default."""
        self.user.metadata_language = "fr"
        item = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Breaking Bad",
        )
        MetadataProviderPreference.objects.create(
            user=self.user,
            item=item,
            language="ja",
        )

        language = metadata_resolution.metadata_language_default(self.user, item)

        self.assertEqual(language, "ja")

    def test_metadata_language_default_ignores_item_for_unauthenticated_user(self):
        """An unauthenticated user should never trigger a preference lookup."""
        item = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Breaking Bad",
        )

        language = metadata_resolution.metadata_language_default(
            AnonymousUser(),
            item,
        )

        self.assertEqual(language, metadata_resolution.settings.TMDB_LANG)

    def test_metadata_default_source_falls_back_when_tvdb_is_disabled(self):
        """TV defaults should fall back to TMDB when TVDB is unavailable."""
        self.user.tv_metadata_source_default = Sources.TVDB.value

        with override_settings(TVDB_API_KEY=""):
            provider = metadata_resolution.metadata_default_source(
                self.user,
                MediaTypes.TV.value,
            )

        self.assertEqual(provider, Sources.TMDB.value)

    @override_settings(GOOGLE_BOOKS_API_KEY="")
    def test_googlebooks_is_hidden_without_an_api_key(self):
        """Google Books should not be offered when the instance is unconfigured."""
        sources = metadata_resolution.available_metadata_sources(MediaTypes.BOOK.value)

        self.assertNotIn(Sources.GOOGLEBOOKS, sources)
        self.assertFalse(metadata_resolution.provider_is_enabled("googlebooks"))

    @override_settings(GOOGLE_BOOKS_API_KEY="google-key")
    def test_googlebooks_is_available_with_an_api_key(self):
        """Google Books should be offered when the instance key is present."""
        sources = metadata_resolution.available_metadata_sources(MediaTypes.BOOK.value)

        self.assertIn(Sources.GOOGLEBOOKS, sources)
        self.assertTrue(metadata_resolution.provider_is_enabled("googlebooks"))

    @override_settings(GOOGLE_BOOKS_API_KEY="google-key")
    def test_books_keep_hardcover_as_the_default_source(self):
        """Adding Google Books must not change the book default provider."""
        self.assertEqual(
            metadata_resolution.metadata_default_source(
                self.user,
                MediaTypes.BOOK.value,
            ),
            Sources.HARDCOVER.value,
        )

    @override_settings(HARDCOVER_API="")
    def test_hardcover_is_hidden_without_a_token(self):
        """Hardcover ships no default token, so it is opt-in (#1025)."""
        sources = metadata_resolution.available_metadata_sources(MediaTypes.BOOK.value)

        self.assertNotIn(Sources.HARDCOVER, sources)
        self.assertFalse(metadata_resolution.provider_is_enabled("hardcover"))

    @override_settings(HARDCOVER_API="")
    def test_books_fall_back_to_open_library_without_a_hardcover_token(self):
        """The reported bug: an unconfigured default left book search dead."""
        self.assertEqual(
            metadata_resolution.metadata_default_source(
                self.user,
                MediaTypes.BOOK.value,
            ),
            Sources.OPENLIBRARY.value,
        )

    @override_settings(HARDCOVER_API="")
    def test_a_personal_token_puts_hardcover_back(self):
        """A member with their own key is not held back by the instance."""
        credentials.set_user("hardcover", self.user, {"api_key": "personal-token"})

        self.assertTrue(
            metadata_resolution.provider_is_enabled("hardcover", self.user),
        )
        self.assertIn(
            Sources.HARDCOVER,
            metadata_resolution.available_metadata_sources(
                MediaTypes.BOOK.value,
                self.user,
            ),
        )
        self.assertEqual(
            metadata_resolution.metadata_default_source(
                self.user,
                MediaTypes.BOOK.value,
            ),
            Sources.HARDCOVER.value,
        )

    def test_get_tracking_media_type_keeps_season_and_episode_distinct_from_tv(self):
        """A season/episode route must not collapse to "tv" via identity_media_type.

        Regression test for GitHub issue #323: TVDB (and grouped-anime routes)
        always tag season/episode metadata with identity_media_type="tv" to
        describe the parent show's identity. get_tracking_media_type used to
        blanket-fallback to identity_media_type whenever it was truthy, which
        resolved "season"/"episode" routes to the TV model/form instead of
        Season/Episode - dropping the season_number field from the track form
        entirely and causing "mark season as Planning" to fail.
        """
        self.assertEqual(
            metadata_resolution.get_tracking_media_type(
                MediaTypes.SEASON.value,
                source=Sources.TVDB.value,
                identity_media_type=MediaTypes.TV.value,
            ),
            MediaTypes.SEASON.value,
        )
        self.assertEqual(
            metadata_resolution.get_tracking_media_type(
                MediaTypes.EPISODE.value,
                source=Sources.TVDB.value,
                identity_media_type=MediaTypes.TV.value,
            ),
            MediaTypes.EPISODE.value,
        )

    def test_get_tracking_media_type_still_groups_anime_into_tv(self):
        """The one legitimate override - grouped anime - should still work."""
        self.assertEqual(
            metadata_resolution.get_tracking_media_type(
                MediaTypes.ANIME.value,
                source=Sources.TVDB.value,
                identity_media_type=MediaTypes.TV.value,
            ),
            MediaTypes.TV.value,
        )
        self.assertEqual(
            metadata_resolution.get_tracking_media_type(
                MediaTypes.ANIME.value,
                source=Sources.MAL.value,
                identity_media_type=None,
            ),
            MediaTypes.ANIME.value,
        )

    @override_settings(TVDB_API_KEY="test-tvdb-key")
    @patch("app.services.metadata_resolution.services.get_media_metadata")
    def test_resolve_detail_metadata_uses_provider_override_without_changing_tracking(
        self,
        mock_get_media_metadata,
    ):
        """Display-provider overrides should not mutate the tracked provider."""
        item = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Breaking Bad",
            image="https://example.com/breaking-bad.jpg",
        )
        MetadataProviderPreference.objects.create(
            user=self.user,
            item=item,
            provider=Sources.TVDB.value,
        )
        ItemProviderLink.objects.create(
            item=item,
            provider=Sources.TVDB.value,
            provider_media_id="81189",
            provider_media_type=MediaTypes.TV.value,
        )
        base_metadata = {
            "media_id": "1396",
            "source": Sources.TMDB.value,
            "media_type": MediaTypes.TV.value,
            "title": "Breaking Bad",
            "image": "https://example.com/breaking-bad.jpg",
            "source_url": "https://www.themoviedb.org/tv/1396",
            "external_links": {"TMDB": "https://www.themoviedb.org/tv/1396"},
            "details": {"episodes": 62, "status": "Tracked"},
            "related": {"recommendations": [{"media_id": "1"}]},
        }
        mock_get_media_metadata.return_value = {
            "media_id": "81189",
            "source": Sources.TVDB.value,
            "media_type": MediaTypes.TV.value,
            "title": "Breaking Bad (TVDB)",
            "image": "https://example.com/breaking-bad-tvdb.jpg",
            "source_url": "https://www.thetvdb.com/dereferrer/series/81189",
            "external_links": {
                "TVDB": "https://www.thetvdb.com/dereferrer/series/81189"
            },
            "details": {"episodes": 999, "status": "Overlay"},
            "related": {"seasons": [{"season_number": 1}]},
        }

        result = metadata_resolution.resolve_detail_metadata(
            self.user,
            item=item,
            route_media_type=MediaTypes.TV.value,
            media_id=item.media_id,
            source=item.source,
            base_metadata=base_metadata,
        )

        self.assertEqual(result.display_provider, Sources.TVDB.value)
        self.assertEqual(result.identity_provider, Sources.TMDB.value)
        self.assertEqual(result.mapping_status, "mapped")
        self.assertEqual(result.provider_media_id, "81189")
        self.assertEqual(result.header_metadata["title"], "Breaking Bad (TVDB)")
        self.assertEqual(
            result.header_metadata["source_url"],
            "https://www.themoviedb.org/tv/1396",
        )
        self.assertEqual(
            result.header_metadata["display_source_url"],
            "https://www.thetvdb.com/dereferrer/series/81189",
        )
        self.assertEqual(result.header_metadata["details"]["status"], "Tracked")
        self.assertEqual(
            result.header_metadata["related"],
            {"recommendations": [{"media_id": "1"}]},
        )
        self.assertEqual(
            result.header_metadata["external_links"],
            {
                "TMDB": "https://www.themoviedb.org/tv/1396",
                "TVDB": "https://www.thetvdb.com/dereferrer/series/81189",
            },
        )
        self.assertEqual(item.source, Sources.TMDB.value)

    @override_settings(TVDB_API_KEY="test-tvdb-key")
    def test_resolve_detail_metadata_defaults_to_tracking_source_without_preference(
        self,
    ):
        """Tracked titles should keep showing metadata from their own source by default."""
        item = Item.objects.create(
            media_id="52991",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Frieren",
            image="https://example.com/frieren.jpg",
        )
        self.user.anime_metadata_source_default = Sources.TVDB.value

        result = metadata_resolution.resolve_detail_metadata(
            self.user,
            item=item,
            route_media_type=MediaTypes.ANIME.value,
            media_id=item.media_id,
            source=item.source,
            base_metadata={
                "media_id": "52991",
                "source": Sources.MAL.value,
                "media_type": MediaTypes.ANIME.value,
                "title": "Frieren",
                "image": "https://example.com/frieren.jpg",
                "details": {"episodes": 28},
                "related": {},
            },
        )

        self.assertEqual(result.display_provider, Sources.MAL.value)
        self.assertEqual(result.identity_provider, Sources.MAL.value)
        self.assertEqual(result.mapping_status, "identity")

    @override_settings(TVDB_API_KEY="test-tvdb-key")
    def test_resolve_detail_metadata_uses_requested_source_for_untracked_result(self):
        """Explicit search-result routes should show their own provider metadata by default."""
        self.user.anime_metadata_source_default = Sources.TVDB.value

        result = metadata_resolution.resolve_detail_metadata(
            self.user,
            item=None,
            route_media_type=MediaTypes.ANIME.value,
            media_id="52991",
            source=Sources.MAL.value,
            base_metadata={
                "media_id": "52991",
                "source": Sources.MAL.value,
                "media_type": MediaTypes.ANIME.value,
                "title": "Frieren",
                "image": "https://example.com/frieren.jpg",
                "details": {"episodes": 28},
                "related": {},
            },
        )

        self.assertEqual(result.display_provider, Sources.MAL.value)
        self.assertEqual(result.identity_provider, Sources.MAL.value)
        self.assertEqual(result.mapping_status, "identity")

    @override_settings(TVDB_API_KEY="test-tvdb-key")
    def test_resolve_detail_metadata_marks_missing_mapping(self):
        """Missing cross-provider mappings should be surfaced without switching tracking."""
        item = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Breaking Bad",
            image="https://example.com/breaking-bad.jpg",
        )
        MetadataProviderPreference.objects.create(
            user=self.user,
            item=item,
            provider=Sources.TVDB.value,
        )
        base_metadata = {
            "media_id": "1396",
            "source": Sources.TMDB.value,
            "media_type": MediaTypes.TV.value,
            "title": "Breaking Bad",
            "image": "https://example.com/breaking-bad.jpg",
            "details": {"episodes": 62},
            "related": {},
        }

        result = metadata_resolution.resolve_detail_metadata(
            self.user,
            item=item,
            route_media_type=MediaTypes.TV.value,
            media_id=item.media_id,
            source=item.source,
            base_metadata=base_metadata,
        )

        self.assertEqual(result.display_provider, Sources.TVDB.value)
        self.assertEqual(result.mapping_status, "missing")
        self.assertIsNone(result.provider_media_id)
        self.assertEqual(result.header_metadata["title"], "Breaking Bad")

    def test_resolve_detail_metadata_uses_custom_overlay_for_movie(self):
        """Custom provider preferences should overlay stored metadata on normal items."""
        item = Item.objects.create(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Matrix",
            original_title="The Matrix",
            localized_title="The Matrix",
            image="https://example.com/custom-matrix.jpg",
            genres=["Action", "Sci-Fi"],
            runtime="2h 16min",
            manual_metadata={
                "title": "The Matrix (Custom)",
                "original_title": "Matrix Original",
                "localized_title": "Matrix Localized",
                "image": "https://example.com/custom-matrix.jpg",
                "synopsis": "Custom synopsis.",
                "genres": ["Action", "Sci-Fi"],
                "details": {
                    "release_date": "1999-03-31",
                    "runtime": "2h 16min",
                    "status": "Released",
                },
            },
        )
        MetadataProviderPreference.objects.create(
            user=self.user,
            item=item,
            provider=Sources.MANUAL.value,
        )
        base_metadata = {
            "media_id": "603",
            "source": Sources.TMDB.value,
            "media_type": MediaTypes.MOVIE.value,
            "title": "The Matrix",
            "image": "https://example.com/provider-matrix.jpg",
            "synopsis": "Provider synopsis.",
            "genres": ["Action"],
            "details": {
                "release_date": "1999-01-01",
                "runtime": "2h 10min",
                "status": "Provider",
            },
            "related": {"recommendations": [{"media_id": "604"}]},
        }

        result = metadata_resolution.resolve_detail_metadata(
            self.user,
            item=item,
            route_media_type=MediaTypes.MOVIE.value,
            media_id=item.media_id,
            source=item.source,
            base_metadata=base_metadata,
        )

        self.assertEqual(result.display_provider, Sources.MANUAL.value)
        self.assertEqual(result.identity_provider, Sources.TMDB.value)
        self.assertEqual(result.mapping_status, "custom")
        self.assertEqual(result.provider_media_id, f"item:{item.id}")
        self.assertEqual(result.header_metadata["title"], "The Matrix (Custom)")
        self.assertEqual(
            result.header_metadata["synopsis"],
            "Custom synopsis.",
        )
        self.assertEqual(
            result.header_metadata["details"]["release_date"],
            "1999-03-31",
        )
        self.assertEqual(
            result.header_metadata["details"]["status"],
            "Released",
        )
        self.assertEqual(
            result.header_metadata["related"],
            {"recommendations": [{"media_id": "604"}]},
        )

    @override_settings(TVDB_API_KEY="test-tvdb-key")
    @patch("app.services.metadata_resolution.anime_mapping.resolve_provider_series_id")
    def test_resolve_provider_media_id_maps_flat_anime_via_mapping_fallback(
        self,
        mock_resolve_provider_series_id,
    ):
        """Flat MAL anime should persist a provider link when grouped mapping exists."""
        item = Item.objects.create(
            media_id="52991",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Frieren",
            image="https://example.com/frieren.jpg",
        )
        mock_resolve_provider_series_id.return_value = "9350138"

        provider_media_id = metadata_resolution.resolve_provider_media_id(
            item,
            Sources.TVDB.value,
            route_media_type=MediaTypes.ANIME.value,
        )

        self.assertEqual(provider_media_id, "9350138")
        self.assertTrue(
            ItemProviderLink.objects.filter(
                item=item,
                provider=Sources.TVDB.value,
                provider_media_id="9350138",
                provider_media_type=MediaTypes.TV.value,
            ).exists(),
        )

    @patch("app.providers.tmdb.find")
    @patch("app.services.metadata_resolution.anime_mapping.resolve_provider_id")
    def test_resolve_provider_media_id_maps_mal_to_tmdb_via_tvdb(
        self,
        mock_resolve_provider_id,
        mock_tmdb_find,
    ):
        """MAL anime should reuse exact TVDB IDs for TMDB resolution."""
        item = Item.objects.create(
            media_id="52991",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Frieren",
        )
        mock_resolve_provider_id.side_effect = lambda _mal_id, provider, **_kwargs: (
            "407407" if provider == Sources.TVDB.value else None
        )
        mock_tmdb_find.return_value = {"tv_results": [{"id": 209867}]}

        provider_media_id = metadata_resolution.resolve_provider_media_id(
            item,
            Sources.TMDB.value,
            route_media_type=MediaTypes.ANIME.value,
        )

        self.assertEqual(provider_media_id, "209867")
        mock_tmdb_find.assert_called_once_with("407407", "tvdb_id")
        item.refresh_from_db()
        self.assertEqual(item.provider_external_ids["tvdb_id"], "407407")
        self.assertEqual(item.provider_external_ids["tmdb_id"], "209867")
        self.assertTrue(
            ItemProviderLink.objects.filter(
                item=item,
                provider=Sources.TMDB.value,
                provider_media_id="209867",
                provider_media_type=MediaTypes.TV.value,
            ).exists(),
        )

    @patch("app.providers.tmdb.find")
    @patch("app.services.metadata_resolution.anime_mapping.resolve_provider_id")
    def test_resolve_provider_media_id_rejects_ambiguous_tvdb_lookup(
        self,
        mock_resolve_provider_id,
        mock_tmdb_find,
    ):
        """An ambiguous external-ID response must not persist a guessed TMDB ID."""
        item = Item.objects.create(
            media_id="52991",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Frieren",
        )
        mock_resolve_provider_id.side_effect = lambda _mal_id, provider, **_kwargs: (
            "407407" if provider == Sources.TVDB.value else None
        )
        mock_tmdb_find.return_value = {"tv_results": [{"id": 1}, {"id": 2}]}

        provider_media_id = metadata_resolution.resolve_provider_media_id(
            item,
            Sources.TMDB.value,
            route_media_type=MediaTypes.ANIME.value,
        )

        self.assertIsNone(provider_media_id)
        self.assertFalse(
            ItemProviderLink.objects.filter(
                item=item,
                provider=Sources.TMDB.value,
            ).exists(),
        )

    @patch("app.providers.tmdb.find")
    @patch("app.services.metadata_resolution.anime_mapping.resolve_provider_id")
    def test_resolve_provider_media_id_tolerates_tmdb_lookup_failure(
        self,
        mock_resolve_provider_id,
        mock_tmdb_find,
    ):
        """Provider enrichment must not make a MAL detail page unavailable."""
        item = Item.objects.create(
            media_id="52991",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Frieren",
        )
        mock_resolve_provider_id.side_effect = lambda _mal_id, provider, **_kwargs: (
            "407407" if provider == Sources.TVDB.value else None
        )
        mock_tmdb_find.side_effect = metadata_resolution.services.ProviderAPIError(
            Sources.TMDB.value,
            RuntimeError("offline"),
        )

        provider_media_id = metadata_resolution.resolve_provider_media_id(
            item,
            Sources.TMDB.value,
            route_media_type=MediaTypes.ANIME.value,
        )

        self.assertIsNone(provider_media_id)

    @patch("app.providers.tmdb.find")
    @patch("app.services.metadata_resolution.anime_mapping.resolve_provider_id")
    def test_resolve_mal_tmdb_identity_maps_movie_via_imdb(
        self,
        mock_resolve_provider_id,
        mock_tmdb_find,
    ):
        mock_resolve_provider_id.side_effect = lambda _mal_id, provider, **_kwargs: (
            "tt0245429" if provider == Sources.IMDB.value else None
        )
        mock_tmdb_find.return_value = {"movie_results": [{"id": 129}]}

        identity = metadata_resolution.resolve_mal_tmdb_identity("199")

        self.assertEqual(
            identity,
            metadata_resolution.AnimeTMDBIdentity(
                media_id="129",
                media_type=MediaTypes.MOVIE.value,
                imdb_id="tt0245429",
            ),
        )
        mock_tmdb_find.assert_called_once_with("tt0245429", "imdb_id")

        item = Item.objects.create(
            media_id="199",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Spirited Away",
        )
        metadata_resolution.persist_mal_tmdb_identity(item, identity)
        self.assertIsNone(
            metadata_resolution.resolve_provider_media_id(
                item,
                Sources.TMDB.value,
                route_media_type=MediaTypes.ANIME.value,
            ),
        )
        self.assertTrue(
            ItemProviderLink.objects.filter(
                item=item,
                provider=Sources.TMDB.value,
                provider_media_id="129",
                provider_media_type=MediaTypes.MOVIE.value,
            ).exists(),
        )

    @override_settings(TVDB_API_KEY="test-tvdb-key")
    @patch("app.services.metadata_resolution.services.get_media_metadata")
    def test_resolve_detail_metadata_adds_grouped_preview_target_for_flat_mal_anime(
        self,
        mock_get_media_metadata,
    ):
        """Flat MAL anime preview should expose the grouped season and episode range."""
        item = Item.objects.create(
            media_id="52991",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Frieren",
            image="https://example.com/frieren.jpg",
        )
        MetadataProviderPreference.objects.create(
            user=self.user,
            item=item,
            provider=Sources.TVDB.value,
        )
        base_metadata = {
            "media_id": "52991",
            "source": Sources.MAL.value,
            "media_type": MediaTypes.ANIME.value,
            "title": "Frieren",
            "image": "https://example.com/frieren.jpg",
            "details": {"episodes": 28},
            "related": {},
        }
        mock_get_media_metadata.side_effect = [
            {
                "media_id": "9350138",
                "source": Sources.TVDB.value,
                "media_type": MediaTypes.ANIME.value,
                "title": "Frieren: Beyond Journey's End",
                "related": {"seasons": [{"season_number": 1}]},
                "external_links": {},
            },
            {
                "media_id": "9350138",
                "source": Sources.TVDB.value,
                "media_type": MediaTypes.ANIME.value,
                "title": "Frieren: Beyond Journey's End",
                "related": {
                    "seasons": [
                        {
                            "season_number": 1,
                            "episode_count": 28,
                        },
                    ],
                },
                "season/1": {
                    "season_number": 1,
                    "season_title": "Season 1",
                    "details": {"episodes": 28},
                },
            },
        ]

        result = metadata_resolution.resolve_detail_metadata(
            self.user,
            item=item,
            route_media_type=MediaTypes.ANIME.value,
            media_id=item.media_id,
            source=item.source,
            base_metadata=base_metadata,
        )

        self.assertEqual(result.mapping_status, "mapped")
        self.assertEqual(
            result.grouped_preview_target,
            {
                "season_number": 1,
                "episode_offset": 0,
                "episode_total": 28,
                "episode_start": 1,
                "episode_end": 28,
                "season_title": "Season 1",
                "season_episode_count": 28,
                "first_air_date": None,
            },
        )
        self.assertTrue(
            result.grouped_preview["related"]["seasons"][0]["is_mapped_target"]
        )
        self.assertEqual(
            result.grouped_preview["related"]["seasons"][0]["mapped_episode_start"],
            1,
        )
        self.assertEqual(
            result.grouped_preview["related"]["seasons"][0]["mapped_episode_end"],
            28,
        )

    @patch("app.services.metadata_resolution.anime_mapping.find_entries_for_mal_id")
    @patch("app.services.metadata_resolution.services.get_media_metadata")
    def test_resolve_detail_metadata_grouped_preview_target_falls_back_to_tvdb_mapping_for_tmdb(
        self,
        mock_get_media_metadata,
        mock_find_entries,
    ):
        """TMDB display should still get a grouped target from a TVDB-only mapping entry.

        Community mapping data (Kometa Anime-IDs) is TVDB-first: most entries carry
        a tvdb_id/tvdb_season but no tmdb_*id field at all. Requiring an exact
        provider-ID match on the entry meant picking TMDB as the display provider
        could never produce a grouped_preview_target for those titles, so the
        episode-cards section silently rendered nothing (#reported: "no episode
        cards" after mapping MAL -> TMDB).
        """
        item = Item.objects.create(
            media_id="31964",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="My Hero Academia",
            image="https://example.com/mha.jpg",
            provider_external_ids={"tmdb_id": "65930"},
        )
        MetadataProviderPreference.objects.create(
            user=self.user,
            item=item,
            provider=Sources.TMDB.value,
        )
        mock_find_entries.return_value = [
            {"tvdb_id": "305074", "tvdb_season": 1, "tvdb_epoffset": 0},
        ]
        base_metadata = {
            "media_id": "31964",
            "source": Sources.MAL.value,
            "media_type": MediaTypes.ANIME.value,
            "title": "My Hero Academia",
            "image": "https://example.com/mha.jpg",
            "details": {"episodes": 13},
            "related": {},
        }
        mock_get_media_metadata.side_effect = [
            {
                "media_id": "65930",
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.ANIME.value,
                "title": "My Hero Academia",
                "related": {"seasons": [{"season_number": 1}]},
                "external_links": {},
            },
            {
                "media_id": "65930",
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.ANIME.value,
                "title": "My Hero Academia",
                "related": {
                    "seasons": [{"season_number": 1, "episode_count": 13}],
                },
                "season/1": {
                    "season_number": 1,
                    "season_title": "Season 1",
                    "details": {"episodes": 13},
                },
            },
        ]

        result = metadata_resolution.resolve_detail_metadata(
            self.user,
            item=item,
            route_media_type=MediaTypes.ANIME.value,
            media_id=item.media_id,
            source=item.source,
            base_metadata=base_metadata,
        )

        self.assertEqual(result.mapping_status, "mapped")
        self.assertIsNotNone(result.grouped_preview_target)
        self.assertEqual(result.grouped_preview_target["season_number"], 1)
        self.assertEqual(result.grouped_preview_target["episode_start"], 1)
        self.assertEqual(result.grouped_preview_target["episode_end"], 13)

    @patch("app.db_retry.time.sleep")
    @patch("app.services.metadata_resolution.ItemProviderLink.objects.update_or_create")
    def test_resolve_detail_metadata_best_effort_keeps_identity_payload_on_lock(
        self,
        mock_update_or_create,
        _mock_sleep,
    ):
        """Identity-provider detail reads should render even if link persistence locks."""
        item = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Breaking Bad",
            image="https://example.com/breaking-bad.jpg",
        )
        mock_update_or_create.side_effect = OperationalError("database is locked")

        result = metadata_resolution.resolve_detail_metadata(
            self.user,
            item=item,
            route_media_type=MediaTypes.TV.value,
            media_id=item.media_id,
            source=item.source,
            base_metadata={
                "media_id": "1396",
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.TV.value,
                "title": "Breaking Bad",
                "image": "https://example.com/breaking-bad.jpg",
                "details": {"episodes": 62},
                "related": {},
            },
            persistence_mode="best_effort",
        )

        self.assertEqual(result.display_provider, Sources.TMDB.value)
        self.assertEqual(result.mapping_status, "identity")
        self.assertEqual(result.header_metadata["title"], "Breaking Bad")
        self.assertEqual(mock_update_or_create.call_count, 12)

    @override_settings(TVDB_API_KEY="test-tvdb-key")
    @patch("app.db_retry.time.sleep")
    @patch("app.services.metadata_resolution.anime_mapping.resolve_provider_series_id")
    @patch("app.services.metadata_resolution.ItemProviderLink.objects.update_or_create")
    def test_resolve_provider_media_id_best_effort_returns_mapping_on_lock(
        self,
        mock_update_or_create,
        mock_resolve_provider_series_id,
        _mock_sleep,
    ):
        """Grouped-anime mapping should still resolve even when link writes defer."""
        item = Item.objects.create(
            media_id="52991",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Frieren",
            image="https://example.com/frieren.jpg",
        )
        mock_resolve_provider_series_id.return_value = "9350138"
        mock_update_or_create.side_effect = OperationalError("database is locked")

        provider_media_id = metadata_resolution.resolve_provider_media_id(
            item,
            Sources.TVDB.value,
            route_media_type=MediaTypes.ANIME.value,
            persistence_mode="best_effort",
        )

        self.assertEqual(provider_media_id, "9350138")
        self.assertFalse(
            ItemProviderLink.objects.filter(
                item=item,
                provider=Sources.TVDB.value,
                provider_media_id="9350138",
                provider_media_type=MediaTypes.TV.value,
            ).exists(),
        )
        self.assertEqual(mock_update_or_create.call_count, 6)

    @patch("app.db_retry.time.sleep")
    @patch("app.services.metadata_resolution.ItemProviderLink.objects.update_or_create")
    def test_upsert_provider_links_required_mode_raises_on_lock(
        self,
        mock_update_or_create,
        _mock_sleep,
    ):
        """Required persistence should still raise after bounded retries."""
        item = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Breaking Bad",
            image="https://example.com/breaking-bad.jpg",
        )
        mock_update_or_create.side_effect = OperationalError("database is locked")

        with self.assertRaises(OperationalError):
            metadata_resolution.upsert_provider_links(
                item,
                {
                    "media_id": "1396",
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.TV.value,
                    "title": "Breaking Bad",
                    "image": "https://example.com/breaking-bad.jpg",
                },
                provider=Sources.TMDB.value,
                provider_media_type=MediaTypes.TV.value,
            )

        self.assertEqual(mock_update_or_create.call_count, 6)


class GetOrCreateTrackedSeasonItemTests(TestCase):
    """Regression tests for issue #326: duplicate Season Items.

    Covers get_or_create_tracked_season_item's provider-link-first
    resolution and its self-healing of stray duplicate Season Items that
    differ only in library_media_type.
    """

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="dexter-watcher",
            password="pw12345",
        )
        self.tv_item = Item.objects.create(
            media_id="1405",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Dexter",
            image="https://example.com/dexter.jpg",
        )
        self.tv_instance = TV.objects.create(
            item=self.tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

    def test_resolves_via_existing_provider_link_regardless_of_bucket(self):
        """An existing ItemProviderLink wins over any caller-supplied bucket."""
        canonical = Item.objects.create(
            media_id="1405",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=3,
            library_media_type=MediaTypes.SEASON.value,
            title="Dexter",
            image="",
        )
        ItemProviderLink.objects.create(
            item=canonical,
            provider=Sources.TMDB.value,
            provider_media_type=MediaTypes.SEASON.value,
            provider_media_id="1405",
            season_number=3,
        )

        resolved = metadata_resolution.get_or_create_tracked_season_item(
            "1405",
            Sources.TMDB.value,
            3,
            # Deliberately wrong bucket — the provider link must still win.
            library_media_type=MediaTypes.ANIME.value,
        )

        self.assertEqual(resolved.pk, canonical.pk)
        self.assertFalse(
            Item.objects.filter(
                media_id="1405",
                media_type=MediaTypes.SEASON.value,
                season_number=3,
                library_media_type=MediaTypes.ANIME.value,
            ).exists(),
        )

    def test_falls_back_to_bucket_scoped_lookup_when_no_link(self):
        """With no provider link yet, resolution is scoped by the caller's bucket."""
        season_bucket_item = Item.objects.create(
            media_id="1405",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=3,
            library_media_type=MediaTypes.SEASON.value,
            title="Dexter",
            image="",
        )
        anime_bucket_item = Item.objects.create(
            media_id="1405",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=3,
            library_media_type=MediaTypes.ANIME.value,
            title="Dexter",
            image="",
        )

        resolved = metadata_resolution.get_or_create_tracked_season_item(
            "1405",
            Sources.TMDB.value,
            3,
            library_media_type=MediaTypes.SEASON.value,
        )

        self.assertEqual(resolved.pk, season_bucket_item.pk)
        # The mismatched-bucket sibling is self-healed away (it was orphaned).
        self.assertFalse(Item.objects.filter(pk=anime_bucket_item.pk).exists())

    def test_dexter_reproduction_heals_orphaned_stray_and_prevents_conflict(self):
        """Reproduces the exact issue #326 shape.

        A canonical Item with a real provider link and tracking data, plus
        an orphaned stray Item in a different bucket. Resolution must return
        the canonical item, delete the stray, and a subsequent
        provider-link write must not raise/log a persistent-conflict
        warning.
        """
        canonical = Item.objects.create(
            media_id="1405",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=3,
            library_media_type=MediaTypes.SEASON.value,
            title="Dexter",
            image="",
        )
        ItemProviderLink.objects.create(
            item=canonical,
            provider=Sources.TMDB.value,
            provider_media_type=MediaTypes.SEASON.value,
            provider_media_id="1405",
            season_number=3,
        )
        Season.objects.create(
            item=canonical,
            user=self.user,
            related_tv=self.tv_instance,
            status=Status.IN_PROGRESS.value,
        )
        stray = Item.objects.create(
            media_id="1405",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=3,
            library_media_type=MediaTypes.ANIME.value,
            title="Dexter",
            image="",
        )

        with self.assertNoLogs("app.db_retry", level="WARNING"):
            resolved = metadata_resolution.get_or_create_tracked_season_item(
                "1405",
                Sources.TMDB.value,
                3,
                library_media_type=MediaTypes.SEASON.value,
                metadata={
                    "media_id": "1405",
                    "provider_external_ids": {"tmdb_id": "1405"},
                },
            )

        self.assertEqual(resolved.pk, canonical.pk)
        self.assertFalse(Item.objects.filter(pk=stray.pk).exists())
        self.assertEqual(
            Item.objects.filter(
                media_id="1405",
                media_type=MediaTypes.SEASON.value,
                season_number=3,
            ).count(),
            1,
        )

    def test_merge_with_progress_preserves_episode_data(self):
        """A stray's tracking data must be preserved, not lost, on merge.

        Its Season/Episode data must be migrated onto the canonical Season
        before the stray is removed — no watch history should be lost.
        """
        canonical = Item.objects.create(
            media_id="1405",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=3,
            library_media_type=MediaTypes.SEASON.value,
            title="Dexter",
            image="",
        )
        ItemProviderLink.objects.create(
            item=canonical,
            provider=Sources.TMDB.value,
            provider_media_type=MediaTypes.SEASON.value,
            provider_media_id="1405",
            season_number=3,
        )
        canonical_season = Season.objects.create(
            item=canonical,
            user=self.user,
            related_tv=self.tv_instance,
            status=Status.IN_PROGRESS.value,
        )
        canonical_ep1_item = Item.objects.create(
            media_id="1405",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=3,
            episode_number=1,
            library_media_type=MediaTypes.EPISODE.value,
            title="Dexter",
            image="",
        )
        Episode.objects.create(
            item=canonical_ep1_item,
            related_season=canonical_season,
            end_date=timezone.now() - timedelta(days=2),
        )

        stray = Item.objects.create(
            media_id="1405",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=3,
            library_media_type=MediaTypes.ANIME.value,
            title="Dexter",
            image="",
        )
        stray_season = Season.objects.create(
            item=stray,
            user=self.user,
            related_tv=self.tv_instance,
            status=Status.IN_PROGRESS.value,
        )
        # Episode 1 on the stray has a MORE RECENT end_date — should win.
        stray_ep1_item = Item.objects.create(
            media_id="1405",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=3,
            episode_number=1,
            library_media_type=MediaTypes.ANIME.value,
            title="Dexter",
            image="",
        )
        newer_end_date = timezone.now()
        Episode.objects.create(
            item=stray_ep1_item,
            related_season=stray_season,
            end_date=newer_end_date,
        )
        # Episode 2 only exists on the stray — must be preserved via repoint.
        stray_ep2_item = Item.objects.create(
            media_id="1405",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=3,
            episode_number=2,
            library_media_type=MediaTypes.ANIME.value,
            title="Dexter",
            image="",
        )
        Episode.objects.create(
            item=stray_ep2_item,
            related_season=stray_season,
            end_date=timezone.now() - timedelta(days=1),
        )

        resolved = metadata_resolution.get_or_create_tracked_season_item(
            "1405",
            Sources.TMDB.value,
            3,
            library_media_type=MediaTypes.SEASON.value,
        )

        self.assertEqual(resolved.pk, canonical.pk)
        self.assertFalse(Item.objects.filter(pk=stray.pk).exists())
        self.assertFalse(Season.objects.filter(pk=stray_season.pk).exists())

        canonical_season.refresh_from_db()
        episodes = Episode.objects.filter(related_season=canonical_season)
        self.assertEqual(episodes.count(), 2)
        ep1 = episodes.get(item__episode_number=1)
        self.assertEqual(ep1.end_date, newer_end_date)
        self.assertTrue(episodes.filter(item__episode_number=2).exists())

    def test_never_raises_when_merge_hits_unexpected_error(self):
        """A failure mid-merge must not propagate.

        The canonical item is still returned and the duplicate is left in
        place for next time.
        """
        canonical = Item.objects.create(
            media_id="1405",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=3,
            library_media_type=MediaTypes.SEASON.value,
            title="Dexter",
            image="",
        )
        ItemProviderLink.objects.create(
            item=canonical,
            provider=Sources.TMDB.value,
            provider_media_type=MediaTypes.SEASON.value,
            provider_media_id="1405",
            season_number=3,
        )
        Item.objects.create(
            media_id="1405",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=3,
            library_media_type=MediaTypes.ANIME.value,
            title="Dexter",
            image="",
        )

        with patch.object(
            metadata_resolution,
            "_merge_stray_season_item",
            side_effect=RuntimeError("boom"),
        ):
            resolved = metadata_resolution.get_or_create_tracked_season_item(
                "1405",
                Sources.TMDB.value,
                3,
                library_media_type=MediaTypes.SEASON.value,
            )

        self.assertEqual(resolved.pk, canonical.pk)


class FindTrackedSeasonTests(TestCase):
    """Regression tests for issue #623: cross-identity Season lookup.

    find_tracked_season must find a tracked Season regardless of which
    Item.library_media_type bucket it's attached to, since read (season
    detail page) and write (media_save) paths must agree on "the" tracked
    season for a show/season/user.
    """

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="naruto-watcher",
            password="pw12345",
        )

    def test_returns_none_when_no_season_tracked(self):
        resolved = metadata_resolution.find_tracked_season(
            self.user,
            "79824",
            Sources.TVDB.value,
            0,
        )
        self.assertIsNone(resolved)

    def test_finds_season_tracked_via_other_bucket(self):
        """A season tracked under the TV-identity bucket is still found from the anime route."""
        tv_item = Item.objects.create(
            media_id="79824",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            title="Naruto Shippuden",
            image="",
            library_media_type=MediaTypes.TV.value,
        )
        tv_instance = TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        season_item = Item.objects.create(
            media_id="79824",
            source=Sources.TVDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=0,
            title="Naruto Shippuden",
            image="",
            library_media_type=MediaTypes.TV.value,
        )
        season = Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=tv_instance,
            status=Status.COMPLETED.value,
        )

        resolved = metadata_resolution.find_tracked_season(
            self.user,
            "79824",
            Sources.TVDB.value,
            0,
            library_media_type=MediaTypes.ANIME.value,
        )

        self.assertEqual(resolved.pk, season.pk)

    def test_prefers_exact_bucket_match_over_other_bucket(self):
        """When both buckets have a tracked row, the requested bucket wins."""
        tv_item = Item.objects.create(
            media_id="79824",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            title="Naruto Shippuden",
            image="",
            library_media_type=MediaTypes.TV.value,
        )
        tv_instance = TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        tv_bucket_season_item = Item.objects.create(
            media_id="79824",
            source=Sources.TVDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=0,
            title="Naruto Shippuden",
            image="",
            library_media_type=MediaTypes.TV.value,
        )
        Season.objects.create(
            item=tv_bucket_season_item,
            user=self.user,
            related_tv=tv_instance,
            status=Status.IN_PROGRESS.value,
        )

        anime_tv_item = Item.objects.create(
            media_id="79824",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            title="Naruto Shippuden",
            image="",
            library_media_type=MediaTypes.ANIME.value,
        )
        anime_tv_instance = TV.objects.create(
            item=anime_tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        anime_bucket_season_item = Item.objects.create(
            media_id="79824",
            source=Sources.TVDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=0,
            title="Naruto Shippuden",
            image="",
            library_media_type=MediaTypes.ANIME.value,
        )
        anime_season = Season.objects.create(
            item=anime_bucket_season_item,
            user=self.user,
            related_tv=anime_tv_instance,
            status=Status.COMPLETED.value,
        )

        resolved = metadata_resolution.find_tracked_season(
            self.user,
            "79824",
            Sources.TVDB.value,
            0,
            library_media_type=MediaTypes.ANIME.value,
        )

        self.assertEqual(resolved.pk, anime_season.pk)


class FindExistingAnimeHomeTests(TestCase):
    """Sticky anime routing, shared by webhooks and importers.

    `ItemProviderLink` is global by design - it caches a content fact, not user
    state - so the link lookup is unscoped while the tracking lookup must not
    be. Getting that boundary wrong routes one user's import by another user's
    library.
    """

    def setUp(self):
        """Create two users and one TMDB-identified show."""
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="anime-home-user",
            password="password",
        )
        self.other = get_user_model().objects.create_user(
            username="anime-home-other",
            password="password",
        )

    def _grouped_item(self):
        return Item.objects.create(
            media_id="209867",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.ANIME.value,
            title="Frieren: Beyond Journey's End",
            image="",
        )

    def _flat_item(self):
        item = Item.objects.create(
            media_id="52991",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Frieren: Beyond Journey's End",
            image="",
        )
        ItemProviderLink.objects.create(
            item=item,
            provider=Sources.TMDB.value,
            provider_media_type=MediaTypes.TV.value,
            provider_media_id="209867",
            episode_offset=0,
        )
        return item

    def test_returns_none_without_any_identity(self):
        """No TMDB or TVDB id means there is nothing to match on."""
        self.assertIsNone(
            metadata_resolution.find_existing_anime_home(self.user),
        )

    def test_finds_a_grouped_home(self):
        """A tracked anime-bucket TV row is a grouped home."""
        item = self._grouped_item()
        TV.objects.create(item=item, user=self.user, status=Status.IN_PROGRESS.value)

        self.assertEqual(
            metadata_resolution.find_existing_anime_home(self.user, tmdb_id="209867"),
            ("grouped", item),
        )

    def test_finds_a_flat_home_through_its_provider_link(self):
        """A tracked MAL row linked to this show is a flat home."""
        from app.models import Anime

        item = self._flat_item()
        Anime.objects.create(
            item=item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
            progress=1,
        )

        self.assertEqual(
            metadata_resolution.find_existing_anime_home(self.user, tmdb_id="209867"),
            ("flat", item),
        )

    def test_grouped_wins_when_both_shapes_exist(self):
        """A grouped home is the TV-shaped one; prefer it over a flat row."""
        from app.models import Anime

        grouped = self._grouped_item()
        TV.objects.create(
            item=grouped,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        flat = self._flat_item()
        Anime.objects.create(
            item=flat,
            user=self.user,
            status=Status.IN_PROGRESS.value,
            progress=1,
        )

        self.assertEqual(
            metadata_resolution.find_existing_anime_home(self.user, tmdb_id="209867"),
            ("grouped", grouped),
        )

    def test_another_users_library_does_not_route_this_user(self):
        """Tracking is per user even though the link table is shared."""
        item = self._grouped_item()
        TV.objects.create(item=item, user=self.other, status=Status.IN_PROGRESS.value)

        self.assertIsNone(
            metadata_resolution.find_existing_anime_home(self.user, tmdb_id="209867"),
        )

    def test_an_untracked_item_is_not_a_home(self):
        """An Item nobody tracks is not anybody's library."""
        self._grouped_item()

        self.assertIsNone(
            metadata_resolution.find_existing_anime_home(self.user, tmdb_id="209867"),
        )

    def test_matches_on_tvdb_identity_too(self):
        """A TVDB-sourced grouped row is found by its TVDB id."""
        item = Item.objects.create(
            media_id="424536",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.ANIME.value,
            title="Frieren: Beyond Journey's End",
            image="",
        )
        TV.objects.create(item=item, user=self.user, status=Status.IN_PROGRESS.value)

        self.assertEqual(
            metadata_resolution.find_existing_anime_home(
                self.user,
                tvdb_id="424536",
            ),
            ("grouped", item),
        )


class PrefersGroupedAnimeTests(TestCase):
    """Storage shape follows the user's Anime Provider."""

    def setUp(self):
        """Create a user with anime enabled."""
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="prefers-grouped-user",
            password="password",
        )

    def test_provider_decides_the_shape(self):
        """TMDB and TVDB mean grouped rows; MAL means flat rows."""
        cases = [
            (Sources.TMDB.value, True),
            (Sources.TVDB.value, True),
            (Sources.MAL.value, False),
        ]
        for provider, expected in cases:
            with self.subTest(provider=provider):
                self.user.anime_metadata_source_default = provider
                self.user.save(update_fields=["anime_metadata_source_default"])
                self.assertIs(
                    metadata_resolution.prefers_grouped_anime(self.user),
                    expected,
                )

    def test_disabled_anime_library_never_prefers_grouped(self):
        """With the Anime library off there is no grouped anime to prefer."""
        self.user.anime_enabled = False
        self.user.anime_metadata_source_default = Sources.TMDB.value
        self.user.save(
            update_fields=["anime_enabled", "anime_metadata_source_default"],
        )

        self.assertFalse(metadata_resolution.prefers_grouped_anime(self.user))
