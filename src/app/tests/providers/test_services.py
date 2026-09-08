from pathlib import Path
from unittest.mock import MagicMock, patch

import requests
from django.core.cache import cache
from django.test import TestCase, override_settings

from app.models import (
    Item,
    MediaTypes,
    Podcast,
    PodcastEpisode,
    PodcastShow,
    Sources,
    Status,
)
from app.providers import (
    credentials,
    igdb,
    mal,
    services,
    tmdb,
)
from integrations.imports.helpers import encrypt
from users.models import User

mock_path = Path(__file__).resolve().parent.parent / "mock_data"


class ServicesTests(TestCase):
    """Test the services module functions."""

    def assert_metadata_title_payload(self, payload, expected_title):
        """Assert merged metadata payload keeps canonical title fields."""
        self.assertEqual(payload["title"], expected_title)
        self.assertIn("original_title", payload)
        self.assertIn("localized_title", payload)

    @patch("app.providers.services.session.get")
    def test_api_request_get(self, mock_get):
        """Test the api_request function with GET method."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "test"}
        mock_get.return_value = mock_response

        result = services.api_request(
            "TEST",
            "GET",
            "https://example.com/api",
            params={"param": "value"},
        )

        self.assertEqual(result, {"data": "test"})

        mock_get.assert_called_once()
        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["url"], "https://example.com/api")
        self.assertEqual(kwargs["params"], {"param": "value"})
        self.assertIn("timeout", kwargs)

    @patch("app.providers.services.session.post")
    def test_api_request_post(self, mock_post):
        """Test the api_request function with POST method."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "test"}
        mock_post.return_value = mock_response

        result = services.api_request(
            "TEST",
            "POST",
            "https://example.com/api",
            params={"json_param": "value"},
            data={"form_data": "value"},
        )

        self.assertEqual(result, {"data": "test"})

        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["url"], "https://example.com/api")
        self.assertEqual(kwargs["json"], {"json_param": "value"})
        self.assertEqual(kwargs["data"], {"form_data": "value"})
        self.assertIn("timeout", kwargs)

    def tearDown(self):
        """Avoid leaking the tmdb proxy cache key between tests."""
        cache.delete("tmdb_proxy_url")
        super().tearDown()

    @patch("app.providers.services.session.get")
    def test_api_request_uses_configured_tmdb_proxy(self, mock_get):
        """TMDB requests should route through a configured user's proxy URL."""
        User.objects.create_user(
            username="proxy-user",
            password="testpass123",
            tmdb_proxy_url=encrypt("socks5://127.0.0.1:1080"),
        )
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "test"}
        mock_get.return_value = mock_response

        services.api_request(Sources.TMDB.value, "GET", "https://example.com/api")

        _, kwargs = mock_get.call_args
        self.assertEqual(
            kwargs["proxies"],
            {"http": "socks5://127.0.0.1:1080", "https": "socks5://127.0.0.1:1080"},
        )

    @patch("app.providers.services.session.get")
    def test_api_request_omits_proxies_when_not_configured(self, mock_get):
        """No proxy should be applied when no user has one configured."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "test"}
        mock_get.return_value = mock_response

        services.api_request(Sources.TMDB.value, "GET", "https://example.com/api")

        _, kwargs = mock_get.call_args
        self.assertNotIn("proxies", kwargs)

    @patch("app.providers.services.session.get")
    def test_api_request_only_proxies_tmdb_provider(self, mock_get):
        """Non-TMDB providers should not pick up the TMDB proxy setting."""
        User.objects.create_user(
            username="proxy-user",
            password="testpass123",
            tmdb_proxy_url=encrypt("socks5://127.0.0.1:1080"),
        )
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "test"}
        mock_get.return_value = mock_response

        services.api_request(Sources.TVDB.value, "GET", "https://example.com/api")

        _, kwargs = mock_get.call_args
        self.assertNotIn("proxies", kwargs)

    @patch("app.providers.services.session.get")
    def test_api_request_wraps_connection_failures(self, mock_get):
        """Network failures should raise a provider error without crashing views."""
        mock_get.side_effect = requests.exceptions.ConnectionError("dns failure")

        with self.assertRaises(services.ProviderAPIError) as cm:
            services.api_request(
                Sources.TMDB.value,
                "GET",
                "https://example.com/api",
            )

        self.assertEqual(cm.exception.provider, Sources.TMDB.value)
        self.assertEqual(cm.exception.provider_label, Sources.TMDB.label)
        self.assertIsNone(cm.exception.status_code)
        self.assertIn("Could not reach", str(cm.exception))

    @patch("app.providers.services.time.sleep")
    @patch("app.providers.services.session.get")
    def test_api_request_retries_transient_http_errors(
        self,
        mock_get,
        mock_sleep,
    ):
        """Transient upstream 5xx responses should be retried before failing."""
        failed_response = MagicMock()
        failed_response.status_code = 502
        failed_response.headers = {}
        failed_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "502 Bad Gateway",
            response=failed_response,
        )

        successful_response = MagicMock()
        successful_response.raise_for_status.return_value = None
        successful_response.json.return_value = {"data": "retry_success"}

        mock_get.side_effect = [failed_response, successful_response]

        result = services.api_request(
            Sources.TMDB.value,
            "GET",
            "https://example.com/api",
        )

        self.assertEqual(result, {"data": "retry_success"})
        self.assertEqual(mock_get.call_count, 2)
        mock_sleep.assert_called_once_with(1)

    @patch("app.providers.services.api_request")
    def test_request_error_handling_rate_limit(self, mock_api_request):
        """Test the request_error_handling function with rate limiting."""
        mock_response = MagicMock()
        mock_response.status_code = 429  # Too many requests
        mock_response.headers = {"Retry-After": "5"}

        error = requests.exceptions.HTTPError("429 Too Many Requests")
        error.response = mock_response

        mock_api_request.return_value = {"data": "retry_success"}

        result = services.api_request(
            error,
            "TEST",
            "GET",
            "https://example.com/api",
            {"param": "value"},
            None,
            None,
        )

        mock_api_request.assert_called_once()

        self.assertEqual(result, {"data": "retry_success"})

    @patch("app.providers.igdb.cache.delete")
    def test_handle_error_igdb_unauthorized(
        self,
        mock_cache_delete,
    ):
        """Test the handle_error function with IGDB unauthorized error."""
        mock_response = MagicMock()
        mock_response.status_code = 401  # Unauthorized

        error = requests.exceptions.HTTPError("401 Unauthorized")
        error.response = mock_response

        result = igdb.handle_error(error)

        # The token cache is keyed by the credentials that minted it, so a
        # personal key cannot invalidate (or serve) someone else's token.
        suffix = credentials.cache_suffix("igdb", "client_id", "client_secret")
        mock_cache_delete.assert_called_once_with(f"igdb_access_token_{suffix}")

        self.assertEqual(result, {"retry": True})

    def test_handle_error_igdb_bad_request(self):
        """Test the handle_error function with IGDB bad request error."""
        mock_response = MagicMock()
        mock_response.status_code = 400  # Bad Request
        mock_response.json.return_value = {"message": "Invalid query"}

        error = requests.exceptions.HTTPError("400 Bad Request")
        error.response = mock_response

        with self.assertRaises(services.ProviderAPIError) as cm:
            igdb.handle_error(error)

        self.assertEqual(cm.exception.provider, Sources.IGDB.value)

    def test_handle_error_tmdb_unauthorized(self):
        """Test the handle_error function with TMDB unauthorized error."""
        mock_response = MagicMock()
        mock_response.status_code = 401  # Unauthorized
        mock_response.json.return_value = {"status_message": "Invalid API key"}

        error = requests.exceptions.HTTPError("401 Unauthorized")
        error.response = mock_response

        with self.assertRaises(services.ProviderAPIError) as cm:
            tmdb.handle_error(error)

        self.assertEqual(cm.exception.provider, Sources.TMDB.value)

    @patch("app.providers.tmdb.logger.exception")
    def test_handle_error_tmdb_non_json_server_error_skips_decode_traceback(
        self,
        mock_logger_exception,
    ):
        """TMDB 5xx HTML bodies should raise provider errors without JSON tracebacks."""
        mock_response = MagicMock()
        mock_response.status_code = 502
        mock_response.headers = {}
        mock_response.text = "<html>Bad Gateway</html>"
        mock_response.json.side_effect = requests.exceptions.JSONDecodeError(
            "Expecting value",
            "",
            0,
        )

        error = requests.exceptions.HTTPError("502 Bad Gateway")
        error.response = mock_response

        with self.assertRaises(services.ProviderAPIError) as cm:
            tmdb.handle_error(error)

        self.assertEqual(cm.exception.provider, Sources.TMDB.value)
        mock_logger_exception.assert_not_called()

    def test_handle_error_mal_forbidden(self):
        """Test the handle_error function with MAL forbidden error."""
        mock_response = MagicMock()
        mock_response.status_code = 403  # Forbidden
        mock_response.json.return_value = {"message": "Forbidden"}

        error = requests.exceptions.HTTPError("403 Forbidden")
        error.response = mock_response

        with self.assertRaises(services.ProviderAPIError) as cm:
            mal.handle_error(error)

        self.assertEqual(cm.exception.provider, Sources.MAL.value)

    def test_igdb_game_adds_hltb_external_link_when_resolvable(self):
        """IGDB game metadata should expose resolvable HowLongToBeat links."""
        with (
            patch("app.providers.igdb.cache.get", return_value=None),
            patch("app.providers.igdb.get_access_token", return_value="token"),
            patch("app.providers.igdb.cache.set"),
            patch("app.providers.igdb.services.api_request") as mock_api_request,
        ):
            mock_api_request.return_value = [
                {
                    "id": 1942,
                    "name": "The Witcher 3: Wild Hunt",
                    "url": "https://www.igdb.com/games/the-witcher-3-wild-hunt",
                    "game_type": 0,
                    "external_games": [{"url": "www.howlongtobeat.com/game/10270"}],
                },
            ]

            response = igdb.game("1942")

        self.assertEqual(
            response["external_links"]["HowLongToBeat"],
            "https://www.howlongtobeat.com/game/10270",
        )

    def test_igdb_game_falls_back_to_hltb_search_link_when_unresolvable(self):
        """IGDB game metadata should add HLTB search link when direct URL is missing."""
        with (
            patch("app.providers.igdb.cache.get", return_value=None),
            patch("app.providers.igdb.get_access_token", return_value="token"),
            patch("app.providers.igdb.cache.set"),
            patch("app.providers.igdb.services.api_request") as mock_api_request,
        ):
            mock_api_request.return_value = [
                {
                    "id": 1942,
                    "name": "The Witcher 3: Wild Hunt",
                    "url": "https://www.igdb.com/games/the-witcher-3-wild-hunt",
                    "game_type": 0,
                    "external_games": [
                        {"url": "https://store.steampowered.com/app/292030"}
                    ],
                },
            ]

            response = igdb.game("1942")

        self.assertEqual(
            response["external_links"]["HowLongToBeat"],
            "https://howlongtobeat.com/?q=The+Witcher+3%3A+Wild+Hunt",
        )

    def test_igdb_game_adds_hltb_external_link_from_websites(self):
        """IGDB game metadata should resolve HLTB links from websites data too."""
        with (
            patch("app.providers.igdb.cache.get", return_value=None),
            patch("app.providers.igdb.get_access_token", return_value="token"),
            patch("app.providers.igdb.cache.set"),
            patch("app.providers.igdb.services.api_request") as mock_api_request,
        ):
            mock_api_request.return_value = [
                {
                    "id": 1942,
                    "name": "The Witcher 3: Wild Hunt",
                    "url": "https://www.igdb.com/games/the-witcher-3-wild-hunt",
                    "game_type": 0,
                    "websites": [{"url": "https://howlongtobeat.com/game/10270"}],
                },
            ]

            response = igdb.game("1942")

        self.assertEqual(
            response["external_links"]["HowLongToBeat"],
            "https://howlongtobeat.com/game/10270",
        )

    def test_igdb_game_omits_hltb_links_without_url_or_title(self):
        """IGDB game metadata should skip HLTB links when URL and title are missing."""
        with (
            patch("app.providers.igdb.cache.get", return_value=None),
            patch("app.providers.igdb.get_access_token", return_value="token"),
            patch("app.providers.igdb.cache.set"),
            patch("app.providers.igdb.services.api_request") as mock_api_request,
        ):
            mock_api_request.return_value = [
                {
                    "id": 1942,
                    "name": "",
                    "url": "https://www.igdb.com/games/the-witcher-3-wild-hunt",
                    "game_type": 0,
                    "external_games": [
                        {"url": "https://store.steampowered.com/app/292030"}
                    ],
                },
            ]

            response = igdb.game("1942")

        self.assertNotIn("external_links", response)

    def test_igdb_get_access_token_raises_not_configured_without_credentials(self):
        """Missing IGDB credentials should raise a clear config error, not a raw Twitch error."""
        with patch("app.providers.credentials.is_configured", return_value=False):
            with self.assertRaises(services.ProviderNotConfiguredError) as cm:
                igdb.get_access_token()

        self.assertEqual(cm.exception.provider, Sources.IGDB.value)
        self.assertIn("not configured", str(cm.exception))

    @patch("app.providers.mal.anime")
    def test_get_media_metadata_anime(self, mock_anime):
        """Test the get_media_metadata function for anime."""
        mock_anime.return_value = {"title": "Test Anime"}

        result = services.get_media_metadata(
            MediaTypes.ANIME.value,
            "1",
            Sources.MAL.value,
        )

        self.assert_metadata_title_payload(result, "Test Anime")

        mock_anime.assert_called_once_with("1")

    @patch("app.providers.mangaupdates.manga")
    def test_get_media_metadata_manga_mangaupdates(self, mock_manga):
        """Test the get_media_metadata function for manga from MangaUpdates."""
        mock_manga.return_value = {"title": "Test Manga"}

        result = services.get_media_metadata(
            MediaTypes.MANGA.value,
            "1",
            Sources.MANGAUPDATES.value,
        )

        self.assert_metadata_title_payload(result, "Test Manga")

        mock_manga.assert_called_once_with("1")

    @patch("app.providers.mal.manga")
    def test_get_media_metadata_manga_mal(self, mock_manga):
        """Test the get_media_metadata function for manga from MAL."""
        mock_manga.return_value = {"title": "Test Manga"}

        result = services.get_media_metadata(
            MediaTypes.MANGA.value,
            "1",
            Sources.MAL.value,
        )

        self.assert_metadata_title_payload(result, "Test Manga")

        mock_manga.assert_called_once_with("1")

    @patch("app.providers.tmdb.tv")
    def test_get_media_metadata_tv(self, mock_tv):
        """Test the get_media_metadata function for TV shows."""
        mock_tv.return_value = {"title": "Test TV"}

        result = services.get_media_metadata(
            MediaTypes.TV.value,
            "1",
            Sources.TMDB.value,
        )

        self.assert_metadata_title_payload(result, "Test TV")

        mock_tv.assert_called_once_with("1", None)

    @patch("app.providers.tvdb.tv")
    def test_get_media_metadata_tv_tvdb(self, mock_tv):
        """Test the get_media_metadata function for TVDB TV shows."""
        mock_tv.return_value = {"title": "Test TVDB Show"}

        result = services.get_media_metadata(
            MediaTypes.TV.value,
            "81189",
            Sources.TVDB.value,
        )

        self.assert_metadata_title_payload(result, "Test TVDB Show")
        mock_tv.assert_called_once_with(
            "81189",
            routed_media_type=MediaTypes.TV.value,
            language=None,
        )

    @patch("app.providers.tmdb.tv_with_seasons")
    def test_get_media_metadata_tv_with_seasons(self, mock_tv_with_seasons):
        """Test the get_media_metadata function for TV shows with seasons."""
        mock_tv_with_seasons.return_value = {"title": "Test TV with Seasons"}

        result = services.get_media_metadata(
            "tv_with_seasons",
            "1",
            Sources.TMDB.value,
            season_numbers=[1, 2],
        )

        self.assert_metadata_title_payload(result, "Test TV with Seasons")

        mock_tv_with_seasons.assert_called_once_with("1", [1, 2], None)

    @patch("app.providers.tvdb.tv_with_seasons")
    def test_get_media_metadata_tv_with_seasons_tvdb(self, mock_tv_with_seasons):
        """Test the get_media_metadata function for TVDB seasons."""
        mock_tv_with_seasons.return_value = {"title": "Test TVDB Seasons"}

        result = services.get_media_metadata(
            "tv_with_seasons",
            "81189",
            Sources.TVDB.value,
            season_numbers=[0, 1],
        )

        self.assert_metadata_title_payload(result, "Test TVDB Seasons")
        mock_tv_with_seasons.assert_called_once_with(
            "81189",
            [0, 1],
            routed_media_type=MediaTypes.TV.value,
            language=None,
        )

    @patch("app.providers.tmdb.tv_with_seasons")
    def test_get_media_metadata_season(self, mock_tv_with_seasons):
        """Test the get_media_metadata function for TV seasons."""
        mock_tv_with_seasons.return_value = {
            "season/1": {"title": "Test Season"},
        }

        result = services.get_media_metadata(
            MediaTypes.SEASON.value,
            "1",
            Sources.TMDB.value,
            season_numbers=[1],
        )

        self.assert_metadata_title_payload(result, "Test Season")

        mock_tv_with_seasons.assert_called_once_with("1", [1], None)

    @patch("app.providers.tmdb.episode")
    def test_get_media_metadata_episode(self, mock_episode):
        """Test the get_media_metadata function for TV episodes."""
        mock_episode.return_value = {"title": "Test Episode"}

        result = services.get_media_metadata(
            MediaTypes.EPISODE.value,
            "1",
            Sources.TMDB.value,
            season_numbers=[1],
            episode_number="2",
        )

        self.assert_metadata_title_payload(result, "Test Episode")

        mock_episode.assert_called_once_with("1", 1, "2", None)

    @patch("app.providers.tmdb.movie")
    def test_get_media_metadata_movie(self, mock_movie):
        """Test the get_media_metadata function for movies."""
        mock_movie.return_value = {"title": "Test Movie"}

        result = services.get_media_metadata(
            MediaTypes.MOVIE.value,
            "1",
            Sources.TMDB.value,
        )

        self.assert_metadata_title_payload(result, "Test Movie")

        mock_movie.assert_called_once_with("1", None)

    @patch("app.providers.igdb.game")
    def test_get_media_metadata_game(self, mock_game):
        """Test the get_media_metadata function for games."""
        mock_game.return_value = {"title": "Test Game"}

        result = services.get_media_metadata(
            MediaTypes.GAME.value,
            "1",
            Sources.IGDB.value,
        )

        self.assert_metadata_title_payload(result, "Test Game")

        mock_game.assert_called_once_with("1")

    @patch("app.providers.comicvine.comic")
    def test_get_media_metadata_comic(self, mock_comic):
        """Test the get_media_metadata function for comics."""
        mock_comic.return_value = {"title": "Test Comic"}

        result = services.get_media_metadata(
            MediaTypes.COMIC.value,
            "1",
            Sources.COMICVINE.value,
        )

        self.assert_metadata_title_payload(result, "Test Comic")

        mock_comic.assert_called_once_with("1", user=None)

    @patch("app.providers.openlibrary.book")
    def test_get_media_metadata_book(self, mock_book):
        """Test the get_media_metadata function for books."""
        mock_book.return_value = {"title": "Test Book"}

        result = services.get_media_metadata(
            MediaTypes.BOOK.value,
            "1",
            Sources.OPENLIBRARY.value,
        )

        self.assert_metadata_title_payload(result, "Test Book")

        mock_book.assert_called_once_with("1")

    @patch("app.providers.googlebooks.book")
    def test_get_media_metadata_googlebooks_book(self, mock_book):
        """Test the Google Books metadata provider routing."""
        mock_book.return_value = {"title": "Test Google Book"}

        result = services.get_media_metadata(
            MediaTypes.BOOK.value,
            "volume-1",
            Sources.GOOGLEBOOKS.value,
        )

        self.assert_metadata_title_payload(result, "Test Google Book")
        mock_book.assert_called_once_with("volume-1", user=None)

    @patch("app.providers.manual.metadata")
    def test_get_media_metadata_manual(self, mock_metadata):
        """Test the get_media_metadata function for manual media."""
        mock_metadata.return_value = {"title": "Test Manual"}

        result = services.get_media_metadata(
            MediaTypes.MOVIE.value,
            "1",
            Sources.MANUAL.value,
        )

        self.assert_metadata_title_payload(result, "Test Manual")

        mock_metadata.assert_called_once_with("1", MediaTypes.MOVIE.value)

    @patch("app.providers.manual.season")
    def test_get_media_metadata_manual_season(self, mock_season):
        """Test the get_media_metadata function for manual seasons."""
        mock_season.return_value = {"title": "Test Manual Season"}

        result = services.get_media_metadata(
            MediaTypes.SEASON.value,
            "1",
            Sources.MANUAL.value,
            season_numbers=[1],
        )

        self.assert_metadata_title_payload(result, "Test Manual Season")

        mock_season.assert_called_once_with("1", 1)

    @patch("app.providers.manual.episode")
    def test_get_media_metadata_manual_episode(self, mock_episode):
        """Test the get_media_metadata function for manual episodes."""
        mock_episode.return_value = {"title": "Test Manual Episode"}

        result = services.get_media_metadata(
            MediaTypes.EPISODE.value,
            "1",
            Sources.MANUAL.value,
            season_numbers=[1],
            episode_number="2",
        )

        self.assert_metadata_title_payload(result, "Test Manual Episode")

        mock_episode.assert_called_once_with("1", 1, "2")

    @patch("app.providers.tmdb.episode")
    def test_get_media_metadata_tmdb_episode_not_found(self, mock_episode):
        """Test the get_media_metadata function for TMDB episodes that don't exist."""
        mock_response = type(
            "Response",
            (),
            {"status_code": 404, "text": "Episode not found"},
        )()
        mock_error = type("Error", (), {"response": mock_response})()
        mock_episode.side_effect = services.ProviderAPIError(
            Sources.TMDB.value,
            mock_error,
        )

        with self.assertRaises(services.ProviderAPIError) as cm:
            services.get_media_metadata(
                MediaTypes.EPISODE.value,
                "1396",
                Sources.TMDB.value,
                season_numbers=[1],
                episode_number="3",
            )

        self.assertEqual(cm.exception.provider, Sources.TMDB.value)

        mock_episode.assert_called_once_with("1396", 1, "3", None)

    def test_get_media_metadata_podcast_episode(self):
        """Podcast detail metadata should resolve from the local episode catalog."""
        show = PodcastShow.objects.create(
            podcast_uuid="podcast-show-services",
            source=Sources.POCKETCASTS.value,
            title="Services Show",
            author="Services Author",
            image="https://example.com/show.jpg",
            description="A service-test show.",
            genres=["Technology"],
            language="en",
        )
        episode = PodcastEpisode.objects.create(
            show=show,
            episode_uuid="podcast-episode-services",
            title="Services Episode",
            duration=1800,
            episode_number=4,
            season_number=2,
        )

        result = services.get_media_metadata(
            MediaTypes.PODCAST.value,
            episode.episode_uuid,
            Sources.POCKETCASTS.value,
        )

        self.assertEqual(result["media_id"], episode.episode_uuid)
        self.assertEqual(result["source"], Sources.POCKETCASTS.value)
        self.assertEqual(result["media_type"], MediaTypes.PODCAST.value)
        self.assertEqual(result["title"], episode.title)
        self.assertEqual(result["image"], show.image)
        self.assertEqual(result["synopsis"], show.description)
        self.assertEqual(result["genres"], show.genres)
        self.assertEqual(result["details"]["show_title"], show.title)
        self.assertEqual(result["details"]["duration"], episode.duration)

    def test_get_media_metadata_podcast_deleted_episode_is_not_found(self):
        """Deleted podcast episodes should not resolve as generic media."""
        show = PodcastShow.objects.create(
            podcast_uuid="podcast-show-deleted",
            source=Sources.POCKETCASTS.value,
            title="Deleted Show",
        )
        episode = PodcastEpisode.objects.create(
            show=show,
            episode_uuid="podcast-episode-deleted",
            title="Deleted Episode",
            is_deleted=True,
        )

        with self.assertRaises(services.ProviderAPIError) as context:
            services.get_media_metadata(
                MediaTypes.PODCAST.value,
                episode.episode_uuid,
                Sources.POCKETCASTS.value,
            )

        self.assertEqual(context.exception.status_code, 404)

    def test_get_media_metadata_podcast_source_mismatch_is_not_found(self):
        """A podcast episode must belong to the requested provider source."""
        show = PodcastShow.objects.create(
            podcast_uuid="podcast-show-source-mismatch",
            source=Sources.GPODDER.value,
            title="GPodder Show",
        )
        episode = PodcastEpisode.objects.create(
            show=show,
            episode_uuid="podcast-episode-source-mismatch",
            title="Source Mismatch Episode",
        )

        with self.assertRaises(services.ProviderAPIError) as context:
            services.get_media_metadata(
                MediaTypes.PODCAST.value,
                episode.episode_uuid,
                Sources.POCKETCASTS.value,
            )

        self.assertEqual(context.exception.status_code, 404)

    def test_get_media_metadata_podcast_uses_tracked_item_fallback(self):
        """Tracked legacy podcast items remain resolvable without catalog links."""
        user = User.objects.create_user(username="podcast-services-user")
        item = Item.objects.create(
            media_id="podcast-legacy-item",
            source=Sources.POCKETCASTS.value,
            media_type=MediaTypes.PODCAST.value,
            title="Cached Podcast Episode",
            image="https://example.com/cached.jpg",
        )
        Podcast.objects.create(
            user=user,
            item=item,
            status=Status.COMPLETED.value,
        )

        result = services.get_media_metadata(
            MediaTypes.PODCAST.value,
            item.media_id,
            item.source,
            user=user,
        )

        self.assertEqual(result["media_id"], item.media_id)
        self.assertEqual(result["media_type"], MediaTypes.PODCAST.value)
        self.assertEqual(result["title"], item.title)

    @patch("app.providers.services.musicbrainz.recording")
    def test_get_media_metadata_music_preserves_provider_identity(self, mock_recording):
        """Music detail metadata should preserve MusicBrainz identity fields."""
        mock_recording.return_value = {
            "media_id": "11111111-1111-1111-1111-111111111111",
            "source": Sources.MUSICBRAINZ.value,
            "media_type": MediaTypes.MUSIC.value,
            "title": "Test Song - Test Artist",
            "image": "https://example.com/track.jpg",
            "related": {},
            "details": {"artist": "Test Artist"},
        }

        result = services.get_media_metadata(
            MediaTypes.MUSIC.value,
            "11111111-1111-1111-1111-111111111111",
            Sources.MUSICBRAINZ.value,
        )

        self.assertEqual(result["media_id"], mock_recording.return_value["media_id"])
        self.assertEqual(result["source"], Sources.MUSICBRAINZ.value)
        self.assertEqual(result["media_type"], MediaTypes.MUSIC.value)
        self.assertEqual(result["title"], "Test Song - Test Artist")
        mock_recording.assert_called_once()

    def test_get_media_metadata_music_invalid_id_is_not_found(self):
        """Invalid MusicBrainz recording IDs should not produce empty metadata."""
        with self.assertRaises(services.ProviderAPIError) as context:
            services.get_media_metadata(
                MediaTypes.MUSIC.value,
                "invalid-recording-id",
                Sources.MUSICBRAINZ.value,
            )

        self.assertEqual(context.exception.status_code, 404)

    @patch("app.providers.services.musicbrainz.recording")
    def test_get_media_metadata_music_provider_not_found_is_propagated(
        self,
        mock_recording,
    ):
        """MusicBrainz 404s should remain explicit not-found errors."""
        response = type(
            "Response",
            (),
            {
                "status_code": 404,
                "headers": {},
                "text": "Recording not found",
                "json": lambda self: {},
            },
        )()
        mock_recording.side_effect = services.ProviderAPIError(
            Sources.MUSICBRAINZ.value,
            requests.exceptions.HTTPError(response=response),
        )

        with self.assertRaises(services.ProviderAPIError) as context:
            services.get_media_metadata(
                MediaTypes.MUSIC.value,
                "11111111-1111-1111-1111-111111111111",
                Sources.MUSICBRAINZ.value,
            )

        self.assertEqual(context.exception.status_code, 404)
        mock_recording.assert_called_once()

    @patch("app.providers.hardcover.book")
    def test_get_media_metadata_hardcover_book(self, mock_book):
        """Test the get_media_metadata function for books from Hardcover."""
        mock_book.return_value = {"title": "Test Hardcover Book"}

        result = services.get_media_metadata(
            MediaTypes.BOOK.value,
            "1",
            Sources.HARDCOVER.value,
        )

        self.assert_metadata_title_payload(result, "Test Hardcover Book")

        mock_book.assert_called_once_with("1", edition_id=None, user=None)

    @patch("app.providers.mal.search")
    def test_search_anime(self, mock_search):
        """Test the search function for anime."""
        mock_search.return_value = [{"title": "Test Anime"}]

        result = services.search(MediaTypes.ANIME.value, "test", 1)

        self.assertEqual(result, [{"title": "Test Anime"}])

        mock_search.assert_called_once_with(MediaTypes.ANIME.value, "test", 1)

    @override_settings(TVDB_API_KEY="test-tvdb-key")
    @patch("app.providers.tvdb.search")
    def test_search_anime_tvdb(self, mock_search):
        """Test the search function for anime via TVDB."""
        mock_search.return_value = {"results": []}

        result = services.search(
            MediaTypes.ANIME.value,
            "test",
            1,
            source=Sources.TVDB.value,
        )

        self.assertEqual(result, {"results": []})
        mock_search.assert_called_once_with(MediaTypes.ANIME.value, "test", 1, None)

    @patch("app.providers.mangaupdates.search")
    def test_search_manga_mangaupdates(self, mock_search):
        """Test the search function for manga from MangaUpdates."""
        mock_search.return_value = [{"title": "Test Manga"}]

        result = services.search(
            MediaTypes.MANGA.value,
            "test",
            1,
            source=Sources.MANGAUPDATES.value,
        )

        self.assertEqual(result, [{"title": "Test Manga"}])

        mock_search.assert_called_once_with("test", 1)

    @patch("app.providers.mal.search")
    def test_search_manga_mal(self, mock_search):
        """Test the search function for manga from MAL."""
        mock_search.return_value = [{"title": "Test Manga"}]

        result = services.search(MediaTypes.MANGA.value, "test", 1)

        self.assertEqual(result, [{"title": "Test Manga"}])

        mock_search.assert_called_once_with(MediaTypes.MANGA.value, "test", 1)

    @patch("app.providers.tmdb.search")
    def test_search_tv(self, mock_search):
        """Test the search function for TV shows."""
        mock_search.return_value = [{"title": "Test TV"}]

        result = services.search(MediaTypes.TV.value, "test", 1)

        self.assertEqual(result, [{"title": "Test TV"}])

        mock_search.assert_called_once_with(MediaTypes.TV.value, "test", 1, None)

    @patch("app.providers.tmdb.search")
    def test_search_movie(self, mock_search):
        """Test the search function for movies."""
        mock_search.return_value = [{"title": "Test Movie"}]

        result = services.search(MediaTypes.MOVIE.value, "test", 1)

        self.assertEqual(result, [{"title": "Test Movie"}])

        mock_search.assert_called_once_with(MediaTypes.MOVIE.value, "test", 1, None)

    @patch("app.providers.igdb.search")
    def test_search_game(self, mock_search):
        """Test the search function for games."""
        mock_search.return_value = [{"title": "Test Game"}]

        result = services.search(MediaTypes.GAME.value, "test", 1)

        self.assertEqual(result, [{"title": "Test Game"}])

        mock_search.assert_called_once_with("test", 1)

    @patch("app.providers.hardcover.search")
    def test_search_hardcover_book(self, mock_search):
        """Test the search function for books from Hardcover."""
        mock_search.return_value = [{"title": "Test Hardcover Book"}]

        result = services.search(
            MediaTypes.BOOK.value,
            "test",
            1,
            source=Sources.HARDCOVER.value,
        )

        self.assertEqual(result, [{"title": "Test Hardcover Book"}])

        mock_search.assert_called_once_with("test", 1, user=None)

    @patch("app.providers.openlibrary.search")
    def test_search_openlibrary_book(self, mock_search):
        """Test the search function for books."""
        mock_search.return_value = [{"title": "Test Book"}]

        result = services.search(
            MediaTypes.BOOK.value,
            "test",
            1,
            source=Sources.OPENLIBRARY.value,
        )

        self.assertEqual(result, [{"title": "Test Book"}])

        mock_search.assert_called_once_with("test", 1)

    @override_settings(GOOGLE_BOOKS_API_KEY="test-google-key")
    @patch("app.providers.googlebooks.search")
    def test_search_googlebooks_book(self, mock_search):
        """Test the Google Books search provider routing."""
        mock_search.return_value = [{"title": "Test Google Book"}]

        result = services.search(
            MediaTypes.BOOK.value,
            "test",
            1,
            source=Sources.GOOGLEBOOKS.value,
            language="fr",
        )

        self.assertEqual(result, [{"title": "Test Google Book"}])
        mock_search.assert_called_once_with("test", 1, language="fr", user=None)

    @override_settings(GOOGLE_BOOKS_API_KEY="test-google-key")
    @patch("app.providers.googlebooks.search")
    @patch("app.providers.hardcover.search")
    @patch("app.providers.services._resolve_hardcover_isbn_search")
    def test_search_googlebooks_does_not_use_hardcover_isbn_bridge(
        self,
        mock_isbn_search,
        mock_hardcover_search,
        mock_google_search,
    ):
        """Google Books searches must not be replaced by Hardcover ISBN lookup."""
        mock_google_search.return_value = [{"title": "Google result"}]

        result = services.search(
            MediaTypes.BOOK.value,
            "9780123456789",
            1,
            source=Sources.GOOGLEBOOKS.value,
        )

        self.assertEqual(result, [{"title": "Google result"}])
        mock_google_search.assert_called_once_with("9780123456789", 1, language=None, user=None)
        mock_hardcover_search.assert_not_called()
        mock_isbn_search.assert_not_called()

    @override_settings(GOOGLE_BOOKS_API_KEY="")
    @patch("app.providers.googlebooks.search")
    @patch("app.providers.hardcover.search")
    def test_removed_googlebooks_key_falls_back_to_hardcover(
        self,
        mock_hardcover_search,
        mock_google_search,
    ):
        """A stale Google Books selection should fall back after key removal."""
        mock_hardcover_search.return_value = [{"title": "Hardcover result"}]

        result = services.search(
            MediaTypes.BOOK.value,
            "book",
            1,
            source=Sources.GOOGLEBOOKS.value,
        )

        self.assertEqual(result, [{"title": "Hardcover result"}])
        mock_hardcover_search.assert_called_once_with("book", 1, user=None)
        mock_google_search.assert_not_called()

    @patch("app.providers.comicvine.search")
    def test_search_comic(self, mock_search):
        """Test the search function for comics."""
        mock_search.return_value = [{"title": "Test Comic"}]

        result = services.search(MediaTypes.COMIC.value, "test", 1)

        self.assertEqual(result, [{"title": "Test Comic"}])

        mock_search.assert_called_once_with("test", 1, user=None)

    def test_get_media_metadata_returns_local_payload_for_audiobookshelf_books(self):
        """Audiobookshelf books should use local Item metadata, not Open Library."""
        Item.objects.create(
            media_id="abs-book-1",
            source=Sources.AUDIOBOOKSHELF.value,
            media_type=MediaTypes.BOOK.value,
            title="The Blade Itself",
            image="https://img.example/blade.jpg",
            runtime_minutes=123,
            authors=["Joe Abercrombie"],
            isbn=["9780316387310"],
        )

        metadata = services.get_media_metadata(
            MediaTypes.BOOK.value,
            "abs-book-1",
            Sources.AUDIOBOOKSHELF.value,
        )

        self.assertEqual(metadata["title"], "The Blade Itself")
        self.assertEqual(metadata["details"]["author"], ["Joe Abercrombie"])
        self.assertEqual(metadata["details"]["runtime_minutes"], 123)
        self.assertEqual(metadata["source"], Sources.AUDIOBOOKSHELF.value)

    @patch("app.providers.openlibrary.book")
    def test_get_media_metadata_does_not_call_openlibrary_for_audiobookshelf(
        self,
        mock_ol_book,
    ):
        """Audiobookshelf IDs should not be sent to Open Library providers."""
        metadata = services.get_media_metadata(
            MediaTypes.BOOK.value,
            "f9e2ce45ec9315a7c54c",
            Sources.AUDIOBOOKSHELF.value,
        )

        mock_ol_book.assert_not_called()
        self.assertEqual(metadata["source"], Sources.AUDIOBOOKSHELF.value)
        self.assertEqual(metadata["media_id"], "f9e2ce45ec9315a7c54c")
