"""Celery tasks for shared outbound delivery and watched-state reconciliation.

All of them run on the default queue. The interactive queue stays dedicated to
user-triggered refreshes, and a library sweep is exactly the kind of
long-running work that must never sit in front of one.
"""

import logging
import os
import time
from contextlib import suppress

from celery import shared_task
from django.utils import timezone

from app.cache_safety import ON_ERROR_SKIP, acquire_lock, release_lock
from integrations.models import (
    CAPABILITY_WATCHED_READ,
    SyncBinding,
    SyncBindingStatus,
    SyncDirection,
)
from integrations.state import outbound

logger = logging.getLogger(__name__)

RECONCILE_LOCK_TIMEOUT = 3600


@shared_task(
    name="Deliver watched state to a provider",
    # Retry is owned by the delivery row's own backoff, not by Celery: every
    # re-attempt has to go through read-first, and a Celery retry would skip it.
    max_retries=0,
)
def deliver_watched_state(delivery_id):
    """Attempt one outbound delivery."""
    return outbound.run_delivery(delivery_id)


@shared_task(name="Send queued deliveries to a batching provider", max_retries=0)
def flush_outbound_batch(binding_id):
    """Send everything due for one binding that takes its writes in batches."""
    return outbound.flush_binding(binding_id)


# The sweep makes provider HTTP calls inline, so it can run long; it is bounded
# so a wedged one frees the single background child instead of pinning it for
# the global limit. Whatever it abandoned stays due and is picked up next tick.
@shared_task(
    name="Sweep pending watched state deliveries",
    soft_time_limit=240,
    time_limit=300,
)
def sweep_watched_state_deliveries(limit=100):
    """Pick up deliveries whose enqueue kick was lost, and due retries.

    The outbox is the source of truth for what still needs sending, so a
    dropped broker message costs latency rather than correctness.
    """
    started = time.monotonic()
    logger.info("sweep_watched_state start pid=%s limit=%s", os.getpid(), limit)
    swept = outbound.sweep_due_deliveries(limit=limit)

    from integrations import connection_health
    from integrations.models import TMDbAccount
    from integrations.state.adapters.base import AdapterError
    from integrations.state.adapters.tmdb import TMDbRatingAdapter

    for account in (
        TMDbAccount.objects.exclude(connection_broken=False)
        .select_related("user")
        .iterator(chunk_size=100)
    ):
        if connection_health.due_for_probe(account):
            adapter = TMDbRatingAdapter(account)
            with suppress(AdapterError):
                adapter._request("GET", "account")

    logger.info(
        "sweep_watched_state finish swept=%s duration_ms=%.0f",
        swept,
        (time.monotonic() - started) * 1000,
    )
    return swept


@shared_task(name="Reconcile watched state with a provider")
def reconcile_watched_state(binding_id=None):
    """Compare provider state against canonical state for one binding.

    Reconciliation, not webhooks, is what catches manual changes: most
    providers have no event for "user ticked watched", so the only way to
    notice is to look.
    """
    bindings = (
        SyncBinding.objects.filter(pk=binding_id)
        if binding_id
        else SyncBinding.objects.filter(status=SyncBindingStatus.ACTIVE.value)
    )

    reconciled = 0
    for binding in bindings:
        if not binding.allows(SyncDirection.INBOUND.value, CAPABILITY_WATCHED_READ):
            continue

        lock_key = f"watch_state_reconcile:{binding.pk}"
        # Fail closed: a reconciliation pass is maintenance, and running two at
        # once against one provider wastes its rate limit for no benefit.
        if not acquire_lock(
            lock_key,
            timeout=RECONCILE_LOCK_TIMEOUT,
            on_error=ON_ERROR_SKIP,
            value=str(binding.pk),
        ):
            continue

        try:
            reconciled += _reconcile_binding(binding)
        finally:
            release_lock(lock_key)

    return reconciled


def _reconcile_binding(binding):
    """Reconcile one binding, recording when it last succeeded.

    Provider enumeration lands with the per-provider adapters. Until then this
    records the attempt without inventing observations: a reconciliation that
    guessed would be worse than one that has not run, because the engine treats
    an observation as evidence.
    """
    binding.last_reconciled_at = timezone.now()
    binding.save(update_fields=["last_reconciled_at", "updated_at"])
    return 0
