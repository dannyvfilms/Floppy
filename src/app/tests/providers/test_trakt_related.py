from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from app.models import MediaTypes
from app.providers import trakt


class TraktRelatedRecommendationsTests(TestCase):
    def setUp(self):
        cache.clear()

    @patch("app.providers.trakt.services.api_request")
    @patch("app.providers.trakt.credentials.get", return_value="")
    def test_no_client_id_skips_requests(self, _get_credential, mock_request):
        self.assertEqual(trakt.related_recommendations(MediaTypes.MOVIE.value, "238"), [])
        mock_request.assert_not_called()

    @patch("app.providers.trakt.services.api_request")
    @patch("app.providers.trakt.credentials.get", return_value="client-id")
    def test_resolves_tmdb_identity_and_normalizes_related_titles(
        self, _get_credential, mock_request
    ):
        mock_request.side_effect = [
            [
                {
                    "movie": {
                        "title": "Test Movie",
                        "ids": {"trakt": 4740, "tmdb": 238},
                    }
                }
            ],
            [
                {
                    "title": "Caligula",
                    "year": 1979,
                    "certification": "NC-17",
                    "ids": {"trakt": 4740, "tmdb": 9453},
                    "images": {"poster": ["media.trakt.tv/movies/4740/medium/poster.webp"]},
                },
                {
                    "title": "Another Movie",
                    "year": 2020,
                    "ids": {"trakt": 5000, "tmdb": 10277},
                    "images": {
                        "poster": [
                            "walter-r2.trakt.tv/images/movies/000/042/897/"
                            "posters/medium/poster.webp"
                        ]
                    },
                },
                {
                    "title": "No TMDB mapping",
                    "ids": {"trakt": 9000},
                },
            ],
        ]

        result = trakt.related_recommendations(MediaTypes.MOVIE.value, "238")

        self.assertEqual(
            result,
            [
                {
                    "source": "tmdb",
                    "media_type": "movie",
                    "media_id": "9453",
                    "title": "Caligula",
                    "image": "https://media.trakt.tv/movies/4740/medium/poster.webp",
                    "year": 1979,
                    "certification": "NC-17",
                    "trakt_id": "4740",
                },
                {
                    "source": "tmdb",
                    "media_type": "movie",
                    "media_id": "10277",
                    "title": "Another Movie",
                    "image": "https://walter-r2.trakt.tv/images/movies/000/042/897/"
                    "posters/medium/poster.webp",
                    "year": 2020,
                    "certification": None,
                    "trakt_id": "5000",
                },
            ],
        )
        self.assertEqual(mock_request.call_count, 2)
        self.assertEqual(
            mock_request.call_args_list[1].kwargs["params"],
            {"extended": "full", "page": 1, "limit": trakt.RELATED_RECOMMENDATIONS_LIMIT},
        )
        self.assertEqual(
            mock_request.call_args_list[1].args[2],
            "https://api.trakt.tv/movies/4740/related",
        )

        trakt.related_recommendations(MediaTypes.MOVIE.value, "238")
        self.assertEqual(mock_request.call_count, 2)
