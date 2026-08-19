"""Cache-clearing helpers backing Settings > Advanced > Clear Cache buttons.

Each function clears exactly one cache's *payload* keys/rows — not the
internal locks, dedupe keys, or dirty-tracking bookkeeping those caches also
keep in Redis. Those are left alone deliberately: they self-manage, and
deleting them buys nothing but a small chance of a duplicate background
refresh being scheduled.

Search is the one instance-wide cache here (its keys carry no user id, since
search results don't depend on who searched) — clearing it affects every
user of this Floppy instance. History, Statistics, and Discover are all
keyed per-user, so clearing them only touches the requesting user's own data.
"""

from django.core.cache import cache

from app.discover.tab_cache import DISCOVER_TAB_PREFIX
from app.history_cache_utils import HISTORY_DAY_PREFIX, HISTORY_INDEX_PREFIX
from app.models import DiscoverRowCache, DiscoverTasteProfile
from app.statistics_cache import STATISTICS_CACHE_PREFIX, STATISTICS_DAY_PREFIX


def clear_search_cache() -> int:
    """Clear cached provider search/metadata results for every user."""
    return cache.delete_pattern("search_*") or 0


def clear_history_cache_for_user(user_id: int) -> int:
    """Clear a user's cached History day and index payloads."""
    deleted = cache.delete_pattern(f"{HISTORY_DAY_PREFIX}_{user_id}_*") or 0
    deleted += cache.delete_pattern(f"{HISTORY_INDEX_PREFIX}_{user_id}_*") or 0
    return deleted


def clear_statistics_cache_for_user(user_id: int) -> int:
    """Clear a user's cached Statistics page and per-day payloads."""
    deleted = cache.delete_pattern(f"{STATISTICS_CACHE_PREFIX}_{user_id}_*") or 0
    deleted += cache.delete_pattern(f"{STATISTICS_DAY_PREFIX}:{user_id}:*") or 0
    return deleted


def clear_discover_cache_for_user(user_id: int) -> int:
    """Clear a user's cached Discover rows, taste profile, and warm tabs.

    Deliberately does not touch DiscoverApiCache — that table is shared
    across every user of this instance (raw provider responses), not
    per-user data, so a self-service button here shouldn't clear it out
    from under other users.
    """
    deleted_rows, _ = DiscoverRowCache.objects.filter(user_id=user_id).delete()
    deleted_profiles, _ = DiscoverTasteProfile.objects.filter(user_id=user_id).delete()
    deleted_tabs = cache.delete_pattern(f"{DISCOVER_TAB_PREFIX}_{user_id}_*") or 0
    return deleted_rows + deleted_profiles + deleted_tabs
