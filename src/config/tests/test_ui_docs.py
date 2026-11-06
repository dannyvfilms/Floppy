"""The UI component register and source map must agree with each other and the code.

Runs scripts/check_ui_docs.py (loaded by path, as in test_migration_order): every
register entry has one status from the register's vocabulary, every path the register
names exists, the source map has a section and the same status for every entry, and
every template, script, stylesheet and frontend file is mapped exactly once.
"""

import contextlib
import importlib.util
import io
from pathlib import Path
from unittest import SkipTest, TestCase

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "scripts" / "check_ui_docs.py"


class UiDocsTests(TestCase):
    """Keep docs/ui honest as components move to React."""

    def test_register_and_source_map_have_no_drift(self):
        """Run the check; its output names every problem."""
        if not _SCRIPT.exists() or not (_ROOT / "docs" / "ui").exists():
            raise SkipTest("docs/ui or scripts/ is not part of this checkout")
        spec = importlib.util.spec_from_file_location("check_ui_docs", _SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = module.main()
        self.assertEqual(exit_code, 0, output.getvalue())
