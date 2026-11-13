"""Isolation, comparison quality and independent correctness contracts."""

import importlib.util
import json
import tempfile
from collections import Counter
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from app.benchmark_data import build_dataset

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "benchmark_matrix", ROOT / "scripts/benchmark_matrix.py"
)
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


class MatrixContractTests(SimpleTestCase):
    def test_explicit_application_comparison_still_requires_identical_method_and_runtime(
        self,
    ):
        original = {
            "protocol": harness.PROTOCOL,
            "eligible": True,
            "source_sha256": "old-source",
            "image": "old-image",
            "method_sha256": "method",
            "runtime_sha256": "runtime",
            "summary": {"cell": {"median": 1}},
        }
        changed = {**original, "source_sha256": "new-source", "image": "new-image"}
        self.assertFalse(harness.compatible(changed, original)["compatible"])
        self.assertTrue(
            harness.compatible(changed, original, code_change=True)["compatible"]
        )
        for key in ("method_sha256", "runtime_sha256"):
            incompatible = {**changed, key: "changed"}
            self.assertEqual(
                harness.compatible(incompatible, original, code_change=True)[
                    "mismatches"
                ],
                [key],
            )

    def test_idle_qualification_needs_two_quiet_samples_and_has_a_deadline(self):
        observations = [
            {"cpu_percent": n, "available_ram_bytes": 100} for n in (70, 10, 5)
        ]
        with patch.object(harness, "host_noise", side_effect=observations):
            result = harness.wait_for_idle(25, 30)
        self.assertTrue(result["qualified"])
        self.assertEqual(result["samples"], observations)
        with patch.object(harness, "host_noise", return_value=observations[0]):
            result = harness.wait_for_idle(25, 0)
        self.assertFalse(result["qualified"])
        self.assertEqual(len(result["samples"]), 1)

    def test_hosted_ci_is_rejected_even_with_dedicated_flag(self):
        self.assertFalse(
            harness.ci_allowed(
                {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted"}, True
            )
        )
        self.assertFalse(
            harness.ci_allowed(
                {"CI": "true", "RUNNER_ENVIRONMENT": "self-hosted"}, False
            )
        )
        self.assertTrue(
            harness.ci_allowed(
                {"CI": "true", "RUNNER_ENVIRONMENT": "self-hosted"}, True
            )
        )
        self.assertTrue(harness.ci_allowed({}, False))

    def test_comparison_withholds_ratios_for_noise_limits_inputs_and_images(self):
        report = {
            "protocol": harness.PROTOCOL,
            "source_sha256": "source",
            "image": "image",
            "postgres_image": "pg",
            "policy": {"cpu": 1},
            "host": {"ram": 10},
            "inputs": {"sha": "fixture"},
            "container_host": {"kernel": "test"},
            "docker_server_version": "test",
            "eligible": True,
            "summary": {"cell": {"median": 1}},
        }
        self.assertEqual(harness.compatible(report, report)["wall_ratios"], {"cell": 1})
        for key in (
            "protocol",
            "source_sha256",
            "image",
            "postgres_image",
            "policy",
            "host",
            "inputs",
            "container_host",
            "docker_server_version",
        ):
            changed = deepcopy(report)
            changed[key] = None
            comparison = harness.compatible(report, changed)
            self.assertFalse(comparison["compatible"])
            self.assertEqual(comparison["mismatches"], [key])
            self.assertEqual(comparison["wall_ratios"], {})
        noisy = {**report, "eligible": False}
        for current, old in ((noisy, report), (report, noisy)):
            self.assertEqual(
                harness.compatible(current, old)["mismatches"], ["quality_gate"]
            )

    def test_cleanup_checks_only_owned_containers_and_records_shutdown(self):
        from subprocess import CompletedProcess

        with (
            patch.object(
                harness.subprocess, "run", return_value=CompletedProcess([], 0)
            ) as run,
            patch.object(harness, "run", return_value="") as inventory,
        ):
            receipt = harness.cleanup_owned(
                {"application": "app-id", "postgresql": "pg-id"}
            )
        self.assertTrue(receipt["passed"])
        self.assertEqual(
            [e["event"] for e in receipt["events"]],
            ["service_shutdown_start", "cleanup_verified"],
        )
        self.assertEqual(run.call_count, 2)
        self.assertEqual(inventory.call_count, 2)
        self.assertEqual(set(receipt["containers"]), {"application", "postgresql"})
        with (
            patch.object(
                harness.subprocess, "run", return_value=CompletedProcess([], 0)
            ),
            patch.object(harness, "run", return_value="still-present"),
        ):
            self.assertFalse(
                harness.cleanup_owned({"application": "still-present"})["passed"]
            )

    def test_support_cpu_is_owned_and_vm_remainder_stays_unknown(self):
        counters = "usage_usec 123\nuser_usec 100\nVM\ncpu 1 2 3 4 5 6 7 8 9 10\nMEM\nMemAvailable: 42 kB\nPSI\nsome avg10=0 total=12"
        with patch.object(harness, "run", return_value=counters):
            result = harness.support_snapshot("owned-pg")
        self.assertEqual(result["cpu_usage_usec"], 123)
        self.assertEqual(result["memory_available_bytes"], 42 * 1024)
        self.assertEqual(result["vm_cpu_ticks"], list(range(1, 9)))
        self.assertIsNone(result["external_cpu_s"])
        self.assertIsNone(harness.support_snapshot(None)["cpu_usage_usec"])

    def test_actual_module_origin_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "scripts/work.py").write_text("pass")
            (root / "source-manifest.json").write_text(
                json.dumps({"scripts/work.py": "wrong"})
            )
            output = root / "origins.json"
            with (
                patch.object(harness, "ROOT", root),
                patch.object(harness.runpy, "run_path"),
            ):
                with self.assertRaises(RuntimeError):
                    harness.source_worker("work.py", [], output)
            receipt = json.loads(output.read_text())
            self.assertFalse(receipt["passed"])
            self.assertIn("scripts/work.py", receipt["failures"])

    def test_snapshot_excludes_runtime_data_untracked_files_and_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "source"
            files = {
                "src/code.py": "code",
                "src/db/private.json": "personal",
                ".env": "SECRET=private",
                "src/untracked.py": "private",
            }
            for name, data in files.items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(data)
            with patch.object(
                harness.subprocess,
                "check_output",
                return_value=b"src/code.py\0src/db/private.json\0.env\0",
            ):
                one, two = Path(directory) / "one", Path(directory) / "two"
                self.assertEqual(
                    harness.snapshot(root, one), harness.snapshot(root, two)
                )
                self.assertEqual(
                    [
                        p.relative_to(one).as_posix()
                        for p in one.rglob("*")
                        if p.is_file()
                    ],
                    ["source-manifest.json", "src/code.py"],
                )
                (root / "src/code.py").unlink()
                (root / "src/code.py").symlink_to(root / ".env")
                with self.assertRaises(ValueError):
                    harness.snapshot(root, Path(directory) / "three")


class MatrixCorrectnessTests(TestCase):
    def test_portable_fixture_is_independently_checked(self):
        models = build_dataset(20, 1729)
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "fixture.json.gz"
            checksum = harness.common.export_fixture(models, fixture)
            receipt = {
                "fixture_sha256": checksum,
                "size": 20,
                "seed": 1729,
                "counts": {
                    model._meta.label_lower: model.objects.count() for model in models
                },
            }
            result = harness.correctness("fixtures", receipt, fixture, 1729, 20)
            self.assertTrue(result["passed"])
            receipt["counts"]["users.user"] += 1
            with self.assertRaises(ValueError):
                harness.correctness("fixtures", receipt, fixture, 1729, 20)
            receipt["fixture_sha256"] = "wrong"
            with self.assertRaises(ValueError):
                harness.correctness("fixtures", receipt, fixture, 1729, 20)
