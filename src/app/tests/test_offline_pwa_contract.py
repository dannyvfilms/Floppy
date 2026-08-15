import json
from pathlib import Path
from urllib.parse import urljoin, urlparse

from django.conf import settings
from django.test import SimpleTestCase


class OfflinePWAContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source_root = Path(settings.BASE_DIR)
        cls.worker = (
            cls.source_root / "static" / "js" / "serviceworker.js"
        ).read_text(encoding="utf-8")
        cls.manifest = json.loads(
            (cls.source_root / "static" / "favicon" / "site.webmanifest").read_text(
                encoding="utf-8",
            ),
        )
        cls.offline_page = (
            cls.source_root / "static" / "offline.html"
        ).read_text(encoding="utf-8")
        cls.base_template = (
            cls.source_root / "templates" / "base.html"
        ).read_text(encoding="utf-8")

    def test_worker_uses_registration_scope_instead_of_root_paths(self):
        self.assertIn("self.registration.scope", self.worker)
        self.assertIn('new URL("static/", APP_SCOPE)', self.worker)
        self.assertIn('new URL("static/offline.html", APP_SCOPE)', self.worker)
        self.assertNotIn('startsWith("/static/")', self.worker)
        self.assertNotIn('"/static/', self.worker)

    def test_worker_never_caches_navigation_or_htmx_responses(self):
        navigation_start = self.worker.index(
            "async function offlineNavigationResponse",
        )
        static_start = self.worker.index("async function publicStaticResponse")
        navigation_source = self.worker[navigation_start:static_start]

        self.assertNotIn("cache.put", navigation_source)
        self.assertIn('request.mode === "navigate"', self.worker)
        self.assertIn('request.headers.get("HX-Request")', self.worker)
        self.assertIn("isPublicStaticRequest", self.worker)
        self.assertIn('response.type === "basic"', self.worker)

    def test_worker_install_does_not_fail_for_one_optional_public_file(self):
        self.assertIn("Promise.allSettled", self.worker)
        self.assertNotIn("cache.addAll", self.worker)

    def test_worker_deletes_only_its_current_scope_and_known_legacy_cache(self):
        self.assertIn("cacheName.startsWith(CACHE_PREFIX)", self.worker)
        self.assertIn("LEGACY_CACHE_NAMES.has(cacheName)", self.worker)
        self.assertNotIn('cacheName.startsWith("floppy-")', self.worker)

    def test_manifest_urls_resolve_inside_root_and_subpath_installations(self):
        for app_path in ("/", "/floppy/"):
            manifest_url = (
                f"https://floppy.example{app_path}static/favicon/site.webmanifest"
            )
            expected_root = f"https://floppy.example{app_path}"

            self.assertEqual(
                urljoin(manifest_url, self.manifest["start_url"]),
                expected_root,
            )
            self.assertEqual(
                urljoin(manifest_url, self.manifest["scope"]),
                expected_root,
            )
            self.assertEqual(
                urljoin(manifest_url, self.manifest["id"]),
                expected_root,
            )

            for icon in self.manifest["icons"]:
                resolved_icon = urlparse(urljoin(manifest_url, icon["src"]))
                self.assertTrue(resolved_icon.path.startswith(f"{app_path}static/"))

            for shortcut in self.manifest["shortcuts"]:
                resolved_url = urlparse(urljoin(manifest_url, shortcut["url"]))
                self.assertTrue(resolved_url.path.startswith(app_path))
                for icon in shortcut.get("icons", []):
                    resolved_icon = urlparse(urljoin(manifest_url, icon["src"]))
                    self.assertTrue(
                        resolved_icon.path.startswith(f"{app_path}static/"),
                    )

    def test_template_registers_worker_at_django_generated_scope(self):
        self.assertIn(
            '.register("{% url \'service_worker\' %}", '
            '{ scope: "{% url \'home\' %}" })',
            self.base_template,
        )
        self.assertNotIn('.register("/serviceworker.js")', self.base_template)

    def test_offline_page_is_self_contained_and_accessible(self):
        self.assertIn('<meta name="viewport"', self.offline_page)
        self.assertIn('<h1 id="offline-title">', self.offline_page)
        self.assertIn('role="status"', self.offline_page)
        self.assertIn('aria-labelledby="offline-title"', self.offline_page)
        self.assertIn(":focus-visible", self.offline_page)
        self.assertIn("prefers-color-scheme: dark", self.offline_page)
        self.assertIn("prefers-reduced-motion: reduce", self.offline_page)
        self.assertIn('<form method="get">', self.offline_page)
        self.assertIn('<button type="submit">Try again</button>', self.offline_page)
        self.assertIn("does not contain private account data", self.offline_page)
        self.assertNotIn("onclick=", self.offline_page)
        self.assertNotIn("<script", self.offline_page)
        self.assertNotIn("https://", self.offline_page)
        self.assertNotIn("http://", self.offline_page)
        self.assertNotIn("localStorage", self.offline_page)
        self.assertNotIn("indexedDB", self.offline_page)
