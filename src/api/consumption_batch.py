"""Run a caller-named batch of consumption creates one item at a time.

Each item commits in its own short transaction (the consumption and its
``ConsumptionBatchItem`` row together), so one bad item never rolls back the
others and the SQLite writer lock is released between items.
"""

import logging
import time
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from app.db_retry import run_retryable_db_operation
from app.models import ConsumptionBatchItem
from integrations.delivery import calculate_payload_digest

from .consumption_create import (
    ConsumptionError,
    create_provider_consumption,
    normalize_body,
    plan_consumption,
)

logger = logging.getLogger(__name__)

Outcome = ConsumptionBatchItem.Outcome
TERMINAL = (Outcome.CREATED, Outcome.SKIPPED)
# A claimed item that never finished committed nothing (create + row are one
# transaction), so after this long it is safe to hand out again.
STALE_RUNNING = timedelta(minutes=15)
INTER_ITEM_PAUSE_SECONDS = 0.05


def max_items():
    """Return the per-request item cap."""
    return getattr(settings, "CONSUMPTION_BATCH_MAX_ITEMS", 100)


def item_digest(spec):
    """Return the digest that identifies a requested item's content."""
    return calculate_payload_digest(spec)


def plan_result(user, spec):
    """Return the dry-run result for one item. Writes nothing."""
    plan = plan_consumption(user, spec)
    result = {
        "client_ref": spec["client_ref"],
        "outcome": plan.outcome,
        "existing": plan.existing,
    }
    if plan.item is not None:
        result["item"] = {
            "media_id": plan.item.media_id,
            "source": plan.item.source,
            "title": plan.item.title,
        }
    for key in ("errors", "detail", "consumption_id"):
        value = getattr(plan, key, None)
        if value:
            result[key] = value
    if "progress" in spec:
        result["progress_source"] = "request"
    return result


def _finish(row, outcome, consumption_id=None, detail=None):
    row.outcome = outcome
    row.consumption_id = consumption_id
    row.detail = detail or {}
    row.save(update_fields=["outcome", "consumption_id", "detail", "updated_at"])


def _claim(row_id):
    """Take a pending/failed row; returns False if another worker has it."""
    return bool(
        ConsumptionBatchItem.objects.filter(
            pk=row_id,
            outcome__in=[Outcome.PENDING, Outcome.FAILED],
        ).update(outcome=Outcome.RUNNING, updated_at=timezone.now()),
    )


def release_stale(user, operation_id):
    """Return interrupted items to pending so a resubmit can finish them."""
    return ConsumptionBatchItem.objects.filter(
        user=user,
        operation_id=operation_id,
        outcome=Outcome.RUNNING,
        updated_at__lt=timezone.now() - STALE_RUNNING,
    ).update(outcome=Outcome.PENDING)


def _apply(user, row, spec):
    """Create (or skip) one item inside one transaction."""
    plan = plan_consumption(user, spec)
    if plan.outcome == "skip":
        _finish(row, Outcome.SKIPPED, plan.consumption_id, {"detail": plan.detail})
        return
    if plan.outcome not in ("would_create", "would_append"):
        _finish(
            row,
            Outcome.FAILED,
            None,
            {
                "reason": plan.outcome,
                "detail": plan.detail,
                "errors": plan.errors,
            },
        )
        return
    body = normalize_body(
        spec["media_type"],
        {k: v for k, v in spec.items() if k not in {"client_ref", "skip_if_existing"}},
    )
    with transaction.atomic():
        try:
            instance = create_provider_consumption(user, spec["media_type"], body)
        except ConsumptionError as error:
            _finish(row, Outcome.FAILED, None, {"reason": "invalid", **error.payload})
            return
        _finish(row, Outcome.CREATED, instance.id, {"detail": plan.outcome})


def run_batch(user, operation_id, specs):
    """Process every unfinished item of an operation; return its rows' results."""
    by_ref = {spec["client_ref"]: spec for spec in specs}
    rows = ConsumptionBatchItem.objects.filter(
        user=user,
        operation_id=operation_id,
        client_ref__in=list(by_ref),
    ).order_by("id")
    for row in rows:
        if row.outcome in TERMINAL or not _claim(row.pk):
            continue
        row.refresh_from_db()
        try:
            run_retryable_db_operation(
                lambda row=row: _apply(user, row, by_ref[row.client_ref]),
                mode="required",
                operation_name="consumption_batch_item",
            )
        except Exception as error:
            logger.warning("Batch item %s failed: %s", row.client_ref, error)
            _finish(
                row,
                Outcome.FAILED,
                None,
                {"reason": "error", "detail": type(error).__name__},
            )
        time.sleep(INTER_ITEM_PAUSE_SECONDS)
    return operation_results(user, operation_id)


def operation_results(user, operation_id):
    """Return the stored per-item results for an operation."""
    results = []
    for row in ConsumptionBatchItem.objects.filter(
        user=user,
        operation_id=operation_id,
    ).order_by("id"):
        stale = (
            row.outcome == Outcome.RUNNING
            and row.updated_at < timezone.now() - STALE_RUNNING
        )
        result = {
            "client_ref": row.client_ref,
            "outcome": "interrupted" if stale else row.outcome,
        }
        if row.consumption_id is not None:
            result["consumption_id"] = row.consumption_id
        if row.detail:
            result["detail"] = row.detail
        results.append(result)
    return results
