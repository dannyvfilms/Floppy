"""IGDB rating backfill: queryset builder, enqueue, drain queue, and reconcile tasks.

Populates Item.igdb_user_rating / Item.provider_rating (critic) for games that were
tracked before the IGDB rating/aggregated_rating field split, whose cached metadata
predates it and would otherwise never refresh.
"""

import logging

from celery import shared_task
from django.conf import settings
from django.core.cache import cache

from app import backfill_queue, metadata_utils
from app.log_safety import exception_summary
from app.models import Item, MediaTypes, MetadataBackfillField, Sources
from app.providers import services
from app.task_cooperation import CooperativeRun
from app.tasks_backfill_state import (
    _apply_backfill_state_filters,
    _filter_backfill_item_ids,
    _normalize_item_ids,
    _record_backfill_failure,
    _record_backfill_success,
)

logger = logging.getLogger(__name__)

BACKGROUND_TASK_PRIORITY = getattr(settings, "CELERY_TASK_PRIORITY_BACKGROUND", 9)

IGDB_RATINGS_BACKFILL_VERSION = 1
IGDB_RATINGS_BACKFILL_QUEUE_TTL = 60 * 60  # 1 hour
IGDB_RATINGS_BACKFILL_ITEMS_QUEUE_KEY = "igdb_ratings_backfill_items_queue"
IGDB_RATINGS_BACKFILL_ITEMS_SCHEDULED_KEY = "igdb_ratings_backfill_items_scheduled"


def _igdb_rating_items_queryset():
    from app.models import MetadataBackfillState

    queryset = Item.objects.filter(
        source=Sources.IGDB.value,
        media_type=MediaTypes.GAME.value,
        metadata_fetched_at__isnull=False,
    )
    queryset = _apply_backfill_state_filters(
        queryset, MetadataBackfillField.IGDB_RATINGS
    )
    completed_ids = MetadataBackfillState.objects.filter(
        field=MetadataBackfillField.IGDB_RATINGS,
        give_up=False,
        fail_count=0,
        last_success_at__isnull=False,
        strategy_version__gte=IGDB_RATINGS_BACKFILL_VERSION,
    ).values("item_id")
    return queryset.exclude(id__in=completed_ids)


def count_igdb_rating_backfill_items() -> int:
    """Return the count igdb rating backfill items."""
    return _igdb_rating_items_queryset().count()


def _populate_igdb_ratings_for_items(items):
    updated_count = 0
    error_count = 0
    run = CooperativeRun("igdb_ratings_backfill")
    for item in run.iter(items):
        try:
            metadata = services.get_media_metadata(
                item.media_type,
                item.media_id,
                item.source,
            )
            if not isinstance(metadata, dict):
                error_count += 1
                _record_backfill_failure(
                    item, MetadataBackfillField.IGDB_RATINGS, "no metadata"
                )
                continue

            update_fields = metadata_utils.apply_item_metadata(
                item,
                metadata,
                include_core=False,
                include_provider=True,
                include_release=False,
            )
            if update_fields:
                item.save(update_fields=update_fields)

            _record_backfill_success(
                item,
                MetadataBackfillField.IGDB_RATINGS,
                strategy_version=IGDB_RATINGS_BACKFILL_VERSION,
            )
            updated_count += 1
        except Exception as exc:
            error_count += 1
            logger.exception(
                "Error backfilling IGDB ratings for %s: %s",
                item.title,
                exception_summary(exc),  # noqa: TRY401  # exception_summary() is the project's sanitised rendering
            )
            _record_backfill_failure(
                item,
                MetadataBackfillField.IGDB_RATINGS,
                f"exception: {exception_summary(exc)}",
            )

    run.reenqueue_if_deferred(enqueue_igdb_rating_backfill_items)
    logger.info(
        "IGDB ratings backfill batch completed: %s updated, %s errors",
        updated_count,
        error_count,
    )
    return updated_count, error_count


@shared_task(name="app.tasks.populate_igdb_rating_data_for_items")
def populate_igdb_rating_data_for_items(item_ids: list[int]):
    """Backfill IGDB ratings for a targeted list of item IDs."""
    normalized = _normalize_item_ids(item_ids)
    if not normalized:
        return {"updated": 0, "errors": 0, "message": "No item IDs provided"}

    items_to_update = list(_igdb_rating_items_queryset().filter(id__in=normalized))
    if not items_to_update:
        return {
            "updated": 0,
            "errors": 0,
            "message": "No matching items require IGDB ratings backfill",
        }

    updated_count, error_count = _populate_igdb_ratings_for_items(items_to_update)
    return {
        "updated": updated_count,
        "errors": error_count,
        "message": f"Processed {len(items_to_update)} targeted items",
    }


def enqueue_igdb_rating_backfill_items(item_ids, countdown=10):
    """Return the enqueue igdb rating backfill items."""
    normalized = _normalize_item_ids(item_ids)
    normalized = _filter_backfill_item_ids(
        normalized, MetadataBackfillField.IGDB_RATINGS
    )
    if not normalized:
        return 0
    queued = backfill_queue.enqueue(
        IGDB_RATINGS_BACKFILL_ITEMS_QUEUE_KEY,
        IGDB_RATINGS_BACKFILL_ITEMS_SCHEDULED_KEY,
        normalized,
        ttl=IGDB_RATINGS_BACKFILL_QUEUE_TTL,
        drain_task=populate_igdb_rating_backfill_queue,
        countdown=countdown,
    )
    if not queued:
        logger.debug("IGDB ratings backfill queue unavailable, dispatching directly")
        populate_igdb_rating_data_for_items.apply_async(
            args=[normalized], countdown=countdown
        )
    return len(normalized)


@shared_task(name="app.tasks.populate_igdb_rating_backfill_queue")
def populate_igdb_rating_backfill_queue(batch_size: int = 25):
    """Drain the IGDB ratings backfill queue and process items in small batches."""
    batch, more_remaining = backfill_queue.take(
        IGDB_RATINGS_BACKFILL_ITEMS_QUEUE_KEY,
        IGDB_RATINGS_BACKFILL_ITEMS_SCHEDULED_KEY,
        batch_size,
    )
    if not batch:
        return {"processed": 0, "message": "No queued IGDB rating items"}

    if more_remaining:
        backfill_queue.reschedule(
            IGDB_RATINGS_BACKFILL_ITEMS_SCHEDULED_KEY,
            populate_igdb_rating_backfill_queue,
        )

    return populate_igdb_rating_data_for_items(batch)


@shared_task(name="app.tasks.reconcile_igdb_rating_backfill")
def reconcile_igdb_rating_backfill(
    strategy_version: int | None = None,
    batch_size: int = 200,
):
    """Queue all current IGDB-ratings-backfill candidates without waiting for the nightly sweep."""
    batch_size = max(int(batch_size), 1)
    last_item_id = 0
    selected = 0
    enqueued = 0

    while True:
        batch_ids = list(
            _igdb_rating_items_queryset()
            .filter(id__gt=last_item_id)
            .order_by("id")
            .values_list("id", flat=True)[:batch_size],
        )
        if not batch_ids:
            break

        last_item_id = batch_ids[-1]
        selected += len(batch_ids)
        enqueued += enqueue_igdb_rating_backfill_items(batch_ids, countdown=10)

    if strategy_version is not None:
        cache.set(
            f"igdb_ratings_backfilled_v{strategy_version}",
            "done",
            timeout=None,
        )

    logger.info(
        "reconcile_igdb_rating_backfill selected=%d enqueued=%d version=%s",
        selected,
        enqueued,
        strategy_version,
    )
    return {"selected": selected, "enqueued": enqueued}
