"""Browser behavior of the shared sidebar's account links."""

import os
import sys
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
            logout_url = self.live_server_url + reverse("account_logout")
            # CI Chromium sometimes opens the modifier-click tab but never loads
            # it (the tab's URL stays empty), so retry the click, not the check.
            for attempt in range(3):
                with context.expect_page() as opened:
                    logout.click(modifiers=["Meta" if sys.platform == "darwin" else "Control"])
                confirmation = opened.value
                try:
                    # A new tab starts on about:blank, which already counts as
                    # loaded, so wait for the logout page's own address.
                    expect(confirmation).to_have_url(logout_url, timeout=10000)
                    break
                except AssertionError:
                    if attempt == 2:
                        raise
                    confirmation.close()
            confirmation.wait_for_load_state()
            self.assertEqual(context.request.get(self.live_server_url + reverse("account")).status, 200)
            confirmation.close()
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
