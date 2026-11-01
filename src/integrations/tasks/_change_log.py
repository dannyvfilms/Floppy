"""Retention for the watched-state change log.

``WatchStateChange`` is append-only and nothing trimmed it, so it grew for the
life of the instance. It cannot simply be aged out either: a change is still
owed to any binding that has not applied it, and deleting it early makes a
client silently miss a state movement.

So compaction is bounded by two things at once — the retention window, and the
lowest checkpoint any live binding has reached.
"""

import logging

from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Max
from django.utils import timezone

from app.models import ProgressChange, WatchStateSequence
from app.models.watch_state import WatchStateChange
from app.services.sync_lock import state_transaction
from integrations.models import SyncBinding
from integrations.state.checkpoints import compaction_watermark

logger = logging.getLogger(__name__)

COMPACT_CHANGE_LOG_TASK_NAME = "integrations.compact_watch_state_changes"

COMPACTION_BATCH_SIZE = 500
MAX_BATCHES_PER_USER = 20


@shared_task(name=COMPACT_CHANGE_LOG_TASK_NAME)
def compact_watch_state_changes(retention_days=None, batch_size=None):
    """Delete change rows that are both aged out and applied everywhere.

    Returns the number of rows deleted, so the figure survives the rows.
    """
    if retention_days is None:
        retention_days = settings.WATCH_STATE_CHANGE_RETENTION_DAYS
    if batch_size is None:
        batch_size = COMPACTION_BATCH_SIZE

    cutoff = timezone.now() - timezone.timedelta(days=retention_days)
    deleted_total = 0

    user_ids = WatchStateSequence.objects.values_list("user_id", flat=True)
    # Include old manually recorded logs that predate an allocator row.
    user_ids = set(user_ids) | set(WatchStateChange.objects.values_list("user_id", flat=True)) | set(ProgressChange.objects.values_list("user_id", flat=True))
    for user_id in sorted(user_ids):
        user = get_user_model().objects.filter(pk=user_id).first()
        if user is None:
            continue
        with state_transaction(user_id) as row:
            watermark = compaction_watermark(user, stale_before=cutoff)
            # Recent native connections without proof retain legacy events.
            native_waiting = SyncBinding.objects.filter(
                user=user, status="active", kill_switch=False,
                disabled_at__isnull=True, updated_at__gte=cutoff,
            ).exists()
            for model, field in ((WatchStateChange, "watched_cursor_floor"), (ProgressChange, "progress_cursor_floor")):
                aged = model.objects.filter(user=user, created_at__lt=cutoff)
                floor = aged.aggregate(value=Max("sequence"))["value"]
                if floor is not None and floor > getattr(row, field):
                    setattr(row, field, floor)
                    row.save(update_fields=[field])
                if model is WatchStateChange:
                    if watermark is None and native_waiting:
                        continue
                    if watermark is not None:
                        aged = aged.filter(sequence__lte=watermark)
                    aged = aged.exclude(deliveries__status__in=["pending", "in_flight", "failed"])
                for _ in range(MAX_BATCHES_PER_USER):
                    ids = list(aged.order_by("sequence").values_list("pk", flat=True)[:batch_size])
                    if not ids:
                        break
                    removed, _ = model.objects.filter(pk__in=ids).delete()
                    deleted_total += removed
                    if len(ids) < batch_size:
                        break

    logger.info(
        "change_log_compaction deleted=%s retention_days=%s",
        deleted_total,
        retention_days,
    )
    return deleted_total
