"""Podcast Index provider for open podcast search.

Podcast Index identifies a show by its RSS feed, so results use the feed URL
as their id and import through the same path as GPodder results. That is what
keeps a show found here and the same show found anywhere else a single show.
"""

import hashlib
import logging
import time

from django.conf import settings
from django.core.cache import cache

from app import helpers, request_timing
from app.models import MediaTypes, Sources
from app.providers import credentials, services

logger = logging.getLogger(__name__)

SEARCH_URL = "https://api.podcastindex.org/api/1.0/search/byterm"
USER_AGENT = "Floppy/1.0 (https://github.com/dannyvfilms/Floppy)"
MAX_RESULTS = 40


def enabled():
    """Return whether a Podcast Index key and secret are configured."""
    return credentials.is_configured(Sources.PODCASTINDEX.value)


def _auth_headers():
    """Build the signed headers Podcast Index requires on every request."""
    api_key, api_secret = credentials.get_together(
        Sources.PODCASTINDEX.value,
        ("api_key", "api_secret"),
    )
    auth_date = str(int(time.time()))
    digest = hashlib.sha1(  # noqa: S324 - the API mandates SHA-1
        f"{api_key}{api_secret}{auth_date}".encode(),
    ).hexdigest()
    return {
        "User-Agent": USER_AGENT,
        "X-Auth-Date": auth_date,
        "X-Auth-Key": api_key,
        "Authorization": digest,
    }


def _search_results(query):
    """Return every show Podcast Index matches for a query."""
    cache_key = (
        f"search_results_{Sources.PODCASTINDEX.value}_{MediaTypes.PODCAST.value}_"
        f"{credentials.cache_suffix(Sources.PODCASTINDEX.value, 'api_key')}_{query}"
    )
    data = cache.get(cache_key)
    if data is not None:
        return data

    response_data = services.api_request(
        Sources.PODCASTINDEX.value,
        "GET",
        SEARCH_URL,
        params={"q": query, "max": MAX_RESULTS, "similar": "true"},
        headers=_auth_headers(),
    )

    results = []
    seen = set()
    feeds = response_data.get("feeds") if isinstance(response_data, dict) else None
    for item in feeds or []:
        feed_url = (item.get("url") or "").strip()
        if not feed_url or feed_url in seen:
            continue
        seen.add(feed_url)
        results.append(
            {
                # The feed is the show's identity, so these import exactly like
                # GPodder results and merge with a show added any other way.
                "media_id": feed_url,
                "source": Sources.GPODDER.value,
                "media_type": MediaTypes.PODCAST.value,
                "title": item.get("title") or "Unknown Podcast",
                "image": item.get("artwork") or item.get("image") or settings.IMG_NONE,
            },
        )

    cache.set(cache_key, results)
    return results


@request_timing.timed_provider_call
def search(query, page):
    """Search for podcasts using the Podcast Index API."""
    per_page = settings.PER_PAGE
    all_results = [] if not query.strip() else _search_results(query)

    start = (page - 1) * per_page
    return helpers.format_search_response(
        page,
        per_page,
        len(all_results),
        all_results[start : start + per_page],
    )
