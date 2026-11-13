"""Tell "the lock is held" apart from "the cache is broken".

The cache is configured with ``IGNORE_EXCEPTIONS``, which is right for the
hundreds of read-through call sites: a backend failure and a miss mean the same
thing to a cache, so both should just fall through to the source of truth.

It is *wrong* for the ~20 places that use ``cache.add`` as a lock, because
``IGNORE_EXCEPTIONS`` turns a failure into ``None`` and ``if not cache.add(...)``
reads that as "someone else holds it". Whether that is safe depends entirely on
what the lock guards:

* A lock around **best-effort maintenance** should fail closed. Skipping a cache
  warm during a Redis outage costs nothing, and piling background work onto an
  already-struggling host costs plenty.
* A lock around **work the user asked for** must fail open. Silently refusing an
  import or dropping a scrobble because the cache was briefly unwell is data
  loss, and these paths all have their own downstream duplicate protection.

``cache_add`` exposes the three states so callers can say which they are, rather
than inheriting whichever behaviour falsiness happens to give them. The
tri-state shape is the one already used by ``discover/tab_cache._cache_add``;
this is that pattern made explicit and shared.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from collections import OrderedDict
from contextlib import suppress

from django.core.cache import cache
from django_redis.compressors.zlib import ZlibCompressor
from redis import ConnectionPool, Redis
from redis.connection import Connection, SSLConnection
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.request_timing import boundary

logger = logging.getLogger(__name__)

# What to do when the cache can't answer.
ON_ERROR_SKIP = "skip"  # treat as "held" - don't do the work
ON_ERROR_PROCEED = "proceed"  # treat as "acquired" - do the work anyway
CACHE_DNS_MAX_ENTRIES = 8
CACHE_DNS_TTL = 30


class CacheCoolingDownError(RedisConnectionError):
    """Represent a known cache outage without another network attempt."""


class CacheCooldownLogFilter(logging.Filter):
    """Keep the original failure visible without a traceback per cache read."""

    def filter(self, record):
        """Suppress only synthetic cooldown errors from django-redis."""
        if not record.exc_info:
            return True
        error = record.exc_info[1]
        return not isinstance(getattr(error, "__cause__", None), CacheCoolingDownError)


class _CacheDNSResolver:
    """Bound request waiting, retaining at most one OS resolver job per PID.

    A timed-out getaddrinfo cannot be cancelled. Leave its daemon thread alive
    and fail subsequent cold lookups promptly until it completes, rather than
    accumulating threads during a DNS outage.
    """

    def __init__(self):
        self._reset()

    def _reset(self):
        self._lock = threading.Lock()
        self._cache = OrderedDict()
        self._pending = None
        self._pid = os.getpid()

    def resolve(self, host, port, family, timeout):
        # Never acquire a lock inherited from another process's resolver thread.
        if self._pid != os.getpid():
            self._reset()
        key = (host, port, family)
        with self._lock:
            if self._pending and self._pending["event"].is_set():
                finished = self._pending
                self._pending = None
                if finished["error"] is None:
                    self._cache[finished["key"]] = (
                        finished["completed_at"] + CACHE_DNS_TTL,
                        finished["addresses"],
                    )
                    if len(self._cache) > CACHE_DNS_MAX_ENTRIES:
                        self._cache.popitem(last=False)
                elif finished["key"] == key:
                    message = "Cache DNS resolution failed"
                    raise RedisConnectionError(message) from finished["error"]
            cached = self._cache.get(key)
            if cached and cached[0] > time.monotonic():
                self._cache.move_to_end(key)
                return cached[1]
            self._cache.pop(key, None)
            if self._pending:
                message = "Cache DNS lookup already pending"
                raise CacheCoolingDownError(message)
            job = {
                "key": key,
                "event": threading.Event(),
                "addresses": None,
                "error": None,
                "completed_at": None,
            }
            self._pending = job

            def lookup():
                try:
                    job["addresses"] = socket.getaddrinfo(
                        host,
                        port,
                        family,
                        socket.SOCK_STREAM,
                    )
                except (OSError, UnicodeError, TypeError, ValueError) as error:
                    job["error"] = error
                finally:
                    job["completed_at"] = time.monotonic()
                    job["event"].set()

            try:
                threading.Thread(target=lookup, name="cache-dns", daemon=True).start()
            except RuntimeError as error:
                self._pending = None
                message = "Cache DNS worker unavailable"
                raise RedisConnectionError(message) from error
        if not job["event"].wait(timeout):
            message = "Cache DNS lookup timed out"
            raise RedisTimeoutError(message)
        # Consume the completed job through the same bounded cache path.
        return self.resolve(host, port, family, timeout)


_cache_dns = _CacheDNSResolver()


class CacheConnection(Connection):
    """Keep Redis's TCP options while bounding foreground DNS waiting."""

    def _connect(self):
        # Socket setup matches redis-py 7.4 Connection._connect. DNS runs off
        # the request thread; measure the caller's wait, not the daemon's time.
        with boundary("redis_connect"):
            with boundary("redis_dns_wait"):
                addresses = _cache_dns.resolve(
                    self.host,
                    self.port,
                    self.socket_type,
                    self.socket_connect_timeout
                    if self.socket_connect_timeout is not None
                    else 1,
                )
            error = None
            for family, socktype, proto, _canonname, address in addresses:
                sock = None
                try:
                    sock = socket.socket(family, socktype, proto)
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    if self.socket_keepalive:
                        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                        for option, value in self.socket_keepalive_options.items():
                            sock.setsockopt(socket.IPPROTO_TCP, option, value)
                    sock.settimeout(self.socket_connect_timeout)
                    sock.connect(address)
                    sock.settimeout(self.socket_timeout)
                except OSError as caught:
                    error = caught
                    if sock is not None:
                        with suppress(OSError):
                            sock.shutdown(socket.SHUT_RDWR)
                        sock.close()
                else:
                    return sock
            if error is not None:
                raise error
            msg = "Cache DNS lookup returned no addresses"
            raise OSError(msg)


class CacheSSLConnection(SSLConnection, CacheConnection):
    """Keep Redis's TLS wrapper and original hostname for SNI/verification."""


class CacheConnectionPool(ConnectionPool):
    """Stop repeated optional-cache waits briefly after a connection failure.

    This pool is only used by Django's cache, not the broker or rate limiter.
    The ordinary Redis error contract is preserved, including strict caches.
    DNS request waiting is bounded; a stuck OS resolver occupies one daemon.
    """

    def __init__(self, *args, **kwargs):
        """Keep a small process-local cooldown on the existing shared pool."""
        super().__init__(*args, **kwargs)
        if self.connection_class is Connection:
            self.connection_class = CacheConnection
        elif self.connection_class is SSLConnection:
            self.connection_class = CacheSSLConnection
        self._unavailable_until = 0.0

    def reset(self):
        """Clear inherited outage state after a fork."""
        super().reset()
        self._unavailable_until = 0.0

    def mark_unavailable(self):
        """Allow another normal connection attempt after two seconds."""
        now = time.monotonic()
        if now >= self._unavailable_until:
            self._unavailable_until = now + 2.0

    def get_connection(self, *args, **kwargs):
        """Fail promptly while unavailable; a later request probes recovery."""
        self._checkpid()
        if time.monotonic() < self._unavailable_until:
            message = "Cache connection temporarily unavailable"
            raise CacheCoolingDownError(message)
        try:
            return super().get_connection(*args, **kwargs)
        except (RedisConnectionError, RedisTimeoutError):
            self.mark_unavailable()
            raise


class CacheRedis(Redis):
    """Include command failures in the cache pool's short cooldown."""

    def execute_command(self, *args, **options):
        """Retain django-redis's miss/tri-state/strict error semantics."""
        try:
            return super().execute_command(*args, **options)
        except (RedisConnectionError, RedisTimeoutError):
            mark_unavailable = getattr(self.connection_pool, "mark_unavailable", None)
            if mark_unavailable is not None:
                mark_unavailable()
            raise


def cache_add(key: str, value=True, *, timeout: int | None = None) -> bool | None:
    """Try to claim a key. True if claimed, False if taken, None if unavailable.

    ``IGNORE_EXCEPTIONS`` already converts most backend failures into ``None``;
    the try/except catches what escapes it, such as pool exhaustion raised
    before a command is ever issued.
    """
    try:
        result = cache.add(key, value, timeout=timeout)
    except Exception as error:
        logger.debug("Cache unavailable acquiring %s: %s", key, error)
        return None
    if result is None:
        logger.debug("Cache unavailable acquiring %s", key)
        return None
    return bool(result)


def acquire_lock(
    key: str,
    *,
    timeout: int | None = None,
    on_error: str = ON_ERROR_SKIP,
    value=True,
) -> bool:
    """Return whether the caller holds the lock, resolving the unavailable case.

    ``on_error`` is mandatory in spirit: pass ``ON_ERROR_PROCEED`` for anything
    the user is waiting on, ``ON_ERROR_SKIP`` for maintenance.
    """
    result = cache_add(key, value, timeout=timeout)
    if result is None:
        return on_error == ON_ERROR_PROCEED
    return result


def release_lock(key: str) -> None:
    """Release a lock, tolerating an unavailable cache."""
    try:
        cache.delete(key)
    except Exception as error:  # pragma: no cover - IGNORE_EXCEPTIONS covers this
        logger.debug("Cache unavailable releasing %s: %s", key, error)


class SizedZlibCompressor(ZlibCompressor):
    """Compress only payloads large enough to repay it (History days, Discover tabs).

    Values below ``min_length`` (sessions, locks, counters) stay plain pickles.
    Reads need no migration: a value that is not zlib raises CompressorError in
    ``decompress``, which django-redis treats as "stored uncompressed".
    """

    min_length = 1024
    preset = 1
