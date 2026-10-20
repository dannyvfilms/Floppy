"""Check-in for types with no runtime to assume: a session you end with Stop.

Games, board games, books, comics, manga and videos have no end the app can
assume, so a check-in is a session. It puts a Now Playing card on Home that
shows elapsed time, and what Stop saves depends on the type:

- A game saves a new In Progress entry at the start (each play session is its
  own entry); Stop adds the elapsed minutes and the end time.
- A board game adds one play to its latest entry at Stop.
- A book, comic or manga moves its latest entry to In Progress (a finished book
  or comic starts a new entry; manga reuses its entry) and Stop fills in the end
  time, and adds the elapsed minutes to its reading time (an audiobook's progress
  already is its time). Pages and chapters are yours to enter, so the page then
  opens the edit dialog.
- A video with a length is assumed watched to the end; Stop saves how far it got.

A session left running ends after four hours (or at the video's length). Its
entry stays as saved, with no made-up hours.

This keeps its own cache record, apart from ``app.checkin``'s.
"""

import logging
import math
import uuid

from django.core.cache import cache
from django.utils import timezone

from app import checkin, live_playback
from app.checkin import SETTLE_DELAY_SECONDS, SOURCE_LABEL, CheckInError
from app.models import (
    BoardGame,
    Book,
    Comic,
    Game,
    Item,
    Manga,
    MediaTypes,
    Status,
    Video,
)

logger = logging.getLogger(__name__)

PHASE_IDLE = "idle"
PHASE_SESSION = "session"

SESSION_TIMEOUT_SECONDS = 4 * 60 * 60
MODELS = {
    MediaTypes.GAME.value: Game,
    MediaTypes.BOARDGAME.value: BoardGame,
    MediaTypes.BOOK.value: Book,
    MediaTypes.COMIC.value: Comic,
    MediaTypes.MANGA.value: Manga,
    MediaTypes.VIDEO.value: Video,
}
# Stop on these hands over to the edit dialog, because only the user knows the pages.
READING = (MediaTypes.BOOK.value, MediaTypes.COMIC.value, MediaTypes.MANGA.value)


def supports(media_type):
    """Return whether this media type is checked in as a session."""
    return media_type in MODELS


def _key(user_id):
    return f"checkin_session_v2:{user_id}"


def _now_ts():
    return int(timezone.now().timestamp())


def _now():
    return timezone.now().replace(second=0, microsecond=0)


def _record(user_id):
    return cache.get(_key(user_id))


def _item(user, source, media_type, media_id):
    item = Item.objects.filter(
        media_id=str(media_id),
        source=source,
        media_type=media_type,
    ).first()
    if (
        item is None
        or not MODELS[media_type].objects.filter(item=item, user=user).exists()
    ):
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


def _owns_card(user_id, record):
    card = live_playback.peek_user_playback_state(user_id)
    return card is None or card.get("checkin_token") == record["token"]


def _end(user_id, record):
    """Forget the session and take its card off Home if it is still ours."""
    owned = _owns_card(user_id, record)
    if owned:
        live_playback.clear_user_playback_state(user_id)
    cache.delete(_key(user_id))
    return owned


def _begin_game(user, item):
    row = Game.objects.create(
        item=item,
        user=user,
        status=Status.IN_PROGRESS.value,
        start_date=_now(),
        entry_source=SOURCE_LABEL,
    )
    return {"row_id": row.id, "created": True, "previous": None}


def _begin_reading(user, item, media_type):
    """Move the latest entry to In Progress, or start a re-read of a finished one."""
    model = MODELS[media_type]
    latest = model.objects.filter(item=item, user=user).order_by("-created_at").first()
    if latest.status == Status.COMPLETED.value and media_type != MediaTypes.MANGA.value:
        row = model.objects.create(
            item=item,
            user=user,
            status=Status.IN_PROGRESS.value,
            start_date=_now(),
            entry_source=SOURCE_LABEL,
        )
        return {"row_id": row.id, "created": True, "previous": None}
    previous = {
        "status": latest.status,
        "start_date": latest.start_date,
        "end_date": latest.end_date,
    }
    latest.status = Status.IN_PROGRESS.value
    latest.start_date = latest.start_date or _now()
    latest.save()
    return {"row_id": latest.id, "created": False, "previous": previous}


def interrupt(user):
    """End the running session because another check-in is replacing it.

    Keeps what it measured: a game's minutes, a reading end, a video's progress.
    """
    settle(user.id)
    running = _record(user.id)
    if running is None:
        return
    _end(user.id, running)
    if running["media_type"] != MediaTypes.BOARDGAME.value:
        _save(user, running, running["media_type"])


def start(user, source, media_type, media_id):
    """Start a session and put its card on Home."""
    item = _item(user, source, media_type, media_id)
    interrupt(user)
    checkin.release_running(user)
    row = {"row_id": None, "created": False, "previous": None}
    if media_type == MediaTypes.GAME.value:
        row = _begin_game(user, item)
    elif media_type in READING:
        row = _begin_reading(user, item, media_type)

    now_ts = _now_ts()
    length = (
        Video.objects.filter(item=item, user=user)
        .values_list(
            "length_seconds",
            flat=True,
        )
        .first()
        if media_type == MediaTypes.VIDEO.value
        else 0
    )
    end_ts = now_ts + (length or SESSION_TIMEOUT_SECONDS)
    token = uuid.uuid4().hex
    record = {
        "token": token,
        "source": source,
        "media_type": media_type,
        "media_id": str(media_id),
        "item_id": item.id,
        "started_at_ts": now_ts,
        "end_ts": end_ts,
        "length": length or 0,
        **row,
    }
    live_playback.apply_playback_event(
        user_id=user.id,
        event_type="media.play",
        playback_media_type=media_type,
        media_id=str(media_id),
        source=source,
        title=item.title,
        image=item.image,
        view_offset_seconds=0,
        checkin_token=token,
        ends_at_ts=end_ts,
    )
    cache.set(_key(user.id), record, timeout=end_ts - now_ts + SETTLE_DELAY_SECONDS * 2)

    from app.tasks import settle_checkin_session

    settle_checkin_session.apply_async(
        args=[user.id],
        countdown=end_ts - now_ts + SETTLE_DELAY_SECONDS,
    )


def _save_video(user, record, progress_seconds):
    video = Video.objects.filter(item_id=record["item_id"], user=user).first()
    if video is not None:
        video.upsert_play(f"check-in:{record['token']}", progress_seconds)


def _is_audiobook(record):
    """Return whether the item is an audiobook, whose progress already is its time."""
    return Item.objects.filter(id=record["item_id"], format="audiobook").exists()


def _save(user, record, media_type):
    """Save what a session measured so far: a game's minutes, a reading end, a video's progress."""
    elapsed = max(0, _now_ts() - record["started_at_ts"])
    if media_type == MediaTypes.VIDEO.value:
        length = record["length"]
        _save_video(user, record, min(elapsed, length) if length else elapsed)
        return
    row = MODELS[media_type].objects.filter(id=record["row_id"], user=user).first()
    if row is None:
        return
    minutes = max(1, math.ceil(elapsed / 60))
    if media_type == MediaTypes.GAME.value:
        row.progress += minutes
    elif media_type in READING and not _is_audiobook(record):
        row.reading_time += minutes
    row.end_date = _now()
    row.save()


def stop(user, source, media_type, media_id):
    """End the session and save what it measured."""
    record = _active_record(user, source, media_type, media_id)
    _end(user.id, record)
    if media_type == MediaTypes.BOARDGAME.value:
        log_play(user, source, media_id)
    else:
        _save(user, record, media_type)


def cancel(user, source, media_type, media_id):
    """Drop the session, and put back or remove the entry it touched."""
    record = _active_record(user, source, media_type, media_id)
    _end(user.id, record)
    if not record["row_id"]:
        return
    rows = MODELS[media_type].objects.filter(id=record["row_id"], user=user)
    if record["created"]:
        # A game entry someone has since edited is theirs now.
        rows.filter(progress=0, end_date__isnull=True).delete()
        return
    row = rows.first()
    if row is not None and record["previous"]:
        for field, value in record["previous"].items():
            setattr(row, field, value)
        row.save()


def log_play(user, source, media_id):
    """Add one play to the board game's latest entry."""
    item = _item(user, source, MediaTypes.BOARDGAME.value, media_id)
    row = BoardGame.objects.filter(item=item, user=user).order_by("-created_at").first()
    row.increase_progress()


def settle(user_id):
    """End a session that ran out its time; a video with a length counts as watched."""
    record = _record(user_id)
    if not record or _now_ts() < record["end_ts"]:
        return
    owned = _end(user_id, record)
    if owned and record["media_type"] == MediaTypes.VIDEO.value and record["length"]:
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(pk=user_id).first()
        if user is not None:
            _save_video(user, record, record["length"])


def phase(user, instance):
    """Return the session phase for a detail page."""
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
