import os
import time
from unittest.mock import patch
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.test import tag
from django.urls import reverse
from playwright.sync_api import sync_playwright

from app.tests.live_server import SerialStaticLiveServerTestCase
from lists.models import CustomList


@tag("slow", "playwright")
class SpinnerBrowserTests(SerialStaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.allow_async = patch.dict(os.environ, {"DJANGO_ALLOW_ASYNC_UNSAFE": "true"})
        cls.allow_async.start()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.allow_async.stop()
        super().tearDownClass()

    def test_public_and_private_list_htmx_search(self):
        user = get_user_model().objects.create_user(username="spinner-proof")
        public = CustomList.objects.create(
            owner=user, name="Public spinner proof", visibility="public"
        )
        private = CustomList.objects.create(owner=user, name="Private spinner proof")
        self.client.force_login(user)
        for surface, item in (("public", public), ("private", private)):
            with self.subTest(surface=surface):
                context = self.browser.new_context(
                    viewport={"width": 390, "height": 844}, service_workers="block"
                )
                if surface == "private":
                    context.add_cookies(
                        [
                            {
                                "name": "sessionid",
                                "value": self.client.cookies["sessionid"].value,
                                "url": self.live_server_url,
                            }
                        ]
                    )

                def route_request(route):
                    if (
                        urlsplit(route.request.url).netloc
                        == urlsplit(self.live_server_url).netloc
                    ):
                        if route.request.headers.get("hx-request") == "true":
                            time.sleep(0.8)
                        route.continue_()
                    else:
                        route.abort()

                context.route("**/*", route_request)
                page = context.new_page()
                errors = []
                page.on(
                    "pageerror", lambda error, errors=errors: errors.append(str(error))
                )
                path = reverse("list_detail", args=[item.public_reference])
                page.goto(self.live_server_url + path, wait_until="domcontentloaded")
                page.wait_for_selector(
                    "#search-indicator-mobile [data-react-mounted]", state="attached"
                )
                ring = page.locator("#search-indicator-mobile [data-spinner-root] > *")
                self.assertEqual(ring.get_attribute("aria-hidden"), "true")
                self.assertEqual(ring.evaluate("e=>getComputedStyle(e).width"), "16px")
                page.evaluate(
                    """() => {
                      window.spinnerEvents = [];
                      document.body.addEventListener('htmx:beforeSend', () => {
                        setTimeout(() => {
                          const indicator = document.querySelector('#search-indicator-mobile');
                          const ring = indicator.querySelector('[data-spinner-root] > *');
                          window.spinnerEvents.push({
                            busy: indicator.classList.contains('htmx-request'),
                            transform: getComputedStyle(ring).transform,
                            visible: getComputedStyle(indicator).opacity
                          });
                        }, 200);
                        setTimeout(() => {
                          const ring = document.querySelector('#search-indicator-mobile [data-spinner-root] > *');
                          window.spinnerEvents.push({later: getComputedStyle(ring).transform});
                        }, 450);
                      });
                      document.body.addEventListener('htmx:afterSwap', event => {
                        if (event.detail.target.id === 'items-view') window.spinnerEvents.push('swap');
                      });
                    }"""
                )
                page.locator("#search-input-mobile").fill("unmatched")
                page.locator("#search-input-mobile").press("d")
                page.wait_for_function(
                    "window.spinnerEvents.includes('swap')", timeout=15000
                )
                events = page.evaluate("window.spinnerEvents")
                busy = next(
                    event
                    for event in events
                    if isinstance(event, dict) and event.get("busy")
                )
                later = next(
                    event["later"]
                    for event in events
                    if isinstance(event, dict) and "later" in event
                )
                self.assertEqual(busy["visible"], "1")
                self.assertNotEqual(busy["transform"], later)
                self.assertEqual(
                    page.locator(
                        "#search-indicator-mobile [data-react-mounted]"
                    ).count(),
                    1,
                )
                if surface == "private":
                    page.set_viewport_size({"width": 1440, "height": 900})
                    page.reload(wait_until="domcontentloaded")
                    page.wait_for_selector(
                        "#search-indicator-mobile [data-react-mounted]",
                        state="attached",
                    )
                    page.evaluate(
                        "window.previousSpinner = document.querySelector('#search-indicator-mobile [data-spinner-root]')"
                    )
                    page.locator('#sidebar-nav a[href="/"]').first.evaluate(
                        "element => element.click()"
                    )
                    page.wait_for_url(self.live_server_url + "/", timeout=15000)
                    self.assertTrue(
                        page.evaluate(
                            "!window.previousSpinner.isConnected && !window.previousSpinner.hasAttribute('data-react-mounted')"
                        )
                    )
                    page.go_back(wait_until="domcontentloaded")
                    page.wait_for_selector(
                        "#search-indicator-mobile [data-react-mounted]",
                        state="attached",
                    )
                self.assertFalse(errors, errors)
                context.close()
