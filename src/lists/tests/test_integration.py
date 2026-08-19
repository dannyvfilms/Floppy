import copy
import os
import re
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import tag
from playwright.sync_api import expect, sync_playwright

PERFECT_BLUE_MEDIA_ID = "437"

PERFECT_BLUE_SEARCH_RESULT = {
    "media_id": PERFECT_BLUE_MEDIA_ID,
    "source": "mal",
    "media_type": "anime",
    "title": "Perfect Blue",
    "original_title": "Perfect Blue",
    "localized_title": "Perfect Blue",
    "image": "https://example.com/perfect_blue.jpg",
    "year": 1998,
}

PERFECT_BLUE_SEARCH = {
    "page": 1,
    "total_results": 1,
    "total_pages": 1,
    "results": [PERFECT_BLUE_SEARCH_RESULT],
}

PERFECT_BLUE_METADATA = {
    "media_id": PERFECT_BLUE_MEDIA_ID,
    "source": "mal",
    "source_url": f"https://myanimelist.net/anime/{PERFECT_BLUE_MEDIA_ID}",
    "media_type": "anime",
    "title": "Perfect Blue",
    "original_title": "Perfect Blue",
    "localized_title": "Perfect Blue",
    "max_progress": 1,
    "image": "https://example.com/perfect_blue.jpg",
    "synopsis": "",
    "genres": [],
    "score": None,
    "score_count": None,
    "details": {
        "format": "Movie",
        "start_date": "1997-02-28",
        "end_date": "1997-02-28",
        "status": "Finished Airing",
        "episodes": 1,
        "runtime": 81,
        "studios": [],
        "season": None,
        "broadcast": None,
        "source": None,
    },
    "related": {"related_anime": [], "recommendations": []},
}


@tag("slow", "playwright")
class IntegrationTest(StaticLiveServerTestCase):
    """Integration tests for the application."""

    @classmethod
    def setUpClass(cls):
        """Set up the test class."""
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
        super().setUpClass()
        cls.playwright = sync_playwright().start()
        # use headless=False, slow_mo=400 to see the browser
        cls.browser = cls.playwright.chromium.launch()

    def setUp(self):
        """Set up test data for CustomList model."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

        # Search results and detail lookups mutate the returned dicts in place
        # (e.g. lists_modal's Item.objects.create consumes the metadata dict),
        # so hand back a fresh deep copy every call rather than a shared
        # return_value that could be corrupted across calls/tests.
        for provider_patch in (
            patch(
                "app.providers.mal.search",
                side_effect=lambda *a, **k: copy.deepcopy(PERFECT_BLUE_SEARCH),
            ),
            patch(
                "app.providers.mal.anime",
                side_effect=lambda *a, **k: copy.deepcopy(PERFECT_BLUE_METADATA),
            ),
        ):
            provider_patch.start()
            self.addCleanup(provider_patch.stop)

        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        self.page.goto(f"{self.live_server_url}/")
        self.page.get_by_placeholder("Enter your username").fill(
            self.credentials["username"],
        )
        self.page.get_by_placeholder("Enter your password").fill(
            self.credentials["password"],
        )
        self.page.get_by_role("button", name="Sign in").click()

    def search_and_submit(self, query):
        """Run a global search via the submit button.

        The search form's Alpine.js submit guard only reliably recognizes
        the click event's target as its own search button; relying on the
        input's implicit Enter-to-submit behavior races with the
        hx-trigger="... , search" suggestions fetch firing on the same
        native `search` event and is intermittently swallowed.
        """
        self.page.locator("#global-search").fill(query)
        self.page.locator('form:has(#global-search) button[type="submit"]').click()

    @classmethod
    def tearDownClass(cls):
        """Tear down the test class."""
        cls.browser.close()
        cls.playwright.stop()
        super().tearDownClass()

    def tearDown(self):
        """Close browser connections before Django flushes the database."""
        self.context.close()
        super().tearDown()

    def test_blank_modal(self):
        """Test the blank modal for creating a list."""
        self.page.get_by_role("button", name="TV Shows").click()
        self.page.locator("li").filter(has_text=re.compile(r"^Anime$")).click()
        self.search_and_submit("perfect blue")
        self.page.locator(".absolute > .relative > button:nth-child(2)").first.click()
        expect(self.page.locator("#lists-anime-437")).to_contain_text(
            "You haven't created any lists yet.",
        )

    def test_flow(self):
        """Test the flow of adding an item to a list and editing the list."""
        # Create list
        self.page.get_by_role("link", name="Lists").click()
        self.page.get_by_role("button", name="New List").click()
        expect(self.page.locator("h2", has_text="Create New List")).to_be_visible()
        self.page.locator("#id_name").click()
        self.page.locator("#id_name").fill("test")
        self.page.get_by_role("button", name="Create List").click()
        expect(self.page.locator("#lists-grid")).to_contain_text("test")

        # Add item to list
        self.page.get_by_role("button", name="TV Shows").click()
        self.page.locator("li").filter(has_text=re.compile(r"^Anime$")).click()
        self.search_and_submit("perfect blue")
        self.page.locator(".absolute > .relative > button:nth-child(2)").first.click()
        expect(self.page.locator("#lists-anime-437")).to_contain_text("Lists test Add")
        self.page.get_by_role("button", name="Add", exact=True).click()
        expect(self.page.locator("#lists-anime-437")).to_contain_text("Remove")
        self.page.locator("#lists-anime-437").get_by_role("button").first.click()

        # Edit list
        self.page.get_by_role("link", name="Lists").click()
        expect(self.page.locator("#lists-grid")).to_contain_text("test")
        expect(self.page.locator("#lists-grid")).to_contain_text("1 item")
        self.page.get_by_role("button", name="Edit list").click()
        expect(self.page.locator("#lists-grid")).to_contain_text("Edit List")
        self.page.locator("#id_1_name").click()
        self.page.locator("#id_1_name").fill("test rename")
        self.page.get_by_role("button", name="Save").click()
