"""Guard the Unraid template's sizing variables.

Floppy sizes gunicorn from the host (``config.runtime_profile``), and the deployment
guide tells operators to remove fixed overrides. The template used to ship
``WEB_CONCURRENCY=2`` anyway, so every Unraid install was started with an
explicit override that cost a second resident copy of the application.
"""

from pathlib import Path
from xml.etree import ElementTree as ET

from django.test import SimpleTestCase

TEMPLATE = Path(__file__).resolve().parents[3] / "templates" / "floppy.xml"
SIZING_VARIABLES = ("WEB_CONCURRENCY", "GUNICORN_THREADS")


class UnraidTemplateSizingTests(SimpleTestCase):
    """The template must not pin what the resource profile should decide."""

    @classmethod
    def setUpClass(cls):
        """Parse the shipped template once."""
        super().setUpClass()
        cls.configs = {
            config.get("Name"): config
            for config in ET.parse(TEMPLATE).getroot().findall("Config")
        }

    def test_sizing_variables_are_still_offered(self):
        """Deleting the elements would orphan a value Unraid still passes.

        Unraid keeps the operator's saved value in its own user template. A
        variable dropped from the CA template disappears from the UI while it
        is still handed to ``docker run``, leaving an override that cannot be
        seen or cleared. Shipping them blank is what makes them clearable.
        """
        for name in SIZING_VARIABLES:
            self.assertIn(name, self.configs)

    def test_sizing_variables_ship_unset(self):
        """Blank default and blank value, the same shape as DB_HOST and URLS."""
        for name in SIZING_VARIABLES:
            with self.subTest(variable=name):
                config = self.configs[name]
                self.assertEqual(config.get("Default"), "")
                self.assertIn(config.text, (None, ""))

    def test_unset_shape_matches_the_other_optional_variables(self):
        """Optional variables already have a convention; these must follow it."""
        reference = self.configs["DB_HOST"]

        for name in SIZING_VARIABLES:
            with self.subTest(variable=name):
                config = self.configs[name]
                self.assertEqual(config.get("Default"), reference.get("Default"))
                self.assertEqual(config.get("Required"), reference.get("Required"))


BUNDLED_TEMPLATES = {
    "floppy-bundled.xml": "latest-bundled",
    "floppy-bundled-stable.xml": "release-bundled",
}
BUNDLED_TEMPLATE = TEMPLATE.with_name("floppy-bundled.xml")


class UnraidBundledTemplateTests(SimpleTestCase):
    """The bundled template must not carry settings that switch off the bundle."""

    @classmethod
    def setUpClass(cls):
        """Parse the bundled template once."""
        super().setUpClass()
        cls.root = ET.parse(BUNDLED_TEMPLATE).getroot()
        cls.targets = {c.get("Target") for c in cls.root.findall("Config")}

    def test_uses_the_bundled_image(self):
        """A bundled template pointing at the standard tag would find no services."""
        self.assertTrue(self.root.findtext("Repository").endswith("-bundled"))

    def test_each_channel_points_at_a_published_tag(self):
        """Latest follows the latest branch, Stable the release branch."""
        for name, tag in BUNDLED_TEMPLATES.items():
            with self.subTest(template=name):
                root = ET.parse(TEMPLATE.with_name(name)).getroot()
                self.assertEqual(
                    root.findtext("Repository"), f"ghcr.io/dannyvfilms/floppy:{tag}"
                )
                self.assertIn(name, root.findtext("TemplateURL"))

    def test_external_service_variables_are_absent(self):
        """DB_HOST or REDIS_URL, even blank, must not reach the container."""
        for name in ("DB_HOST", "REDIS_URL", "DB_PASSWORD"):
            self.assertNotIn(name, self.targets)

    def test_persistent_paths_are_offered(self):
        """Data, database and backups each have their own host mount."""
        for path in ("/floppy/db", "/floppy/pgdata", "/floppy/backups"):
            self.assertIn(path, self.targets)

    def test_standard_template_is_unchanged_in_shape(self):
        """Existing installs keep SQLite and the external Redis default."""
        standard = ET.parse(TEMPLATE).getroot()
        self.assertEqual(
            standard.findtext("Repository"), "ghcr.io/dannyvfilms/floppy:latest"
        )
