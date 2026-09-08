"""Regression tests for inline JavaScript catalog extraction."""

import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "update_translations.py"
SPEC = importlib.util.spec_from_file_location("update_translations", SCRIPT)
translations = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(translations)


class InlineExtractionTests(unittest.TestCase):
    """Cover literals, dynamic labels, and the real GNU gettext boundary."""

    def test_escaped_quotes_entities_and_plural(self):
        """Keep JS escaping intact and decode HTML attribute entities once."""
        html = r"""
        <button x-text="gettext('Don\'t delete')"></button>
        <button onclick="gettext(&quot;Say \&quot;hello\&quot;&quot;)"></button>
        <script>ngettext('One item', 'Many items', items.length);</script>
        """
        self.assertEqual(
            translations.extract_inline_calls(html),
            [
                r"gettext('Don\'t delete');",
                r'gettext("Say \"hello\"");',
                "ngettext('One item', 'Many items', 2);",
            ],
        )

    def test_dynamic_arguments_comments_and_strings_are_ignored(self):
        """Never turn runtime values, comments, or example strings into msgids."""
        html = """
        <!-- <button x-text="gettext('HTML comment')"></button> -->
        {% comment %}<script>gettext('Django comment')</script>{% endcomment %}
        <button x-text="gettext('{{ user.theme|default:'dark'|escapejs }}')"></button>
        <script>
          gettext(label);
          gettext('prefix ' + label);
          ngettext(one, 'many', count);
          gettext(`dynamic ${label}`);
          const sample = "gettext('example')";
          // gettext('JS comment');
          /* gettext('block comment'); */
          window.gettext('Kept');
        </script>
        """
        self.assertEqual(translations.extract_inline_calls(html), ["gettext('Kept');"])

    def test_context_and_non_message_values(self):
        """Preserve contexts while ignoring neighboring status values and keys."""
        html = """
        <button @click="status = 'Planning'; label = pgettext('menu', 'Open')"></button>
        <script>npgettext('files', 'One file', 'Many files', count);</script>
        """
        self.assertEqual(
            translations.extract_inline_calls(html),
            [
                "pgettext('menu', 'Open');",
                "npgettext('files', 'One file', 'Many files', 2);",
            ],
        )

    def test_verbatim_examples_do_not_swallow_following_calls(self):
        """Handlebars inside verbatim must not start a Django comment."""
        html = """
        <textarea>{% verbatim %}
          {"Event": "{{#if Started}}Play{{/if}}"}
        {% endverbatim %}</textarea>
        <button x-text="gettext('No libraries available')"></button>
        {# Later Django comment #}
        {% verbatim example %}<script>gettext('Example')</script>
        {% endverbatim example %}
        <button @click="gettext('Still present')"></button>
        """
        self.assertEqual(
            translations.extract_inline_calls(html),
            ["gettext('No libraries available');", "gettext('Still present');"],
        )

    def test_cleanup_on_failed_django_command(self):
        """A failed catalog refresh cannot leave generated sources in the tree."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "templates").mkdir()
            with patch.object(
                translations.subprocess,
                "run",
                side_effect=subprocess.CalledProcessError(1, "makemessages"),
            ):
                with self.assertRaises(subprocess.CalledProcessError):
                    translations.update_catalogs(root, ["de"])
            self.assertFalse((root / "inline_translation_extraction").exists())

    @unittest.skipUnless(
        shutil.which("xgettext") and importlib.util.find_spec("django"),
        "Django and GNU gettext are required",
    )
    def test_native_django_refresh_covers_both_domains(self):
        """Refresh only an isolated project's Python, HTML, and JS catalogs."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "templates").mkdir()
            (root / "locale").mkdir()
            (root / "manage.py").write_text(
                "from pathlib import Path\n"
                "from django.conf import settings\n"
                "from django.core.management import execute_from_command_line\n"
                "settings.configure(USE_I18N=True, "
                "LOCALE_PATHS=[str(Path(__file__).parent / 'locale')])\n"
                "execute_from_command_line()\n",
                encoding="utf-8",
            )
            (root / "labels.py").write_text(
                "from django.utils.translation import gettext_noop\n"
                "LABEL = gettext_noop('Dynamic Python label')\n",
                encoding="utf-8",
            )
            (root / "templates/sample.html").write_text(
                '{% load i18n %}{% translate "HTML message" %}'
                "<button x-text=\"gettext('Inline message')\"></button>",
                encoding="utf-8",
            )
            (root / "native.js").write_text(
                "gettext('Native JS message');\n",
                encoding="utf-8",
            )
            vendor = root / "static/js/libraries"
            vendor.mkdir(parents=True)
            (vendor / "example.min.js").write_text(
                "gettext('Third-party example');",
                encoding="utf-8",
            )
            translations.update_catalogs(root, ["de"])
            catalogs = root / "locale/de/LC_MESSAGES"
            python_catalog = (catalogs / "django.po").read_text(encoding="utf-8")
            js_catalog = (catalogs / "djangojs.po").read_text(encoding="utf-8")
            self.assertIn('msgid "Dynamic Python label"', python_catalog)
            self.assertIn('msgid "HTML message"', python_catalog)
            self.assertIn('msgid "Inline message"', js_catalog)
            self.assertIn('msgid "Native JS message"', js_catalog)
            self.assertNotIn('msgid "Third-party example"', js_catalog)
            self.assertFalse((root / "inline_translation_extraction").exists())
            js_path = catalogs / "djangojs.po"
            js_path.write_text(
                js_catalog.replace(
                    'msgid "Inline message"\nmsgstr ""',
                    'msgid "Inline message"\nmsgstr "Inline-Nachricht"',
                ),
                encoding="utf-8",
            )
            translations.update_catalogs(root, ["de"])
            self.assertIn('msgstr "Inline-Nachricht"', js_path.read_text("utf-8"))
            self.assertFalse((root / "inline_translation_extraction").exists())

    @unittest.skipUnless(shutil.which("xgettext"), "GNU gettext is not installed")
    def test_real_xgettext_extracts_generated_messages(self):
        """Prove extraction into a temporary PO without touching app catalogs."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            templates = root / "templates"
            templates.mkdir()
            (templates / "sample.html").write_text(
                r"""<button x-text="gettext('Don\'t delete')"></button>
                <script>ngettext('One item', 'Many items', count);</script>""",
                encoding="utf-8",
            )
            generated = root / "generated"
            translations.write_inline_sources(root, generated)
            output = root / "djangojs.po"
            subprocess.run(  # noqa: S603 -- trusted gettext tool, temporary test inputs
                [
                    shutil.which("xgettext"),
                    "--language=JavaScript",
                    "--from-code=UTF-8",
                    "--keyword=gettext",
                    "--keyword=ngettext:1,2",
                    "--no-location",
                    "-o",
                    str(output),
                    str(generated / "templates/sample.html.js"),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            catalog = output.read_text(encoding="utf-8")
            self.assertIn('msgid "Don\'t delete"', catalog)
            self.assertIn('msgid "One item"', catalog)
            self.assertIn('msgid_plural "Many items"', catalog)


if __name__ == "__main__":
    unittest.main()
