"""Say why Redis could not be reached, in words an operator can act on.

A failed Redis connection reaches Floppy wrapped several times over. Kombu's
``OperationalError`` wraps redis-py's ``ConnectionError``, which in turn wraps the
socket error that actually happened. Each caller used to report the outermost
layer, so an unresolvable hostname surfaced as "check the worker" or "check that
the Redis service is running". Neither points at the real cause (#1166, #1229,
#1263).

The common real cause is a stack whose containers do not share a user-defined
Docker network. Docker then cannot resolve the service name ``redis``. This
module finds the underlying failure and describes it the same way in the startup
log, in ``floppy_preflight`` and in the message an import shows.
"""

from __future__ import annotations

import socket
from urllib.parse import urlsplit

import redis

DNS = "dns"
REFUSED = "refused"
TIMEOUT = "timeout"
AUTH = "auth"
OTHER = "other"

# The kinds that mean "Floppy cannot get a connection at all", as opposed to a
# server that answered and said no.
UNREACHABLE = frozenset({DNS, REFUSED, TIMEOUT})

GUIDE_SECTION = "Floppy can't reach Redis"
GUIDE_URL = (
    "https://github.com/dannyvfilms/Floppy/blob/latest/docs/deployment.md"
    "#floppy-cant-reach-redis"
)

# Celery also accepts brokers such as RabbitMQ. A failure there is not a Redis
# problem, so it keeps the caller's own wording.
REDIS_SCHEMES = ("redis://", "rediss://", "unix://")

# Kombu re-raises with only the message text, so the message has to be read too.
# musl (Alpine, the Floppy image) and glibc word resolver failures differently,
# and redis-py prefixes the resolver's errno.
_DNS_MARKERS = (
    "name does not resolve",
    "name or service not known",
    "temporary failure in name resolution",
    "nodename nor servname",
    "no address associated with hostname",
    "error -2 connecting",
    "error -3 connecting",
    "error -5 connecting",
)
_REFUSED_MARKERS = ("connection refused",)
_TIMEOUT_MARKERS = ("timed out", "timeout connecting")


def _chain(error: BaseException):
    """Yield the error and everything it was raised from or while handling."""
    seen: set[int] = set()
    pending: list[BaseException] = [error]
    while pending:
        current = pending.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        pending.extend(
            linked
            for linked in (current.__cause__, current.__context__)
            if linked is not None
        )


def classify_redis_error(error: BaseException) -> str:
    """Return which way a Redis connection failed.

    One of ``dns``, ``refused``, ``timeout``, ``auth`` or ``other``.
    """
    chain = list(_chain(error))

    # Types first: they are exact where the text is only a good guess.
    for current in chain:
        if isinstance(current, redis.AuthenticationError):
            return AUTH
        if isinstance(current, socket.gaierror):
            return DNS
        if isinstance(current, ConnectionRefusedError):
            return REFUSED
        if isinstance(current, (TimeoutError, redis.TimeoutError)):
            return TIMEOUT

    for current in chain:
        text = str(current).lower()
        if any(marker in text for marker in _DNS_MARKERS):
            return DNS
        if any(marker in text for marker in _REFUSED_MARKERS):
            return REFUSED
        if any(marker in text for marker in _TIMEOUT_MARKERS):
            return TIMEOUT
    return OTHER


def _endpoint(url: str | None) -> tuple[str, str]:
    """Return (host:port, host) for a Redis URL, with credentials dropped.

    Only the host and port are read, so userinfo never reaches the result. The
    original URL is parsed rather than ``safe_url``'s output, which drops the
    brackets around an IPv6 host and makes the port unparseable.
    """
    parts = urlsplit(str(url or ""))
    host = parts.hostname or ""
    if not host:
        # unix:// sockets have a path and no host.
        return parts.path, parts.path
    try:
        port = parts.port
    except ValueError:
        port = None
    shown = f"[{host}]" if ":" in host else host
    return (f"{shown}:{port}" if port else shown), host


def _in_container() -> bool:
    # Imported here because preflight imports redis_tuning, which imports this.
    from app.preflight import in_container

    return in_container()


def explain_redis_error(error: BaseException, url: str | None) -> tuple[str, str]:
    """Return (cause, fix) for a failed connection to ``url``.

    Returns empty strings when the failure is not one this module can explain
    better than the error itself, so a caller keeps its own wording.
    """
    kind = classify_redis_error(error)
    endpoint, host = _endpoint(url)
    container = _in_container()

    if kind == DNS:
        cause = f'the hostname "{host}" does not resolve'
        if container:
            fix = (
                "put Floppy and Redis on the same user-defined Docker network (a "
                "networks: entry on every service, and no network_mode: bridge), "
                "or set REDIS_URL to an address this container can reach. See "
                f'"{GUIDE_SECTION}" in the deployment guide: {GUIDE_URL}'
            )
        else:
            fix = "set REDIS_URL to a hostname this machine can resolve"
        return cause, fix
    if kind == REFUSED:
        cause = f"{endpoint} refused the connection"
        fix = (
            "check that the Redis container is running and that REDIS_URL uses its port"
            if container
            else "check that Redis is running and listening on the port in REDIS_URL"
        )
        return cause, fix
    if kind == TIMEOUT:
        cause = f"{endpoint} did not answer in time"
        fix = "check that Redis is running and that no firewall blocks its port"
        return cause, fix
    return "", ""


def unreachable_detail(error: BaseException, url: str | None) -> str | None:
    """Return one sentence naming why Redis is unreachable, or None.

    None means the error is not a connection failure, and the caller should keep
    its generic message.
    """
    if not str(url or "").startswith(REDIS_SCHEMES):
        return None
    if classify_redis_error(error) not in UNREACHABLE:
        return None
    cause, _fix = explain_redis_error(error, url)
    endpoint, _host = _endpoint(url)
    return (
        f"Floppy cannot reach Redis at {endpoint}: {cause}. "
        f'See "{GUIDE_SECTION}" in the deployment guide.'
    )


def queue_failure_message(
    error: BaseException,
    summary: str,
    hint: str,
    url: str | None,
) -> str:
    """Return the message for a task that could not be queued.

    ``summary`` says what failed ("The import could not be queued."). The Redis
    explanation replaces ``hint`` when the broker was unreachable, because
    "check the worker" sends the operator to the wrong place.
    """
    detail = unreachable_detail(error, url)
    return f"{summary} {detail or hint}".strip()
