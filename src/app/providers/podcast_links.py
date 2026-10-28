"""Turn a pasted podcast link into a search result.

Podcast search accepts a show's name, an Apple Podcasts link or an RSS feed
address. The two links resolve directly to the show, whichever source tab is
selected, so a show that no directory lists can still be added.
"""

import logging
import re
from urllib.parse import urlparse

from django.conf import settings

from app import helpers
from app.log_safety import exception_summary
from app.models import MediaTypes, Sources
from integrations import podcast_rss

logger = logging.getLogger(__name__)

_APPLE_ID_RE = re.compile(r"/id(\d+)(?:[/?#]|$)")
_APPLE_HOSTS = {"podcasts.apple.com", "itunes.apple.com"}


def looks_like_link(query):
    """Return whether a search query is a web address."""
    parsed = urlparse((query or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def apple_podcast_id(query):
    """Return the iTunes collection id in an Apple Podcasts link, or None."""
    if not looks_like_link(query):
        return None
    parsed = urlparse(query.strip())
    if (parsed.hostname or "").lower() not in _APPLE_HOSTS:
        return None
    match = _APPLE_ID_RE.search(parsed.path)
    return match.group(1) if match else None


def _apple_result(itunes_id):
    """Look an Apple Podcasts id up and return it as a search result."""
    from app.providers import pocketcasts

    try:
        data = pocketcasts.lookup_by_itunes_id(itunes_id)
    except Exception as exc:  # best-effort: fall back to a plain search
        logger.debug("Apple Podcasts link lookup failed: %s", exception_summary(exc))
        return None
    if not data.get("feed_url"):
        return None
    return {
        "media_id": itunes_id,
        "source": Sources.POCKETCASTS.value,
        "media_type": MediaTypes.PODCAST.value,
        "title": data.get("title") or "Unknown Podcast",
        "image": data.get("artwork_url") or settings.IMG_NONE,
    }


def _feed_result(feed_url):
    """Read an RSS feed address and return its show as a search result."""
    metadata = podcast_rss.fetch_show_metadata_from_rss(feed_url)
    if not metadata.get("title"):
        return None
    return {
        "media_id": feed_url,
        "source": Sources.GPODDER.value,
        "media_type": MediaTypes.PODCAST.value,
        "title": metadata["title"],
        "image": metadata.get("image") or settings.IMG_NONE,
    }


def resolve(query):
    """Return a one-result search response for a pasted link, or None."""
    query = (query or "").strip()
    if not looks_like_link(query):
        return None

    itunes_id = apple_podcast_id(query)
    result = _apple_result(itunes_id) if itunes_id else None
    if result is None:
        result = _feed_result(query)
    if result is None:
        return None
    response = helpers.format_search_response(1, 1, 1, [result])
    # One show is one page; the shared formatter would say there are two.
    response["total_pages"] = 1
    return response
