"""Trakt popularity backfill Celery tasks.

Extracted from tasks.py. Re-exported from app.tasks for backward compatibility.
Tasks use deferred imports for private helpers that remain in tasks.py to avoid
circular imports (tasks.py re-exports these tasks).
"""

import logging

from celery import shared_task
from django.core.cache import cache

from app import backfill_queue
from app.log_safety import exception_summary
from app.models import TRAKT_POPULARITY_BACKFILL_VERSION, MetadataBackfillField
from app.services import trakt_popularity as trakt_popularity_service
from app.task_cooperation import CooperativeRun

logger = logging.getLogger(__name__)

# Queue constants — moved from tasks.py (only used by this module's tasks).
TRAKT_POPULARITY_BACKFILL_QUEUE_TTL = 60 * 60  # 1 hour
TRAKT_POPULARITY_BACKFILL_ITEMS_QUEUE_KEY = "trakt_popularity_backfill_items_queue"
TRAKT_POPULARITY_BACKFILL_ITEMS_SCHEDULED_KEY = (
    "trakt_popularity_backfill_items_scheduled"
)

# Reconcile works in bounded chunks so its resident cost is a function of the
# chunk, not of library size. Kept under 999: that is
# SQLITE_MAX_VARIABLE_NUMBER before SQLite 3.32, and an `id__in` of one
# parameter per id is not batched by Django the way bulk_update is.
RECONCILE_CHUNK_SIZE = 900
RECONCILE_UPDATE_BATCH_SIZE = 500


def enqueue_trakt_popularity_backfill_items(item_ids, countdown=10, *, force=False):
    """Queue item IDs for Trakt popularity backfill via the cache-based queue."""
    # Deferred to avoid circular import: tasks.py re-exports this module.
    from app.tasks import (
        _filter_backfill_item_ids,
        _normalize_item_ids,
    )

    normalized = _normalize_item_ids(item_ids)
    normalized = _filter_backfill_item_ids(
        normalized, MetadataBackfillField.TRAKT_POPULARITY
    )
    if not normalized:
        return 0
    queued = backfill_queue.enqueue(
        TRAKT_POPULARITY_BACKFILL_ITEMS_QUEUE_KEY,
        TRAKT_POPULARITY_BACKFILL_ITEMS_SCHEDULED_KEY,
        normalized,
        ttl=TRAKT_POPULARITY_BACKFILL_QUEUE_TTL,
        drain_task=populate_trakt_popularity_backfill_queue,
        countdown=countdown,
        drain_kwargs={"force": force},
    )
    if not queued:
        logger.debug("Trakt popularity backfill queue unavailable, dispatching directly")
        populate_trakt_popularity_data_for_items.apply_async(
            args=[normalized],
            kwargs={"force": force},
            countdown=countdown,
        )
    return len(normalized)


@shared_task(name="app.tasks.populate_trakt_popularity_data_for_items")
def populate_trakt_popularity_data_for_items(
    item_ids: list[int],
    delay_seconds: float = 0.0,
    force: bool = False,
):
    """Refresh persisted Trakt popularity metadata for targeted items."""
    # Deferred to avoid circular import: tasks.py re-exports this module.
    from app.tasks import (
        _filter_backfill_item_ids,
        _normalize_item_ids,
        _record_backfill_failure,
        _record_backfill_success,
    )

    normalized = _normalize_item_ids(item_ids)
    normalized = _filter_backfill_item_ids(
        normalized, MetadataBackfillField.TRAKT_POPULARITY
    )
    if not normalized:
        return {"updated": 0, "errors": 0, "message": "No item IDs provided"}
    if not trakt_popularity_service.trakt_provider.is_configured():
        return {"updated": 0, "errors": 0, "message": "TRAKT_API is not configured"}

    items = list(
        trakt_popularity_service.tracked_items_queryset().filter(id__in=normalized),
    )
    if not force:
        items = [item for item in items if trakt_popularity_service.needs_refresh(item)]
    if not items:
        logger.info("No targeted items need Trakt popularity data")
        return {
            "updated": 0,
            "errors": 0,
            "message": "No targeted items need Trakt popularity data",
        }

    updated_count = 0
    error_count = 0
    run = CooperativeRun("trakt_popularity_backfill")
    for item in run.iter(items):
        try:
            trakt_popularity_service.refresh_trakt_popularity(
                item,
                route_media_type=trakt_popularity_service.route_media_type_for_item(
                    item
                ),
                force=force,
            )
            _record_backfill_success(
                item,
                MetadataBackfillField.TRAKT_POPULARITY,
                strategy_version=TRAKT_POPULARITY_BACKFILL_VERSION,
            )
            updated_count += 1

            if delay_seconds > 0:
                import time

                time.sleep(delay_seconds)
        except Exception as exc:
            error_count += 1
            logger.warning(
                "trakt_popularity_backfill_error item_id=%s media_id=%s error=%s",
                item.id,
                item.media_id,
                exception_summary(exc),
            )
            _record_backfill_failure(
                item,
                MetadataBackfillField.TRAKT_POPULARITY,
                f"exception: {exception_summary(exc)}",
            )

    run.reenqueue_if_deferred(
        lambda ids, countdown: enqueue_trakt_popularity_backfill_items(
            ids, countdown=countdown, force=force
        ),
    )

    return {
        "updated": updated_count,
        "errors": error_count,
        "message": f"Processed {len(items)} targeted items",
    }


@shared_task(name="app.tasks.populate_trakt_popularity_backfill_queue")
def populate_trakt_popularity_backfill_queue(
    batch_size: int = 50,
    delay_seconds: float = 0.0,
    force: bool = False,
):
    """Drain the Trakt popularity queue and process items in small batches."""
    with backfill_queue.drain(
        TRAKT_POPULARITY_BACKFILL_ITEMS_QUEUE_KEY,
        TRAKT_POPULARITY_BACKFILL_ITEMS_SCHEDULED_KEY,
        batch_size,
        drain_task=populate_trakt_popularity_backfill_queue,
        drain_kwargs={"force": force},
    ) as batch:
        if not batch:
            return {"processed": 0, "message": "No queued Trakt popularity items"}

        result = populate_trakt_popularity_data_for_items(
            batch,
            delay_seconds=delay_seconds,
            force=force,
        )

    if not backfill_queue.depth(TRAKT_POPULARITY_BACKFILL_ITEMS_QUEUE_KEY):
        logger.info("trakt_popularity_backfill_complete: queue fully drained")
    return result


@shared_task(name="app.tasks.populate_trakt_episode_ratings_for_season")
def populate_trakt_episode_ratings_for_season(
    media_id: str,
    source: str,
    season_number: int,
    delay_seconds: float = 0.5,
):
    """Fetch and store Trakt aggregate ratings for all episodes in a season."""
    from app.models import Item, MediaTypes
    from app.providers import trakt as trakt_provider
    from app.services import trakt_popularity as trakt_pop

    if not trakt_provider.is_configured():
        return {"updated": 0, "message": "Trakt not configured"}

    episode_items = list(
        Item.objects.filter(
            media_id=str(media_id),
            source=source,
            media_type=MediaTypes.EPISODE.value,
            season_number=season_number,
            trakt_rating__isnull=True,
        ).order_by("episode_number")
    )
    if not episode_items:
        return {"updated": 0, "message": "No episodes need Trakt ratings"}

    # Resolve Trakt show ID via the show or season Item
    anchor = (
        Item.objects.filter(
            media_id=str(media_id),
            source=source,
            media_type=MediaTypes.TV.value,
        ).first()
        or Item.objects.filter(
            media_id=str(media_id),
            source=source,
            media_type=MediaTypes.SEASON.value,
            season_number=season_number,
        ).first()
    )
    if not anchor:
        return {
            "updated": 0,
            "message": "No show/season Item found for Trakt ID resolution",
        }

    try:
        show_lookup = trakt_pop.lookup_item_summary(
            anchor, route_media_type=MediaTypes.TV.value
        )
    except Exception as exc:
        logger.warning(
            "trakt_episode_ratings_lookup_error media_id=%s season=%s error=%s",
            media_id,
            season_number,
            exception_summary(exc),
        )
        return {"updated": 0, "message": f"API error: {exception_summary(exc)}"}

    if not show_lookup:
        return {"updated": 0, "message": "Could not resolve Trakt show ID"}

    episode_numbers = [
        ep.episode_number for ep in episode_items if ep.episode_number is not None
    ]
    try:
        ratings = trakt_provider.fetch_episode_ratings_for_season(
            show_lookup,
            season_number,
            episode_numbers,
            delay_seconds=delay_seconds,
        )
    except Exception as exc:
        logger.warning(
            "trakt_episode_ratings_error media_id=%s season=%s error=%s",
            media_id,
            season_number,
            exception_summary(exc),
        )
        return {"updated": 0, "message": f"API error: {exception_summary(exc)}"}

    updated_items = []
    for ep in episode_items:
        ep_data = ratings.get(ep.episode_number)
        if ep_data is not None:
            ep.trakt_rating = ep_data["rating"]
            ep.trakt_rating_count = ep_data["votes"]
            updated_items.append(ep)

    if updated_items:
        Item.objects.bulk_update(
            updated_items, ["trakt_rating", "trakt_rating_count"], batch_size=100
        )

    logger.info(
        "trakt_episode_ratings_complete media_id=%s season=%s updated=%d",
        media_id,
        season_number,
        len(updated_items),
    )
    return {
        "updated": len(updated_items),
        "message": f"Updated {len(updated_items)} episodes",
    }


@shared_task(name="app.tasks.reconcile_trakt_popularity")
def reconcile_trakt_popularity(score_version: int | None = None):
    """Reconcile Trakt popularity data for all tracked items on startup.

    For items that have already been fetched from Trakt (trakt_popularity_fetched_at
    is set), recomputes score and rank locally from stored rating/votes — no API
    calls.  For items that have never been fetched, enqueues them for the normal
    API backfill so they converge without waiting for the nightly beat schedule.

    On success, stamps a permanent version cache key so this version's recompute
    does not fire again until the formula version advances.
    """
    from app.models import Item

    # Ids first, and only ids. `tracked_items_queryset()` is a bare
    # `Item.objects.filter(...)`, so hydrating it loads all ~60 columns -
    # including `synopsis` and the `watch_providers` blob, ~146 KiB a title -
    # to read four scalars. Holding the whole library that way took one
    # production run's VmHWM from 198 MiB to 799 MiB for 2972 rows.
    # `.order_by("id")` also displaces `Item.Meta.ordering = ["media_id"]`, so
    # the DISTINCT dedupes on an integer key instead of sorting a 500-char
    # column across full rows.
    all_ids = list(
        trakt_popularity_service.tracked_items_queryset()
        .order_by("id")
        .values_list("id", flat=True)
    )

    recomputed = 0
    never_fetched_ids = []

    # Two passes rather than one streamed cursor: no read cursor stays open
    # across the writes, which is the guarantee the original `list()` bought
    # by paying for the whole library.
    for offset in range(0, len(all_ids), RECONCILE_CHUNK_SIZE):
        chunk = all_ids[offset : offset + RECONCILE_CHUNK_SIZE]
        updates = []
        rows = Item.objects.filter(id__in=chunk).values_list(
            "id",
            "trakt_popularity_fetched_at",
            "trakt_rating",
            "trakt_rating_count",
        )
        for item_id, fetched_at, rating, rating_count in rows:
            if fetched_at is None:
                never_fetched_ids.append(item_id)
                continue
            # Already have Trakt data — recompute derived fields locally.
            new_score = trakt_popularity_service.compute_popularity_score(
                rating,
                rating_count,
            )
            updates.append(
                Item(
                    pk=item_id,
                    trakt_popularity_score=new_score,
                    trakt_popularity_rank=(
                        trakt_popularity_service.estimate_rank_from_score(new_score)
                    ),
                ),
            )
        if updates:
            Item.objects.bulk_update(
                updates,
                ["trakt_popularity_score", "trakt_popularity_rank"],
                batch_size=RECONCILE_UPDATE_BATCH_SIZE,
            )
            recomputed += len(updates)

    enqueued = 0
    if never_fetched_ids and trakt_popularity_service.trakt_provider.is_configured():
        enqueued = enqueue_trakt_popularity_backfill_items(
            never_fetched_ids, countdown=10
        )

    # Mark this formula version as fully reconciled so restarts don't re-run it.
    if score_version is not None:
        cache.set(
            f"trakt_popularity_reconciled_v{score_version}",
            "done",
            timeout=None,
        )

    # `total` is logged because `recomputed` alone cannot say how large the
    # working set was - the number a memory regression here would show up in.
    logger.info(
        "reconcile_trakt_popularity total=%d recomputed=%d enqueued_for_fetch=%d "
        "version=%s",
        len(all_ids),
        recomputed,
        enqueued,
        score_version,
    )
    return {
        "total": len(all_ids),
        "recomputed": recomputed,
        "enqueued_for_fetch": enqueued,
    }
