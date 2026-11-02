"""GPodder provider for public podcast search."""

import logging

from django.conf import settings
from django.core.cache import cache

from app import helpers, request_timing
from app.models import MediaTypes, Sources
from app.providers import services

logger = logging.getLogger(__name__)

SEARCH_URL = "https://gpodder.net/search.json"
USER_AGENT = "Floppy/1.0 (https://github.com/dannyvfilms/Floppy)"


def _search_results(query):
    """Return every podcast gpodder.net matches for a query, unfiltered."""
    cache_key = (
        f"search_results_{Sources.GPODDER.value}_{MediaTypes.PODCAST.value}_{query}"
    )
    data = cache.get(cache_key)
    if data is not None:
        return data

    response_data = services.api_request(
        Sources.GPODDER.value,
        "GET",
        SEARCH_URL,
        params={"q": query},
        # gpodder.net rejects requests without an explicit application
        # User-Agent with HTTP 403.
        headers={"User-Agent": USER_AGENT},
    )

    results = []
    for item in response_data if isinstance(response_data, list) else []:
        feed_url = item.get("url")
        if not feed_url:
            continue
        results.append(
            {
                "media_id": feed_url,
                "source": Sources.GPODDER.value,
                "media_type": MediaTypes.PODCAST.value,
                "title": item.get("title") or "Unknown Podcast",
                "image": item.get("logo_url")
                or item.get("scaled_logo_url")
                or settings.IMG_NONE,
            },
        )

    cache.set(cache_key, results)
    return results


@request_timing.timed_provider_call
def search(query, page):
    """Search for podcasts using the public gpodder.net API."""
    per_page = settings.PER_PAGE
    cache_key = (
        f"search_{Sources.GPODDER.value}_{MediaTypes.PODCAST.value}_{query}_{page}"
    )
    data = cache.get(cache_key)
    if data is not None:
        return data

    all_results = [] if not query.strip() else _search_results(query)

    start = (page - 1) * per_page
    results = all_results[start : start + per_page]
    data = helpers.format_search_response(
        page,
        per_page,
        len(all_results),
        results,
    )
    cache.set(cache_key, data)
    return data
