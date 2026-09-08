"""Backfill the canonical watched-state projection over an existing library.

The projection maintains itself from here on through signals, but a library
tracked before it existed has no rows at all. This walks those items once and
projects them.

It emits **no changes and no deliveries**, by construction: ``project_watch_state``
only records a change when the user is already synchronizing, and a user cannot
be synchronizing before their first connection is activated. That is load
bearing — a backfill that emitted changes would push a user's entire library out
to every connected provider the moment they upgraded.
"""

import logging

from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model

from app.models import Item, MediaTypes, WatchState
from app.services.watch_state import PROJECTED_MEDIA_TYPES, project_watch_state

logger = logging.getLogger(__name__)

BACKGROUND_TASK_PRIORITY = getattr(settings, "CELERY_TASK_PRIORITY_BACKGROUND", 9)
BACKFILL_BATCH_SIZE = 500


def _tracked_item_ids(user, media_type):
    """Return ids of items this user has tracking rows for, for one type."""
    if media_type == MediaTypes.EPISODE.value:
        from app.models import Episode

        return Episode.objects.filter(
            related_season__user=user,
            item__isnull=False,
        ).values_list("item_id", flat=True)

    from django.apps import apps

    model = apps.get_model(app_label="app", model_name=media_type)
    manager = getattr(model, "all_objects", model.objects)
    return manager.filter(user=user).values_list("item_id", flat=True)


def backfill_user_watch_state(user, *, after_item_id=0, limit=BACKFILL_BATCH_SIZE):
    """Project one batch of a user's library.

    Returns the last item id processed, or None when the user is done. Batching
    by item id makes the walk resumable after a crash without a cursor table.
    """
    item_ids = set()
    for media_type in PROJECTED_MEDIA_TYPES:
        item_ids.update(_tracked_item_ids(user, media_type))

    items = (
        Item.objects.filter(id__in=item_ids, id__gt=after_item_id)
        .order_by("id")[:limit]
    )
    items = list(items)
    if not items:
        return None

    for item in items:
        project_watch_state(user, item, record_changes=False)

    return items[-1].id


@shared_task(name="Backfill canonical watch state")
def backfill_watch_state(user_id=None):
    """Project canonical state for one user, or for everyone."""
    user_model = get_user_model()
    users = (
        user_model.objects.filter(id=user_id)
        if user_id
        else user_model.objects.all().order_by("id")
    )

    projected = 0
    for user in users:
        cursor = 0
        while True:
            cursor = backfill_user_watch_state(user, after_item_id=cursor)
            if cursor is None:
                break
            projected += 1

    logger.info(
        "Watch state backfill complete (users=%s, batches=%s, rows=%s)",
        users.count(),
        projected,
        WatchState.objects.count(),
    )
    return projected
