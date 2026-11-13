"""Selector cases for scripts/test.sh --affected."""

import os
import stat
import subprocess
import textwrap
from pathlib import Path

from django.test import SimpleTestCase

from config.affected_tests import (
    MODE_FULL,
    MODE_LABELS,
    MODE_NONE,
    MissingBaseError,
    changed_paths,
    parse_diff_hunks,
    select,
    test_module_from_context,
)

_REPO = Path(__file__).resolve().parents[3]


def _write(repo: Path, relative: str, source: str) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source), encoding="utf-8")


def _sample(repo: Path) -> None:
    _write(
        repo,
        "src/app/models/__init__.py",
        "from app.models.media import Movie\n",
    )
    _write(repo, "src/app/models/media.py", "class Movie:\n    pass\n")
    _write(repo, "src/app/models/music.py", "class Album:\n    pass\n")
    _write(repo, "src/app/services.py", "def run():\n    return None\n")
    _write(repo, "src/app/signals.py", "def ready():\n    return None\n")
    _write(
        repo,
        "src/app/tests/test_media.py",
        "from app.models import Movie\n",
    )
    _write(
        repo,
        "src/app/tests/test_services.py",
        "from app.services import run\n",
    )
    _write(
        repo,
        "src/app/tests/test_signals.py",
        "import app.signals\n",
    )
    _write(repo, "src/users/orphan.py", "VALUE = 1\n")


class AffectedTestsSelectionTests(SimpleTestCase):
    def setUp(self):
        self.repo = Path(self._tmpdir())
        _sample(self.repo)

    def _tmpdir(self) -> str:
        import tempfile

        self.addCleanup(lambda: None)
        path = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(path, ignore_errors=True))
        return path

    def _mode(self, *paths: str, hooks_dir: str | None = None):
        return select(list(paths), repo=self.repo, hooks_dir=hooks_dir)

    def test_changed_test_module_runs_that_module(self):
        mode, labels, _notes = self._mode("src/app/tests/test_media.py")
        self.assertEqual(mode, MODE_LABELS)
        self.assertEqual(labels, ["app.tests.test_media"])

    def test_reexported_submodule_selects_the_barrel_importer(self):
        mode, labels, _notes = self._mode("src/app/models/media.py")
        self.assertEqual(mode, MODE_LABELS)
        self.assertEqual(labels, ["app.tests.test_media"])

    def test_direct_import_selects_that_test(self):
        mode, labels, _notes = self._mode("src/app/services.py")
        self.assertEqual(mode, MODE_LABELS)
        self.assertEqual(labels, ["app.tests.test_services"])

    def test_unmapped_file_runs_the_app(self):
        mode, labels, notes = self._mode("src/app/models/music.py")
        self.assertEqual(mode, MODE_LABELS)
        self.assertEqual(labels, ["app"])
        self.assertIn("src/app/models/music.py", notes[0])

    def test_signal_module_runs_the_app(self):
        mode, labels, _notes = self._mode("src/app/signals.py")
        self.assertEqual(mode, MODE_LABELS)
        self.assertEqual(labels, ["app"])

    def test_template_runs_the_fast_suite(self):
        mode, _labels, _notes = self._mode("src/templates/base.html")
        self.assertEqual(mode, MODE_FULL)

    def test_lockfile_runs_the_fast_suite(self):
        mode, _labels, _notes = self._mode("uv.lock")
        self.assertEqual(mode, MODE_FULL)

    def test_docs_only_runs_nothing(self):
        mode, labels, _notes = self._mode("docs/plans/3-run-affected-tests.md")
        self.assertEqual(mode, MODE_NONE)
        self.assertEqual(labels, [])

    def test_deleted_test_module_is_omitted(self):
        mode, labels, _notes = self._mode("src/app/tests/test_gone.py")
        self.assertEqual(mode, MODE_NONE)
        self.assertEqual(labels, [])

    def test_untracked_test_module_is_included(self):
        _write(self.repo, "src/app/tests/test_new.py", "VALUE = 1\n")
        mode, labels, _notes = self._mode("src/app/tests/test_new.py")
        self.assertEqual(mode, MODE_LABELS)
        self.assertEqual(labels, ["app.tests.test_new"])

    def test_mcp_tests_do_not_escalate(self):
        mode, labels, notes = self._mode("mcp_server/tests/test_tool.py")
        self.assertEqual(mode, MODE_NONE)
        self.assertEqual(labels, [])
        self.assertIn("mcp_server/tests/test_tool.py", notes[0])

    def test_other_app_fallback_stays_on_that_app(self):
        mode, labels, _notes = self._mode("src/users/orphan.py")
        self.assertEqual(mode, MODE_LABELS)
        self.assertEqual(labels, ["users"])

    def test_hook_file_runs_the_app(self):
        _write(self.repo, "hooks/genre.py", "VALUE = 1\n")
        mode, labels, _notes = self._mode(
            "hooks/genre.py",
            hooks_dir=str(self.repo / "hooks"),
        )
        self.assertEqual(mode, MODE_LABELS)
        self.assertEqual(labels, ["app"])

    def test_app_fallback_covers_a_specific_label_in_that_app(self):
        mode, labels, _notes = self._mode(
            "src/app/models/music.py",
            "src/app/services.py",
        )
        self.assertEqual(mode, MODE_LABELS)
        self.assertEqual(labels, ["app"])

    def test_collector_returns_paths_when_base_exists(self):
        try:
            paths = changed_paths(_REPO)
        except MissingBaseError:
            self.skipTest("origin/latest is not available")
        self.assertIsInstance(paths, list)

    def test_coverage_map_selects_the_test_that_executed_the_line(self):
        mode, labels, _notes = select(
            ["src/app/models/media.py"],
            repo=self.repo,
            line_map={
                "src/app/models/media.py": (
                    "src/app/models/media.py",
                    frozenset({2}),
                ),
            },
            coverage_index={
                "src/app/models/media.py": {2: {"app.tests.test_services"}},
            },
        )
        self.assertEqual(mode, MODE_LABELS)
        self.assertEqual(labels, ["app.tests.test_services"])

    def test_file_missing_from_the_map_uses_imports(self):
        mode, labels, notes = select(
            ["src/app/services.py"],
            repo=self.repo,
            line_map={
                "src/app/services.py": ("src/app/services.py", frozenset({1})),
            },
            coverage_index={},
        )
        self.assertEqual(mode, MODE_LABELS)
        self.assertEqual(labels, ["app.tests.test_services"])
        self.assertIn("src/app/services.py", notes[0])

    def test_new_file_uses_imports(self):
        mode, labels, _notes = select(
            ["src/app/services.py"],
            repo=self.repo,
            line_map={"src/app/services.py": ("src/app/services.py", frozenset())},
            coverage_index={
                "src/app/services.py": {1: {"app.tests.test_media"}},
            },
        )
        self.assertEqual(mode, MODE_LABELS)
        self.assertEqual(labels, ["app.tests.test_services"])

    def test_measured_lines_with_no_test_fall_back_to_the_app(self):
        mode, labels, notes = select(
            ["src/app/models/music.py"],
            repo=self.repo,
            line_map={
                "src/app/models/music.py": (
                    "src/app/models/music.py",
                    frozenset({1}),
                ),
            },
            coverage_index={"src/app/models/music.py": {1: set()}},
        )
        self.assertEqual(mode, MODE_LABELS)
        self.assertEqual(labels, ["app"])
        self.assertIn("src/app/models/music.py", notes[0])

    def test_uncovered_lines_still_run_known_importers(self):
        mode, labels, _notes = select(
            ["src/app/services.py"],
            repo=self.repo,
            line_map={"src/app/services.py": ("src/app/services.py", {99})},
            coverage_index={
                "src/app/services.py": {1: {"app.tests.test_media"}},
            },
        )
        self.assertEqual(mode, MODE_LABELS)
        self.assertEqual(labels, ["app.tests.test_services"])

    def test_template_stays_full_when_a_map_is_present(self):
        mode, _labels, _notes = select(
            ["src/templates/base.html"],
            repo=self.repo,
            line_map={},
            coverage_index={},
        )
        self.assertEqual(mode, MODE_FULL)

    def test_changed_test_module_still_runs_with_a_map(self):
        mode, labels, _notes = select(
            ["src/app/tests/test_media.py", "src/app/models/media.py"],
            repo=self.repo,
            line_map={
                "src/app/models/media.py": (
                    "src/app/models/media.py",
                    frozenset({2}),
                ),
            },
            coverage_index={
                "src/app/models/media.py": {2: {"app.tests.test_services"}},
            },
        )
        self.assertEqual(mode, MODE_LABELS)
        self.assertEqual(
            labels,
            ["app.tests.test_media", "app.tests.test_services"],
        )


class AffectedTestsDiffTests(SimpleTestCase):
    def test_hunks_use_old_lines_and_the_insertion_anchor(self):
        parsed = parse_diff_hunks(
            "\n".join(
                [
                    "diff --git a/src/app/models/media.py b/src/app/models/media.py",
                    "--- a/src/app/models/media.py",
                    "+++ b/src/app/models/media.py",
                    "@@ -10,3 +10,4 @@",
                    "@@ -40,0 +41,2 @@",
                    "diff --git a/src/app/old.py b/src/app/new.py",
                    "--- a/src/app/old.py",
                    "+++ b/src/app/new.py",
                    "@@ -2 +2 @@",
                ],
            ),
        )
        _lookup, lines = parsed["src/app/models/media.py"]
        self.assertEqual(set(lines), {10, 11, 12, 40})
        self.assertEqual(parsed["src/app/new.py"][0], "src/app/old.py")
        self.assertEqual(set(parsed["src/app/old.py"][1]), {2})

    def test_new_file_has_no_old_lines(self):
        parsed = parse_diff_hunks(
            "\n".join(
                [
                    "diff --git a/src/app/new.py b/src/app/new.py",
                    "--- /dev/null",
                    "+++ b/src/app/new.py",
                    "@@ -0,0 +1,4 @@",
                ],
            ),
        )
        self.assertEqual(set(parsed["src/app/new.py"][1]), set())

    def test_context_collapses_to_the_test_module(self):
        self.assertEqual(
            test_module_from_context(
                "app.tests.test_media.MediaTests.test_movie",
            ),
            "app.tests.test_media",
        )
        self.assertEqual(
            test_module_from_context("app.tests.test_media.test_func"),
            "app.tests.test_media",
        )
        self.assertIsNone(test_module_from_context(""))
        self.assertIsNone(test_module_from_context("app.services.do_thing"))


class AffectedTestsScriptTests(SimpleTestCase):
    def _run(self, stdout: str, *extra: str) -> tuple[int, str]:
        bindir = Path(self._tmpdir())
        invoked = bindir / "invoked"
        uv = bindir / "uv"
        uv.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env python3
                import sys
                args = sys.argv[1:]
                if any(arg.endswith("affected_tests.py") for arg in args):
                    sys.stdout.write({stdout!r})
                    raise SystemExit(0)
                open({str(invoked)!r}, "w").write(" ".join(args))
                raise SystemExit(0)
                """
            ),
            encoding="utf-8",
        )
        timeout = bindir / "timeout"
        timeout.write_text(
            textwrap.dedent(
                """\
                #!/bin/sh
                while [ $# -gt 0 ]; do
                  case "$1" in
                    --kill-after=*) shift ;;
                    [0-9]*) shift; break ;;
                    *) shift ;;
                  esac
                done
                exec "$@"
                """
            ),
            encoding="utf-8",
        )
        uv.chmod(uv.stat().st_mode | stat.S_IEXEC)
        timeout.chmod(timeout.stat().st_mode | stat.S_IEXEC)
        env = os.environ.copy()
        env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
        result = subprocess.run(  # noqa: S603
            ["bash", str(_REPO / "scripts" / "test.sh"), "--affected", *extra],  # noqa: S607
            cwd=_REPO,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        recorded = invoked.read_text(encoding="utf-8") if invoked.exists() else ""
        return result.returncode, recorded

    def _tmpdir(self) -> str:
        import tempfile

        path = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(path, ignore_errors=True))
        return path

    def test_none_does_not_start_django(self):
        code, recorded = self._run("none\n")
        self.assertEqual(code, 0)
        self.assertEqual(recorded, "")

    def test_labels_use_the_targeted_exclude(self):
        code, recorded = self._run("labels\napp.tests.test_media\n")
        self.assertEqual(code, 0)
        self.assertIn("app.tests.test_media", recorded)
        self.assertIn("--exclude-tag", recorded)
        self.assertIn("network", recorded)
        self.assertNotIn("slow", recorded)

    def test_full_uses_the_fast_suite_excludes(self):
        code, recorded = self._run("full\n")
        self.assertEqual(code, 0)
        self.assertIn("--exclude-tag", recorded)
        self.assertIn("slow", recorded)
        self.assertIn("network", recorded)
        self.assertIn("src/manage.py", recorded)

    def test_include_slow_keeps_slow_tests_on_a_full_fallback(self):
        code, recorded = self._run("full\n", "--include-slow")
        self.assertEqual(code, 0)
        self.assertIn("network", recorded)
        self.assertNotIn("slow", recorded)
