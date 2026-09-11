import os

from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import tag
from playwright.sync_api import expect, sync_playwright

# Headless Chromium never fires a real beforeinstallprompt, so the suite
# dispatches a stand-in carrying the same surface the About script uses:
# preventDefault(), prompt() and userChoice.
FAKE_INSTALL_EVENT = """
(outcome) => {
  const event = new Event('beforeinstallprompt');
  event.prompt = () => Promise.resolve();
  event.userChoice = Promise.resolve({ outcome, platform: 'web' });
  window.dispatchEvent(event);
}
"""

IOS_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)
ANDROID_UA = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Mobile Safari/537.36"
)

FAILING_INSTALL_EVENT = """
() => {
  const event = new Event('beforeinstallprompt');
  event.prompt = () => Promise.reject(new Error('not allowed'));
  event.userChoice = Promise.reject(new Error('not allowed'));
  window.dispatchEvent(event);
}
"""


@tag("slow", "playwright")
class AboutInstallSectionTests(StaticLiveServerTestCase):
    """Browser coverage for the About page install control."""

    @classmethod
    def setUpClass(cls):
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
        super().setUpClass()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        super().tearDownClass()

    def setUp(self):
        self.credentials = {"username": "test", "password": "12345"}
        get_user_model().objects.create_user(**self.credentials)

    def open_about(self, **context_kwargs):
        """Sign in and land on the About page, returning the page."""
        context = self.browser.new_context(**context_kwargs)
        self.addCleanup(context.close)
        page = context.new_page()
        page.goto(f"{self.live_server_url}/")
        page.get_by_placeholder("Enter your username").fill(
            self.credentials["username"],
        )
        page.get_by_placeholder("Enter your password").fill(
            self.credentials["password"],
        )
        page.get_by_role("button", name="Sign in").click()
        page.goto(f"{self.live_server_url}/settings/about")
        return page

    def install_button(self, page):
        return page.get_by_role("button", name="Install Floppy")

    def test_instructions_render_without_an_install_event(self):
        page = self.open_about()

        expect(page.get_by_role("heading", name="Install Floppy")).to_be_visible()
        expect(page.get_by_text("Floppy is an installable PWA.")).to_be_visible()
        # Desktop keeps a route to the phone steps without printing both.
        expect(page.get_by_text("Installing on a phone instead?")).to_be_visible()
        # No event means no button, and no claim that install is impossible.
        expect(self.install_button(page)).to_be_hidden()

    def test_instructions_render_without_javascript(self):
        page = self.browser.new_context(java_script_enabled=False)
        self.addCleanup(page.close)
        # Sign in over HTTP so the session exists without scripting.
        signed_in = self.open_about()
        cookies = signed_in.context.cookies()
        page.add_cookies(cookies)
        no_js_page = page.new_page()
        no_js_page.goto(f"{self.live_server_url}/settings/about")

        expect(no_js_page.get_by_role("heading", name="Install Floppy")).to_be_visible()
        expect(no_js_page.get_by_role("heading", name="iOS and iPadOS")).to_be_visible()
        expect(no_js_page.get_by_role("heading", name="Android")).to_be_visible()
        expect(self.install_button(no_js_page)).to_be_hidden()

    def test_button_appears_when_an_install_event_is_available(self):
        page = self.open_about()

        page.evaluate(FAKE_INSTALL_EVENT, "accepted")

        expect(self.install_button(page)).to_be_visible()

    def test_accepting_the_prompt_reports_success_and_consumes_the_event(self):
        page = self.open_about()
        page.evaluate(FAKE_INSTALL_EVENT, "accepted")

        self.install_button(page).click()

        expect(page.get_by_text("Installing Floppy.")).to_be_visible()
        expect(self.install_button(page)).to_be_hidden()
        self.assertIsNone(page.evaluate("() => window.floppyPwa.deferredPrompt"))

    def test_dismissing_the_prompt_keeps_the_manual_steps(self):
        page = self.open_about()
        page.evaluate(FAKE_INSTALL_EVENT, "dismissed")

        self.install_button(page).click()

        expect(page.get_by_text("Installation dismissed.")).to_be_visible()
        expect(self.install_button(page)).to_be_hidden()
        expect(page.get_by_text("Installing on a phone instead?")).to_be_visible()

    def test_a_failing_prompt_falls_back_to_the_manual_steps(self):
        page = self.open_about()
        page.evaluate(FAILING_INSTALL_EVENT)

        self.install_button(page).click()

        expect(
            page.get_by_text("Your browser could not open the install prompt."),
        ).to_be_visible()
        expect(self.install_button(page)).to_be_hidden()

    def test_standalone_launches_never_offer_the_button(self):
        page = self.open_about()
        # iOS reports standalone through navigator.standalone rather than
        # the display-mode media query.
        page.evaluate(
            "() => Object.defineProperty(navigator, 'standalone', { value: true })",
        )

        page.evaluate(FAKE_INSTALL_EVENT, "accepted")

        expect(self.install_button(page)).to_be_hidden()

    def test_appinstalled_withdraws_the_button(self):
        page = self.open_about()
        page.evaluate(FAKE_INSTALL_EVENT, "accepted")
        expect(self.install_button(page)).to_be_visible()

        page.evaluate("() => window.dispatchEvent(new Event('appinstalled'))")

        expect(self.install_button(page)).to_be_hidden()

    def panel(self, page, heading):
        return page.get_by_role("heading", name=heading).locator("xpath=ancestor::div[1]")

    def test_only_the_visitors_platform_panel_is_shown(self):
        for name, kwargs, visible, hidden in (
            ("ios", {"user_agent": IOS_UA}, "iOS and iPadOS", "Android"),
            ("android", {"user_agent": ANDROID_UA}, "Android", "iOS and iPadOS"),
        ):
            with self.subTest(platform=name):
                page = self.open_about(viewport={"width": 390, "height": 844}, **kwargs)
                expect(self.panel(page, visible)).to_be_visible()
                expect(self.panel(page, hidden)).to_be_hidden()

    def test_desktop_hides_both_phone_panels(self):
        page = self.open_about()

        expect(self.panel(page, "iOS and iPadOS")).to_be_hidden()
        expect(self.panel(page, "Android")).to_be_hidden()
        expect(page.get_by_text("Installing on a phone instead?")).to_be_visible()

    def test_about_page_does_not_scroll_sideways_on_a_phone(self):
        page = self.open_about(viewport={"width": 390, "height": 844}, user_agent=IOS_UA)

        widths = page.evaluate(
            "() => ({view: document.documentElement.clientWidth,"
            " scroll: document.documentElement.scrollWidth})",
        )

        self.assertEqual(widths["scroll"], widths["view"])
