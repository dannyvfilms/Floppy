"""Keep a status the user chose when a progress sync rewrites a book.

Audiobookshelf, Storyteller, KOReader and Plex audiobooks each work out a
status from the service's progress and write it with ``update_or_create``.
Without this, a book the user marked Paused, Dropped or Completed went back to
whatever the service reported on the next sync (#1316). This is the book-sync
counterpart of the TV rule in ``USER_HELD_STATUSES`` (#1133).
"""

from app.models.choices import USER_HELD_STATUSES, Status

SYNC_HELD_STATUSES = frozenset({*USER_HELD_STATUSES, Status.COMPLETED.value})


def status_changed_at(media):
    """Return when ``media`` last moved into its current status, or None."""
    history = media.history.all()
    previous = (
        history.exclude(status=media.status)
        .order_by("-history_date")
        .values_list("history_date", flat=True)
        .first()
    )
    current = history.filter(status=media.status)
    if previous is not None:
        current = current.filter(history_date__gt=previous)
    return current.order_by("history_date").values_list(
        "history_date",
        flat=True,
    ).first()


def keep_held_status(existing, defaults, activity_at):
    """Return ``update_or_create`` defaults that keep a status the user chose.

    ``existing`` is the tracked row (or None), ``defaults`` holds the status the
    service implies, and ``activity_at`` is when the service last saw the user
    read or listen. A Paused, Dropped or Completed status stays until the
    service reports the book finished, or shows activity after that status was
    set. Without an activity time the status stays: the sync cannot show the
    user came back to the book.
    """
    reported = defaults["status"]
    if (
        existing is None
        or existing.status not in SYNC_HELD_STATUSES
        or reported in {existing.status, Status.COMPLETED.value}
    ):
        return defaults

    if activity_at is not None:
        held_since = status_changed_at(existing)
        if held_since is not None and activity_at > held_since:
            return defaults

    kept = {**defaults, "status": existing.status}
    if "end_date" in kept:
        kept["end_date"] = existing.end_date
    if existing.status == Status.COMPLETED.value:
        # A finished book keeps its full progress rather than the service's
        # partial position.
        kept["progress"] = existing.progress
    return kept
