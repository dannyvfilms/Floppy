"""Fetch and parse podcast episodes from RSS feeds.

Similar to pocketcasts_artwork.py, this module fetches episode data from
public RSS feeds to get the complete episode list, not just what's in
Pocket Casts history.
"""

import contextlib
import logging
import re
from datetime import datetime
from xml.etree.ElementTree import Element

import requests
from defusedxml import ElementTree as ET  # noqa: N817  # long-standing alias
from django.utils import timezone

from app.log_safety import exception_summary, safe_url
from integrations.safe_fetch import UnsafeUrlError, safe_fetch

logger = logging.getLogger(__name__)

USER_AGENT = "Floppy/1.0 (https://github.com/dannyvfilms/Floppy)"
MAX_FEED_BYTES = 10 * 1024 * 1024

# Component counts for duration strings formatted as "MM:SS" or "HH:MM:SS".
DURATION_PARTS_MM_SS = 2
DURATION_PARTS_HH_MM_SS = 3


def _fetch_feed_root(rss_feed_url: str) -> Element | None:
    """Fetch a feed once and return its parsed root, or None if unusable.

    Every reader of a feed goes through here, so a caller that wants both the
    channel metadata and the episodes can read the document once instead of
    issuing two identical HTTP requests -- which is what the podcast detail
    page does on every view.
    """
    try:
        response, body = safe_fetch(
            rss_feed_url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/rss+xml, application/atom+xml, application/xml",
            },
            max_bytes=MAX_FEED_BYTES,
        )
        response.raise_for_status()
    except (requests.RequestException, UnsafeUrlError) as e:
        logger.exception(
            "Failed to fetch RSS feed %s: %s",
            safe_url(rss_feed_url),
            exception_summary(e),  # noqa: TRY401  # exception_summary() is the project's sanitised rendering
        )
        return None
    except Exception as e:
        logger.exception(
            "Unexpected error fetching RSS feed %s: %s",
            safe_url(rss_feed_url),
            exception_summary(e),  # noqa: TRY401  # exception_summary() is the project's sanitised rendering
        )
        return None

    try:
        return ET.fromstring(body)
    except ET.ParseError:
        logger.exception("Failed to parse RSS feed XML")
        return None


def _extract_show_metadata(root: Element) -> dict:
    """Read the channel-level show metadata out of an already-parsed feed."""
    metadata = {}
    namespaces = {
        "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
    }

    # Find channel element (RSS) or feed element (Atom)
    channel = root.find(".//channel")
    if channel is None:
        # Try Atom feed
        channel = root if root.tag == "feed" or root.tag.endswith("}feed") else None

    if channel is not None:
        title_elem = channel.find("title")
        if title_elem is None:
            title_elem = channel.find("{http://www.w3.org/2005/Atom}title")
        if title_elem is not None and title_elem.text:
            metadata["title"] = title_elem.text.strip()

        # Description
        desc_elem = channel.find("description")
        if desc_elem is None:
            desc_elem = channel.find("itunes:summary", namespaces)
        if desc_elem is None:
            desc_elem = channel.find("{http://www.w3.org/2005/Atom}summary")
        if desc_elem is not None and desc_elem.text:
            description = desc_elem.text.strip()
            # Remove HTML tags
            description = re.sub(r"<[^>]+>", "", description)
            metadata["description"] = description

        # Language
        lang_elem = channel.find("language")
        if lang_elem is not None and lang_elem.text:
            metadata["language"] = lang_elem.text.strip()

        # Author, from the iTunes namespace.
        author_elem = channel.find("itunes:author", namespaces)
        if author_elem is not None and author_elem.text:
            metadata["author"] = author_elem.text.strip()

        # Artwork, preferring the iTunes namespace image, falling back to
        # the plain RSS <image><url> element.
        itunes_image_elem = channel.find("itunes:image", namespaces)
        if itunes_image_elem is not None and itunes_image_elem.get("href"):
            metadata["image"] = itunes_image_elem.get("href").strip()
        else:
            image_url_elem = channel.find("image/url")
            if image_url_elem is not None and image_url_elem.text:
                metadata["image"] = image_url_elem.text.strip()

        # Website, preferring the plain RSS <link> text content, falling
        # back to an Atom <link rel="alternate"> element's href.
        link_elem = channel.find("link")
        if link_elem is not None and link_elem.text:
            metadata["website_url"] = link_elem.text.strip()
        else:
            for candidate in channel.findall(
                "{http://www.w3.org/2005/Atom}link"
            ):
                rel = candidate.get("rel")
                href = candidate.get("href")
                if rel in (None, "alternate") and href:
                    metadata["website_url"] = href.strip()
                    break
    return metadata


def _extract_episodes(root: Element, limit: int | None) -> list[dict]:
    """Read the episode list out of an already-parsed feed."""
    if root.tag == "feed" or root.tag.endswith("}feed"):
        return _parse_atom_feed(root, limit)
    return _parse_rss_feed(root, limit)


def fetch_show_metadata_from_rss(rss_feed_url: str) -> dict:
    """Fetch show metadata from RSS feed channel.

    Args:
        rss_feed_url: URL to the podcast RSS feed

    Returns:
        Dict with show metadata:
        - description: Show description
        - language: Show language (optional)
        - author: Show author (optional)
        - image: Show artwork URL (optional)
        - website_url: Show homepage URL (optional)
    """
    root = _fetch_feed_root(rss_feed_url)
    if root is None:
        return {}
    try:
        return _extract_show_metadata(root)
    except Exception as e:
        logger.exception(
            "Unexpected error parsing RSS feed %s: %s",
            safe_url(rss_feed_url),
            exception_summary(e),  # noqa: TRY401  # exception_summary() is the project's sanitised rendering
        )
        return {}


def fetch_episodes_from_rss(rss_feed_url: str, limit: int | None = None) -> list[dict]:
    """Fetch and parse episodes from RSS feed.

    Args:
        rss_feed_url: URL to the podcast RSS feed
        limit: Optional limit on number of episodes to return (None = all)

    Returns:
        List of episode dicts with keys:
        - title: Episode title
        - published: Published datetime (timezone-aware)
        - duration: Duration in seconds (optional)
        - audio_url: Audio file URL (optional)
        - guid: Episode GUID/UUID for matching (optional)
        - episode_number: Episode number (optional)
        - season_number: Season number (optional)
        - description: Episode description (optional)
        - website_url: Episode webpage URL (optional)
    """
    root = _fetch_feed_root(rss_feed_url)
    if root is None:
        return []
    try:
        episodes = _extract_episodes(root, limit)
    except Exception as e:
        logger.exception(
            "Unexpected error parsing RSS feed %s: %s",
            safe_url(rss_feed_url),
            exception_summary(e),  # noqa: TRY401  # exception_summary() is the project's sanitised rendering
        )
        return []
    logger.info(
        "Fetched %d episodes from RSS feed %s",
        len(episodes),
        safe_url(rss_feed_url),
    )
    return episodes


def fetch_feed_from_rss(
    rss_feed_url: str,
    limit: int | None = None,
) -> tuple[dict, list[dict]]:
    """Read a feed once, returning (show metadata, episodes).

    For callers that want both. Going through the two single-purpose functions
    above would fetch the same document twice.
    """
    root = _fetch_feed_root(rss_feed_url)
    if root is None:
        return {}, []
    try:
        metadata = _extract_show_metadata(root)
        episodes = _extract_episodes(root, limit)
    except Exception as e:
        logger.exception(
            "Unexpected error parsing RSS feed %s: %s",
            safe_url(rss_feed_url),
            exception_summary(e),  # noqa: TRY401  # exception_summary() is the project's sanitised rendering
        )
        return {}, []
    logger.info(
        "Fetched %d episodes from RSS feed %s",
        len(episodes),
        safe_url(rss_feed_url),
    )
    return metadata, episodes


def _parse_rss_feed(root: Element, limit: int | None) -> list[dict]:
    """Parse RSS 2.0 format feed."""
    episodes = []
    namespaces = {
        "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
        "content": "http://purl.org/rss/1.0/modules/content/",
    }

    # Find all items
    items = root.findall(".//item")
    if limit:
        items = items[:limit]

    for item in items:
        episode = {}

        # Title
        title_elem = item.find("title")
        if title_elem is not None and title_elem.text:
            episode["title"] = title_elem.text.strip()
        else:
            continue  # Skip items without titles

        # Published date
        pub_date_elem = item.find("pubDate")
        if pub_date_elem is not None and pub_date_elem.text:
            episode["published"] = _parse_date(pub_date_elem.text.strip())

        # GUID
        guid_elem = item.find("guid")
        if guid_elem is not None:
            guid_text = guid_elem.text or guid_elem.get("isPermaLink", "")
            if guid_text:
                episode["guid"] = guid_text.strip()

        # Duration, from the iTunes namespace.
        duration_elem = item.find("itunes:duration", namespaces)
        if duration_elem is not None and duration_elem.text:
            episode["duration"] = _parse_duration(duration_elem.text.strip())

        # Audio URL (enclosure)
        enclosure_elem = item.find("enclosure")
        if enclosure_elem is not None:
            audio_url = enclosure_elem.get("url")
            if audio_url:
                episode["audio_url"] = audio_url

        # Website (shownotes) URL
        link_elem = item.find("link")
        if link_elem is not None and link_elem.text:
            episode["website_url"] = link_elem.text.strip()

        # Episode number (iTunes)
        episode_elem = item.find("itunes:episode", namespaces)
        if episode_elem is not None and episode_elem.text:
            with contextlib.suppress(ValueError):
                episode["episode_number"] = int(episode_elem.text.strip())

        # Season number (iTunes)
        season_elem = item.find("itunes:season", namespaces)
        if season_elem is not None and season_elem.text:
            with contextlib.suppress(ValueError):
                episode["season_number"] = int(season_elem.text.strip())

        # Description
        description_elem = item.find("description")
        if description_elem is not None and description_elem.text:
            # Strip HTML tags for basic description
            description = description_elem.text.strip()
            # Remove common HTML tags
            description = re.sub(r"<[^>]+>", "", description)
            episode["description"] = description[:500]  # Limit length

        episodes.append(episode)

    return episodes


def _parse_atom_feed(root: Element, limit: int | None) -> list[dict]:
    """Parse Atom format feed."""
    episodes = []
    namespaces = {
        "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
    }

    # Find all entries
    entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    if not entries:
        # Try without namespace
        entries = root.findall(".//entry")

    if limit:
        entries = entries[:limit]

    for entry in entries:
        episode = {}

        # Title
        title_elem = entry.find("{http://www.w3.org/2005/Atom}title")
        if title_elem is None:
            title_elem = entry.find("title")
        if title_elem is not None and title_elem.text:
            episode["title"] = title_elem.text.strip()
        else:
            continue  # Skip entries without titles

        # Published date
        published_elem = entry.find("{http://www.w3.org/2005/Atom}published")
        if published_elem is None:
            published_elem = entry.find("published")
        if published_elem is not None and published_elem.text:
            episode["published"] = _parse_date(published_elem.text.strip())

        # ID (used as GUID)
        id_elem = entry.find("{http://www.w3.org/2005/Atom}id")
        if id_elem is None:
            id_elem = entry.find("id")
        if id_elem is not None and id_elem.text:
            episode["guid"] = id_elem.text.strip()

        # Duration, from the iTunes namespace.
        duration_elem = entry.find("itunes:duration", namespaces)
        if duration_elem is not None and duration_elem.text:
            episode["duration"] = _parse_duration(duration_elem.text.strip())

        # Audio URL (link with type="audio")
        links = entry.findall("{http://www.w3.org/2005/Atom}link")
        if not links:
            links = entry.findall("link")
        for link in links:
            link_type = link.get("type", "")
            if "audio" in link_type or link.get("rel") == "enclosure":
                audio_url = link.get("href")
                if audio_url:
                    episode["audio_url"] = audio_url
                    break

        # Website (shownotes) URL
        for link in links:
            rel = link.get("rel")
            href = link.get("href")
            if rel in (None, "alternate") and href:
                episode["website_url"] = href
                break

        # Episode number (iTunes)
        episode_elem = entry.find("itunes:episode", namespaces)
        if episode_elem is not None and episode_elem.text:
            with contextlib.suppress(ValueError):
                episode["episode_number"] = int(episode_elem.text.strip())

        # Season number (iTunes)
        season_elem = entry.find("itunes:season", namespaces)
        if season_elem is not None and season_elem.text:
            with contextlib.suppress(ValueError):
                episode["season_number"] = int(season_elem.text.strip())

        # Description/Summary
        summary_elem = entry.find("{http://www.w3.org/2005/Atom}summary")
        if summary_elem is None:
            summary_elem = entry.find("summary")
        if summary_elem is not None and summary_elem.text:
            description = summary_elem.text.strip()
            description = re.sub(r"<[^>]+>", "", description)
            episode["description"] = description[:500]

        episodes.append(episode)

    return episodes


def _parse_date(date_str: str) -> datetime | None:
    """Parse date string from RSS feed.

    Handles common formats:
    - RFC 822: "Mon, 01 Jan 2024 12:00:00 GMT"
    - ISO 8601: "2024-01-01T12:00:00Z"
    - ISO 8601 with timezone: "2024-01-01T12:00:00+00:00"
    """
    if not date_str:
        return None

    # Try common formats
    formats = [
        "%a, %d %b %Y %H:%M:%S %Z",  # RFC 822
        "%a, %d %b %Y %H:%M:%S %z",  # RFC 822 with timezone
        "%Y-%m-%dT%H:%M:%SZ",  # ISO 8601 UTC
        "%Y-%m-%dT%H:%M:%S%z",  # ISO 8601 with timezone
        "%Y-%m-%dT%H:%M:%S",  # ISO 8601 without timezone
        "%Y-%m-%d",  # Date only
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)  # noqa: DTZ007  # date-only value; no timezone applies
            # Make timezone-aware if not already
            if timezone.is_naive(dt):
                dt = timezone.make_aware(dt)
        except ValueError:
            continue
        else:
            return dt

    # Try ISO format with fromisoformat
    try:
        # Handle Z suffix
        date_str_clean = date_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(date_str_clean)
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt)
    except (ValueError, AttributeError):
        pass
    else:
        return dt

    logger.debug("Failed to parse date: %s", date_str)
    return None


def _parse_duration(duration_str: str) -> int | None:
    """Parse duration string to seconds.

    Handles formats:
    - "3600" (seconds)
    - "60:00" (MM:SS)
    - "1:00:00" (HH:MM:SS)
    """
    if not duration_str:
        return None

    # Try simple integer (seconds)
    try:
        return int(duration_str)
    except ValueError:
        pass

    # Try MM:SS or HH:MM:SS format
    parts = duration_str.split(":")
    if len(parts) == DURATION_PARTS_MM_SS:
        # Format is minutes then seconds.
        try:
            minutes = int(parts[0])
            seconds = int(parts[1])
            return minutes * 60 + seconds
        except ValueError:
            pass
    elif len(parts) == DURATION_PARTS_HH_MM_SS:
        # HH:MM:SS
        try:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = int(parts[2])
            return hours * 3600 + minutes * 60 + seconds
        except ValueError:
            pass

    logger.debug("Failed to parse duration: %s", duration_str)
    return None
