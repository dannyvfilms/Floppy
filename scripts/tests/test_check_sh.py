"""Focused tests for scripts/check.sh: a failing gate must fail the script.

The failure mode that matters is a gate script that prints a green summary
while a command failed. These tests stub the gates through the script's
override seams (UV/PYTHON/RUFF/TEST_SH) and assert the exit code plus the
FAIL result line.

Run: .venv/bin/python scripts/tests/test_check_sh.py
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "check.sh"


class CheckShTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="check-sh-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _shim(self, name: str, body: str):
        path = self.tmp / name
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(0o755)

    def _run(self, extra_env: dict, *args) -> subprocess.CompletedProcess:
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/tmp"),
            "CHECK_SKIP_SYNC": "1",
            "CHECK_SKIP_DJANGO": "1",
            "UV": str(self.tmp / "uv"),
            "PYTHON": str(self.tmp / "python"),
            "RUFF": str(self.tmp / "ruff"),
        }
        env.update(extra_env)
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
            check=False,
        )

    def test_a_failing_ruff_gate_fails_the_script(self):
        """The exact false-success these tests exist to prevent."""
        self._shim("python", "exit 0")
        self._shim("ruff", "echo 'simulated lint failure' >&2; exit 2")

        result = self._run({})

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ruff=FAIL(2)", result.stderr)
        self.assertIn("RESULT: FAIL", result.stderr)
        self.assertIn("simulated lint failure", result.stderr)

    def test_a_failing_mcp_gate_fails_the_script(self):
        self._shim("python", "exit 1")
        self._shim("ruff", "exit 0")

        result = self._run({})

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mcp=FAIL(1)", result.stderr)

    def test_a_failing_django_gate_fails_the_script(self):
        self._shim("python", "exit 0")
        self._shim("ruff", "exit 0")
        self._shim("test.sh", "exit 3")

        result = self._run(
            {"CHECK_SKIP_DJANGO": "0", "TEST_SH": str(self.tmp / "test.sh")}
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("django=FAIL(3)", result.stderr)

    def test_all_gates_passing_reports_pass_with_the_mode_summary(self):
        self._shim("python", "exit 0")
        self._shim("ruff", "exit 0")
        self._shim("test.sh", "exit 0")

        result = self._run(
            {
                "CHECK_SKIP_DJANGO": "0",
                "TEST_SH": str(self.tmp / "test.sh"),
                "FLOPPY_TEST_FAST_DB": "1",
            }
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("mcp=ok", result.stderr)
        self.assertIn("django-mode=fast-db", result.stderr)
        self.assertIn("network-excluded", result.stderr)
        self.assertIn("RESULT: PASS", result.stderr)

    def test_network_mode_is_reported_honestly(self):
        self._shim("python", "exit 0")
        self._shim("ruff", "exit 0")
        self._shim("test.sh", "exit 0")
        result = self._run(
            {"CHECK_SKIP_DJANGO": "0", "TEST_SH": str(self.tmp / "test.sh")},
            "--network",
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("network-enabled", result.stderr)
        self.assertNotIn("network-excluded", result.stderr)

    def test_skipped_django_does_not_claim_migration_replay(self):
        self._shim("python", "exit 0")
        self._shim("ruff", "exit 0")
        first = self._run({})
        second = self._run({})
        self.assertIn("django-mode=skipped", first.stderr)
        first_logs = next(line for line in first.stderr.splitlines() if "logs:" in line)
        second_logs = next(line for line in second.stderr.splitlines() if "logs:" in line)
        self.assertNotEqual(first_logs, second_logs)


if __name__ == "__main__":
    unittest.main()
