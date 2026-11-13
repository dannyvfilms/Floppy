# ruff: noqa: INP001 -- opt-in benchmark helper, never imported by production
"""Privacy-safe schedule inventory and Celery attempt tracing for BENCH-05."""

import ast
import contextlib
import hashlib
import json
import logging
import os
import re
import time
from collections import Counter

from scripts import benchmark_fixtures as common

PREFIX = "bench05."


def schedule_sites(root):
    """Inventory direct PeriodicTask creation sites; expose no argument values."""
    sites = []
    for path in sorted((root / "src").rglob("*.py")):
        if {"tests", "migrations"}.intersection(path.parts):
            continue
        tree = ast.parse(path.read_text())

        def visit(node, scope="module", path=path):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                scope = node.name
            if isinstance(node, ast.Call):
                target = ast.unparse(node.func)
                if target in {
                    "PeriodicTask.objects.create",
                    "PeriodicTask.objects.get_or_create",
                    "PeriodicTask.objects.update_or_create",
                    "PeriodicTask.objects.bulk_create",
                }:
                    task = next(
                        (kw.value for kw in node.keywords if kw.arg == "task"), None
                    )
                    sites.append(
                        {
                            "source": str(path.relative_to(root)),
                            "line": node.lineno,
                            "function": scope,
                            "operation": target,
                            "task_literal": task.value
                            if isinstance(task, ast.Constant)
                            and isinstance(task.value, str)
                            else None,
                            "task_resolved": isinstance(task, ast.Constant)
                            and isinstance(task.value, str),
                            "fields": sorted(
                                kw.arg
                                for kw in node.keywords
                                if kw.arg is not None
                                and kw.arg
                                not in {
                                    "args",
                                    "kwargs",
                                    "headers",
                                    "name",
                                    "description",
                                }
                            ),
                        }
                    )
            for child in ast.iter_child_nodes(node):
                visit(child, scope)

        visit(tree)
    return sites


def cadence(value):
    """Describe a static schedule without representations containing addresses."""
    if isinstance(value, (float, int)):
        return {"kind": "interval", "seconds": float(value)}
    if hasattr(value, "_orig_minute"):
        return {
            "kind": "crontab",
            **{
                name: str(getattr(value, "_orig_" + name))
                for name in (
                    "minute",
                    "hour",
                    "day_of_week",
                    "day_of_month",
                    "month_of_year",
                )
            },
        }
    if hasattr(value, "run_every"):
        return {"kind": "interval", "seconds": value.run_every.total_seconds()}
    return {"kind": type(value).__name__, "details": "unavailable"}


def inventory(root):
    """Inspect configured static schedules and only this disposable database."""
    from django.conf import settings
    from django_celery_beat.models import PeriodicTask

    static = [
        {
            "entry": name,
            "task": entry["task"],
            "cadence": cadence(entry["schedule"]),
            "queue": entry.get("options", {}).get("queue"),
            "has_arguments": bool(entry.get("args") or entry.get("kwargs")),
        }
        for name, entry in sorted(settings.CELERY_BEAT_SCHEDULE.items())
    ]
    dynamic = []
    for index, task in enumerate(
        PeriodicTask.objects.select_related(
            "interval", "crontab", "clocked", "solar"
        ).order_by("pk"),
        1,
    ):
        timing = {"kind": "unavailable"}
        if task.interval_id:
            timing = {
                "kind": "interval",
                "every": task.interval.every,
                "period": task.interval.period,
            }
        elif task.crontab_id:
            timing = {
                "kind": "crontab",
                **{
                    key: str(getattr(task.crontab, key))
                    for key in (
                        "minute",
                        "hour",
                        "day_of_week",
                        "day_of_month",
                        "month_of_year",
                        "timezone",
                    )
                },
            }
        elif task.clocked_id:
            timing = {"kind": "clocked", "at": task.clocked.clocked_time.isoformat()}
        elif task.solar_id:
            timing = {"kind": "solar", "location_omitted": True}
        dynamic.append(
            {
                "schedule": f"dynamic-{index}",
                "task": task.task,
                "cadence": timing,
                "enabled": task.enabled,
                "one_off": task.one_off,
                "queue": task.queue,
                "has_arguments": task.args != "[]" or task.kwargs != "{}",
            }
        )
    return {
        "static": static,
        "dynamic": dynamic,
        "creation_sites": schedule_sites(root),
        "routes": {
            key: value.get("queue")
            for key, value in sorted(settings.CELERY_TASK_ROUTES.items())
        },
        "notes": [
            "Dynamic rows are synthetic examples, not the user's configured schedules; beat is not started.",
            "Creation sites cover direct PeriodicTask ORM calls outside tests/migrations. Aliases, delegated queryset updates and historical migration schedules are not statically resolved.",
            "Dynamic task expressions remain unresolved with source/function/line evidence; arguments, names, headers, descriptions and solar locations are omitted.",
        ],
    }


class Trace(logging.Handler):
    """Opt-in signals, provider spy and numeric existing-diagnostic capture."""

    def __init__(self, redis, origin):
        """Use only the newly created benchmark Redis socket."""
        super().__init__()
        self.redis, self.origin = redis, origin
        self.active = {}

    def event(self, event, task_id, attempt, **values):
        """Append allowlisted fields; never serialize signal bodies or errors."""
        self.redis.rpush(
            "bench05:events",
            json.dumps(
                {
                    "event": event,
                    "job": task_id,
                    "attempt": attempt,
                    "at_s": time.perf_counter() - self.origin,
                    **values,
                }
            ),
        )

    @staticmethod
    def identity(task=None, request=None):
        """Get a synthetic task identity only."""
        request = request or getattr(task, "request", None)
        name = getattr(task, "name", None) or getattr(request, "task", "")
        if not name.startswith(PREFIX):
            return None
        return request.id, request.retries

    def publish(self, sender=None, headers=None, **_kwargs):
        """Record producer intent, including retry publications."""
        if sender and sender.startswith(PREFIX):
            self.event("enqueue", headers["id"], headers.get("retries", 0))

    def published(self, sender=None, headers=None, **_kwargs):
        """Record broker publication return; consumption can race this event."""
        if sender and sender.startswith(PREFIX):
            self.event("published", headers["id"], headers.get("retries", 0))

    def start(self, sender=None, **_kwargs):
        """Record resource boundaries for one execution attempt."""
        key = self.identity(sender)
        if key is None:
            return
        # Celery/Django worker logging setup can replace the pre-fork logger
        # configuration. Restore this benchmark-only sink after startup.
        logger = logging.getLogger("app.memory_envelope")
        logger.disabled = False
        logger.setLevel(logging.INFO)
        if self not in logger.handlers:
            logger.addHandler(self)
        self.active[key] = {
            "start": time.perf_counter(),
            "thread_cpu": time.thread_time(),
            "process_cpu": time.process_time(),
            "provider_calls": 0,
            "provider_s": 0.0,
        }
        self.event(
            "start",
            *key,
            at_s=self.active[key]["start"] - self.origin,
            worker_pid=os.getpid(),
            queue=sender.request.delivery_info.get("routing_key"),
            memory_bytes=common.memory(),
        )

    def retry(self, sender=None, request=None, **_kwargs):
        """Correlate a retry decision without retaining its exception or args."""
        key = self.identity(sender, request)
        if key:
            self.event("retry", *key)

    def end(self, sender=None, state=None, **_kwargs):
        """Close an attempt, including RETRY, independently of logical success."""
        key = self.identity(sender)
        if key is None:
            return
        opening = self.active.pop(key)
        finished = time.perf_counter()
        elapsed = {
            "wall_s": finished - opening["start"],
            "thread_cpu_s": time.thread_time() - opening["thread_cpu"],
            "process_cpu_s": time.process_time() - opening["process_cpu"],
            "provider_calls": opening["provider_calls"],
            "provider_s": opening["provider_s"],
        }
        self.event(
            "end",
            *key,
            at_s=finished - self.origin,
            state=state,
            worker_pid=os.getpid(),
            memory_bytes=common.memory(),
            **elapsed,
        )

    def emit(self, record):
        """Retain numeric task diagnostics from existing production timers."""
        message = record.getMessage()
        if not message.startswith("slow_task name=" + PREFIX):
            return
        from celery import current_task

        key = self.identity(current_task)
        if key:
            metrics = {
                name: float(value)
                for name, value in re.findall(
                    r"\b(duration_ms|cpu_ms|queries|provider_calls|db_ms|provider_ms|cache_ms|broker_ms|rss_delta_bytes|process_hwm_bytes)=(-?[0-9.]+)",
                    message,
                )
            }
            self.event("diagnostic", *key, metrics=metrics)

    @contextlib.contextmanager
    def connected(self):
        """Attach only around disposable workers, and always disconnect."""
        from celery import signals

        pairs = [
            (signals.before_task_publish, self.publish),
            (signals.after_task_publish, self.published),
            (signals.task_prerun, self.start),
            (signals.task_postrun, self.end),
            (signals.task_retry, self.retry),
        ]
        logger = logging.getLogger("app.memory_envelope")
        level = logger.level
        logger.setLevel(logging.INFO)
        logger.addHandler(self)
        try:
            for signal, callback in pairs:
                signal.connect(callback, weak=False)
            yield
        finally:
            for signal, callback in pairs:
                signal.disconnect(callback)
            logger.removeHandler(self)
            logger.setLevel(level)


def correlate(events):
    """Join by job/attempt, retain incomplete boundaries and observed overlaps."""
    attempts, workers = {}, {}
    for event in sorted(events, key=lambda value: value["at_s"]):
        row = dict(event)
        if "worker_pid" in row:
            pid = row.pop("worker_pid")
            row["worker"] = workers.setdefault(pid, f"worker-{len(workers) + 1}")
        key = (row["job"], row["attempt"])
        attempt = attempts.setdefault(
            key, {"job": key[0], "attempt": key[1], "events": []}
        )
        attempt["events"].append(row)
    result = []
    for attempt in attempts.values():
        by_name = {e["event"]: e for e in attempt["events"]}
        missing = sorted({"enqueue", "published", "start", "end"} - by_name.keys())
        attempt["missing_events"] = missing
        attempt["duplicate_events"] = {
            name: count
            for name, count in Counter(e["event"] for e in attempt["events"]).items()
            if count > 1
        }
        attempt["queue_delay_s"] = (
            by_name["start"]["at_s"] - by_name["enqueue"]["at_s"]
            if {"start", "enqueue"} <= by_name.keys()
            else None
        )
        attempt["broker_return_to_start_s"] = (
            by_name["start"]["at_s"] - by_name["published"]["at_s"]
            if {"start", "published"} <= by_name.keys()
            else None
        )
        attempt["state"] = by_name.get("end", {}).get("state")
        result.append(attempt)
    overlap = []
    complete = [a for a in result if not a["missing_events"]]
    for index, left in enumerate(complete):
        left_times = {e["event"]: e["at_s"] for e in left["events"]}
        for right in complete[index + 1 :]:
            r = {e["event"]: e["at_s"] for e in right["events"]}
            seconds = min(left_times["end"], r["end"]) - max(
                left_times["start"], r["start"]
            )
            if seconds > 0:
                overlap.append(
                    {
                        "left": [left["job"], left["attempt"]],
                        "right": [right["job"], right["attempt"]],
                        "seconds": seconds,
                    }
                )
    return {
        "attempts": result,
        "overlap": overlap,
        "worker_count": len(workers),
        "incomplete_attempts": sum(bool(a["missing_events"]) for a in result),
        "duplicate_attempts": sum(bool(a["duplicate_events"]) for a in result),
        "event_checksum": hashlib.sha256(
            json.dumps(
                sorted(
                    (
                        a["job"],
                        a["attempt"],
                        a["state"],
                        sorted(e["event"] for e in a["events"]),
                    )
                    for a in result
                )
            ).encode()
        ).hexdigest(),
    }
