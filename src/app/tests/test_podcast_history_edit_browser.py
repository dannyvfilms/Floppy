"""Editing a play from a podcast episode's Activity History, in a real browser."""

import os
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import tag
from django.utils import timezone
from playwright.sync_api import expect, sync_playwright

from app.models import (
    Item,
    MediaTypes,
    Podcast,
    PodcastEpisode,
    PodcastPlay,
    PodcastShow,
    Sources,
)
from app.services import podcast_plays
from app.tests.live_server import SerialStaticLiveServerTestCase


@tag("slow", "playwright")
class PodcastHistoryEditBrowserTests(SerialStaticLiveServerTestCase):
    """The history pencil must open the play editor (#1895)."""

    @classmethod
    def setUpClass(cls):
        """Start the browser."""
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
        super().setUpClass()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()
        expect.set_options(timeout=15000)

    @classmethod
    def tearDownClass(cls):
        """Stop the browser."""
        expect.set_options(timeout=5000)
        cls.browser.close()
        cls.playwright.stop()
        super().tearDownClass()

    def setUp(self):
        """Create a show with two episodes and sign in."""
        self.user = get_user_model().objects.create_user("listener", password="12345")
        self.show = PodcastShow.objects.create(
            podcast_uuid="show-browser",
            title="Browser Show",
            source=Sources.POCKETCASTS.value,
        )
        self.played = PodcastEpisode.objects.create(
            show=self.show,
            episode_uuid="ep-played",
            title="Played Episode",
            duration=1800,
            published=timezone.now() - timedelta(days=9),
        )
        self.fresh = PodcastEpisode.objects.create(
            show=self.show,
            episode_uuid="ep-fresh",
            title="Fresh Episode",
            duration=1800,
            published=timezone.now() - timedelta(days=2),
        )
        podcast_plays.create_play(
            self.user,
            self.show,
            episode=self.played,
            end_date=timezone.now() - timedelta(days=5),
        )
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        self.page.goto(f"{self.live_server_url}/")
        self.page.get_by_placeholder("Enter your username").fill("listener")
        self.page.get_by_placeholder("Enter your password").fill("12345")
        self.page.get_by_role("button", name="Sign in").click()
        expect(self.page.locator("#global-search")).to_be_visible()
        self.page.wait_for_function("() => window.htmx")
        self.page.wait_for_load_state("networkidle")

    def tearDown(self):
        """Close the browser context before Django flushes the database."""
        self.context.close()
        super().tearDown()

    def open_show(self):
        """Open the show page."""
        self.page.goto(
            f"{self.live_server_url}/details/pocketcasts/podcast/show-browser/browser-show",
        )
        self.page.wait_for_load_state("networkidle")

    def test_history_pencil_opens_a_form(self):
        """The pencil closes Activity History and opens a form, not a dimmed dead end."""
        self.page.goto(
            f"{self.live_server_url}/details/pocketcasts/podcast/show-browser/browser-show",
        )
        self.page.wait_for_load_state("networkidle")
        self.page.locator("[data-episode-uuid='ep-played']").get_by_title(
            "View your activity history",
        ).click()
        expect(self.page.get_by_text("Activity History")).to_be_visible()
        row = self.page.locator("[data-history-modal-root] li").first
        row.hover()
        row.get_by_title("Edit").click()
        expect(self.page.get_by_text("Activity History")).to_have_count(0)
        expect(
            self.page.get_by_role("heading", name="Track Episode").locator("visible=true"),
        ).to_have_count(1)
