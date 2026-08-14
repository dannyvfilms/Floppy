import hashlib
import re
from pathlib import Path

from django.conf import settings
from django.templatetags.static import static
from django.test import SimpleTestCase

ZXING_VERSION = "0.21.3"
ZXING_ASSET = f"js/libraries/zxing-library-{ZXING_VERSION}.min.js"
ZXING_LICENSE = f"js/libraries/zxing-library-{ZXING_VERSION}.LICENSE.txt"
ZXING_PROVENANCE = f"js/libraries/zxing-library-{ZXING_VERSION}.PROVENANCE.txt"
ZXING_ASSET_SIZE = 336_097
ZXING_ASSET_GIT_BLOB = "7d0271d985f301e7d5e8ac3cc484721c3a627271"
ZXING_TAG_COMMIT = "0e68da880f64974746083431f3442c29835eddda"


def git_blob_sha(path):
    """Return the Git object ID for a file without invoking Git."""
    content = path.read_bytes()
    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(
        header + content,
        usedforsecurity=False,
    ).hexdigest()


class StaticLibraryContractTests(SimpleTestCase):
    """Protect vendored static libraries against remote or unreviewed drift."""

    def setUp(self):
        """Resolve the source static tree and shared template paths."""
        base_dir = Path(settings.BASE_DIR)
        static_dir = base_dir / "static"
        self.shared_template_paths = (
            base_dir / "templates" / "base.html",
            base_dir / "templates" / "base_public.html",
        )
        self.base_template_path = self.shared_template_paths[0]
        self.zxing_asset_path = static_dir / ZXING_ASSET
        self.zxing_license_path = static_dir / ZXING_LICENSE
        self.zxing_provenance_path = static_dir / ZXING_PROVENANCE

    def test_zxing_vendored_library_matches_reviewed_asset(self):
        """The repository must ship the exact ZXing bundle reviewed in this change."""
        self.assertTrue(
            self.zxing_asset_path.exists(),
            f"static/{ZXING_ASSET} must exist.",
        )
        content = self.zxing_asset_path.read_text(encoding="utf-8")

        self.assertEqual(self.zxing_asset_path.stat().st_size, ZXING_ASSET_SIZE)
        self.assertEqual(git_blob_sha(self.zxing_asset_path), ZXING_ASSET_GIT_BLOB)
        self.assertIn(f"@zxing/library v{ZXING_VERSION}", content)
        self.assertIn("BrowserMultiFormatReader", content)
        self.assertIn("BarcodeFormat", content)
        self.assertIn("Apache-2.0", content)

    def test_zxing_license_file_exists(self):
        """The complete ZXing license must be stored beside the bundle."""
        self.assertTrue(
            self.zxing_license_path.exists(),
            f"static/{ZXING_LICENSE} must exist.",
        )
        content = self.zxing_license_path.read_text(encoding="utf-8")
        self.assertIn("Apache License", content)
        self.assertIn("Version 2.0", content)

    def test_zxing_provenance_records_source_and_identity(self):
        """The bundle must have enough source data for a controlled update."""
        self.assertTrue(
            self.zxing_provenance_path.exists(),
            f"static/{ZXING_PROVENANCE} must exist.",
        )
        content = self.zxing_provenance_path.read_text(encoding="utf-8")
        self.assertIn("Package: @zxing/library", content)
        self.assertIn(f"Version: {ZXING_VERSION}", content)
        self.assertIn("Package file: umd/index.min.js", content)
        self.assertIn(ZXING_ASSET_GIT_BLOB, content)
        self.assertIn(ZXING_TAG_COMMIT, content)

    def test_shared_templates_have_no_remote_zxing_script(self):
        """Shared templates must load ZXing only from the local static tree."""
        script_src_pattern = re.compile(r'<script\b[^>]*src=["\']([^"\']+)["\']')

        for path in self.shared_template_paths:
            content = path.read_text(encoding="utf-8")
            relative_path = path.relative_to(settings.BASE_DIR).as_posix()
            for match in script_src_pattern.finditer(content):
                src = match.group(1)
                if "zxing" not in src.lower():
                    continue
                self.assertFalse(
                    src.startswith(("http://", "https://", "//")),
                    f"{relative_path} must not load remote ZXing: {src}",
                )
                self.assertNotIn(
                    "@latest",
                    src,
                    f"{relative_path} must not load unpinned ZXing: {src}",
                )

    def test_base_template_references_reviewed_local_zxing_asset(self):
        """The real base template must reference the reviewed versioned file."""
        content = self.base_template_path.read_text(encoding="utf-8")
        expected_tag = f"{{% static '{ZXING_ASSET}' %}}"

        self.assertEqual(content.count(expected_tag), 1)

    def test_zxing_loads_before_barcode_scanner_helper(self):
        """ZXing must load before the helper reads the window.ZXing export."""
        content = self.base_template_path.read_text(encoding="utf-8")
        zxing_tag = f"{{% static '{ZXING_ASSET}' %}}"
        scanner_tag = "{% static 'js/barcode-scanner.js' %}"

        self.assertIn(zxing_tag, content)
        self.assertIn(scanner_tag, content)
        self.assertLess(content.index(zxing_tag), content.index(scanner_tag))

    def test_configured_static_url_is_local(self):
        """Django must resolve the ZXing file without an external origin."""
        rendered_url = static(ZXING_ASSET)

        self.assertTrue(rendered_url.startswith(settings.STATIC_URL))
        self.assertNotIn("http://", rendered_url)
        self.assertNotIn("https://", rendered_url)
        self.assertFalse(rendered_url.startswith("//"))

    def test_no_unpinned_latest_script_tags_in_shared_templates(self):
        """Shared templates must not contain an unpinned @latest script source."""
        script_src_pattern = re.compile(r'<script\b[^>]*src=["\']([^"\']+)["\']')
        for path in self.shared_template_paths:
            content = path.read_text(encoding="utf-8")
            relative_path = path.relative_to(settings.BASE_DIR).as_posix()
            for match in script_src_pattern.finditer(content):
                src = match.group(1)
                self.assertNotIn(
                    "@latest",
                    src,
                    f"{relative_path} has an unpinned @latest script source: {src}",
                )

    def test_barcode_scanner_helper_uses_local_window_export(self):
        """The helper must use the local window export and contain no CDN URL."""
        scanner_js_path = (
            Path(settings.BASE_DIR) / "static" / "js" / "barcode-scanner.js"
        )
        self.assertTrue(scanner_js_path.exists(), "barcode-scanner.js must exist.")
        content = scanner_js_path.read_text(encoding="utf-8")
        self.assertNotIn("cdn.jsdelivr.net", content)
        self.assertNotIn("unpkg.com", content)
        self.assertIn("window.ZXing", content)
        self.assertIn("initBarcodeScanner", content)
        self.assertIn("normalizeIsbn", content)
