"""Resumable, bounded Statistics refresh runs.

A Statistics refresh used to be one Celery task body: plan the whole range,
build every day it needed, aggregate, publish. On the dedicated interactive
worker -- concurrency 1, prefetch 1 -- that meant one All Time rebuild owned
the fast lane for as long as it took, which production has seen reach 189
seconds. Nothing in the task yielded, so a Plex scrobble arriving one second
in waited for the whole rebuild.

This module keeps the same final cache semantics but splits the work into a
run: a START that plans, a bounded sequence of CHUNKs that each build at most
``STATISTICS_REFRESH_CHUNK_DAYS`` days and then **return**, and a FINISH that
aggregates and publishes. Each chunk is its own Celery message, so the worker
is free between them and a webhook published at a higher priority overtakes
the next chunk.

Where the run state lives
------------------------
In the cache, in the *existing* refresh-lock key. That is deliberate:

* Every input the run consumes already lives in the cache -- per-day payloads,
  the dirty-day set, the per-user history version, the published range entry.
  Durable run state would outlive the data it orchestrates and resume against
  day caches that are no longer there.
* The continuation messages live in Redis too (it is the broker). Database run
  state would survive a Redis loss into a world with no continuation message
  and nothing scheduled to notice it -- a genuinely stuck run rather than a
  self-healing one.
* Losing the run is already safe: the published range entry stays stale, and
  the next reader (`get_statistics_data`) schedules a fresh refresh. That is
  the existing recovery path, not a new one.
* Reusing the refresh-lock key means `_lock_is_stale`, `_any_range_refreshing`,
  the statistics polling view and `get_statistics_data`'s "refresh in progress"
  branch all keep working across a multi-task run with no changes. Each chunk
  re-stamps ``started_at``, so the lock is a heartbeat lease: if a chunk dies,
  the lock ages out instead of becoming immortal.

The run record holds control state only -- ids, a cursor, counters, flags. The
day payloads it builds go straight to their own cache entries and are dropped.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone

from app.statistics_cache import (
    PREDEFINED_RANGES,
    STATISTICS_WARM_DAYS,
    _collect_stale_reading_score_days,
    _load_dirty_days,
    _lock_is_stale,
    _maybe_clear_metadata_refresh,
    _refresh_lock_key,
    _store_dirty_days,
    cache_statistics_data,
)
from app.statistics_day_builder import _build_prefetch_for_range, build_stats_for_day
from app.statistics_day_cache import (
    STATISTICS_DAY_CACHE_TIMEOUT,
    _day_cache_key,
    _get_history_version,
    _normalize_day_value,
)

logger = logging.getLogger(__name__)

RUN_STATE_BUILDING = "building"
RUN_STATE_FINISHING = "finishing"

# Cap on the per-run list of days whose cache write was reported as failed.
# The list is only telemetry -- FINISH rebuilds a missing day through the
# aggregator's existing `build_missing` path whether or not it is listed.
STATISTICS_REFRESH_FAILED_WRITE_CAP = 500


def _chunk_days() -> int:
    """Days one chunk builds.

    The bound the interactive lane actually cares about is wall-clock, not
    days, so this is the knob a Docker session turns until the slowest chunk
    fits its latency budget. Deliberately not derived from any production
    timing that cannot be reproduced without a real library. Read at call time
    so it can be tuned (or overridden in a test) without a restart.
    """
    return max(1, getattr(settings, "STATISTICS_REFRESH_CHUNK_DAYS", 25))


def _chunk_countdown() -> int:
    """Delay applied to each continuation. Zero by default, on purpose.

    Celery's Redis transport delivers an ETA task to the worker immediately and
    holds it in memory until due; with ``prefetch_multiplier=1`` and
    ``concurrency=1`` that held message occupies the worker's only prefetch
    slot, which is the opposite of yielding. Priority, not delay, is what keeps
    a webhook ahead of a queued chunk.
    """
    return max(0, getattr(settings, "STATISTICS_REFRESH_CHUNK_COUNTDOWN", 0))


def _run_lease() -> int:
    """Lease TTL for the run record, re-stamped by every chunk.

    A run that stops advancing stops renewing it, so a dead chunk ages the run
    out instead of leaving an immortal lock.
    """
    return max(60, getattr(settings, "STATISTICS_REFRESH_RUN_LEASE", 300))


_COMPACT_DAY_FORMAT = "%Y%m%d"


def _run_work_key(user_id: int, range_name: str, run_id: str) -> str:
    return f"stats:refresh:work:{user_id}:{run_id}"


def _run_dirty_key(user_id: int, range_name: str, run_id: str) -> str:
    return f"stats:refresh:dirty:{user_id}:{run_id}"


def _rerun_key(user_id: int, range_name: str) -> str:
    from app.statistics_cache import _normalize_range_name

    return f"stats:refresh:rerun:{user_id}:{_normalize_range_name(range_name)}"


def _encode_days(days) -> list[str]:
    """Store the work list as compact day tokens, not payloads.

    ``_normalize_day_value`` already round-trips ``YYYYMMDD``, so eight bytes a
    day is the whole cost of remembering what a run still owes. Even a decade
    of daily activity is well under 40 KiB.
    """
    return [day.strftime(_COMPACT_DAY_FORMAT) for day in days if day]


def _decode_days(tokens) -> list:
    decoded = []
    for token in tokens or []:
        day = _normalize_day_value(token)
        if day:
            decoded.append(day)
    return decoded


def load_run(user_id: int, range_name: str) -> dict | None:
    """Return the active run record, or None if there isn't a live one."""
    value = cache.get(_refresh_lock_key(user_id, range_name))
    if not isinstance(value, dict) or not value.get("run_id"):
        return None
    if _lock_is_stale(value):
        return None
    return value


def _store_run(user_id: int, range_name: str, run: dict, *, heartbeat: bool = True):
    if heartbeat:
        run["started_at"] = timezone.now().isoformat()
    cache.set(
        _refresh_lock_key(user_id, range_name),
        run,
        timeout=_run_lease(),
    )
    return run


def release_run(user_id: int, range_name: str, run_id: str | None) -> None:
    """Drop the lock and the run's scratch keys, if we still own the lock."""
    lock_key = _refresh_lock_key(user_id, range_name)
    current = cache.get(lock_key)
    if (
        run_id is None
        or not isinstance(current, dict)
        or current.get("run_id") in (None, run_id)
    ):
        cache.delete(lock_key)
    if run_id:
        cache.delete_many(
            [
                _run_work_key(user_id, range_name, run_id),
                _run_dirty_key(user_id, range_name, run_id),
            ]
        )
    _maybe_clear_metadata_refresh(user_id)


def request_rerun(user_id: int, range_name: str, reason: str = "forced") -> None:
    """Record that another pass is owed once the active run finishes.

    Kept in its own key rather than on the run record: the record is rewritten
    by every chunk, so a flag set there could be lost to a concurrent chunk
    write. A forced refresh must never be silently dropped.
    """
    cache.set(
        _rerun_key(user_id, range_name),
        {"requested_at": timezone.now().isoformat(), "reason": reason},
        timeout=_run_lease(),
    )
    logger.info(
        "statistics_refresh_followup_requested user_id=%s range=%s reason=%s",
        user_id,
        range_name,
        reason,
    )


def _consume_rerun(user_id: int, range_name: str) -> dict | None:
    key = _rerun_key(user_id, range_name)
    value = cache.get(key)
    if value:
        cache.delete(key)
    return value if isinstance(value, dict) else None


def _load_user(user_id: int):
    user_model = get_user_model()
    try:
        return user_model.objects.get(id=user_id)
    except user_model.DoesNotExist:
        return None


def _plan_run(user, range_name: str):
    """Decide which days this run owes, exactly as the single-shot refresh did.

    Returns ``(start_date, end_date, day_list, work_days, dirty_covered,
    stale_score_days)``.
    """
    from app.statistics_refresh import _get_predefined_range_dates, _resolve_day_list

    start_date, end_date = _get_predefined_range_dates(range_name)
    day_list = _resolve_day_list(user, start_date, end_date)
    day_list_set = set(day_list)

    dirty_days = _load_dirty_days(user.id)
    dirty_dates = {_normalize_day_value(day) for day in dirty_days if day}

    warm_days = []
    if STATISTICS_WARM_DAYS and day_list:
        today = timezone.localdate()
        for offset in range(STATISTICS_WARM_DAYS):
            warm_day = today - timedelta(days=offset)
            if warm_day in day_list_set:
                warm_days.append(warm_day)

    missing_days = set()
    chunk_size = 50
    for offset in range(0, len(day_list), chunk_size):
        chunk = day_list[offset : offset + chunk_size]
        keys = [_day_cache_key(user.id, day) for day in chunk]
        cached = cache.get_many(keys)
        for day, key in zip(chunk, keys, strict=False):
            if key not in cached:
                missing_days.add(day)

    days_to_refresh = set(warm_days)
    days_to_refresh.update(missing_days)
    days_to_refresh.update(day for day in dirty_dates if day in day_list_set)
    stale_score_days = _collect_stale_reading_score_days(
        user, day_whitelist=day_list_set
    )
    days_to_refresh.update(stale_score_days)

    work_days = [day for day in sorted(days_to_refresh) if day]
    dirty_covered = {day.isoformat() for day in work_days}
    return start_date, end_date, day_list, work_days, dirty_covered, stale_score_days


def begin_run(
    user_id: int,
    range_name: str,
    *,
    force: bool = False,
    chunk_size: int | None = None,
    takeover: bool = False,
) -> dict | None:
    """Plan a refresh and claim the run. Returns the run record, or None.

    None means no run was started: unknown user, unsupported range, or an
    active run already owns this user/range. A forced request that collides
    with an active run is recorded as a follow-up rather than dropped.
    """
    if range_name not in PREDEFINED_RANGES:
        logger.warning(
            "Attempted to refresh cache for non-predefined range: %s", range_name
        )
        return None

    existing = load_run(user_id, range_name)
    if existing and not takeover:
        if force:
            request_rerun(user_id, range_name, reason="forced_during_active_run")
        else:
            logger.debug(
                "statistics_refresh_run_duplicate user_id=%s range=%s active_run=%s",
                user_id,
                range_name,
                existing.get("run_id"),
            )
        return None

    user = _load_user(user_id)
    if user is None:
        release_run(user_id, range_name, None)
        return None

    (
        _start_date,
        _end_date,
        day_list,
        work_days,
        dirty_covered,
        stale_score_days,
    ) = _plan_run(user, range_name)

    run_id = uuid.uuid4().hex
    resolved_chunk_size = max(1, int(chunk_size or _chunk_days()))
    run = {
        "run_id": run_id,
        "range_name": range_name,
        "history_version": _get_history_version(user_id),
        "state": RUN_STATE_BUILDING if work_days else RUN_STATE_FINISHING,
        "cursor": 0,
        "chunk_index": 0,
        "chunk_size": resolved_chunk_size,
        "total_days": len(work_days),
        "day_count": len(day_list),
        "credit_backfill_hints": 0,
        "stale_score_days": len(stale_score_days),
        "failed_write_days": [],
        "failed_write_count": 0,
        "created_at": timezone.now().isoformat(),
    }

    if work_days:
        cache.set(
            _run_work_key(user_id, range_name, run_id),
            _encode_days(work_days),
            timeout=_run_lease(),
        )
    cache.set(
        _run_dirty_key(user_id, range_name, run_id),
        sorted(dirty_covered),
        timeout=_run_lease(),
    )
    _store_run(user_id, range_name, run)

    logger.info(
        "statistics_refresh_run_start run_id=%s user_id=%s range=%s "
        "history_version=%s day_count=%s work_days=%s chunk_size=%s chunks=%s",
        run_id,
        user_id,
        range_name,
        run["history_version"],
        len(day_list),
        len(work_days),
        resolved_chunk_size,
        _remaining_chunks(run),
    )
    return run


def _remaining_chunks(run: dict) -> int:
    remaining = max(0, int(run.get("total_days", 0)) - int(run.get("cursor", 0)))
    chunk_size = max(1, int(run.get("chunk_size", 1)))
    return -(-remaining // chunk_size)


def _abort_run(user_id: int, range_name: str, run: dict, reason: str) -> None:
    logger.info(
        "statistics_refresh_run_abort run_id=%s user_id=%s range=%s reason=%s "
        "expected_version=%s actual_version=%s chunk_index=%s",
        run.get("run_id"),
        user_id,
        range_name,
        reason,
        run.get("history_version"),
        _get_history_version(user_id),
        run.get("chunk_index"),
    )
    # Dirty days stay dirty and the published entry stays untouched: an aborted
    # run must leave every piece of work it did not finish discoverable.
    release_run(user_id, range_name, run.get("run_id"))


def _claim_step(user_id: int, range_name: str, run_id: str) -> dict | None:
    """Return the run record iff `run_id` still owns this user/range."""
    run = load_run(user_id, range_name)
    if run is None:
        logger.info(
            "statistics_refresh_run_abort run_id=%s user_id=%s range=%s reason=%s",
            run_id,
            user_id,
            range_name,
            "run_state_missing",
        )
        return None
    if run.get("run_id") != run_id:
        logger.info(
            "statistics_refresh_run_abort run_id=%s user_id=%s range=%s reason=%s "
            "active_run=%s",
            run_id,
            user_id,
            range_name,
            "superseded",
            run.get("run_id"),
        )
        return None
    return run


def _flush_day_writes(user_id: int, range_name: str, run: dict, pending: dict) -> int:
    """Write a chunk's day payloads, retrying once, and record what still failed.

    The single-shot refresh kept the payloads of failed writes in Python and
    handed them to the aggregator as `prebuilt_days`. A run cannot carry
    payloads across task boundaries, so it records the day *identifiers* and
    lets FINISH rebuild them: `_aggregate_statistics_from_days(...,
    build_missing=True)` already rebuilds any day it cannot read from the
    cache, and `build_stats_for_day` is deterministic for the same database
    state and history version, so the published numbers are unchanged.
    """
    if not pending:
        return 0

    failed_keys = set(
        cache.set_many(pending, timeout=STATISTICS_DAY_CACHE_TIMEOUT) or ()
    )
    if failed_keys:
        retry = {key: pending[key] for key in failed_keys if key in pending}
        failed_keys = set(
            cache.set_many(retry, timeout=STATISTICS_DAY_CACHE_TIMEOUT) or ()
        )

    if not failed_keys:
        return 0

    run["failed_write_count"] = int(run.get("failed_write_count", 0)) + len(failed_keys)
    listed = run.setdefault("failed_write_days", [])
    for key in sorted(failed_keys):
        if len(listed) >= STATISTICS_REFRESH_FAILED_WRITE_CAP:
            break
        listed.append(key.rsplit(":", 1)[-1])
    return len(failed_keys)


def run_chunk(user_id: int, range_name: str, run: dict, user=None) -> dict:
    """Build at most one chunk of days and return the advanced run record."""
    chunk_started = time.perf_counter()
    run_id = run["run_id"]
    cursor = int(run.get("cursor", 0))
    chunk_size = max(1, int(run.get("chunk_size") or _chunk_days()))
    chunk_index = int(run.get("chunk_index", 0))

    work_days = _decode_days(cache.get(_run_work_key(user_id, range_name, run_id)))
    days = work_days[cursor : cursor + chunk_size]

    if user is None:
        user = _load_user(user_id)
    if user is None or not days:
        run["cursor"] = int(run.get("total_days", 0))
        run["state"] = RUN_STATE_FINISHING
        return _store_run(user_id, range_name, run)

    # Prefetch only this chunk's span. The single-shot refresh built one
    # range-wide prefetch, which is the structure that made chunking unsafe and
    # the largest single allocation in an All Time rebuild. Per-chunk prefetch
    # costs ~13 more queries per chunk and bounds the allocation to the chunk.
    prefetch = _build_prefetch_for_range(user, days)
    history_version = run.get("history_version")
    backfill_collector = {
        "runtime_item_ids": set(),
        "genre_item_ids": set(),
        "episode_runtime_keys": set(),
        "credit_item_ids": set(),
    }

    pending: dict[str, dict] = {}
    credit_hints = 0
    nonempty_days = 0
    for day in days:
        day_stats = build_stats_for_day(
            user_id,
            day,
            user=user,
            prefetch=prefetch,
            history_version=history_version,
            defer_cache_write=True,
            backfill_collector=backfill_collector,
        )
        if not day_stats:
            continue
        pending[_day_cache_key(user_id, day)] = day_stats
        credit_hints += int(day_stats.get("backfill", {}).get("missing_credits") or 0)
        totals = day_stats.get("totals", {})
        if (
            sum(totals.get("plays_by_type", {}).values())
            or sum(totals.get("minutes_by_type", {}).values())
            or sum(day_stats.get("daily_minutes_by_type", {}).values())
        ):
            nonempty_days += 1

    cache_write_failures = _flush_day_writes(user_id, range_name, run, pending)
    pending.clear()

    # Flush this chunk's hints now rather than accumulating a run-wide
    # collector. The enqueue helpers filter already-satisfied items and write
    # into set-backed queues, so repeating an id across chunks is a no-op.
    from app.statistics_refresh import _enqueue_collected_backfills

    _enqueue_collected_backfills(user_id, backfill_collector)

    run["cursor"] = cursor + len(days)
    run["chunk_index"] = chunk_index + 1
    run["credit_backfill_hints"] = (
        int(run.get("credit_backfill_hints", 0)) + credit_hints
    )
    if run["cursor"] >= int(run.get("total_days", 0)):
        run["state"] = RUN_STATE_FINISHING
    _store_run(user_id, range_name, run)

    logger.info(
        "statistics_refresh_chunk_end run_id=%s user_id=%s range=%s chunk_index=%s "
        "days=%s nonempty=%s elapsed_ms=%.2f cache_write_failures=%s "
        "remaining_chunks=%s",
        run_id,
        user_id,
        range_name,
        chunk_index,
        len(days),
        nonempty_days,
        (time.perf_counter() - chunk_started) * 1000,
        cache_write_failures,
        _remaining_chunks(run),
    )
    return run


def finish_run(user_id: int, range_name: str, run: dict, user=None):
    """Aggregate, publish, clear the dirty days this run covered, and release.

    Returns the published statistics payload, or None if the run was aborted.
    """
    from app.statistics_refresh import (
        _aggregate_statistics_from_days,
        _get_predefined_range_dates,
        _resolve_day_list,
    )

    run_id = run.get("run_id")
    if user is None:
        user = _load_user(user_id)
    if user is None:
        _abort_run(user_id, range_name, run, "user_missing")
        return None

    current_version = _get_history_version(user_id)
    if run.get("history_version") != current_version:
        # History moved under this run. Publishing now would overwrite a newer
        # result with numbers built against the old version, and clearing the
        # dirty days would discard work that belongs to the new one.
        _abort_run(user_id, range_name, run, "history_version_changed")
        request_rerun(user_id, range_name, reason="history_version_changed")
        return None

    start_date, end_date = _get_predefined_range_dates(range_name)
    day_list = _resolve_day_list(user, start_date, end_date)
    dirty_covered = set(
        cache.get(_run_dirty_key(user_id, range_name, run_id)) or (),
    )

    stats_data = _aggregate_statistics_from_days(
        user,
        day_list,
        start_date,
        end_date,
        build_missing=True,
        credit_backfill_hints=int(run.get("credit_backfill_hints", 0)),
    )

    # Last check before publishing: aggregation reads the database, so history
    # can still have moved while it ran.
    if _get_history_version(user_id) != current_version:
        _abort_run(user_id, range_name, run, "history_version_changed_during_finish")
        request_rerun(user_id, range_name, reason="history_version_changed")
        return None

    cache_statistics_data(
        user_id, range_name, stats_data, history_version=current_version
    )

    if dirty_covered:
        remaining = _load_dirty_days(user_id)
        remaining.difference_update(dirty_covered)
        _store_dirty_days(user_id, remaining)

    if run.get("stale_score_days"):
        logger.info(
            "stats_score_repair user_id=%s range=%s repaired_days=%s",
            user_id,
            range_name,
            run.get("stale_score_days"),
        )

    logger.info(
        "statistics_refresh_run_finish run_id=%s user_id=%s range=%s chunks=%s "
        "work_days=%s day_count=%s cache_write_failures=%s history_version=%s "
        "total_elapsed_ms=%.2f totals=%s",
        run_id,
        user_id,
        range_name,
        run.get("chunk_index"),
        run.get("total_days"),
        run.get("day_count"),
        run.get("failed_write_count", 0),
        current_version,
        _elapsed_ms(run),
        stats_data.get("hours_per_media_type", {}),
    )
    logger.info(
        "stats_range_summary user_id=%s range=%s days=%s refreshed=%s nonempty=%s "
        "elapsed_ms=%.2f totals=%s",
        user_id,
        range_name,
        run.get("day_count"),
        run.get("total_days"),
        run.get("total_days"),
        _elapsed_ms(run),
        stats_data.get("hours_per_media_type", {}),
    )

    release_run(user_id, range_name, run_id)
    return stats_data


def _elapsed_ms(run: dict) -> float:
    created_at = run.get("created_at")
    if not isinstance(created_at, str):
        return 0.0
    try:
        started = datetime.fromisoformat(created_at)
    except ValueError:
        return 0.0
    if timezone.is_naive(started):
        started = timezone.make_aware(started, timezone.get_current_timezone())
    return (timezone.now() - started).total_seconds() * 1000


def _schedule_continuation(user_id: int, range_name: str, run: dict) -> bool:
    """Queue exactly one continuation message and return.

    This is the whole point of the redesign: one bounded message, published at
    a priority that a new webhook outranks, rather than a loop that keeps the
    worker.
    """
    try:
        from app.tasks_interactive import continue_statistics_refresh_task

        continue_statistics_refresh_task.apply_async(
            args=[user_id, range_name, run["run_id"]],
            countdown=_chunk_countdown(),
            priority=getattr(
                settings,
                "CELERY_TASK_PRIORITY_STATISTICS_CONTINUATION",
                getattr(settings, "CELERY_TASK_PRIORITY_FOLLOWUP", 3),
            ),
        )
    except Exception as exc:  # pragma: no cover - Celery not available
        logger.warning(
            "statistics_refresh_run_abort run_id=%s user_id=%s range=%s reason=%s "
            "error=%s",
            run.get("run_id"),
            user_id,
            range_name,
            "continuation_unschedulable",
            exc,
        )
        release_run(user_id, range_name, run.get("run_id"))
        return False
    else:
        return True


def _schedule_followup(user_id: int, range_name: str, rerun: dict) -> None:
    from app.statistics_refresh import schedule_statistics_refresh

    logger.info(
        "statistics_refresh_followup_scheduled user_id=%s range=%s reason=%s",
        user_id,
        range_name,
        rerun.get("reason"),
    )
    schedule_statistics_refresh(
        user_id,
        range_name,
        debounce_seconds=0,
        countdown=0,
        allow_inline=False,
        force=True,
    )


def start_chunked_run(user_id: int, range_name: str, *, force: bool = False) -> bool:
    """START stage: plan the run and queue its first continuation."""
    run = begin_run(user_id, range_name, force=force)
    if run is None:
        return False
    return _schedule_continuation(user_id, range_name, run)


def advance_chunked_run(user_id: int, range_name: str, run_id: str) -> bool:
    """CHUNK/FINISH stage: do one bounded step, then yield the worker."""
    run = _claim_step(user_id, range_name, run_id)
    if run is None:
        return False

    if run.get("history_version") != _get_history_version(user_id):
        _abort_run(user_id, range_name, run, "history_version_changed")
        request_rerun(user_id, range_name, reason="history_version_changed")
        rerun = _consume_rerun(user_id, range_name)
        if rerun:
            _schedule_followup(user_id, range_name, rerun)
        return False

    if run.get("state") == RUN_STATE_BUILDING:
        logger.info(
            "statistics_refresh_chunk_start run_id=%s user_id=%s range=%s "
            "chunk_index=%s cursor=%s total_days=%s",
            run_id,
            user_id,
            range_name,
            run.get("chunk_index"),
            run.get("cursor"),
            run.get("total_days"),
        )
        try:
            run = run_chunk(user_id, range_name, run)
        except Exception:
            # Leave the run record in place. The cursor was not advanced, so a
            # retry redoes exactly this chunk; if nothing retries, the lease
            # ages out and the next reader schedules a fresh run. Either way
            # the dirty days this run owed are still dirty.
            logger.exception(
                "statistics_refresh_chunk_failed run_id=%s user_id=%s range=%s "
                "chunk_index=%s",
                run_id,
                user_id,
                range_name,
                run.get("chunk_index"),
            )
            raise
        return _schedule_continuation(user_id, range_name, run)

    finish_run(user_id, range_name, run)
    rerun = _consume_rerun(user_id, range_name)
    if rerun:
        _schedule_followup(user_id, range_name, rerun)
    return True


def run_refresh_inline(
    user_id: int,
    range_name: str,
    *,
    chunk_size: int | None = None,
):
    """Drive a whole run to completion in this process.

    Same state machine, different driver: used by the eager/test path and by
    the inline fallback when Celery is unavailable, where there is no worker to
    yield to and the caller needs the payload back.
    """
    stats_data = None
    # A run that aborts because history moved under it owes another pass. The
    # inline driver has no worker to hand that to, so it makes the pass itself
    # -- bounded, so a history version changing on every attempt cannot spin.
    for _attempt in range(2):
        run = begin_run(
            user_id, range_name, force=True, chunk_size=chunk_size, takeover=True
        )
        if run is None:
            return None

        user = _load_user(user_id)
        if user is None:
            release_run(user_id, range_name, run.get("run_id"))
            return None

        try:
            while run.get("state") == RUN_STATE_BUILDING:
                run = run_chunk(user_id, range_name, run, user=user)
            stats_data = finish_run(user_id, range_name, run, user=user)
        except Exception:
            release_run(user_id, range_name, run.get("run_id"))
            raise

        if stats_data is not None:
            _consume_rerun(user_id, range_name)
            break
        if not _consume_rerun(user_id, range_name):
            break
    return stats_data
