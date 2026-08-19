from unittest.mock import patch

from django.test import TestCase

from app.discover.providers.tmdb_adapter import TMDbDiscoverAdapter
from app.models import DiscoverApiCache, MediaTypes


class TMDbDiscoverAdapterTests(TestCase):
    """Tests for TMDb Discover adapter cache behavior."""

    def setUp(self):
        DiscoverApiCache.objects.all().delete()

    @patch("app.discover.providers.tmdb_adapter.services.api_request")
    def test_trending_uses_db_cache_after_first_fetch(self, mock_api_request):
        def _side_effect(_provider, _method, url, params=None):
            if url.endswith("/genre/movie/list"):
                return {"genres": [{"id": 28, "name": "Action"}]}
            if url.endswith("/trending/movie/day"):
                return {
                    "results": [
                        {
                            "id": 11,
                            "title": "Mock Movie",
                            "poster_path": "/poster.jpg",
                            "genre_ids": [28],
                            "popularity": 10.0,
                            "vote_average": 7.5,
                            "vote_count": 100,
                            "release_date": "2025-01-01",
                        },
                    ],
                }
            raise AssertionError(f"Unexpected URL called: {url}")

        mock_api_request.side_effect = _side_effect

        adapter = TMDbDiscoverAdapter()
        first = adapter.trending(MediaTypes.MOVIE.value, limit=10)
        second = adapter.trending(MediaTypes.MOVIE.value, limit=10)

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(first[0].title, "Mock Movie")
        self.assertEqual(mock_api_request.call_count, 2)

    def _movie_payload(self, movie_id: int, title: str) -> dict:
        return {
            "id": movie_id,
            "title": title,
            "poster_path": "/poster.jpg",
            "genre_ids": [28],
            "popularity": 10.0,
            "vote_average": 7.0,
            "vote_count": 500,
            "release_date": "2020-01-01",
        }

    @patch("app.discover.providers.tmdb_adapter.services.api_request")
    def test_related_movies_merges_similar_and_recommendations_across_pages(
        self,
        mock_api_request,
    ):
        calls: list[tuple[str, dict | None]] = []

        def _side_effect(_provider, _method, url, params=None):
            calls.append((url, params))
            if url.endswith("/genre/movie/list"):
                return {"genres": [{"id": 28, "name": "Action"}]}
            if url.endswith("/movie/42/similar"):
                if (params or {}).get("page") == 1:
                    return {
                        "page": 1,
                        "total_pages": 2,
                        "results": [
                            self._movie_payload(1, "Similar One"),
                            self._movie_payload(2, "Similar Two"),
                        ],
                    }
                return {
                    "page": 2,
                    "total_pages": 2,
                    "results": [self._movie_payload(3, "Similar Three")],
                }
            if url.endswith("/movie/42/recommendations"):
                if (params or {}).get("page") == 1:
                    return {
                        "page": 1,
                        "total_pages": 1,
                        "results": [
                            # Overlaps with a /similar result; must be deduped.
                            self._movie_payload(2, "Similar Two"),
                            self._movie_payload(4, "Recommended Four"),
                        ],
                    }
                return {"page": 2, "total_pages": 1, "results": []}
            raise AssertionError(f"Unexpected URL called: {url}")

        mock_api_request.side_effect = _side_effect

        adapter = TMDbDiscoverAdapter()
        results = adapter.related(MediaTypes.MOVIE.value, "42", limit=50)

        self.assertEqual(
            sorted(candidate.media_id for candidate in results),
            ["1", "2", "3", "4"],
        )
        similar_calls = [c for c in calls if c[0].endswith("/movie/42/similar")]
        recommendations_calls = [
            c for c in calls if c[0].endswith("/movie/42/recommendations")
        ]
        self.assertEqual(len(similar_calls), 2)
        self.assertEqual(len(recommendations_calls), 1)

    @patch("app.discover.providers.tmdb_adapter.services.api_request")
    def test_genre_discovery_paginates_and_dedupes(self, mock_api_request):
        def _side_effect(_provider, _method, url, params=None):
            if url.endswith("/genre/movie/list"):
                return {"genres": [{"id": 35, "name": "Comedy"}]}
            if url.endswith("/discover/movie"):
                if (params or {}).get("page") == 1:
                    return {
                        "page": 1,
                        "total_pages": 2,
                        "results": [
                            self._movie_payload(10, "Discover One"),
                            self._movie_payload(11, "Discover Two"),
                        ],
                    }
                return {
                    "page": 2,
                    "total_pages": 2,
                    "results": [self._movie_payload(12, "Discover Three")],
                }
            raise AssertionError(f"Unexpected URL called: {url}")

        mock_api_request.side_effect = _side_effect

        adapter = TMDbDiscoverAdapter()
        results = adapter.genre_discovery(
            MediaTypes.MOVIE.value,
            ["Comedy"],
            limit=50,
        )

        self.assertEqual(
            sorted(candidate.media_id for candidate in results),
            ["10", "11", "12"],
        )

    @patch("app.discover.providers.tmdb_adapter.services.api_request")
    def test_related_tv_still_uses_recommendations_only(self, mock_api_request):
        def _side_effect(_provider, _method, url, params=None):
            if url.endswith("/genre/tv/list"):
                return {"genres": [{"id": 28, "name": "Action"}]}
            if url.endswith("/tv/7/recommendations"):
                return {
                    "page": 1,
                    "total_pages": 1,
                    "results": [self._movie_payload(5, "Show One")],
                }
            raise AssertionError(f"Unexpected URL called: {url}")

        mock_api_request.side_effect = _side_effect

        adapter = TMDbDiscoverAdapter()
        results = adapter.related(MediaTypes.TV.value, "7", limit=50)

        self.assertEqual([candidate.media_id for candidate in results], ["5"])
