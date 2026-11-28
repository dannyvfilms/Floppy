"""Browser lifecycle of the Access & Tokens copy control.

The account-token copy control is the shared CopyField when the React island
mounts, and the server control wired by copy-item.js otherwise. These tests run
the real page, bundle and htmx in Chromium against a local test server. Writes
to the clipboard are recorded in the page instead of reaching the system
clipboard, so they show what was copied, not that the OS clipboard received it.
"""

import os
from unittest.mock import patch
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.test import tag
from playwright.sync_api import expect, sync_playwright

from app.tests.live_server import SerialStaticLiveServerTestCase

HOST = '[data-copy-field-root][data-props-id="access-token-copy-props"]'
LEGACY_CONTROL = 'span[data-copy-target="#token"]'

# Record copies made through the Clipboard API (both CopyField and copy-item.js
# use it on a secure localhost page). `window.failCopies` makes it reject.
RECORD_CLIPBOARD = """(() => {
  window.copiedTexts = [];
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText: async (text) => {
      if (window.failCopies) throw new Error('denied');
      window.copiedTexts.push(text);
    } },
  });
})()"""

# The same event htmx fires before removing an element; the island loader
# disposes the root and the root restores its cloned server fallback.
DISPOSE_HOST = f"""() => {{
  const host = document.querySelector('{HOST}');
  host.dispatchEvent(new CustomEvent('htmx:beforeCleanupElement', {{
    bubbles: true, detail: {{ elt: host }},
  }}));
}}"""

# True when the token input's whole, non-empty value is selected. Returns only
# a boolean so a failure never prints the token.
SELECTED_ALL = """() => {
  const input = document.querySelector('#token');
  return input.value.length > 0 && input.selectionStart === 0
    && input.selectionEnd === input.value.length;
}"""

# True once exactly `count` copies were recorded and each was the token. The
# token is compared in the page so a failure never prints it.
COPIED = """([token, count]) => window.copiedTexts.length === count
  && window.copiedTexts.every((text) => text === token)"""


@tag("slow", "playwright")
class AccessCopyBrowserTests(SerialStaticLiveServerTestCase):
    """Copy the account token through mount, dispose and boosted navigation."""

    @classmethod
    def setUpClass(cls):
        """Start Chromium with the synchronous Django boundary used elsewhere."""
        super().setUpClass()
        cls.async_override = patch.dict(os.environ, {"DJANGO_ALLOW_ASYNC_UNSAFE": "true"})
        cls.async_override.start()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        """Release Chromium and restore the Django async guard."""
        cls.browser.close()
        cls.playwright.stop()
        cls.async_override.stop()
        super().tearDownClass()

    def setUp(self):
        """Sign a fresh user in to an isolated browser context."""
        self.user = get_user_model().objects.create_user(username="copy-proof")
        self.client.force_login(self.user)
        self.errors = []
        self.block_renderer = False
        self.context = self.browser.new_context(
            viewport={"width": 1280, "height": 900}, service_workers="block",
        )
        self.addCleanup(self.context.close)
        self.context.add_cookies([{
            "name": "sessionid", "value": self.client.cookies["sessionid"].value,
            "url": self.live_server_url,
        }])
        self.context.route("**/*", self.serve)
        self.context.add_init_script(RECORD_CLIPBOARD)
        self.page = self.context.new_page()
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))

    def serve(self, route):
        """Serve only the local app; optionally fail the React mount chunks."""
        url = urlsplit(route.request.url)
        if url.netloc != urlsplit(self.live_server_url).netloc or (
            self.block_renderer and "/static/ui/mount" in url.path
        ):
            route.abort()
        else:
            route.continue_()

    def expect_copies(self, count):
        """Wait until exactly `count` copies of the account token were made."""
        self.page.wait_for_function(COPIED, arg=[self.user.token, count])

    def test_mounted_copy_then_restored_fallback_copies(self):
        """Initialized fallback -> mount -> dispose -> the restored control copies."""
        self.page.goto(f"{self.live_server_url}/settings/access")
        host = self.page.locator(HOST)
        expect(host).to_have_attribute("data-react-mounted", "true")
        self.assertTrue(self.page.evaluate("() => window.floppyCopyItemsReady === true"))
        # The server input is the field's value; the legacy icon is gone.
        expect(self.page.locator("#token")).to_have_count(1)
        expect(host.locator("#token")).to_be_visible()
        expect(host.locator(LEGACY_CONTROL)).to_have_count(0)

        self.page.get_by_role("button", name="Copy API token").click()
        self.expect_copies(1)
        expect(self.page.get_by_role("button", name="Copied!")).to_be_visible()

        self.page.evaluate(DISPOSE_HOST)
        expect(host).not_to_have_attribute("data-react-mounted", "true")
        restored = host.locator(LEGACY_CONTROL)
        expect(restored).to_have_count(1)
        restored.click()
        self.expect_copies(2)
        expect(restored.locator("svg.text-emerald-400")).to_have_count(1)
        self.assertEqual(self.errors, [])

    def test_mounted_input_selects_all_on_click_for_manual_recovery(self):
        """After a failed copy the mounted token input still selects all on click."""
        self.page.goto(f"{self.live_server_url}/settings/access")
        host = self.page.locator(HOST)
        expect(host).to_have_attribute("data-react-mounted", "true")
        token_input = host.locator("#token")

        token_input.click()
        self.assertTrue(self.page.evaluate(SELECTED_ALL))

        # Fail both the Clipboard API and the execCommand fallback.
        self.page.evaluate(
            "() => { window.failCopies = true; document.execCommand = () => false; }"
        )
        self.page.get_by_role("button", name="Copy API token").click()
        expect(host.get_by_text("Could not copy automatically.")).to_be_visible()
        # The recovery dialog is a modal portal at the end of <body>.
        self.page.get_by_role("button", name="Close", exact=True).last.click()

        # Clear the selection, then select manually as the recovery text says.
        self.page.evaluate(
            "() => document.querySelector('#token').setSelectionRange(0, 0)"
        )
        self.assertFalse(self.page.evaluate(SELECTED_ALL))
        token_input.click()
        self.assertTrue(self.page.evaluate(SELECTED_ALL))
        self.assertEqual(self.page.evaluate("() => window.copiedTexts.length"), 0)
        self.assertEqual(self.errors, [])

    def test_server_control_copies_when_the_island_cannot_load(self):
        """Without the React chunks the server control still copies."""
        self.block_renderer = True
        self.page.goto(f"{self.live_server_url}/settings/access")
        host = self.page.locator(HOST)
        control = host.locator(LEGACY_CONTROL)
        expect(control).to_be_visible()
        expect(host).not_to_have_attribute("data-react-mounted", "true")

        control.click()
        self.expect_copies(1)

    def test_boosted_navigation_mounts_and_copies_once(self):
        """Boosted visits remount the field and never double-wire copy-item.js."""
        self.page.goto(f"{self.live_server_url}/settings/access")
        expect(self.page.locator(HOST)).to_have_attribute("data-react-mounted", "true")
        nav = self.page.get_by_test_id("settings-nav")

        # Away and back through boosted links: copy-item.js runs again on the
        # second visit, and its delegated listener must stay single.
        nav.get_by_role("link", name="Account", exact=True).click()
        self.page.wait_for_url("**/settings/account")
        nav = self.page.get_by_test_id("settings-nav")
        nav.get_by_role("link", name="Access & Tokens", exact=True).click()
        self.page.wait_for_url("**/settings/access")
        host = self.page.locator(HOST)
        expect(host).to_have_attribute("data-react-mounted", "true")

        self.page.get_by_role("button", name="Copy API token").click()
        self.expect_copies(1)

        self.page.evaluate(DISPOSE_HOST)
        host.locator(LEGACY_CONTROL).click()
        self.expect_copies(2)
        # A duplicate listener would have written a third copy by now.
        self.page.wait_for_timeout(300)
        self.assertTrue(self.page.evaluate(COPIED, [self.user.token, 2]))
        self.assertEqual(self.errors, [])
