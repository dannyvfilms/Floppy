"""Browser behavior of the shared sidebar's account links."""

import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import tag
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from app.tests.live_server import SerialStaticLiveServerTestCase


@tag("slow", "playwright")
class SidebarLinksBrowserTests(SerialStaticLiveServerTestCase):
    def test_links_and_logout(self):
        user = get_user_model().objects.create_user(username="sidebar-links")
        self.client.force_login(user)
        with (
            patch.dict("os.environ", {"DJANGO_ALLOW_ASYNC_UNSAFE": "true"}),
            sync_playwright() as playwright,
            playwright.chromium.launch(executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")) as browser,
        ):
            context = browser.new_context(service_workers="block")
            context.add_cookies([{
                "name": "sessionid", "value": self.client.cookies["sessionid"].value,
                "url": self.live_server_url,
            }])
            page = context.new_page()
            page.goto(self.live_server_url + reverse("lists"))
            sidebar = page.locator("[data-sidebar-root]")
            expect(sidebar).to_have_attribute("data-react-mounted", "true", timeout=15000)
            settings = sidebar.get_by_role("link", name="Settings", exact=True)
            logout = sidebar.get_by_role("link", name="Logout", exact=True)
            expect(settings).to_have_attribute("href", reverse("account"))
            expect(logout).to_have_attribute("href", reverse("account_logout"))
            # A modifier-click must stay a plain link click so the browser can open
            # it in a new tab. Opening a real tab is not asserted: CI Chromium
            # sometimes never opens or loads it. Instead dispatch the click and
            # check, after the sidebar's own handlers have run (window bubble
            # phase), that nothing cancelled it and no POST was sent. The probe
            # cancels it afterwards so the test page does not navigate.
            posts = []
            page.on("request", lambda request: posts.append(request.url) if request.method == "POST" else None)
            cancelled = page.evaluate(
                """() => new Promise((resolve) => {
                    const link = document.querySelector('[data-sidebar-root] a[href$="/accounts/logout/"]');
                    window.addEventListener('click', (event) => {
                        resolve(event.defaultPrevented);
                        event.preventDefault();
                    }, {once: true});
                    link.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, ctrlKey: true, metaKey: true}));
                })"""
            )
            self.assertFalse(cancelled, "the sidebar cancelled a modifier-click on Logout")
            page.wait_for_timeout(500)
            self.assertEqual(posts, [])
            self.assertEqual(context.request.get(self.live_server_url + reverse("account")).status, 200)
            page.bring_to_front()
            with page.expect_request(lambda request: request.method == "POST" and
                                     request.url.endswith(reverse("account_logout")), timeout=5000):
                logout.press("Enter")
            page.wait_for_url(lambda url: reverse("account_logout") not in str(url))
            self.assertNotEqual(context.request.get(self.live_server_url + reverse("account"), max_redirects=0).status, 200)
            self.client.force_login(user)
            context.add_cookies([{
                "name": "sessionid", "value": self.client.cookies["sessionid"].value,
                "url": self.live_server_url,
            }])
            page.goto(self.live_server_url + reverse("lists"))
            expect(sidebar).to_have_attribute("data-react-mounted", "true", timeout=15000)
            with page.expect_request(lambda request: request.method == "POST" and
                                     request.url.endswith(reverse("account_logout")), timeout=5000):
                sidebar.get_by_role("link", name="Logout", exact=True).click()
            context.close()
