"""Manual Check-in for movies: Floppy's own button acting as a scrobbling client.

A check-in does what a media server's scrobbles do, in the same order. The tap
puts a card on Home (Now Playing) and saves the movie as In Progress. The end
is assumed from the runtime, and when it passes the movie is completed with
that end time. Pause keeps the saved position and leaves the movie In Progress.
Finish completes it early.

A real scrobble for the same title takes the card over: its state is rebuilt
without our token, so the end-of-runtime step sees a card it does not own and
leaves the movie to the scrobbler, which finds our In Progress row and
completes it instead of adding a second one.

The check-in itself lives in a cache record (one per user, like Now Playing).
Losing it leaves a visible In Progress movie, never a missing watch.
"""

import logging
import uuid
from datetime import UTC, datetime

from django.core.cache import cache
from django.utils import timezone

from app import live_playback
from app.models import Item, MediaTypes, Movie, PlaybackProgress, Sources, Status
from app.services.completion import select_preferred_activity_entry

logger = logging.getLogger(__name__)

RECORD_TIMEOUT_SECONDS = live_playback.PLAYBACK_CACHE_TIMEOUT_SECONDS
# Finish replaces Pause at the same point a media server counts a title watched.
FINISH_RATIO = live_playback.PLAYBACK_SCROBBLE_MIN_PROGRESS_RATIO
SETTLE_DELAY_SECONDS = 5
# Without a runtime there is no end to assume; the card closes like any stale one.
UNKNOWN_RUNTIME_SECONDS = live_playback.PLAYBACK_HARD_STALE_SECONDS

PHASE_IDLE = "idle"
PHASE_ACTIVE = "active"
PHASE_FINISHABLE = "finishable"
PHASE_PAUSED = "paused"


class CheckInError(Exception):
    """A check-in action that cannot be carried out; the message is shown."""


def supports(media_type, source):
    """Return whether a title can be checked in (TMDB movies for now)."""
    return media_type == MediaTypes.MOVIE.value and source == Sources.TMDB.value


def _key(user_id):
    return f"checkin_v1:{user_id}"


def _record(user_id):
    return cache.get(_key(user_id))


def _drop_record(user_id):
    cache.delete(_key(user_id))


def _now_ts():
    return int(timezone.now().timestamp())


def _movie_item(media_id):
    return Item.objects.filter(
        media_id=str(media_id),
        source=Sources.TMDB.value,
        media_type=MediaTypes.MOVIE.value,
    ).first()


def _scrobble(user, item, *, position, duration, completed, played_at=None):
    from integrations.webhooks.checkin import CheckInProcessor

    CheckInProcessor().process_payload(
        {
            "media_type": "movie",
            "ids": {"tmdb": item.media_id},
            "title": item.title,
            "position_seconds": position,
            "duration_seconds": duration,
            "completed": completed,
            "played_at": played_at,
        },
        user,
    )


def _saved_position(user, item):
    progress = PlaybackProgress.objects.filter(user=user, item=item).first()
    if progress is None or progress.completed:
        return 0
    return progress.position_seconds


def _position(record, now_ts):
    """Seconds into the movie right now, never past the runtime."""
    position = record["offset"] + max(0, now_ts - record["started_at_ts"])
    if record["duration"]:
        position = min(position, record["duration"])
    return position


def _owns_card(user_id, record):
    """Return whether the Now Playing card is still this check-in's."""
    card = live_playback.peek_user_playback_state(user_id)
    return card is None or card.get("checkin_token") == record["token"]


def start(user, media_id):
    """Check in to a tracked movie, resuming from a saved Pause if there is one."""
    item = _movie_item(media_id)
    if item is None:
        msg = "Track this movie before checking in."
        raise CheckInError(msg)

    movies = Movie.objects.filter(item=item, user=user)
    before_ids = set(movies.values_list("id", flat=True))
    current = select_preferred_activity_entry(movies)
    previous = (
        {"status": current.status, "start_date": current.start_date}
        if current
        else None
    )

    duration = item.runtime_minutes * 60 if item.runtime_minutes else None
    offset = _saved_position(user, item)
    if duration and offset >= duration:
        offset = 0

    _scrobble(user, item, position=offset, duration=duration, completed=False)

    created = movies.exclude(id__in=before_ids).first()
    row = created or current
    if row is None:
        msg = "Could not start the check-in."
        raise CheckInError(msg)

    now_ts = _now_ts()
    end_ts = now_ts + (duration - offset if duration else UNKNOWN_RUNTIME_SECONDS)
    token = uuid.uuid4().hex
    record = {
        "token": token,
        "media_id": str(item.media_id),
        "started_at_ts": now_ts,
        "offset": offset,
        "duration": duration,
        # Only a known runtime gives an end that completes the movie.
        "end_ts": end_ts if duration else None,
        "row_id": row.id,
        "created": created is not None,
        "previous": None if created else previous,
    }
    live_playback.apply_playback_event(
        user_id=user.id,
        event_type="media.play",
        playback_media_type=MediaTypes.MOVIE.value,
        media_id=item.media_id,
        source=Sources.TMDB.value,
        title=item.title,
        view_offset_seconds=offset,
        duration_seconds=duration,
        image=item.image,
        checkin_token=token,
        ends_at_ts=end_ts,
    )
    cache.set(_key(user.id), record, timeout=RECORD_TIMEOUT_SECONDS)

    from app.tasks import settle_checkin

    settle_checkin.apply_async(
        args=[user.id],
        countdown=end_ts - now_ts + SETTLE_DELAY_SECONDS,
    )


def _active_record(user, media_id):
    record = _record(user.id)
    if record is None or record["media_id"] != str(media_id):
        msg = "No check-in is running for this movie."
        raise CheckInError(msg)
    return record


def _close_card(user_id, record):
    if _owns_card(user_id, record):
        live_playback.clear_user_playback_state(user_id)
    _drop_record(user_id)


def pause(user, media_id):
    """Stop the check-in and keep where it got to; the movie stays In Progress."""
    record = _active_record(user, media_id)
    item = _movie_item(media_id)
    position = _position(record, _now_ts())

    from api.fork_views_playback import upsert_playback_progress

    upsert_playback_progress(user, item, position, record["duration"], completed=False)
    _close_card(user.id, record)


def _complete(user, record, at):
    """Complete the movie this check-in saved, unless something else already did."""
    row = Movie.objects.filter(
        id=record["row_id"],
        user=user,
        status=Status.IN_PROGRESS.value,
    ).first()
    if row is None:
        return
    row.status = Status.COMPLETED.value
    row.progress = 1
    row.end_date = at
    row.save()

    from api.fork_views_playback import upsert_playback_progress

    duration = record["duration"] or 0
    upsert_playback_progress(user, row.item, duration, duration or None, completed=True)


def finish(user, media_id):
    """Complete the movie now."""
    record = _active_record(user, media_id)
    _close_card(user.id, record)
    _complete(user, record, timezone.now().replace(second=0, microsecond=0))


def cancel(user, media_id):
    """Undo the check-in: remove the movie it added, or restore what it changed."""
    record = _active_record(user, media_id)
    row = Movie.objects.filter(id=record["row_id"], user=user).first()
    if row is not None and row.status == Status.IN_PROGRESS.value:
        if record["created"]:
            row.delete()
        elif record["previous"] and record["previous"]["status"] != row.status:
            row.status = record["previous"]["status"]
            row.start_date = record["previous"]["start_date"]
            row.save()
    _close_card(user.id, record)


def settle(user_id):
    """Complete the movie once the assumed end has passed, if the card is still ours.

    Run by a delayed task, and by the detail page as a catch-up, so a lost task
    cannot leave a finished check-in running.
    """
    record = _record(user_id)
    if record is None or record["end_ts"] is None or _now_ts() < record["end_ts"]:
        return
    owned = _owns_card(user_id, record)
    _close_card(user_id, record)
    if not owned:
        return
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.filter(pk=user_id).first()
    if user is not None:
        end = datetime.fromtimestamp(record["end_ts"], tz=UTC)
        _complete(user, record, end.replace(second=0, microsecond=0))


def phase(user, instance):
    """Return the check-in phase for a movie's detail page, with a reload hint.

    ``reload_in`` is the seconds until the button label changes by itself, so the
    page can refresh at that moment.
    """
    item = instance.item
    if not supports(item.media_type, item.source):
        return None

    settle(user.id)
    record = _record(user.id)
    now_ts = _now_ts()
    if record is not None and record["media_id"] == str(item.media_id):
        duration = record["duration"]
        if duration is None:
            return {"phase": PHASE_FINISHABLE, "reload_in": None}
        finish_at = record["started_at_ts"] + max(
            0,
            int(duration * FINISH_RATIO) - record["offset"],
        )
        if now_ts >= finish_at:
            return {"phase": PHASE_FINISHABLE, "reload_in": record["end_ts"] - now_ts}
        return {"phase": PHASE_ACTIVE, "reload_in": finish_at - now_ts}

    if instance.status == Status.IN_PROGRESS.value and _saved_position(user, item):
        return {"phase": PHASE_PAUSED, "reload_in": None}
    return {"phase": PHASE_IDLE, "reload_in": None}
