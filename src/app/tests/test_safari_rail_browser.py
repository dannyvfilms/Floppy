"""Exercise decorative overflow without changing the application layout.

Chromium emulates Safari's reported geometry here; native rail compositing still
needs the Duo simulator. No database or external services are involved.
"""

from pathlib import Path
from unittest import TestCase

from django.conf import settings
from django.test import tag
from playwright.sync_api import expect, sync_playwright

STATIC = Path(settings.BASE_DIR) / "static"
SAFARI = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 27_1 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/27.1 Mobile/15E148 Safari/604.1"
)
FIXTURE = """<!doctype html><html><head>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>.app-menu-overlay {position:fixed;inset:0;z-index:42;background:rgb(0 0 0 / 50%)}</style>
</head><body>
<div class="app-shell" style="min-height:2400px;background:var(--color-page-bg)">
  <div class="app-menu-overlay" style="display:none"></div>
  <header class="app-topbar" style="position:sticky;top:0;height:64px;box-sizing:border-box;
    background:var(--color-sidebar);border-bottom:1px solid var(--color-border)">
    <button>Menu</button><input aria-label="Search">
  </header>
  <main style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;padding:16px">
    <article>First card</article><article>Second card</article><article>Third card</article>
  </main>
</div></body></html>"""


@tag("slow", "playwright")
class SafariRailBrowserTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        super().tearDownClass()

    def open_page(self, *, width=612, screen_width=696, ua=SAFARI, standalone=False):
        context = self.browser.new_context(
            viewport={"width": width, "height": 900},
            screen={"width": screen_width, "height": 976},
            user_agent=ua,
            has_touch=True,
            # Chromium's mobile overflow changes its page scale, unlike the
            # Safari behavior under test. Emulate the reported viewport only.
            is_mobile=False,
        )
        self.addCleanup(context.close)
        page = context.new_page()
        page.set_content(FIXTURE)
        page.evaluate("Object.defineProperty(navigator, 'maxTouchPoints', {value: 5})")
        # set_viewport_size otherwise resets Chromium's emulated screen width.
        page.evaluate(
            "width => Object.defineProperty(screen, 'width', {value: width})",
            screen_width,
        )
        page.add_style_tag(content=(STATIC / "css/main.css").read_text())
        if standalone:
            page.evaluate(
                "Object.defineProperty(navigator, 'standalone', {value: true})"
            )
        self.before = page.locator("main").bounding_box()
        page.add_script_tag(content=(STATIC / "js/safari-rail.js").read_text())
        # Flush initialization and the ResizeObserver's scheduled update.
        page.evaluate(
            "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
        )
        return page

    def test_only_decorative_document_width_changes(self):
        page = self.open_page()
        rail = page.locator("#safari-rail")
        expect(rail).to_have_count(1)
        box = rail.bounding_box()
        self.assertEqual(box["x"], 612)
        self.assertEqual(box["width"], 84)
        self.assertEqual(page.locator("main").bounding_box(), self.before)
        self.assertEqual(page.locator("article").count(), 3)
        self.assertEqual(rail.get_attribute("aria-hidden"), "true")
        self.assertEqual(
            rail.evaluate("e => getComputedStyle(e).pointerEvents"), "none"
        )
        self.assertEqual(
            page.evaluate("getComputedStyle(document.body).touchAction"),
            "pan-y pinch-zoom",
        )
        page.evaluate("window.scrollTo(0, 500)")
        expect(rail.locator("div")).to_have_css(
            "transform", "matrix(1, 0, 0, 1, 0, 500)"
        )
        self.assertEqual(page.evaluate("window.scrollX"), 0)
        page.emulate_media(reduced_motion="reduce")
        expect(rail.locator("div")).to_have_css(
            "transform", "matrix(1, 0, 0, 1, 0, 500)"
        )

    def test_other_environments_are_unchanged(self):
        for options in (
            {"width": 390, "screen_width": 390},
            {"standalone": True},
            {
                "ua": "Mozilla/5.0 (Macintosh) Version/27.1 Safari/605.1.15",
                "width": 1440,
                "screen_width": 1600,
            },
            {"ua": SAFARI.replace("Version/27.1", "CriOS/150.0")},
            {"width": 612, "screen_width": 1200},
        ):
            with self.subTest(options=options):
                page = self.open_page(**options)
                expect(page.locator("#safari-rail")).to_have_count(0)
                self.assertEqual(page.locator("main").bounding_box(), self.before)
                self.assertEqual(
                    page.evaluate("getComputedStyle(document.body).touchAction"), "auto"
                )

    def test_resizing_and_navigation_rebuild_the_rail(self):
        page = self.open_page()
        page.set_viewport_size({"width": 696, "height": 900})
        expect(page.locator("#safari-rail")).to_have_count(0)
        page.set_viewport_size({"width": 612, "height": 900})
        expect(page.locator("#safari-rail")).to_have_count(1)
        page.evaluate("""() => {
          document.body.innerHTML = document.body.innerHTML;
          document.querySelector('.app-shell').style.minHeight = '1600px';
          document.dispatchEvent(new Event('htmx:afterSettle'));
        }""")
        expect(page.locator("#safari-rail")).to_have_css("height", "1600px")
        expect(page.locator("#safari-rail")).to_have_count(1)

    def test_theme_changes_and_header_height_are_copied(self):
        page = self.open_page()
        page.evaluate("document.documentElement.className = 'light'")
        expect(page.locator("#safari-rail")).to_have_css(
            "background-color", "rgb(248, 249, 250)"
        )
        expect(page.locator("#safari-rail > div")).to_have_css(
            "background-color", "rgb(241, 243, 245)"
        )
        page.evaluate("document.querySelector('.app-topbar').style.height = '80px'")
        expect(page.locator("#safari-rail > div")).to_have_css("height", "80px")

    def test_collapsed_toolbar_uses_the_visible_scrollport_height(self):
        page = self.open_page()
        # Duo Safari's clientHeight stays fixed as innerHeight grows by 18px.
        page.evaluate("""() => {
          Object.defineProperty(window, 'innerHeight', {value: 918});
          window.dispatchEvent(new Event('resize'));
        }""")
        expect(page.locator("#safari-rail")).to_have_css("--rail-scroll", "1482px")

    def test_sidebar_scrim_covers_the_page_and_rail_at_any_scroll_position(self):
        page = self.open_page()
        page.evaluate("""() => {
          const scrim = document.querySelector('.app-menu-overlay');
          scrim.style.display = 'block';
          scrim.addEventListener('click', () => scrim.style.display = 'none');
          window.scrollTo(0, 500);
        }""")
        scrim = page.locator(".app-menu-overlay")
        expect(scrim).to_have_css("position", "absolute")
        expect(scrim).to_have_css("background-color", "rgba(0, 0, 0, 0.5)")
        box = scrim.bounding_box()
        self.assertEqual(box["width"], 696)
        self.assertEqual(box["height"], 2400)
        self.assertEqual(box["y"], -500)
        scrim.click(position={"x": 400, "y": 800})
        expect(scrim).to_be_hidden()

    def test_deferred_detail_backdrop_continues_without_copying_content(self):
        page = self.open_page()
        page.evaluate("""() => {
          const detail = document.createElement('section');
          detail.className = 'detail-carousel-grid';
          detail.innerHTML = `<div class="detail-mobile-hero" aria-hidden="true">
            <div class="detail-mobile-hero__backdrop">
              <img class="detail-mobile-hero__blur" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E" alt="">
              <img class="detail-mobile-hero__sharp" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E" alt="">
            </div>
            <img class="detail-mobile-hero__logo" alt="Title logo">
          </div><button>Check in</button>`;
          document.querySelector('main').appendChild(detail);
          document.dispatchEvent(new Event('htmx:afterSettle'));
        }""")
        rail = page.locator("#safari-rail")
        expect(rail.locator("img, button")).to_have_count(0)
        expect(page.locator(".detail-mobile-hero")).to_have_count(1)
        original = page.locator(".detail-mobile-hero").bounding_box()
        backdrop = page.locator(".detail-mobile-hero__backdrop").bounding_box()
        logo = page.locator(".detail-mobile-hero__logo").bounding_box()
        self.assertEqual(backdrop["width"], original["width"] + 168)
        self.assertAlmostEqual(
            backdrop["x"] + backdrop["width"] / 2, original["x"] + original["width"] / 2
        )
        page.evaluate("document.documentElement.removeAttribute('data-safari-rail')")
        self.assertEqual(page.locator(".detail-mobile-hero").bounding_box(), original)
        self.assertEqual(page.locator(".detail-mobile-hero__logo").bounding_box(), logo)
        self.assertEqual(
            page.locator(".detail-mobile-hero__backdrop").bounding_box()["width"],
            original["width"],
        )
        page.evaluate("""() => {
          document.querySelector('.detail-carousel-grid').remove();
          document.dispatchEvent(new Event('htmx:afterSettle'));
        }""")
        expect(page.locator(".detail-mobile-hero")).to_have_count(0)
