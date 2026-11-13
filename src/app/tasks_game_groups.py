"""Game-group backfill: queryset builder, enqueue, drain queue, and reconcile tasks.

Populates Item.provider_franchise_* and Item.provider_collection_* for IGDB games
tracked before those catalog relationships were fetched. The Games library can
then group by franchise or collection/series without a live provider call.
"""

import logging
from collections import defaultdict

from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db.models import Q

from app import backfill_queue, metadata_utils
from app.log_safety import exception_summary
from app.models import Game, Item, MediaTypes, MetadataBackfillField, Sources
from app.providers import credentials, services
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

GAME_GROUPS_BACKFILL_VERSION = 1
GAME_GROUPS_BACKFILL_QUEUE_TTL = 60 * 60  # 1 hour
GAME_GROUPS_BACKFILL_ITEMS_QUEUE_KEY = "game_groups_backfill_items_queue"
GAME_GROUPS_BACKFILL_ITEMS_SCHEDULED_KEY = "game_groups_backfill_items_scheduled"


def _game_group_items_queryset():
    """Return IGDB games missing a provider franchise or collection name."""
    from app.models import MetadataBackfillState

    queryset = Item.objects.filter(
        source=Sources.IGDB.value,
        media_type=MediaTypes.GAME.value,
    ).filter(
        Q(provider_franchise_name="") | Q(provider_collection_name=""),
    )
    queryset = _apply_backfill_state_filters(
        queryset, MetadataBackfillField.GAME_GROUPS
    )
    completed_ids = MetadataBackfillState.objects.filter(
        field=MetadataBackfillField.GAME_GROUPS,
        give_up=False,
        fail_count=0,
        last_success_at__isnull=False,
        strategy_version__gte=GAME_GROUPS_BACKFILL_VERSION,
    ).values("item_id")
    return queryset.exclude(id__in=completed_ids)


def count_game_group_backfill_items() -> int:
    """Return the number of games still missing group backfill."""
    return _game_group_items_queryset().count()


def _users_by_item(items):
    """Return the tracking users that can scope each item's provider keys."""
    item_ids = [item.id for item in items]
    user_ids_by_item = defaultdict(list)
    for item_id, user_id in Game.objects.filter(item_id__in=item_ids).values_list(
        "item_id", "user_id"
    ):
        if user_id not in user_ids_by_item[item_id]:
            user_ids_by_item[item_id].append(user_id)
    users = {
        user.pk: user
        for user in get_user_model().objects.filter(
            pk__in={user_id for ids in user_ids_by_item.values() for user_id in ids}
        )
    }
    configured = {}

    def scoped_user(item):
        candidates = [
            users[user_id]
            for user_id in user_ids_by_item.get(item.id, ())
            if user_id in users
        ]
        for user in candidates:
            if user.pk not in configured:
                configured[user.pk] = credentials.is_configured("igdb", user)
            if configured[user.pk]:
                return user
        return candidates[0] if candidates else None

    return scoped_user


def _populate_game_groups_for_items(items):
    updated_count = 0
    error_count = 0
    run = CooperativeRun("game_groups_backfill")
    scoped_user = _users_by_item(items)
    for item in run.iter(items):
        try:
            with credentials.current_user_scope(scoped_user(item)):
                metadata = services.get_media_metadata(
                    item.media_type,
                    item.media_id,
                    item.source,
                )
            if not isinstance(metadata, dict):
                error_count += 1
                _record_backfill_failure(
                    item, MetadataBackfillField.GAME_GROUPS, "no metadata"
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

            # A provider answer with no franchise/collection is still a
            # completed backfill, otherwise the sweep never converges.
            _record_backfill_success(
                item,
                MetadataBackfillField.GAME_GROUPS,
                strategy_version=GAME_GROUPS_BACKFILL_VERSION,
            )
            updated_count += 1
        except services.ProviderNotConfiguredError:
            # Missing keys say nothing about the item, so they must not burn
            # its attempts; reopen_unconfigured_game_groups() picks it up
            # once the provider is configured.
            logger.info("Game groups backfill skipped: IGDB is not configured")
            break
        except Exception as exc:
            error_count += 1
            logger.exception(
                "Error backfilling game groups for %s: %s",
                item.title,
                exception_summary(exc),  # noqa: TRY401  # exception_summary() is the project's sanitised rendering
            )
            _record_backfill_failure(
                item,
                MetadataBackfillField.GAME_GROUPS,
                f"exception: {exception_summary(exc)}",
            )

    run.reenqueue_if_deferred(enqueue_game_group_backfill_items)
    logger.info(
        "Game groups backfill batch completed: %s updated, %s errors",
        updated_count,
        error_count,
    )
    return updated_count, error_count


@shared_task(name="app.tasks.populate_game_group_data_for_items")
def populate_game_group_data_for_items(item_ids: list[int]):
    """Backfill franchise/collection data for a targeted list of game IDs."""
    normalized = _normalize_item_ids(item_ids)
    if not normalized:
        return {"updated": 0, "errors": 0, "message": "No item IDs provided"}

    items_to_update = list(_game_group_items_queryset().filter(id__in=normalized))
    if not items_to_update:
        return {
            "updated": 0,
            "errors": 0,
            "message": "No matching games require game-group backfill",
        }

    updated_count, error_count = _populate_game_groups_for_items(items_to_update)
    return {
        "updated": updated_count,
        "errors": error_count,
        "message": f"Processed {len(items_to_update)} targeted items",
    }


def enqueue_game_group_backfill_items(item_ids, countdown=10):
    """Queue game IDs for franchise/collection backfill."""
    normalized = _normalize_item_ids(item_ids)
    normalized = _filter_backfill_item_ids(
        normalized, MetadataBackfillField.GAME_GROUPS
    )
    if not normalized:
        return 0
    queued = backfill_queue.enqueue(
        GAME_GROUPS_BACKFILL_ITEMS_QUEUE_KEY,
        GAME_GROUPS_BACKFILL_ITEMS_SCHEDULED_KEY,
        normalized,
        ttl=GAME_GROUPS_BACKFILL_QUEUE_TTL,
        drain_task=populate_game_group_backfill_queue,
        countdown=countdown,
    )
    if not queued:
        logger.debug("Game groups backfill queue unavailable, dispatching directly")
        populate_game_group_data_for_items.apply_async(
            args=[normalized], countdown=countdown
        )
    return len(normalized)


@shared_task(name="app.tasks.populate_game_group_backfill_queue")
def populate_game_group_backfill_queue(batch_size: int = 25):
    """Drain the game-groups backfill queue in small batches."""
    with backfill_queue.drain(
        GAME_GROUPS_BACKFILL_ITEMS_QUEUE_KEY,
        GAME_GROUPS_BACKFILL_ITEMS_SCHEDULED_KEY,
        batch_size,
        drain_task=populate_game_group_backfill_queue,
    ) as batch:
        if not batch:
            return {"processed": 0, "message": "No queued game-group items"}

        return populate_game_group_data_for_items(batch)


def reopen_unconfigured_game_groups(user=None) -> int:
    """Retry games that failed only because IGDB had no credentials.

    Those failures count toward give-up, and the startup sweep is one-time per
    version, so without this a late-configured key would never backfill them.
    Called only on events that show IGDB can now work (credentials saved, process
    start), never per item. Returns the number of reopened items.
    """
    from app.models import MetadataBackfillState

    if not credentials.is_configured("igdb", user):
        return 0
    reopened = MetadataBackfillState.objects.filter(
        field=MetadataBackfillField.GAME_GROUPS,
        last_success_at__isnull=True,
        last_error__contains="ProviderNotConfiguredError",
    ).update(
        fail_count=0,
        give_up=False,
        next_retry_at=None,
        last_error="",
        terminal=False,
    )
    if reopened:
        reconcile_game_groups_backfill.apply_async(
            countdown=10, priority=BACKGROUND_TASK_PRIORITY
        )
    return reopened


@shared_task(name="app.tasks.reconcile_game_groups_backfill")
def reconcile_game_groups_backfill(
    strategy_version: int | None = None,
    batch_size: int = 200,
):
    """Queue all current game-group backfill candidates once."""
    batch_size = max(int(batch_size), 1)
    last_item_id = 0
    selected = 0
    enqueued = 0

    while True:
        batch_ids = list(
            _game_group_items_queryset()
            .filter(id__gt=last_item_id)
            .order_by("id")
            .values_list("id", flat=True)[:batch_size],
        )
        if not batch_ids:
            break

        last_item_id = batch_ids[-1]
        selected += len(batch_ids)
        enqueued += enqueue_game_group_backfill_items(batch_ids, countdown=10)

    if strategy_version is not None:
        cache.set(
            f"game_groups_backfilled_v{strategy_version}",
            "done",
            timeout=None,
        )

    logger.info(
        "reconcile_game_groups_backfill selected=%d enqueued=%d version=%s",
        selected,
        enqueued,
        strategy_version,
    )
    return {"selected": selected, "enqueued": enqueued}
