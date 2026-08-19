"""A Redis-set work queue for the metadata backfills.

Seven backfills (watch providers, genres, runtimes, episode runtimes, credits,
IGDB ratings, Trakt popularity) each kept their pending IDs as one pickled list
under a single cache key, and each enqueued by reading the whole list, unioning
into it, and writing the whole list back. That is O(N) bytes through Redis per
batch and O(N^2) per sweep, and since the reconcilers re-enqueued every
candidate every five minutes, the same multi-megabyte value was rewritten
continuously - which with ``--appendonly yes`` also meant continuous disk
writes (issue #521).

A Redis set does the same job in O(batch): ``SADD`` to enqueue, ``SPOP`` to take
work, and the deduplication the ``set().union()`` was there for comes free.

The second thing this fixes is a silent failure. Each copy wrapped its cache
work in ``try/except`` and fell back to dispatching the IDs directly. With
``IGNORE_EXCEPTIONS`` on the cache that ``except`` became unreachable -
``cache.set`` and ``cache.add`` return ``None`` instead of raising, the drain is
never scheduled, and the IDs are dropped with no error anywhere. Callers here
get an explicit "the queue is unavailable" answer instead of inferring it from
an exception that no longer arrives.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

import redis
from django.conf import settings
from django_redis import get_redis_connection

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

logger = logging.getLogger(__name__)

# How long the "a drain task is already on its way" marker lives. Short, because
# losing it only costs one redundant drain, while holding it too long stalls the
# queue until the next enqueue.
SCHEDULED_MARKER_TTL = 30


def _client():
    """Return a raw Redis client, or None when the cache isn't Redis-backed."""
    try:
        return get_redis_connection("default")
    except Exception as error:
        logger.debug("No raw Redis connection available: %s", error)
        return None


def namespaced(key: str) -> str:
    """Return the key with REDIS_PREFIX applied.

    Going through the raw client bypasses django-redis's KEY_PREFIX, so the
    prefix has to be applied here or two Floppy instances sharing one Redis -
    which is exactly what REDIS_PREFIX exists to support - would share each
    other's backfill queues.
    """
    prefix = getattr(settings, "REDIS_PREFIX", None)
    return f"{prefix}:{key}" if prefix else key


def _decode(value, coerce: Callable[[str], object]):
    """Return a set member converted back to the type the caller enqueued."""
    text = value.decode() if isinstance(value, bytes) else str(value)
    try:
        return coerce(text)
    except (TypeError, ValueError):
        return None


def enqueue(
    queue_key: str,
    scheduled_key: str,
    members: Iterable,
    *,
    ttl: int,
    drain_task,
    countdown: int = 10,
    drain_kwargs: dict | None = None,
) -> bool:
    """Add members to the queue and ensure a drain task is scheduled.

    Returns False when the queue is unavailable, so the caller can dispatch the
    work directly instead of dropping it.
    """
    members = [str(member) for member in members]
    if not members:
        return True

    client = _client()
    if client is None:
        return False

    queue_key, scheduled_key = namespaced(queue_key), namespaced(scheduled_key)
    try:
        pipe = client.pipeline()
        pipe.sadd(queue_key, *members)
        # Refreshed on every enqueue so an actively-fed queue never expires
        # mid-drain, while an abandoned one still ages out.
        pipe.expire(queue_key, ttl)
        pipe.set(scheduled_key, 1, ex=SCHEDULED_MARKER_TTL, nx=True)
        results = pipe.execute()
    except redis.RedisError as error:
        logger.debug("Backfill queue %s unavailable: %s", queue_key, error)
        return False

    # SET NX returns truthy only for the caller that created the marker, so
    # exactly one of several concurrent enqueues schedules the drain.
    if results[-1]:
        drain_task.apply_async(countdown=countdown, kwargs=drain_kwargs or {})
    return True


def take(
    queue_key: str,
    scheduled_key: str,
    batch_size: int,
    *,
    coerce: Callable[[str], object] = int,
) -> tuple[list, bool]:
    """Pop up to batch_size members. Returns (batch, more_remaining).

    Clears the scheduled marker as it goes, so a subsequent enqueue can schedule
    the next drain.
    """
    client = _client()
    if client is None:
        return [], False

    queue_key, scheduled_key = namespaced(queue_key), namespaced(scheduled_key)
    try:
        raw = client.spop(queue_key, batch_size) or []
        remaining = client.scard(queue_key)
        client.delete(scheduled_key)
    except redis.RedisError as error:
        logger.debug("Backfill queue %s unavailable: %s", queue_key, error)
        return [], False

    # spop returns a single value rather than a set when count is omitted; we
    # always pass one, but be defensive about the shape.
    if not isinstance(raw, (set, list, tuple)):
        raw = [raw]

    batch = [_decode(value, coerce) for value in raw]
    return [member for member in batch if member is not None], bool(remaining)


def reschedule(
    scheduled_key: str,
    drain_task,
    countdown: int = 10,
    drain_kwargs: dict | None = None,
) -> None:
    """Schedule the next drain pass unless one is already pending."""
    client = _client()
    if client is None:
        drain_task.apply_async(countdown=countdown, kwargs=drain_kwargs or {})
        return
    try:
        claimed = client.set(
            namespaced(scheduled_key), 1, ex=SCHEDULED_MARKER_TTL, nx=True
        )
    except redis.RedisError:
        # Better a duplicate drain (the queue is a set, so it's idempotent) than
        # a queue that stops being drained.
        claimed = True
    if claimed:
        drain_task.apply_async(countdown=countdown, kwargs=drain_kwargs or {})


def depth(queue_key: str) -> int:
    """Return the number of queued members, or 0 if unknown."""
    client = _client()
    if client is None:
        return 0
    try:
        return int(client.scard(namespaced(queue_key)))
    except redis.RedisError:
        return 0


def members(queue_key: str, *, coerce: Callable[[str], object] = int) -> set:
    """Return the queued members without removing them. For tests and support."""
    client = _client()
    if client is None:
        return set()
    try:
        raw = client.smembers(namespaced(queue_key))
    except redis.RedisError:
        return set()
    decoded = {_decode(value, coerce) for value in raw}
    return {member for member in decoded if member is not None}


def clear(*keys: str) -> None:
    """Delete queue and marker keys. For tests and support."""
    client = _client()
    if client is None:
        return
    with contextlib.suppress(redis.RedisError):
        client.delete(*[namespaced(key) for key in keys])
