"""Browser regression coverage for the Home settings menu controls."""

import json
import os
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import tag
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from app.tests.live_server import SerialStaticLiveServerTestCase
from users.home_screen import save_home_screen_configuration


@tag("slow", "playwright")
class HomeScreenMenuTests(SerialStaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        environment = patch.dict(os.environ, {"DJANGO_ALLOW_ASYNC_UNSAFE": "true"})
        environment.start()
        cls.addClassCleanup(environment.stop)
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch()
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        user = get_user_model().objects.create_user(username="menu-test")
        save_home_screen_configuration(
            user,
            json.dumps(
                [
                    {
                        "media_type": "movie",
                        "rows": [
                            {
                                "row_type": "library_query",
                                "enabled": True,
                                "filters": {"status": [status]},
                                "sort_by": "title",
                            }
                            for status in ("In progress", "Planning", "Completed")
                        ],
                    }
                ]
            ),
        )
        self.client.force_login(user)
        # Service-worker requests can bypass the route used to inject filter options.
        self.page = self.browser.new_page(
            viewport={"width": 1280, "height": 900}, service_workers="block"
        )
        self.addCleanup(self.page.close)
        self.page.context.add_cookies(
            [
                {
                    "name": settings.SESSION_COOKIE_NAME,
                    "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
                    "url": self.live_server_url,
                }
            ]
        )
        self.page.goto(self.live_server_url + reverse("home_screen"))
        self.section = self.page.locator('[data-section-media-type="movie"]')
        self.section.locator("h3").click()

    def test_row_title_can_be_clicked_and_saved(self):
        self.page.wait_for_function("window.homeScreenSettingsInstance.sortables.length > 0")
        title = self.section.locator("article").first.get_by_label("Row name")
        title.click()
        expect(title).to_be_focused()
        title.fill("My movies")
        self.page.get_by_role("button", name="Save Home Screen").click()
        self.section.locator("h3").click()
        expect(self.section.locator("article").first.get_by_label("Row name")).to_have_value(
            "My movies"
        )

    def test_last_watched_preset_saves_a_mixed_library_row(self):
        section = self.page.locator('[data-section-media-type="all"]')
        section.locator("h3").click()
        section.get_by_role("button", name="Add Row", exact=True).click()
        section.get_by_role("button", name="Last Watched", exact=True).click()
        row = section.locator("article").last
        expect(row.get_by_label("Row name")).to_have_value("Last Watched")
        self.page.get_by_role("button", name="Save Home Screen").click()
        self.page.reload()
        saved = self.page.evaluate("""() => window.homeScreenSettingsInstance.sections
            .find(section => section.media_type === 'all').rows
            .find(row => row.custom_title === 'Last Watched')""")
        self.assertEqual(saved["row_type"], "library_query")
        self.assertEqual(saved["sort_by"], "end_date")
        self.assertEqual(saved["direction"], "desc")
        self.assertEqual(set(saved["filters"]["media_types"]), {"movie", "tv"})
        self.assertEqual(
            set(saved["filters"]["status"]),
            {"In progress", "Completed", "Paused", "Dropped"},
        )
        self.assertEqual(saved["filters"]["progress"], "all")

    def test_all_media_nested_levels_save_and_keyboard_backtracks(self):
        errors = []
        self.page.on("pageerror", lambda error: errors.append(str(error)))
        section = self.page.locator('[data-section-media-type="all"]')
        section.locator("h3").click()
        section.get_by_role("button", name="Add Row", exact=True).click()
        section.get_by_role("button", name="Library Row", exact=True).click()
        row = section.locator("article").last
        trigger = row.locator(".filter-control").first.locator("button").first
        trigger.click()
        row.get_by_role("button", name="Media types", exact=False).last.click()
        for family, level in (("TV Shows", "Episodes"), ("Music", "Albums"), ("Podcasts", "Shows")):
            arrow = row.get_by_role("button", name=f"Display level for {family}", exact=True)
            if family == "Music":
                arrow.focus()
                self.page.keyboard.press("Enter")
            else:
                arrow.click()
            family_value = {"TV Shows": "tv", "Music": "music", "Podcasts": "podcast"}[family]
            self.assertEqual(row.evaluate("element => Alpine.$data(element).filterView"), f"media_subview:{family_value}", errors)
            option = row.get_by_role("button", name=level, exact=True)
            if family == "Music":
                option.focus()
                self.page.keyboard.press("Enter")
            else:
                option.click()
            expect(option).to_have_attribute("aria-pressed", "true")
            expect(option.locator("svg.text-green-400")).to_be_visible()
            if family == "TV Shows":
                row.get_by_role("button", name="Back", exact=True).click()
                expect(arrow).to_be_focused()
                arrow.click()
                option.focus()
            self.page.keyboard.press("Escape")
            expect(arrow).to_be_visible()
            expect(arrow).to_be_focused()
        self.page.keyboard.press("Escape")
        expect(trigger).to_have_attribute("aria-expanded", "true")
        expect(row.locator('[data-filter-field="media_types"]')).to_be_focused()
        self.page.keyboard.press("Escape")
        expect(trigger).to_have_attribute("aria-expanded", "false")
        expect(trigger).to_be_focused()
        self.assertEqual(errors, [])
        self.page.get_by_role("button", name="Save Home Screen").click()
        self.page.reload()
        saved = self.page.evaluate("""() => window.homeScreenSettingsInstance.sections
            .find(section => section.media_type === 'all').rows.at(-1)""")
        self.assertEqual(saved["filters"]["media_subviews"], {"tv": "episodes", "music": "albums", "podcast": "shows"})

    def test_filter_menu_does_not_render_unopened_option_lists(self):
        def many_tags(route):
            response = route.fetch()
            payload = response.json()
            field = next(field for field in payload["filter_fields"] if field["key"] == "tag")
            field["options"] = [{"value": f"Tag {index}", "label": f"Tag {index}"} for index in range(2000)]
            route.fulfill(response=response, json=payload)

        self.page.route("**/filter-fields?media_type=all", many_tags)
        section = self.page.locator('[data-section-media-type="all"]')
        section.locator("h3").click()
        section.get_by_role("button", name="Add Row", exact=True).click()
        section.get_by_role("button", name="Library Row", exact=True).click()
        row = section.locator("article").last
        trigger = row.locator(".filter-control").first.locator("button").first
        self.page.wait_for_function("""() => window.homeScreenSettingsInstance.sections
            .find(section => section.media_type === 'all').filter_fields
            .find(field => field.key === 'tag')?.options.length === 2000""")
        trigger.click()
        expect(row.get_by_role("button", name="Media types", exact=False)).to_be_visible()
        self.assertEqual(row.locator("button").filter(has_text="Tag 1999").count(), 0)
        row.get_by_role("button", name="Media types", exact=False).click()
        expect(row.get_by_role("button", name="Display level for TV Shows")).to_be_visible()
        self.assertEqual(row.locator("button").filter(has_text="Tag 1999").count(), 0)

    def test_sort_menu_receives_clicks_and_escape_restores_focus(self):
        for width in (1280, 768, 390):
            with self.subTest(width=width):
                self.page.set_viewport_size({"width": width, "height": 900})
                self.page.reload()
                with self.page.expect_response(
                    lambda response: "filter-fields" in response.url
                ):
                    self.section.locator("h3").click()
                row = self.section.locator("article").first
                control = row.locator(".filter-control").nth(2)
                trigger = control.locator("button").first
                trigger.focus()
                self.page.keyboard.press("Enter")
                expect(trigger).to_have_attribute("aria-expanded", "true")
                self.assertFalse(
                    self.page.evaluate(
                        "document.documentElement.scrollWidth > innerWidth"
                    ),
                    "An open Home row menu must fit the viewport",
                )
                option = control.get_by_role(
                    "button", name="Date Added", exact=True
                ).last
                option.focus()
                self.page.keyboard.press("Escape")
                expect(trigger).to_have_attribute("aria-expanded", "false")
                expect(trigger).to_be_focused()
                trigger.click()
                # Playwright's normal click fails if a neighboring row covers it.
                option.click()
                expect(trigger).to_contain_text("Date Added")
                expect(trigger).to_have_attribute("aria-expanded", "false")

    def test_add_row_menu_can_be_closed_from_a_keyboard_focused_option(self):
        trigger = self.section.get_by_role("button", name="Add Row", exact=True)
        trigger.focus()
        self.page.keyboard.press("Enter")
        expect(trigger).to_have_attribute("aria-expanded", "true")
        self.section.get_by_role("button", name="Library Row", exact=True).focus()
        self.page.keyboard.press("Escape")
        expect(trigger).to_have_attribute("aria-expanded", "false")
        expect(trigger).to_be_focused()

    def test_filter_and_status_menus_stay_above_neighboring_rows(self):
        for width in (1280, 768, 390):
            with self.subTest(width=width):
                self.page.set_viewport_size({"width": width, "height": 900})
                self.page.reload()
                self.section.locator("h3").click()
                row = self.section.locator("article").first

                filter_control = row.locator(".filter-control").first
                filter_trigger = filter_control.locator("button").first
                filter_trigger.click()
                expect(filter_trigger).to_have_attribute("aria-expanded", "true")
                filter_control.get_by_role("button", name="All", exact=True).click()
                expect(filter_trigger).to_have_attribute("aria-expanded", "false")

                status_control = row.locator(".filter-control").nth(1)
                status_trigger = status_control.locator("button").first
                status_trigger.click()
                expect(status_trigger).to_have_attribute("aria-expanded", "true")
                status_control.get_by_role(
                    "button", name="Planning", exact=True
                ).click()
                self.assertFalse(
                    self.page.evaluate(
                        "document.documentElement.scrollWidth > innerWidth"
                    ),
                    "Home row menus must fit the viewport",
                )
