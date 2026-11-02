"""TMDB movie payloads must carry the external IDs TMDB already returns.

`movie()` requested `external_ids` but spent them only on detail-page links, so
`metadata_resolution` never saw an `imdb_id` for a movie and the Stremio catalog
and IMDb rating sync skipped every one of them (issue #1066).
"""

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from app.models import Item, MediaTypes, Sources
from app.providers import tmdb
from app.services import metadata_resolution

MOVIE_RESPONSE = {
    "id": 550,
    "title": "Fight Club",
    "overview": "An insomniac office worker.",
    "release_date": "1999-10-15",
    "status": "Released",
    "runtime": 139,
    "poster_path": "/poster.jpg",
    "genres": [{"name": "Drama"}],
    "vote_average": 8.4,
    "vote_count": 27000,
    "popularity": 61.4,
    "production_companies": [],
    "production_countries": [],
    "spoken_languages": [],
    "belongs_to_collection": None,
    "external_ids": {
        "imdb_id": "tt0137523",
        "wikidata_id": "Q190050",
        "facebook_id": None,
    },
}


class TMDBMovieExternalIDTests(TestCase):
    """The movie payload should expose external IDs for persistence."""

    def setUp(self):
        cache.clear()

    @patch("app.providers.tmdb.services.api_request")
    def test_movie_emits_provider_external_ids(self, mock_api_request):
        """The IMDb ID TMDB returns should survive into the metadata dict."""
        mock_api_request.return_value = MOVIE_RESPONSE

        result = tmdb.movie("550")

        self.assertEqual(
            result["provider_external_ids"]["imdb_id"],
            "tt0137523",
        )
        self.assertEqual(
            result["provider_external_ids"]["wikidata_id"],
            "Q190050",
        )

    @patch("app.providers.tmdb.services.api_request")
    def test_movie_keeps_letterboxd_link(self, mock_api_request):
        """Movies pass media_id to get_external_links; TV deliberately doesn't."""
        mock_api_request.return_value = MOVIE_RESPONSE

        result = tmdb.movie("550")

        self.assertEqual(
            result["external_links"]["IMDb"],
            "https://www.imdb.com/title/tt0137523/",
        )
        self.assertIn("Letterboxd", result["external_links"])

    @patch("app.providers.tmdb.services.api_request")
    def test_movie_without_external_ids_returns_empty_mapping(self, mock_api_request):
        """A payload with no external_ids shouldn't blow up downstream callers."""
        mock_api_request.return_value = MOVIE_RESPONSE | {"external_ids": None}

        result = tmdb.movie("550")

        self.assertEqual(result["provider_external_ids"], {})
        self.assertNotIn("IMDb", result["external_links"])

    @patch("app.providers.tmdb.services.api_request")
    def test_movie_metadata_persists_imdb_id_onto_item(self, mock_api_request):
        """The end-to-end path the Stremio catalog and IMDb ratings depend on."""
        mock_api_request.return_value = MOVIE_RESPONSE
        item = Item.objects.create(
            media_id="550",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Fight Club",
            image="https://example.com/poster.jpg",
        )

        metadata_resolution.upsert_provider_links(
            item,
            tmdb.movie("550"),
            provider=Sources.TMDB.value,
            provider_media_type=MediaTypes.MOVIE.value,
        )

        item.refresh_from_db()
        self.assertEqual(item.provider_external_ids["imdb_id"], "tt0137523")
        self.assertEqual(item.provider_external_ids["tmdb_id"], "550")


class TMDBMovieCacheKeyTests(TestCase):
    """The versioned movie key must stay reachable from cache-clearing callers."""

    def test_movie_cache_key_carries_the_strategy_version(self):
        """Payloads cached before the fix lack the key and must not be reused."""
        key = tmdb._movie_cache_key("550")

        self.assertIn(f"v{tmdb.TMDB_MOVIE_CACHE_VERSION}", key)
        self.assertNotEqual(
            key,
            f"{Sources.TMDB.value}_{MediaTypes.MOVIE.value}_550",
        )

    def test_metadata_cache_keys_match_the_fetchers(self):
        """tasks_metadata_cache clears through here rather than rebuilding keys."""
        self.assertEqual(
            tmdb.metadata_cache_keys("550", MediaTypes.MOVIE.value),
            [tmdb._movie_cache_key("550")],
        )
        self.assertEqual(
            tmdb.metadata_cache_keys("1396", MediaTypes.TV.value),
            [tmdb._tv_cache_key("1396")],
        )
        self.assertEqual(
            tmdb.metadata_cache_keys("1396", MediaTypes.SEASON.value, season_number=1),
            [tmdb._season_cache_key("1396", 1)],
        )

    def test_clearing_item_metadata_cache_evicts_the_versioned_movie_key(self):
        """A hand-rolled key would silently miss the versioned one."""
        from app.tasks_metadata_cache import _clear_item_metadata_cache

        item = Item.objects.create(
            media_id="550",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Fight Club",
            image="https://example.com/poster.jpg",
        )
        cache.set(tmdb._movie_cache_key("550"), {"stale": True})

        _clear_item_metadata_cache(item)

        self.assertIsNone(cache.get(tmdb._movie_cache_key("550")))


class ProviderMetadataCacheKeyHelperTests(TestCase):
    """Refresh paths must reach the versioned key, not the legacy shape.

    A refresh that builds `source_mediatype_mediaid` by hand reads a TTL of
    None, deletes nothing, and is then served the very payload it meant to
    replace - reporting success without fetching anything (issue #1066).
    """

    def setUp(self):
        cache.clear()

    def test_tmdb_movie_keys_include_the_versioned_key_first(self):
        from app import metadata_utils

        keys = metadata_utils.provider_metadata_cache_keys(
            Sources.TMDB.value,
            MediaTypes.MOVIE.value,
            "550",
        )

        self.assertEqual(keys[0], tmdb._movie_cache_key("550"))
        self.assertIn(f"{Sources.TMDB.value}_{MediaTypes.MOVIE.value}_550", keys)

    def test_tmdb_season_keys_include_the_versioned_key(self):
        from app import metadata_utils

        keys = metadata_utils.provider_metadata_cache_keys(
            Sources.TMDB.value,
            MediaTypes.SEASON.value,
            "1396",
            season_number=1,
        )

        self.assertIn(tmdb._season_cache_key("1396", 1), keys)

    def test_deleting_the_returned_keys_evicts_a_cached_movie(self):
        from django.core.cache import cache as django_cache

        from app import metadata_utils

        django_cache.set(tmdb._movie_cache_key("550"), {"stale": True})

        django_cache.delete_many(
            metadata_utils.provider_metadata_cache_keys(
                Sources.TMDB.value,
                MediaTypes.MOVIE.value,
                "550",
            ),
        )

        self.assertIsNone(django_cache.get(tmdb._movie_cache_key("550")))

    def test_unknown_sources_fall_back_to_the_legacy_shape(self):
        from app import metadata_utils

        keys = metadata_utils.provider_metadata_cache_keys(
            Sources.MAL.value,
            MediaTypes.ANIME.value,
            "52991",
        )

        self.assertEqual(keys, [f"{Sources.MAL.value}_{MediaTypes.ANIME.value}_52991"])


class TMDBMovieBackdropSeedTests(TestCase):
    """A movie detail fetch records the backdrop TMDB already returned (#1249)."""

    def setUp(self):
        cache.clear()

    @patch("app.providers.tmdb.services.api_request")
    def test_movie_fetch_caches_its_backdrop(self, mock_api_request):
        from app import backdrops

        mock_api_request.return_value = MOVIE_RESPONSE | {
            "backdrop_path": "/fight-club.jpg",
        }

        tmdb.movie("550")

        item = {
            "source": Sources.TMDB.value,
            "media_type": MediaTypes.MOVIE.value,
            "media_id": "550",
        }
        self.assertEqual(
            backdrops.cached_backdrop(item),
            "https://image.tmdb.org/t/p/w1280/fight-club.jpg",
        )
        # One request: the backdrop rode along with the detail response.
        mock_api_request.assert_called_once()
