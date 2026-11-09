"""Permission-aware structured detail endpoint tests."""

from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch

from app.models import MediaTypes, Sources
from integrations.models import IntegrationToken

from .base import FloppyApiTestCase


class DetailPageTests(FloppyApiTestCase):
    """The detail projection separates public metadata from viewer state."""

    def setUp(self):
        super().setUp()
        self.carousel_patch = patch(
            "api.fork_views_detail.carousel.resolve_carousel_media",
            return_value=None,
        )
        self.carousel_patch.start()

    def tearDown(self):
        self.carousel_patch.stop()
        super().tearDown()

    @patch(
        "api.fork_views_detail.services.get_media_metadata",
        return_value={
            "title": "Movie One",
            "original_title": "Film One",
            "synopsis": "A test synopsis.",
            "image": "https://example.com/poster.jpg",
            "genres": ["Drama"],
            "details": {"Release date": "2024-01-01"},
            "cast": [{"name": "Actor One"}],
            "related": {"seasons": []},
        },
    )
    def test_tracked_user_gets_metadata_and_only_own_tracking_state(self, _metadata):
        item = self.items_by_type[MediaTypes.MOVIE.value][0]
        response = self.client.get(
            f"/api/v1/media/{item.media_type}/{item.source}/{item.media_id}/detail/",
            **self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.OK)
        body = response.json()
        self.assertEqual(body["title"], "Movie One")
        self.assertEqual(body["synopsis"], "A test synopsis.")
        self.assertEqual(body["sections"][0]["items"], ["Drama"])
        self.assertTrue(body["capabilities"]["can_update"])
        self.assertFalse(body["read_only"])
        self.assertIsNotNone(body["tracking"])
        self.assertIn("history", body)
        self.assertIn("collections", body)

    @patch(
        "api.fork_views_detail.services.get_media_metadata",
        return_value={"title": "Movie One", "genres": ["Drama"]},
    )
    def test_untracked_signed_in_user_gets_no_other_users_tracking(self, _metadata):
        item = self.items_by_type[MediaTypes.MOVIE.value][0]
        response = self.client.get(
            f"/api/v1/media/{item.media_type}/{item.source}/{item.media_id}/detail/",
            **self.auth_headers2,
        )

        self.assertEqual(response.status_code, HTTP.OK)
        body = response.json()
        self.assertIsNone(body["tracking"])
        self.assertTrue(body["capabilities"]["can_track"])
        self.assertFalse(body["read_only"])

    @patch(
        "api.fork_views_detail.services.get_media_metadata",
        return_value={"title": "Movie One", "genres": ["Drama"]},
    )
    def test_public_view_is_read_only_even_for_a_tracked_item(self, _metadata):
        item = self.items_by_type[MediaTypes.MOVIE.value][0]
        response = self.client.get(
            f"/api/v1/media/{item.media_type}/{item.source}/{item.media_id}/detail/?public_view=1",
            **self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.OK)
        body = response.json()
        self.assertIsNone(body["tracking"])
        self.assertTrue(body["read_only"])
        self.assertFalse(body["capabilities"]["can_track"])
        self.assertFalse(body["capabilities"]["can_update"])
        self.assertEqual(body["history"], [])
        self.assertEqual(body["collections"], [])

    @patch(
        "api.fork_views_detail.services.get_media_metadata",
        return_value={"title": "Public Movie", "genres": ["Drama"]},
    )
    def test_anonymous_request_gets_public_metadata_without_actions(self, _metadata):
        response = self.client.get(
            f"/api/v1/media/{MediaTypes.MOVIE.value}/{Sources.TMDB.value}/public-id/detail/"
        )

        self.assertEqual(response.status_code, HTTP.OK)
        body = response.json()
        self.assertEqual(body["title"], "Public Movie")
        self.assertTrue(body["read_only"])
        self.assertFalse(body["capabilities"]["can_track"])

    @patch(
        "api.fork_views_detail.services.get_media_metadata",
        return_value={"title": "Public video", "synopsis": "A video."},
    )
    def test_video_detail_uses_the_public_provider_projection(self, _metadata):
        response = self.client.get(
            f"/api/v1/media/{MediaTypes.VIDEO.value}/{Sources.YOUTUBE.value}/video-id/detail/"
        )

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["title"], "Public video")
        self.assertTrue(response.json()["read_only"])

    @patch(
        "api.fork_views_detail.services.get_media_metadata",
        return_value={"title": "TV Show 1", "season/2": {
            "title": "TV Show 1", "season_number": 2,
            "synopsis": "Season synopsis", "episodes": [],
        }},
    )
    def test_season_detail_keeps_parent_identity_and_season_coordinate(self, metadata):
        response = self.client.get(
            "/api/v1/media/tv/tmdb/1001/detail/?detail_type=season&season_number=2",
            **self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["identity"]["media_type"], "season")
        self.assertEqual(response.json()["identity"]["parent_media_type"], "tv")
        self.assertEqual(response.json()["synopsis"], "Season synopsis")
        metadata.assert_called_once()
        self.assertEqual(metadata.call_args.args[0], "tv_with_seasons")
        self.assertEqual(metadata.call_args.kwargs["season_numbers"], [2])

    @patch("api.fork_views_detail.tmdb.process_episodes", return_value=[{
        "title": "Blood Money", "episode_number": 1, "season_number": 5,
        "overview": "An episode synopsis.", "image": "https://example.com/still.jpg",
        "history": [],
    }])
    @patch("api.fork_views_detail.services.get_media_metadata", return_value={
        "title": "Breaking Bad", "season/5": {
            "title": "Breaking Bad", "season_number": 5, "media_id": "1396",
            "synopsis": "Season synopsis.", "episodes": [{"episode_number": 1}],
        },
    })
    def test_season_and_episode_project_the_selected_provider_content(self, _metadata, _episodes):
        season = self.client.get(
            "/api/v1/media/tv/tmdb/1396/detail/?detail_type=season&season_number=5",
            **self.auth_headers,
        )
        self.assertEqual(season.status_code, HTTP.OK)
        self.assertEqual(season.json()["synopsis"], "Season synopsis.")
        self.assertEqual(season.json()["children"]["episodes"][0]["title"], "Blood Money")
        episode = self.client.get(
            "/api/v1/media/tv/tmdb/1396/detail/?detail_type=episode&season_number=5&episode_number=1",
            **self.auth_headers,
        )
        self.assertEqual(episode.status_code, HTTP.OK)
        self.assertEqual(episode.json()["title"], "Blood Money")
        self.assertEqual(episode.json()["synopsis"], "An episode synopsis.")

    @patch(
        "api.fork_views_detail.carousel.resolve_carousel_media",
        return_value={
            "hero": {"url": "https://example.com/backdrop.jpg", "logo_url": "https://example.com/logo.png"},
            "overview": {"url": "https://example.com/backdrop.jpg", "logo_url": "https://example.com/logo.png"},
            "photos": [{"url": "https://example.com/still.jpg", "thumb_url": "https://example.com/still-small.jpg"}],
            "video": {"key": "trailer-id"},
        },
    )
    @patch(
        "api.fork_views_detail.services.get_media_metadata",
        return_value={
            "title": "Movie One",
            "synopsis": "A full synopsis.",
            "genres": ["Drama"],
            "related": {
                "recommendations": [{
                    "media_type": "movie",
                    "source": "tmdb",
                    "media_id": "related-1",
                    "title": "Related Movie",
                    "image": "https://example.com/related.jpg",
                }],
            },
        },
    )
    def test_projection_includes_hero_chips_and_recommendation_cards(self, _metadata, _gallery):
        item = self.items_by_type[MediaTypes.MOVIE.value][0]
        response = self.client.get(
            f"/api/v1/media/{item.media_type}/{item.source}/{item.media_id}/detail/",
            **self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.OK)
        body = response.json()
        self.assertEqual(body["artwork"]["backdrop"], "https://example.com/backdrop.jpg")
        self.assertEqual(body["artwork"]["logo"], "https://example.com/logo.png")
        self.assertEqual(body["artwork"]["gallery"]["video"]["key"], "trailer-id")
        self.assertEqual(body["synopsis"], "A full synopsis.")
        self.assertEqual(body["related_sections"][0]["label"], "Recommendations")
        self.assertEqual(body["related_sections"][0]["items"][0]["model"]["title"], "Related Movie")

    @patch(
        "api.fork_views_detail.enrich_detail_seasons",
        return_value=(None, []),
    )
    @patch(
        "api.fork_views_detail.enrich_detail_related_cards",
        return_value=None,
    )
    @patch(
        "api.fork_views_detail.services.get_media_metadata",
        return_value={
            "title": "TV Show",
            "episodes": [
                {"title": f"Episode {number}", "episode_number": number, "season_number": 1}
                for number in range(1, 36)
            ],
        },
    )
    def test_episode_projection_paginates_and_accepts_next_page(self, _metadata, _related, _seasons):
        first = self.client.get("/api/v1/media/tv/tmdb/show-id/detail/", **self.auth_headers)
        second = self.client.get(
            "/api/v1/media/tv/tmdb/show-id/detail/?episode_page=2",
            **self.auth_headers,
        )

        self.assertEqual(first.status_code, HTTP.OK)
        self.assertEqual(second.status_code, HTTP.OK)
        self.assertEqual(first.json()["children"]["next_page"], 2)
        self.assertLess(len(first.json()["children"]["episodes"]), 35)
        self.assertNotEqual(
            first.json()["children"]["episodes"][0]["title"],
            second.json()["children"]["episodes"][0]["title"],
        )

    @patch(
        "api.fork_views_detail.enrich_detail_seasons",
        return_value=(None, []),
    )
    @patch(
        "api.fork_views_detail.services.get_media_metadata",
        return_value={
            "title": "TV Show",
            "episodes": [{
                "title": "Episode 1",
                "season_number": 1,
                "episode_number": 1,
            }],
        },
    )
    def test_episode_actions_are_permission_gated(self, _metadata, _seasons):
        endpoint = "/api/v1/media/tv/tmdb/show-id/detail/"
        signed_in = self.client.get(endpoint, **self.auth_headers)
        public = self.client.get(f"{endpoint}?public_view=1", **self.auth_headers)

        self.assertEqual(signed_in.status_code, HTTP.OK)
        self.assertEqual(public.status_code, HTTP.OK)
        editable_child = signed_in.json()["children"]["episodes"][0]
        readonly_child = public.json()["children"]["episodes"][0]
        self.assertTrue(editable_child["canRate"])
        self.assertEqual(editable_child["actions"][0]["key"], "watch")
        self.assertFalse(readonly_child["canRate"])
        self.assertEqual(readonly_child["actions"], [])

    @patch(
        "api.fork_views_detail.enrich_detail_seasons",
        return_value=(None, []),
    )
    @patch(
        "api.fork_views_detail.services.get_media_metadata",
        return_value={"title": "TV Show", "episodes": [{
            "title": "Episode 1", "season_number": 1, "episode_number": 1,
        }]},
    )
    def test_read_only_integration_token_gets_no_episode_actions(self, _metadata, _seasons):
        _token, raw = IntegrationToken.generate(
            user=self.user1,
            name="Metadata reader",
            scopes=["watchlist:read"],
        )
        response = self.client.get(
            "/api/v1/media/tv/tmdb/show-id/detail/",
            HTTP_AUTHORIZATION=f"Bearer {raw}",
        )

        self.assertEqual(response.status_code, HTTP.OK)
        child = response.json()["children"]["episodes"][0]
        self.assertFalse(child["canRate"])
        self.assertEqual(child["actions"], [])

    @patch("api.fork_views_detail._build_game_lengths_context", return_value=None)
    @patch("api.fork_views_detail.build_book_formats", return_value=[])
    @patch("api.fork_views_detail.enrich_detail_related_cards", return_value=None)
    @patch("api.fork_views_detail.enrich_detail_seasons", return_value=(None, []))
    @patch(
        "api.fork_views_detail.services.get_media_metadata",
        return_value={
            "title": "Structured title",
            "synopsis": "Structured summary.",
            "details": {"Format": "Paperback"},
            "related": {"seasons": [], "recommendations": []},
            "episodes": [],
            "cast": [],
            "crew": [],
        },
    )
    def test_projection_shape_covers_video_book_game_comic_anime_and_manga(
        self, _metadata, _seasons, _related, _book_formats, _game_lengths,
    ):
        identities = [
            (MediaTypes.VIDEO.value, Sources.YOUTUBE.value, "public-video-id"),
            (MediaTypes.BOOK.value, self.items_by_type[MediaTypes.BOOK.value][0].source,
             self.items_by_type[MediaTypes.BOOK.value][0].media_id),
            (MediaTypes.GAME.value, self.items_by_type[MediaTypes.GAME.value][0].source,
             self.items_by_type[MediaTypes.GAME.value][0].media_id),
            (MediaTypes.COMIC.value, self.items_by_type[MediaTypes.COMIC.value][0].source,
             self.items_by_type[MediaTypes.COMIC.value][0].media_id),
            (MediaTypes.ANIME.value, self.items_by_type[MediaTypes.ANIME.value][0].source,
             self.items_by_type[MediaTypes.ANIME.value][0].media_id),
            (MediaTypes.MANGA.value, self.items_by_type[MediaTypes.MANGA.value][0].source,
             self.items_by_type[MediaTypes.MANGA.value][0].media_id),
        ]

        for media_type, source, media_id in identities:
            with self.subTest(media_type=media_type):
                response = self.client.get(
                    f"/api/v1/media/{media_type}/{source}/{media_id}/detail/",
                    **self.auth_headers,
                )
                self.assertEqual(response.status_code, HTTP.OK)
                body = response.json()
                self.assertEqual(body["title"], "Structured title")
                self.assertEqual(body["synopsis"], "Structured summary.")
                self.assertIn("artwork", body)
                self.assertIn("score_chips", body)
                self.assertIn("related_sections", body)
                self.assertNotIn("<", str(body))

    @patch(
        "api.fork_views_detail.carousel.resolve_carousel_media",
        return_value={"hero": {"url": "https://example.com/backdrop.jpg"}, "photos": []},
    )
    def test_deferred_gallery_endpoint_returns_structured_media(self, _gallery):
        response = self.client.get(
            "/api/v1/media/movie/tmdb/123/detail/gallery/",
        )

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["gallery"]["hero"]["url"], "https://example.com/backdrop.jpg")

