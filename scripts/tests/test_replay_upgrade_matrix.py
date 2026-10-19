"""Exercise upgrade orchestration with real Git refs and a stub database runner."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "replay_upgrade_matrix.sh"


class UpgradeReplayTests(unittest.TestCase):
    def test_head_upgrades_to_the_callers_commit_and_propagates_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)

            def git(*args):
                return subprocess.check_output(  # noqa: S603 -- fixed test arguments
                    ["git", *args],  # noqa: S607 -- exercise Git's normal PATH lookup
                    cwd=repo,
                    text=True,
                    stderr=subprocess.PIPE,
                ).strip()

            git("init", "--quiet")
            (repo / "src").mkdir()
            (repo / "src/.gitkeep").touch()
            git("add", "src/.gitkeep")
            git(
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.com",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "--quiet",
                "--allow-empty",
                "-m",
                "Old release",
            )
            old = git("rev-parse", "HEAD")
            git("tag", "old-release")
            git(
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.com",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "--quiet",
                "--allow-empty",
                "-m",
                "Candidate",
            )
            candidate = git("rev-parse", "HEAD")
            (repo / "scripts").mkdir()
            (repo / "scripts/upgrade_fixture.py").write_text("")
            bin_dir = repo / "bin"
            bin_dir.mkdir()
            uv = bin_dir / "uv"
            uv.write_text(
                "#!/bin/sh\n"
                'git rev-parse HEAD >> "$REPLAY_CALLS"\n'
                '[ "$(git rev-parse HEAD)" != "$FAIL_REF" ]\n'
            )
            uv.chmod(0o755)
            calls = repo / "calls"
            environment = {
                **os.environ,
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "REPLAY_CALLS": str(calls),
                "FAIL_REF": "",
            }
            arguments = [
                "bash",
                str(SCRIPT),
                "--from-tag",
                "old-release",
                "--to-ref",
                "HEAD",
                "--db",
                "sqlite",
            ]
            result = subprocess.run(  # noqa: S603 -- local fixture and script
                arguments,
                cwd=repo,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            refs = calls.read_text().splitlines()
            self.assertEqual(refs[:2], [old, old])
            self.assertTrue(refs[2:])
            self.assertEqual(set(refs[2:]), {candidate})

            environment["FAIL_REF"] = candidate
            result = subprocess.run(  # noqa: S603 -- local fixture and script
                arguments,
                cwd=repo,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("Upgrade replay matrix passed", result.stdout)
