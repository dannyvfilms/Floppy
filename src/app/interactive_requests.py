"""Shared helpers for marking active interactive browser requests."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.core.cache import cache

if TYPE_CHECKING:
    from django.http import HttpRequest

logger = logging.getLogger(__name__)

INTERACTIVE_REQUEST_CACHE_KEY = "interactive_request_active"
INTERACTIVE_REQUEST_TTL_SECONDS = 30
_INTERACTIVE_REQUEST_EXCLUDED_PREFIXES = (
    "/api/",
    "/media/",
    "/static/",
    # Django Debug Toolbar mounts at /__debug__/ and its history sidebar polls
    # continuously in dev — that must not count as user activity or background
    # backfills defer forever, one item per cycle.
    "/__debug__/",
)
_INTERACTIVE_REQUEST_EXCLUDED_PATHS = {"/serviceworker.js"}


def should_mark_interactive_request(request: HttpRequest) -> bool:
    """Return whether this request should suppress best-effort maintenance work."""
    if request.method not in {"GET", "HEAD"}:
        return False

    path = request.path_info or ""
    if path in _INTERACTIVE_REQUEST_EXCLUDED_PATHS or path.startswith(
        _INTERACTIVE_REQUEST_EXCLUDED_PREFIXES,
    ):
        return False

    is_htmx = request.headers.get("HX-Request") == "true"
    if is_htmx:
        return True

    accept = request.headers.get("Accept", "")
    return not accept or "text/html" in accept or "*/*" in accept


def mark_interactive_request() -> None:
    """Refresh the shared interactive-request marker."""
    cache.set(
        INTERACTIVE_REQUEST_CACHE_KEY,
        True,
        timeout=INTERACTIVE_REQUEST_TTL_SECONDS,
    )


def interactive_request_active() -> bool:
    """Return whether a recent interactive browser request is active.

    Falls back to False when the cache is unreachable. Guarding here rather than
    at the ~30 call sites matters because ``CooperativeRun.iter()`` calls this
    once per item from *outside* the per-item try/except in the backfill tasks,
    so a raise would abandon the whole batch (#521).

    False is the right answer despite looking like the incautious one: True
    would defer every background task for as long as the outage lasted, so
    maintenance would never converge, and yielding to a user who may not even
    be there is a courtesy rather than a correctness requirement.
    """
    try:
        return bool(cache.get(INTERACTIVE_REQUEST_CACHE_KEY))
    except Exception as error:
        logger.debug("Cache unavailable reading interactive marker: %s", error)
        return False
