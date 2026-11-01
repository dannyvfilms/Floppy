"""Every importer must report progress, or the Activity panel shows a placeholder.

The importer list is discovered, not maintained: adding a module under
``integrations.imports`` that exposes ``importer`` fails this test until it
reports progress (or is listed in ``INHERITS_REPORTING`` with its parent).
"""

import importlib
import inspect
import pkgutil
import re
from pathlib import Path

from django.test import SimpleTestCase

import integrations.imports as imports_package

# Modules whose importer subclasses another importer that does the reporting.
INHERITS_REPORTING = {
    "trakt_export": "trakt",
    "wetrakr": "trakt",
    "kavita": "reading_server",
    "komga": "reading_server",
}
REPORT_CALL = re.compile(r"import_progress\.report\(")


def _importer_modules():
    names = []
    for info in pkgutil.iter_modules(imports_package.__path__):
        module = importlib.import_module(f"integrations.imports.{info.name}")
        if callable(getattr(module, "importer", None)):
            names.append(info.name)
    return names


def _reports(name):
    source = inspect.getsource(importlib.import_module(f"integrations.imports.{name}"))
    return bool(REPORT_CALL.search(source))


class ImportProgressCoverageTests(SimpleTestCase):
    def test_every_importer_reports_progress(self):
        missing = []
        for name in _importer_modules():
            if _reports(name):
                continue
            parent = INHERITS_REPORTING.get(name)
            if parent is None or not _reports(parent):
                missing.append(name)
        self.assertEqual(
            missing,
            [],
            "Importers without import_progress.report(); add per-item reports "
            "(total=None when the count is unknown).",
        )

    def test_inherited_reporters_still_call_the_parent_loop(self):
        """An override of the parent's loop must keep its own report call."""
        for name, parent in INHERITS_REPORTING.items():
            if _reports(name):
                continue
            self.assertTrue(_reports(parent), f"{name} -> {parent} does not report")

    def test_every_task_importer_is_covered(self):
        """Importers wired into tasks must live in a checked module."""
        covered = set(_importer_modules())
        tasks_dir = Path(inspect.getfile(imports_package)).parents[1] / "tasks"
        referenced = set()
        for path in tasks_dir.glob("*.py"):
            referenced.update(re.findall(r"\b([a-z_0-9]+)\.importer\b", path.read_text()))
        unknown = {
            name
            for name in referenced
            if name in {m.name for m in pkgutil.iter_modules(imports_package.__path__)}
            and name not in covered
        }
        self.assertEqual(unknown, set())
