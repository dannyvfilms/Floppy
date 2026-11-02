"""Helpers for making background task loops yield to interactive requests.

Mirrors the deferral semantics proven in backfill_item_metadata_task: always
make some progress, check the shared interactive-request flag between items,
log the deferral, and let the caller re-enqueue the remainder.
"""

import logging
import time

from django.conf import settings

from app.interactive_requests import (
    INTERACTIVE_REQUEST_TTL_SECONDS,
    interactive_request_active,
)

logger = logging.getLogger(__name__)

# The interactive flag outlives the last request by its TTL, so a sooner retry
# only finds it still set, does one item and defers again (#1158).
DEFERRED_RETRY_SECONDS = INTERACTIVE_REQUEST_TTL_SECONDS


_BROKER_LOOK_FAILED_AT = 0.0
_BROKER_RETRY_SECONDS = 60


def higher_priority_task_waiting(queue: str, priority: int = 0) -> bool:
    """Whether a task of ``priority`` is queued and not yet picked up.

    A worker cannot be preempted, so a long task that wants to be polite has to
    look at the broker itself between slices. Redis only: eager runs and any
    other transport report False, and so does a broker error, because a failed
    look must never stop the work it guards. After a failure the broker is
    left alone for a minute, so a broker that is slow to refuse does not add
    its timeout to every slice.
    """
    global _BROKER_LOOK_FAILED_AT  # noqa: PLW0603
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        return False
    if time.monotonic() - _BROKER_LOOK_FAILED_AT < _BROKER_RETRY_SECONDS:
        return False
    try:
        from config.celery import app

        with app.pool.acquire(block=True, timeout=2) as connection:
            channel = connection.default_channel
            key = channel._q_for_pri(queue, priority)
            return int(channel.client.llen(key)) > 0
    except Exception:
        _BROKER_LOOK_FAILED_AT = time.monotonic()
        return False


class CooperativeRun:
    """Iterate work items while yielding to active interactive browser requests.

    Usage:
        run = CooperativeRun("genre_backfill")
        for item in run.iter(items):
            process(item)
        if run.deferred:
            enqueue(run.remaining_ids)
    """

    def __init__(self, label, *, check_every=1, min_progress=1):
        """Configure the run.

        check_every: check the interactive flag every N items.
        min_progress: never defer before this many items were processed, so
        a busy instance still converges.
        """
        self.label = label
        self.check_every = max(1, check_every)
        self.min_progress = max(0, min_progress)
        self.deferred = False
        self.remaining = []

    def iter(self, items):
        """Yield items until exhausted or an interactive request is active."""
        items = list(items)
        for index, item in enumerate(items):
            if (
                index >= self.min_progress
                and index % self.check_every == 0
                and interactive_request_active()
            ):
                self.deferred = True
                self.remaining = items[index:]
                logger.info(
                    "%s_deferred reason=interactive_request_active "
                    "processed=%s remaining=%s",
                    self.label,
                    index,
                    len(self.remaining),
                )
                return
            yield item

    @property
    def remaining_ids(self):
        """Return the ids of items that were not processed."""
        return [item.id for item in self.remaining]

    def reenqueue_if_deferred(self, enqueue):
        """Hand unprocessed item ids back to the given enqueue callable."""
        if self.deferred and self.remaining:
            enqueue(self.remaining_ids, countdown=DEFERRED_RETRY_SECONDS)
