from unittest.mock import patch

from django.core.cache import cache
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase

from app import carousel
from app.models import MediaTypes, Sources
from app.providers import tmdb


class CarouselOverviewTests(SimpleTestCase):
    def setUp(self):
        image_url_patch = patch("app.carousel.rewrite_image_url", side_effect=lambda url: url)
        image_url_patch.start()
        self.addCleanup(image_url_patch.stop)

    @patch("app.providers.tmdb.get_carousel_image_url")
    @patch("app.providers.tmdb.carousel_media")
    def test_tmdb_movie_adds_backdrop_and_logo_as_overview(
        self, mock_media, mock_image_url
    ):
        mock_media.return_value = {
            "video": {"key": "trailer"},
            "photos": [{"file_path": "/backdrop.jpg", "width": 1600, "height": 900}],
            "logos": ["/logo.png"],
            "backdrop_path": "/backdrop.jpg",
        }
        mock_image_url.side_effect = lambda path, size: f"{size}{path}"

        result = carousel.resolve_carousel_media(
            MediaTypes.MOVIE.value, Sources.TMDB.value, "42"
        )

        self.assertEqual(
            result["overview"],
            {
                "url": "w1280/backdrop.jpg",
                "thumb_url": "w300/backdrop.jpg",
                "logo_url": "w500/logo.png",
            },
        )
        self.assertEqual(result["photos"], [])

    @patch("app.providers.tmdb.get_carousel_image_url")
    @patch("app.providers.tmdb.carousel_media")
    def test_overview_images_go_through_the_image_cache(self, mock_media, mock_image_url):
        mock_media.return_value = {
            "video": None,
            "photos": [{"file_path": "/backdrop.jpg"}, {"file_path": "/other.jpg"}],
            "logos": ["/logo.png"],
            "backdrop_path": "/backdrop.jpg",
        }
        mock_image_url.side_effect = lambda path, size: f"{size}{path}"

        with patch(
            "app.carousel.rewrite_image_url", side_effect=lambda url: f"cached:{url}"
        ):
            result = carousel.resolve_carousel_media(
                MediaTypes.MOVIE.value, Sources.TMDB.value, "42"
            )

        self.assertEqual(
            result["overview"],
            {
                "url": "cached:w1280/backdrop.jpg",
                "thumb_url": "cached:w300/backdrop.jpg",
                "logo_url": "cached:w500/logo.png",
            },
        )
        # The duplicate of the overview backdrop is still dropped from the photos.
        self.assertEqual([p["url"] for p in result["photos"]], ["cached:w1280/other.jpg"])

    def test_tmdb_season_prefers_season_backdrop_and_parent_logo(self):
        season_data = {
            "video": None,
            "photos": [{"file_path": "/season-backdrop.jpg", "width": 1600, "height": 900}],
            "logos": ["/season-logo.png"],
            "backdrop_path": "/season-backdrop.jpg",
        }
        show_data = {
            "video": None,
            "photos": [],
            "logos": ["/show-logo.png"],
            "backdrop_path": "/show-backdrop.jpg",
        }
        with (
            patch("app.providers.tmdb.carousel_media", side_effect=[season_data, show_data]),
            patch(
                "app.providers.tmdb.get_carousel_image_url",
                side_effect=lambda path, size: f"{size}{path}",
            ),
        ):
            result = carousel.resolve_carousel_media(
                MediaTypes.SEASON.value,
                Sources.TMDB.value,
                "108978",
                season_number=1,
            )

        self.assertEqual(result["overview"]["url"], "w1280/season-backdrop.jpg")
        self.assertEqual(result["overview"]["logo_url"], "w500/show-logo.png")

    @patch("app.providers.tmdb.get_carousel_image_url")
    @patch("app.providers.tmdb.carousel_media")
    def test_phone_hero_carries_backdrop_and_logo(self, mock_media, mock_image_url):
        mock_media.return_value = {
            "video": None,
            "photos": [{"file_path": "/backdrop.jpg"}],
            "logos": ["/logo.png"],
            "backdrop_path": "/backdrop.jpg",
        }
        mock_image_url.side_effect = lambda path, size: f"{size}{path}"

        result = carousel.resolve_carousel_media(
            MediaTypes.MOVIE.value, Sources.TMDB.value, "42"
        )

        self.assertEqual(
            result["hero"], {"url": "w1280/backdrop.jpg", "logo_url": "w500/logo.png"}
        )

    @patch("app.providers.tmdb.get_carousel_image_url")
    @patch("app.providers.tmdb.carousel_media")
    def test_phone_hero_without_a_logo_keeps_the_backdrop_for_a_text_title(
        self, mock_media, mock_image_url
    ):
        mock_media.return_value = {
            "video": None,
            "photos": [{"file_path": "/backdrop.jpg"}],
            "logos": [],
            "backdrop_path": "/backdrop.jpg",
        }
        mock_image_url.side_effect = lambda path, size: f"{size}{path}"

        result = carousel.resolve_carousel_media(
            MediaTypes.MOVIE.value, Sources.TMDB.value, "42"
        )

        # No logo means no desktop overview, but the phone hero still gets the art.
        self.assertIsNone(result["overview"])
        self.assertEqual(result["hero"], {"url": "w1280/backdrop.jpg", "logo_url": None})

    @patch("app.providers.tmdb.get_carousel_image_url")
    @patch("app.providers.tmdb.carousel_media")
    def test_a_lone_backdrop_still_builds_the_hero_and_a_one_image_carousel(
        self, mock_media, mock_image_url
    ):
        # TMDB can return a top-level backdrop with no gallery, trailer or logo.
        mock_media.return_value = {
            "video": None,
            "photos": [],
            "logos": [],
            "backdrop_path": "/backdrop.jpg",
        }
        mock_image_url.side_effect = lambda path, size: f"{size}{path}"

        result = carousel.resolve_carousel_media(
            MediaTypes.MOVIE.value, Sources.TMDB.value, "42"
        )

        self.assertEqual(result["hero"], {"url": "w1280/backdrop.jpg", "logo_url": None})
        self.assertEqual(
            result["photos"],
            [{"url": "w1280/backdrop.jpg", "thumb_url": "w300/backdrop.jpg"}],
        )

    @patch("app.providers.tmdb.carousel_media")
    def test_no_backdrop_means_no_phone_hero(self, mock_media):
        mock_media.return_value = {
            "video": {"key": "trailer"},
            "photos": [],
            "logos": [],
            "backdrop_path": None,
        }

        with patch("app.backdrops.resolve_backdrop", return_value=None):
            result = carousel.resolve_carousel_media(
                MediaTypes.MOVIE.value, Sources.TMDB.value, "42"
            )

        self.assertIsNone(result["hero"])

    @patch("lists.models.CustomList._get_igdb_carousel_media")
    def test_igdb_phone_hero_without_a_logo_keeps_the_hero_image(self, mock_media):
        mock_media.return_value = {
            "video": None,
            "photos": ["art1", "shot2"],
            "hero_image_id": "art1",
            "logo_image_id": None,
        }

        result = carousel.resolve_carousel_media(
            MediaTypes.GAME.value, Sources.IGDB.value, "123"
        )

        self.assertIsNone(result["overview"])
        self.assertIn("art1", result["hero"]["url"])
        self.assertIsNone(result["hero"]["logo_url"])

    @patch("lists.models.CustomList._get_igdb_carousel_media")
    def test_igdb_game_adds_game_logo_and_omits_duplicate_hero_photo(self, mock_media):
        mock_media.return_value = {
            "video": None,
            "photos": ["art1", "shot2"],
            "hero_image_id": "art1",
            "logo_image_id": "logo1",
        }

        result = carousel.resolve_carousel_media(
            MediaTypes.GAME.value, Sources.IGDB.value, "123"
        )

        self.assertEqual(result["overview"]["logo_url"], "https://images.igdb.com/igdb/image/upload/t_logo_med/logo1.png")
        self.assertEqual(len(result["photos"]), 1)
        self.assertIn("shot2", result["photos"][0]["url"])

    def test_tmdb_logo_parser_prefers_english_then_neutral_then_other(self):
        logos = tmdb._parse_carousel_logos(
            {
                "images": {
                    "logos": [
                        {"file_path": "/fr.png", "iso_639_1": "fr"},
                        {"file_path": "/none.png", "iso_639_1": None},
                        {"file_path": "/en.png", "iso_639_1": "en"},
                    ]
                }
            }
        )

        self.assertEqual(logos, ["/en.png", "/none.png", "/fr.png"])

    def test_overview_is_the_initial_strip_item(self):
        html = render_to_string(
            "app/components/detail_carousel_fragment.html",
            {
                "carousel": {
                    "overview": {
                        "url": "https://images.example.com/backdrop.jpg",
                        "thumb_url": "https://images.example.com/thumb.jpg",
                        "logo_url": "https://images.example.com/logo.png",
                    },
                    "video": {"key": "trailer"},
                    "photos": [],
                }
            },
        )

        self.assertLess(html.index("Overview"), html.index("mqdefault.jpg"))
        self.assertIn("detail-carousel-overview-logo", html)


    def test_fragment_renders_the_phone_hero_only_when_there_is_one(self):
        base = {"video": {"key": "trailer"}, "photos": [], "overview": None}

        with_logo = render_to_string(
            "app/components/detail_carousel_fragment.html",
            {"carousel": {**base, "hero": {"url": "https://x.test/b.jpg", "logo_url": "https://x.test/l.png"}}},
        )
        text_only = render_to_string(
            "app/components/detail_carousel_fragment.html",
            {"carousel": {**base, "hero": {"url": "https://x.test/b.jpg", "logo_url": None}}},
        )
        without = render_to_string(
            "app/components/detail_carousel_fragment.html",
            {"carousel": {**base, "hero": None}},
        )

        self.assertIn("detail-mobile-hero__logo", with_logo)
        self.assertIn("detail-mobile-hero__sharp", text_only)
        self.assertNotIn("detail-mobile-hero__logo", text_only)
        self.assertNotIn("detail-mobile-hero", without)


class IgdbCarouselOverviewTests(TestCase):
    def tearDown(self):
        cache.clear()
        super().tearDown()

    @patch("app.providers.igdb.get_access_token", return_value="token")
    @patch(
        "app.providers.services.api_request",
        side_effect=[
            [
                {
                    "id": 123,
                    "logo": {"image_id": "game-logo"},
                    "artworks": [],
                    "screenshots": [{"image_id": "game-screen"}],
                }
            ],
            [],
        ],
    )
    def test_igdb_carousel_fetch_includes_game_logo(self, mock_api, _mock_token):
        from lists.models import CustomList

        data = CustomList()._get_igdb_carousel_media("123")

        self.assertIn("logo.image_id", mock_api.call_args_list[0].kwargs["data"])
        self.assertEqual(data["logo_image_id"], "game-logo")
        self.assertEqual(data["hero_image_id"], "game-screen")

    @patch("app.providers.igdb.get_access_token", side_effect=RuntimeError("down"))
    def test_igdb_carousel_fetch_failure_returns_empty_media(self, _mock_token):
        from lists.models import CustomList

        data = CustomList()._get_igdb_carousel_media("123")

        self.assertEqual(data["photos"], [])
        self.assertIsNone(data["logo_image_id"])
        self.assertIsNone(data["hero_image_id"])
