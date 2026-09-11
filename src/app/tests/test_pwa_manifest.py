import json
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import resolve


class WebManifestTests(SimpleTestCase):
    """Regression tests for the installed PWA manifest."""

    def setUp(self):
        self.static_dir = Path(settings.BASE_DIR) / "static"
        manifest_path = self.static_dir / "favicon" / "site.webmanifest"
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    def test_manifest_includes_maskable_icons_and_valid_shortcuts(self):
        icons = {icon["src"]: icon for icon in self.manifest["icons"]}
        expected_icons = {
            "/static/favicon/android-chrome-192x192.png": "any",
            "/static/favicon/android-chrome-512x512.png": "any",
            "/static/favicon/android-chrome-192x192-maskable.png": "maskable",
            "/static/favicon/android-chrome-512x512-maskable.png": "maskable",
        }

        for src, purpose in expected_icons.items():
            self.assertIn(src, icons)
            self.assertEqual(icons[src]["purpose"], purpose)
            asset_path = self.static_dir / src.removeprefix("/static/")
            self.assertTrue(asset_path.exists(), f"Missing manifest icon asset: {src}")

        expected_shortcuts = {
            "Home": ("/", "/static/img/shortcuts/home.svg"),
            "TV Shows": ("/medialist/tv", "/static/img/shortcuts/tv.svg"),
            "Movies": ("/medialist/movie", "/static/img/shortcuts/movies.svg"),
            "Anime": ("/medialist/anime", "/static/img/shortcuts/anime.svg"),
            "Manga": ("/medialist/manga", "/static/img/shortcuts/manga.svg"),
            "Games": ("/medialist/game", "/static/img/shortcuts/games.svg"),
            "Books": ("/medialist/book", "/static/img/shortcuts/books.svg"),
            "Comics": ("/medialist/comic", "/static/img/shortcuts/comics.svg"),
            "Board Games": (
                "/medialist/boardgame",
                "/static/img/shortcuts/boardgames.svg",
            ),
            "Statistics": ("/statistics", "/static/img/shortcuts/stats.svg"),
            "Your Lists": ("/lists", "/static/img/shortcuts/lists.svg"),
        }
        shortcuts = {
            shortcut["name"]: shortcut for shortcut in self.manifest["shortcuts"]
        }

        self.assertEqual(set(shortcuts), set(expected_shortcuts))

        for name, (url, icon_src) in expected_shortcuts.items():
            shortcut = shortcuts[name]
            self.assertEqual(shortcut["url"], url)
            self.assertEqual(shortcut["icons"], [{"src": icon_src, "sizes": "192x192"}])
            asset_path = self.static_dir / icon_src.removeprefix("/static/")
            self.assertTrue(
                asset_path.exists(), f"Missing shortcut icon asset: {icon_src}"
            )

    def test_manifest_declares_a_standalone_root_scoped_identity(self):
        self.assertEqual(self.manifest["name"], "Floppy - Media Tracker")
        self.assertEqual(self.manifest["short_name"], "Floppy")
        self.assertEqual(self.manifest["id"], "/")
        self.assertEqual(self.manifest["start_url"], "/")
        self.assertEqual(self.manifest["scope"], "/")
        self.assertEqual(self.manifest["display"], "standalone")
        self.assertEqual(self.manifest["display_override"], ["standalone"])
        self.assertEqual(self.manifest["theme_color"], "#181a1b")
        self.assertEqual(self.manifest["background_color"], "#212529")

    def test_manifest_icon_files_match_their_declared_sizes(self):
        from PIL import Image

        for icon in self.manifest["icons"]:
            with self.subTest(src=icon["src"]):
                asset_path = self.static_dir / icon["src"].removeprefix("/static/")
                with Image.open(asset_path) as image:
                    self.assertEqual(
                        f"{image.width}x{image.height}",
                        icon["sizes"],
                        f"{icon['src']} does not match its declared sizes",
                    )
                self.assertEqual(icon["type"], "image/png")

    def test_every_shortcut_url_resolves_to_a_real_route(self):
        for shortcut in self.manifest["shortcuts"]:
            with self.subTest(url=shortcut["url"]):
                # Raises Resolver404 if a shortcut points at a dead route.
                resolve(shortcut["url"])

    def test_manifest_ships_both_any_and_maskable_icons_at_both_sizes(self):
        by_purpose = {}
        for icon in self.manifest["icons"]:
            by_purpose.setdefault(icon["purpose"], set()).add(icon["sizes"])

        self.assertEqual(by_purpose["any"], {"192x192", "512x512"})
        self.assertEqual(by_purpose["maskable"], {"192x192", "512x512"})


class BaseTemplateIconReferenceTests(SimpleTestCase):
    """The head must not point at favicon assets that were never shipped."""

    def test_base_templates_only_reference_existing_favicon_assets(self):
        static_dir = Path(settings.BASE_DIR) / "static"
        template_dir = Path(settings.BASE_DIR) / "templates"
        pattern = re.compile(r"favicon/[A-Za-z0-9._-]+")

        for name in ("base.html", "base_public.html"):
            source = (template_dir / name).read_text(encoding="utf-8")
            for reference in sorted(set(pattern.findall(source))):
                with self.subTest(template=name, asset=reference):
                    self.assertTrue(
                        (static_dir / reference).exists(),
                        f"{name} references missing static asset: {reference}",
                    )

    def test_base_captures_the_install_prompt_before_the_body_renders(self):
        source = (
            Path(settings.BASE_DIR) / "templates" / "base.html"
        ).read_text(encoding="utf-8")
        head = source.split("</head>", 1)[0]

        # hx-boost swaps the body only, so a body-scoped listener would miss
        # beforeinstallprompt on every boosted settings navigation.
        self.assertIn('window.addEventListener("beforeinstallprompt"', head)
        self.assertIn('window.addEventListener("appinstalled"', head)
        self.assertIn("window.floppyPwa", head)
