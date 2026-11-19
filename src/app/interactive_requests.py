"""Who counts as a person using Floppy right now, so maintenance can wait.

Background tasks check :func:`interactive_request_active` and stand back while
it is true (see ``app.task_cooperation``). The mark lasts
:data:`INTERACTIVE_REQUEST_TTL_SECONDS` after the last request that set it, so
anything that requests on a timer would hold it forever and starve maintenance.

Who sets it:

* A browser page or HTMX swap (:func:`marks_page_request`), checked before
  the view runs so the first page after idle is protected.
* A read from the web pages' React islands or the Floppy app
  (:func:`marks_api_request`), checked after the view because only then is the
  credential known. ``/api/`` is no longer excluded wholesale: since the React
  and Expo migration, people browse through it. It counts only for a session
  cookie (the web pages, Expo web, and the app's password sign-in) or a token
  issued to the first-party app's device-flow client.

Who never sets it: other tokens and legacy ``User.token`` (scrobblers, FlexGet,
Nuvio, media-server plugins), ListenBrainz-compatible ``/apis/`` clients,
writes, health checks, static and media files, and the timer polls in
:data:`_POLL_URL_NAMES`. A token pasted into the app cannot be told apart from
a third-party one, so it does not count either.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.cache import cache

from integrations.oauth_scope_info import FIRST_PARTY_CLIENT_ID

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
_INTERACTIVE_REQUEST_EXCLUDED_PATHS = {
    "/health/",
    "/health/full/",
    "/ping/",
    "/serviceworker.js",
}
# ListenBrainz-compatible scrobblers. Not covered by "/api/" above.
_SCROBBLER_PREFIX = "/apis/"
# Requests a page or the app repeats on a timer while it waits for background
# work or keeps a card current. Someone may have walked away from the screen,
# and several wait for the very work the mark would defer.
_POLL_URL_NAMES = frozenset(
    {
        "api_discover_status",
        "api_home_artwork",
        "api_library_bulk_plays_status",
        "api_playback_home_cards",
        "api_playback_now_playing",
        "bulk_show_plays_status",
        "episode_history_poll",
        "home_rows_artwork_refresh",
        "import_data_activity",
        "prefetch_artist_covers",
        "prefetch_artist_relation_images",
        "trakt_device_poll",
        "trakt_lists_device_poll",
        "trakt_series_graph_fragment",
    },
)
# The mark lasts 30 seconds, so renewing it every 10 keeps it set without a
# cache write on every request. Per process; each worker renews its own.
_MARK_RENEW_SECONDS = 10
_last_marked_at: float | None = None


def should_mark_interactive_request(request: HttpRequest) -> bool:
    """Return whether this is a browser page load or HTMX swap.

    Also decides who gets the friendly database-busy page, so it stays a test of
    request shape; :func:`marks_page_request` adds the marking exclusions.
    """
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


def _is_poll(request: HttpRequest) -> bool:
    match = getattr(request, "resolver_match", None)
    return bool(match and match.url_name in _POLL_URL_NAMES)


def marks_page_request(request: HttpRequest) -> bool:
    """Return whether a page or HTMX request, about to run its view, is a person's."""
    return (
        should_mark_interactive_request(request)
        and not (request.path_info or "").startswith(_SCROBBLER_PREFIX)
        and not _is_poll(request)
    )


def marks_api_request(request: HttpRequest) -> bool:
    """Return whether a finished API read came from the web pages or the Floppy app.

    Reads only what DRF already put on the request, so it adds no query. A
    view that never authenticated (not DRF, or public) has no ``auth`` set.
    """
    if request.method not in {"GET", "HEAD"}:
        return False
    if not (request.path_info or "").startswith("/api/") or _is_poll(request):
        return False
    if "auth" not in request.__dict__:
        return False
    user = request.__dict__.get("user")
    if not getattr(user, "is_authenticated", False):
        return False
    token = request.auth
    if token is not None:
        return getattr(token, "client_identifier", "") == FIRST_PARTY_CLIENT_ID
    # No token object: a session, or a legacy User.token sent in a header.
    # The cookie must have come with the request, so auto-login does not make
    # a credential-less client count.
    return (
        settings.SESSION_COOKIE_NAME in request.COOKIES
        and "Authorization" not in request.headers
        and "X-API-Key" not in request.headers
    )


def refresh_interactive_mark() -> None:
    """Set the mark unless this process set it within the last few seconds."""
    global _last_marked_at  # noqa: PLW0603
    now = time.monotonic()
    if _last_marked_at is not None and now - _last_marked_at < _MARK_RENEW_SECONDS:
        return
    mark_interactive_request()
    _last_marked_at = now


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
