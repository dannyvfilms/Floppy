import datetime
import os

from django.contrib.auth import get_user_model
from django.test import tag
from django.utils import timezone
from playwright.sync_api import expect, sync_playwright

from app.models import Game, Item, MediaTypes, Movie, Sources, Status
from app.tests.live_server import SerialStaticLiveServerTestCase


@tag("slow", "playwright")
class StatisticsMediaTypeSelectionTests(SerialStaticLiveServerTestCase):
    """Browser coverage for picking one or several media types (issue #1317)."""

    @classmethod
    def setUpClass(cls):
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
        super().setUpClass()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        super().tearDownClass()

    def setUp(self):
        self.credentials = {"username": "stats-types", "password": "12345"}
        user = get_user_model().objects.create_user(**self.credentials)
        now = timezone.now()
        for index in range(2):
            item = Item.objects.create(
                media_id=f"movie-{index}",
                source=Sources.MANUAL.value,
                media_type=MediaTypes.MOVIE.value,
                title=f"Movie {index}",
                runtime_minutes=120,
            )
            Movie.objects.create(
                item=item,
                user=user,
                status=Status.COMPLETED.value,
                start_date=now - datetime.timedelta(days=index + 1),
                end_date=now - datetime.timedelta(days=index + 1),
            )
        game_item = Item.objects.create(
            media_id="game-1",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.GAME.value,
            title="A Game",
        )
        Game.objects.create(
            item=game_item,
            user=user,
            status=Status.COMPLETED.value,
            progress=120,
            start_date=now - datetime.timedelta(days=5),
            end_date=now - datetime.timedelta(days=5),
        )

    def open_statistics(self, query=""):
        context = self.browser.new_context()
        self.addCleanup(context.close)
        page = context.new_page()
        page.goto(f"{self.live_server_url}/")
        page.get_by_placeholder("Enter your username").fill(
            self.credentials["username"],
        )
        page.get_by_placeholder("Enter your password").fill(
            self.credentials["password"],
        )
        page.get_by_role("button", name="Sign in").click()
        page.goto(f"{self.live_server_url}/statistics{query}")
        return page

    def pick(self, page, name):
        menu = page.locator(".stats-mediatype-wrapper .stats-dropdown-panel")
        if not menu.is_visible():
            page.locator(".stats-mediatype-button").click()
        menu.get_by_role("button", name=name, exact=True).click()

    def trigger(self, page):
        return page.locator(".stats-mediatype-button .stats-button-title")

    def test_first_click_selects_only_that_type_then_more_can_be_added(self):
        page = self.open_statistics()
        expect(self.trigger(page)).to_have_text("All media")
        expect(page.locator(".stats-hero-title").nth(1)).to_contain_text("3 titles")

        self.pick(page, "Movies")
        expect(self.trigger(page)).to_have_text("Movies")
        expect(page.locator(".stats-hero-title").nth(1)).to_contain_text("2 films")
        self.assertIn("media-type=movie", page.url)
        self.assertNotIn("game", page.url)

        self.pick(page, "Games")
        expect(self.trigger(page)).to_have_text("Movies, Games")
        expect(page.locator(".stats-hero-title").nth(1)).to_contain_text("3 titles")
        self.assertIn("media-type=movie%2Cgame", page.url)

    def test_unticking_the_last_type_and_all_media_return_to_all(self):
        page = self.open_statistics()
        self.pick(page, "Movies")
        self.pick(page, "Movies")
        expect(self.trigger(page)).to_have_text("All media")
        self.assertNotIn("media-type", page.url)

        self.pick(page, "Games")
        self.pick(page, "Movies")
        self.pick(page, "All media")
        expect(self.trigger(page)).to_have_text("All media")
        self.assertNotIn("media-type", page.url)

    def test_selection_survives_a_reload_and_old_single_links(self):
        page = self.open_statistics("?media-type=movie,game")
        expect(self.trigger(page)).to_have_text("Movies, Games")

        page = self.open_statistics("?media-type=game")
        expect(self.trigger(page)).to_have_text("Games")
        expect(page.locator(".stats-hero-title").nth(1)).to_contain_text("1 games")
