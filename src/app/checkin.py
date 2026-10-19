"""Manual Check-in for movies and shows: Floppy's own button acting as a scrobbler.

A check-in does what a media server's scrobbles do, in the same order. The tap
puts a card on Home (Now Playing) and saves the movie, or the next episode of
the show, as In Progress. The end is assumed from the runtime, and when it
passes the row is completed with that end time. Pause keeps the saved position
and leaves the row In Progress. Finish completes it early.

A real scrobble for the same title takes the card over: its state is rebuilt
without our token, so the end-of-runtime step sees a card it does not own and
leaves the row to the scrobbler, which finds our In Progress row and completes
it instead of adding a second one.

The check-in itself lives in a cache record (one per user, like Now Playing).
Losing it leaves a visible In Progress row, never a missing watch.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from django.core.cache import cache
from django.utils import timezone

from app import live_playback
from app.models import (
    TV,
    Episode,
    Item,
    MediaTypes,
    Movie,
    PlaybackProgress,
    Season,
    Sources,
    Status,
)
from app.models.episode_runtimes import usable_runtime_minutes
from app.services.completion import select_preferred_activity_entry
from app.services.episode_coordinates import InvalidEpisodeCoordinateError

logger = logging.getLogger(__name__)

SOURCE_LABEL = "check-in"
RECORD_TIMEOUT_SECONDS = live_playback.PLAYBACK_CACHE_TIMEOUT_SECONDS
# The record must outlive the assumed end so the settle step can still find it.
RECORD_END_MARGIN_SECONDS = 3600
# What a Pause remembers so a later Cancel can still undo the whole check-in.
ROLLBACK_TIMEOUT_SECONDS = 7 * 24 * 3600
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
    """A check-in action that cannot be carried out; ``message`` is shown."""

    def __init__(self, message):
        """Keep the text on ``message`` for the view to return."""
        super().__init__(message)
        self.message = message


@dataclass
class _Subject:
    """What a check-in is of: a movie, or the next episode of a tracked show."""

    media_type: str
    media_id: str
    item: Item  # the item whose position is saved
    duration: int | None
    code: str = ""  # "S02E05" for an episode
    season: object = None
    card: dict = field(default_factory=dict)

    @property
    def is_episode(self):
        return self.media_type == MediaTypes.TV.value


def supports(media_type, source):
    """Return whether a title can be checked in (TMDB movies and shows)."""
    return source == Sources.TMDB.value and media_type in (
        MediaTypes.MOVIE.value,
        MediaTypes.TV.value,
    )


def card_control(user_id, state):
    """Return the stop action only for the manual check-in owning this card."""
    token = state.get("checkin_token")
    if not token:
        return None
    from app import checkin_session

    for record, action in ((_record(user_id), "pause"), (checkin_session._record(user_id), "stop")):
        if record and record["token"] == token:
            return {
                "token": token,
                "source": record.get("source", Sources.TMDB.value),
                "media_type": record["media_type"],
                "media_id": record["media_id"],
                "action": action,
            }
    return None


def episode_code(season_number, episode_number):
    """Return the standard S02E05 form the Now Playing card already uses."""
    return f"S{int(season_number):02d}E{int(episode_number):02d}"


def _key(user_id):
    return f"checkin_v2:{user_id}"


def _rollback_key(user_id, media_type, media_id):
    return f"checkin_rollback_v1:{user_id}:{media_type}:{media_id}"


def _record(user_id):
    return cache.get(_key(user_id))


def _save_record(user_id, record):
    timeout = RECORD_TIMEOUT_SECONDS
    if record["end_ts"] is not None:
        timeout = max(
            timeout,
            record["end_ts"] - _now_ts() + RECORD_END_MARGIN_SECONDS,
        )
    cache.set(_key(user_id), record, timeout=timeout)


def mark_taken_over(user_id, token):
    """Note that a real scrobble replaced this check-in's card.

    The replacement card can expire before the assumed end, and that must not
    read as the check-in's own card disappearing.
    """
    record = _record(user_id)
    if record is not None and record["token"] == token:
        record["taken_over"] = True
        _save_record(user_id, record)


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


def _tracked_show(user, media_id):
    return (
        TV.objects.filter(
            user=user,
            item__media_id=str(media_id),
            item__source=Sources.TMDB.value,
            item__media_type=MediaTypes.TV.value,
        )
        .select_related("item")
        .first()
    )


def _seconds(runtime_minutes):
    minutes = usable_runtime_minutes(runtime_minutes)
    return minutes * 60 if minutes else None


def _subject(user, media_type, media_id):
    """Resolve what a check-in would be of, raising when there is nothing to start."""
    if media_type == MediaTypes.MOVIE.value:
        item = _movie_item(media_id)
        if item is None:
            msg = "Track this movie before checking in."
            raise CheckInError(msg)
        return _Subject(
            media_type=media_type,
            media_id=str(media_id),
            item=item,
            duration=_seconds(item.runtime_minutes),
            card={"title": item.title, "image": item.image},
        )

    show = _tracked_show(user, media_id)
    if show is None:
        msg = "Track this show before checking in."
        raise CheckInError(msg)
    target = show.next_episode_target()
    if target is None:
        msg = "There is no next episode to check in to."
        raise CheckInError(msg)
    season, episode_number = target
    try:
        episode_item = season.get_episode_item(episode_number)
    except InvalidEpisodeCoordinateError as error:
        msg = "That episode is not listed yet."
        raise CheckInError(msg) from error
    season_number = season.item.season_number
    return _Subject(
        media_type=media_type,
        media_id=str(media_id),
        item=episode_item,
        duration=_seconds(episode_item.runtime_minutes),
        code=episode_code(season_number, episode_number),
        season=season,
        card={
            "title": show.item.title,
            "series_title": show.item.title,
            "season_number": season_number,
            "episode_number": episode_number,
            "image": episode_item.image or show.item.image,
        },
    )


def _scrobble_movie(user, item, *, position, duration):
    from integrations.webhooks.checkin import CheckInProcessor

    CheckInProcessor().process_payload(
        {
            "media_type": "movie",
            "ids": {"tmdb": item.media_id},
            "title": item.title,
            "position_seconds": position,
            "duration_seconds": duration,
            "completed": False,
        },
        user,
    )


def _begin_movie(user, subject, offset):
    """Save the movie In Progress through the shared scrobble code."""
    movies = Movie.objects.filter(item=subject.item, user=user)
    before_ids = set(movies.values_list("id", flat=True))
    current = select_preferred_activity_entry(movies)
    previous = (
        {"status": current.status, "start_date": current.start_date}
        if current
        else None
    )

    _scrobble_movie(user, subject.item, position=offset, duration=subject.duration)

    created = movies.exclude(id__in=before_ids).first()
    row = created or current
    if row is None:
        msg = "Could not start the check-in."
        raise CheckInError(msg)
    return {
        "row_id": row.id,
        "created": created is not None,
        "previous": None if created else previous,
    }


def _open_episode(subject):
    return Episode.objects.filter(
        item=subject.item,
        related_season=subject.season,
        status=Status.IN_PROGRESS.value,
    ).first()


def _begin_episode(user, subject):
    """Save the episode as an open play, reusing one the user already left open."""
    existing = _open_episode(subject)
    if existing is not None:
        return {
            "row_id": existing.id,
            "created": False,
            "previous": {"status": existing.status, "start_date": existing.start_date},
        }
    # Saving the episode also moves its season and show to In Progress.
    season, show = subject.season, subject.season.related_tv
    parents = {
        "season_id": season.id,
        "season": season.status,
        "tv_id": show.id,
        "tv": show.status,
    }
    row = Episode.objects.create(
        item=subject.item,
        related_season=subject.season,
        status=Status.IN_PROGRESS.value,
        start_date=timezone.now().replace(second=0, microsecond=0),
        entry_source=SOURCE_LABEL,
    )
    return {"row_id": row.id, "created": True, "previous": None, "parents": parents}


def _saved_position(user, item):
    progress = PlaybackProgress.objects.filter(user=user, item=item).first()
    if progress is None or progress.completed:
        return 0
    return progress.position_seconds


def _position(record, now_ts):
    """Seconds into the title right now, never past the runtime."""
    position = record["offset"] + max(0, now_ts - record["started_at_ts"])
    if record["duration"]:
        position = min(position, record["duration"])
    return position


def _owns_card(user_id, record):
    """Return whether the Now Playing card is still this check-in's."""
    card = live_playback.peek_user_playback_state(user_id)
    return card is None or card.get("checkin_token") == record["token"]


def release_running(user):
    """Keep a running movie or show check-in's place before another check-in replaces it."""
    running = _record(user.id)
    if running is None:
        return
    if running.get("taken_over") or not _owns_card(user.id, running):
        _drop_record(user.id)
    else:
        pause(user, running["media_type"], running["media_id"])


def start(user, media_type, media_id):
    """Check in, resuming from a saved Pause if there is one."""
    subject = _subject(user, media_type, media_id)

    # One check-in per user, across movies, shows and sessions.
    from app import checkin_session

    checkin_session.interrupt(user)
    release_running(user)

    offset = _saved_position(user, subject.item)
    if subject.duration and offset >= subject.duration:
        offset = 0

    if subject.is_episode:
        row = _begin_episode(user, subject)
    else:
        row = _begin_movie(user, subject, offset)

    # A Resume continues the check-in a Pause left, so keep how to undo it.
    rollback_key = _rollback_key(user.id, media_type, subject.media_id)
    rollback = cache.get(rollback_key)
    if rollback and rollback["row_id"] == row["row_id"]:
        row = {
            **row,
            "created": rollback["created"],
            "previous": rollback["previous"],
            "parents": rollback.get("parents"),
        }
    cache.set(
        rollback_key,
        {key: row.get(key) for key in ("row_id", "created", "previous", "parents")},
        timeout=ROLLBACK_TIMEOUT_SECONDS,
    )

    now_ts = _now_ts()
    remaining = subject.duration - offset if subject.duration else None
    end_ts = now_ts + (remaining or UNKNOWN_RUNTIME_SECONDS)
    token = uuid.uuid4().hex
    record = {
        "token": token,
        "media_type": media_type,
        "media_id": subject.media_id,
        "item_id": subject.item.id,
        "code": subject.code,
        "started_at_ts": now_ts,
        "offset": offset,
        "duration": subject.duration,
        # Only a known runtime gives an end that completes the row.
        "end_ts": end_ts if subject.duration else None,
        **row,
    }
    live_playback.apply_playback_event(
        user_id=user.id,
        event_type="media.play",
        playback_media_type=(
            MediaTypes.EPISODE.value if subject.is_episode else MediaTypes.MOVIE.value
        ),
        media_id=subject.media_id,
        source=Sources.TMDB.value,
        view_offset_seconds=offset,
        duration_seconds=subject.duration,
        checkin_token=token,
        ends_at_ts=end_ts,
        **subject.card,
    )
    _save_record(user.id, record)

    from app.tasks import settle_checkin

    settle_checkin.apply_async(
        args=[user.id],
        countdown=end_ts - now_ts + SETTLE_DELAY_SECONDS,
    )


def _active_record(user, media_type, media_id):
    record = _record(user.id)
    if (
        record is None
        or record["media_type"] != media_type
        or record["media_id"] != str(media_id)
    ):
        msg = "No check-in is running here."
        raise CheckInError(msg)
    return record


def _close_card(user_id, record):
    if _owns_card(user_id, record):
        live_playback.clear_user_playback_state(user_id)
    _drop_record(user_id)


def _row(user, record):
    if record["media_type"] == MediaTypes.TV.value:
        return Episode.objects.filter(
            id=record["row_id"],
            related_season__user=user,
        ).first()
    return Movie.objects.filter(id=record["row_id"], user=user).first()


def pause(user, media_type, media_id):
    """Stop the check-in and keep where it got to; the row stays In Progress."""
    record = _active_record(user, media_type, media_id)
    position = _position(record, _now_ts())

    from api.fork_views_playback import upsert_playback_progress

    upsert_playback_progress(
        user,
        Item.objects.get(id=record["item_id"]),
        position,
        record["duration"],
        completed=False,
    )
    _close_card(user.id, record)


def _complete(user, record, at):
    """Complete the row this check-in saved, unless something else already did."""
    cache.delete(_rollback_key(user.id, record["media_type"], record["media_id"]))
    row = _row(user, record)
    if row is None or row.status != Status.IN_PROGRESS.value:
        return
    row.status = Status.COMPLETED.value
    row.end_date = at
    if isinstance(row, Movie):
        row.progress = 1
    row.save()

    from api.fork_views_playback import upsert_playback_progress

    duration = record["duration"] or 0
    upsert_playback_progress(
        user,
        Item.objects.get(id=record["item_id"]),
        duration,
        duration or None,
        completed=True,
    )


def finish(user, media_type, media_id):
    """Complete the row now."""
    record = _active_record(user, media_type, media_id)
    _close_card(user.id, record)
    _complete(user, record, timezone.now().replace(second=0, microsecond=0))


def _restore_parents(parents):
    """Put back the season and show status the created episode play changed."""
    if not parents:
        return
    Season.objects.filter(id=parents["season_id"]).update(status=parents["season"])
    TV.objects.filter(id=parents["tv_id"]).update(status=parents["tv"])


def cancel(user, media_type, media_id):
    """Undo the check-in: remove the row it added, or restore what it changed."""
    record = _active_record(user, media_type, media_id)
    row = _row(user, record)
    if row is not None and row.status == Status.IN_PROGRESS.value:
        if record["created"]:
            row.delete()
            _restore_parents(record.get("parents"))
        elif record["previous"] and record["previous"]["status"] != row.status:
            row.status = record["previous"]["status"]
            row.start_date = record["previous"]["start_date"]
            row.save()
    cache.delete(_rollback_key(user.id, record["media_type"], record["media_id"]))
    _close_card(user.id, record)


def settle(user_id):
    """Complete the row once the assumed end has passed, if the card is still ours.

    Run by a delayed task, and by the detail page as a catch-up, so a lost task
    cannot leave a finished check-in running.
    """
    record = _record(user_id)
    if record is None or record["end_ts"] is None or _now_ts() < record["end_ts"]:
        return
    owned = not record.get("taken_over") and _owns_card(user_id, record)
    _close_card(user_id, record)
    if not owned:
        cache.delete(_rollback_key(user_id, record["media_type"], record["media_id"]))
        return
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.filter(pk=user_id).first()
    if user is not None:
        end = datetime.fromtimestamp(record["end_ts"], tz=UTC)
        _complete(user, record, end.replace(second=0, microsecond=0))


def _running_phase(record, now_ts):
    """Return the phase of a running check-in, and when its label next changes."""
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


def _idle_target(user, instance):
    """Return (code, paused item) for a tracked show that has an episode to start.

    Reads only the database, so the detail page never waits on a provider.
    """
    target = instance.next_episode_target()
    if target is None:
        return None
    season, episode_number = target
    code = episode_code(season.item.season_number, episode_number)
    open_play = (
        Episode.objects.filter(
            related_season=season,
            item__episode_number=episode_number,
            status=Status.IN_PROGRESS.value,
        )
        .select_related("item")
        .first()
    )
    return code, open_play.item if open_play else None


def phase(user, instance):
    """Return the check-in phase for a movie or show detail page, or None.

    ``reload_in`` is the seconds until the button label changes by itself, so
    the page can refresh at that moment. ``code`` is the episode a show's
    Check-in or Resume would start.
    """
    item = instance.item
    from app import checkin_session

    if checkin_session.supports(item.media_type):
        return checkin_session.phase(user, instance)
    if not supports(item.media_type, item.source):
        return None

    settle(user.id)
    record = _record(user.id)
    now_ts = _now_ts()
    media_type = item.media_type
    if (
        record is not None
        and record["media_type"] == media_type
        and record["media_id"] == str(item.media_id)
    ):
        return {**_running_phase(record, now_ts), "code": record["code"]}

    if media_type == MediaTypes.MOVIE.value:
        paused = instance.status == Status.IN_PROGRESS.value and _saved_position(
            user,
            item,
        )
        return {
            "phase": PHASE_PAUSED if paused else PHASE_IDLE,
            "reload_in": None,
            "code": "",
        }

    target = _idle_target(user, instance)
    if target is None:
        return None
    code, open_item = target
    paused = open_item is not None and _saved_position(user, open_item)
    return {
        "phase": PHASE_PAUSED if paused else PHASE_IDLE,
        "reload_in": None,
        "code": code,
    }
