"""Decide whether a whole-library reconcile sweep needs to run at all.

The genre and watch-provider reconcilers ran every five minutes, and each run
began with a ``NOT IN (subquery)`` ``.exists()`` over the whole ``Item`` table
before enqueueing every remaining candidate. Three things conspired to make that
permanent rather than transitional (issue #521):

* The ``"pending"`` cache marker that was supposed to suppress overlapping runs
  was only ever written by ``AppConfig.ready()``, with a 300 second TTL, so a
  beat-triggered sweep never saw it.
* The ``"done"`` marker *was* written, but the beat task logged
  ``stale_cache_done`` and ran anyway.
* Both markers lived in the cache, so a Redis restart erased any memory of
  having finished.

So the state moves to the database, the completion check happens *before* any
expensive query, and a sweep that finds nothing to do backs off instead of
retrying at the same cadence forever.

The cache still provides the mutex, because that is what a lock wants to be -
short-lived and automatically released. ``last_run_at`` is the fallback when the
cache can't be reached, which is deliberately the conservative direction: better
to skip a sweep than to run several at once on a host already under pressure.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from app import cache_safety
from app.models import BackfillReconcileState

logger = logging.getLogger(__name__)

# Backoff for sweeps that keep finding nothing: 30m, 1h, 2h, 4h, then 6h.
BACKOFF_BASE_SECONDS = 30 * 60
BACKOFF_MAX_SECONDS = 6 * 60 * 60
# How long a sweep is presumed to still be running when the cache lock is
# unavailable. Comfortably longer than a sweep should take, since the cost of
# being wrong in this direction is only a delayed sweep.
ASSUMED_RUN_SECONDS = 30 * 60
LOCK_TIMEOUT_SECONDS = 30 * 60


def _lock_key(key: str) -> str:
    return f"reconcile_lock_{key}"


def get_state(key: str, strategy_version: int) -> BackfillReconcileState:
    """Return the state row for a key, resetting it if the strategy changed."""
    state, created = BackfillReconcileState.objects.get_or_create(
        key=key,
        defaults={"strategy_version": strategy_version},
    )
    if not created and state.strategy_version != strategy_version:
        # A new strategy version means previously-reconciled items may need
        # revisiting, so start over from the top.
        state.strategy_version = strategy_version
        state.completed_at = None
        state.consecutive_no_op_runs = 0
        state.last_cursor_item_id = 0
        state.next_run_after = None
        state.save(
            update_fields=[
                "strategy_version",
                "completed_at",
                "consecutive_no_op_runs",
                "last_cursor_item_id",
                "next_run_after",
                "updated_at",
            ],
        )
    return state


def should_run(key: str, strategy_version: int) -> BackfillReconcileState | None:
    """Return the state to work with, or None if this sweep should be skipped.

    Deliberately answers using only the state row, with no query against Item
    and no cache read: on a large library that completion check was itself the
    expensive part, and it ran every five minutes whether or not there was
    anything left to do.
    """
    state = get_state(key, strategy_version)
    now = timezone.now()

    if state.completed_at is not None:
        logger.debug("%s reconcile already complete for v%s", key, strategy_version)
        return None

    if state.next_run_after and state.next_run_after > now:
        logger.debug("%s reconcile backing off until %s", key, state.next_run_after)
        return None

    return state


def acquire(key: str, state: BackfillReconcileState) -> bool:
    """Take the sweep lock. Returns False if another sweep holds it.

    Fails closed when the cache is unavailable: a duplicate whole-library sweep
    is exactly the load this module exists to prevent. ``last_run_at`` provides
    a second guard so two sweeps can't overlap even without a working cache.
    """
    now = timezone.now()
    if (
        state.last_run_at
        and (now - state.last_run_at).total_seconds() < ASSUMED_RUN_SECONDS
        and state.next_run_after
        and state.next_run_after > now
    ):
        return False

    if not cache_safety.acquire_lock(
        _lock_key(key),
        timeout=LOCK_TIMEOUT_SECONDS,
        on_error=cache_safety.ON_ERROR_SKIP,
    ):
        logger.debug("%s reconcile lock held or cache unavailable", key)
        return False

    BackfillReconcileState.objects.filter(pk=state.pk).update(
        last_run_at=now,
        # Claim a window up front so a crashed sweep can't be immediately
        # retried by the next beat tick.
        next_run_after=now + timedelta(seconds=ASSUMED_RUN_SECONDS),
    )
    state.last_run_at = now
    return True


def release(key: str) -> None:
    """Release the sweep lock."""
    cache_safety.release_lock(_lock_key(key))


@transaction.atomic
def mark_complete(key: str, strategy_version: int) -> None:
    """Record that this strategy version has no remaining candidates."""
    BackfillReconcileState.objects.filter(
        key=key,
        strategy_version=strategy_version,
    ).update(
        completed_at=timezone.now(),
        next_run_after=None,
        consecutive_no_op_runs=0,
        last_cursor_item_id=0,
        updated_at=timezone.now(),
    )
    logger.info("%s reconcile complete for v%s", key, strategy_version)


def mark_progress(
    key: str,
    strategy_version: int,
    *,
    cursor: int,
    enqueued: int,
) -> None:
    """Record a sweep that made progress, scheduling the next pass.

    A sweep that enqueued work is followed up promptly; one that scanned but
    found nothing to enqueue backs off, since the same scan will most likely
    find nothing again.
    """
    now = timezone.now()
    updates = {"last_cursor_item_id": cursor, "updated_at": now}

    if enqueued:
        updates["consecutive_no_op_runs"] = 0
        updates["next_run_after"] = now + timedelta(seconds=BACKOFF_BASE_SECONDS)
    else:
        state = BackfillReconcileState.objects.filter(
            key=key,
            strategy_version=strategy_version,
        ).first()
        misses = (state.consecutive_no_op_runs if state else 0) + 1
        delay = min(BACKOFF_BASE_SECONDS * 2 ** (misses - 1), BACKOFF_MAX_SECONDS)
        updates["consecutive_no_op_runs"] = misses
        updates["next_run_after"] = now + timedelta(seconds=delay)

    BackfillReconcileState.objects.filter(
        key=key,
        strategy_version=strategy_version,
    ).update(**updates)
