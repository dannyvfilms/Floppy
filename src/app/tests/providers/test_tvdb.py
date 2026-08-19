from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from app.models import MediaTypes, Sources
from app.providers import tvdb


class TVDBProviderTests(TestCase):
    """Tests for TVDB metadata normalization and caching."""

    def setUp(self):
        cache.clear()

    @override_settings(TVDB_API_KEY="test-tvdb-key", TVDB_PIN="1234")
    @patch("app.providers.tvdb.services.api_request")
    def test_get_token_caches_login_response(self, mock_api_request):
        """TVDB login should cache the bearer token between requests."""
        mock_api_request.return_value = {"data": {"token": "cached-token"}}

        first = tvdb._get_token()
        second = tvdb._get_token()

        self.assertEqual(first, "cached-token")
        self.assertEqual(second, "cached-token")
        mock_api_request.assert_called_once()

    @patch("app.providers.tvdb._request")
    def test_tv_normalizes_series_metadata(self, mock_request):
        """Series metadata should normalize title fields, links, and seasons."""
        mock_request.return_value = {
            "data": {
                "id": 81189,
                "name": {"language": "eng", "name": "Breaking Bad"},
                "originalName": {"language": "eng", "name": "Breaking Bad"},
                "overview": "Chemistry teacher becomes kingpin.",
                "firstAired": "2008-01-20",
                "lastAired": "2013-09-29",
                "numberOfEpisodes": 62,
                "averageRuntime": 47,
                "status": {"name": "Ended"},
                "siteRating": "9.5",
                "siteRatingCount": "1000",
                "score": 859244,
                "remoteIds": [
                    {"sourceName": "TheMovieDB.com", "id": "1396"},
                    {"sourceName": "IMDb", "id": "tt0903747"},
                ],
                "seasons": [
                    {
                        "id": 101,
                        "number": 0,
                        "name": "Specials",
                        "type": {"name": "Aired Order"},
                        "episodes": [],
                    },
                    {
                        "id": 102,
                        "number": 1,
                        "name": "Season 1",
                        "type": {"name": "Aired Order"},
                        "episodes": [
                            {"aired": "2008-01-20"},
                            {"aired": "2008-01-27"},
                        ],
                    },
                ],
                "genres": [{"name": "Drama"}],
                "characters": [],
            },
        }

        result = tvdb.tv("81189")

        self.assertEqual(result["title"], "Breaking Bad")
        self.assertEqual(result["tvdb_id"], "81189")
        self.assertEqual(result["provider_external_ids"]["tmdb_id"], "1396")
        self.assertEqual(result["provider_external_ids"]["imdb_id"], "tt0903747")
        self.assertEqual(result["details"]["status"], "Ended")
        self.assertEqual(result["details"]["episodes"], 62)
        self.assertEqual(result["score"], 9.5)
        self.assertEqual(result["score_count"], 1000)
        self.assertEqual(result["related"]["seasons"][0]["season_number"], 0)
        self.assertIn("episode_count", result["related"]["seasons"][0])
        self.assertIn("details", result["related"]["seasons"][0])

    @patch("app.providers.tvdb._request")
    def test_tv_with_seasons_reuses_cached_series_extended_payload(
        self,
        mock_request,
    ):
        """Series extended metadata should be fetched once across TVDB lookups."""
        mock_request.side_effect = [
            {
                "data": {
                    "id": 81189,
                    "name": "Breaking Bad",
                    "seasons": [
                        {
                            "id": 102,
                            "number": 1,
                            "name": "Season 1",
                            "type": {"name": "Aired Order"},
                        },
                    ],
                    "characters": [],
                },
            },
            {"data": {}},
            {
                "data": {
                    "id": 102,
                    "number": 1,
                    "name": "Season 1",
                    "type": {"name": "Aired Order"},
                    "episodes": [],
                },
            },
            {"data": {}},
        ]

        tvdb.tv("81189")
        tvdb.tv_with_seasons("81189", [1])
        tvdb.tv_with_seasons("81189", [1])

        requested_paths = [call.args[0] for call in mock_request.call_args_list]
        self.assertEqual(requested_paths.count("series/81189/extended"), 1)
        self.assertEqual(requested_paths.count("seasons/102/extended"), 1)

    @patch("app.providers.tvdb._request")
    def test_tv_uses_explicit_metadata_cache_timeout(self, mock_request):
        """Normalized series metadata should use the long-lived TVDB TTL."""
        mock_request.side_effect = [
            {
                "data": {
                    "id": 81189,
                    "name": "Breaking Bad",
                    "seasons": [],
                    "characters": [],
                },
            },
            {"data": {}},
        ]

        tvdb.tv("81189")

        self.assertGreaterEqual(
            cache.ttl(
                tvdb._cache_key(
                    MediaTypes.TV.value, "81189", tvdb._preferred_language_code()
                )
            ),
            tvdb.TVDB_METADATA_CACHE_TIMEOUT - 1,
        )

    @patch("app.providers.tvdb._request")
    def test_tv_prefers_english_translation_payload_for_titles_and_synopsis(
        self,
        mock_request,
    ):
        """Series metadata should prefer English translation payloads when available."""
        mock_request.side_effect = [
            {
                "data": {
                    "id": 259640,
                    "name": {"language": "jpn", "name": "ソードアート・オンライン"},
                    "originalName": {
                        "language": "jpn",
                        "name": "ソードアート・オンライン",
                    },
                    "overview": "日本語の概要",
                    "firstAired": "2012-07-08",
                    "status": {"name": "Ended"},
                    "seasons": [],
                    "characters": [],
                },
            },
            {
                "data": {
                    "name": "Sword Art Online",
                    "overview": "English overview",
                    "language": "eng",
                },
            },
        ]

        result = tvdb.tv("259640")

        self.assertEqual(result["title"], "Sword Art Online")
        self.assertEqual(result["localized_title"], "Sword Art Online")
        self.assertEqual(result["original_title"], "ソードアート・オンライン")
        self.assertEqual(result["synopsis"], "English overview")

    @patch("app.providers.tvdb.tv")
    def test_tv_with_seasons_falls_back_to_series_metadata_when_season_numbers_missing(
        self,
        mock_tv,
    ):
        """A falsy season_numbers (None or []) should return series metadata, not crash."""
        mock_tv.return_value = {"title": "Breaking Bad"}

        self.assertEqual(tvdb.tv_with_seasons("81189", None), {"title": "Breaking Bad"})
        self.assertEqual(tvdb.tv_with_seasons("81189", []), {"title": "Breaking Bad"})

    @patch("app.providers.tvdb.tv")
    @patch("app.providers.tvdb._request")
    def test_tv_with_seasons_normalizes_specials_episode_rows(
        self,
        mock_request,
        mock_tv,
    ):
        """Season payloads should normalize specials and episode rows."""
        mock_tv.return_value = {
            "media_id": "81189",
            "source": Sources.TVDB.value,
            "media_type": MediaTypes.TV.value,
            "title": "Breaking Bad",
            "original_title": "Breaking Bad",
            "localized_title": "Breaking Bad",
            "image": "https://example.com/show.jpg",
            "synopsis": "Chemistry teacher becomes kingpin.",
            "details": {"episodes": 62},
            "related": {"seasons": [{"season_number": 0}]},
            "external_links": {
                "TVDB": "https://www.thetvdb.com/dereferrer/series/81189",
            },
        }
        mock_request.side_effect = [
            {
                "data": {
                    "id": 81189,
                    "name": "Breaking Bad",
                    "seasons": [
                        {
                            "id": 101,
                            "number": 0,
                            "name": "Specials",
                            "type": {"name": "Aired Order"},
                        },
                    ],
                },
            },
            {"data": {}},
            {
                "data": {
                    "id": 101,
                    "number": 0,
                    "name": "Specials",
                    "type": {"name": "Aired Order"},
                    "episodes": [
                        {
                            "number": 1,
                            "aired": "2009-02-17T03:00:00+00:00",
                            "name": "Special 1",
                            "overview": "Behind the scenes.",
                            "image": "https://example.com/special1.jpg",
                            "runtime": 12,
                        },
                    ],
                },
            },
            {"data": {}},
            {"data": {"episodes": []}, "links": {"next": None}},
        ]

        result = tvdb.tv_with_seasons("81189", [0])

        self.assertEqual(result["season/0"]["season_title"], "Specials")
        self.assertEqual(result["season/0"]["episodes"][0]["episode_number"], 1)
        self.assertEqual(
            result["season/0"]["episodes"][0]["air_date"].isoformat(),
            "2009-02-17T03:00:00+00:00",
        )
        self.assertEqual(
            result["season/0"]["episodes"][0]["image"],
            "https://example.com/special1.jpg",
        )

    @patch("app.providers.tvdb.tv")
    @patch("app.providers.tvdb._request")
    def test_tv_with_seasons_prefers_english_episode_translations(
        self,
        mock_request,
        mock_tv,
    ):
        """Season episode rows should use preferred translation names when provided."""
        mock_tv.return_value = {
            "media_id": "120089",
            "source": Sources.TVDB.value,
            "media_type": MediaTypes.ANIME.value,
            "title": "Attack on Titan",
            "original_title": "進撃の巨人",
            "localized_title": "Attack on Titan",
            "image": "https://example.com/show.jpg",
            "synopsis": "English synopsis",
            "details": {"episodes": 25},
            "related": {"seasons": [{"season_number": 1}]},
            "external_links": {
                "TVDB": "https://www.thetvdb.com/dereferrer/series/120089",
            },
        }
        mock_request.side_effect = [
            {
                "data": {
                    "id": 120089,
                    "name": "進撃の巨人",
                    "seasons": [
                        {
                            "id": 201,
                            "number": 1,
                            "name": "Season 1",
                            "type": {"name": "Aired Order"},
                        },
                    ],
                },
            },
            {"data": {}},
            {
                "data": {
                    "id": 201,
                    "number": 1,
                    "name": "Season 1",
                    "type": {"name": "Aired Order"},
                    "episodes": [
                        {
                            "id": 7001,
                            "number": 1,
                            "name": "二千年後の君へ -シガンシナ陥落①-",
                        },
                    ],
                },
            },
            {"data": {}},
            {
                "data": {
                    "episodes": [
                        {
                            "id": 7001,
                            "name": "To You, in 2000 Years",
                            "overview": "English episode overview.",
                        },
                    ],
                },
                "links": {"next": None},
            },
        ]

        result = tvdb.tv_with_seasons(
            "120089", [1], routed_media_type=MediaTypes.ANIME.value
        )

        self.assertEqual(
            result["season/1"]["episodes"][0]["name"],
            "To You, in 2000 Years",
        )

    @patch("app.providers.tvdb.tv")
    @patch("app.providers.tvdb._request")
    def test_tv_with_seasons_batches_episode_translations_in_one_request(
        self,
        mock_request,
        mock_tv,
    ):
        """Episode translations for a whole season should cost one HTTP call.

        Previously, `_normalize_episode_rows` called `_with_preferred_translation`
        per episode, which meant one uncached `episodes/{id}/translations/{lang}`
        request per episode (an N+1). TVDB v4's `series/{id}/episodes/default/{lang}`
        bulk endpoint returns every episode's translated name/overview in one
        (paginated) request, so a season with any number of episodes should only
        need a single extra request for translations, not one per episode.
        """
        mock_tv.return_value = {
            "media_id": "330000",
            "source": Sources.TVDB.value,
            "media_type": MediaTypes.ANIME.value,
            "title": "Some Show",
            "original_title": "何かのショー",
            "localized_title": "Some Show",
            "image": "https://example.com/show.jpg",
            "synopsis": "English synopsis",
            "details": {"episodes": 3},
            "related": {"seasons": [{"season_number": 1}]},
            "external_links": {
                "TVDB": "https://www.thetvdb.com/dereferrer/series/330000",
            },
        }
        mock_request.side_effect = [
            {
                "data": {
                    "id": 330000,
                    "name": "何かのショー",
                    "seasons": [
                        {
                            "id": 401,
                            "number": 1,
                            "name": "Season 1",
                            "type": {"name": "Aired Order"},
                        },
                    ],
                },
            },
            {"data": {}},
            {
                "data": {
                    "id": 401,
                    "seriesId": 330000,
                    "number": 1,
                    "name": "Season 1",
                    "type": {"name": "Aired Order"},
                    "episodes": [
                        {"id": 9001, "number": 1, "name": "第一話"},
                        {"id": 9002, "number": 2, "name": "第二話"},
                        {"id": 9003, "number": 3, "name": "第三話"},
                    ],
                },
            },
            {"data": {}},
            {
                "data": {
                    "episodes": [
                        {
                            "id": 9001,
                            "name": "Episode One",
                            "overview": "First overview.",
                        },
                        {
                            "id": 9002,
                            "name": "Episode Two",
                            "overview": "Second overview.",
                        },
                        {
                            "id": 9003,
                            "name": "Episode Three",
                            "overview": "Third overview.",
                        },
                    ],
                },
                "links": {"next": None},
            },
        ]

        result = tvdb.tv_with_seasons(
            "330000", [1], routed_media_type=MediaTypes.ANIME.value
        )

        episode_names = [episode["name"] for episode in result["season/1"]["episodes"]]
        self.assertEqual(
            episode_names,
            ["Episode One", "Episode Two", "Episode Three"],
        )

        requested_paths = [call.args[0] for call in mock_request.call_args_list]
        self.assertEqual(
            requested_paths.count("series/330000/episodes/default/eng"),
            1,
        )
        self.assertEqual(len(mock_request.call_args_list), 5)
        self.assertFalse(
            any(path.startswith("episodes/") for path in requested_paths),
        )

    @override_settings(TVDB_API_KEY="test-tvdb-key")
    @patch("app.providers.tvdb.tv")
    def test_series_has_anime_genre_uses_supplied_metadata(self, mock_tv):
        """Anime genre detection should use supplied metadata without refetching."""
        result = tvdb.series_has_anime_genre(
            "81189",
            tv_data={"genres": ["Drama", "Anime"]},
        )

        self.assertTrue(result)
        mock_tv.assert_not_called()

    @override_settings(TVDB_API_KEY="test-tvdb-key")
    @patch("app.providers.tvdb.tv")
    def test_series_has_anime_genre_fetches_tvdb_metadata(self, mock_tv):
        """Anime genre detection should fetch TVDB metadata when needed."""
        mock_tv.return_value = {
            "genres": ["Action", "Anime"],
        }

        result = tvdb.series_has_anime_genre("81189")

        self.assertTrue(result)
        mock_tv.assert_called_once_with(
            "81189",
            routed_media_type=MediaTypes.TV.value,
        )

    @patch("app.providers.tvdb._request")
    def test_search_prefers_english_translation_rows(self, mock_request):
        """Search results should prefer English names from translation arrays."""
        mock_request.return_value = {
            "data": [
                {
                    "id": 259640,
                    "name": {"language": "jpn", "name": "ソードアート・オンライン"},
                    "translations": {
                        "name": [
                            {"language": "jpn", "name": "ソードアート・オンライン"},
                            {"language": "eng", "name": "Sword Art Online"},
                        ],
                    },
                    "firstAired": "2012-07-08",
                },
            ],
        }

        result = tvdb.search(MediaTypes.ANIME.value, "sword art online", 1)

        self.assertEqual(result["results"][0]["title"], "Sword Art Online")
        self.assertEqual(result["results"][0]["localized_title"], "Sword Art Online")

    @override_settings(TMDB_LANG="ja")
    @patch("app.providers.tvdb._request")
    def test_search_prefers_configured_language_translation_rows(self, mock_request):
        """Search results should prefer titles in the configured TMDB_LANG."""
        mock_request.return_value = {
            "data": [
                {
                    "id": 259640,
                    "name": {"language": "eng", "name": "Sword Art Online"},
                    "translations": {
                        "name": [
                            {"language": "eng", "name": "Sword Art Online"},
                            {"language": "jpn", "name": "ソードアート・オンライン"},
                        ],
                    },
                    "firstAired": "2012-07-08",
                },
            ],
        }

        result = tvdb.search(MediaTypes.ANIME.value, "sword art online", 1)

        self.assertEqual(result["results"][0]["title"], "ソードアート・オンライン")
        self.assertEqual(
            result["results"][0]["localized_title"],
            "ソードアート・オンライン",
        )
        self.assertEqual(mock_request.call_args.kwargs["params"]["lang"], "jpn")

    @patch("app.providers.tvdb.tv")
    @patch("app.providers.tvdb.tv_with_seasons")
    def test_episode_returns_tmdb_compatible_episode_payload(
        self,
        mock_tv_with_seasons,
        mock_tv,
    ):
        """Episode lookups should produce TMDB-compatible title fields."""
        mock_tv.return_value = {
            "title": "Breaking Bad",
            "original_title": "Breaking Bad",
            "localized_title": "Breaking Bad",
        }
        mock_tv_with_seasons.return_value = {
            "season/1": {
                "title": "Breaking Bad",
                "original_title": "Breaking Bad",
                "localized_title": "Breaking Bad",
                "season_title": "Season 1",
                "episodes": [
                    {
                        "episode_number": 1,
                        "name": "Pilot",
                        "image": "https://example.com/pilot.jpg",
                    },
                ],
            },
        }

        result = tvdb.episode("81189", 1, 1)

        self.assertEqual(result["title"], "Breaking Bad")
        self.assertEqual(result["season_title"], "Season 1")
        self.assertEqual(result["episode_title"], "Pilot")
        self.assertEqual(result["image"], "https://example.com/pilot.jpg")

    @patch("app.providers.tvdb.cache")
    @patch("app.providers.tvdb._request")
    def test_episode_by_id_returns_series_and_numbering(
        self,
        mock_request,
        mock_cache,
    ):
        """Episode-level TVDB IDs should resolve to their series metadata."""
        mock_cache.get.return_value = None
        mock_request.return_value = {
            "data": {
                "id": 11821802,
                "seriesId": 407407,
                "seasonNumber": 1,
                "number": 3,
            },
        }

        result = tvdb.episode_by_id("11821802")

        self.assertEqual(
            result,
            {
                "episode_id": 11821802,
                "series_id": 407407,
                "season_number": 1,
                "episode_number": 3,
            },
        )
        mock_request.assert_called_once_with("episodes/11821802/extended")

    @patch("app.providers.tvdb.cache")
    @patch("app.providers.tvdb._request")
    def test_series_tmdb_id_returns_remote_tmdb_id(
        self,
        mock_request,
        mock_cache,
    ):
        """TVDB series metadata should expose its TMDB remote ID."""
        mock_cache.get.return_value = None
        mock_request.return_value = {
            "data": {
                "remoteIds": [
                    {"sourceName": "TheMovieDB.com", "id": "124428"},
                ],
            },
        }

        result = tvdb.series_tmdb_id("407407")

        self.assertEqual(result, "124428")
        mock_request.assert_called_once_with("series/407407/extended")

    @patch("app.providers.tvdb._request")
    def test_series_tmdb_id_reuses_cached_series_extended_payload(
        self,
        mock_request,
    ):
        """series_tmdb_id should reuse _get_series_extended's cache, not refetch."""
        series_payload = {
            "data": {
                "id": 81189,
                "name": "Breaking Bad",
                "seasons": [],
                "characters": [],
                "remoteIds": [
                    {"sourceName": "TheMovieDB.com", "id": "1396"},
                ],
            },
        }
        mock_request.side_effect = [
            series_payload,
            {"data": {}},
            series_payload,
        ]

        tvdb.tv("81189")
        result = tvdb.series_tmdb_id("81189")

        self.assertEqual(result, "1396")
        requested_paths = [call.args[0] for call in mock_request.call_args_list]
        self.assertEqual(requested_paths.count("series/81189/extended"), 1)

    @patch("app.providers.tvdb._request")
    def test_get_episode_airstamp_map_caches_precise_episode_times(self, mock_request):
        """Default-order episode maps should cache normalized airstamps."""
        mock_request.return_value = {
            "data": {
                "episodes": [
                    {
                        "seasonNumber": 1,
                        "number": 1,
                        "aired": "2008-01-20T22:00:00+00:00",
                    },
                    {
                        "seasonNumber": 1,
                        "number": 2,
                        "aired": "2008-01-27T22:00:00+00:00",
                    },
                ],
            },
        }

        first = tvdb.get_episode_airstamp_map("81189")
        second = tvdb.get_episode_airstamp_map("81189")

        self.assertEqual(first["1_1"], "2008-01-20T22:00:00+00:00")
        self.assertEqual(second, first)
        mock_request.assert_called_once()
