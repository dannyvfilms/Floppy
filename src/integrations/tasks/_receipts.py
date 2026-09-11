"""Retention for idempotency receipts.

``IntegrationEventReceipt`` grows with every mutating request a client retries
against. Nothing trimmed it, so the table grew without bound. Compaction runs on
the default queue: the interactive queue stays dedicated to user-triggered work.
"""

import logging

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from integrations.models import IntegrationEventReceipt

logger = logging.getLogger(__name__)

COMPACT_RECEIPTS_TASK_NAME = "integrations.compact_integration_event_receipts"

# Bounded so one sweep cannot hold a long write lock. SQLite takes a database
# level lock for the delete, and a large unbounded DELETE blocks every writer.
COMPACTION_BATCH_SIZE = 500
MAX_BATCHES_PER_RUN = 40


@shared_task(name=COMPACT_RECEIPTS_TASK_NAME)
def compact_integration_event_receipts(retention_days=None, batch_size=None):
    """Delete receipts past the retention window, in bounded batches.

    Returns the number of rows deleted so the count survives the rows: once a
    receipt is gone the only remaining evidence it existed is this figure.
    """
    if retention_days is None:
        retention_days = settings.INTEGRATION_RECEIPT_RETENTION_DAYS
    if batch_size is None:
        batch_size = COMPACTION_BATCH_SIZE

    cutoff = timezone.now() - timezone.timedelta(days=retention_days)
    deleted_total = 0

    for _ in range(MAX_BATCHES_PER_RUN):
        expired_ids = list(
            IntegrationEventReceipt.objects.filter(created_at__lt=cutoff)
            .values_list("pk", flat=True)[:batch_size],
        )
        if not expired_ids:
            break
        deleted, _detail = IntegrationEventReceipt.objects.filter(
            pk__in=expired_ids,
        ).delete()
        deleted_total += deleted
        if len(expired_ids) < batch_size:
            break

    remaining = IntegrationEventReceipt.objects.count()
    logger.info(
        "receipt_compaction deleted=%s remaining=%s retention_days=%s",
        deleted_total,
        remaining,
        retention_days,
    )
    return deleted_total
