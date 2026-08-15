"""Bounded Redis admission control for Stremio playback events."""

from __future__ import annotations

import logging
from collections import Counter

import redis
from django_redis import get_redis_connection

from app.backfill_queue import namespaced

logger = logging.getLogger(__name__)

MAX_PENDING_PER_USER = 8
PENDING_TTL_SECONDS = 600
PENDING_KEY_PREFIX = "stremio_pending_v1"
ADMISSION_COUNTS = Counter()

RESERVE_SCRIPT = """
if redis.call('SISMEMBER', KEYS[1], ARGV[1]) == 1 then
    return 2
end
if redis.call('SCARD', KEYS[1]) >= tonumber(ARGV[2]) then
    return 0
end
redis.call('SADD', KEYS[1], ARGV[1])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3]))
return 1
"""


def _client():
    """Return the raw Redis client or None when Redis is unavailable."""
    try:
        return get_redis_connection("default")
    except Exception as error:  # pragma: no cover - backend-specific failure
        logger.info("stremio_queue status=unavailable error=%s", error)
        return None


def _key(user_id: int) -> str:
    return namespaced(f"{PENDING_KEY_PREFIX}:{user_id}")


def member(media_type: str, media_id: str) -> str:
    """Return the canonical deduplication member for one playback item."""
    return f"{media_type}:{media_id}"


def _record_admission(status: str, user_id: int) -> None:
    """Record process-local admission totals for operational diagnostics."""
    ADMISSION_COUNTS[status] += 1
    logger.info(
        "stremio_queue_admission status=%s count=%s user_id=%s",
        status,
        ADMISSION_COUNTS[status],
        user_id,
    )


def reserve_pending(user_id: int, queue_member: str) -> str:
    """Atomically admit one member as accepted, duplicate, limited, or unavailable."""
    client = _client()
    if client is None:
        _record_admission("unavailable", user_id)
        return "unavailable"
    try:
        result = int(
            client.eval(
                RESERVE_SCRIPT,
                1,
                _key(user_id),
                queue_member,
                MAX_PENDING_PER_USER,
                PENDING_TTL_SECONDS,
            ),
        )
    except redis.RedisError as error:
        logger.info(
            "stremio_queue status=unavailable user_id=%s error=%s",
            user_id,
            error,
        )
        _record_admission("unavailable", user_id)
        return "unavailable"

    status = {1: "accepted", 2: "duplicate"}.get(result, "limited")
    _record_admission(status, user_id)
    return status


def release_pending(user_id: int, queue_member: str) -> bool:
    """Release a member when processing starts or dispatch fails."""
    client = _client()
    if client is None:
        return False
    try:
        removed = bool(client.srem(_key(user_id), queue_member))
        if client.scard(_key(user_id)) == 0:
            client.delete(_key(user_id))
    except redis.RedisError as error:
        logger.info(
            "stremio_queue_release status=unavailable user_id=%s error=%s",
            user_id,
            error,
        )
        return False
    return removed
