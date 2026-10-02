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
        self.page = self.browser.new_page(viewport={"width": 1280, "height": 900})
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
