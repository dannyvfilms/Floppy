"""Day-cache keys and history versions shared by statistics builders and refreshes.

This module must remain independent of the range cache and its orchestration.
"""

from datetime import date, datetime

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

STATISTICS_DAY_CACHE_VERSION = 9
STATISTICS_DAY_PREFIX = f"stats:day:v{STATISTICS_DAY_CACHE_VERSION}"
STATISTICS_HISTORY_VERSION_PREFIX = "stats:history_version"
STATISTICS_DAY_CACHE_TIMEOUT = getattr(
    settings, "STATISTICS_DAY_CACHE_TIMEOUT", 60 * 60 * 24 * 30
)
DAY_KEY_LENGTH = 8


def _normalize_day_value(value):
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        localized = timezone.localtime(value) if timezone.is_aware(value) else value
        return localized.date()
    if isinstance(value, str):
        try:
            if value.isdigit() and len(value) == DAY_KEY_LENGTH:
                return datetime.strptime(value, "%Y%m%d").date()  # noqa: DTZ007  # date-only value; no timezone applies
            return datetime.strptime(value, "%Y-%m-%d").date()  # noqa: DTZ007  # date-only value; no timezone applies
        except ValueError:
            return None
    return None


def _day_cache_key(user_id: int, day_value: date | datetime | str) -> str:
    day = _normalize_day_value(day_value)
    if not day:
        return ""
    return f"{STATISTICS_DAY_PREFIX}:{user_id}:{day.isoformat()}"


def _history_version_key(user_id: int) -> str:
    return f"{STATISTICS_HISTORY_VERSION_PREFIX}:{user_id}"


def _get_history_version(user_id: int) -> str:
    version = cache.get(_history_version_key(user_id))
    if version:
        return version
    version = timezone.now().isoformat()
    cache.set(
        _history_version_key(user_id), version, timeout=STATISTICS_DAY_CACHE_TIMEOUT
    )
    return version


def _set_history_version(user_id: int, value: str | None = None) -> str:
    version = value or timezone.now().isoformat()
    cache.set(
        _history_version_key(user_id), version, timeout=STATISTICS_DAY_CACHE_TIMEOUT
    )
    return version
