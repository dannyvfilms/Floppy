"""Bounded, session-safe verification of Stremio playback completion.

A start webhook creates one Redis-guarded session per user and canonical media
identity.  Its first library observation becomes the baseline.  Completion
requires both Stremio's completion state and post-baseline evidence, so a stale
recently-completed snapshot cannot complete a replay.  Sessions end on verified
completion, supersession, terminal account failure, or an absolute runtime-based
deadline.  Provider failures have a separate consecutive-failure budget.

Same-season auto-next is intrinsically sequential.  Cross-season rollover is
trusted only when the locally persisted, media-server-sourced season episode
count proves that the source episode is the season finale.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta

import redis
import requests
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django_redis import get_redis_connection

from app.backfill_queue import namespaced
from app.models.tv import Season
from app.providers.services import ProviderAPIError
from integrations.imports import helpers
from integrations.imports.helpers import MediaImportError
from integrations.imports.stremio import get_library_items
from integrations.models import StremioAccount
from integrations.stremio_events import milliseconds_to_seconds, parse_episode_id

logger = logging.getLogger(__name__)

SESSION_PREFIX = "stremio_playback_v1"
BASELINE_DISCOVERY_SECONDS = 15 * 60
MINIMUM_GRACE_SECONDS = 30 * 60
MAXIMUM_GRACE_SECONDS = 60 * 60
MAXIMUM_SESSION_SECONDS = 6 * 60 * 60
MAX_TRANSIENT_FAILURES = 5
TRANSIENT_BACKOFF_SECONDS = (30, 60, 120, 120, 120)
INITIAL_OBSERVATION_SECONDS = 60
PUBLICATION_DELAY_TOLERANCE_SECONDS = 2 * 60
AUTO_NEXT_THRESHOLD = 85.0
SERVER_ERROR_MINIMUM = 500

CREATE_SCRIPT = """
if redis.call('EXISTS', KEYS[1]) == 1 then
    return redis.call('GET', KEYS[1])
end
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
redis.call('SET', KEYS[2], KEYS[1], 'EX', ARGV[2])
return ARGV[1]
"""

CAS_SCRIPT = """
local current = redis.call('GET', KEYS[1])
if not current or current ~= ARGV[1] then
    return 0
end
if ARGV[2] == '' then
    redis.call('DEL', KEYS[1])
    redis.call('DEL', KEYS[2])
else
    redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
    redis.call('EXPIRE', KEYS[2], ARGV[3])
end
return 1
"""


@dataclass(frozen=True)
class PlaybackDecision:
    """One directly testable state-machine outcome for the Celery adapter."""

    status: str
    session_id: str | None = None
    countdown: int | None = None
    payload: dict | None = None
    reason: str | None = None
    user_id: int | None = None


def _client():
    try:
        return get_redis_connection("default")
    except Exception as error:  # pragma: no cover - backend-specific failure
        logger.info("stremio_playback status=guard_unavailable error=%s", error)
        return None


def _identity(payload):
    media_id = str(payload.get("id") or "")
    media_type = str(payload.get("type") or "")
    if not media_id or media_type not in {"movie", "series"}:
        return None
    return media_type, media_id


def _key(user_id, media_type, media_id):
    return namespaced(f"{SESSION_PREFIX}:{user_id}:{media_type}:{media_id}")


def _index_key(session_id):
    return namespaced(f"{SESSION_PREFIX}:session:{session_id}")


def _dump(session):
    return json.dumps(session, sort_keys=True, separators=(",", ":"))


def _load(raw):
    if isinstance(raw, bytes):
        raw = raw.decode()
    return json.loads(raw)


def _aware(value):
    parsed = parse_datetime(str(value)) if value else None
    if parsed is not None and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def _remaining_ttl(session, now):
    deadline = _aware(session["deadline"])
    return max(1, int((deadline - now).total_seconds()) + 60)


def start_session(payload, user_id, *, now=None):
    """Atomically create or reuse the one active verifier for this playback."""
    identity = _identity(payload)
    if identity is None:
        return PlaybackDecision("terminal", reason="invalid_payload")
    now = now or timezone.now()
    media_type, media_id = identity
    session = {
        "id": uuid.uuid4().hex,
        "user_id": user_id,
        "media_type": media_type,
        "media_id": media_id,
        "started_at": now.isoformat(),
        "deadline": (now + timedelta(seconds=BASELINE_DISCOVERY_SECONDS)).isoformat(),
        "runtime_deadline_set": False,
        "baseline": None,
        "current_session_seen": False,
        "reset_seen": False,
        "best": None,
        "transient_failures": 0,
        "revision": 0,
    }
    client = _client()
    if client is None:
        return PlaybackDecision("terminal", reason="guard_unavailable")
    proposed = _dump(session)
    try:
        stored = client.eval(
            CREATE_SCRIPT,
            2,
            _key(user_id, media_type, media_id),
            _index_key(session["id"]),
            proposed,
            BASELINE_DISCOVERY_SECONDS + 60,
        )
    except redis.RedisError as error:
        logger.info("stremio_playback status=guard_unavailable error=%s", error)
        return PlaybackDecision("terminal", reason="guard_unavailable")
    active = _load(stored)
    created = active["id"] == session["id"]
    return PlaybackDecision(
        "schedule" if created else "duplicate",
        session_id=active["id"],
        countdown=INITIAL_OBSERVATION_SECONDS if created else None,
    )


def _read_session(session_id):
    client = _client()
    if client is None:
        return None, None, None
    try:
        key = client.get(_index_key(session_id))
        if key:
            raw = client.get(key)
            if raw:
                return client, key, raw.decode() if isinstance(raw, bytes) else raw
    except redis.RedisError as error:
        logger.info("stremio_playback status=guard_unavailable error=%s", error)
    return client, None, None


def _cas(client, key, old_raw, session, now):
    new_raw = _dump(session)
    try:
        won = client.eval(
            CAS_SCRIPT,
            2,
            key,
            _index_key(session["id"]),
            old_raw,
            new_raw,
            _remaining_ttl(session, now),
        )
    except redis.RedisError as error:
        logger.info("stremio_playback status=guard_unavailable error=%s", error)
        return False
    return bool(won)


def _close(client, key, old_raw, session_id):
    try:
        return bool(
            client.eval(
                CAS_SCRIPT, 2, key, _index_key(session_id), old_raw, "", 1
            )
        )
    except redis.RedisError as error:
        logger.info("stremio_playback status=guard_unavailable error=%s", error)
        return False


def _float(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def normalize_state(entry, target_id, media_type):
    """Return the stable Stremio fields used by the state machine."""
    state = (entry or {}).get("state") or {}
    duration = _float(state.get("duration"))
    watched = _float(state.get("timeWatched"))
    return {
        "video_id": str(state.get("video_id") or ""),
        "last_watched": (_aware(state.get("lastWatched")).isoformat() if _aware(state.get("lastWatched")) else None),
        "times_watched": _float(state.get("timesWatched")),
        "time_watched": watched,
        "duration": duration,
        "flagged": _float(state.get("flaggedWatched")),
        "watched_percent": watched / duration * 100.0 if duration > 0 else 0.0,
        "exact": media_type == "movie" or str(state.get("video_id") or "") == target_id,
    }


def _watched_assertion(*values):
    """Return True/False from Stremio's watched fields, or None when absent.

    Stremio records watched-ness in two places — `timesWatched` (a count) and
    `flaggedWatched` (the manual flag) — and the repo's importer reads them as a
    union (`integrations/imports/stremio.py`).  A value that cannot be parsed is
    treated as absent: asserting False would clear a completed session, and only
    the client can know it did not.
    """
    usable = []
    for value in values:
        try:
            usable.append(float(value))
        except (TypeError, ValueError):
            continue
    if not usable:
        return None
    return any(number > 0 for number in usable)

def poll_observation_from_state(media_type, entry):
    """Build one tracker Observation from a cloud-library entry, or None.

    This is the poller's output to the tracker merge point.  It exists because
    `normalize_state` drops Stremio's `timeOffset`: without it a client that
    cannot emit player events leaves no resume position behind.

    `observed_at` is stamped with OUR clock, not Stremio's `lastWatched`.
    Ordering compares observations across sources, and player events are
    stamped with server receive time, so a Stremio-domain timestamp is not
    comparable.  `lastWatched` stays data — the poller's own session-evidence
    and auto-next checks read it — but it is never the ordering stamp.

    `watched` is three-state, read from Stremio's own `timesWatched` and
    `flaggedWatched` as a union rather than re-derived from
    `time_watched > duration * 0.7`: a naturally-completed item carries only
    `timesWatched`, so reading the manual flag alone would assert False and
    clear the completed session.  When every usable field is zero the client is
    explicitly asserting not-watched; when no field is usable nothing is
    asserted and the value stays None.

    `records_play` is False.  The library flag describes the ITEM, not the
    session in flight: a replay of an already-watched title still reads
    `timesWatched=1`, so treating it as evidence of a viewing would complete
    the replay the moment it started — the stale-snapshot case the verifier's
    post-baseline evidence exists to reject.  Position is what this observation
    contributes, and the history play stays the verifier's to append.

    Wiring this in does NOT double-append a completed play.  `records_play`
    keeps the poll from appending at all, and the two paths that can append —
    the tracker's `_append_play` and the webhook processor — both measure the
    candidate against `play_dedupe` before writing, so one viewing lands as one
    history row.
    """
    state = entry.get("state") if isinstance(entry, dict) else None
    if not isinstance(state, dict):
        logger.info(
            "stremio_poll status=unusable media_type=%s reason=missing_state",
            media_type,
        )
        return None

    from integrations import stremio_tracker

    return stremio_tracker.Observation(
        action="observed",
        # A zero offset means "no resume point", not "resume at 0": storing 0
        # would overwrite a real position. The same applies to a zero duration,
        # which is why neither is treated as a value. A missing duration no
        # longer discards the observation — `persist_merge_result` preserves a
        # stored duration when the observation carries none.
        position_seconds=milliseconds_to_seconds(state.get("timeOffset")) or None,
        duration_seconds=milliseconds_to_seconds(state.get("duration")) or None,
        watched=_watched_assertion(
            state.get("timesWatched"), state.get("flaggedWatched")
        ),
        observed_at=timezone.now(),
        video_id=(state.get("video_id") or None) if media_type == "series" else None,
        records_play=False,
    )

def _entry_has_live_progress(entry):
    """Return whether Stremio counts this entry's position as live progress.

    Mirrors `LibraryItem::is_in_continue_watching` in stremio-core:
    `not removed or temp`. `removed` alone is NOT a reason to skip — Stremio
    keeps auto-added entries for a year and `temp` marks them, so
    `removed and temp` is the dominant bucket for real in-flight progress
    (319 of the 411 entries carrying a `timeOffset` in this account). Only
    `removed and not temp` — explicitly added, then explicitly removed — has
    left the user's active library, and its `timeOffset` is a leftover rather
    than a resume point.
    """
    return not entry.get("removed") or bool(entry.get("temp"))

def _record_poll_position(user, session, entry, now):
    """Fold this poll's resume position into the tracker merge point.

    Auxiliary to the session's purpose, so a failure is logged and swallowed:
    the completion logic in `observe_session` is what the task exists for, and
    it must not be abandoned because a position write failed.  This mirrors
    `app.live_playback._store_playback_progress`, the other auxiliary progress
    write.
    """
    from integrations import stremio_tracker

    try:
        observation = poll_observation_from_state(session["media_type"], entry)
        if observation is None:
            return
        stremio_tracker.record_poll_observation(
            user,
            session["media_type"],
            session["media_id"],
            observation,
            now=now,
        )
    except Exception:
        logger.warning("Stremio poll position update failed", exc_info=True)

def deadline_for_runtime(started, duration_ms):
    """Return the absolute bounded deadline for one known media runtime."""
    runtime = max(1.0, duration_ms / 1000.0)
    grace = max(MINIMUM_GRACE_SECONDS, min(MAXIMUM_GRACE_SECONDS, runtime * 0.25))
    lifetime = min(MAXIMUM_SESSION_SECONDS, runtime + grace)
    return started + timedelta(seconds=lifetime)


def polling_delay(duration_ms, watched_percent):
    """Poll near useful thresholds while remaining efficient for short media."""
    runtime = max(1.0, duration_ms / 1000.0)
    target = AUTO_NEXT_THRESHOLD if watched_percent < AUTO_NEXT_THRESHOLD else 90.0
    step = max(1.0, min(10.0, max(0.0, target - watched_percent) / 2.0))
    return round(max(5.0, min(120.0, runtime * step / 100.0)))


def _authoritative_final_episode(user_id, series_id, season_number):
    return (
        Season.objects.filter(
            user_id=user_id,
            related_tv__item__provider_external_ids__imdb_id=series_id,
            item__season_number=season_number,
            item__local_season_episode_count__isnull=False,
        )
        .values_list("item__local_season_episode_count", flat=True)
        .first()
    )


def is_sequential_next(user_id, target_video, current_video):
    """Return whether current_video safely follows target_video."""
    target = parse_episode_id(target_video)
    current = parse_episode_id(current_video)
    if not target or not current or target[0] != current[0]:
        return False
    _, target_season, target_episode = target
    _, current_season, current_episode = current
    if current_season == target_season and current_episode == target_episode + 1:
        return True
    if current_season != target_season + 1 or current_episode != 1:
        return False
    final_episode = _authoritative_final_episode(user_id, target[0], target_season)
    return final_episode is not None and target_episode == final_episode


def _session_evidence(session, observation):
    baseline = session["baseline"]
    if not observation["exact"]:
        return session["current_session_seen"]
    if observation["time_watched"] < baseline["time_watched"]:
        session["reset_seen"] = True
        session["best"] = observation
    last_advanced = (
        _aware(observation["last_watched"]) is not None
        and (
            (
                _aware(baseline["last_watched"]) is not None
                and _aware(observation["last_watched"])
                > _aware(baseline["last_watched"])
            )
            or (
                _aware(baseline["last_watched"]) is None
                and _aware(observation["last_watched"])
                >= _aware(session["started_at"])
            )
        )
    )
    times_advanced = observation["times_watched"] > baseline["times_watched"]
    best = session.get("best") or baseline
    position_advanced = observation["time_watched"] > best["time_watched"]
    if times_advanced or (last_advanced and position_advanced):
        session["current_session_seen"] = True
    return session["current_session_seen"]


def _baseline_supports_auto_next(session, observed_at):
    """Trust a qualifying target baseline only after sequential auto-next."""
    baseline = session["baseline"]
    baseline_last_watched = _aware(baseline["last_watched"])
    started_at = _aware(session["started_at"])
    return (
        observed_at > started_at
        and baseline["exact"]
        and baseline["video_id"] == session["media_id"]
        and baseline["watched_percent"] >= AUTO_NEXT_THRESHOLD
        and baseline["flagged"] >= 1
        and baseline_last_watched is not None
        and baseline_last_watched
        >= started_at - timedelta(seconds=PUBLICATION_DELAY_TOLERANCE_SECONDS)
    )


def _retryable_provider_error(error):
    status = error.status_code
    return status is None or status in {408, 429} or status >= SERVER_ERROR_MINIMUM


def _load_library(session):
    """Return `(user, library_items)` for a session's Stremio account.

    Raises `TerminalPlaybackError` for a failure that cannot recover during
    this playback, and `TransientPlaybackError` for one governed by the
    consecutive-failure budget.  The user is returned because folding a poll
    observation into the tracker needs the resolved identity it owns.
    """
    user_model = get_user_model()
    try:
        user = user_model.objects.get(id=session["user_id"], is_active=True)
    except user_model.DoesNotExist as error:
        reason = "user_missing_or_inactive"
        raise TerminalPlaybackError(reason) from error
    try:
        account = user.stremio_account
    except StremioAccount.DoesNotExist as error:
        reason = "account_missing"
        raise TerminalPlaybackError(reason) from error
    if not account.is_connected:
        reason = "account_disconnected"
        raise TerminalPlaybackError(reason)
    try:
        auth_key = helpers.decrypt_or_raise(account.auth_key)
    except MediaImportError as error:
        reason = "credential_configuration"
        raise TerminalPlaybackError(reason) from error
    try:
        return user, get_library_items(auth_key)
    except ProviderAPIError as error:
        if _retryable_provider_error(error):
            reason = "provider_unavailable"
            raise TransientPlaybackError(reason) from error
        reason = "provider_auth_or_configuration"
        raise TerminalPlaybackError(reason) from error
    except requests.exceptions.RequestException as error:
        reason = "network_unavailable"
        raise TransientPlaybackError(reason) from error
    except MediaImportError as error:
        reason = "provider_auth_or_configuration"
        raise TerminalPlaybackError(reason) from error


class TerminalPlaybackError(Exception):
    """Known failure which cannot recover during this playback session."""


class TransientPlaybackError(Exception):
    """Known temporary failure governed by the separate failure budget."""


def observe_session(session_id, *, now=None):
    """Observe and atomically advance one playback session."""
    now = now or timezone.now()
    client, key, old_raw = _read_session(session_id)
    if client is None:
        return PlaybackDecision("terminal", session_id, reason="guard_unavailable")
    if key is None:
        return PlaybackDecision("duplicate", session_id, reason="session_inactive")
    session = _load(old_raw)
    if now >= _aware(session["deadline"]):
        _close(client, key, old_raw, session_id)
        return PlaybackDecision("expired", session_id, reason="deadline")

    try:
        user, items = _load_library(session)
    except TerminalPlaybackError as error:
        _close(client, key, old_raw, session_id)
        return PlaybackDecision("terminal", session_id, reason=str(error))
    except TransientPlaybackError as error:
        failures = session["transient_failures"] + 1
        if failures > MAX_TRANSIENT_FAILURES:
            _close(client, key, old_raw, session_id)
            return PlaybackDecision("terminal", session_id, reason="transient_budget_exhausted")
        session["transient_failures"] = failures
        session["revision"] += 1
        countdown = TRANSIENT_BACKOFF_SECONDS[failures - 1]
        if now + timedelta(seconds=countdown) >= _aware(session["deadline"]):
            _close(client, key, old_raw, session_id)
            return PlaybackDecision("expired", session_id, reason="deadline")
        if not _cas(client, key, old_raw, session, now):
            return PlaybackDecision("duplicate", session_id, reason="stale_observation")
        return PlaybackDecision("schedule", session_id, countdown, reason=str(error))

    session["transient_failures"] = 0
    entry_id = session["media_id"].split(":", 1)[0] if session["media_type"] == "series" else session["media_id"]
    entry = next((item for item in items if str(item.get("_id") or "") == entry_id), None)
    if entry is None:
        session["revision"] += 1
        if not _cas(client, key, old_raw, session, now):
            return PlaybackDecision("duplicate", session_id, reason="stale_observation")
        return PlaybackDecision("schedule", session_id, 30, reason="library_item_missing")
    observation = normalize_state(entry, session["media_id"], session["media_type"])

    # The poll is the only source that reports a resume position for a client
    # that cannot emit player events.  Gated on `exact`: the library's state is
    # only about this session's video, and folding a sibling episode's position
    # would file it under the wrong identity.  Gated on liveness because a
    # resume point is library-scoped; completion below still runs, so a removed
    # item's viewing still reaches history.
    if observation["exact"] and _entry_has_live_progress(entry):
        _record_poll_position(user, session, entry, now)

    if observation["duration"] > 0 and not session["runtime_deadline_set"]:
        session["deadline"] = deadline_for_runtime(
            _aware(session["started_at"]), observation["duration"]
        ).isoformat()
        session["runtime_deadline_set"] = True

    if session["baseline"] is None:
        session["baseline"] = observation
        session["best"] = observation
        session["revision"] += 1
        countdown = polling_delay(observation["duration"], observation["watched_percent"])
        if not _cas(client, key, old_raw, session, now):
            return PlaybackDecision("duplicate", session_id, reason="stale_observation")
        return PlaybackDecision("schedule", session_id, countdown, reason="baseline_captured")

    evidence = _session_evidence(session, observation)
    best = session["best"]
    if observation["exact"] and observation["watched_percent"] >= best["watched_percent"]:
        session["best"] = observation

    sequential = False
    if session["media_type"] == "series" and not observation["exact"]:
        sequential = is_sequential_next(
            session["user_id"], session["media_id"], observation["video_id"]
        )
        if not sequential:
            _close(client, key, old_raw, session_id)
            return PlaybackDecision("superseded", session_id, reason="video_mismatch")
        evidence = evidence or _baseline_supports_auto_next(session, now)

    completion_state = session["best"] if sequential else observation
    threshold = AUTO_NEXT_THRESHOLD if sequential else 90.0
    complete = (
        evidence
        and completion_state["watched_percent"] >= threshold
        and completion_state["flagged"] >= 1
        and completion_state["last_watched"] is not None
    )
    if complete:
        if not _close(client, key, old_raw, session_id):
            return PlaybackDecision("duplicate", session_id, reason="completion_already_claimed")
        watched_at = _aware(completion_state["last_watched"])
        payload = {
            "id": session["media_id"],
            "type": session["media_type"],
            "viewedAt": int(watched_at.timestamp()),
            "_floppy_verified_completion": True,
        }
        return PlaybackDecision(
            "complete", session_id, payload=payload, user_id=session["user_id"]
        )

    session["revision"] += 1
    countdown = polling_delay(
        observation["duration"] or session["best"]["duration"],
        observation["watched_percent"],
    )
    if now + timedelta(seconds=countdown) >= _aware(session["deadline"]):
        _close(client, key, old_raw, session_id)
        return PlaybackDecision("expired", session_id, reason="deadline")
    if not _cas(client, key, old_raw, session, now):
        return PlaybackDecision("duplicate", session_id, reason="stale_observation")
    return PlaybackDecision("schedule", session_id, countdown, reason="not_complete")
