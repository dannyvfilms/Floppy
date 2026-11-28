import os
import re
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.test import override_settings, tag
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from app.tests.live_server import SerialStaticLiveServerTestCase


@tag("slow", "playwright")
class AdvancedDiscoverBrowserTests(SerialStaticLiveServerTestCase):
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
        self.credentials = {"username": "advanced-discover-browser", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

    def signed_in_page(self):
        context = self.browser.new_context(
            viewport={"width": 1280, "height": 900},
            color_scheme="dark",
        )
        self.addCleanup(context.close)
        page = context.new_page()
        page.goto(f"{self.live_server_url}/")
        page.get_by_placeholder("Enter your username").fill(self.credentials["username"])
        page.get_by_placeholder("Enter your password").fill(self.credentials["password"])
        page.get_by_role("button", name="Sign in").click()
        expect(page.get_by_role("button", name="Explore")).to_be_visible()
        return page

    @override_settings(TMDB_NSFW=True)
    @patch("app.people_views.tmdb.discovery_country_names", return_value={"US": "United States"})
    @patch("app.people_views.tmdb.discovery_certifications")
    def test_stages_people_country_certification_and_renders_shared_results(
        self,
        certifications,
        country_names,
    ):
        certifications.return_value = {
            "US": [
                {"certification": "R", "meaning": "Restricted"},
                {"certification": "NR", "meaning": "No rating information"},
            ],
        }
        page = self.signed_in_page()
        discovery_calls = []

        def fulfill_discovery(route):
            params = parse_qs(urlparse(route.request.url).query)
            if params.get("action") == ["people"]:
                return route.fulfill(json={"people": [{
                    "person_id": "123",
                    "name": "Keanu Reeves",
                    "image": None,
                    "known_for_department": "Acting",
                    "known_for": [],
                }]})
            if params.get("search") == ["1"]:
                discovery_calls.append(params)
                adult_only = params.get("adult_mode") == ["only"]
                result = {
                    "id": "movie:99",
                    "title": "The Matrix",
                    "mediaType": "movie",
                    "mediaTypeLabel": "Movie",
                    "source": "tmdb",
                    "mediaId": "99",
                    "year": "2024",
                    "role": "",
                    "imageUrl": "https://image.tmdb.org/t/p/w500/poster.jpg",
                    "href": "/details/tmdb/movie/99/the-matrix",
                    "watched": False,
                    "watchedRuntimeLabel": "",
                    "voteAverage": None,
                    "card": {
                        "title": "The Matrix",
                        "href": "/details/tmdb/movie/99/the-matrix",
                        "shape": "poster",
                        "image": {"src": "https://image.tmdb.org/t/p/w500/poster.jpg"},
                        "lines": [{"parts": [{"text": "2024"}]}],
                        "cornerChips": [],
                    },
                }
                return route.fulfill(json={
                    "results": [] if adult_only else [result],
                    "page": int(params.get("page", ["1"])[0]),
                    "totalPages": None if adult_only else 4,
                    "hasNextPage": True,
                    "totalResults": None if adult_only else 1,
                    "searched": True,
                    "error": "",
                    "adultMode": params.get("adult_mode", ["exclude"])[0],
                })
            return route.continue_()

        page.route("**/discover/advanced?*", fulfill_discovery)
        page.goto(f"{self.live_server_url}{reverse('advanced_discover')}")
        root = page.locator("[data-people-hero-root]")
        expect(page.get_by_role("heading", name="Advanced discover")).to_be_visible()
        root.get_by_role("textbox", name="People").fill("Keanu")
        expect(root.get_by_role("button", name="Add Keanu Reeves")).to_be_visible()
        root.get_by_role("button", name="Add Keanu Reeves").click()
        expect(page.get_by_text("Keanu Reeves", exact=True)).to_be_visible()

        root.get_by_role("button", name=re.compile("^Certification country:")).click()
        page.get_by_role("radio", name="United States (US)").click()
        root.get_by_role("button", name=re.compile("^Certification:")).click()
        page.get_by_role("radio", name="R — Restricted").click()
        root.get_by_role("button", name=re.compile("^Certification:")).click()
        page.get_by_role("radio", name="NR — No rating information").click()
        expect(root.get_by_text("Any selected certification")).to_be_visible()
        root.get_by_role("button", name="Match people as: Cast, crew, or either").click()
        page.get_by_role("radio", name="Cast", exact=True).click()
        root.get_by_role("button", name="Match: All people").click()
        page.get_by_role("radio", name="Any person").click()
        root.get_by_role("button", name="Sort by: Release date").click()
        page.get_by_role("radio", name="Votes", exact=True).click()
        screenshot_dir = Path.cwd() / ".floppy" / "review-shots" / "advanced-discover"
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(screenshot_dir / "advanced-discover-before-search-desktop.png"))
        root.get_by_role("button", name="Search", exact=True).click()
        self.assertEqual(len(discovery_calls), 1)
        expect(page.get_by_text("The Matrix", exact=True)).to_be_visible()
        expect(page.get_by_text("TMDB Adult", exact=True)).to_have_count(0)
        expect(page.get_by_text("1 / 4", exact=True)).to_be_visible()
        title_color = page.locator(".media-card-title").first.evaluate(
            "element => getComputedStyle(element).color",
        )
        page_text_color = page.evaluate("""() => {
            const probe = document.createElement("span");
            probe.style.color = getComputedStyle(document.documentElement).getPropertyValue("--color-text");
            document.body.append(probe);
            const color = getComputedStyle(probe).color;
            probe.remove();
            return color;
        }""")
        self.assertEqual(title_color, page_text_color)
        expect(page.get_by_role("link", name="The Matrix").first).to_have_attribute(
            "href", "/details/tmdb/movie/99/the-matrix",
        )
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.screenshot(path=str(screenshot_dir / "advanced-discover-after-search-desktop.png"))
        first_query = discovery_calls[0]
        self.assertEqual(first_query["adult_mode"], ["exclude"])
        self.assertEqual(first_query["person_role"], ["cast"])
        self.assertEqual(first_query["person"], ["123"])
        self.assertEqual(first_query["certification"], ["R", "NR"])
        root.get_by_role("button", name="Adult titles: Exclude adult titles").click()
        page.get_by_role("radio", name="Adult titles only").click()
        root.get_by_role("button", name="Search", exact=True).click()
        expect(page.get_by_text("The Matrix", exact=True)).to_have_count(0)
        expect(page.get_by_text("No adult-flagged titles on this TMDB page.", exact=True)).to_be_visible()
        expect(page.get_by_text("Page 1", exact=True)).to_be_visible()
        expect(page.get_by_text("1 / 4", exact=True)).to_have_count(0)
        self.assertEqual(len(discovery_calls), 2)
        self.assertEqual(discovery_calls[1]["adult_mode"], ["only"])

        page.get_by_role("button", name="Next").click()
        expect(page.get_by_text("Page 2", exact=True)).to_be_visible()
        self.assertEqual(len(discovery_calls), 3)
        self.assertEqual(discovery_calls[2]["page"], ["2"])

        page.set_viewport_size({"width": 390, "height": 844})
        page.reload()
        root = page.locator("[data-people-hero-root]")
        expect(root).to_be_visible()
        root.get_by_role("textbox", name="People").fill("Keanu")
        expect(root.get_by_role("button", name="Add Keanu Reeves")).to_be_visible()
        root.get_by_role("button", name="Add Keanu Reeves").click()
        bounds = root.bounding_box()
        self.assertLessEqual(bounds["x"] + bounds["width"], 390)
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(screenshot_dir / "advanced-discover-before-search-phone.png"))
        root.get_by_role("button", name="Search", exact=True).click()
        expect(page.get_by_text("The Matrix", exact=True)).to_be_visible()
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.screenshot(path=str(screenshot_dir / "advanced-discover-after-search-phone.png"))

    @override_settings(TMDB_NSFW=True)
    @patch("app.people_views.tmdb.person")
    def test_filmography_adult_filter_row_is_visible_without_selecting_adult_only(self, person):
        person.return_value = {
            "person_id": "6384",
            "source": "tmdb",
            "name": "Keanu Reeves",
            "image": "",
            "biography": "",
            "known_for_department": "Acting",
            "gender": "male",
            "birth_date": None,
            "death_date": None,
            "place_of_birth": "",
            "filmography": [],
        }
        page = self.signed_in_page()
        page.goto(f"{self.live_server_url}{reverse('person_detail', kwargs={'source': 'tmdb', 'person_id': '6384', 'name': 'keanu-reeves'})}")
        expect(page.get_by_role("heading", name="Keanu Reeves")).to_be_visible()
        filters = page.get_by_role("button", name="Filters: All", exact=True)
        expect(filters).to_be_visible()
        filters.click()
        adult_titles = page.get_by_role("menuitem", name="Adult titles", exact=True)
        expect(adult_titles).to_be_visible()
        screenshot_dir = Path.cwd() / ".floppy" / "review-shots" / "filmography-adult-filter"
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(screenshot_dir / "before-adult-filter-row.png"))
        adult_titles.click()
        expect(page.get_by_role("radio", name="Show default", exact=True)).to_be_checked()
        expect(page.get_by_text("Only Adult", exact=True)).to_be_visible()
        page.screenshot(path=str(screenshot_dir / "after-adult-filter-row.png"))
