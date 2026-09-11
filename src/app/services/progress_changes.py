"""Recording and reading ordered resume-progress changes.

``PlaybackProgress`` remains the current-state store; this records what moved so
a client can catch up in server order rather than diffing a snapshot. Deletes
are explicit, because a timestamp filter cannot express a row that is gone.

Recording is gated on the same per-user switch as watched state: a library with
no synchronizing connection writes no change rows at all.
"""

import logging

from django.db import transaction
from django.db.models import Max, Min

from app.models.progress_change import ProgressChange, ProgressChangeKind
from app.models.watch_state import WatchStateSequence
from app.services.watch_state import allocate_sequence

logger = logging.getLogger(__name__)

PROGRESS_RESOURCE = "progress"


def changes_enabled(user) -> bool:
    """Return whether this user's state movements are being recorded."""
    row = WatchStateSequence.objects.filter(user=user).first()
    return bool(row and row.emit_changes)


def record_progress_change(
    user,
    item,
    *,
    kind=ProgressChangeKind.UPSERT.value,
    position_seconds=0,
    duration_seconds=None,
    completed=False,
    origin_key="",
):
    """Append one ordered progress change, or return None when recording is off.

    Must run inside the transaction that wrote the progress row: the sequence is
    allocated under a row lock, so sequence order equals commit order only while
    both share a transaction.
    """
    if not changes_enabled(user):
        return None

    return ProgressChange.objects.create(
        user=user,
        item=item,
        sequence=allocate_sequence(user),
        kind=kind,
        position_seconds=position_seconds or 0,
        duration_seconds=duration_seconds,
        completed=bool(completed),
        origin_key=origin_key or "",
    )


def record_progress_deletion(user, item, *, origin_key=""):
    """Append an explicit tombstone for a cleared resume position."""
    return record_progress_change(
        user,
        item,
        kind=ProgressChangeKind.DELETE.value,
        origin_key=origin_key,
    )


def progress_changes_since(user, sequence, *, limit=100):
    """Return this user's progress changes after ``sequence``, in server order."""
    return list(
        ProgressChange.objects.filter(user=user, sequence__gt=sequence)
        .select_related("item")
        .order_by("sequence")[:limit],
    )


def retained_progress_range(user):
    """Return the (oldest, newest) progress sequence still retained."""
    bounds = ProgressChange.objects.filter(user=user).aggregate(
        oldest=Min("sequence"),
        newest=Max("sequence"),
    )
    return bounds["oldest"], bounds["newest"]


def record_progress_change_atomically(user, item, **kwargs):
    """Record a change in its own transaction, for callers outside one."""
    with transaction.atomic():
        return record_progress_change(user, item, **kwargs)
