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
from django.utils import timezone

from app.models.watch_state import WatchStateChange
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

    user_ids = (
        WatchStateChange.objects.values_list("user_id", flat=True).distinct().iterator()
    )
    for user_id in list(user_ids):
        user = get_user_model().objects.filter(pk=user_id).first()
        if user is None:
            continue

        watermark = compaction_watermark(user, stale_before=cutoff)
        if watermark is None:
            # A live binding is still owed changes, or has applied nothing.
            continue

        deleted_total += _compact_for_user(user, watermark, cutoff, batch_size)

    logger.info(
        "change_log_compaction deleted=%s retention_days=%s",
        deleted_total,
        retention_days,
    )
    return deleted_total


def _compact_for_user(user, watermark, cutoff, batch_size):
    """Delete one user's applied, aged-out changes in bounded batches."""
    deleted = 0
    for _ in range(MAX_BATCHES_PER_USER):
        ids = list(
            WatchStateChange.objects.filter(
                user=user,
                sequence__lte=watermark,
                created_at__lt=cutoff,
            )
            .values_list("pk", flat=True)[:batch_size],
        )
        if not ids:
            break
        removed, _detail = WatchStateChange.objects.filter(pk__in=ids).delete()
        deleted += removed
        if len(ids) < batch_size:
            break
    return deleted
