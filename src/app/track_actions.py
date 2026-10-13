"""Which tracking actions the detail-page split button offers.

The first action is the main button. A second action becomes a small
icon-only segment and three or more open a menu, so adding an action later
needs no template change.
"""

from django.utils.translation import gettext as _

from app import checkin
from app.models import MediaTypes, Status

# Every play is its own entry, so adding one is always the forward action.
ALWAYS_ADD_ENTRY = frozenset({MediaTypes.GAME.value, MediaTypes.BOARDGAME.value})
# Once a finished entry exists, the next thing to do is another one. Videos keep
# one row per user (repeat watches are plays on it) and TV-backed anime one
# tracker, so neither can take a second entry.
ADD_ENTRY_WHEN_COMPLETED = frozenset(
    {
        MediaTypes.MOVIE.value,
        MediaTypes.ANIME.value,
        MediaTypes.BOOK.value,
        MediaTypes.COMIC.value,
    },
)


def track_actions(media_type, status, checkin_phase=None):
    """Return the ordered actions for a tracked item of this type and status.

    ``checkin_phase`` is ``app.checkin.phase`` for a title that can be checked in.
    Modal actions (``edit``, ``create``) open the track modal; the rest post to
    the Check-in endpoint under their own key.
    """
    edit = {"key": "edit", "label": _("Edit"), "icon": "edit"}
    add_entry = {"key": "create", "label": _("Add new entry"), "icon": "plus"}
    if checkin_phase is not None:
        start = {"key": "start", "label": _("Check-in"), "icon": "play"}
        phase = checkin_phase["phase"]
        if phase == checkin.PHASE_ACTIVE:
            return [
                {"key": "pause", "label": _("Pause"), "icon": "pause"},
                {"key": "cancel", "label": _("Cancel check-in"), "icon": "x"},
                edit,
            ]
        if phase == checkin.PHASE_FINISHABLE:
            return [
                {"key": "finish", "label": _("Finish"), "icon": "checkmark"},
                {"key": "pause", "label": _("Pause"), "icon": "pause"},
                {"key": "cancel", "label": _("Cancel check-in"), "icon": "x"},
                edit,
            ]
        if phase == checkin.PHASE_PAUSED:
            return [
                {"key": "resume", "label": _("Resume"), "icon": "play"},
                edit,
            ]
        if status == Status.COMPLETED.value:
            return [add_entry, start, edit]
        return [start, edit]
    if media_type in ALWAYS_ADD_ENTRY or (
        media_type in ADD_ENTRY_WHEN_COMPLETED and status == Status.COMPLETED.value
    ):
        return [add_entry, edit]
    return [edit]
