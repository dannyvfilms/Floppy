import ast
import importlib
import json
import zoneinfo
from datetime import datetime, timedelta

import croniter
from celery import states
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone

# A cron expression "minute hour ..." needs at least this many space-separated
# fields before its hour part can be inspected for an "every X hours" pattern.
MIN_CRON_PARTS_FOR_HOUR_PATTERN = 2

IS_FIRST_RUN_CACHE_KEY = "users_is_first_run"
IS_FIRST_RUN_CACHE_TIMEOUT = 60  # seconds


def task_kwargs_belong_to_user(payload, user_id):
    """Verify the actual owner field, never an id embedded inside a string value."""
    try:
        values = json.loads(payload)
    except (TypeError, ValueError, RecursionError):
        try:
            # Celery also records Python repr kwargs, rather than JSON.
            values = ast.literal_eval(payload)
        except (TypeError, ValueError, SyntaxError, RecursionError):
            return False
    return isinstance(values, dict) and type(values.get("user_id")) is int and values["user_id"] == user_id


def is_first_run() -> bool:
    """Return whether this instance has no real (non-demo) user account yet.

    Cached briefly: once a real account exists this permanently flips to
    False, so a short TTL is enough to avoid a DB query on every request
    while still self-correcting quickly for the handful of requests before
    the first account is created.
    """
    cached = cache.get(IS_FIRST_RUN_CACHE_KEY)
    if cached is not None:
        return cached

    no_real_users = not get_user_model().objects.filter(is_demo=False).exists()
    cache.set(IS_FIRST_RUN_CACHE_KEY, no_real_users, IS_FIRST_RUN_CACHE_TIMEOUT)
    return no_real_users


def _deserialize_task_result(result):
    """Return the stored task result in its native Python shape when possible."""
    if not isinstance(result, str):
        return result

    try:
        return json.loads(result)
    except json.JSONDecodeError:
        return result


def _split_success_result(result_text):
    """Split a string success payload into summary and error details."""
    error_title = importlib.import_module("integrations.tasks").ERROR_TITLE.strip()
    parts = result_text.split(error_title)
    if len(parts) > 1:
        return parts[0].strip(), parts[1].strip()
    return result_text.strip(), None


def _format_dict_success_result(result):
    """Render a dict-based Celery success payload."""
    message = result.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip(), None

    if "processed" in result:
        processed = result.get("processed", 0)
        total_accounts = result.get("total_accounts")
        if total_accounts is None:
            summary = f"Processed {processed} account(s)."
        else:
            summary = f"Processed {processed} of {total_accounts} account(s)."

        errors = result.get("errors")
        if errors:
            return summary, f"{errors} account(s) reported errors."
        return summary, None

    return json.dumps(result, sort_keys=True), None


def _format_list_success_result(result):
    """Render a list-based Celery success payload."""
    if result and all(isinstance(item, str) for item in result):
        summary = result[0].strip() or "Task completed successfully."
        error_lines = [item.strip() for item in result[1:] if item and item.strip()]
        return summary, "\n".join(error_lines) or None

    return "Queued follow-up import task.", None


def _format_structured_success_result(result):
    """Render a user-facing summary for non-string Celery success payloads."""
    if isinstance(result, dict):
        return _format_dict_success_result(result)

    if isinstance(result, list):
        return _format_list_success_result(result)

    if result is None:
        return "Task completed successfully.", None

    return str(result), None


STATUS_SUMMARIES = {
    states.PENDING: "This task has been queued and is waiting to run.",
    states.RECEIVED: "This task has been picked up and is about to run.",
    states.STARTED: "This task is currently running.",
    states.RETRY: "This task failed and is waiting to be retried.",
    states.REVOKED: "This task was cancelled before it finished.",
    states.REJECTED: "This task was turned away by the worker and never ran.",
    states.IGNORED: "This task ran without recording a result.",
}


def process_task_result(task):
    """Process task result based on status and format appropriately.

    A task can hold any Celery state, not just the four the activity panel
    styles: cancelling an import leaves it REVOKED, and a worker can report
    RETRY or REJECTED. Callers read `summary` and `errors` unconditionally,
    so every state has to leave both set.
    """
    task.summary = STATUS_SUMMARIES.get(
        task.status,
        f"This task is in an unrecognised state ({task.status}).",
    )
    task.errors = None

    if task.status == states.FAILURE:
        result_json = _deserialize_task_result(task.result)
        if (
            isinstance(result_json, dict)
            and result_json.get("exc_type") == "MediaImportError"
            and result_json.get("exc_message")
        ):
            task.summary = result_json["exc_message"][0]
        else:
            task.summary = "Unexpected error occurred while processing the task."
        task.errors = task.traceback
    elif task.status == states.SUCCESS:
        result_json = _deserialize_task_result(task.result)
        if isinstance(result_json, str):
            task.summary, task.errors = _split_success_result(result_json)
        else:
            task.summary, task.errors = _format_structured_success_result(result_json)

    return task


def get_next_run_info(periodic_task):
    """Calculate next run time and frequency for a periodic task."""
    try:
        kwargs = json.loads(periodic_task.kwargs)
        mode = kwargs.get("mode", "new")  # Default to 'new' if not specified
    except (AttributeError, TypeError, json.JSONDecodeError):
        mode = "new"

    mode_labels = {
        "new": "Only New Items",
        "overwrite": "Overwrite Existing",
        "update_collection": "Collection Metadata Only",
        "watchlist": "Watchlist Sync",
    }
    mode = mode_labels.get(mode, str(mode).replace("_", " ").title())

    if getattr(periodic_task, "interval", None):
        delta = _interval_to_timedelta(periodic_task.interval)
        if delta is None:
            return None

        now = timezone.now()
        base_time = periodic_task.last_run_at or periodic_task.start_time or now
        if base_time > now:
            next_run = base_time
        else:
            elapsed = now - base_time
            steps = int(elapsed // delta) + 1
            next_run = base_time + (delta * steps)

        return {
            "next_run": next_run,
            "frequency": _interval_frequency_display(periodic_task.interval),
            "mode": mode,
        }

    if not periodic_task.crontab:
        return None

    cron = periodic_task.crontab
    tz = zoneinfo.ZoneInfo(str(cron.timezone))
    now = timezone.now().astimezone(tz)

    # Create cron expression
    cron_expr = (
        f"{cron.minute} {cron.hour} {cron.day_of_month} "
        f"{cron.month_of_year} {cron.day_of_week}"
    )
    cron_iter = croniter.croniter(cron_expr, now)
    next_run = cron_iter.get_next(datetime)

    # Determine frequency
    if cron.day_of_week == "*":
        # Check for "every X hours" pattern by examining the cron expression
        # Pattern should be: "0 */X * * *" (minute=0, hour=*/X, all others *)
        cron_parts = cron_expr.split()
        if len(cron_parts) >= MIN_CRON_PARTS_FOR_HOUR_PATTERN:
            minute_part = str(cron_parts[0])
            hour_part = str(cron_parts[1])
            # Check if it matches "every 2 hours" pattern
            if hour_part == "*/2" and minute_part in ("0", "00"):
                frequency = "Every 2 hours"
            # Check if it matches "every 3 hours" pattern (for backwards compatibility)
            elif hour_part == "*/3" and minute_part in ("0", "00"):
                frequency = "Every 3 hours"
            elif cron.day_of_month == "*" and cron.month_of_year == "*":
                frequency = "Every Day"
            else:
                frequency = "Every Day"
        elif cron.day_of_month == "*" and cron.month_of_year == "*":
            frequency = "Every Day"
        else:
            frequency = "Every Day"
    elif cron.day_of_week == "*/2":
        frequency = "Every 2 days"
    else:
        frequency = f"Cron: {cron_expr}"

    return {
        "next_run": next_run,
        "frequency": frequency,
        "mode": mode,
    }


# Frequencies a user may assign to an existing periodic import. Sub-daily
# values are minutes applied as an IntervalSchedule; the remaining values map
# to a CrontabSchedule day_of_week plus a daily time.
SCHEDULE_FREQUENCY_OPTIONS = (
    ("15m", "Every 15 minutes", 15),
    ("30m", "Every 30 minutes", 30),
    ("1h", "Every hour", 60),
    ("2h", "Every 2 hours", 120),
    ("4h", "Every 4 hours", 240),
    ("6h", "Every 6 hours", 360),
    ("12h", "Every 12 hours", 720),
    ("daily", "Every Day", None),
    ("2days", "Every 2 days", None),
    ("weekly", "Weekly", None),
)
SCHEDULE_DAY_OF_WEEK = {
    "daily": "*",
    "2days": "*/2",
    "weekly": "0",
}


def schedule_frequency_minutes(value):
    """Return the interval minutes for a frequency value, or None."""
    for option, _label, minutes in SCHEDULE_FREQUENCY_OPTIONS:
        if option == value:
            return minutes
    return None


def schedule_edit_state(periodic_task):
    """Return (frequency_value, "HH:MM") describing a task's current cadence.

    An empty frequency means the current schedule does not match an editable
    option (custom crontab or unusual interval); the form still offers editing
    but leaves the current value preselected as "Custom schedule".
    """
    if getattr(periodic_task, "interval", None):
        delta = _interval_to_timedelta(periodic_task.interval)
        minutes = int(delta.total_seconds() // 60) if delta else None
        value = next(
            (option for option, _label, m in SCHEDULE_FREQUENCY_OPTIONS if m == minutes),
            "",
        )
        return value, ""
    cron = getattr(periodic_task, "crontab", None)
    if cron is None:
        return "", ""
    time = ""
    minute, hour = str(cron.minute), str(cron.hour)
    if minute.isdigit() and hour.isdigit():
        time = f"{int(hour):02d}:{int(minute):02d}"
    if cron.day_of_week == "*" and minute in ("0", "00") and hour.startswith("*/"):
        try:
            minutes = int(hour[2:]) * 60
            value = next(
                option for option, _label, m in SCHEDULE_FREQUENCY_OPTIONS
                if m == minutes
            )
        except (ValueError, StopIteration):
            value = ""
        return value, ""
    if not (minute.isdigit() and hour.isdigit()):
        # Expressions like "*/15 * * * *" have no editable equivalent.
        return "", ""
    value = next(
        (v for v, dow in SCHEDULE_DAY_OF_WEEK.items() if dow == cron.day_of_week),
        "",
    )
    return value, time


def _interval_to_timedelta(interval):
    """Convert a Celery beat interval schedule into a timedelta."""
    multipliers = {
        "days": "days",
        "hours": "hours",
        "minutes": "minutes",
        "seconds": "seconds",
    }
    unit = multipliers.get(interval.period)
    if unit is None:
        return None
    return timedelta(**{unit: interval.every})


def _interval_frequency_display(interval):
    """Render a human-readable label for an interval schedule."""
    every = interval.every
    period = interval.period
    if period == "minutes" and every % 60 == 0:
        # Prefer the largest whole unit so an edited "6h" schedule reads
        # "Every 6 hours", not "Every 360 minutes".
        if every % 1440 == 0:
            every, period = every // 1440, "days"
        else:
            every, period = every // 60, "hours"
    singular = {
        "days": "day",
        "hours": "hour",
        "minutes": "minute",
        "seconds": "second",
    }
    unit = singular.get(period, period)
    suffix = "" if every == 1 else "s"
    return f"Every {every} {unit}{suffix}"


def get_export_next_run_info(periodic_task):
    """Calculate next run time and frequency for a periodic export task."""
    if not periodic_task.crontab:
        return None

    try:
        kwargs = json.loads(periodic_task.kwargs)
        media_types = kwargs.get("media_types")
        include_lists = kwargs.get("include_lists", True)
        include_collection = kwargs.get("include_collection", True)
    except json.JSONDecodeError:
        media_types = None
        include_lists = True
        include_collection = True

    cron = periodic_task.crontab
    tz = zoneinfo.ZoneInfo(str(cron.timezone))
    now = timezone.now().astimezone(tz)

    cron_expr = (
        f"{cron.minute} {cron.hour} {cron.day_of_month} "
        f"{cron.month_of_year} {cron.day_of_week}"
    )
    cron_iter = croniter.croniter(cron_expr, now)
    next_run = cron_iter.get_next(datetime)

    # Determine frequency
    if cron.day_of_week == "*/2":
        frequency = "Every 2 Days"
    elif cron.day_of_month == "*/7" or cron.day_of_week in (
        "0",
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
    ):
        frequency = "Weekly"
    else:
        frequency = "Daily"

    return {
        "next_run": next_run,
        "frequency": frequency,
        "media_types": media_types,
        "include_lists": include_lists,
        "include_collection": include_collection,
    }
