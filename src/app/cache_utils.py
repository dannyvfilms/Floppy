import logging
import time

import redis
from django.conf import settings
from django.core.cache import cache
from django_redis import get_redis_connection

logger = logging.getLogger(__name__)


# v19: payload changed from a pickled entry list to a compact ordered-ids
# structure hydrated per page (see media_list_views time_left handling).
TIME_LEFT_CACHE_PREFIX = "time_left_sorted_v19"
_REGISTRY_TEMPLATE = f"{TIME_LEFT_CACHE_PREFIX}_registry_{{user_id}}"

# v2: payload changed from a pickled full MediaListEntry list to a compact
# {media_pk, model, item_pk} order hydrated per page (issue #865). Bumped so a
# rolling deploy can't hand the new code an old pickled entry (or vice versa).
MEDIA_LIST_CACHE_PREFIX = "media_list_v2"
MEDIA_LIST_CACHE_TTL = 60  # seconds — enough for "navigate away and back" use case
# v2: filter payloads include per-tag media-list usage counts.
MEDIA_LIST_FILTER_CACHE_PREFIX = "media_list_filters_v2"
MEDIA_LIST_FILTER_CACHE_TTL = 300
_MEDIA_LIST_REGISTRY_TEMPLATE = f"{MEDIA_LIST_CACHE_PREFIX}_registry_{{user_id}}"


def build_time_left_cache_key(
    user_id: int,
    media_type: str,
    status_filter: str,
    search_query: str,
    direction: str,
    rating_filter: str,
    progress_filter: str = "",
    collection_filter: str = "",
    genre_filter: str = "",
    year_filter: str = "",
    release_filter: str = "",
    source_filter: str = "",
    language_filter: str = "",
    country_filter: str = "",
    platform_filter: str = "",
    platform_mode: str = "",
    origin_filter: str = "",
    tag_filter: str = "",
    tag_mode: str = "",
    provider_filter: str = "",
    watch_provider_region: str = "",
    media_status_filter: str = "",
    pinned_providers: str = "",
    completed_date_from: str = "",
    completed_date_to: str = "",
    range_filters: str = "",
) -> str:
    """Create the cache key used for time-left sorted TV lists."""
    normalized_status = status_filter or ""
    normalized_query = search_query or ""
    normalized_direction = direction or ""
    normalized_rating = rating_filter or ""
    normalized_progress = progress_filter or ""
    normalized_collection = collection_filter or ""
    normalized_genre = genre_filter or ""
    normalized_year = year_filter or ""
    normalized_release = release_filter or ""
    normalized_source = source_filter or ""
    normalized_language = language_filter or ""
    normalized_country = country_filter or ""
    normalized_platform = platform_filter or ""
    normalized_platform_mode = platform_mode or ""
    normalized_origin = origin_filter or ""
    normalized_tag = tag_filter or ""
    normalized_tag_mode = tag_mode or ""
    normalized_provider = provider_filter or ""
    normalized_region = watch_provider_region or ""
    normalized_media_status = media_status_filter or ""
    normalized_pinned_providers = pinned_providers or ""
    normalized_completed_date_from = completed_date_from or ""
    normalized_completed_date_to = completed_date_to or ""
    return (
        f"{TIME_LEFT_CACHE_PREFIX}_{user_id}_{media_type}_{normalized_status}_"
        f"{normalized_query}_{normalized_direction}_{normalized_rating}_{normalized_progress}_{normalized_collection}_"
        f"{normalized_genre}_{normalized_year}_{normalized_release}_{normalized_source}_"
        f"{normalized_language}_{normalized_country}_{normalized_platform}_{normalized_platform_mode}_{normalized_origin}_"
        f"{normalized_tag}_{normalized_tag_mode}_{normalized_provider}_{normalized_region}_"
        f"{normalized_media_status}_{normalized_pinned_providers}_"
        f"{normalized_completed_date_from}_{normalized_completed_date_to}"
        f"_{range_filters or ''}"
    )


def _registry_client():
    """Return a raw Redis client, or None when the cache isn't Redis-backed."""
    try:
        return get_redis_connection("default")
    except Exception as error:  # registries are best-effort
        logger.debug("No raw Redis connection for cache registry: %s", error)
        return None


def _legacy_registry_add(registry_key: str, cache_key: str) -> None:
    """Read-modify-write fallback for a cache that is not a raw Redis."""
    keys = set(cache.get(registry_key) or ())
    if cache_key not in keys:
        keys.add(cache_key)
        cache.set(registry_key, list(keys), getattr(settings, "CACHE_TIMEOUT", None))


def _registry_add(registry_key: str, cache_key: str) -> None:
    """Add ``cache_key`` to the registry with one atomic SADD round trip.

    The registry is a Redis set, so concurrent misses cannot overwrite each
    other the way ``get`` + ``set`` of a whole list did. A registry written by
    an older release is a pickled string; it is migrated on first touch.
    """
    client = _registry_client()
    if client is None:
        _legacy_registry_add(registry_key, cache_key)
        return
    raw_key = cache.make_key(registry_key)
    timeout = getattr(settings, "CACHE_TIMEOUT", None)
    try:
        try:
            pipe = client.pipeline()
            pipe.sadd(raw_key, cache_key)
            if timeout:
                pipe.expire(raw_key, timeout)
            pipe.execute()
        except redis.ResponseError:  # WRONGTYPE: a pickled list from an old release
            legacy = cache.get(registry_key)
            members = [*legacy, cache_key] if isinstance(legacy, list) else [cache_key]
            client.delete(raw_key)
            client.sadd(raw_key, *members)
    except redis.RedisError as error:
        logger.debug("Cache registry %s unavailable: %s", registry_key, error)


# Atomically read and drop a set registry. A non-set value is an older release's
# pickled list: leave it untouched (nil) so the caller can read it normally.
_TAKE_REGISTRY_LUA = """
if redis.call('TYPE', KEYS[1]).ok == 'set' then
    local members = redis.call('SMEMBERS', KEYS[1])
    redis.call('DEL', KEYS[1])
    return members
end
return false
"""


def _registry_take(registry_key: str) -> list[str]:
    """Return and remove every key in the registry, atomically.

    Read and delete are one script, so a key registered while we are
    invalidating lands in the next registry instead of being erased unseen.
    """
    client = _registry_client()
    if client is not None:
        try:
            members = client.eval(_TAKE_REGISTRY_LUA, 1, cache.make_key(registry_key))
        except redis.RedisError as error:
            logger.debug("Cache registry %s unavailable: %s", registry_key, error)
            return []
        if members is not False and members is not None:
            return [m.decode() if isinstance(m, bytes) else m for m in members]
    keys = list(cache.get(registry_key) or ())
    cache.delete(registry_key)
    return keys


def _registry_key_for_user(user_id: int) -> str:
    return _REGISTRY_TEMPLATE.format(user_id=user_id)


def register_time_left_cache_key(user_id: int, cache_key: str) -> None:
    """Keep track of active cache keys for a user so we can invalidate them later."""
    _registry_add(_registry_key_for_user(user_id), cache_key)


def clear_time_left_cache_for_user(user_id: int) -> None:
    """Invalidate all cached time-left lists for a user."""
    keys = _registry_take(_registry_key_for_user(user_id))

    if not keys:
        return

    cache.delete_many(keys)

    logger.debug(
        "Cleared %s time_left cache entries for user %s",
        len(keys),
        user_id,
    )


def build_media_list_cache_key(
    user_id: int,
    media_type: str,
    sort_filter: str,
    direction: str,
    status_filter: str,
    search_query: str,
    rating_filter: str,
    progress_filter: str = "",
    collection_filter: str = "",
    author_filter: str = "",
    format_filter: str = "",
    genre_filter: str = "",
    implied_genre_filter: str = "",
    year_filter: str = "",
    release_filter: str = "",
    source_filter: str = "",
    language_filter: str = "",
    country_filter: str = "",
    platform_filter: str = "",
    platform_mode: str = "",
    origin_filter: str = "",
    tag_filter: str = "",
    tag_mode: str = "",
    cache_variant: str = "",
    provider_filter: str = "",
    watch_provider_region: str = "",
    media_status_filter: str = "",
    pinned_providers: str = "",
    completed_date_from: str = "",
    completed_date_to: str = "",
    range_filters: str = "",
) -> str:
    """Create the cache key for a fully-processed media list page."""
    parts = [
        MEDIA_LIST_CACHE_PREFIX,
        str(user_id),
        media_type,
        sort_filter or "",
        direction or "",
        status_filter or "",
        search_query or "",
        rating_filter or "",
        progress_filter or "",
        collection_filter or "",
        author_filter or "",
        format_filter or "",
        genre_filter or "",
        implied_genre_filter or "",
        year_filter or "",
        release_filter or "",
        source_filter or "",
        language_filter or "",
        country_filter or "",
        platform_filter or "",
        platform_mode or "",
        origin_filter or "",
        tag_filter or "",
        tag_mode or "",
        cache_variant or "",
        provider_filter or "",
        watch_provider_region or "",
        media_status_filter or "",
        pinned_providers or "",
        completed_date_from or "",
        completed_date_to or "",
        range_filters or "",
    ]
    return "_".join(parts)


def build_media_list_filter_cache_key(
    user_id: int,
    media_type: str,
    status_filter: str,
    search_query: str,
    progress_filter: str = "",
    genre_filter: str = "",
    implied_genre_filter: str = "",
    year_filter: str = "",
    release_filter: str = "",
    source_filter: str = "",
    language_filter: str = "",
    country_filter: str = "",
    platform_filter: str = "",
    platform_mode: str = "",
    author_filter: str = "",
    format_filter: str = "",
    tag_filter: str = "",
    tag_mode: str = "",
    cache_variant: str = "",
    provider_filter: str = "",
    watch_provider_region: str = "",
    media_status_filter: str = "",
    pinned_providers: str = "",
    completed_date_from: str = "",
    completed_date_to: str = "",
) -> str:
    """Create the cache key for media-list filter summary data."""
    parts = [
        MEDIA_LIST_FILTER_CACHE_PREFIX,
        str(user_id),
        media_type,
        status_filter or "",
        search_query or "",
        progress_filter or "",
        genre_filter or "",
        implied_genre_filter or "",
        year_filter or "",
        release_filter or "",
        source_filter or "",
        language_filter or "",
        country_filter or "",
        platform_filter or "",
        platform_mode or "",
        author_filter or "",
        format_filter or "",
        tag_filter or "",
        tag_mode or "",
        cache_variant or "",
        provider_filter or "",
        watch_provider_region or "",
        media_status_filter or "",
        pinned_providers or "",
        completed_date_from or "",
        completed_date_to or "",
    ]
    return "_".join(parts)


HOME_ROW_CACHE_PREFIX = "home_row_v2"
HOME_ROW_CACHE_TTL = 60  # seconds — matches the media-list cache horizon
# A Python-ordered shelf's id order is the expensive part. Keep it well past the
# rendered section so a section expiry (or a warm visit minutes later) reloads
# one page instead of re-ranking the shelf. Media writes invalidate it through
# the same registry; only provider/event refreshes can lag.
HOME_ROW_ORDER_CACHE_TTL = 1800
_HOME_ROW_REGISTRY_TEMPLATE = f"{HOME_ROW_CACHE_PREFIX}_registry_{{user_id}}"


def build_home_row_cache_key(user_id: int, row_id: int, items_limit: int) -> str:
    """Cache key for one built home-row section."""
    return f"{HOME_ROW_CACHE_PREFIX}_{user_id}_{row_id}_{items_limit}"


def _home_row_registry_key(user_id: int) -> str:
    return _HOME_ROW_REGISTRY_TEMPLATE.format(user_id=user_id)


def register_home_row_cache_key(user_id: int, cache_key: str) -> None:
    """Track active home_row cache keys so they can be invalidated on save."""
    _registry_add(_home_row_registry_key(user_id), cache_key)


def clear_home_row_cache_for_user(user_id: int) -> None:
    """Invalidate all cached home_row entries for a user."""
    keys = _registry_take(_home_row_registry_key(user_id))

    if not keys:
        return

    cache.delete_many(keys)

    logger.debug(
        "Cleared %s home_row cache entries for user %s",
        len(keys),
        user_id,
    )


def _media_list_registry_key(user_id: int) -> str:
    return _MEDIA_LIST_REGISTRY_TEMPLATE.format(user_id=user_id)


def register_media_list_cache_key(user_id: int, cache_key: str) -> None:
    """Track active media_list cache keys so they can be invalidated on save."""
    _registry_add(_media_list_registry_key(user_id), cache_key)


MEDIA_LIST_BUILD_LOCK_TTL = 20  # seconds — a crashed builder frees readers fast
MEDIA_LIST_BUILD_WAIT = 5.0  # seconds a follower waits before building anyway
_MEDIA_LIST_BUILD_POLL = 0.05


def acquire_media_list_build_lock(cache_key: str) -> bool:
    """Claim the right to rebuild ``cache_key``; False if a builder is running."""
    return bool(cache.add(f"{cache_key}_building", 1, MEDIA_LIST_BUILD_LOCK_TTL))


def release_media_list_build_lock(cache_key: str) -> None:
    """Drop the build lock once the result is cached."""
    cache.delete(f"{cache_key}_building")


def wait_for_media_list_build(cache_key: str, is_ready) -> bool:
    """Poll until ``is_ready()`` or the lock clears; False means build it yourself."""
    deadline = time.monotonic() + MEDIA_LIST_BUILD_WAIT
    lock_key = f"{cache_key}_building"
    while time.monotonic() < deadline:
        if is_ready():
            return True
        if cache.get(lock_key) is None:
            return is_ready()
        time.sleep(_MEDIA_LIST_BUILD_POLL)
    return is_ready()


def clear_media_list_cache_for_user(user_id: int) -> None:
    """Invalidate all cached media_list entries for a user."""
    keys = _registry_take(_media_list_registry_key(user_id))

    if not keys:
        return

    cache.delete_many(keys)

    logger.debug(
        "Cleared %s media_list cache entries for user %s",
        len(keys),
        user_id,
    )
