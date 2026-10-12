"""Check-in for games and board games: a play session with no assumed end.

A game has no runtime, so there is nothing to assume. Check-in saves a new In
Progress entry that starts now (each play session is its own entry); Stop adds
the elapsed minutes and the end time. A board game adds one play to its latest
entry at Stop. If Stop is never pressed the record is dropped after four hours:
a game keeps the entry with its start time and no made-up hours, and a board
game logs nothing.

This keeps its own cache record, apart from ``app.checkin``'s, and does not use
the Now Playing card, which only knows movies and episodes.
"""

import logging
import math

from django.core.cache import cache
from django.utils import timezone

from app.checkin import SETTLE_DELAY_SECONDS, SOURCE_LABEL, CheckInError
from app.models import BoardGame, Game, Item, MediaTypes, Status

logger = logging.getLogger(__name__)

PHASE_IDLE = "idle"
PHASE_SESSION = "session"

SESSION_TIMEOUT_SECONDS = 4 * 60 * 60
MODELS = {MediaTypes.GAME.value: Game, MediaTypes.BOARDGAME.value: BoardGame}


def supports(media_type):
    """Return whether this media type is checked in as a session."""
    return media_type in MODELS


def _key(user_id):
    return f"checkin_session_v1:{user_id}"


def _now_ts():
    return int(timezone.now().timestamp())


def _record(user_id):
    return cache.get(_key(user_id))


def _item(source, media_type, media_id):
    item = Item.objects.filter(
        media_id=str(media_id),
        source=source,
        media_type=media_type,
    ).first()
    if item is None or not MODELS[media_type].objects.filter(item=item).exists():
        msg = "Track this before checking in."
        raise CheckInError(msg)
    return item


def _active_record(user, source, media_type, media_id):
    record = _record(user.id)
    if (
        record is None
        or record["media_type"] != media_type
        or record["media_id"] != str(media_id)
        or record["source"] != source
    ):
        msg = "No check-in is running here."
        raise CheckInError(msg)
    return record


def start(user, source, media_type, media_id):
    """Start a session; a game saves its entry now so a lost record loses nothing."""
    item = _item(source, media_type, media_id)
    started = timezone.now().replace(second=0, microsecond=0)
    row_id = None
    if media_type == MediaTypes.GAME.value:
        row_id = Game.objects.create(
            item=item,
            user=user,
            status=Status.IN_PROGRESS.value,
            start_date=started,
            entry_source=SOURCE_LABEL,
        ).id
    now_ts = _now_ts()
    cache.set(
        _key(user.id),
        {
            "source": source,
            "media_type": media_type,
            "media_id": str(media_id),
            "started_at_ts": now_ts,
            "row_id": row_id,
        },
        timeout=SESSION_TIMEOUT_SECONDS + SETTLE_DELAY_SECONDS * 2,
    )

    from app.tasks import settle_checkin_session

    settle_checkin_session.apply_async(
        args=[user.id],
        countdown=SESSION_TIMEOUT_SECONDS + SETTLE_DELAY_SECONDS,
    )


def stop(user, source, media_type, media_id):
    """End the session and save what it measured."""
    record = _active_record(user, source, media_type, media_id)
    cache.delete(_key(user.id))
    if media_type == MediaTypes.BOARDGAME.value:
        log_play(user, source, media_id)
        return
    row = Game.objects.filter(id=record["row_id"], user=user).first()
    if row is None:
        return
    elapsed = max(0, _now_ts() - record["started_at_ts"])
    row.progress += max(1, math.ceil(elapsed / 60))
    row.end_date = timezone.now().replace(second=0, microsecond=0)
    row.save()


def cancel(user, source, media_type, media_id):
    """Drop the session, and the entry it added if nothing else touched it."""
    record = _active_record(user, source, media_type, media_id)
    cache.delete(_key(user.id))
    if record["row_id"]:
        Game.objects.filter(
            id=record["row_id"],
            user=user,
            progress=0,
            end_date__isnull=True,
        ).delete()


def log_play(user, source, media_id):
    """Add one play to the board game's latest entry."""
    item = _item(source, MediaTypes.BOARDGAME.value, media_id)
    row = BoardGame.objects.filter(item=item, user=user).order_by("-created_at").first()
    if row is None:
        msg = "Track this before logging a play."
        raise CheckInError(msg)
    row.increase_progress()


def settle(user_id):
    """Drop a session that ran past the four-hour limit; its entry stays as saved."""
    record = _record(user_id)
    if record and _now_ts() >= record["started_at_ts"] + SESSION_TIMEOUT_SECONDS:
        cache.delete(_key(user_id))


def phase(user, instance):
    """Return the session phase for a game or board game detail page."""
    settle(user.id)
    record = _record(user.id)
    item = instance.item
    if (
        record
        and record["media_type"] == item.media_type
        and record["media_id"] == str(item.media_id)
        and record["source"] == item.source
    ):
        return {"phase": PHASE_SESSION, "reload_in": None, "kind": "session"}
    return {"phase": PHASE_IDLE, "reload_in": None, "kind": "session"}
