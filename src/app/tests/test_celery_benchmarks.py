"""Contracts and optional real-worker integration for BENCH-05 tracing."""

import contextlib
import importlib.util
import json
import logging
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, TestCase, override_settings, tag
from django_celery_beat.models import IntervalSchedule, PeriodicTask

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "benchmark_celery", ROOT / "scripts/benchmark_celery.py"
)
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)
from scripts import celery_trace as trace  # noqa: E402


class CeleryTraceContractTests(SimpleTestCase):
    @override_settings(PERF_LOG_ENABLED=False)
    def test_failed_result_handles_detach_before_private_backend_shutdown(self):
        futures = [Mock() for _ in harness.plan(1729)]
        backends = [future.backend for future in futures]
        futures[0].get.side_effect = RuntimeError("synthetic failed result")
        work = Mock()
        work.apply_async.side_effect = futures
        with (
            patch(
                "celery.contrib.testing.worker.start_worker",
                return_value=contextlib.nullcontext(),
            ),
            patch("django.db.connections.close_all"),
            self.assertRaises(RuntimeError),
        ):
            harness.exercise(
                SimpleNamespace(provider_ms=40),
                Mock(),
                Mock(),
                work,
                harness.plan(1729),
                False,
            )
        for future, backend in zip(futures, backends, strict=True):
            backend.remove_pending_result.assert_called_once_with(future)
            self.assertIsNone(future.backend)

    def test_deterministic_plan_changes_with_seed(self):
        self.assertEqual(harness.plan(1729), harness.plan(1729))
        self.assertNotEqual(harness.plan(1729), harness.plan(1730))
        self.assertEqual(sum(job["retry_once"] for job in harness.plan(1729)), 1)
        self.assertEqual(len({job["job"] for job in harness.plan(1729)}), 6)

    def test_correlation_keeps_retry_attempts_and_overlap_without_pids(self):
        def event(name, job, attempt, at, **kw):
            return {"event": name, "job": job, "attempt": attempt, "at_s": at, **kw}

        events = [
            event("enqueue", "one", 0, 0),
            event("published", "one", 0, 0.2),
            event("start", "one", 0, 0.1, worker_pid=123),
            event("retry", "one", 0, 2.5),
            event("end", "one", 0, 3, state="RETRY", worker_pid=123),
            event("enqueue", "two", 0, 1),
            event("published", "two", 0, 1.1),
            event("start", "two", 0, 2, worker_pid=456),
            event("end", "two", 0, 4, state="SUCCESS", worker_pid=456),
            event("enqueue", "one", 1, 2.4),
            event("published", "one", 1, 2.6),
            event("start", "one", 1, 4),
            event("end", "one", 1, 5, state="SUCCESS"),
        ]
        result = trace.correlate(list(reversed(events)))
        self.assertEqual(len(result["attempts"]), 3)
        self.assertEqual(result["worker_count"], 2)
        self.assertEqual(result["incomplete_attempts"], 0)
        self.assertEqual(result["overlap"][0]["seconds"], 1)
        self.assertEqual(result["attempts"][0]["queue_delay_s"], 0.1)
        self.assertEqual(result["attempts"][0]["broker_return_to_start_s"], -0.1)
        self.assertNotIn("worker_pid", json.dumps(result))
        self.assertEqual(
            result["event_checksum"], trace.correlate(events)["event_checksum"]
        )

    def test_missing_and_duplicate_boundaries_are_explicit(self):
        event = {"event": "enqueue", "job": "one", "attempt": 0, "at_s": 0}
        result = trace.correlate([event, event])
        self.assertEqual(result["incomplete_attempts"], 1)
        self.assertEqual(result["duplicate_attempts"], 1)
        self.assertIsNone(result["attempts"][0]["queue_delay_s"])
        self.assertEqual(result["attempts"][0]["duplicate_events"], {"enqueue": 2})

    def test_static_creation_inventory_retains_unresolved_without_argument_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "src/schedules.py").write_text(
                'def schedule(user):\n    PeriodicTask.objects.create(task=f"Import {user}", name="private", kwargs="secret")\n'
            )
            rows = trace.schedule_sites(root)
        self.assertEqual(rows[0]["function"], "schedule")
        self.assertEqual(rows[0]["line"], 2)
        self.assertFalse(rows[0]["task_resolved"])
        self.assertIsNone(rows[0]["task_literal"])
        self.assertNotIn("secret", json.dumps(rows))
        self.assertNotIn("private", json.dumps(rows))

    def test_publish_only_records_synthetic_identity_not_body(self):
        redis = Mock()
        observer = trace.Trace(redis, 0)
        observer.publish(
            sender="bench05.work",
            headers={"id": "synthetic", "retries": 1, "token": "secret"},
            body={"private": "secret"},
        )
        event = json.loads(redis.rpush.call_args.args[1])
        self.assertEqual(event["attempt"], 1)
        self.assertNotIn("secret", json.dumps(event))
        redis.reset_mock()
        observer.publish(sender="real.task", headers={"id": "private"})
        redis.rpush.assert_not_called()

    def test_existing_diagnostic_capture_exports_only_numeric_fields(self):
        observer = trace.Trace(Mock(), 0)
        observer.identity = Mock(return_value=("synthetic", 1))
        observer.emit(
            logging.LogRecord(
                "app.memory_envelope",
                logging.INFO,
                "",
                0,
                "slow_task name=bench05.work task_id=synthetic state=RETRY queries=2 provider_calls=1 db_ms=3.5 private=secret",
                (),
                None,
            )
        )
        event = json.loads(observer.redis.rpush.call_args.args[1])
        self.assertEqual(
            event["metrics"], {"queries": 2, "provider_calls": 1, "db_ms": 3.5}
        )
        self.assertNotIn("secret", json.dumps(event))
        self.assertIsNone(
            trace.Trace.identity(SimpleNamespace(name="other", request=None))
        )


class CeleryScheduleInventoryTests(TestCase):
    @override_settings(
        CELERY_BEAT_SCHEDULE={
            "static": {
                "task": "bench05.work",
                "schedule": 60,
                "kwargs": {"token": "secret"},
            }
        }
    )
    def test_dynamic_rows_exclude_user_names_args_headers_and_descriptions(self):
        interval = IntervalSchedule.objects.create(every=10, period="minutes")
        PeriodicTask.objects.create(
            name="private-user",
            task="bench05.work",
            interval=interval,
            kwargs='{"token":"secret"}',
            headers='{"token":"secret"}',
            description="private description",
            enabled=False,
        )
        result = trace.inventory(ROOT)
        self.assertEqual(
            result["static"][0]["cadence"], {"kind": "interval", "seconds": 60}
        )
        self.assertEqual(
            result["dynamic"][0]["cadence"],
            {"kind": "interval", "every": 10, "period": "minutes"},
        )
        self.assertFalse(result["dynamic"][0]["enabled"])
        for private in ("secret", "private-user", "private description"):
            self.assertNotIn(private, json.dumps(result))


@tag("slow", "benchmark")
class CeleryBenchmarkIntegrationTests(SimpleTestCase):
    @unittest.skipUnless(
        os.environ.get("RUN_CELERY_BENCHMARKS") == "1",
        "opt-in Redis/prefork integration",
    )
    def test_real_retry_overlap_resources_and_disposable_output(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "run"
            completed = subprocess.run(  # noqa: S603 -- fixed interpreter/script and controlled arguments
                [
                    sys.executable,
                    str(ROOT / "scripts/benchmark_celery.py"),
                    "--size",
                    "20",
                    "--output",
                    str(target),
                ],
                cwd=ROOT,
                env={**os.environ, "PYTHONHASHSEED": "0"},
                capture_output=True,
                text=True,
                check=False,
                timeout=180,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr[-3000:])
            self.assertNotIn("Exception ignored", completed.stderr)
            report = json.loads((target / "report.json").read_text())
            self.assertTrue((target / "report.md").exists())
            self.assertEqual(len(set(report["scenario"]["fixtures"])), 1)
            self.assertFalse(list(target.rglob("*.sqlite3")))
            for receipt in report["receipts"]:
                enabled = next(
                    m for m in receipt["measurements"] if m["mode"] == "enabled"
                )
                traced = enabled["trace"]
                self.assertEqual(traced["worker_count"], 2)
                self.assertEqual(traced["incomplete_attempts"], 0)
                self.assertEqual(traced["duplicate_attempts"], 0)
                self.assertEqual(len(traced["attempts"]), 7)
                self.assertEqual(
                    sum(a["state"] == "RETRY" for a in traced["attempts"]), 1
                )
                self.assertTrue(traced["overlap"])
                ends = [
                    e
                    for a in traced["attempts"]
                    for e in a["events"]
                    if e["event"] == "end"
                ]
                self.assertEqual(sum(e["provider_calls"] for e in ends), 9)
                for attempt in traced["attempts"]:
                    self.assertGreaterEqual(attempt["queue_delay_s"], 0)
                    self.assertTrue(
                        any(e["event"] == "diagnostic" for e in attempt["events"])
                    )
                    end = next(e for e in attempt["events"] if e["event"] == "end")
                    self.assertGreater(end["thread_cpu_s"], 0)
                    self.assertIsNotNone(end["memory_bytes"]["rss"])
            for private in (
                str(ROOT),
                "sessionid",
                "bench-only-disabled",
                "worker_pid",
                "provider.invalid",
            ):
                self.assertNotIn(private, json.dumps(report))
