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

from django.core.cache import cache

logger = logging.getLogger(__name__)

# What to do when the cache can't answer.
ON_ERROR_SKIP = "skip"  # treat as "held" - don't do the work
ON_ERROR_PROCEED = "proceed"  # treat as "acquired" - do the work anyway


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
