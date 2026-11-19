"""The JavaScript test guard must fail, naming the file, for every gap.

Each case builds a small repository with its own package.json files and runs
the real script against it: a test file no script runs, a file run twice, a
listed file that is gone, a missing script, and ignored folders that must not
count. The last case checks this repository itself.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_js_tests.py"
spec = importlib.util.spec_from_file_location("check_js_tests", SCRIPT)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

ROOT_SCRIPTS = {
    "test:js": "python3 scripts/check_js_tests.py && npm run test:logic && npm --prefix app run test:native",
    "test:logic": "node --test scripts/a.test.mjs scripts/b.test.mjs",
}
NATIVE_SCRIPTS = {"test:native": 'node --no-warnings --test "src/**/*.test.mjs"'}


class JsTestGuardTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name).resolve()
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)  # noqa: S607
        (self.repo / ".gitignore").write_text("node_modules/\n")
        self._package(".", ROOT_SCRIPTS)
        self._package("app", NATIVE_SCRIPTS)
        for path in (
            "scripts/a.test.mjs",
            "scripts/b.test.mjs",
            "app/src/top.test.mjs",
            "app/src/data/deep.test.mjs",
        ):
            self._file(path)

    def tearDown(self):
        self._tmp.cleanup()

    def _package(self, directory: str, scripts: dict[str, str]) -> None:
        folder = self.repo / directory
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "package.json").write_text(json.dumps({"scripts": scripts}))

    def _file(self, path: str) -> None:
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("")

    def _check(self):
        passed, report = guard.check(self.repo)
        return passed, "\n".join(report)

    def test_every_file_run_once_passes(self):
        passed, report = self._check()
        self.assertTrue(passed, report)
        self.assertIn("4 test files, each run once", report)

    def test_glob_matches_files_at_any_depth(self):
        runs, problems = guard.collect_runs(self.repo)
        self.assertEqual(problems, [])
        self.assertEqual(runs["app/src/top.test.mjs"], ["app/package.json test:native"])
        self.assertIn("app/src/data/deep.test.mjs", runs)

    def test_file_no_script_runs_is_named_with_where_to_add_it(self):
        self._file("scripts/zz_probe.test.mjs")
        self._file("app/other/stray.test.mjs")
        passed, report = self._check()
        self.assertFalse(passed)
        self.assertIn(
            "scripts/zz_probe.test.mjs is not run by `npm run test:js`", report
        )
        self.assertIn("test:js-logic in package.json", report)
        self.assertIn("app/other/stray.test.mjs is not run", report)

    def test_untracked_new_file_counts(self):
        self._file("scripts/new.test.mjs")
        self.assertIn("scripts/new.test.mjs", guard.tracked_tests(self.repo))

    def test_ignored_folders_do_not_count(self):
        self._file("node_modules/pkg/dep.test.mjs")
        passed, report = self._check()
        self.assertTrue(passed, report)

    def test_file_run_by_two_scripts_fails(self):
        scripts = dict(ROOT_SCRIPTS)
        scripts["test:js"] += " && npm run test:again"
        scripts["test:again"] = "node --test --test-force-exit scripts/a.test.mjs"
        self._package(".", scripts)
        passed, report = self._check()
        self.assertFalse(passed)
        self.assertIn("scripts/a.test.mjs runs 2 times", report)

    def test_listed_file_that_is_gone_fails(self):
        (self.repo / "scripts/b.test.mjs").unlink()
        passed, report = self._check()
        self.assertFalse(passed)
        self.assertIn("scripts/b.test.mjs matches no file", report)

    def test_missing_script_fails(self):
        self._package("app", {})
        passed, report = self._check()
        self.assertFalse(passed)
        self.assertIn("app/package.json test:native: script is missing", report)

    def test_this_repository_runs_every_javascript_test_once(self):
        passed, report = guard.check(ROOT)
        self.assertTrue(passed, "\n".join(report))


if __name__ == "__main__":
    unittest.main()
