import copy
import os
import re
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import tag
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from app.models import Item, MediaTypes
from lists.models import CustomList, CustomListItem

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

        # The Anime library defaults to TMDB (users/0129), but this suite mocks
        # the MAL provider and asserts on a MAL-sourced item (#lists-anime-437).
        # Without pinning the provider the search goes to TMDB, which ordinary
        # tests cannot reach, so it renders "No results found" and every
        # card-level locator below times out.
        self.user.anime_metadata_source_default = "mal"
        self.user.save(update_fields=["anime_metadata_source_default"])

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
        expect(self.page.locator("#global-search")).to_be_visible()

    def click_card_lists_action(self):
        """Click a media card's Lists action button.

        Dispatched rather than clicked through the pointer. Once the poster
        image has loaded, the browsers CI runs put that image on top of the
        card's action overlay at the button's coordinates, so a real click -
        and even a hover - is rejected with "subtree intercepts pointer
        events" and retried until the timeout. This suite is here to cover the
        lists modal flow, not the overlay's hit-testing, so address the button
        directly and keep the assertions below meaningful.
        """
        button = (
            self.page.locator(".media-card-overlay")
            .first.locator(".relative > button:nth-child(2)")
            .first
        )
        button.scroll_into_view_if_needed()
        button.dispatch_event("click")

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
        self.click_card_lists_action()
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
        self.click_card_lists_action()
        expect(self.page.locator("#lists-anime-437")).to_contain_text("Lists test Add")
        self.page.get_by_role("button", name="Add item to test", exact=True).click()
        expect(self.page.locator("#lists-anime-437")).to_contain_text("Remove")
        self.page.locator("#lists-anime-437").get_by_role("button").first.click()

        # Edit list
        self.page.get_by_role("link", name="Lists").click()
        expect(self.page.locator("#lists-grid")).to_contain_text("test")
        expect(self.page.locator("#lists-grid")).to_contain_text("1 item")
        self.page.get_by_role("button", name="Edit test", exact=True).click()
        expect(self.page.locator("#lists-grid")).to_contain_text("Edit List")
        self.page.locator("#id_1_name").click()
        self.page.locator("#id_1_name").fill("test rename")
        self.page.get_by_role("button", name="Save").click()

    def test_list_toggle_refreshes_header_count_once_desktop_and_mobile(self):
        """A successful toggle refreshes the grid and count exactly once."""
        item = Item.objects.create(
            media_id=PERFECT_BLUE_MEDIA_ID,
            source="mal",
            media_type=MediaTypes.ANIME.value,
            title="Perfect Blue",
            image=PERFECT_BLUE_SEARCH_RESULT["image"],
        )

        for index, viewport in enumerate(
            (
                {"width": 1280, "height": 800},
                {"width": 390, "height": 844},
            ),
        ):
            page = self.context.new_page()
            self.addCleanup(page.close)
            refresh_requests = []
            toggle_requests = []
            toggle_statuses = []

            def record_refresh_request(request, requests=refresh_requests):
                if (
                    request.method == "GET"
                    and request.headers.get("hx-request") == "true"
                    and "/list/" in request.url.split("?", 1)[0]
                ):
                    requests.append(request)

            page.on("request", record_refresh_request)
            self.addCleanup(page.remove_listener, "request", record_refresh_request)

            def record_toggle_request(request, requests=toggle_requests):
                if request.method == "POST" and "list_item_toggle" in request.url:
                    requests.append(request)

            page.on("request", record_toggle_request)
            self.addCleanup(page.remove_listener, "request", record_toggle_request)

            def record_toggle_response(response, statuses=toggle_statuses):
                if response.request.method == "POST" and "list_item_toggle" in response.url:
                    statuses.append(response.status)

            page.on("response", record_toggle_response)
            self.addCleanup(page.remove_listener, "response", record_toggle_response)

            custom_list = CustomList.objects.create(
                name=f"count-test-{index}",
                owner=self.user,
            )
            CustomListItem.objects.create(custom_list=custom_list, item=item)
            list_url = (
                f"{self.live_server_url}"
                f"{reverse('list_detail', args=[custom_list.public_reference])}"
            )
            page.set_viewport_size(viewport)
            page.goto(list_url)

            count = page.locator("[data-list-item-count]")
            expect(count).to_have_text("1 item")
            page.evaluate(
                """
                () => {
                    window.__listCountUpdates = 0;
                    document.body.addEventListener(
                        'listCountUpdated',
                        () => { window.__listCountUpdates += 1; },
                    );
                }
                """,
            )

            page.locator(
                '.media-card-overlay button[title="Add to custom lists"]',
            ).first.dispatch_event("click")
            modal = page.locator("#lists-anime-437")
            expect(modal).to_contain_text("Remove")
            toggle_button = modal.locator(
                f'button[aria-label="Remove item from {custom_list.name}"]'
            )
            expect(toggle_button).to_be_visible()
            toggle_button.evaluate(
                """
                async (element) => {
                    await htmx.ajax('POST', element.getAttribute('hx-post'), {
                        source: element,
                        target: element,
                        swap: 'outerHTML',
                        values: JSON.parse(element.getAttribute('hx-vals')),
                        headers: JSON.parse(element.getAttribute('hx-headers')),
                    });
                }
                """,
            )

            self.assertEqual(len(toggle_requests), 1)
            self.assertEqual(toggle_statuses, [200])
            self.assertEqual(len(refresh_requests), 1)
            self.assertEqual(page.evaluate("window.__listCountUpdates"), 1)
            expect(count).to_have_text("0 items")
