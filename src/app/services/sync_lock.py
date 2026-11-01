"""The per-user commit barrier shared by state writers and reliable readers."""

from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from functools import wraps
from uuid import uuid4

from django.db import transaction

_locked = ContextVar("sync_sequence_locks", default=None)


def lock_sequence(user_id):
    """Lock until the enclosing transaction commits; never call in autocommit."""
    from app.models import WatchStateSequence

    rows = _locked.get() or {}
    if user_id in rows:
        return rows[user_id]
    row, _ = WatchStateSequence.objects.get_or_create(user_id=user_id)
    return WatchStateSequence.objects.select_for_update().get(pk=row.pk)


@contextmanager
def state_transaction(user_id):
    """Take the allocator lock before source/state locks, through commit."""
    with transaction.atomic():
        row = lock_sequence(user_id)
        token = _locked.set({**(_locked.get() or {}), user_id: row})
        try:
            yield row
        finally:
            _locked.reset(token)


def serialized_state_write(method):
    """Keep model saves and their signal projections inside the same barrier."""

    @wraps(method)
    def wrapped(instance, *args, **kwargs):
        user_id = getattr(instance, "user_id", None)
        if user_id is None:
            user_id = (
                instance.related_season.user_id
                if hasattr(instance, "related_season_id")
                else instance.movie.user_id
            )
        with state_transaction(user_id):
            return method(instance, *args, **kwargs)

    return wrapped


def invalidate_contexts(row):
    """Invalidate strict contexts without resetting sequences or provider state."""
    row.sync_generation = uuid4()
    row.save(update_fields=["sync_generation"])


def invalidate_item_contexts(item_ids):
    """Fence identity changes, including users with only retained delete events."""
    from django.db.models import Q

    from app.models import (
        Episode,
        PlaybackProgress,
        ProgressChange,
        WatchState,
        WatchStateChange,
    )

    user_ids = set()
    for model in (WatchState, PlaybackProgress, WatchStateChange, ProgressChange):
        user_ids.update(
            model.objects.filter(item_id__in=item_ids).values_list("user_id", flat=True)
        )
    user_ids.update(
        Episode.objects.filter(
            Q(item_id__in=item_ids)
            | Q(related_season__item_id__in=item_ids)
            | Q(related_season__related_tv__item_id__in=item_ids),
        ).values_list("related_season__user_id", flat=True)
    )
    for user_id in sorted(user_ids):
        invalidate_contexts(lock_sequence(user_id))


@contextmanager
def tracking_mutation(queryset, *, instances=None, publish_quiet=False):
    """Publish bulk ORM changes that do not send model-save signals."""
    from django.contrib.auth import get_user_model

    from app.models import BackfillReconcileState, Episode, Item
    from app.services.watch_state import (
        PROJECTED_MEDIA_TYPES,
        project_watch_states_bulk,
        projection_suspended,
        suspend_projection,
    )
    from app.tasks_watch_state import REPAIR_KEY

    kind = queryset.model._meta.model_name
    if queryset.model._meta.app_label != "app" or kind not in PROJECTED_MEDIA_TYPES | {
        "movieplay",
        "tv",
        "season",
    }:
        yield
        return

    def identities():
        if instances is not None:
            return {
                (
                    obj.related_season.user_id
                    if kind == "episode"
                    else obj.movie.user_id
                    if kind == "movieplay"
                    else obj.user_id,
                    obj.movie.item_id if kind == "movieplay" else obj.item_id,
                )
                for obj in instances
            }
        if kind in {"tv", "season"}:
            episodes = Episode.objects.filter(
                **{
                    "related_season__related_tv__in"
                    if kind == "tv"
                    else "related_season__in": queryset
                },
            )
            return set(episodes.values_list("related_season__user_id", "item_id"))
        owner = (
            "related_season__user_id"
            if kind == "episode"
            else "movie__user_id"
            if kind == "movieplay"
            else "user_id"
        )
        item = "movie__item_id" if kind == "movieplay" else "item_id"
        return set(queryset.values_list(owner, item))

    pairs = identities()
    was_suspended = projection_suspended()
    with ExitStack() as stack:
        for user_id in sorted({user_id for user_id, _ in pairs}):
            stack.enter_context(state_transaction(user_id))
        with suspend_projection():
            yield
        # A caller explicitly batching a whole import publishes once at its
        # existing final projection boundary instead of emitting transient state.
        if was_suspended:
            return
        pairs |= identities()
        for user_id in sorted({user_id for user_id, _ in pairs}):
            sequence = lock_sequence(user_id)
            if not publish_quiet and not (
                sequence.api_feed_enabled or sequence.emit_changes
            ):
                # Preserve pre-contract provider behavior. A later first sync
                # must repair these quiet bulk writes before publishing state.
                invalidate_contexts(sequence)
                BackfillReconcileState.objects.filter(
                    key=f"{REPAIR_KEY}_user_{user_id}"
                ).update(completed_at=None, last_cursor_item_id=0)
                continue
            user = get_user_model().objects.get(pk=user_id)
            ids = sorted(
                item_id
                for owner, item_id in pairs
                if owner == user_id and item_id is not None
            )
            for start in range(0, len(ids), 500):
                project_watch_states_bulk(
                    user, Item.objects.filter(pk__in=ids[start : start + 500])
                )
