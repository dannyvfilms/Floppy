# FORK: plan and apply many consumption creates safely (#1614). Dry-run is
# synchronous and writes nothing; execution is a per-item, resumable Celery task.
import logging
from http import HTTPStatus as HTTP  # noqa: N814

from django.conf import settings
from django.db import IntegrityError, transaction
from drf_spectacular.utils import extend_schema
from rest_framework import views as drf_views
from rest_framework.response import Response

from app.models import ConsumptionBatchItem
from app.tasks_bulk_plays import bulk_consumption_batch_task

from . import consumption_batch

logger = logging.getLogger(__name__)

OPERATION_ID_MAX = 64
CLIENT_REF_MAX = 255


def _validate(data):
    """Return ``(operation_id, execute, items, error_response)``."""
    if not isinstance(data, dict):
        return None, False, None, "Body must be a JSON object."
    items = data.get("items")
    if not isinstance(items, list) or not items:
        return None, False, None, "`items` must be a non-empty list."
    limit = consumption_batch.max_items()
    if len(items) > limit:
        return None, False, None, f"At most {limit} items per request."
    execute = data.get("execute", False)
    if not isinstance(execute, bool):
        return None, False, None, "`execute` must be true or false."
    operation_id = str(data.get("operation_id") or "")
    if execute and not operation_id:
        return None, False, None, "`operation_id` is required to execute."
    if len(operation_id) > OPERATION_ID_MAX:
        return (
            None,
            False,
            None,
            f"`operation_id` is at most {OPERATION_ID_MAX} characters.",
        )
    seen = set()
    for item in items:
        ref = item.get("client_ref") if isinstance(item, dict) else None
        if not isinstance(ref, str) or not ref or len(ref) > CLIENT_REF_MAX:
            return None, False, None, "Every item needs a `client_ref` string."
        if ref in seen:
            return None, False, None, f"Duplicate client_ref `{ref}`."
        seen.add(ref)
    return operation_id, execute, items, None


# /api/v1/consumptions/batch/
class ConsumptionBatchView(drf_views.APIView):
    """Plan (default) or apply a batch of historical consumptions."""

    @extend_schema(
        operation_id="planOrApplyConsumptionBatch",
        request=None,
        responses={200: None, 202: None},
    )
    def post(self, request):
        """Dry-run each item, or with `execute: true` queue the writes.

        Dry-run returns a per-item `outcome` (`would_create`, `would_append`,
        `skip`, `ambiguous`, `invalid`, `unavailable`, `not_found`) plus the
        item's `existing` consumptions so the caller decides what counts as a
        duplicate. Execution requires a caller `operation_id`; resubmitting it
        only finishes unfinished items.
        """
        operation_id, execute, items, error = _validate(request.data)
        if error:
            return Response({"detail": error}, status=HTTP.BAD_REQUEST)

        if not execute:
            results = [consumption_batch.plan_result(request.user, i) for i in items]
            return Response({"dry_run": True, "results": results}, status=HTTP.OK)

        digests = {i["client_ref"]: consumption_batch.item_digest(i) for i in items}
        try:
            with transaction.atomic():
                existing = {
                    row.client_ref: row
                    for row in ConsumptionBatchItem.objects.filter(
                        user=request.user,
                        operation_id=operation_id,
                    )
                }
                changed = [
                    ref
                    for ref, row in existing.items()
                    if ref in digests and row.payload_digest != digests[ref]
                ]
                if changed:
                    return Response(
                        {
                            "detail": "operation_id was used with different items.",
                            "code": "idempotency_conflict",
                            "client_refs": changed,
                        },
                        status=HTTP.CONFLICT,
                    )
                ConsumptionBatchItem.objects.bulk_create(
                    [
                        ConsumptionBatchItem(
                            user=request.user,
                            operation_id=operation_id,
                            client_ref=ref,
                            payload_digest=digest,
                        )
                        for ref, digest in digests.items()
                        if ref not in existing
                    ],
                )
        except IntegrityError:
            # A concurrent identical submit won; its rows are the operation.
            logger.info("Consumption batch %s raced; reusing rows", operation_id)

        consumption_batch.release_stale(request.user, operation_id)
        results = consumption_batch.operation_results(request.user, operation_id)
        unfinished = [r for r in results if r["outcome"] not in ("created", "skipped")]
        if not unfinished:
            return Response(
                {"operation_id": operation_id, "results": results},
                status=HTTP.OK,
            )
        task = bulk_consumption_batch_task.apply_async(
            kwargs={
                "user_id": request.user.id,
                "operation_id": operation_id,
                "items": items,
            },
            priority=settings.CELERY_TASK_PRIORITY_INTERACTIVE,
        )
        return Response(
            {"operation_id": operation_id, "task_id": task.id},
            status=HTTP.ACCEPTED,
        )


# /api/v1/consumptions/batch/[operation_id]/
class ConsumptionBatchDetailView(drf_views.APIView):
    """Report an operation's stored per-item results."""

    @extend_schema(operation_id="getConsumptionBatch", responses={200: None})
    def get(self, request, operation_id):
        """Return every item's outcome and the counts per outcome."""
        results = consumption_batch.operation_results(request.user, operation_id)
        if not results:
            return Response({"detail": "Operation not found."}, status=HTTP.NOT_FOUND)
        counts = {}
        for result in results:
            counts[result["outcome"]] = counts.get(result["outcome"], 0) + 1
        return Response(
            {"operation_id": operation_id, "counts": counts, "results": results},
            status=HTTP.OK,
        )
