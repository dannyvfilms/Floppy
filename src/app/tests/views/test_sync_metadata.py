from unittest.mock import patch

import requests
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from app.models import Item, MediaTypes, PodcastShow, Sources
from app.providers import tmdb, tvdb

User = get_user_model()


class SyncMetadataViewTests(TestCase):
    def setUp(self):
        self.credentials = {"username": "sync-user", "password": "12345"}
        self.user = User.objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    @patch("app.fork_services_podcast.podcast_rss.fetch_feed_from_rss")
    def test_sync_metadata_on_a_podcast_show_uuid_rereads_the_feed(
        self,
        mock_feed,
    ):
        """Regression for issue #1014: the button 404'd on every podcast show.

        A podcast route addresses a show by podcast_uuid, which only ever
        resolved as an episode uuid, so the sync answered
        "Podcast episode with ID gp_... not found". A show also has no Item row
        of its own, so the generic path must not run and mint one.
        """
        show = PodcastShow.objects.create(
            podcast_uuid="gp_75aa1669b361ba1e0a22d07adddfb7f1",
            source=Sources.GPODDER.value,
            title="The Jeff Gerstmann Show",
            rss_feed_url="https://feeds.megaphone.fm/QCD5913450294",
        )
        mock_feed.return_value = (
            {
                "title": "The Jeff Gerstmann Show",
                "website_url": "https://example.com/jeff",
            },
            [],
        )

        response = self.client.post(
            reverse(
                "sync_metadata",
                kwargs={
                    "source": Sources.GPODDER.value,
                    "media_type": MediaTypes.PODCAST.value,
                    "media_id": show.podcast_uuid,
                },
            ),
            {"next": "/"},
        )

        self.assertEqual(response.status_code, 302)
        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertIn("Metadata synced successfully.", messages)

        show.refresh_from_db()
        self.assertEqual(show.website_url, "https://example.com/jeff")
        self.assertFalse(
            Item.objects.filter(media_id=show.podcast_uuid).exists(),
            "the show uuid must not gain an Item row of its own",
        )

    @patch(
        "app.fork_services_podcast.podcast_rss.fetch_feed_from_rss",
        side_effect=requests.exceptions.ConnectionError("boom"),
    )
    def test_sync_metadata_on_a_podcast_show_survives_an_unreachable_feed(
        self,
        _mock_feed,
    ):
        show = PodcastShow.objects.create(
            podcast_uuid="gp_unreachable",
            source=Sources.GPODDER.value,
            title="Unreachable",
            rss_feed_url="https://example.com/gone.xml",
        )

        response = self.client.post(
            reverse(
                "sync_metadata",
                kwargs={
                    "source": Sources.GPODDER.value,
                    "media_type": MediaTypes.PODCAST.value,
                    "media_id": show.podcast_uuid,
                },
            ),
            {"next": "/"},
        )

        self.assertEqual(response.status_code, 302)

    @patch("app.tasks_imdb.refresh_imdb_game_credits_from_datasets.apply_async")
    @patch("app.metadata_sync_views._sync_plex_rating")
    @patch("app.views.Item.fetch_releases")
    @patch("app.views.game_length_services.refresh_game_lengths")
    @patch("app.views.services.get_media_metadata")
    def test_sync_metadata_refreshes_game_lengths_for_igdb_games(
        self,
        mock_get_media_metadata,
        mock_refresh_game_lengths,
        mock_fetch_releases,
        mock_sync_plex_rating,
        _mock_refresh_imdb_credits,
    ):
        mock_get_media_metadata.return_value = {
            "media_id": "325609",
            "title": "Dispatch",
            "media_type": MediaTypes.GAME.value,
            "source": Sources.IGDB.value,
            "image": "https://example.com/dispatch.jpg",
            "details": {
                "format": "Main game",
                "release_date": "2025-10-22",
                "platforms": ["PC", "PlayStation 5"],
            },
            "genres": ["Action"],
            "related": {},
            "external_links": {
                "HowLongToBeat": "https://howlongtobeat.com/?q=Dispatch",
            },
        }

        response = self.client.post(
            reverse(
                "sync_metadata",
                kwargs={
                    "source": Sources.IGDB.value,
                    "media_type": MediaTypes.GAME.value,
                    "media_id": "325609",
                },
            ),
            {"next": "/"},
        )

        self.assertEqual(response.status_code, 302)
        mock_refresh_game_lengths.assert_called_once()
        _, kwargs = mock_refresh_game_lengths.call_args
        self.assertTrue(kwargs["force"])
        self.assertTrue(kwargs["fetch_hltb"])
        mock_fetch_releases.assert_called_once()
        mock_sync_plex_rating.assert_called_once()

    @patch("app.metadata_sync_views._sync_plex_rating")
    @patch("app.views.Item.fetch_releases")
    @patch("app.views.trakt_popularity_service.refresh_trakt_popularity")
    @patch("app.views.services.get_media_metadata")
    def test_sync_metadata_refreshes_trakt_popularity_for_movies(
        self,
        mock_get_media_metadata,
        mock_refresh_trakt_popularity,
        mock_fetch_releases,
        mock_sync_plex_rating,
    ):
        mock_get_media_metadata.return_value = {
            "media_id": "238",
            "title": "The Godfather",
            "media_type": MediaTypes.MOVIE.value,
            "source": Sources.TMDB.value,
            "image": "https://example.com/godfather.jpg",
            "details": {
                "release_date": "1972-03-14",
            },
            "related": {},
        }

        response = self.client.post(
            reverse(
                "sync_metadata",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.MOVIE.value,
                    "media_id": "238",
                },
            ),
            {"next": "/"},
        )

        self.assertEqual(response.status_code, 302)
        mock_refresh_trakt_popularity.assert_called_once()
        _, kwargs = mock_refresh_trakt_popularity.call_args
        self.assertEqual(kwargs["route_media_type"], MediaTypes.MOVIE.value)
        self.assertTrue(kwargs["force"])
        mock_fetch_releases.assert_called_once()
        mock_sync_plex_rating.assert_called_once()

    @patch("app.metadata_sync_views._sync_plex_rating")
    @patch("app.views.Item.fetch_releases")
    @patch("app.views.credits.sync_item_credits_from_metadata")
    @patch("app.views.trakt_popularity_service.refresh_trakt_popularity")
    @patch("app.views.metadata_resolution.upsert_provider_links")
    @patch("app.views.services.get_media_metadata")
    def test_sync_metadata_preserves_tmdb_tv_anime_genre_supplement(
        self,
        mock_get_media_metadata,
        mock_upsert_provider_links,
        mock_refresh_trakt_popularity,
        mock_sync_item_credits,
        mock_fetch_releases,
        mock_sync_plex_rating,
    ):
        item = Item.objects.create(
            media_id="2002",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Manual Refresh Anime",
            image="https://example.com/manual-refresh-anime.jpg",
            genres=["Comedy", "Anime"],
        )
        mock_get_media_metadata.return_value = {
            "media_id": item.media_id,
            "title": item.title,
            "media_type": MediaTypes.TV.value,
            "source": Sources.TMDB.value,
            "image": item.image,
            "genres": ["Comedy"],
            "details": {
                "format": "TV",
                "release_date": "2024-01-01",
            },
            "related": {},
        }

        response = self.client.post(
            reverse(
                "sync_metadata",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.TV.value,
                    "media_id": item.media_id,
                },
            ),
            {"next": "/"},
        )

        item.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(item.genres, ["Comedy", "Anime"])
        # A second upsert may fire for the user's preferred provider; the
        # source-provider upsert is the one this test cares about.
        mock_upsert_provider_links.assert_any_call(
            item,
            mock_get_media_metadata.return_value,
            provider=Sources.TMDB.value,
            provider_media_type=MediaTypes.TV.value,
            season_number=None,
        )
        mock_refresh_trakt_popularity.assert_called_once()
        mock_sync_item_credits.assert_called_once()
        mock_fetch_releases.assert_called_once()
        mock_sync_plex_rating.assert_called_once()

    @patch("app.metadata_sync_views._sync_plex_rating")
    @patch("app.views.Item.fetch_releases")
    @patch("app.views.credits.sync_item_credits_from_metadata")
    @patch("app.views.trakt_popularity_service.refresh_trakt_popularity")
    @patch("app.views.metadata_resolution.upsert_provider_links")
    @patch("app.views.services.get_media_metadata")
    def test_sync_metadata_scopes_to_anime_bucket_and_preserves_library_media_type(
        self,
        mock_get_media_metadata,
        mock_upsert_provider_links,
        mock_refresh_trakt_popularity,
        mock_sync_item_credits,
        mock_fetch_releases,
        mock_sync_plex_rating,
    ):
        tv_item = Item.objects.create(
            media_id="387",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=2,
            title="Spongebob Squarepants",
            image="https://example.com/tv.jpg",
        )
        anime_item = Item.objects.create(
            media_id="387",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=2,
            library_media_type=MediaTypes.ANIME.value,
            title="Spongebob Squarepants (Anime)",
            image="https://example.com/anime.jpg",
        )
        mock_get_media_metadata.return_value = {
            "media_id": "387",
            "title": "Spongebob Squarepants Season 2",
            "media_type": MediaTypes.SEASON.value,
            "source": Sources.TMDB.value,
            "image": "https://example.com/refreshed.jpg",
            "details": {},
            "related": {},
            "episodes": [],
        }

        response = self.client.post(
            reverse(
                "sync_metadata",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.SEASON.value,
                    "media_id": "387",
                    "season_number": 2,
                },
            ),
            {"next": "/", "library_media_type": MediaTypes.ANIME.value},
        )

        self.assertEqual(response.status_code, 302)

        tv_item.refresh_from_db()
        anime_item.refresh_from_db()

        # Only the anime-bucketed row should have been refreshed.
        self.assertEqual(anime_item.title, "Spongebob Squarepants Season 2")
        self.assertEqual(anime_item.image, "https://example.com/refreshed.jpg")

        # The sibling TV-bucketed row must be untouched, and neither row's
        # library_media_type should have been reclassified by the sync.
        self.assertEqual(tv_item.title, "Spongebob Squarepants")
        self.assertEqual(tv_item.image, "https://example.com/tv.jpg")
        self.assertEqual(tv_item.library_media_type, MediaTypes.SEASON.value)
        self.assertEqual(anime_item.library_media_type, MediaTypes.ANIME.value)

    @patch("app.views.services.get_media_metadata")
    def test_sync_metadata_restores_cached_entry_and_returns_error_for_htmx_failures(
        self,
        mock_get_media_metadata,
    ):
        cache_key = tmdb._season_cache_key("294737", 1)
        cached_payload = {"title": "Cached Season"}
        cache.set(cache_key, cached_payload, timeout=600)
        mock_get_media_metadata.side_effect = requests.exceptions.ConnectionError(
            "dns failure",
        )

        response = self.client.post(
            reverse(
                "sync_metadata",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.SEASON.value,
                    "media_id": "294737",
                    "season_number": 1,
                },
            ),
            {"next": "/details/tmdb/season/294737/1"},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            response["HX-Redirect"],
            "/details/tmdb/season/294737/1",
        )
        self.assertEqual(cache.get(cache_key), cached_payload)
        messages = [message.message for message in get_messages(response.wsgi_request)]
        self.assertEqual(len(messages), 1)
        self.assertIn("could not be reached", messages[0].lower())
        self.assertIn("cached data has been kept", messages[0].lower())

    def test_sync_metadata_invalidates_versioned_tvdb_series_and_season_keys(self):
        """TVDB refreshes should clear normalized, raw, and season cache entries."""
        media_id = "81189"
        season_number = 1
        cache_keys = tvdb.metadata_cache_keys(media_id, season_number)
        primary_key = tvdb._season_cache_key(
            media_id,
            season_number,
            MediaTypes.TV.value,
            tvdb._preferred_language_code(),
        )
        for cache_key in cache_keys:
            cache.set(cache_key, {"cached": True}, timeout=600)

        metadata = {
            "media_id": media_id,
            "source": Sources.TVDB.value,
            "media_type": MediaTypes.SEASON.value,
            "title": "Breaking Bad Season 1",
            "image": "https://example.com/season.jpg",
            "details": {},
            "related": {},
            "episodes": [],
        }
        with (
            patch(
                "app.metadata_sync_views.services.get_media_metadata",
                return_value=metadata,
            ),
            patch("app.metadata_sync_views.metadata_resolution.upsert_provider_links"),
            patch(
                "app.metadata_sync_views.metadata_resolution.get_preferred_provider",
                return_value=Sources.TVDB.value,
            ),
            patch("app.metadata_sync_views.cache.delete_many") as mock_delete_many,
            patch("app.metadata_sync_views._sync_plex_rating"),
            patch("app.views.Item.fetch_releases"),
            patch("app.views.trakt_popularity_service.refresh_trakt_popularity"),
        ):
            response = self.client.post(
                reverse(
                    "sync_metadata",
                    kwargs={
                        "source": Sources.TVDB.value,
                        "media_type": MediaTypes.SEASON.value,
                        "media_id": media_id,
                        "season_number": season_number,
                    },
                ),
                {"next": "/"},
            )

        self.assertEqual(response.status_code, 302)
        mock_delete_many.assert_called_once()
        deleted_keys = mock_delete_many.call_args.args[0]
        # The refresh reads its TTL from the first key, so the one this request
        # is actually about has to lead; the rest are order-independent.
        self.assertEqual(deleted_keys[0], primary_key)
        self.assertEqual(set(deleted_keys), set(cache_keys))

    def test_tvdb_refresh_keys_reach_language_qualified_cache_entries(self):
        """TVDB refresh helpers should evict the keys used by localized fetches."""
        from app import metadata_utils

        language = "es"
        keys = metadata_utils.provider_metadata_cache_keys(
            Sources.TVDB.value,
            MediaTypes.SEASON.value,
            "81189",
            season_number=1,
            language=language,
        )
        expected_keys = {
            tvdb._cache_key(
                MediaTypes.TV.value,
                "81189",
                tvdb._preferred_language_code(language),
            ),
            tvdb._season_cache_key("81189", 1, MediaTypes.TV.value, language),
            tvdb._series_extended_cache_key("81189", language),
            tvdb._cache_key(
                "series_extended",
                MediaTypes.TV.value,
                "81189",
                tvdb._preferred_language_code(language),
            ),
            tvdb._series_episode_translations_cache_key("81189", language),
        }

        self.assertTrue(expected_keys.issubset(keys))
        for key in expected_keys:
            cache.set(key, {"cached": True}, timeout=600)

        cache.delete_many(keys)

        for key in expected_keys:
            self.assertIsNone(cache.get(key))

    @patch("app.metadata_sync_views._sync_plex_rating")
    @patch("app.views.Item.fetch_releases")
    @patch("app.views.services.get_media_metadata")
    def test_sync_metadata_forces_live_refetch_on_next_detail_view(
        self,
        mock_get_media_metadata,
        mock_fetch_releases,
        mock_sync_plex_rating,
    ):
        """The detail page right after a sync must not fall back to the
        Item-only stub, which drops score/cast/recommendations (#931).
        """
        full_metadata = {
            "media_id": "603",
            "title": "The Matrix",
            "media_type": MediaTypes.MOVIE.value,
            "source": Sources.TMDB.value,
            "image": "https://example.com/matrix.jpg",
            "synopsis": "A hacker learns the truth about reality.",
            "genres": ["Action"],
            "score": 8.2,
            "score_count": 24000,
            "cast": [{"name": "Keanu Reeves", "character": "Neo"}],
            "crew": [],
            "studios_full": [],
            "details": {"release_date": "1999-03-31"},
            "related": {},
        }
        mock_get_media_metadata.return_value = full_metadata

        sync_response = self.client.post(
            reverse(
                "sync_metadata",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.MOVIE.value,
                    "media_id": "603",
                },
            ),
            {"next": "/"},
        )
        self.assertEqual(sync_response.status_code, 302)

        item = Item.objects.get(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
        )
        self.assertIsNotNone(item.metadata_fetched_at)
        mock_get_media_metadata.reset_mock()

        detail_response = self.client.get(
            reverse(
                "media_details",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.MOVIE.value,
                    "media_id": "603",
                    "title": "the-matrix",
                },
            ),
        )

        self.assertEqual(detail_response.status_code, 200)
        mock_get_media_metadata.assert_called_once()
        self.assertContains(detail_response, "8.2")

    @patch("app.metadata_sync_views._sync_plex_rating")
    @patch("app.views.Item.fetch_releases")
    @patch("app.views.services.get_media_metadata")
    def test_synced_item_keeps_score_and_links_after_force_live_window_expires(
        self,
        mock_get_media_metadata,
        mock_fetch_releases,
        mock_sync_plex_rating,
    ):
        """Issue #1077: the rating chip and external links vanished about a
        minute after a sync, once the force-live marker expired and the detail
        shell fell back to the stored Item.
        """
        Item.objects.create(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Matrix",
            image="https://example.com/matrix.jpg",
            provider_external_ids={
                "imdb_id": "tt0133093",
                "wikidata_id": "Q83495",
            },
        )
        mock_get_media_metadata.return_value = {
            "media_id": "603",
            "title": "The Matrix",
            "media_type": MediaTypes.MOVIE.value,
            "source": Sources.TMDB.value,
            "image": "https://example.com/matrix.jpg",
            "synopsis": "A hacker learns the truth about reality.",
            "genres": ["Action"],
            "score": 8.2,
            "score_count": 24000,
            "external_links": {"IMDb": "https://www.imdb.com/title/tt0133093/"},
            "cast": [],
            "crew": [],
            "studios_full": [],
            "details": {"release_date": "1999-03-31"},
            "related": {},
        }

        sync_response = self.client.post(
            reverse(
                "sync_metadata",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.MOVIE.value,
                    "media_id": "603",
                },
            ),
            {"next": "/"},
        )
        self.assertEqual(sync_response.status_code, 302)

        # The force-live marker lasts 60 seconds; after that the shell serves
        # stored metadata and must still carry the rating and the links.
        cache.clear()
        mock_get_media_metadata.reset_mock()

        detail_response = self.client.get(
            reverse(
                "media_details",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.MOVIE.value,
                    "media_id": "603",
                    "title": "the-matrix",
                },
            ),
        )

        self.assertEqual(detail_response.status_code, 200)
        mock_get_media_metadata.assert_not_called()
        self.assertEqual(detail_response.context["media"]["score"], 8.2)
        self.assertEqual(detail_response.context["media"]["score_count"], 24000)
        external_section = next(
            section
            for section in detail_response.context["detail_link_sections"]
            if section["title"] == "External links"
        )
        self.assertEqual(
            {entry["label"] for entry in external_section["entries"]},
            {"Letterboxd", "IMDb", "Wikidata"},
        )

    @patch("app.metadata_sync_views._sync_plex_rating")
    @patch("app.views.Item.fetch_releases")
    @patch("app.views.services.get_media_metadata")
    def test_sync_metadata_keeps_stored_page_count_for_non_books(
        self,
        mock_get_media_metadata,
        mock_fetch_releases,
        mock_sync_plex_rating,
    ):
        """Only books resolve a page count during a sync, so a manga's stored
        count must survive instead of being nulled (#1077).
        """
        Item.objects.create(
            media_id="11",
            source=Sources.MAL.value,
            media_type=MediaTypes.MANGA.value,
            title="Naruto",
            image="https://example.com/naruto.jpg",
            number_of_pages=700,
        )
        mock_get_media_metadata.return_value = {
            "media_id": "11",
            "title": "Naruto",
            "media_type": MediaTypes.MANGA.value,
            "source": Sources.MAL.value,
            "image": "https://example.com/naruto.jpg",
            "synopsis": "A ninja story.",
            "genres": ["Action"],
            "cast": [],
            "crew": [],
            "studios_full": [],
            "details": {},
            "related": {},
        }

        response = self.client.post(
            reverse(
                "sync_metadata",
                kwargs={
                    "source": Sources.MAL.value,
                    "media_type": MediaTypes.MANGA.value,
                    "media_id": "11",
                },
            ),
            {"next": "/"},
        )

        self.assertEqual(response.status_code, 302)
        item = Item.objects.get(
            media_id="11",
            source=Sources.MAL.value,
            media_type=MediaTypes.MANGA.value,
        )
        self.assertEqual(item.number_of_pages, 700)
