"""Fold one user's duplicate tracking row into another without losing what they wrote.

Used by unattended merges (`app.services.item_merge`), where two `Item` rows
turn out to be the same title and one user tracked both. There is nobody to
ask which score or status is right, so the rule only ever adds information:

- a field empty on the survivor takes the other row's value (score with its
  `scored_at`, notes, start date, end date, entry source);
- notes present on both are joined, the other row's after a blank line,
  unless they are identical;
- start date takes the earlier, end date the later, progress the larger;
- status takes the more advanced one (Planning, then In progress, then
  Completed). A user-held status (Dropped, Paused) on the survivor is never
  changed. A user-held status on the other row is taken only when the
  survivor has no status or is still Planning; otherwise the survivor's
  played status stands;
- a score present on both keeps the survivor's.

Whatever was not taken (the other score, the other status) is written into
the history change reason, so the result can be explained later. The write
goes through `bulk_update_with_history` so no save-time side effects run.

Music album and artist merges (`app.services.music`,
`app.services.music_scrobble`) use the same rule for their trackers.

The user-driven match correction (`integrations.match_corrections`) shares
`USER_SCALAR_FIELDS` but asks the user to choose instead of folding.
"""

from __future__ import annotations

from django.utils import timezone
from simple_history.exceptions import NotHistoricalModelError
from simple_history.utils import (
    bulk_update_with_history,
    get_history_manager_for_model,
)

from app.models import USER_HELD_STATUSES, Status

# The user-owned fields of a tracking row. Shared with match corrections.
USER_SCALAR_FIELDS = (
    "status",
    "score",
    "progress",
    "start_date",
    "end_date",
    "notes",
)

MERGE_CHANGE_REASON = "Merged duplicate entry"
# simple_history's change_reason column is 100 characters.
_REASON_MAX_LENGTH = 100

_STATUS_RANK = {
    None: 0,
    "": 0,
    Status.PLANNING.value: 1,
    Status.IN_PROGRESS.value: 2,
    Status.COMPLETED.value: 3,
}


def _empty(value) -> bool:
    return value is None or value == ""


def _folded_status(survivor_status, other_status):
    """Return the status to keep, and whether the other one was set aside."""
    if survivor_status == other_status or _empty(other_status):
        return survivor_status, False
    if survivor_status in USER_HELD_STATUSES:
        return survivor_status, True
    if other_status in USER_HELD_STATUSES:
        if _STATUS_RANK.get(survivor_status, 0) <= _STATUS_RANK[Status.PLANNING.value]:
            return other_status, False
        return survivor_status, True
    if _STATUS_RANK.get(other_status, 0) > _STATUS_RANK.get(survivor_status, 0):
        return other_status, False
    return survivor_status, True


def fold_tracker_fields(other, survivor) -> tuple[list[str], list[str]]:
    """Fold `other`'s user-owned fields into `survivor` in memory.

    Returns the changed field names and short notes on what was set aside.
    """
    field_names = {field.name for field in survivor._meta.concrete_fields}
    changed: list[str] = []
    set_aside: list[str] = []

    def take(name, value):
        setattr(survivor, name, value)
        changed.append(name)

    if "status" in field_names:
        status, discarded = _folded_status(survivor.status, other.status)
        if status != survivor.status:
            take("status", status)
        elif discarded:
            set_aside.append(f"other status {other.status}")

    if "score" in field_names and other.score is not None:
        if survivor.score is None:
            take("score", other.score)
            if "scored_at" in field_names:
                take("scored_at", other.scored_at or timezone.now())
        elif survivor.score != other.score:
            set_aside.append(f"other score {other.score}")

    if "progress" in field_names and (other.progress or 0) > (survivor.progress or 0):
        take("progress", other.progress)

    if (
        "start_date" in field_names
        and other.start_date is not None
        and (survivor.start_date is None or other.start_date < survivor.start_date)
    ):
        take("start_date", other.start_date)

    if (
        "end_date" in field_names
        and other.end_date is not None
        and (survivor.end_date is None or other.end_date > survivor.end_date)
    ):
        take("end_date", other.end_date)

    if "notes" in field_names:
        other_notes = (other.notes or "").strip()
        survivor_notes = (survivor.notes or "").strip()
        if other_notes and other_notes != survivor_notes:
            take(
                "notes",
                f"{survivor.notes}\n\n{other.notes}" if survivor_notes else other.notes,
            )

    if (
        "entry_source" in field_names
        and not survivor.entry_source
        and other.entry_source
    ):
        take("entry_source", other.entry_source)

    return changed, set_aside


def merge_change_reason(set_aside: list[str]) -> str:
    """Return the history change reason for a fold, naming what was set aside."""
    if not set_aside:
        return MERGE_CHANGE_REASON
    reason = f"{MERGE_CHANGE_REASON} ({', '.join(set_aside)})"
    if len(reason) > _REASON_MAX_LENGTH:
        reason = reason[: _REASON_MAX_LENGTH - 1] + ")"
    return reason


def fold_tracker_into(other, survivor) -> list[str]:
    """Fold `other` into `survivor` and write the survivor.

    A model with edit history (`TV`, `Season`, every `Media` row) is written
    through `bulk_update_with_history`, so no save-time side effects run and
    the history row says a merge happened. It always writes, even when no
    field changed: the survivor absorbed the other row's children, so its
    `updated_at` must move for API clients that mirror the library.

    A model without history (album and artist trackers) is saved normally,
    and only when something changed. Returns the changed field names.
    """
    changed, set_aside = fold_tracker_fields(other, survivor)
    model = type(survivor)
    fields = list(dict.fromkeys(changed))
    try:
        get_history_manager_for_model(model)
    except NotHistoricalModelError:
        if fields:
            survivor.save(update_fields=fields)
        return changed
    if "updated_at" in {field.name for field in model._meta.concrete_fields}:
        survivor.updated_at = timezone.now()
        fields.append("updated_at")
    bulk_update_with_history(
        [survivor],
        model,
        fields=fields,
        default_user=getattr(survivor, "user", None),
        default_change_reason=merge_change_reason(set_aside),
        manager=model._base_manager,
    )
    return changed
