"""Tests for scripts/merge_train_ui.py with real Git repositories.

The npm build is replaced by a deterministic stand-in: the bundle name is a hash of
the frontend sources, so a merged source tree always yields one correct bundle set.
"""

# ruff: noqa: S603, S607
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "merge_train_ui.py"
_spec = importlib.util.spec_from_file_location("merge_train_ui", _SCRIPT)
ui = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ui
_spec.loader.exec_module(ui)

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull,
}


def fake_build(repo: Path) -> None:
    """Write bundles named after the hash of the frontend sources."""
    digest = hashlib.sha256()
    for path in sorted((repo / "frontend").rglob("*")):
        if path.is_file():
            digest.update(path.name.encode() + path.read_bytes())
    out = repo / "src" / "static" / "ui"
    out.mkdir(parents=True, exist_ok=True)
    tag = digest.hexdigest()[:8]
    (out / f"settings-islands-{tag}.js").write_text(f"bundle {tag}\n")
    (out / f"chunk-{tag}.js").write_text(f"chunk {tag}\n")
    (out / "markdown-islands.js").write_text(
        f"entry {tag}\n"
    )  # fixed name: both sides edit it


class GitCase(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        patcher = patch.dict(os.environ, GIT_ENV)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.origin = self.root / "origin.git"
        subprocess.run(
            ["git", "init", "-q", "--bare", "-b", "latest", self.origin], check=True
        )
        self.seed = self.root / "seed"
        subprocess.run(
            ["git", "clone", "-q", self.origin, self.seed],
            check=True,
            capture_output=True,
        )
        self.git(self.seed, "checkout", "-q", "-b", "latest")
        self.write(self.seed, "frontend/a.js", "a1\n")
        self.write(self.seed, "frontend/b.js", "b1\n")
        self.write(self.seed, "src/app/views.py", "v1\n")
        fake_build(self.seed)
        self.git(self.seed, "add", "-A")
        self.git(self.seed, "commit", "-q", "-m", "base")
        self.git(self.seed, "push", "-q", "origin", "latest")
        self.base_commit = self.rev(self.seed)

    def git(self, repo, *args):
        return subprocess.run(
            ["git", *args], cwd=repo, check=True, capture_output=True, text=True
        ).stdout

    def rev(self, repo, ref="HEAD"):
        return self.git(repo, "rev-parse", ref).strip()

    def write(self, repo, path, text):
        target = Path(repo) / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def commit_all(self, repo, message, rebuild=True):
        if rebuild:
            shutil.rmtree(Path(repo) / "src/static/ui", ignore_errors=True)
            fake_build(Path(repo))
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-q", "-m", message)
        return self.rev(repo)

    def make_branches(self, pr_edit, latest_edit):
        """Return (pr head, latest) after each side edits from the common base."""
        self.git(self.seed, "checkout", "-q", "-b", "pr", self.base_commit)
        pr_edit(self.seed)
        head = self.commit_all(self.seed, "pr")
        self.git(self.seed, "push", "-q", "origin", "pr")
        self.git(self.seed, "checkout", "-q", "latest")
        latest_edit(self.seed)
        base = self.commit_all(self.seed, "latest")
        self.git(self.seed, "push", "-q", "origin", "latest")
        return head, base

    def checkout_for_build(self, head):
        work = self.root / "work"
        subprocess.run(
            ["git", "clone", "-q", self.origin, work], check=True, capture_output=True
        )
        self.git(work, "checkout", "-q", "--detach", head)
        return work

    def run_build(self, head, base):
        work = self.checkout_for_build(head)
        out = self.root / "ui-1"
        with patch.object(ui, "run_build", fake_build):
            result = ui.build(work, out, 1, head, base)
        return result, out

    def publish(self, head, base, artifacts_dir=None, check=None):
        entry = {"number": 1, "branch": "pr", "head": head, "base": base}
        with (
            patch.object(ui, "check_current", check or (lambda *_: None)),
            patch.object(ui, "_auth_env", lambda _t: {}),
        ):
            return ui.publish_one(
                "o/r",
                "t",
                entry,
                artifacts_dir or self.root,
                push_env={},
                remote_url=str(self.origin),
            )

    def pushed_tree(self, ref="pr"):
        return {
            p: self.git(self.origin, "show", f"{ref}:{p}")
            for p in self.git(self.origin, "ls-tree", "-r", "--name-only", ref).split()
        }


class BuildTests(GitCase):
    def test_both_sides_rebuilt_bundles_conflict_only_in_generated_output(self):
        head, base = self.make_branches(
            lambda r: self.write(r, "frontend/a.js", "a-pr\n"),
            lambda r: self.write(r, "frontend/b.js", "b-latest\n"),
        )
        result, out = self.run_build(head, base)
        self.assertEqual(result["status"], "ok", result)
        names = {m["name"] for m in result["files"]}
        self.assertEqual(len(names), 3)  # one bundle set, no stale chunks
        self.assertTrue(all(p.name in names for p in (out / "files").iterdir()))

    def test_clean_merge_with_overlapping_builds_still_gets_consistent_bundles(self):
        """No conflict, yet each side's bundle is stale for the merged source."""
        head, base = self.make_branches(
            lambda r: self.write(r, "frontend/a.js", "a-pr\n"),
            lambda r: self.write(r, "frontend/b.js", "b-latest\n"),
        )
        result, _ = self.run_build(head, base)
        expected = self.root / "expected"
        subprocess.run(
            ["git", "clone", "-q", self.origin, expected],
            check=True,
            capture_output=True,
        )
        self.git(expected, "checkout", "-q", "--detach", head)
        self.git(expected, "merge", "-q", "--no-edit", "--no-ff", base, "-X", "theirs")
        self.write(expected, "src/static/ui/.keep", "")
        shutil.rmtree(expected / "src/static/ui")
        fake_build(expected)
        self.assertEqual(
            {m["name"] for m in result["files"]},
            {p.name for p in (expected / "src/static/ui").iterdir()},
        )

    def test_content_conflict_in_a_generated_file_is_resolved(self):
        head, base = self.make_branches(
            lambda r: self.write(r, "frontend/a.js", "a-pr\n"),
            lambda r: self.write(r, "frontend/b.js", "b-latest\n"),
        )
        scratch = self.root / "scratch"
        subprocess.run(
            ["git", "clone", "-q", self.origin, scratch],
            check=True,
            capture_output=True,
        )
        self.git(scratch, "checkout", "-q", "--detach", head)
        merge = subprocess.run(
            ["git", "merge", "--no-commit", "--no-ff", base],
            cwd=scratch,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(
            merge.returncode, 0
        )  # a real conflict, in markdown-islands.js
        result, _ = self.run_build(head, base)
        self.assertEqual(result["status"], "ok", result)

    def test_added_and_deleted_hashed_chunks_are_resolved(self):
        """The PR deletes a chunk latest edited, and each side adds its own."""
        self.git(self.seed, "checkout", "-q", "latest")
        self.write(self.seed, "src/static/ui/old-chunk.js", "old\n")
        self.commit_all(self.seed, "add old chunk", rebuild=False)
        self.git(self.seed, "push", "-q", "origin", "latest")
        self.base_commit = self.rev(self.seed)

        def pr_edit(repo):
            self.write(repo, "frontend/a.js", "a-pr\n")

        head, base = self.make_branches(
            pr_edit, lambda r: self.write(r, "frontend/b.js", "b-latest\n")
        )
        self.git(self.seed, "checkout", "-q", "latest")
        self.git(self.seed, "reset", "-q", "--hard", self.base_commit)
        self.write(self.seed, "src/static/ui/old-chunk.js", "old edited by latest\n")
        self.write(self.seed, "frontend/b.js", "b-latest\n")
        self.git(self.seed, "add", "-A")
        self.git(self.seed, "commit", "-q", "-m", "latest edits old chunk")
        self.git(self.seed, "push", "-q", "-f", "origin", "latest")
        base = self.rev(self.seed)
        result, out = self.run_build(head, base)
        self.assertEqual(result["status"], "ok", result)
        self.assertNotIn("old-chunk.js", {m["name"] for m in result["files"]})

    def test_source_conflict_stays_manual_even_beside_generated_ones(self):
        head, base = self.make_branches(
            lambda r: self.write(r, "frontend/a.js", "a-pr\n"),
            lambda r: self.write(r, "frontend/a.js", "a-latest\n"),
        )
        result, _ = self.run_build(head, base)
        self.assertEqual(result["status"], "failed")
        self.assertIn("frontend/a.js", result["reason"])

    def test_mixed_source_and_generated_conflict_is_left_manual(self):
        head, base = self.make_branches(
            lambda r: self.write(r, "src/app/views.py", "pr\n"),
            lambda r: self.write(r, "src/app/views.py", "latest\n"),
        )
        result, _ = self.run_build(head, base)
        self.assertEqual(result["status"], "failed")
        self.assertIn("conflicts outside src/static/ui/", result["reason"])

    def test_migration_conflict_is_never_resolved(self):
        head, base = self.make_branches(
            lambda r: self.write(r, "src/app/migrations/0100_a.py", "pr\n"),
            lambda r: self.write(r, "src/app/migrations/0100_a.py", "latest\n"),
        )
        result, _ = self.run_build(head, base)
        self.assertEqual(result["status"], "failed")

    def test_build_that_modifies_source_fails(self):
        head, base = self.make_branches(
            lambda r: self.write(r, "frontend/a.js", "a-pr\n"),
            lambda r: self.write(r, "frontend/b.js", "b-latest\n"),
        )
        work = self.checkout_for_build(head)

        def bad_build(repo):
            fake_build(repo)
            (repo / "package-lock.json").write_text("changed")

        with patch.object(ui, "run_build", bad_build):
            result = ui.build(work, self.root / "o", 1, head, base)
        self.assertEqual(result["status"], "failed")
        self.assertIn("modified source", result["reason"])

    def test_build_failure_is_reported_not_raised(self):
        head, base = self.make_branches(
            lambda r: self.write(r, "frontend/a.js", "a-pr\n"),
            lambda r: self.write(r, "frontend/b.js", "b-latest\n"),
        )
        work = self.checkout_for_build(head)

        def broken(_repo):
            raise ui.RefreshError("`npm run check:ui` failed: boom")

        with patch.object(ui, "run_build", broken):
            result = ui.build(work, self.root / "o", 1, head, base)
        self.assertEqual(result["status"], "failed")
        self.assertIn("boom", result["reason"])


class PublishTests(GitCase):
    def setUp(self):
        super().setUp()
        self.head, self.base = self.make_branches(
            lambda r: self.write(r, "frontend/a.js", "a-pr\n"),
            lambda r: self.write(r, "frontend/b.js", "b-latest\n"),
        )
        self.result, self.out = self.run_build(self.head, self.base)
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir()
        subprocess.run(
            ["cp", "-R", str(self.out), str(self.artifacts / "ui-1")], check=True
        )

    def publish_artifact(self, **kw):
        return self.publish(self.head, self.base, self.artifacts, **kw)

    def test_publishes_one_merge_commit_with_head_and_latest_as_parents(self):
        self.publish_artifact()
        self.assertEqual(
            self.git(self.origin, "rev-list", "--parents", "-n1", "pr").split()[1:],
            [self.head, self.base],
        )
        tree = self.pushed_tree()
        self.assertEqual(tree["frontend/a.js"], "a-pr\n")  # PR source kept
        self.assertEqual(tree["frontend/b.js"], "b-latest\n")  # latest source kept
        bundles = {p for p in tree if p.startswith("src/static/ui/")}
        self.assertEqual(
            {Path(p).name for p in bundles}, {m["name"] for m in self.result["files"]}
        )

    def test_unchanged_latest_branch_is_never_touched(self):
        before = self.rev(self.origin, "latest")
        self.publish_artifact()
        self.assertEqual(self.rev(self.origin, "latest"), before)
        refs = self.git(self.origin, "for-each-ref", "--format=%(refname)").split()
        self.assertEqual(sorted(refs), ["refs/heads/latest", "refs/heads/pr"])

    def test_tampered_artifacts_are_rejected(self):
        name = sorted(p.name for p in (self.artifacts / "ui-1" / "files").iterdir())[0]
        for label in ("content", "extra", "type", "dir", "link"):
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                copy = Path(tmp) / "ui-1"
                subprocess.run(
                    ["cp", "-R", str(self.artifacts / "ui-1"), str(copy)], check=True
                )
                tampered = Path(tmp) / "a"
                tampered.mkdir()
                copy.rename(tampered / "ui-1")
                files_dir = tampered / "ui-1" / "files"
                if label == "content":
                    (files_dir / name).write_text("evil")
                elif label == "extra":
                    (files_dir / "extra.js").write_text("x")
                elif label == "type":
                    (files_dir / "run.sh").write_text("x")
                elif label == "dir":
                    (files_dir / "sub").mkdir()
                else:
                    (files_dir / "l.js").symlink_to("/etc/passwd")
                with self.assertRaises(ui.RefreshError):
                    self.publish(self.head, self.base, tampered)
        self.assertEqual(self.rev(self.origin, "pr"), self.head)

    def test_artifact_built_from_different_source_is_rejected(self):
        result = json.loads((self.artifacts / "ui-1" / "result.json").read_text())
        result["source_tree"] = "0" * 40
        (self.artifacts / "ui-1" / "result.json").write_text(json.dumps(result))
        with self.assertRaisesRegex(ui.RefreshError, "differs"):
            self.publish_artifact()
        self.assertEqual(self.rev(self.origin, "pr"), self.head)

    def test_result_for_another_head_is_rejected(self):
        with self.assertRaisesRegex(ui.RefreshError, "different head"):
            self.publish("f" * 40, self.base, self.artifacts)

    def test_failed_build_is_not_published(self):
        (self.artifacts / "ui-1" / "result.json").write_text(
            json.dumps({"status": "failed", "reason": "boom"})
        )
        with self.assertRaisesRegex(ui.RefreshError, "boom"):
            self.publish_artifact()
        self.assertEqual(self.rev(self.origin, "pr"), self.head)

    def test_missing_result_is_not_published(self):
        with self.assertRaisesRegex(ui.RefreshError, "no result"):
            self.publish(self.head, self.base, self.root / "empty")

    def test_newer_agent_push_is_never_overwritten(self):
        self.git(self.seed, "checkout", "-q", "pr")
        self.write(self.seed, "frontend/new.js", "agent\n")
        newer = self.commit_all(self.seed, "agent push", rebuild=False)
        self.git(self.seed, "push", "-q", "origin", "pr")
        with self.assertRaises(ui.RefreshError):
            self.publish_artifact()
        self.assertEqual(self.rev(self.origin, "pr"), newer)

    def test_lost_eligibility_or_moved_latest_stops_before_any_push(self):
        def stale(*_):
            raise ui.StaleError("latest moved")

        with self.assertRaises(ui.StaleError):
            self.publish_artifact(check=stale)
        self.assertEqual(self.rev(self.origin, "pr"), self.head)

    def test_one_failed_pr_does_not_stop_the_others(self):
        plan = [
            {"number": 7, "branch": "x", "head": "a" * 40, "base": "b" * 40},
            {"number": 1, "branch": "pr", "head": self.head, "base": self.base},
        ]
        with (
            patch.object(ui, "check_current", lambda *_: None),
            patch.object(ui, "_auth_env", lambda _t: {}),
            patch.object(ui, "_comment") as comment,
            patch.object(ui, "_delete_comment"),
            patch.object(
                ui, "publish_one", side_effect=[ui.RefreshError("boom"), "#1 refreshed"]
            ),
        ):
            lines, failed = ui.publish(plan, self.artifacts, "o/r", "t")
        self.assertTrue(failed)
        self.assertEqual(len(lines), 2)
        self.assertIn(
            f"merge-train-ui:{'a' * 40}:{'b' * 40}:failed", comment.call_args.args[2]
        )
