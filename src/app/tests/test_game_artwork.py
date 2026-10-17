from datetime import timedelta
from unittest.mock import patch

import requests
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from app import game_artwork, image_cache
from app.game_artwork import libretro, screenscraper, steam, steamgriddb, thegamesdb
from app.game_artwork.base import BACKDROP, LOGO, Art, GameQuery, normalize
from app.game_artwork.systems import systems_for
from app.models import GameArtwork

API = "app.providers.services.api_request"
SNES = "Super Nintendo Entertainment System"


def query(**overrides):
    values = {"media_id": "7", "title": "Super Mario World", "year": 1990}
    return GameQuery(**{**values, **overrides})


class SystemsTests(SimpleTestCase):
    def test_igdb_platform_names_map_to_retro_systems(self):
        systems = systems_for(["PC (Microsoft Windows)", SNES, "Arcade"])

        self.assertEqual([s.screenscraper for s in systems], [4, 75])

    def test_modern_platforms_are_not_retro(self):
        self.assertEqual(systems_for(["PC (Microsoft Windows)", "PlayStation 5"]), ())

    def test_query_derives_its_systems(self):
        self.assertEqual(query(platforms=(SNES,)).systems[0].libretro, "Nintendo - Super Nintendo Entertainment System")

    def test_normalize_ignores_case_punctuation_and_accents(self):
        self.assertEqual(normalize("Pokémon: Red!"), normalize("pokemon red"))


class SteamTests(SimpleTestCase):
    @patch("app.game_artwork.steam.image_exists", return_value=True)
    def test_uses_the_library_logo_and_hero(self, _exists):
        found = steam.find(query(steam_app_id="620"), [LOGO, BACKDROP])

        self.assertTrue(found[LOGO].url.endswith("/620/logo.png"))
        self.assertTrue(found[BACKDROP].url.endswith("/620/library_hero.jpg"))
        self.assertEqual(found[LOGO].provider_id, "620")

    @patch("app.game_artwork.steam.image_exists", side_effect=[True, False])
    def test_a_missing_asset_is_left_out(self, _exists):
        found = steam.find(query(steam_app_id="620"), [LOGO, BACKDROP])

        self.assertEqual(list(found), [LOGO])

    @patch("app.game_artwork.steam.image_exists")
    def test_needs_a_steam_app_id(self, mock_exists):
        self.assertEqual(steam.find(query(), [LOGO, BACKDROP]), {})
        mock_exists.assert_not_called()


class LibretroTests(SimpleTestCase):
    def test_finds_the_region_named_file_and_its_logo(self):
        urls = []

        def exists(url):
            urls.append(url)
            return "%28USA%29" in url and ("Named_Snaps" in url or "Named_Logos" in url)

        with patch("app.game_artwork.libretro.image_exists", side_effect=exists):
            found = libretro.find(query(platforms=(SNES,)), [LOGO, BACKDROP])

        self.assertIn("Named_Snaps/Super%20Mario%20World%20%28USA%29.png", found[BACKDROP].url)
        self.assertIn("Named_Logos/", found[LOGO].url)
        self.assertEqual(found[BACKDROP].provider_id, "Super Mario World (USA)")

    def test_falls_back_to_the_title_screen(self):
        with patch(
            "app.game_artwork.libretro.image_exists",
            side_effect=lambda url: "Named_Titles" in url,
        ):
            found = libretro.find(query(platforms=(SNES,)), [BACKDROP])

        self.assertIn("Named_Titles", found[BACKDROP].url)
        self.assertNotIn(LOGO, found)

    def test_unsafe_characters_become_underscores_like_libretro_files(self):
        seen = []
        with patch(
            "app.game_artwork.libretro.image_exists",
            side_effect=lambda url: seen.append(url) and False,
        ):
            libretro.find(query(title="Zelda: A/B?", platforms=(SNES,)), [BACKDROP])

        self.assertIn("Zelda_%20A_B_", seen[0])

    @patch("app.game_artwork.libretro.image_exists")
    def test_only_retro_games_are_probed(self, mock_exists):
        self.assertEqual(libretro.find(query(), [LOGO, BACKDROP]), {})
        mock_exists.assert_not_called()


@override_settings(STEAMGRIDDB_API_KEY="sgdb-key")
class SteamGridDbTests(TestCase):
    def test_does_nothing_without_a_key(self):
        with override_settings(STEAMGRIDDB_API_KEY=""), patch(API) as mock_api:
            self.assertEqual(steamgriddb.find(query(), [LOGO]), {})
        mock_api.assert_not_called()

    def test_resolves_a_steam_game_by_app_id_and_picks_the_best_images(self):
        responses = {
            "/games/steam/620": {"data": {"id": 55}},
            "/logos/game/55": {"data": [
                {"id": 1, "score": 3, "url": "https://cdn2.steamgriddb.com/logo/low.png"},
                {"id": 2, "score": 9, "url": "https://cdn2.steamgriddb.com/logo/top.png"},
            ]},
            "/heroes/game/55": {"data": [
                {"id": 3, "score": 99, "url": "https://cdn2.steamgriddb.com/hero/square.png", "width": 600, "height": 600},
                {"id": 4, "score": 5, "url": "https://cdn2.steamgriddb.com/hero/wide.png", "width": 1920, "height": 620},
            ]},
        }

        def api(provider, method, url, **kwargs):
            self.assertEqual(kwargs["headers"], {"Authorization": "Bearer sgdb-key"})
            return responses[url.split("/api/v2")[1]]

        with patch(API, side_effect=api):
            found = steamgriddb.find(query(steam_app_id="620"), [LOGO, BACKDROP])

        self.assertEqual(found[LOGO], Art("https://cdn2.steamgriddb.com/logo/top.png", "steamgriddb", "2"))
        self.assertEqual(found[BACKDROP].provider_id, "4")

    def test_searches_by_exact_title_when_there_is_no_app_id(self):
        def api(provider, method, url, **kwargs):
            if "autocomplete" in url:
                self.assertIn("Super%20Mario%20World", url)
                return {"data": [{"id": 1, "name": "Super Mario World 2"}, {"id": 2, "name": "Super Mario World"}]}
            self.assertIn("/logos/game/2", url)
            return {"data": [{"id": 8, "score": 1, "url": "https://cdn2.steamgriddb.com/logo/a.png"}]}

        with patch(API, side_effect=api):
            found = steamgriddb.find(query(), [LOGO])

        self.assertEqual(found[LOGO].provider_id, "8")

    def test_a_near_match_is_not_used(self):
        with patch(API, return_value={"data": [{"id": 1, "name": "Super Mario World 2"}]}) as mock_api:
            self.assertEqual(steamgriddb.find(query(), [LOGO]), {})
        self.assertEqual(mock_api.call_count, 1)

    def test_an_unknown_steam_app_falls_back_to_the_title_search(self):
        not_found = requests.exceptions.HTTPError(response=type("R", (), {"status_code": 404})())

        def api(provider, method, url, **kwargs):
            if "/games/steam/" in url:
                raise not_found
            if "autocomplete" in url:
                return {"data": [{"id": 2, "name": "Super Mario World"}]}
            return {"data": [{"id": 8, "score": 1, "url": "https://cdn2.steamgriddb.com/logo/a.png"}]}

        with patch(API, side_effect=api):
            found = steamgriddb.find(query(steam_app_id="1"), [LOGO])

        self.assertIn(LOGO, found)


@override_settings(THEGAMESDB_API_KEY="tgdb-key")
class TheGamesDbTests(TestCase):
    def test_does_nothing_without_a_key(self):
        with override_settings(THEGAMESDB_API_KEY=""), patch(API) as mock_api:
            self.assertEqual(thegamesdb.find(query(), [LOGO]), {})
        mock_api.assert_not_called()

    def test_finds_the_clear_logo_and_fanart_of_the_exact_title_and_year(self):
        def api(provider, method, url, **kwargs):
            if "ByGameName" in url:
                return {"data": {"games": [
                    {"id": 1, "game_title": "Super Mario World", "release_date": "1991-08-23"},
                    {"id": 2, "game_title": "Super Mario World", "release_date": "1990-11-21"},
                ]}}
            self.assertEqual(kwargs["params"]["games_id"], 2)
            self.assertEqual(kwargs["params"]["filter[type]"], "clearlogo,fanart")
            return {"data": {
                "base_url": {"original": "https://cdn.thegamesdb.net/images/original/"},
                "images": {"2": [
                    {"id": 10, "type": "fanart", "filename": "fanart/2-1.jpg"},
                    {"id": 11, "type": "clearlogo", "filename": "clear-logo/2.png"},
                ]},
            }}

        with patch(API, side_effect=api):
            found = thegamesdb.find(query(), [LOGO, BACKDROP])

        self.assertEqual(found[LOGO], Art("https://cdn.thegamesdb.net/images/original/clear-logo/2.png", "thegamesdb", "11"))
        self.assertEqual(found[BACKDROP].provider_id, "10")

    def test_no_exact_title_means_no_images(self):
        with patch(API, return_value={"data": {"games": [{"id": 1, "game_title": "Other"}]}}) as mock_api:
            self.assertEqual(thegamesdb.find(query(), [LOGO]), {})
        self.assertEqual(mock_api.call_count, 1)


DEV = {
    "SCREENSCRAPER_DEV_ID": "dev",
    "SCREENSCRAPER_DEV_PASSWORD": "devpass",
    "SCREENSCRAPER_SOFTNAME": "Floppy",
    "SCREENSCRAPER_SSID": "",
    "SCREENSCRAPER_SSPASSWORD": "",
}
MEDIA_URL = (
    "https://api.screenscraper.fr/api2/mediaJeu.php?devid=xxx&devpassword=yyy"
    "&softname=zzz&ssid=&sspassword=&systemeid=4&jeuid=9&media=wheel(wor)"
)
RESPONSE = {"response": {"jeu": {"id": "9", "noms": [{"region": "wor", "text": "Super Mario World"}], "medias": [
    {"type": "wheel", "region": "jp", "url": MEDIA_URL.replace("wor", "jp")},
    {"type": "wheel", "region": "wor", "url": MEDIA_URL},
    {"type": "fanart", "region": "wor", "url": MEDIA_URL.replace("wheel(wor)", "fanart")},
    {"type": "ss", "region": "wor", "url": "https://api.screenscraper.fr/ss"},
]}}}


class ScreenScraperTests(TestCase):
    def test_inactive_without_developer_credentials(self):
        with override_settings(**{**DEV, "SCREENSCRAPER_DEV_ID": ""}), patch(API) as mock_api:
            self.assertEqual(screenscraper.find(query(platforms=(SNES,)), [LOGO]), {})
        mock_api.assert_not_called()

    @override_settings(**DEV)
    def test_stored_urls_never_carry_credentials(self):
        with patch(API, return_value=RESPONSE) as mock_api:
            found = screenscraper.find(query(platforms=(SNES,)), [LOGO, BACKDROP])

        sent = mock_api.call_args.kwargs["params"]
        self.assertEqual(sent["devid"], "dev")
        self.assertEqual(sent["systemeid"], 4)
        for art in found.values():
            for secret in ("devid", "devpassword", "softname", "ssid", "sspassword"):
                self.assertNotIn(secret, art.url)
        self.assertEqual(found[LOGO].url, "https://api.screenscraper.fr/api2/mediaJeu.php?systemeid=4&jeuid=9&media=wheel(wor)")
        self.assertIn("media=fanart", found[BACKDROP].url)

    @override_settings(**DEV)
    def test_a_members_own_login_is_sent_when_set(self):
        with override_settings(SCREENSCRAPER_SSID="me", SCREENSCRAPER_SSPASSWORD="pw"), patch(API, return_value=RESPONSE) as mock_api:
            screenscraper.find(query(platforms=(SNES,)), [LOGO])

        self.assertEqual(mock_api.call_args.kwargs["params"]["ssid"], "me")

    @override_settings(**DEV)
    def test_half_a_personal_login_is_not_paired_with_the_instance_login(self):
        from django.contrib.auth import get_user_model

        from app.providers import credentials

        user = get_user_model().objects.create_user(username="half", password="x")
        credentials.set_user("screenscraper", user, {"ssid": "me"})
        cache.clear()
        mixed = {"SCREENSCRAPER_SSPASSWORD": "instance-pw"}

        with override_settings(**mixed), credentials.current_user_scope(user):
            sent = screenscraper._request_credentials()

        self.assertNotIn("ssid", sent)
        self.assertNotIn("sspassword", sent)

    @override_settings(**DEV)
    def test_a_login_from_one_tier_is_sent_whole(self):
        both = {"SCREENSCRAPER_SSID": "inst", "SCREENSCRAPER_SSPASSWORD": "instance-pw"}

        with override_settings(**both):
            sent = screenscraper._request_credentials()

        self.assertEqual((sent["ssid"], sent["sspassword"]), ("inst", "instance-pw"))

    def test_the_settings_validator_requires_the_whole_login(self):
        from app.providers import credentials

        validate = credentials.get_spec("screenscraper").validator

        self.assertIsNotNone(validate({"ssid": "me", "sspassword": ""}))
        self.assertIsNotNone(validate({"ssid": "", "sspassword": "pw"}))
        self.assertIsNone(validate({"ssid": "me", "sspassword": "pw"}))

    @override_settings(**DEV)
    def test_a_different_game_name_is_not_accepted(self):
        with patch(API, return_value=RESPONSE):
            self.assertEqual(screenscraper.find(query(title="Other Game", platforms=(SNES,)), [LOGO]), {})

    @override_settings(**DEV)
    def test_only_retro_games_are_asked_about(self):
        with patch(API) as mock_api:
            self.assertEqual(screenscraper.find(query(), [LOGO]), {})
        mock_api.assert_not_called()

    @override_settings(**DEV)
    def test_credentials_are_added_only_when_fetching_screenscraper_urls(self):
        fetched = screenscraper.authenticate("https://api.screenscraper.fr/api2/mediaJeu.php?systemeid=4&media=wheel(wor)")

        self.assertIn("devpassword=devpass", fetched)
        self.assertIn("media=wheel(wor)", fetched)
        other = "https://images.igdb.com/a.jpg"
        self.assertEqual(screenscraper.authenticate(other), other)
        self.assertEqual(screenscraper.authenticate("http://api.screenscraper.fr/x"), "http://api.screenscraper.fr/x")
        self.assertEqual(screenscraper.authenticate("https://evilscreenscraper.fr/x"), "https://evilscreenscraper.fr/x")


class ScreenScraperImageProxyTests(TestCase):
    URL = "https://api.screenscraper.fr/api2/mediaJeu.php?systemeid=4&media=wheel(wor)"

    def test_goes_through_the_proxy_even_when_image_caching_is_off(self):
        image_cache.set_enabled(False)

        proxied = image_cache.rewrite_image_url(self.URL)

        self.assertTrue(proxied.startswith("/"))
        self.assertNotIn("screenscraper", proxied)
        self.assertEqual(image_cache.rewrite_image_url("https://cdn2.steamgriddb.com/a.png"), "https://cdn2.steamgriddb.com/a.png")

    def test_the_other_art_hosts_are_approved(self):
        for host in (
            "cdn.cloudflare.steamstatic.com",
            "cdn2.steamgriddb.com",
            "cdn.thegamesdb.net",
            "thumbnails.libretro.com",
        ):
            self.assertTrue(image_cache.is_approved_url(f"https://{host}/x.png"), host)

    @override_settings(**DEV)
    def test_the_proxy_fetches_with_credentials(self):
        class Response:
            is_redirect = is_permanent_redirect = False
            status_code = 200
            headers = {"Content-Type": "image/png", "Content-Length": "1"}

            def close(self):
                pass

        with patch("app.image_cache.requests.get", return_value=Response()) as mock_get:
            image_cache._open_image_response(self.URL)

        self.assertIn("devpassword=devpass", mock_get.call_args.args[0])


class ResolverTests(TestCase):
    def tearDown(self):
        cache.clear()
        super().tearDown()

    def provider(self, name, **assets):
        return patch.multiple(
            f"app.game_artwork.{name}",
            find=lambda q, wanted: {k: v for k, v in assets.items() if k in wanted},
        )

    def test_provider_order_depends_on_what_is_known(self):
        steam_order = game_artwork.provider_order(query(steam_app_id="620"))
        retro_order = game_artwork.provider_order(query(platforms=(SNES,)))
        other_order = game_artwork.provider_order(query())

        self.assertEqual(steam_order, [steam, steamgriddb, thegamesdb])
        self.assertEqual(retro_order, [screenscraper, thegamesdb, steamgriddb, libretro])
        self.assertEqual(other_order, [steamgriddb, thegamesdb])

    def test_a_retro_steam_game_also_asks_screenscraper(self):
        order = game_artwork.provider_order(query(steam_app_id="1", platforms=(SNES,)))

        self.assertEqual(order[-1], screenscraper)

    def test_logo_and_backdrop_can_come_from_different_providers(self):
        logo = Art("https://cdn2.steamgriddb.com/l.png", "steamgriddb", "1")
        backdrop = Art("https://api.screenscraper.fr/b", "screenscraper", "2")
        with (
            self.provider("screenscraper", **{BACKDROP: backdrop}),
            self.provider("thegamesdb"),
            self.provider("steamgriddb", **{LOGO: logo}),
            self.provider("libretro"),
        ):
            result = game_artwork.resolve(query(platforms=(SNES,)))

        self.assertEqual(result, {LOGO: logo, BACKDROP: backdrop})
        row = GameArtwork.objects.get(media_id="7")
        self.assertEqual((row.logo_provider, row.logo_provider_id), ("steamgriddb", "1"))
        self.assertEqual((row.backdrop_provider, row.backdrop_provider_id), ("screenscraper", "2"))
        self.assertEqual(row.backdrop_url, backdrop.url)

    def test_later_providers_are_only_asked_for_what_is_missing(self):
        logo = Art("https://x.test/l.png", "steamgriddb", "1")
        asked = []

        def second(q, wanted):
            asked.append(list(wanted))
            return {}

        with self.provider("steamgriddb", **{LOGO: logo}), patch.object(thegamesdb, "find", side_effect=second):
            game_artwork.resolve(query())

        self.assertEqual(asked, [[BACKDROP]])

    def test_igdb_art_is_the_recorded_backdrop_fallback(self):
        fallback = Art("https://images.igdb.com/a.jpg", "igdb", "a")
        with self.provider("steamgriddb"), self.provider("thegamesdb"):
            result = game_artwork.resolve(query(), fallback_backdrop=fallback)

        self.assertEqual(result, {LOGO: None, BACKDROP: fallback})
        self.assertEqual(GameArtwork.objects.get().backdrop_provider, "igdb")

    def test_a_stored_result_is_reused_without_asking_providers(self):
        GameArtwork.objects.create(source="igdb", media_id="7", logo_url="https://x.test/l.png", logo_provider="steam", backdrop_url="https://x.test/b.jpg", backdrop_provider="steam")

        with patch.object(steamgriddb, "find") as mock_find:
            result = game_artwork.resolve(query())

        mock_find.assert_not_called()
        self.assertEqual(result[LOGO].provider, "steam")

    def test_an_incomplete_result_is_retried_after_a_few_hours(self):
        row = GameArtwork.objects.create(source="igdb", media_id="7", backdrop_url="https://images.igdb.com/a.jpg", backdrop_provider="igdb")
        GameArtwork.objects.filter(pk=row.pk).update(resolved_at=timezone.now() - timedelta(hours=7))
        logo = Art("https://x.test/l.png", "steamgriddb", "1")

        with self.provider("steamgriddb", **{LOGO: logo}), self.provider("thegamesdb"):
            result = game_artwork.resolve(query())

        self.assertEqual(result[LOGO], logo)

    def test_a_complete_result_is_kept_for_weeks(self):
        row = GameArtwork.objects.create(source="igdb", media_id="7", logo_url="https://x.test/l.png", logo_provider="steam", backdrop_url="https://x.test/b.jpg", backdrop_provider="steam")
        GameArtwork.objects.filter(pk=row.pk).update(resolved_at=timezone.now() - timedelta(days=20))

        with patch.object(steamgriddb, "find") as mock_find:
            game_artwork.resolve(query())

        mock_find.assert_not_called()

    def test_igdb_art_is_read_fresh_not_from_the_stored_copy(self):
        GameArtwork.objects.create(source="igdb", media_id="7", backdrop_url="https://images.igdb.com/old.jpg", backdrop_provider="igdb", backdrop_provider_id="old")
        fresh = Art("https://images.igdb.com/new.jpg", "igdb", "new")

        result = game_artwork.resolve(query(), fallback_backdrop=fresh)

        self.assertEqual(result[BACKDROP], fresh)

    def test_a_provider_error_does_not_stop_the_others_or_get_stored_as_absence(self):
        with (
            patch.object(steamgriddb, "find", side_effect=requests.ConnectionError("down")),
            patch.object(thegamesdb, "find", return_value={}) as other,
        ):
            result = game_artwork.resolve(query())

        other.assert_called_once()
        self.assertEqual(result, {LOGO: None, BACKDROP: None})
        self.assertFalse(GameArtwork.objects.exists())

    def test_an_image_url_too_long_to_store_is_skipped_not_fatal(self):
        too_long = Art("https://cdn2.steamgriddb.com/" + "a" * 1000, "steamgriddb", "1")
        logo = Art("https://x.test/l.png", "thegamesdb", "2")

        with (
            patch.object(steamgriddb, "find", return_value={LOGO: too_long, BACKDROP: too_long}),
            patch.object(thegamesdb, "find", return_value={LOGO: logo}),
        ):
            result = game_artwork.resolve(query())

        self.assertEqual(result[LOGO], logo)
        self.assertIsNone(result[BACKDROP])

    def test_after_an_error_the_next_views_do_not_hammer_providers(self):
        with patch.object(steamgriddb, "find", side_effect=requests.ConnectionError("down")), patch.object(thegamesdb, "find", return_value={}):
            game_artwork.resolve(query())

        with patch.object(steamgriddb, "find") as mock_find:
            game_artwork.resolve(query())

        mock_find.assert_not_called()

    def test_a_clean_search_with_no_results_is_stored_as_absence(self):
        with patch.object(steamgriddb, "find", return_value={}), patch.object(thegamesdb, "find", return_value={}):
            game_artwork.resolve(query())

        self.assertTrue(GameArtwork.objects.filter(media_id="7", logo_url="").exists())

    def test_a_failed_refresh_keeps_the_logo_found_earlier(self):
        row = GameArtwork.objects.create(source="igdb", media_id="7", logo_url="https://x.test/l.png", logo_provider="steamgriddb", logo_provider_id="1")
        GameArtwork.objects.filter(pk=row.pk).update(resolved_at=timezone.now() - timedelta(hours=7))
        backdrop = Art("https://x.test/b.jpg", "thegamesdb", "2")

        with patch.object(steamgriddb, "find", side_effect=requests.ConnectionError("down")), patch.object(thegamesdb, "find", return_value={BACKDROP: backdrop}):
            result = game_artwork.resolve(query())

        self.assertEqual(result[LOGO].url, "https://x.test/l.png")
        self.assertEqual(result[BACKDROP], backdrop)

    def test_query_for_reads_igdb_metadata(self):
        metadata = {
            "title": "Portal",
            "details": {"release_date": "2007-10-10", "platforms": ["PC (Microsoft Windows)", SNES]},
            "external_ids": {"steam_app_id": "400"},
        }

        built = game_artwork.query_for(12, metadata)

        self.assertEqual((built.media_id, built.title, built.year, built.steam_app_id), ("12", "Portal", 2007, "400"))
        self.assertEqual(len(built.systems), 1)

    def test_query_for_copes_with_sparse_metadata(self):
        built = game_artwork.query_for(12, {"title": "X", "details": {"release_date": None, "platforms": None}})

        self.assertEqual((built.year, built.platforms, built.steam_app_id), (None, (), ""))


class ExpiryTests(TestCase):
    """A refresh or a new key must not wait hours behind a stored lookup."""

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def row(self, media_id="7", *, complete=False):
        values = {"backdrop_url": "https://images.igdb.com/a.jpg", "backdrop_provider": "igdb"}
        if complete:
            values = {
                "logo_url": "https://x.test/l.png",
                "logo_provider": "steamgriddb",
                "backdrop_url": "https://x.test/b.jpg",
                "backdrop_provider": "steamgriddb",
            }
        return GameArtwork.objects.create(source="igdb", media_id=media_id, **values)

    def test_a_refreshed_game_is_looked_up_again_even_when_complete(self):
        row = self.row(complete=True)

        game_artwork.expire("7")
        row.refresh_from_db()

        self.assertTrue(game_artwork.is_stale(row))
        self.assertEqual(row.logo_url, "https://x.test/l.png")

    def test_a_refresh_leaves_other_games_alone(self):
        other = self.row("8", complete=True)

        game_artwork.expire("7")
        other.refresh_from_db()

        self.assertFalse(game_artwork.is_stale(other))

    def test_a_refresh_ends_the_error_backoff(self):
        cache.set(game_artwork._error_key("7"), 1, 300)

        game_artwork.expire("7")

        self.assertIsNone(cache.get(game_artwork._error_key("7")))

    def test_a_refreshed_game_gets_the_new_art_on_its_next_lookup(self):
        self.row()
        logo = Art("https://cdn2.steamgriddb.com/logo/1.png", "steamgriddb", "1")
        backdrop = Art("https://cdn2.steamgriddb.com/hero/2.png", "steamgriddb", "2")
        game_artwork.expire("7")

        with patch.object(steamgriddb, "find", return_value={LOGO: logo, BACKDROP: backdrop}):
            result = game_artwork.resolve(query())

        self.assertEqual(result, {LOGO: logo, BACKDROP: backdrop})

    def test_a_refresh_that_finds_nothing_keeps_the_stored_art(self):
        self.row(complete=True)
        game_artwork.expire("7")

        with (
            patch.object(steamgriddb, "find", side_effect=requests.ConnectionError("down")),
            patch.object(thegamesdb, "find", return_value={}),
        ):
            result = game_artwork.resolve(query())

        self.assertEqual(result[LOGO].url, "https://x.test/l.png")
        self.assertEqual(result[BACKDROP].url, "https://x.test/b.jpg")

    def test_refreshing_a_game_with_no_row_does_nothing(self):
        game_artwork.expire("7")

        self.assertFalse(GameArtwork.objects.exists())

    def keyholder(self, name="keys"):
        from django.contrib.auth import get_user_model

        return get_user_model().objects.create_user(username=name, password="x")

    def as_user(self, user):
        from app.providers import credentials

        return credentials.current_user_scope(user)

    def test_a_new_instance_key_reopens_games_with_a_gap_for_everyone(self):
        gap = self.row("7")
        no_logo = GameArtwork.objects.create(
            source="igdb",
            media_id="9",
            backdrop_url="https://x.test/b.jpg",
            backdrop_provider="steamgriddb",
        )
        done = self.row("8", complete=True)

        game_artwork.keys_saved()

        self.assertTrue(game_artwork.is_stale(gap))
        self.assertTrue(game_artwork.is_stale(no_logo))
        self.assertFalse(game_artwork.is_stale(done))

    def test_a_members_key_only_reopens_games_for_that_member(self):
        owner, other = self.keyholder("owner"), self.keyholder("other")
        row = self.row()

        game_artwork.keys_saved(owner)

        with self.as_user(owner):
            self.assertTrue(game_artwork.is_stale(row))
        with self.as_user(other):
            self.assertFalse(game_artwork.is_stale(row))
        self.assertFalse(game_artwork.is_stale(row))

    def test_a_member_without_the_key_cannot_use_up_the_members_recheck(self):
        owner, other = self.keyholder("owner"), self.keyholder("other")
        self.row()
        game_artwork.keys_saved(owner)

        with (
            self.as_user(other),
            patch.object(steamgriddb, "find", return_value={}) as other_find,
        ):
            game_artwork.resolve(query())
        other_find.assert_not_called()

        logo = Art("https://cdn2.steamgriddb.com/logo/1.png", "steamgriddb", "1")
        with (
            self.as_user(owner),
            patch.object(steamgriddb, "find", return_value={LOGO: logo}),
            patch.object(thegamesdb, "find", return_value={}),
        ):
            result = game_artwork.resolve(query())

        self.assertEqual(result[LOGO], logo)

    def test_a_recheck_is_used_up_once_the_lookup_has_run(self):
        owner = self.keyholder("owner")
        self.row()
        game_artwork.keys_saved(owner)

        with (
            self.as_user(owner),
            patch.object(steamgriddb, "find", return_value={}),
            patch.object(thegamesdb, "find", return_value={}),
        ):
            game_artwork.resolve(query())
            row = GameArtwork.objects.get(media_id="7")
            self.assertFalse(game_artwork.is_stale(row))

    def test_a_new_key_ends_an_earlier_error_backoff(self):
        owner = self.keyholder("owner")
        with (
            patch.object(steamgriddb, "find", side_effect=requests.ConnectionError("down")),
            patch.object(thegamesdb, "find", return_value={}),
        ):
            game_artwork.resolve(query())
        game_artwork.keys_saved(owner)
        logo = Art("https://cdn2.steamgriddb.com/logo/1.png", "steamgriddb", "1")

        with (
            self.as_user(owner),
            patch.object(steamgriddb, "find", return_value={LOGO: logo}),
            patch.object(thegamesdb, "find", return_value={}),
        ):
            result = game_artwork.resolve(query())

        self.assertEqual(result[LOGO], logo)

    def test_an_error_backoff_does_not_settle_the_row(self):
        row = self.row()
        GameArtwork.objects.filter(pk=row.pk).update(resolved_at=timezone.now() - timedelta(hours=7))
        cache.set(game_artwork._error_key("7"), 1, 300)

        with patch.object(steamgriddb, "find") as mock_find:
            game_artwork.resolve(query())

        mock_find.assert_not_called()
        self.assertTrue(game_artwork.is_stale(GameArtwork.objects.get(pk=row.pk)))

    def test_saving_a_game_artwork_key_reopens_games_with_a_gap(self):
        from app.providers import credentials

        user = self.keyholder()
        row = self.row()
        for slug in ("steamgriddb", "thegamesdb"):
            for save, scope in (
                (lambda slug=slug: credentials.set_user(slug, user, {"api_key": "k"}), user),
                (lambda slug=slug: credentials.set_instance(slug, {"api_key": "k"}), None),
            ):
                with self.subTest(slug=slug, personal=scope is not None):
                    cache.clear()
                    GameArtwork.objects.filter(pk=row.pk).update(resolved_at=timezone.now())
                    row.refresh_from_db()
                    with self.as_user(user):
                        self.assertFalse(game_artwork.is_stale(row))

                    save()

                    with self.as_user(user):
                        self.assertTrue(game_artwork.is_stale(row))

    def test_saving_another_providers_key_leaves_artwork_alone(self):
        from app.providers import credentials

        row = self.row()

        credentials.set_instance("tmdb", {"api_key": "k"})

        self.assertFalse(game_artwork.is_stale(row))

    def test_a_failure_while_reopening_artwork_does_not_fail_saving_the_key(self):
        from app.providers import credentials

        with patch.object(game_artwork, "keys_saved", side_effect=RuntimeError("cache")):
            credentials.set_instance("steamgriddb", {"api_key": "k"})

        self.assertEqual(credentials.instance_value("steamgriddb", "api_key"), "k")

    @patch("app.game_artwork.gallery", return_value=[])
    def test_the_game_page_loads_its_carousel_again_after_a_refresh(self, _gallery):
        from app import carousel

        self.row()
        cache.set("igdb_carousel_v4_7", {"video": None, "photos": []}, 60)
        self.assertTrue(carousel.confirmed_empty("game", "igdb", "7"))

        game_artwork.expire("7")

        self.assertFalse(carousel.confirmed_empty("game", "igdb", "7"))

    @patch("app.game_artwork.gallery", return_value=[])
    def test_the_game_page_loads_its_carousel_again_after_a_key_is_saved(self, _gallery):
        from app import carousel

        self.row()
        cache.set("igdb_carousel_v4_7", {"video": None, "photos": []}, 60)
        self.assertTrue(carousel.confirmed_empty("game", "igdb", "7"))

        game_artwork.keys_saved()

        self.assertFalse(carousel.confirmed_empty("game", "igdb", "7"))


class GalleryProviderTests(TestCase):
    @override_settings(STEAMGRIDDB_API_KEY="sgdb-key")
    def test_steamgriddb_returns_all_heroes_sorted_with_thumbnails(self):
        images = [
            {"url": "https://x/low.jpg", "score": 1},
            {"url": "https://x/high.jpg", "thumb": "https://x/thumb.jpg", "score": 9, "width": 1920, "height": 620},
        ]
        with patch.object(steamgriddb, "_game_id", return_value=55), patch(API, return_value={"data": images}) as api:
            photos = steamgriddb.gallery(query())
        self.assertEqual([p["url"] for p in photos], ["https://x/high.jpg", "https://x/low.jpg"])
        self.assertEqual(photos[0]["thumb_url"], "https://x/thumb.jpg")
        self.assertIn("/heroes/game/55", api.call_args.args[2])

    @override_settings(THEGAMESDB_API_KEY="tgdb-key")
    def test_thegamesdb_returns_every_fanart(self):
        payload = {"data": {"base_url": {"original": "https://x/"}, "images": {"55": [
            {"type": "fanart", "filename": "one.jpg"},
            {"type": "fanart", "filename": "two.jpg"},
            {"type": "clearlogo", "filename": "logo.png"},
        ]}}}
        with patch.object(thegamesdb, "_game_id", return_value=55), patch(API, return_value=payload):
            photos = thegamesdb.gallery(query())
        self.assertEqual([p["url"] for p in photos], ["https://x/one.jpg", "https://x/two.jpg"])

    @override_settings(**DEV)
    def test_screenscraper_gallery_strips_credentials_and_excludes_logos(self):
        with patch(API, return_value=RESPONSE):
            photos = screenscraper.gallery(query(platforms=(SNES,)))
        self.assertEqual(len(photos), 2)
        self.assertIn("media=fanart", photos[0]["url"])
        self.assertEqual(photos[1]["url"], "https://api.screenscraper.fr/ss")
        for photo in photos:
            for secret in ("devid", "devpassword", "softname", "ssid", "sspassword"):
                self.assertNotIn(secret, photo["url"])
