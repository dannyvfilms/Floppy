import shutil
import subprocess
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class StatsMediaMergeSelfcheckTests(SimpleTestCase):
    """Runs the browser-side merge helpers' assert script under Node."""

    def test_selfcheck_passes(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed")

        script = (
            Path(settings.STATICFILES_DIRS[0])
            / "js"
            / "stats-media-merge.selfcheck.mjs"
        )
        result = subprocess.run(  # noqa: S603  # fixed argv, no user input
            [node, str(script)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertIn("selfcheck passed", result.stdout)

    def test_cached_english_weekday_uses_current_interface_language(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed")
        source = Path(settings.STATICFILES_DIRS[0]) / "js" / "date-range.js"
        script = """
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const document = {documentElement: {lang: 'es'}};
const context = {document, gettext: value => value,
  StatsMediaMerge: {mergeSummary: () => ({most_active_day: 'Friday'})}};
vm.createContext(context);
const picker = vm.runInContext(fs.readFileSync(process.argv[1], 'utf8') + '; dateRangePicker()', context);
assert.equal(picker.currentTypeSummary.most_active_day_label, 'viernes');
assert.equal(picker.currentTypeSummary.most_active_day, 'Friday');
document.documentElement.lang = 'en';
assert.equal(picker.currentTypeSummary.most_active_day_label, 'Friday');
"""
        result = subprocess.run(  # noqa: S603  # fixed script and repository asset
            [node, "-e", script, str(source)], capture_output=True, text=True,
            timeout=10, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
