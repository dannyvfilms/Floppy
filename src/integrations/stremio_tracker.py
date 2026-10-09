"""Media identity and merge policy for Stremio playback tracking.

`PlaybackProgress` is keyed on `Item`, not on Movie/Episode (Episode is not a
Media subclass), so every observation must resolve to an Item before it can be
stored. Resolution never guesses: an unknown id returns None and the caller
skips the write.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import unquote

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

# The shared durable-progress sink. Imported at module scope: `api.urls` is
# included ahead of `integrations.urls` in the root URLconf, and neither
# `fork_views_playback` nor its `integrations.delivery` dependency imports this
# module, so there is no cycle.
from api.fork_views_playback import upsert_playback_progress
from app import fork_services_episode
from app import fork_services_play_dedupe as play_dedupe
from app.models import Item, Movie, PlaybackProgress
from app.models.choices import MediaTypes, Sources
from app.services.progress_changes import record_progress_deletion

from .stremio_events import parse_episode_id, parse_library_extra, parse_player_extra

logger = logging.getLogger(__name__)

# Stremio batches library-event video ids; see LIBRARY_EVENT_VIDEOS_COUNT in
# stremio-core. Only a sanity bound is needed here, not enforcement.
VIDEO_ID_BATCH_LIMIT = 100

# Bounds for a parsed video id's coordinates. A client supplies the video id, so
# an out-of-range number must be rejected here rather than bound into a query.
MAX_EPISODE_COORDINATE = 9999

# Stremio flags a title watched above this fraction of its duration
# (WATCHED_THRESHOLD_COEF in stremio-core). Used only as the provisional for a
# player `stop`; the library flag is the authoritative signal.
WATCHED_THRESHOLD_COEF = 0.7

# A session is short-lived; the poller reconciles anything that outlives it.
_SESSION_TTL_SECONDS = 6 * 60 * 60


def _imdb_q(imdb_id):
    """Match an Item by IMDB id, whichever way it stores it.

    A Stremio id is an IMDB tt id. Items sourced directly from IMDB carry it as
    media_id; TMDB-sourced Items carry it in provider_external_ids — and those
    are what the Stremio importer creates.
    """
    return Q(source=Sources.IMDB.value, media_id=imdb_id) | Q(
        provider_external_ids__imdb_id=imdb_id,
    )


def _movie_item(user, imdb_id):
    # Movie.item has no explicit related_name, so the reverse accessor is the
    # default `movie`.
    return (
        Item.objects.filter(
            _imdb_q(imdb_id),
            media_type=MediaTypes.MOVIE.value,
            movie__user=user,
        )
        .distinct()
        .first()
    )


def _series_item(user, imdb_id):
    return (
        Item.objects.filter(
            _imdb_q(imdb_id),
            media_type=MediaTypes.TV.value,
            tv__user=user,
        )
        .distinct()
        .first()
    )


def _episode_item(user, series_imdb_id, season_number, episode_number):
    """Find the episode Item under the resolved series.

    Episode Items are keyed by the *series* media_id plus season_number and
    episode_number — they do not carry a composite tt123:1:2 media_id.

    This deliberately does NOT join through ``Episode``. ``Episode`` is a play
    row: nothing creates one for an episode the user has not played yet, so
    requiring it would drop every position and play for the first viewing of an
    episode — which is exactly what the poll producer exists to capture. User
    scoping comes from ``_series_item``, which already filters ``tv__user``.
    """
    series_item = _series_item(user, series_imdb_id)
    if series_item is None:
        return None
    return (
        Item.objects.filter(
            media_id=series_item.media_id,
            source=series_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=season_number,
            episode_number=episode_number,
        )
        .distinct()
        .first()
    )


def resolve_media_identity(user, media_type, media_id, video_id=None):
    """Return the Item this observation belongs to, or None.

    For a series with a video_id the episode is the identity, not the series:
    the position describes one episode. Returning the series would collapse
    every episode's progress onto a single item.
    """
    if not media_id:
        return None

    if media_type == "movie":
        return _movie_item(user, media_id)

    if media_type != "series":
        return None

    if not video_id:
        return _series_item(user, media_id)

    parsed = parse_episode_id(video_id)
    if parsed is None:
        logger.info("stremio_tracker status=unresolved reason=malformed_video_id")
        return None
    # parse_episode_id returns (series_id, season_number, episode_number).
    series_id, season_number, episode_number = parsed

    # Season 0 is Stremio's specials bucket and is legitimate; episodes start at
    # 1, so only the season bound is relaxed.
    if not (0 <= season_number <= MAX_EPISODE_COORDINATE) or not (
        1 <= episode_number <= MAX_EPISODE_COORDINATE
    ):
        logger.info(
            "stremio_tracker status=unresolved reason=out_of_range_video_id",
        )
        return None

    return _episode_item(user, series_id, season_number, episode_number)


# A poll observation older than this is treated as stale for position and
# status purposes. The flag may still be applied.
SESSION_GRACE_SECONDS = 600

# Sources are polled independently and a retry can arrive with an
# `observed_at` slightly before the last applied event. Within this window the
# ordering is treated as clock skew, not as a stale observation.
SESSION_CLOCK_SKEW_SECONDS = 120

_TERMINAL_ACTIONS = frozenset({"stop"})
_CLEAR_ACTIONS = frozenset({"unwatched", "libraryRemove"})


@dataclass(frozen=True)
class Observation:
    """One fact about playback, from any source.

    `records_play` says whether the fact is evidence of a *viewing*, which is
    what earns a history row. The player and library sources report the session
    in flight, so they are. A poll reports the item's state from the cloud
    library, which can be stale relative to the session — a replay of an
    already-watched title still reads `timesWatched=1` — so it is not, and the
    history play stays the verifier's to append. A poll still carries `watched`,
    because the library flag is authoritative for whether the item is watched,
    and the progress row reflects that.
    """

    action: str
    position_seconds: int | None
    duration_seconds: int | None
    watched: bool | None
    observed_at: object
    video_id: str | None
    records_play: bool = True


@dataclass(frozen=True)
class MergeResult:
    """What the caller should persist after folding in one observation."""

    completed: bool
    position_seconds: int | None
    duration_seconds: int | None
    record_play: bool
    clear_progress: bool


def new_session(video_id, started_at):
    """Start a fresh session baseline for one media identity."""
    return {
        "video_id": video_id,
        "started_at": started_at,
        "last_event_at": started_at,
        "position_seconds": None,
        "duration_seconds": None,
        "completed": False,
        "play_recorded": False,
        "settled": False,
        # What the last successful persist wrote for this identity. Stremio
        # pushes `time_offset` no more often than ~90s while the verifier polls
        # every 5-120s, so most polls repeat the position already stored, and
        # re-writing it appends an unchanged `ProgressChange` row that nothing
        # prunes.
        "persisted_position_seconds": None,
        "persisted_duration_seconds": None,
        "persisted_completed": None,
    }


_REWATCH_START_ACTIONS = frozenset({"start"})


def session_for_observation(session, observation, *, now=None):
    """Return the session this observation belongs to, starting a new one if needed.

    Rule 3: a new session resets the position baseline and clears `completed`, so
    a rewatch is counted as a fresh play instead of being pinned near the end by
    the monotonic-position rule.

    A new session is also started when an observation arrives more than
    SESSION_GRACE_SECONDS after the last applied event of a settled session.
    That trigger is gated on `settled` deliberately: without the gate, any
    observation later than the grace window would start a new session, so a
    long pause mid-episode would clear `play_recorded` and the eventual `stop`
    would append a second play for the same viewing.

    Callers MUST use the returned session: the input is never mutated, and a
    new session object is returned whenever a boundary is crossed.

    `now` is accepted for signature symmetry with the callers' clock and does
    not participate in the decision; ordering uses `observation.observed_at`.
    """
    if session is None:
        return new_session(
            video_id=observation.video_id,
            started_at=observation.observed_at,
        )

    if observation.video_id and observation.video_id != session.get("video_id"):
        return new_session(
            video_id=observation.video_id or session.get("video_id"),
            started_at=observation.observed_at,
        )

    if observation.action in _REWATCH_START_ACTIONS and session.get("settled"):
        return new_session(
            video_id=observation.video_id or session.get("video_id"),
            started_at=observation.observed_at,
        )

    last_event_at = session.get("last_event_at")
    if (
        session.get("settled")
        and last_event_at is not None
        and observation.observed_at
        > last_event_at + timedelta(seconds=SESSION_GRACE_SECONDS)
    ):
        return new_session(
            video_id=observation.video_id or session.get("video_id"),
            started_at=observation.observed_at,
        )

    return session


def _is_stale(session, observation):
    """Return whether an observation predates the session's last applied one.

    An observation up to SESSION_CLOCK_SKEW_SECONDS before the last applied
    event is treated as fresh: independent sources can report the same event
    with slightly different timestamps.
    """
    last = session.get("last_event_at")
    if last is None:
        return False
    return observation.observed_at < last - timedelta(
        seconds=SESSION_CLOCK_SKEW_SECONDS
    )


def apply_observation(session, observation):
    """Fold one observation into a session and report the effects.

    Mutates `session` in place and returns what the caller should persist.
    Rules, in precedence order, are documented in the spec §5.

    `Observation.watched` is a three-state contract, and the distinction is
    load-bearing:

    * ``True`` asserts the media is watched.
    * ``False`` asserts it is NOT watched, and clears a completed session. The
      flag is authoritative, so an explicit ``False`` overrides a provisional
      completion: Stremio derives the flag from accumulated watch *time*
      (``time_watched > duration * 0.7``), which can legitimately disagree with
      a position-based completion, and the flag wins.
    * ``None`` means the source holds no assertion about watched-ness. It never
      changes completion in either direction.

    Callers that merely lack a flag MUST pass ``None``, not ``False``: a
    ``False`` is an assertion that unwatches the media and clears the session's
    completion, so passing it for "unknown" silently destroys state.
    """
    stale = _is_stale(session, observation)

    # Rule 1: a stale observation may still carry watched state, because the
    # flag is authoritative for watched-ness, but it must not move position or
    # status. A poll is the usual source of a stale observation.
    watched = observation.watched
    if watched is not None:
        session["completed"] = bool(watched)

    if observation.action in _CLEAR_ACTIONS:
        session["completed"] = False
        session["position_seconds"] = None
        session["duration_seconds"] = None
        session["settled"] = True
        session["last_event_at"] = max(
            session.get("last_event_at") or observation.observed_at,
            observation.observed_at,
        )
        return MergeResult(
            completed=False,
            position_seconds=None,
            duration_seconds=None,
            record_play=False,
            clear_progress=True,
        )

    if not stale:
        # Rule 2: position is monotonic within a session.
        if observation.position_seconds is not None:
            current = session.get("position_seconds")
            if current is None or observation.position_seconds > current:
                session["position_seconds"] = observation.position_seconds
        if observation.duration_seconds is not None:
            session["duration_seconds"] = observation.duration_seconds
        if observation.action in _TERMINAL_ACTIONS:
            session["settled"] = True
        if session.get("last_event_at") is None or (
            observation.observed_at > session["last_event_at"]
        ):
            session["last_event_at"] = observation.observed_at

    # Rule 4: completion persists otherwise. A `watched` assertion above may
    # raise OR clear it; no other rule may change it.
    completed = bool(session.get("completed"))

    # Rule 5: a play is appended only on the false->true transition, and only
    # for an observation that is evidence of a viewing. A poll reports the
    # item's state, which can be stale relative to the session in flight, so it
    # never appends on its own.
    #
    # The appending observation must assert watched-ness ITSELF. The sticky
    # `session["completed"]` flag is not enough: a poll of an already-watched
    # title sets it (correctly — the progress row should say completed), and
    # the next `pause` of an abandoned replay asserts nothing, so gating on the
    # flag alone appends a history play for a viewing that never finished.
    record_play = (
        observation.records_play
        and observation.watched is True
        and not session.get("play_recorded")
    )
    if record_play:
        session["play_recorded"] = True

    return MergeResult(
        completed=completed,
        position_seconds=session.get("position_seconds"),
        duration_seconds=session.get("duration_seconds"),
        record_play=record_play,
        clear_progress=False,
    )


def play_external_id(media_id, video_id, session_started_at):
    """Build the deduplicating id for one session's play.

    The id is the session key: the app-level pre-check in `Movie.watch` and
    `Season.watch` returns the existing play instead of appending a second one,
    and the unique constraint on the play is the backstop — `(movie,
    external_id)` for `MoviePlay`, `(related_season, item, external_id)` for
    `Episode`.

    `session_started_at` MUST be the session's start time, passed unchanged. A
    `None` collapses the stamp to `''`, so every session of the same media
    shares one id and a genuinely distinct session is silently deduped away.
    """
    stamp = ""
    if session_started_at is not None:
        stamp = (
            session_started_at.isoformat()
            if hasattr(session_started_at, "isoformat")
            else str(session_started_at)
        )
    return f"stremio:{media_id}:{video_id or ''}:{stamp}"


def _append_play(user, item, external_id, ended_at):
    """Append one history play for a completed session.

    Returns whether a play was created. `Movie.watch` returns `(play, created)`;
    `Season.watch` returns an `EpisodeWatchResult(episode, created)`.

    The legacy verifier appends the same viewing when it completes a title at
    90%, and it dedups on a time window rather than on the session id this
    function passes. That check has to run here too, or one finished title
    lands as two history rows.
    """
    movie = Movie.objects.filter(item=item, user=user).first()
    if movie is not None:
        if play_dedupe.existing_movie_play_times(
            user,
            media_ids=[item.media_id],
            source=item.source,
        ).is_duplicate(item.media_id, ended_at):
            logger.debug(
                "stremio_tracker status=duplicate_play source=movie near=%s",
                ended_at,
            )
            return False
        _play, created = movie.watch(
            ended_at,
            external_id=external_id,
            entry_source="stremio",
        )
        return bool(created)

    # The tracked Season may not exist yet. An Episode row is created only for
    # an episode the user has already played, so the first viewing of an episode
    # has none — requiring one here would silently drop that play. Resolve (or
    # create) the season the same way the Jellyfin playback reporter does.
    season = fork_services_episode.resolve_or_create_season(
        user,
        item.media_id,
        item.source,
        item.season_number,
    )
    if season is None:
        return False

    play_key = (item.media_id, item.season_number, item.episode_number)
    if play_dedupe.existing_episode_play_times(
        user,
        media_ids=[item.media_id],
        source=item.source,
    ).is_duplicate(play_key, ended_at):
        logger.debug(
            "stremio_tracker status=duplicate_play source=episode near=%s",
            ended_at,
        )
        return False
    result = season.watch(
        item.episode_number,
        ended_at,
        external_id=external_id,
        entry_source="stremio",
    )
    return bool(result.created)


def persist_merge_result(
    user,
    item,
    result,
    *,
    media_id,
    video_id,
    session_started_at,
    ended_at,
    persisted_position_seconds=None,
    persisted_duration_seconds=None,
    persisted_completed=None,
):
    """Write one merge result. Returns whether a history play was appended.

    The three `persisted_*` arguments are what the last successful write stored
    for this identity, carried on the session. Stremio pushes `time_offset` no
    more often than ~90s while the verifier polls every 5-120s, so most polls
    repeat a position already stored — and every write appends a
    `ProgressChange` row that nothing prunes. A write is skipped only when the
    position, the duration, AND the completion state are all already stored, so
    a `completed` flag that arrives with an unchanged position is still written.
    """
    if item is None:
        return False

    ended_at = ended_at or timezone.now()
    unchanged = (
        not result.clear_progress
        and result.position_seconds is not None
        and result.position_seconds == persisted_position_seconds
        and result.duration_seconds == persisted_duration_seconds
        and result.completed == persisted_completed
    )

    # `upsert_playback_progress` is the one durable-progress sink: it takes the
    # row lock and records the ordered change a delta-sync client reads. The
    # position write must go through it rather than through the row directly,
    # and a duration-less observation must preserve the stored duration instead
    # of clearing it.
    with transaction.atomic():
        if result.clear_progress:
            removed, _detail = PlaybackProgress.objects.filter(
                user=user,
                item=item,
            ).delete()
            if removed:
                # Explicit tombstone: a cleared row is simply absent from a
                # timestamp query, and absence is never a delete.
                record_progress_deletion(user, item)
        elif result.position_seconds is not None and not unchanged:
            upsert_playback_progress(
                user,
                item,
                result.position_seconds,
                result.duration_seconds,
                completed=result.completed,
                preserve_duration=result.duration_seconds is None,
            )

        if not result.record_play:
            return False

        return _append_play(
            user,
            item,
            play_external_id(media_id, video_id, session_started_at),
            ended_at,
        )


def _session_key(user_id, media_type, media_id, video_id):
    return f"stremio_tracker_v1:{user_id}:{media_type}:{media_id}:{video_id or ''}"


def _load_session(user_id, media_type, media_id, video_id, now):
    """Return `(key, session)` for one media identity, starting one if absent.

    The cached session is the raw stored value; callers MUST still pass it
    through `session_for_observation` to cross a session boundary.
    """
    from django.core.cache import cache

    key = _session_key(user_id, media_type, media_id, video_id)
    session = cache.get(key)
    if session is None:
        session = new_session(video_id=video_id, started_at=now)
    return key, session

def _fold_observation(user, item, media_type, media_id, video_id, observation, now):
    """Merge one observation into its session and persist the result.

    Returns whether a history play was appended. `media_id` is the identity the
    session is keyed under — the series id for an episode — while `video_id` is
    the episode coordinate.
    """
    from django.core.cache import cache

    key, session = _load_session(user.id, media_type, media_id, video_id, now)
    # The returned session is the one that carries the boundary: a rewatch
    # starts a fresh session and must not reuse the settled one.
    session = session_for_observation(session, observation, now=now)
    result = apply_observation(session, observation)

    appended = persist_merge_result(
        user,
        item,
        result,
        media_id=media_id,
        video_id=video_id,
        session_started_at=session.get("started_at"),
        ended_at=now,
        persisted_position_seconds=session["persisted_position_seconds"],
        persisted_duration_seconds=session["persisted_duration_seconds"],
        persisted_completed=session["persisted_completed"],
    )
    _remember_persisted_progress(session, result)
    cache.set(key, session, timeout=_SESSION_TTL_SECONDS)
    return appended


def _remember_persisted_progress(session, result):
    """Record what `persist_merge_result` has now stored for this session.

    Only a position-bearing result writes progress, and a duration-less one
    preserves the stored duration, so both are folded in here rather than
    recomputed by the writer.
    """
    if result.clear_progress:
        session["persisted_position_seconds"] = None
        session["persisted_duration_seconds"] = None
        session["persisted_completed"] = None
    elif result.position_seconds is not None:
        session["persisted_position_seconds"] = result.position_seconds
        if result.duration_seconds is not None:
            session["persisted_duration_seconds"] = result.duration_seconds
        session["persisted_completed"] = result.completed


def _looks_complete(event):
    """Return whether a `stop` position clears Stremio's watched threshold.

    Deliberately not `is_played()`, which requires the final 30 seconds and
    would drop every completion between 70% and the credits.
    """
    if not event.duration_seconds:
        return False
    return event.position_seconds >= event.duration_seconds * WATCHED_THRESHOLD_COEF


def record_player_event(user, media_type, media_id, extra, *, now=None):
    """Handle one `player` event: parse, resolve, merge, persist.

    Returns a status string for logging and tests.
    """
    event = parse_player_extra(extra)
    if event is None:
        logger.info("stremio_tracker status=invalid_extra source=player")
        return "invalid_extra"

    media_id = unquote(media_id)
    now = now or timezone.now()

    # The player path id is already the video id for an episode (`tt123:1:2`),
    # so the series id is its prefix; a movie id is the id.
    video_id = media_id if media_type == "series" and ":" in media_id else None
    series_id = media_id.split(":")[0] if video_id else media_id

    item = resolve_media_identity(user, media_type, series_id, video_id)
    if item is None:
        logger.info(
            "stremio_tracker status=unresolved_media source=player media_type=%s",
            media_type,
        )
        return "unresolved_media"

    # `watched` is three-state. Only a threshold-meeting stop is a positive
    # signal; everything else is None, never False, which would assert the
    # media is NOT watched and clear a session the flag already completed.
    watched = None
    if event.action == "stop" and _looks_complete(event):
        watched = True

    observation = Observation(
        action=event.action,
        position_seconds=event.position_seconds,
        duration_seconds=event.duration_seconds,
        watched=watched,
        observed_at=now,
        video_id=video_id,
    )
    _fold_observation(user, item, media_type, series_id, video_id, observation, now)
    return "recorded"


_WATCHED_ACTIONS = frozenset({"watched"})
_UNWATCHED_ACTIONS = frozenset({"unwatched"})


def record_library_event(user, media_type, media_id, extra, *, now=None):
    """Handle one `library` event: parse, resolve each target, merge, persist.

    A library event names a library *item* in the path (the series for a
    series) and carries the episode(s) in `videoId` — the opposite of the
    `player` path, whose id is the video id itself. With no video id the event
    is item-level, which for a series means the series itself.

    Returns a status string for logging and tests.
    """
    event = parse_library_extra(extra)
    if event is None:
        logger.info("stremio_tracker status=invalid_extra source=library")
        return "invalid_extra"

    media_id = unquote(media_id)
    now = now or timezone.now()

    targets = list(event.video_ids) or [None]
    if len(targets) > VIDEO_ID_BATCH_LIMIT:
        logger.info(
            "stremio_tracker status=batch_truncated count=%s",
            len(targets),
        )
        targets = targets[:VIDEO_ID_BATCH_LIMIT]

    recorded = 0
    for video_id in targets:
        if _record_one_library_target(
            user,
            media_type,
            media_id,
            video_id,
            event.action,
            now,
        ):
            recorded += 1

    if recorded == 0:
        return "unresolved_media"
    return "recorded"


def _record_one_library_target(user, media_type, media_id, video_id, action, now):
    """Apply one library action to one media identity. Returns whether it landed."""
    # A movie has one video, so a `videoId` on a movie event (Stremio sends the
    # id itself) must not become part of the identity: the player and poll paths
    # both force None, and a movie session keyed with a video id would be a
    # SECOND session for the same movie, splitting the merge point.
    video_id = video_id if media_type == "series" else None
    item = resolve_media_identity(user, media_type, media_id, video_id)
    if item is None:
        # Never log the id itself: it is client-supplied and unbounded.
        logger.info(
            "stremio_tracker status=unresolved_media source=library media_type=%s",
            media_type,
        )
        return False

    # `watched` is three-state, and this resource is where `False` is
    # legitimate: an explicit un-watch asserts the item is not watched and
    # clears a completed session. `libraryAdd`/`libraryRemove` assert nothing,
    # so they pass `None` — a `False` would wrongly clear completed state.
    watched = None
    if action in _WATCHED_ACTIONS:
        watched = True
    elif action in _UNWATCHED_ACTIONS:
        watched = False

    observation = Observation(
        action=action,
        position_seconds=None,
        duration_seconds=None,
        watched=watched,
        observed_at=now,
        video_id=video_id,
    )

    _fold_observation(user, item, media_type, media_id, video_id, observation, now)
    return True

def record_poll_observation(user, media_type, media_id, observation, *, now=None):
    """Fold one poll observation into the merge point for its media identity.

    Returns whether the identity resolved. This is the wiring for
    `stremio_playback.poll_observation_from_state`, and it is what stores a
    resume position for a client that cannot emit player events.

    The observation carries `records_play=False`: the poll reads the cloud
    library, so it reports the item's state rather than evidence about the
    session in flight. Completion and the history play stay the verifier's —
    asserting the library's flag as a viewing would let a stale completed
    snapshot complete a replay, which is the case the verifier's post-baseline
    evidence exists to reject.
    """
    now = now or timezone.now()

    # The poll's media id is already the video id for an episode (`tt123:1:2`),
    # so the series id is its prefix; a movie id is the id. The same split the
    # player path makes, so both address one session.
    video_id = media_id if media_type == "series" and ":" in media_id else None
    series_id = media_id.split(":")[0] if video_id else media_id

    item = resolve_media_identity(user, media_type, series_id, video_id)
    if item is None:
        logger.info(
            "stremio_tracker status=unresolved_media source=poll media_type=%s",
            media_type,
        )
        return False

    _fold_observation(user, item, media_type, series_id, video_id, observation, now)
    return True
