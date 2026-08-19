"""Give Redis a memory ceiling at startup so it can't take the host down.

Redis defaults to ``maxmemory 0`` / ``noeviction``: it grows until something
kills it, and with ``--appendonly yes`` (Floppy's own shipped default) that
growth lands on disk too. Floppy caches whole processed TMDB payloads with a
24 hour TTL, so a background backfill sweeping a large library will
progressively warm the entire library into Redis. On a 2 GB host with swap
disabled that ends as an unrecoverable hang rather than an eviction
(issue #521).

Floppy can't edit the user's compose file, so it configures the running server
instead. ``CONFIG SET maxmemory`` and ``maxmemory-policy`` both take effect
immediately and survive until the server restarts, at which point this runs
again.

Two rules govern the whole module:

* **Never override a deliberate choice.** A non-zero ``maxmemory`` means the
  operator has already decided; leave both values alone.
* **Never be fatal.** Managed Redis, an ACL without ``+config``, and
  ``enable-protected-configs no`` all refuse ``CONFIG SET``. That warrants one
  actionable warning, not a failed boot.

The policy is ``volatile-lru``, not ``allkeys-lru``, because ``maxmemory`` is
server-wide and the selected server can also be the Celery broker. Kombu's
keys - the queue lists, ``_kombu.binding.*``, ``unacked*`` - carry no TTL, so
``volatile-lru`` cannot evict them, while every Django cache entry has one
(``CACHES["default"]["TIMEOUT"]`` applies whenever ``cache.set`` omits a
timeout) and Celery results have ``CELERY_RESULT_EXPIRES``. That scopes
eviction to the cache without moving anything to a separate logical database.

The corollary is that ``cache.set(..., timeout=None)`` writes a key eviction
can never reclaim, and that at ``maxmemory`` with nothing volatile left Redis
returns OOM on writes - so the budget has to stay generous relative to the
broker's steady-state size.
"""

import logging

import redis
from django.conf import settings

from app.log_safety import exception_summary
from config.runtime_profile import MIB, PROFILE

logger = logging.getLogger(__name__)

# A fraction rather than a fixed size: the cache should scale with the host, but
# Redis is one of several tenants (Floppy's own six processes, Postgres) so it
# can never have the lion's share.
MAXMEMORY_FRACTION = 0.15
MAXMEMORY_FLOOR = 96 * MIB
MAXMEMORY_CEILING = 512 * MIB

_SIZE_SUFFIXES = {
    "kb": 1024,
    "mb": 1024**2,
    "gb": 1024**3,
    "k": 1024,
    "m": 1024**2,
    "g": 1024**3,
}


def parse_size(value: str | int | None) -> int | None:
    """Return a byte count from a redis.conf-style size, or None if unparseable.

    Accepts plain byte counts and the ``256mb`` spelling users will copy out of
    the compose file, so the override reads the same either way.
    """
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip().lower().replace(" ", "")
    if not text:
        return None
    for suffix, multiplier in sorted(
        _SIZE_SUFFIXES.items(),
        key=lambda item: -len(item[0]),
    ):
        if text.endswith(suffix):
            try:
                return int(float(text[: -len(suffix)]) * multiplier)
            except ValueError:
                return None
    try:
        return int(text)
    except ValueError:
        return None


def derive_maxmemory_bytes() -> int | None:
    """Return the maxmemory to request, or None to leave Redis untouched.

    ``FLOPPY_REDIS_MAXMEMORY=0`` opts out entirely, for operators who manage
    Redis themselves and don't want Floppy touching it at all.
    """
    override = settings.FLOPPY_REDIS_MAXMEMORY
    if override is not None:
        parsed = parse_size(override)
        if parsed is None:
            logger.warning(
                "Ignoring unparseable FLOPPY_REDIS_MAXMEMORY=%r",
                override,
            )
        elif parsed <= 0:
            return None
        else:
            return parsed

    if PROFILE.memory_bytes is None:
        # Without a memory reading there's no defensible budget, and guessing
        # low would evict hot caches on a large host for no reason.
        return None

    budget = int(PROFILE.memory_bytes * MAXMEMORY_FRACTION)
    return max(MAXMEMORY_FLOOR, min(budget, MAXMEMORY_CEILING))


def _config_get(client: redis.Redis, name: str) -> str | None:
    """Return a single CONFIG GET value as text, or None if unavailable."""
    result = client.config_get(name)
    if not result:
        return None
    value = next(iter(result.values()))
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


def _record_error(
    summary: dict,
    operation: str,
    error: Exception,
    next_action: str,
) -> str:
    """Add and return an actionable error that does not expose Redis details."""
    message = f"{operation} failed ({exception_summary(error)}). {next_action}"
    summary["errors"].append(message)
    return message


def tune_redis(*, dry_run: bool = False) -> dict:
    """Apply a memory ceiling and eviction policy to Redis if it has none.

    Returns a summary of what was applied, skipped, or failed - the management
    command renders it, and the tests assert on it.
    """
    summary: dict = {"applied": {}, "skipped": {}, "errors": []}

    redis_url = getattr(settings, "REDIS_ADMIN_URL", "") or ""
    if not redis_url.startswith(("redis://", "rediss://")):
        summary["skipped"]["reason"] = "not_a_redis_url"
        return summary

    budget = derive_maxmemory_bytes()
    if budget is None:
        summary["skipped"]["reason"] = "no_budget"
        return summary

    try:
        client = redis.Redis.from_url(redis_url)
        current_maxmemory = parse_size(_config_get(client, "maxmemory"))
    except Exception as error:
        # Redis being unreachable is not this function's problem to solve; the
        # startup log reports it, and the next restart tries again.
        message = _record_error(
            summary,
            "Redis administration maxmemory read",
            error,
            "Check REDIS_ADMIN_URL and server availability.",
        )
        logger.info("Skipping Redis memory tuning. %s", message)
        return summary

    if current_maxmemory:
        summary["skipped"]["maxmemory"] = current_maxmemory
        logger.info(
            "Redis maxmemory already set to %s bytes by the operator, leaving it alone",
            current_maxmemory,
        )
        return summary

    try:
        current_policy = _config_get(client, "maxmemory-policy")
    except Exception as error:
        current_policy = None
        message = _record_error(
            summary,
            "Redis maxmemory-policy read",
            error,
            "Grant CONFIG access, configure Redis directly, or set "
            "FLOPPY_REDIS_MAXMEMORY=0.",
        )
        logger.warning("%s", message)

    if dry_run:
        summary["applied"]["maxmemory"] = budget
        if current_policy in (None, "noeviction"):
            summary["applied"]["maxmemory-policy"] = "volatile-lru"
        else:
            summary["skipped"]["maxmemory-policy"] = current_policy
        return summary

    try:
        client.config_set("maxmemory", budget)
        summary["applied"]["maxmemory"] = budget
    except Exception as error:
        message = _record_error(
            summary,
            "Redis maxmemory update",
            error,
            "Grant CONFIG access, configure Redis directly, or set "
            "FLOPPY_REDIS_MAXMEMORY=0.",
        )
        logger.warning(
            "%s Redis will grow without "
            "bound and can exhaust the host. Add this to your redis service in "
            'docker-compose.yml: command: redis-server --appendonly yes --save "" '
            "--maxmemory %dmb --maxmemory-policy volatile-lru",
            message,
            budget // MIB,
        )
        return summary

    # Only replace the default. A user who chose volatile-ttl or allkeys-lfu
    # made a decision worth keeping.
    if current_policy in (None, "noeviction"):
        try:
            client.config_set("maxmemory-policy", "volatile-lru")
            summary["applied"]["maxmemory-policy"] = "volatile-lru"
        except Exception as error:
            message = _record_error(
                summary,
                "Redis maxmemory-policy update",
                error,
                "Grant CONFIG access, configure Redis directly, or set "
                "FLOPPY_REDIS_MAXMEMORY=0.",
            )
            logger.warning(
                "Set Redis maxmemory, but the policy update failed. %s With "
                "noeviction Redis will reject writes once full rather than evict",
                message,
            )
    else:
        summary["skipped"]["maxmemory-policy"] = current_policy

    _tune_persistence(client, summary)

    if summary["applied"]:
        logger.info(
            "Tuned Redis for %s: %s",
            PROFILE.describe(),
            summary["applied"],
        )
    return summary


def _tune_persistence(client: redis.Redis, summary: dict) -> None:
    """Relax appendfsync=always, which fsyncs on every single write.

    Floppy's cache is regenerable, so paying a disk sync per write buys nothing
    and shows up as the I/O load reported in #521. Only ``always`` is changed:
    ``everysec`` is already the sensible default and ``no`` is a deliberate
    choice.
    """
    try:
        if _config_get(client, "appendonly") != "yes":
            return
        if _config_get(client, "appendfsync") != "always":
            return
        client.config_set("appendfsync", "everysec")
    except Exception as error:
        message = _record_error(
            summary,
            "Redis persistence update",
            error,
            "Configure Redis persistence directly or set FLOPPY_REDIS_MAXMEMORY=0.",
        )
        logger.warning("%s", message)
        return
    summary["applied"]["appendfsync"] = "everysec"
    logger.info(
        "Relaxed Redis appendfsync from always to everysec; Floppy's cache is "
        "regenerable and does not need a disk sync per write",
    )
