"""Browser proof for the React card shell alongside real Django/Alpine forms."""

import json
import os
from unittest.mock import patch
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import tag
from django_celery_beat.models import CrontabSchedule, PeriodicTask
from django_celery_results.models import TaskResult
from playwright.sync_api import expect, sync_playwright

from app.providers import credentials
from app.tests.live_server import SerialStaticLiveServerTestCase
from integrations.models import ImportRun


@tag("slow", "playwright")
class SettingsCardsBrowserTests(SerialStaticLiveServerTestCase):
    """Exercise a real local Django server with provider network access blocked."""

    @classmethod
    def setUpClass(cls):
        """Use the same synchronous browser/Django boundary as the local proof."""
        super().setUpClass()
        cls.async_override = patch.dict(os.environ, {"DJANGO_ALLOW_ASYNC_UNSAFE": "true"})
        cls.async_override.start()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()
        cls.proof_metrics = {}

    @classmethod
    def tearDownClass(cls):
        """Release Chromium and restore the Django async guard."""
        cls.browser.close()
        cls.playwright.stop()
        cls.async_override.stop()
        super().tearDownClass()
        if cls.proof_metrics:
            print("Settings-card browser metrics:", json.dumps(cls.proof_metrics))

    def setUp(self):
        """Authenticate the browser through an isolated local Django session."""
        cache.clear()
        self.user = get_user_model().objects.create_user(username="card-proof", theme="system")
        self.client.force_login(self.user)
        self.errors = []
        self.block_renderer = False
        self.probe = patch("app.providers.credentials._probe", return_value=None)
        self.probe.start()
        self.addCleanup(self.probe.stop)
        self.context = self.browser.new_context(
            viewport={"width": 1440, "height": 1000}, service_workers="block",
        )
        self.addCleanup(self.context.close)
        self.context.add_cookies([{
            "name": "sessionid", "value": self.client.cookies["sessionid"].value,
            "url": self.live_server_url,
        }])
        self.context.route("**/*", self.serve)
        self.page = self.context.new_page()
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.failed_requests = []
        self.page.on("requestfailed", lambda request: self.failed_requests.append((request.url, request.failure)))

    def serve(self, route):
        """Allow real local HTTP responses and block only provider traffic/chunks."""
        url = urlsplit(route.request.url)
        if url.netloc != urlsplit(self.live_server_url).netloc or (self.block_renderer and (
            "/static/ui/mount-" in url.path or "/static/ui/Directory-" in url.path
        )):
            route.abort()
        else:
            route.continue_()

    def open_cards(self, tab="import"):
        """Wait for the single owner of the entire AniList provider region."""
        self.page.goto(f"{self.live_server_url}/settings/providers/anilist?tab={tab}")
        expect(self.page.locator('[data-react-mounted="true"]')).to_have_count(1)

    def choose_option(self, label, option):
        """Operate the shared select by its accessible user-facing labels."""
        self.page.get_by_role("combobox", name=label, exact=True).click()
        self.page.get_by_role("option", name=option, exact=True).click()

    def test_shared_dropdown_menu_keyboard_dismissal_and_connection_status(self):
        self.page.goto(f"{self.live_server_url}/settings/providers")
        expect(self.page.locator('[data-provider-directory-root][data-react-mounted="true"]')).to_have_count(1)
        dropdown = self.page.get_by_role("combobox", name="Filter by capability", exact=True)
        dropdown.click()
        options = self.page.get_by_role("listbox", name="Filter by capability", exact=True)
        expect(options).to_be_visible()
        colors = options.evaluate("""element => {
          const probe = document.createElement('div'); probe.style.color = 'var(--color-surface-strong)';
          element.after(probe); const panel = getComputedStyle(probe).color; probe.remove();
          return [getComputedStyle(element).backgroundColor, panel];
        }""")
        self.assertEqual(colors[0], colors[1])
        expect(dropdown.locator(".ui-filter-icon")).to_have_count(1)
        selected_colors = self.page.get_by_role("option", name="All Capabilities", exact=True).evaluate("""element => {
          const probe = document.createElement('div'); probe.style.color = 'var(--ui-action)';
          element.after(probe); const action = getComputedStyle(probe).color; probe.remove();
          return [getComputedStyle(element).backgroundColor, action];
        }""")
        self.assertEqual(selected_colors[0], selected_colors[1])
        self.page.keyboard.press("c")
        expect(self.page.get_by_role("option", name="Connection", exact=True)).to_be_focused()
        self.page.keyboard.press("Enter")
        expect(dropdown).to_have_text("Connection")
        expect(dropdown).to_be_focused()
        self.page.wait_for_url("**capability=connection")
        expect(self.page.locator('#provider-results[aria-busy="false"]')).to_be_visible()
        cards = self.page.locator("#provider-results a")
        self.assertGreater(cards.count(), 0)
        self.assertEqual(cards.locator(".ui-status-icon").count(), cards.count())
        expect(self.page.get_by_role("link", name="Open Goodreads", exact=True)).to_have_count(0)
        dropdown.click()
        self.page.keyboard.press("Escape")
        expect(options).to_have_count(0)
        expect(dropdown).to_be_focused()
        dropdown.click()
        self.page.get_by_role("heading", name="Providers", exact=True).click()
        expect(options).to_have_count(0)
        self.page.set_viewport_size({"width": 390, "height": 1000})
        for label in ("Filter by capability", "Filter by media type"):
            self.page.get_by_role("combobox", name=label, exact=True).click()
            bounds = self.page.get_by_role("listbox", name=label, exact=True).evaluate(
                "element => ({left:element.getBoundingClientRect().left, right:element.getBoundingClientRect().right, viewport:innerWidth})"
            )
            self.assertGreaterEqual(bounds["left"], 0)
            self.assertLessEqual(bounds["right"], bounds["viewport"])
            self.page.keyboard.press("Escape")
        self.page.set_viewport_size({"width": 1440, "height": 1000})
        self.open_cards("import")
        self.page.get_by_role("combobox", name="Import Frequency", exact=True).click()
        preference = self.page.get_by_role("listbox", name="Import Frequency", exact=True)
        colors = preference.evaluate("""element => {
          const probe = document.createElement('div'); probe.style.color = 'var(--color-panel)';
          element.after(probe); const panel = getComputedStyle(probe).color; probe.remove();
          return [getComputedStyle(element).backgroundColor, panel];
        }""")
        self.assertEqual(colors[0], colors[1])
        expect(self.page.locator(".ui-select-filter")).to_have_count(0)
        self.page.keyboard.press("Escape")
        self.assertEqual(self.errors, [])

    def test_credentials_help_restores_focus_and_forms_keep_csrf(self):
        """React owns the dialog and submits through the existing CSRF-safe backend."""
        self.open_cards("connection")
        badge = self.page.get_by_role("button", name="Read-only: explain instance credential access")
        badge.focus()
        self.page.keyboard.press("Enter")
        dialog = self.page.get_by_role("dialog", name="Instance credential access")
        expect(dialog).to_be_visible()
        self.page.keyboard.press("Escape")
        expect(dialog).not_to_be_visible()
        expect(badge).to_be_focused()
        self.page.get_by_label("Your Client ID", exact=True).fill("test-public-client")
        self.page.get_by_label("Your Client secret", exact=True).fill("test-personal-secret")
        with self.page.expect_response(lambda response: "/personal" in response.url and response.request.method == "POST") as result:
            self.page.get_by_role("button", name="Save personal key", exact=True).click()
        self.assertEqual(result.value.status, 302)
        self.page.wait_for_load_state("networkidle")
        self.assertIn("tab=connection", self.page.url, (result.value.headers, self.failed_requests))
        expect(self.page.locator('[data-react-mounted="true"]')).to_have_count(1)
        self.assertNotIn("test-personal-secret", "".join(self.page.locator('script[type="application/json"]').all_text_contents()))
        self.assertEqual(self.errors, [])

    def test_import_settings_submit_and_private_gate_still_work(self):
        """React preference writes and private/public toggles preserve entered state."""
        self.open_cards()
        self.page.locator('[name="user"]').fill("public-person")
        with self.page.expect_response(lambda response: "/settings/import/save-settings" in response.url) as result:
            self.choose_option("Import Mode", "Sync New Items and Overwrite Existing")
        self.assertEqual(result.value.status, 204)
        self.user.refresh_from_db()
        self.assertEqual(self.user.import_mode, "overwrite")
        toggle = self.page.get_by_role("button", name="Public / Private", exact=True)
        expect(toggle).to_have_text("Public")
        expect(toggle).to_have_attribute("aria-pressed", "false")
        toggle.click()
        expect(toggle).to_have_text("Private")
        expect(toggle).to_have_attribute("aria-pressed", "true")
        expect(self.page.get_by_text("Private imports require provider credentials.")).to_be_visible()
        toggle.focus()
        toggle.press("Space")
        expect(toggle).to_have_text("Public")
        expect(toggle).to_have_attribute("aria-pressed", "false")
        expect(self.page.locator('[name="user"]')).to_have_value("public-person")
        self.assertEqual(self.errors, [])

    def test_import_controls_use_surface_borders_inset_arrows_and_purple_action(self):
        """Ordinary fields must not resemble invalid controls in either theme."""
        for scheme in ("light", "dark"):
            self.page.emulate_media(color_scheme=scheme)
            self.open_cards()
            for label in ("Import Frequency", "Import Mode", "Public username"):
                field = self.page.get_by_label(label, exact=True)
                style = field.evaluate("""element => {
                  const style = getComputedStyle(element), probe = document.createElement('div');
                  probe.style.color = 'var(--color-surface-border)'; element.after(probe);
                  const expected = getComputedStyle(probe).color; probe.remove();
                  return {border:style.borderTopColor, expected, outlineStyle:style.outlineStyle};
                }""")
                self.assertEqual(style["border"], style["expected"])
                self.assertEqual(style["outlineStyle"], "none", (label, style))
            for arrow in self.page.locator(".ui-select-chevron").all():
                geometry = arrow.evaluate("""arrow => {
                  const select = arrow.previousElementSibling, box = select.getBoundingClientRect();
                  const icon = arrow.getBoundingClientRect();
                  return {inset:box.right-icon.right, padding:parseFloat(getComputedStyle(select).paddingRight),
                    iconWidth:icon.width};
                }""")
                self.assertGreaterEqual(geometry["inset"], 10)
                self.assertGreater(geometry["padding"], geometry["iconWidth"] + geometry["inset"])
            color = self.page.get_by_role("button", name="Import", exact=True).evaluate("""element => {
              const probe = document.createElement('div');
              probe.style.color = 'var(--color-indigo-600)'; element.after(probe);
              const expected = getComputedStyle(probe).color; probe.remove();
              return {actual:getComputedStyle(element).backgroundColor, expected};
            }""")
            self.assertEqual(color["actual"], color["expected"])
        self.assertEqual(self.errors, [])

    def test_connection_and_import_heading_spacing_matches(self):
        """Tab divider spacing stays consistent for plain and action-row headings."""
        for width in (390, 1440):
            self.page.set_viewport_size({"width": width, "height": 1000})
            gaps = []
            for tab, title in (("connection", "Provider credentials"), ("import", "Import settings")):
                self.open_cards(tab)
                heading = self.page.get_by_role("heading", name=title, exact=True)
                gap = heading.evaluate("""heading => heading.getBoundingClientRect().top -
                  document.querySelector('.ui-tabs').getBoundingClientRect().bottom""")
                self.assertGreaterEqual(gap, 23)
                self.assertLessEqual(gap, 26)
                gaps.append(gap)
            self.assertLessEqual(abs(gaps[0] - gaps[1]), 2)
        self.assertEqual(self.errors, [])

    def test_directory_uses_available_width_and_preserves_live_filters_and_back(self):
        """Catalog columns follow actual content width; filters retain server semantics."""
        for width, columns in ((1920, 3), (1440, 3), (1280, 3), (1135, 2), (390, 1)):
            self.page.set_viewport_size({"width": width, "height": 1000})
            self.page.goto(f"{self.live_server_url}/settings/providers")
            expect(self.page.locator('[data-provider-directory-root][data-react-mounted="true"]')).to_have_count(1)
            grid = self.page.locator("#provider-results")
            self.assertEqual(grid.evaluate("element => getComputedStyle(element).gridTemplateColumns.split(' ').length"), columns)
            self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth > innerWidth + 1"))
            self.assertTrue(grid.locator("a").evaluate_all("cards => cards.every(card => card.getBoundingClientRect().width >= 185)"))
        # The shared grid can still use four columns when its container has room;
        # the current Settings shell caps the actual directory below that width.
        grid.evaluate("element => element.parentElement.style.width = '1040px'")
        self.assertEqual(grid.evaluate("element => getComputedStyle(element).gridTemplateColumns.split(' ').length"), 4)
        grid.evaluate("element => element.parentElement.style.width = ''")
        search = self.page.get_by_label("Search providers", exact=True)
        search.fill("steam")
        self.page.wait_for_url("**/settings/providers?q=steam")
        expect(self.page.get_by_role("link", name="Open SteamGridDB", exact=True)).to_be_visible()
        self.choose_option("Filter by capability", "Metadata")
        self.choose_option("Filter by media type", "Games")
        self.page.wait_for_url("**capability=metadata&media=game")
        expect(self.page.locator("#provider-results a")).to_have_count(2)
        expect(self.page.get_by_role("link", name="Open Steam", exact=True)).to_have_attribute("href", "/settings/providers/steam?tab=metadata")
        search.fill("no-such-provider")
        expect(self.page.get_by_text("No providers match these filters.", exact=True)).to_be_visible()
        self.page.go_back()
        expect(search).to_have_value("steam")
        expect(self.page.locator("#provider-results a")).to_have_count(2)
        self.assertEqual(self.errors, [])

    def test_directory_bundle_failure_preserves_native_filter_fallback(self):
        self.block_renderer = True
        self.page.goto(f"{self.live_server_url}/settings/providers")
        expect(self.page.get_by_role("heading", name="Providers", exact=True)).to_be_visible()
        self.page.get_by_label("Search providers", exact=True).fill("steam")
        self.page.get_by_label("Filter by capability", exact=True).select_option("metadata")
        self.page.get_by_label("Filter by media type", exact=True).select_option("game")
        self.page.get_by_role("button", name="Search providers", exact=True).click()
        self.page.wait_for_load_state("networkidle")
        expect(self.page.locator("#provider-results a")).to_have_count(2)
        expect(self.page.locator('[data-react-mounted="true"]')).to_have_count(0)
        self.assertEqual(self.errors, [])

    def test_chip_focus_ring_is_for_keyboard_navigation_only(self):
        """Shared toggle, dialog and link chips distinguish pointer/keyboard focus."""
        self.open_cards()
        toggle = self.page.get_by_role("button", name="Public / Private", exact=True)
        toggle.click()
        expect(toggle).to_be_focused()
        self.assertEqual(toggle.evaluate("element => getComputedStyle(element).outlineStyle"), "none")
        self.page.keyboard.press("Shift+Tab")
        self.page.keyboard.press("Tab")
        expect(toggle).to_be_focused()
        self.assertEqual(toggle.evaluate("element => getComputedStyle(element).outlineStyle"), "solid")
        self.page.keyboard.press("Space")
        expect(toggle).to_have_attribute("aria-pressed", "false")
        self.open_cards("connection")
        badge = self.page.get_by_role("button", name="Read-only: explain instance credential access")
        badge.click()
        self.page.keyboard.press("Escape")
        expect(badge).to_be_focused()
        self.page.mouse.click(0, 0)
        badge.click()
        self.page.get_by_role("dialog").get_by_role("button", name="Close", exact=True).click()
        expect(badge).to_be_focused()
        self.assertEqual(badge.evaluate("element => getComputedStyle(element).outlineStyle"), "none")
        self.page.keyboard.press("Shift+Tab")
        link = self.page.get_by_role("link", name="Get a key from AniList", exact=True)
        expect(link).to_be_focused()
        self.assertEqual(link.evaluate("element => getComputedStyle(element).outlineStyle"), "solid")
        self.assertEqual(self.errors, [])

    def test_repeated_htmx_cleanup_swaps_and_bfcache_restore(self):
        """Partial/OOB replacements dispose roots and reinitialize exactly once."""
        self.open_cards()
        for _ in range(12):
            self.page.evaluate("""() => {
              const host = document.querySelector('[data-provider-root]');
              const original = host.querySelector('input[name=user]');
              htmx.trigger(host, 'htmx:load', {elt: host});
              if (host.querySelector('input[name=user]') !== original) throw Error('Duplicate load replaced the form');
              htmx.trigger(host, 'htmx:beforeCleanupElement', {elt: host});
              if (host.dataset.reactMounted) throw Error('Root was not disposed');
              const copy = host.cloneNode(true);
              host.replaceWith(copy);
              htmx.trigger(copy, 'htmx:load', {elt: copy});
            }""")
            expect(self.page.locator('[data-react-mounted="true"]')).to_have_count(1)
        self.page.get_by_label("Public username", exact=True).fill("retained-on-back")
        self.page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted:true}))")
        expect(self.page.locator('[data-react-mounted="true"]')).to_have_count(1)
        self.page.evaluate("window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted:true}))")
        expect(self.page.locator('[data-react-mounted="true"]')).to_have_count(1)
        expect(self.page.get_by_label("Public username", exact=True)).to_have_value("retained-on-back")
        self.page.evaluate("htmx.ajax('GET', '/settings/providers/anilist?tab=connection', {target:'body', swap:'innerHTML'})")
        expect(self.page.get_by_role("heading", name="Instance credentials")).to_be_visible()
        expect(self.page.locator('[data-react-mounted="true"]')).to_have_count(1)
        self.assertEqual(self.errors, [])

    def test_theme_and_responsive_parity(self):
        """Cover the six theme states and phone/tablet/desktop without overflow."""
        for theme, scheme in (("system", "light"), ("system", "dark"), ("light", "dark"),
                              ("dark", "light"), ("nord", "light"), ("custom", "light")):
            self.user.theme = theme
            self.user.save(update_fields=["theme"])
            self.page.emulate_media(color_scheme=scheme, reduced_motion="reduce")
            for width in (390, 768, 1440):
                with self.subTest(theme=theme, scheme=scheme, width=width):
                    self.page.set_viewport_size({"width": width, "height": 1000})
                    for tab in ("overview", "connection", "import", "activity"):
                        self.open_cards(tab)
                        expect(self.page.locator(".settings-card")).to_have_count(3 if tab == "overview" else 2)
                        self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth > innerWidth + 1"))
        self.assertEqual(self.errors, [])

    def test_blocked_bundle_preserves_fallback_and_import_controls(self):
        """A failed lazy chunk must leave useful SSR content and working forms."""
        self.block_renderer = True
        self.page.goto(f"{self.live_server_url}/settings/providers/anilist?tab=import")
        expect(self.page.get_by_role("heading", name="Import preferences")).to_be_visible()
        expect(self.page.get_by_label("Public username", exact=True)).to_be_visible()
        expect(self.page.locator('[data-react-mounted="true"]')).to_have_count(0)
        self.assertEqual(self.errors, [])

    def test_navigation_from_a_page_without_cards_lazily_loads_the_runtime(self):
        """The global loader must discover islands introduced by boosted navigation."""
        self.page.goto(f"{self.live_server_url}/settings/account")
        self.page.wait_for_load_state("networkidle")
        self.assertFalse(self.page.evaluate("""performance.getEntriesByType('resource')
          .some(entry => /\\/ui\\/mount-/.test(entry.name))"""))
        self.page.evaluate("htmx.ajax('GET', '/settings/providers/anilist?tab=import', {target:'body', swap:'innerHTML'})")
        expect(self.page.locator('[data-react-mounted="true"]')).to_have_count(1)
        self.assertEqual(self.errors, [])

    def test_runtime_cost_layout_shift_and_cleanup_memory(self):
        """Bound the first pilot's desktop execution/layout and retained memory."""
        self.page.add_init_script("""(() => {
          window.cardProof = {cls: 0, mountedAt: 0};
          new PerformanceObserver(list => {
            for (const entry of list.getEntries()) {
              if (!entry.hadRecentInput) cardProof.cls += entry.value;
            }
          }).observe({type: 'layout-shift', buffered: true});
          new MutationObserver(() => {
            if (document.querySelectorAll('[data-react-mounted=true]').length === 1) {
              cardProof.mountedAt ||= performance.now();
            }
          }).observe(document, {subtree:true, attributes:true, attributeFilter:['data-react-mounted']});
        })()""")
        self.open_cards()
        self.page.wait_for_load_state("networkidle")
        metrics = self.page.evaluate("""() => ({
          cls: cardProof.cls,
          mountAfterFetchMs: cardProof.mountedAt - performance.getEntriesByType('resource')
            .find(entry => /\\/ui\\/mount-/.test(entry.name)).responseEnd,
          version: navigator.userAgent,
        })""")
        session = self.context.new_cdp_session(self.page)
        session.send("HeapProfiler.collectGarbage")
        before = session.send("Runtime.getHeapUsage")["usedSize"]
        for _ in range(40):
            self.page.evaluate("""() => {
              window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted:false}));
              window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted:false}));
            }""")
            expect(self.page.locator('[data-react-mounted="true"]')).to_have_count(1)
        session.send("HeapProfiler.collectGarbage")
        metrics["heapGrowthBytes"] = session.send("Runtime.getHeapUsage")["usedSize"] - before
        self.__class__.proof_metrics = metrics
        self.assertLess(metrics["cls"], 0.02)
        self.assertLess(metrics["mountAfterFetchMs"], 1000)  # CI smoke guard; desktop acceptance is measured separately.
        self.assertLess(metrics["heapGrowthBytes"], 5 * 1024 * 1024)
        self.assertEqual(self.errors, [])

    def test_overview_shows_three_cards_using_real_state(self):
        """Credential saves, enabled schedules and the latest run feed Overview."""
        self.open_cards("overview")
        expect(self.page.locator(".provider-overview > .settings-card")).to_have_count(3)
        expect(self.page.get_by_text("No credentials active", exact=True)).to_be_visible()
        expect(self.page.get_by_text("No automatic imports configured", exact=True)).to_be_visible()
        credentials.set_user("anilist", self.user, {"client_id": "browser-client", "client_secret": "browser-secret"})
        cron = CrontabSchedule.objects.create(minute="0", hour="3")
        PeriodicTask.objects.create(name="browser-auto", task="Import from AniList", crontab=cron,
                                   kwargs=json.dumps({"user_id": self.user.pk, "mode": "new"}))
        ImportRun.objects.create(user=self.user, source="anilist", status="completed")
        self.open_cards("overview")
        expect(self.page.get_by_text("Personal credentials active", exact=True)).to_be_visible()
        expect(self.page.get_by_text("1 enabled schedule", exact=True)).to_be_visible()
        expect(self.page.get_by_text("Completed", exact=True)).to_be_visible()
        self.assertEqual(self.errors, [])

    def test_activity_details_pause_updates_and_schedule_remove_returns_here(self):
        """Keep diagnostics open while the server changes and preserve action routing."""
        TaskResult.objects.create(task_id="browser-failed", task_name="Import from AniList", status="FAILURE",
                                  task_kwargs=json.dumps({"user_id": self.user.pk}), result="{}", traceback="AniList test traceback")
        ImportRun.objects.create(user=self.user, source="anilist", status="running")
        self.open_cards("activity")
        self.page.get_by_text("Show traceback", exact=True).click()
        expect(self.page.get_by_text("AniList test traceback", exact=True)).to_be_visible()
        # An open details element prevents another request even when a retry signal
        # or active interval would otherwise refresh the list.
        requests = []
        self.page.on("request", lambda request: requests.append(request.url) if "format=json" in request.url else None)
        self.page.wait_for_timeout(5100)
        self.assertEqual(requests, [])
        cron = CrontabSchedule.objects.create(minute="0", hour="3")
        PeriodicTask.objects.create(name="browser-remove", task="Import from AniList", crontab=cron,
                                   kwargs=json.dumps({"user_id": self.user.pk, "mode": "new"}))
        self.page.get_by_text("Show traceback", exact=True).click()
        self.page.get_by_role("button", name="Remove schedule", exact=True).wait_for(state="visible")
        self.page.get_by_role("button", name="Remove schedule", exact=True).click()
        self.page.wait_for_url("**/settings/providers/anilist?tab=activity")
        expect(self.page.get_by_text("No periodic imports configured", exact=True)).to_be_visible()
        self.assertFalse(PeriodicTask.objects.filter(name="browser-remove").exists())
        self.assertEqual(self.errors, [])

    def test_retained_provider_still_uses_shared_header_islands(self):
        """The full-page port does not orphan partial migrations on other providers."""
        self.page.goto(f"{self.live_server_url}/settings/providers/hardcover?tab=connection")
        expect(self.page.locator("[data-settings-card-root][data-react-mounted=true]")).to_have_count(2)
        expect(self.page.locator("[data-provider-root][data-react-mounted=true]")).to_have_count(1)
        expect(self.page.get_by_role("navigation", name="Provider sections")).to_be_visible()
        self.assertEqual(self.errors, [])

    def test_all_provider_overviews_share_the_react_page_and_card_components(self):
        """Different capabilities change data, never the provider page renderer."""
        for slug, titles in (("bgg", ["Connection", "Metadata"]),
                             ("anilist", ["Connection", "Automatic import", "Last active import"]),
                             ("goodreads", ["Automatic import", "Last active import"])):
            self.page.goto(f"{self.live_server_url}/settings/providers/{slug}?tab=overview")
            expect(self.page.locator("[data-provider-root][data-react-mounted=true]")).to_have_count(1)
            cards = self.page.locator(".provider-overview > .settings-card")
            self.assertEqual(cards.locator('[role="heading"]').all_text_contents(), titles)
            self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth > innerWidth + 1"))
            self.assertEqual(self.page.locator(".provider-page").count(), 1)
        self.page.goto(f"{self.live_server_url}/settings/providers/bgg?tab=overview")
        expect(self.page.locator("[data-provider-root][data-react-mounted=true]")).to_have_count(1)
        self.page.locator(".provider-overview").get_by_role("link", name="Connection", exact=True).click()
        expect(self.page.get_by_role("heading", name="Instance credentials", exact=True)).to_be_visible()
        expect(self.page.locator("[data-provider-root][data-react-mounted=true]")).to_have_count(1)
        expect(self.page.locator("[data-settings-card-root][data-react-mounted=true]")).to_have_count(2)
        self.assertEqual(self.errors, [])

    def test_overview_and_directory_share_column_breakpoints(self):
        for width in (390, 1135, 1280, 1440):
            self.page.set_viewport_size({"width": width, "height": 1000})
            columns = []
            for path, selector in (("/settings/providers", "#provider-results"),
                                   ("/settings/providers/anilist?tab=overview", ".provider-overview")):
                self.page.goto(self.live_server_url + path)
                expect(self.page.locator('[data-react-mounted="true"]')).to_have_count(1)
                columns.append(self.page.locator(selector).evaluate("element => getComputedStyle(element).gridTemplateColumns.split(' ').length"))
            self.assertEqual(columns[0], columns[1])
        self.assertEqual(self.errors, [])

    def test_metadata_is_inline_and_saves_shared_primary_source(self):
        credentials.set_user("hardcover", self.user, {"api_key": "browser-metadata-key"})
        self.page.goto(f"{self.live_server_url}/settings/providers/hardcover?tab=metadata")
        expect(self.page.locator('[data-provider-root][data-react-mounted="true"]')).to_have_count(1)
        expect(self.page.get_by_role("heading", name="Metadata sources", exact=True)).to_be_visible()
        expect(self.page.get_by_role("heading", name="Provider settings", exact=True)).to_be_visible()
        expect(self.page.get_by_role("dialog")).to_have_count(0)
        self.choose_option("Provider for new titles", "Hardcover")
        self.page.get_by_role("button", name="Save", exact=True).click()
        self.page.wait_for_url("**/settings/providers/hardcover?tab=metadata")
        self.user.refresh_from_db()
        self.assertEqual(self.user.book_metadata_source_default, "hardcover")
        self.page.goto(f"{self.live_server_url}/settings/providers/openlibrary?tab=metadata")
        expect(self.page.locator('[data-provider-root][data-react-mounted="true"]')).to_have_count(1)
        expect(self.page.get_by_role("combobox", name="Provider for new titles", exact=True)).to_have_text("Hardcover")
        for width in (390, 768, 1440):
            self.page.set_viewport_size({"width": width, "height": 1000})
            self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth > innerWidth + 1"))
        self.assertEqual(self.errors, [])

    def test_metadata_feature_list_prioritizes_activity_and_provider_outputs(self):
        for slug in ("bgg", "igdb", "steamgriddb", "libretro"):
            self.page.goto(f"{self.live_server_url}/settings/providers/{slug}?tab=metadata")
            expect(self.page.locator('[data-provider-root][data-react-mounted="true"]')).to_have_count(1)
            expect(self.page.locator(".ui-feature-list > li").first).to_be_visible()
            feature_list = self.page.locator(".ui-feature-list")
            expect(feature_list.get_by_text("Active", exact=True)).to_have_count(0)
            self.assertTrue(feature_list.evaluate("element => element.nextElementSibling === null"))
            self.assertTrue(feature_list.locator("li").evaluate_all("""rows => rows.every(row => {
              const icon = row.querySelector('.ui-status-icon'), text = row.querySelector('div');
              return icon.getBoundingClientRect().right <= text.getBoundingClientRect().left &&
                getComputedStyle(row).borderTopWidth === '0px';
            })"""))
            expect(self.page.get_by_role("heading", name="No additional provider settings", exact=True)).to_have_count(0)
            expect(self.page.get_by_role("link", name="Configure Connection", exact=True)).to_have_count(0)
            expect(self.page.get_by_text("This provider has no additional settings.", exact=True)).to_be_visible()
            expect(self.page.get_by_text("Read-only", exact=True)).to_have_count(0)
            for width in (390, 768, 1440):
                self.page.set_viewport_size({"width": width, "height": 1000})
                self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth > innerWidth + 1"))
        expect(self.page.get_by_role("img", name="Title logos: Active", exact=True)).to_be_visible()
        expect(self.page.get_by_role("img", name="Search results and title details: Not provided", exact=True)).to_be_visible()
        self.assertEqual(self.errors, [])

    @patch("integrations.views.tasks.import_anilist.delay")
    def test_public_import_submits_current_react_preferences(self, import_task):
        """The React form retains the established task arguments and return route."""
        self.open_cards()
        self.page.get_by_label("Public username", exact=True).fill("react-public-profile")
        with self.page.expect_response(lambda response: "/save-settings" in response.url):
            self.choose_option("Import Mode", "Sync New Items and Overwrite Existing")
        self.page.get_by_role("button", name="Import", exact=True).click()
        self.page.wait_for_url("**/settings/providers/anilist?tab=import")
        expect(self.page.locator("[data-provider-root][data-react-mounted=true]")).to_have_count(1)
        import_task.assert_called_once_with(user_id=self.user.pk, mode="overwrite", username="react-public-profile")
        self.assertEqual(self.errors, [])

    def test_preference_failure_is_visible_and_retry_saves_the_current_value(self):
        """A network failure cannot silently imply that a preference was saved."""
        self.open_cards()
        pattern = "**/settings/import/save-settings"
        self.page.route(pattern, lambda route: route.abort())
        self.choose_option("Import Mode", "Sync New Items and Overwrite Existing")
        expect(self.page.get_by_text("Could not save preferences. Try again.", exact=True)).to_be_visible()
        self.page.unroute(pattern)
        self.page.get_by_role("button", name="Retry", exact=True).click()
        expect(self.page.locator(".provider-page").get_by_role("status")).to_have_text("Saved")
        self.user.refresh_from_db()
        self.assertEqual(self.user.import_mode, "overwrite")
        self.assertEqual(self.errors, [])

    def test_overview_chips_stay_inside_clickable_cards_at_narrow_breakpoints(self):
        """Contain badges inside narrow grid cards and make the whole card a link."""
        for width in (390, 768, 1024, 1100, 1200, 1280, 1440):
            with self.subTest(width=width):
                self.page.set_viewport_size({"width": width, "height": 1000})
                self.open_cards("overview")
                spills = self.page.locator(".provider-overview > .settings-card").evaluate_all("""cards => cards.flatMap(card => {
                  const bounds = card.getBoundingClientRect();
                  return [...card.querySelectorAll('[data-testid=settings-card-badge]')].filter(badge => {
                    const box = badge.getBoundingClientRect();
                    return box.left < bounds.left || box.right > bounds.right + 1;
                  }).map(badge => badge.textContent);
                })""")
                self.assertEqual(spills, [])
                expect(self.page.locator(".provider-overview").get_by_role("link")).to_have_count(3)
                expect(self.page.get_by_text("Manage connection", exact=True)).to_have_count(0)
                expect(self.page.get_by_text("Configure imports", exact=True)).to_have_count(0)
                expect(self.page.get_by_text("View activity", exact=True)).to_have_count(0)
        self.page.locator(".provider-overview").get_by_role("link", name="Connection", exact=True).click()
        self.page.wait_for_url("**/settings/providers/anilist?tab=connection")
        self.open_cards("overview")
        self.page.locator(".provider-overview").get_by_role("link", name="Automatic import", exact=True).focus()
        self.page.keyboard.press("Enter")
        self.page.wait_for_url("**/settings/providers/anilist?tab=import")
        self.open_cards("overview")
        self.page.locator(".provider-overview").get_by_role("link", name="Last active import", exact=True).click()
        self.page.wait_for_url("**/settings/providers/anilist?tab=activity")
        self.assertEqual(self.errors, [])

    def test_connection_summary_is_compact_and_hover_has_no_white_outline_flash(self):
        """Keep explanatory copy in a tooltip and sample the first painted hover frames."""
        self.page.emulate_media(color_scheme="dark")
        self.open_cards("overview")
        card = self.page.locator(".provider-overview").get_by_role("link", name="Connection", exact=True)
        expect(card.locator("p")).to_have_count(1)
        expect(card).to_have_attribute("title", "Public username imports do not require provider credentials.")
        self.page.mouse.move(0, 0)
        card.evaluate("""card => {
          window.providerHoverFrames = [];
          window.providerHoverRecording = true;
          let count = 0;
          function sample() {
            const style = getComputedStyle(card);
            if (card.matches(':hover')) providerHoverFrames.push({color:style.outlineColor, width:style.outlineWidth});
            if (providerHoverRecording && ++count < 120) requestAnimationFrame(sample);
          }
          requestAnimationFrame(sample);
        }""")
        card.hover()
        self.page.wait_for_timeout(400)
        frames = self.page.evaluate("providerHoverRecording=false; providerHoverFrames")
        self.assertTrue(frames)
        self.assertTrue(all(frame == frames[-1] for frame in frames), frames)
        self.assertEqual(frames[-1]["width"], "1px")
        self.open_cards("connection")
        for control in (
            self.page.get_by_role("button", name="Save personal key", exact=True),
            self.page.get_by_role("button", name="Read-only: explain instance credential access"),
            self.page.get_by_role("link", name="Get a key from AniList", exact=True),
        ):
            control.hover()
            properties = control.evaluate("element => getComputedStyle(element).transitionProperty.split(',').map(value => value.trim())")
            self.assertNotIn("all", properties)
            self.assertFalse(any(value.startswith("outline") for value in properties))
        self.assertEqual(self.errors, [])

    def test_overview_subtitles_and_interactive_chips_are_consistent(self):
        """Match status typography and shared link/button chip interactions."""
        self.open_cards("overview")
        subtitles = self.page.locator(".provider-overview > .settings-card").evaluate_all("""cards => cards.map(card => {
          const p = card.querySelector('p'), style = getComputedStyle(p);
          return {text:p.textContent.trim(), color:style.color, weight:style.fontWeight, size:style.fontSize};
        })""")
        self.assertTrue(all(not row["text"].endswith(".") for row in subtitles))
        self.assertTrue(all((row["color"], row["weight"], row["size"]) ==
                            (subtitles[0]["color"], subtitles[0]["weight"], subtitles[0]["size"]) for row in subtitles))
        self.open_cards("connection")
        read_only = self.page.get_by_role("button", name="Read-only: explain instance credential access")
        key_link = self.page.get_by_role("link", name="Get a key from AniList", exact=True)
        dimensions = []
        for chip in (read_only, key_link):
            self.page.mouse.move(0, 0)
            self.page.wait_for_timeout(300)
            before = chip.evaluate("element => getComputedStyle(element).backgroundColor")
            chip.hover()
            self.page.wait_for_timeout(300)
            style = chip.evaluate("""element => {
              const s=getComputedStyle(element), text=getComputedStyle(element.firstElementChild);
              return {background:s.backgroundColor, underline:s.textDecorationLine, radius:s.borderRadius,
                padding:s.padding, border:s.borderWidth, font:text.fontSize};
            }""")
            self.assertNotEqual(style["background"], before)
            self.assertEqual(style["underline"], "none")
            dimensions.append((style["radius"], style["padding"], style["border"], style["font"]))
        self.assertEqual(dimensions[0], dimensions[1])
        expect(key_link).to_have_attribute("href", "https://anilist.co/settings/developer")
        expect(key_link).to_have_attribute("target", "_blank")
        with self.page.expect_popup() as popup:
            key_link.click()
        popup.value.close()
        for name in ("Overview", "Connection", "Import", "Activity"):
            tab = self.page.get_by_role("navigation", name="Provider sections").get_by_role("link", name=name, exact=True)
            tab.hover()
            self.assertEqual(tab.evaluate("element => getComputedStyle(element).textDecorationLine"), "none")
        active = self.page.locator('.ui-tabs a[aria-current="page"]')
        self.assertEqual(active.evaluate("element => getComputedStyle(element).borderBottomWidth"), "2px")
        self.assertEqual(self.errors, [])
