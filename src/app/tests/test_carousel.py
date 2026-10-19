from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from app import carousel
from app.game_artwork.base import Art
from app.models import GameArtwork, Item, MediaTypes, Sources
from app.providers import services, tmdb

IGDB_HERO = Art(
    "https://images.igdb.com/igdb/image/upload/t_1080p/art1.jpg", "igdb", "art1"
)
SGDB_LOGO = Art("https://cdn2.steamgriddb.com/logo/1.png", "steamgriddb", "9")


class CarouselOverviewTests(SimpleTestCase):
    def setUp(self):
        gallery_patch = patch("app.game_artwork.gallery", return_value=[])
        gallery_patch.start()
        self.addCleanup(gallery_patch.stop)
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

    @patch("app.carousel._game_artwork")
    @patch("lists.models.CustomList._get_igdb_carousel_media")
    def test_igdb_phone_hero_without_a_logo_keeps_the_hero_image(
        self, mock_media, mock_artwork
    ):
        mock_media.return_value = {
            "video": None,
            "photos": ["art1", "shot2"],
            "hero_image_id": "art1",
        }
        mock_artwork.return_value = {"logo": None, "backdrop": IGDB_HERO}

        result = carousel.resolve_carousel_media(
            MediaTypes.GAME.value, Sources.IGDB.value, "123"
        )

        self.assertIsNone(result["overview"])
        self.assertIn("art1", result["hero"]["url"])
        self.assertIsNone(result["hero"]["logo_url"])

    @patch("app.carousel._game_artwork")
    @patch("lists.models.CustomList._get_igdb_carousel_media")
    def test_igdb_game_adds_game_logo_and_omits_duplicate_hero_photo(
        self, mock_media, mock_artwork
    ):
        mock_media.return_value = {
            "video": None,
            "photos": ["art1", "shot2"],
            "hero_image_id": "art1",
        }
        mock_artwork.return_value = {"logo": SGDB_LOGO, "backdrop": IGDB_HERO}

        result = carousel.resolve_carousel_media(
            MediaTypes.GAME.value, Sources.IGDB.value, "123"
        )

        self.assertEqual(result["overview"]["logo_url"], SGDB_LOGO.url)
        self.assertEqual(len(result["photos"]), 1)
        self.assertIn("shot2", result["photos"][0]["url"])

    @patch("app.carousel._game_artwork")
    @patch("lists.models.CustomList._get_igdb_carousel_media")
    def test_provider_backdrop_replaces_the_igdb_hero_in_the_overview(
        self, mock_media, mock_artwork
    ):
        mock_media.return_value = {
            "video": None,
            "photos": ["art1", "shot2"],
            "hero_image_id": "art1",
        }
        backdrop = Art("https://cdn2.steamgriddb.com/hero/1.jpg", "steamgriddb", "5")
        mock_artwork.return_value = {"logo": SGDB_LOGO, "backdrop": backdrop}

        result = carousel.resolve_carousel_media(
            MediaTypes.GAME.value, Sources.IGDB.value, "123"
        )

        self.assertEqual(result["overview"]["url"], backdrop.url)
        self.assertEqual(result["hero"]["url"], backdrop.url)
        # IGDB's own artwork stays in the gallery when it is not the overview.
        self.assertEqual(len(result["photos"]), 2)

    @patch("app.carousel._game_artwork")
    @patch("lists.models.CustomList._get_igdb_carousel_media")
    def test_game_with_only_provider_art_still_gets_an_overview(
        self, mock_media, mock_artwork
    ):
        mock_media.return_value = {"video": None, "photos": [], "hero_image_id": None}
        backdrop = Art("https://cdn2.steamgriddb.com/hero/1.jpg", "steamgriddb", "5")
        mock_artwork.return_value = {"logo": SGDB_LOGO, "backdrop": backdrop}

        result = carousel.resolve_carousel_media(
            MediaTypes.GAME.value, Sources.IGDB.value, "123"
        )

        self.assertEqual(result["overview"]["logo_url"], SGDB_LOGO.url)

    @patch("app.game_artwork.resolve", side_effect=RuntimeError("down"))
    @patch("app.providers.igdb.game", return_value={"title": "Game"})
    def test_artwork_failure_falls_back_to_igdb_art(self, _game, _resolve):
        result = carousel._game_artwork("123", "art1")

        self.assertIsNone(result["logo"])
        self.assertEqual(result["backdrop"], IGDB_HERO)

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


class GameCarouselRetryTests(TestCase):
    """A game counts as empty only once its artwork lookup settled."""

    def setUp(self):
        gallery_patch = patch("app.game_artwork.gallery", return_value=[])
        gallery_patch.start()
        self.addCleanup(gallery_patch.stop)
        cache.set("igdb_carousel_v4_123", {"video": None, "photos": []}, 60)

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def empty(self):
        return carousel.confirmed_empty(MediaTypes.GAME.value, Sources.IGDB.value, "123")

    def row(self, **overrides):
        values = {"source": Sources.IGDB.value, "media_id": "123"}
        return GameArtwork.objects.create(**{**values, **overrides})

    def test_no_row_means_the_lookup_may_still_run(self):
        # A provider error stores nothing, so the page must still ask again.
        self.assertFalse(self.empty())

    def test_a_fresh_miss_is_confirmed_empty(self):
        self.row()

        self.assertTrue(self.empty())

    def test_an_old_miss_is_looked_up_again(self):
        row = self.row()
        GameArtwork.objects.filter(pk=row.pk).update(
            resolved_at=timezone.now() - timedelta(days=1)
        )

        self.assertFalse(self.empty())

    def test_a_game_with_a_logo_and_backdrop_is_not_empty(self):
        self.row(logo_url="https://x/logo.png", backdrop_url="https://x/hero.jpg")

        self.assertFalse(self.empty())

    @patch("app.carousel._game_artwork")
    @patch("lists.models.CustomList._get_igdb_carousel_media")
    def test_the_lookup_runs_in_the_interactive_request_scope(self, mock_media, mock_artwork):
        seen = []

        def media(_media_id):
            seen.append(services._interactive_request.get())
            return {"video": None, "photos": ["shot"], "hero_image_id": None}

        def artwork(*_args):
            seen.append(services._interactive_request.get())
            return {"logo": None, "backdrop": None}

        mock_media.side_effect = media
        mock_artwork.side_effect = artwork

        carousel.resolve_carousel_media(MediaTypes.GAME.value, Sources.IGDB.value, "123")

        self.assertEqual(seen, [True, True])
        self.assertFalse(services._interactive_request.get())

    @patch("app.game_artwork.resolve")
    @patch("app.providers.igdb.game")
    @patch("lists.models.CustomList._get_igdb_carousel_media")
    def test_cached_game_uses_stored_artwork_without_provider_calls(self, gallery, metadata, resolve):
        self.row(
            logo_url="https://x/logo.png",
            backdrop_url="https://x/hero.jpg",
            backdrop_provider="steamgriddb",
        )
        result = carousel.resolve_carousel_media("game", "igdb", "123", cached_only=True)
        self.assertEqual(result["overview"]["logo_url"], "https://x/logo.png")
        gallery.assert_not_called()
        metadata.assert_not_called()
        resolve.assert_not_called()

    @patch("app.game_artwork.resolve")
    @patch("lists.models.CustomList._get_igdb_carousel_media")
    def test_cached_game_defers_missing_or_expired_artwork(self, gallery, resolve):
        from app.game_artwork import expire

        self.assertIsNone(carousel.resolve_carousel_media("game", "igdb", "123", cached_only=True))
        self.row(logo_url="https://x/logo.png", backdrop_url="https://x/hero.jpg")
        expire("123")
        self.assertIsNone(carousel.resolve_carousel_media("game", "igdb", "123", cached_only=True))
        gallery.assert_not_called()
        resolve.assert_not_called()

    @patch("app.providers.igdb.game", side_effect=services.ProviderNotConfiguredError("igdb", "no key"))
    @patch("app.game_artwork.steamgriddb.find")
    def test_saved_keys_upgrade_stored_game_without_an_igdb_key(self, find, _metadata):
        from app import game_artwork

        Item.objects.create(
            source="igdb", media_type="game", media_id="123", title="Galactic Racer",
            platforms=["PC (Microsoft Windows)"],
        )
        self.row()
        self.assertTrue(self.empty())
        game_artwork.keys_saved()
        self.assertFalse(self.empty())
        self.assertIsNone(carousel.resolve_carousel_media("game", "igdb", "123", cached_only=True))
        find.assert_not_called()
        find.return_value = {
            "logo": SGDB_LOGO,
            "backdrop": Art("https://cdn2.steamgriddb.com/hero/1.jpg", "steamgriddb", "1"),
        }

        result = carousel.resolve_carousel_media("game", "igdb", "123")

        self.assertEqual(result["overview"]["logo_url"], SGDB_LOGO.url)
        query = find.call_args.args[0]
        self.assertEqual(query.title, "Galactic Racer")
        self.assertEqual(query.platforms, ("PC (Microsoft Windows)",))
        self.assertEqual(GameArtwork.objects.get(media_id="123").logo_url, SGDB_LOGO.url)
        with patch("app.game_artwork._search", side_effect=AssertionError("unexpected lookup")):
            warm = carousel.resolve_carousel_media("game", "igdb", "123", cached_only=True)
        self.assertEqual(warm["overview"], result["overview"])

    @patch("app.providers.tmdb.carousel_media")
    def test_cached_tmdb_and_seasons_do_not_fetch(self, fetch):
        for kind, season in [("movie", None), ("tv", None), ("season", 1)]:
            data = {"video": None, "photos": [], "logos": ["/logo.png"], "backdrop_path": "/hero.jpg"}
            with patch("app.providers.tmdb.peek_carousel_media", return_value=data):
                result = carousel.resolve_carousel_media(kind, "tmdb", "123", season_number=season, cached_only=True)
                self.assertIsNotNone(result["overview"])
            with patch("app.providers.tmdb.peek_carousel_media", return_value=None):
                self.assertIsNone(carousel.resolve_carousel_media(kind, "tmdb", "123", season_number=season, cached_only=True))
        fetch.assert_not_called()


class IgdbCarouselOverviewTests(TestCase):
    def setUp(self):
        gallery_patch = patch("app.game_artwork.gallery", return_value=[])
        gallery_patch.start()
        self.addCleanup(gallery_patch.stop)

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
    def test_igdb_carousel_fetch_does_not_ask_for_a_game_logo(self, mock_api, _mock_token):
        from lists.models import CustomList

        data = CustomList()._get_igdb_carousel_media("123")

        # IGDB games have no `logo` field: asking for one fails the whole query.
        self.assertNotIn("logo", mock_api.call_args_list[0].kwargs["data"])
        self.assertEqual(data["hero_image_id"], "game-screen")

    @patch("app.providers.igdb.get_access_token", side_effect=RuntimeError("down"))
    def test_igdb_carousel_fetch_failure_returns_empty_media(self, _mock_token):
        from lists.models import CustomList

        data = CustomList()._get_igdb_carousel_media("123")

        self.assertEqual(data["photos"], [])
        self.assertIsNone(data["hero_image_id"])

    @patch("app.providers.igdb.get_access_token", return_value="token")
    @patch("app.providers.services.api_request")
    def test_a_failed_lookup_is_only_cached_briefly(self, mock_api, _mock_token):
        from lists.models import IGDB_CAROUSEL_FAILURE_TTL, CustomList

        mock_api.side_effect = RuntimeError("igdb down")

        with patch("django.core.cache.cache.set") as mock_set:
            CustomList()._get_igdb_carousel_media("123")

        self.assertEqual(mock_set.call_args.args[2], IGDB_CAROUSEL_FAILURE_TTL)

    @patch("app.providers.igdb.get_access_token", return_value="token")
    @patch("app.providers.services.api_request")
    def test_a_game_with_no_media_is_cached_for_a_day(self, mock_api, _mock_token):
        from lists.models import CustomList

        mock_api.side_effect = [[{"id": 123, "artworks": [], "screenshots": []}], []]

        with patch("django.core.cache.cache.set") as mock_set:
            CustomList()._get_igdb_carousel_media("123")

        self.assertEqual(mock_set.call_args.args[2], 60 * 60 * 24)


class GameGalleryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        Item.objects.create(source="igdb", media_type="game", media_id="123", title="Game")
        GameArtwork.objects.create(
            source="igdb", media_id="123", logo_url=SGDB_LOGO.url,
            backdrop_url="https://x/hero.jpg", backdrop_provider="steamgriddb",
        )
        cache.set("igdb_carousel_v4_123", {"video": None, "photos": []}, 60)

    @patch("app.game_artwork.steamgriddb.gallery")
    @patch("app.game_artwork.thegamesdb.gallery")
    def test_provider_gallery_is_merged_deduplicated_and_reused(self, tgdb, sgdb):
        from app import game_artwork
        from app.game_artwork import steamgriddb, thegamesdb

        sgdb.return_value = [{"url": "https://x/hero.jpg"}, {"url": "https://x/shot.jpg", "width": 1920, "height": 1080}]
        tgdb.return_value = [{"url": "https://x/shot.jpg"}, {"url": "https://x/fanart.jpg"}]
        with patch("app.game_artwork.provider_order", return_value=[steamgriddb, thegamesdb]):
            self.assertIsNone(carousel.resolve_carousel_media("game", "igdb", "123", cached_only=True))
            sgdb.assert_not_called()
            game_artwork.gallery("123")
            warm = carousel.resolve_carousel_media("game", "igdb", "123", cached_only=True)
            self.assertEqual([p["url"] for p in warm["photos"]], ["https://x/shot.jpg", "https://x/fanart.jpg"])
            self.assertEqual(warm["photos"][0]["width"], 1920)
            cache.delete("igdb_carousel_v4_123")
            with patch("app.carousel.credentials.is_configured", return_value=False):
                without_igdb = carousel.resolve_carousel_media("game", "igdb", "123", cached_only=True)
            self.assertEqual(without_igdb["photos"], warm["photos"])
            with patch("app.carousel.credentials.is_configured", return_value=True):
                self.assertIsNone(carousel.resolve_carousel_media("game", "igdb", "123", cached_only=True))
            game_artwork.gallery("123")
            sgdb.assert_called_once()
            tgdb.assert_called_once()
            game_artwork.keys_saved()
            game_artwork.gallery("123")
            self.assertEqual(sgdb.call_count, 2)
            game_artwork.expire("123")
            game_artwork.gallery("123")
            self.assertEqual(sgdb.call_count, 3)

    @patch("app.game_artwork.steamgriddb.gallery", side_effect=RuntimeError("down"))
    @patch("app.game_artwork.thegamesdb.gallery", return_value=[{"url": "https://x/fanart.jpg"}])
    def test_failed_provider_does_not_hide_other_providers(self, _tgdb, _sgdb):
        from app import game_artwork
        from app.game_artwork import steamgriddb, thegamesdb

        with patch("app.game_artwork.provider_order", return_value=[steamgriddb, thegamesdb]):
            self.assertEqual(game_artwork.gallery("123")[0]["url"], "https://x/fanart.jpg")

    @patch("app.game_artwork.steamgriddb.gallery")
    def test_gallery_is_bounded(self, sgdb):
        from app import game_artwork
        from app.game_artwork import steamgriddb

        sgdb.return_value = [{"url": f"https://x/{i}.jpg"} for i in range(60)]
        with patch("app.game_artwork.provider_order", return_value=[steamgriddb]):
            self.assertEqual(len(game_artwork.gallery("123")), game_artwork.MAX_GALLERY_PHOTOS)
