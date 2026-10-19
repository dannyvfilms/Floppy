"""Horizontal (16:9) backdrop resolution shared by the web UI and the API.

Item.image holds a portrait poster (TMDB w500); backdrops are never stored on
the model, only fetched from the provider and cached in Redis for 7 days.
TMDB fetching and its cache contract live here; IGDB still delegates to lists.

``resolve_backdrop`` returns ``None`` when no backdrop exists, leaving the
choice of fallback to the caller: the web UI falls back to the poster so a
card always renders, while the API reports ``null`` so clients can pick their
own artwork.

Request paths and the interactive worker never fetch: they read Redis and
hand misses to ``schedule_backdrop_warm``, which fetches them on a background
worker so a later read finds them. TMDB detail fetches also record the
backdrop their response already carried (``remember_tmdb_backdrop``).
"""

import logging

from django.conf import settings
from django.core.cache import cache

from app.models import MediaTypes, Sources

logger = logging.getLogger(__name__)

# How long a queued warm suppresses another request for the same item.
BACKDROP_WARM_GUARD_SECONDS = 60 * 10
TMDB_BACKDROP_BASE_URL = "https://image.tmdb.org/t/p/w1280"
TMDB_BACKDROP_TTL = 60 * 60 * 24 * 7

# Episodes and seasons share their show's media_id, and TMDB files anime under
# /tv, so all three resolve against the show-level backdrop.
_SHOW_LEVEL_TYPES = (
    MediaTypes.EPISODE.value,
    MediaTypes.SEASON.value,
    MediaTypes.ANIME.value,
)
_TVDB_TYPES = (MediaTypes.TV.value, *_SHOW_LEVEL_TYPES)


def _read(item, key):
    """Read a field from either a serialized dict or a model instance."""
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _identity(item):
    """Return (source, media_type, media_id) or None when incomplete."""
    if not item:
        return None
    source = _read(item, "source")
    media_type = _read(item, "media_type")
    media_id = _read(item, "media_id")
    if not source or not media_type or not media_id:
        return None
    return source, media_type, media_id


def _tvdb_tmdb_id(item):
    """Return the TMDB cross-reference the TVDB provider stores, if any."""
    return (_read(item, "provider_external_ids") or {}).get("tmdb_id")


def _usable(backdrop):
    """Treat the placeholder image as no backdrop at all."""
    if backdrop and backdrop != settings.IMG_NONE:
        return backdrop
    return None


def _tmdb_backdrop_key(media_type, media_id) -> str:
    """Shared key for TMDB detail responses, list covers, and backdrop reads."""
    return f"tmdb_backdrop_{media_type}_{media_id}"


def get_tmdb_backdrop(media_type, media_id):
    """Fetch TMDB artwork, caching success for seven days and absence for one.

    Returns the placeholder on provider failure or missing artwork. Presentation
    callers choose their own fallback after filtering that placeholder.
    """
    cache_key = _tmdb_backdrop_key(media_type, media_id)
    cached_backdrop = cache.get(cache_key)
    if cached_backdrop is not None:
        return cached_backdrop

    try:
        from app.providers import services, tmdb

        if media_type == MediaTypes.MOVIE.value:
            url = f"{tmdb.base_url}/movie/{media_id}"
        else:
            url = f"{tmdb.base_url}/tv/{media_id}"

        params = dict(tmdb.base_params())
        response = services.api_request(
            Sources.TMDB.value,
            "GET",
            url,
            params=params,
        )

        backdrop_path = response.get("backdrop_path")
        if backdrop_path:
            backdrop_url = f"{TMDB_BACKDROP_BASE_URL}{backdrop_path}"
            # Cache for 7 days (same as TMDB metadata cache)
            cache.set(cache_key, backdrop_url, TMDB_BACKDROP_TTL)
            return backdrop_url
    except Exception:  # noqa: S110  # deliberate best-effort; failure is non-fatal here
        pass

    # Cache the absence of backdrop to avoid repeated failed calls
    cache.set(cache_key, settings.IMG_NONE, 60 * 60 * 24)
    return settings.IMG_NONE


def _backdrop_cache_key(item) -> str | None:
    """Return the Redis key holding an item's backdrop, or None if it has none.

    This is also the eligibility rule: an item without a key can never have a
    backdrop, so it is never fetched or warmed.
    """
    identity = _identity(item)
    if identity is None:
        return None
    source, media_type, media_id = identity

    if source == Sources.TMDB.value:
        backdrop_media_type = (
            MediaTypes.TV.value if media_type in _SHOW_LEVEL_TYPES else media_type
        )
        if backdrop_media_type in (MediaTypes.MOVIE.value, MediaTypes.TV.value):
            return _tmdb_backdrop_key(backdrop_media_type, media_id)

    if source == Sources.TVDB.value and media_type in _TVDB_TYPES:
        tmdb_id = _tvdb_tmdb_id(item)
        if tmdb_id:
            return _tmdb_backdrop_key(MediaTypes.TV.value, tmdb_id)

    if source == Sources.IGDB.value and media_type == MediaTypes.GAME.value:
        return f"igdb_backdrop_{media_id}"

    return None


def cached_backdrop(item) -> str | None:
    """Return an already-cached backdrop without triggering provider lookups."""
    key = _backdrop_cache_key(item)
    return _usable(cache.get(key)) if key else None


def remember_tmdb_backdrop(media_type, media_id, backdrop_path) -> None:
    """Cache the backdrop a TMDB detail response already carried.

    Movie and TV detail responses include ``backdrop_path``, so recording it
    here spares the separate backdrop request a later reader would need.
    """
    if not backdrop_path or not media_id:
        return
    cache.set(
        _tmdb_backdrop_key(media_type, media_id),
        f"{TMDB_BACKDROP_BASE_URL}{backdrop_path}",
        TMDB_BACKDROP_TTL,
    )


def cached_backdrop_or_warm(item) -> str | None:
    """Return a cached backdrop; on a miss, queue a background fetch.

    For request paths that must not wait on a provider: the response reports
    no backdrop this time and a later request finds it in Redis.
    """
    backdrop = cached_backdrop(item)
    if backdrop is None:
        schedule_backdrop_warm([item])
    return backdrop


def resolve_backdrop(item, *, allow_network=True) -> str | None:
    """Return a horizontal backdrop URL for an item, or None if there is none.

    With ``allow_network=False`` only the Redis cache is consulted, so callers
    on a hot path never block on a provider request.
    """
    cached = cached_backdrop(item)
    if cached:
        return cached

    identity = _identity(item)
    if identity is None or not allow_network:
        return None
    source, media_type, media_id = identity

    if source == Sources.TMDB.value and media_type in _SHOW_LEVEL_TYPES:
        return _fetch(get_tmdb_backdrop, MediaTypes.TV.value, media_id)

    if source == Sources.TMDB.value and media_type in (
        MediaTypes.MOVIE.value,
        MediaTypes.TV.value,
    ):
        return _fetch(get_tmdb_backdrop, media_type, media_id)

    if source == Sources.TVDB.value and media_type in _TVDB_TYPES:
        tmdb_id = _tvdb_tmdb_id(item)
        if tmdb_id:
            return _fetch(get_tmdb_backdrop, MediaTypes.TV.value, tmdb_id)

    if source == Sources.IGDB.value and media_type == MediaTypes.GAME.value:
        try:
            from lists.models import CustomList
        except Exception:
            return None
        return _fetch(CustomList()._get_igdb_backdrop, media_id)

    return None


def _fetch(getter, *args) -> str | None:
    """Call a provider backdrop getter; artwork is never worth raising over."""
    try:
        return _usable(getter(*args))
    except Exception:  # deliberate best-effort; failure is non-fatal here
        return None


def warm_identity(item) -> dict | None:
    """Return a JSON-safe identity to warm, or None if no backdrop can exist."""
    if _backdrop_cache_key(item) is None:
        return None
    source, media_type, media_id = _identity(item)
    identity = {"source": source, "media_type": media_type, "media_id": str(media_id)}
    if source == Sources.TVDB.value:
        identity["provider_external_ids"] = {"tmdb_id": _tvdb_tmdb_id(item)}
    return identity


def _warm_guard_key(identity: dict) -> str:
    return (
        f"backdrop_warm:{identity['source']}:{identity['media_type']}:"
        f"{identity['media_id']}"
    )


def schedule_backdrop_warm(items) -> int:
    """Queue one background fetch for the backdrops these items are missing.

    Each item is guarded for ``BACKDROP_WARM_GUARD_SECONDS`` so repeated page
    loads do not queue the same fetch again. Returns the number queued.
    """
    identities = []
    guard_keys = []
    for item in items:
        identity = warm_identity(item)
        if identity is None:
            continue
        if cache.get(_backdrop_cache_key(item)) is not None:
            # Already known, including a cached "no backdrop" answer.
            continue
        key = _warm_guard_key(identity)
        if key in guard_keys or not cache.add(key, True, BACKDROP_WARM_GUARD_SECONDS):
            continue
        guard_keys.append(key)
        identities.append(identity)

    if not identities:
        return 0

    try:
        from app.tasks_backdrops import warm_backdrops_task

        warm_backdrops_task.apply_async(
            args=[identities],
            priority=getattr(settings, "CELERY_TASK_PRIORITY_FOLLOWUP", 3),
        )
    except Exception:  # pragma: no cover - Celery not available
        cache.delete_many(guard_keys)
        logger.debug("Could not schedule backdrop warm", exc_info=True)
        return 0
    return len(identities)
