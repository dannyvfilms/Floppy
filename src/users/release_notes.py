"""Release notes shown on the About page and the "updated" banner.

The notes are the highlights written on each GitHub Release. They are written
after the image is built, so Floppy reads them from GitHub rather than
shipping them in the image. A server that cannot reach GitHub gets ``None``
and the page links to the releases instead.
"""

import logging
import re

import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

RELEASES_URL = "https://api.github.com/repos/dannyvfilms/Floppy/releases"
RELEASES_PAGE_URL = "https://github.com/dannyvfilms/Floppy/releases"
CACHE_KEY = "release_notes_v1"
CACHE_TTL = 6 * 60 * 60
FAILURE_TTL = 10 * 60
RELEASES_SHOWN = 3
REQUEST_TIMEOUT = 5

_TAG_RE = re.compile(r"^v?(\d+(?:\.\d+)*)")
_BULLET_RE = re.compile(r"^\s*[*-]\s+(.*\S)\s*$")
_BOLD_LEAD_RE = re.compile(r"^\*\*(.+?)\*\*\s*[\u2014\u2013-]*\s*(.*)$")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def release_tag(version):
    """Return the release tag a version string was built from, or "".

    ``git describe`` on a build between releases reads ``v26.10.8-12-gabc123``
    (plus ``-dirty``); the banner and the "Installed" label care about the
    release underneath, not the commit.
    """
    match = _TAG_RE.match(version or "")
    if not match:
        return ""
    return f"v{match.group(1)}"


def tag_sort_key(tag):
    """Order tags numerically, so v26.10.8 sorts after v26.9.24."""
    match = _TAG_RE.match(tag or "")
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def _plain(text):
    """Drop Markdown links and emphasis; the page renders plain text."""
    text = _LINK_RE.sub(r"\1", text)
    return text.replace("**", "").replace("`", "").strip()


def parse_highlights(body):
    """Return [{"title", "text"}] from a release's "Changes since" section."""
    highlights = []
    in_section = False
    for line in (body or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            if in_section:
                break
            in_section = stripped.lstrip("#").strip().lower().startswith("changes")
            continue
        if not in_section:
            continue
        bullet = _BULLET_RE.match(line)
        if not bullet:
            continue
        lead = _BOLD_LEAD_RE.match(bullet.group(1))
        if lead:
            highlights.append(
                {"title": _plain(lead.group(1)), "text": _plain(lead.group(2))},
            )
        else:
            highlights.append({"title": "", "text": _plain(bullet.group(1))})
    return highlights


def _fetch():
    response = requests.get(
        RELEASES_URL,
        params={"per_page": RELEASES_SHOWN},
        headers={"Accept": "application/vnd.github+json"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    releases = []
    for item in response.json():
        if item.get("draft") or item.get("prerelease"):
            continue
        releases.append(
            {
                "tag": item["tag_name"],
                "url": item["html_url"],
                "published": (item.get("published_at") or "")[:10],
                "highlights": parse_highlights(item.get("body")),
            },
        )
    return releases


def get_releases():
    """Return recent releases, newest first, or None when GitHub is unreachable."""
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached or None
    try:
        releases = _fetch()
    except (requests.RequestException, ValueError, KeyError, TypeError):
        logger.warning("Could not load release notes from GitHub", exc_info=True)
        cache.set(CACHE_KEY, [], FAILURE_TTL)
        return None
    releases.sort(key=lambda release: tag_sort_key(release["tag"]), reverse=True)
    cache.set(CACHE_KEY, releases, CACHE_TTL)
    return releases or None
