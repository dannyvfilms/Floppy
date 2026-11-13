"""OpenCritic game scores through RapidAPI, spent against a daily quota.

RapidAPI meters two daily allowances: searches and requests (a search counts
against both). Every response reports what is left and how many seconds until
the reset in ``X-RateLimit-<Quota>-Remaining`` / ``-Reset`` headers, so the
quota recorded here follows whatever plan the key is on. Until a response has
been seen, the free Basic plan's limits and a UTC-midnight reset are assumed.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import UTC, datetime, timedelta
from http import HTTPStatus

import requests
from django.core.cache import cache
from django.utils.text import slugify

from app.providers import credentials, services

logger = logging.getLogger(__name__)

BASE_URL = "https://opencritic-api.p.rapidapi.com"
RAPIDAPI_HOST = "opencritic-api.p.rapidapi.com"
SITE_URL = "https://opencritic.com"

QUOTA_SEARCHES = "searches"
QUOTA_REQUESTS = "requests"
# RapidAPI's free Basic plan for OpenCritic.
FREE_TIER_LIMITS = {QUOTA_SEARCHES: 25, QUOTA_REQUESTS: 200}
QUOTA_CACHE_KEY = "opencritic_quota:{key}:{name}"

_QUOTA_HEADER_RE = re.compile(
    r"^x-ratelimit-(?P<name>searches|requests)-(?P<field>remaining|reset)$",
    re.IGNORECASE,
)


class QuotaExhaustedError(Exception):
    """Raised instead of making a call the day's quota cannot cover."""


def is_configured():
    """Return whether a key applies to the current user or the instance."""
    return credentials.is_configured("opencritic")


def quota_cache_key(name):
    """Return the cache key of a quota, per key since each key has its own."""
    return QUOTA_CACHE_KEY.format(
        key=credentials.cache_suffix("opencritic", "api_key"),
        name=name,
    )


def _next_utc_midnight(now):
    return datetime.combine(
        now.date() + timedelta(days=1),
        datetime.min.time(),
        tzinfo=UTC,
    ).timestamp()


def quota_state(name, now=None):
    """Return ``{"remaining", "reset_at"}`` for a quota, starting fresh after reset."""
    now = now or time.time()
    state = cache.get(quota_cache_key(name))
    if state and state["reset_at"] > now:
        return state
    return {
        "remaining": FREE_TIER_LIMITS[name],
        "reset_at": _next_utc_midnight(datetime.fromtimestamp(now, tz=UTC)),
    }


def _save_quota(name, state, now):
    timeout = max(int(state["reset_at"] - now), 1) + 60
    cache.set(quota_cache_key(name), state, timeout=timeout)


def has_quota(*names):
    """Return whether every named quota has at least one call left."""
    return all(quota_state(name)["remaining"] > 0 for name in names)


def seconds_until_reset():
    """Return seconds until the request quota resets."""
    return max(quota_state(QUOTA_REQUESTS)["reset_at"] - time.time(), 0)


def _record_response(names, response):
    """Charge one call to each quota, then trust any quota headers returned."""
    now = time.time()
    states = {name: dict(quota_state(name, now)) for name in names}
    for state in states.values():
        state["remaining"] = max(state["remaining"] - 1, 0)

    for header, value in response.headers.items():
        match = _QUOTA_HEADER_RE.match(header)
        if not match:
            continue
        name = match["name"].lower()
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        state = states.setdefault(name, dict(quota_state(name, now)))
        if match["field"].lower() == "remaining":
            state["remaining"] = max(number, 0)
        else:
            state["reset_at"] = now + number

    if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
        for state in states.values():
            state["remaining"] = 0

    for name, state in states.items():
        _save_quota(name, state, now)


def _get(path, params, quotas):
    if not has_quota(*quotas):
        raise QuotaExhaustedError(path)
    headers = {
        "X-RapidAPI-Key": credentials.get("opencritic", "api_key"),
        "X-RapidAPI-Host": RAPIDAPI_HOST,
    }
    response = services.resilient_request(
        "GET",
        url=f"{BASE_URL}{path}",
        params=params,
        headers=headers,
        timeout=services.request_timeout(),
    )
    _record_response(quotas, response)
    if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
        raise QuotaExhaustedError(path)
    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as error:
        provider = "opencritic"
        raise services.ProviderAPIError(provider, error) from error
    return response.json()


def search(title):
    """Return OpenCritic search results (``id``/``name`` dicts) for a title."""
    results = _get(
        "/game/search",
        {"criteria": title},
        (QUOTA_SEARCHES, QUOTA_REQUESTS),
    )
    return results if isinstance(results, list) else []


def _number(value):
    """OpenCritic reports a missing score as -1."""
    if isinstance(value, (int, float)) and value >= 0:
        return value
    return None


def game(opencritic_id):
    """Return the stored-score fields for one OpenCritic game."""
    data = _get(f"/game/{int(opencritic_id)}", None, (QUOTA_REQUESTS,))
    url = data.get("url") or ""
    if not url.startswith(SITE_URL):
        url = f"{SITE_URL}/game/{int(opencritic_id)}/{slugify(data.get('name', ''))}"
    return {
        "opencritic_score": _number(data.get("topCriticScore")),
        "opencritic_percent_recommended": _number(data.get("percentRecommended")),
        "opencritic_tier": data.get("tier") or "",
        "opencritic_review_count": _number(data.get("numTopCriticReviews")),
        "opencritic_url": url,
    }
