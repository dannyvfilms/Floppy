import os
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import tag
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from app.models import Sources
from app.tests.live_server import SerialStaticLiveServerTestCase


@tag("slow", "playwright")
class PeopleDiscoveryBrowserTests(SerialStaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        cls.async_environment = patch.dict(os.environ, {"DJANGO_ALLOW_ASYNC_UNSAFE": "true"})
        cls.async_environment.start()
        super().setUpClass()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        super().tearDownClass()
        cls.async_environment.stop()

    def setUp(self):
        self.credentials = {"username": "people-browser", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

    def signed_in_page(self, viewport=None):
        context = self.browser.new_context(
            viewport=viewport or {"width": 1280, "height": 900},
        )
        self.addCleanup(context.close)
        page = context.new_page()
        page.goto(f"{self.live_server_url}/")
        page.get_by_placeholder("Enter your username").fill(self.credentials["username"])
        page.get_by_placeholder("Enter your password").fill(self.credentials["password"])
        page.get_by_role("button", name="Sign in").click()
        expect(page.get_by_role("button", name="Explore")).to_be_visible()
        return page

    @patch("app.providers.tmdb.person")
    @patch("app.providers.tmdb.search_people")
    def test_sidebar_search_opens_the_existing_advanced_person_profile(self, search_people, person):
        search_people.return_value = [
            {
                "person_id": "123",
                "name": "Jane Star",
                "image": None,
                "known_for_department": "Acting",
                "known_for": ["Film One"],
            },
            {
                "person_id": "456",
                "name": "Jane Star",
                "image": None,
                "known_for_department": "Directing",
                "known_for": ["Film Two"],
            },
        ]
        person.return_value = {
            "person_id": "456",
            "source": Sources.TMDB.value,
            "name": "Jane Star",
            "image": "",
            "biography": "",
            "known_for_department": "Directing",
            "gender": "unknown",
            "birth_date": None,
            "death_date": None,
            "place_of_birth": "",
            "filmography": [],
        }
        page = self.signed_in_page()
        page.get_by_role("button", name="Explore").click()
        page.get_by_role("link", name="Discover people", exact=True).click()
        search = page.get_by_test_id("people-search")
        expect(search).to_be_visible()
        review_dir = Path.cwd() / ".floppy" / "review-shots" / "people-search"
        review_dir.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=review_dir / "before-search-desktop.png")
        search_input = page.get_by_role("textbox", name="Person name")
        search_input.fill("Jane Star")
        search.get_by_role("button", name="Search", exact=True).click()
        profile = search.get_by_role("link", name="Open profile: Jane Star").nth(1)
        expect(profile).to_be_visible()
        page.screenshot(path=review_dir / "after-search-desktop.png")
        profile.click()
        page.wait_for_url("**" + reverse(
            "person_detail",
            kwargs={"source": Sources.TMDB.value, "person_id": "456", "name": "jane-star"},
        ))
        expect(page.get_by_role("heading", name="Jane Star")).to_be_visible()
        search_people.assert_called_once_with("Jane Star")
        person.assert_called_once_with("456")

        phone_page = self.signed_in_page({"width": 390, "height": 844})
        phone_page.get_by_role("button", name="Toggle navigation menu").click()
        phone_page.get_by_role("button", name="Explore").click()
        phone_page.get_by_role("link", name="Discover people", exact=True).click()
        phone_search = phone_page.get_by_test_id("people-search")
        expect(phone_search).to_be_visible()
        phone_search.get_by_role("textbox", name="Person name").fill("Jane Star")
        phone_search.get_by_role("button", name="Search", exact=True).click()
        expect(phone_search.get_by_role("link", name="Open profile: Jane Star").nth(1)).to_be_visible()
        phone_page.screenshot(path=review_dir / "after-search-phone.png")
        bounds = phone_search.bounding_box()
        self.assertLessEqual(bounds["x"] + bounds["width"], 390)
        phone_page.get_by_role("link", name="Open profile: Jane Star").nth(1).click()
        phone_page.wait_for_url("**" + reverse(
            "person_detail",
            kwargs={"source": Sources.TMDB.value, "person_id": "456", "name": "jane-star"},
        ))
        expect(phone_page.get_by_role("heading", name="Jane Star")).to_be_visible()
        phone_page.screenshot(path=review_dir / "after-person-profile-phone.png")
        self.assertEqual(search_people.call_count, 2)
        self.assertEqual(person.call_count, 2)
