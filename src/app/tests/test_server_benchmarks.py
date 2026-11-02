"""Privacy and attribution contracts for the opt-in server benchmark."""

import importlib.util
import json
import logging
import os
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from django.test import SimpleTestCase, tag

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "benchmark_server", ROOT / "scripts/benchmark_server.py"
)
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


class ServerBenchmarkContractTests(SimpleTestCase):
    def test_log_capture_only_retains_numeric_allowlist(self):
        handler = harness.RequestMetrics()
        record = logging.LogRecord(
            "app.middleware",
            logging.INFO,
            "",
            0,
            "slow_request path=/private?token=secret queries=3 duration_ms=1.5 db_ms=0.2",
            (),
            None,
        )
        handler.emit(record)
        self.assertEqual(
            handler.samples, [{"queries": 3.0, "duration_ms": 1.5, "db_ms": 0.2}]
        )
        self.assertNotIn("secret", json.dumps(handler.samples))

    def test_explain_exports_no_predicates_identifiers_or_literals(self):
        sqlite = harness.plan_summary(
            "sqlite", [(2, 0, 0, "SEARCH private_table USING INDEX secret (token=?)")]
        )
        self.assertEqual(sqlite, [{"id": 2, "parent": 0, "operation": "SEARCH"}])
        postgres = harness.plan_summary(
            "postgresql",
            [
                (
                    [
                        {
                            "Plan": {
                                "Node Type": "Index Scan",
                                "Total Cost": 12.5,
                                "Filter": "token = 'secret'",
                                "Relation Name": "private_table",
                                "Plans": [
                                    {"Node Type": "Result", "Output": ["secret"]}
                                ],
                            }
                        }
                    ],
                )
            ],
        )
        self.assertEqual(
            postgres,
            {
                "Node Type": "Index Scan",
                "Total Cost": 12.5,
                "Plans": [{"Node Type": "Result", "Plans": []}],
            },
        )
        self.assertNotIn("secret", json.dumps(postgres))

    def test_comparison_rejects_incompatible_inputs(self):
        report = {
            "protocol": harness.PROTOCOL,
            "machine": {"ram": 10},
            "sources": {"script": "sha"},
            "scenario": {"seed": 1729},
            "summary": {"movie": {"wall_s": {"median": 0.1}}},
        }
        self.assertEqual(
            harness.comparison(report, report)["wall_ratios"], {"movie": 1}
        )
        for key in ("protocol", "machine", "sources", "scenario"):
            previous = deepcopy(report)
            previous[key] = None
            comparison = harness.comparison(report, previous)
            self.assertFalse(comparison["compatible"])
            self.assertEqual(comparison["mismatches"], [key])
            self.assertEqual(comparison["wall_ratios"], {})

    def test_variance_retains_raw_range_and_sample_count(self):
        result = harness.summarize([1, 2, 3])
        self.assertEqual(
            result, {"n": 3, "median": 2, "min": 1, "max": 3, "cv_pct": 50}
        )


@tag("slow", "benchmark")
class ServerBenchmarkIntegrationTests(SimpleTestCase):
    def test_controlled_sqlite_lock_has_known_owner_but_no_native_wait_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "locks.sqlite3"
            samples = harness.lock_trials(path, 2)
            self.assertFalse(path.exists())
        self.assertEqual(len(samples), 6)
        for sample in samples:
            self.assertIsNone(sample["native_busy_sleep_s"])
            self.assertGreaterEqual(sample["execution_s"], sample["writer_overlap_s"])
            if sample["scenario"] == "timeout":
                self.assertEqual(sample["kind"], "busy")
                self.assertEqual(sample["sqlite_code"], 5)
                self.assertGreater(sample["failed_execution_ms"], 0)
            else:
                self.assertEqual(sample["outcome"], "ok")

    @unittest.skipUnless(
        os.environ.get("RUN_SERVER_BENCHMARKS") == "1",
        "opt-in disposable request benchmark",
    )
    def test_disposable_requests_profiles_and_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "run"
            result = subprocess.run(  # noqa: S603 -- fixed script and controlled CLI
                [
                    sys.executable,
                    str(ROOT / "scripts/benchmark_server.py"),
                    "--size",
                    "20",
                    "--runs",
                    "2",
                    "--routes",
                    "movies",
                    "history",
                    "--profile",
                    "--output",
                    str(target),
                ],
                cwd=ROOT,
                env={**os.environ, "PYTHONHASHSEED": "0"},
                check=False,
                capture_output=True,
                text=True,
                timeout=180,
            )
            self.assertEqual(result.returncode, 0, result.stderr[-3000:])
            report = json.loads((target / "report.json").read_text())
            self.assertTrue((target / "report.md").exists())
            self.assertEqual(len(set(report["scenario"]["fixtures"])), 1)
            for receipt in report["receipts"]:
                self.assertEqual(len(receipt["samples"]), 16)
                self.assertFalse(list(target.rglob("*.sqlite3")))
                for sample in receipt["samples"]:
                    self.assertEqual(sample["status"], 200)
                    if sample["mode"] == "enabled":
                        self.assertGreater(sample["middleware"]["queries"], 0)
                        self.assertIn("db;dur=", sample["server_timing"])
                    else:
                        self.assertIsNone(sample["middleware"])
                        self.assertIsNone(sample["server_timing"])
                for profile in receipt["profiles"].values():
                    self.assertTrue(profile["plans"])
                    self.assertTrue(profile["sql_profile"]["queries"])
            serialized = json.dumps(report)
            for secret in (str(ROOT), "bench-only-disabled", "sessionid", "SELECT "):
                self.assertNotIn(secret, serialized)
