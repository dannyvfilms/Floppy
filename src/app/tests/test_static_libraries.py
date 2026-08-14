import re
from pathlib import Path

from django.conf import settings
from django.template import Context, Template
from django.test import SimpleTestCase


class StaticLibraryContractTests(SimpleTestCase):
    """Protect vendored static libraries against unpinned CDN regressions."""

    def setUp(self):
        """Resolve base directories and template paths for contract assertions."""
        base_dir = Path(settings.BASE_DIR)
        self.static_libraries_dir = base_dir / "static" / "js" / "libraries"
        self.base_template_path = base_dir / "templates" / "base.html"
        self.base_public_template_path = base_dir / "templates" / "base_public.html"
        self.zxing_asset_path = (
            self.static_libraries_dir / "zxing-library-0.21.3.min.js"
        )
        self.zxing_license_path = (
            self.static_libraries_dir / "zxing-library-0.21.3.LICENSE.txt"
        )

    def test_zxing_vendored_library_exists_and_is_valid(self):
        """The source static tree must ship the pinned ZXing library asset."""
        self.assertTrue(
            self.zxing_asset_path.exists(),
            "static/js/libraries/zxing-library-0.21.3.min.js must exist.",
        )
        content = self.zxing_asset_path.read_text(encoding="utf-8")
        self.assertGreater(
            len(content),
            200_000,
            "ZXing minified asset should be substantial in size.",
        )
        self.assertIn(
            "BrowserMultiFormatReader",
            content,
            "ZXing library must export BrowserMultiFormatReader.",
        )
        self.assertIn(
            "BarcodeFormat",
            content,
            "ZXing library must export BarcodeFormat enum.",
        )
        self.assertIn(
            "Apache-2.0",
            content,
            "ZXing library header must declare Apache-2.0 license.",
        )

    def test_zxing_license_file_exists(self):
        """ZXing license text must be stored beside the vendored asset."""
        self.assertTrue(
            self.zxing_license_path.exists(),
            "static/js/libraries/zxing-library-0.21.3.LICENSE.txt must exist.",
        )
        content = self.zxing_license_path.read_text(encoding="utf-8")
        self.assertIn("Apache License", content)
        self.assertIn("Version 2.0", content)

    def test_base_template_has_no_remote_zxing_urls(self):
        """Templates must not reference remote CDN URLs for ZXing."""
        for path in (self.base_template_path, self.base_public_template_path):
            content = path.read_text(encoding="utf-8")
            relative_path = path.relative_to(settings.BASE_DIR).as_posix()

            self.assertNotIn(
                "cdn.jsdelivr.net/npm/@zxing",
                content,
                f"{relative_path} must not load ZXing from jsDelivr.",
            )
            self.assertNotIn(
                "@zxing/library@latest",
                content,
                f"{relative_path} must not load unpinned @latest ZXing.",
            )

    def test_base_template_references_local_zxing_library(self):
        """The base template must load the pinned local ZXing static file."""
        content = self.base_template_path.read_text(encoding="utf-8")
        self.assertIn(
            "js/libraries/zxing-library-0.21.3.min.js",
            content,
            "base.html must reference js/libraries/zxing-library-0.21.3.min.js.",
        )

    def test_base_template_renders_local_zxing_static_url(self):
        """Template rendering resolves the ZXing asset to a local static URL."""
        template_str = """
        {% load static %}
        <script src="{% static 'js/libraries/zxing-library-0.21.3.min.js' %}"></script>
        """
        rendered = Template(template_str).render(Context({}))
        self.assertIn("/static/js/libraries/zxing-library-0.21.3.min.js", rendered)
        self.assertNotIn("http://", rendered)
        self.assertNotIn("https://", rendered)

    def test_no_unpinned_latest_script_tags_in_shared_templates(self):
        """Shared templates must not contain unpinned @latest CDN script tags."""
        script_src_pattern = re.compile(r'<script\b[^>]*src=["\']([^"\']+)["\']')
        for path in (self.base_template_path, self.base_public_template_path):
            content = path.read_text(encoding="utf-8")
            relative_path = path.relative_to(settings.BASE_DIR).as_posix()
            for match in script_src_pattern.finditer(content):
                src = match.group(1)
                self.assertNotIn(
                    "@latest",
                    src,
                    f"{relative_path} has unpinned @latest script src: {src}",
                )

    def test_barcode_scanner_script_exists_and_references_local_assets(self):
        """The barcode scanner helper must exist and have no remote CDN references."""
        scanner_js_path = (
            Path(settings.BASE_DIR) / "static" / "js" / "barcode-scanner.js"
        )
        self.assertTrue(scanner_js_path.exists(), "barcode-scanner.js must exist.")
        content = scanner_js_path.read_text(encoding="utf-8")
        self.assertNotIn("cdn.jsdelivr.net", content)
        self.assertIn("initBarcodeScanner", content)
        self.assertIn("normalizeIsbn", content)

