"""Grand Comics Database (comics.org) metadata provider.

GCD's REST API is a Django REST Framework service: page-number pagination
(50 per page), Basic auth, and a 30/hour anonymous limit against 2000/day for a
logged-in account, so Floppy requires a GCD login. Relations come back as API
URLs (``.../api/series/123/``), so ids are parsed out of those URLs. GCD warns
that the field set is not stable; everything here reads fields defensively.
"""

import base64
import logging
import re
from urllib.parse import quote

import requests
from django.conf import settings
from django.core.cache import cache

from app import helpers
from app.models import MediaTypes, Sources
from app.providers import credentials, services

logger = logging.getLogger(__name__)

site_url = "https://www.comics.org"
base_url = f"{site_url}/api"
GCD_PAGE_SIZE = 50
# Overview pages fetched for one series (50 issues each). A series longer than
# this shows the first pages only and is not scheduled on the calendar, because
# its newest issue would be unknown.
MAX_OVERVIEW_PAGES = 10

_URL_ID_RE = re.compile(r"/(\d+)/?(?:\?.*)?$")
_LEADING_NUMBER_RE = re.compile(r"\d+")
_FULL_DATE_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])")
_YEAR_RE = re.compile(r"\d{4}")
_ISSUE_QUERY_RE = re.compile(r"^(?P<series>.+?)[\s#]+(?P<number>\d+\w*)$")


def request_headers(user=None):
    """Return the request headers, authenticated as the user's GCD account."""
    username = credentials.get("gcd", "username", user=user)
    password = credentials.get("gcd", "password", user=user)
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {
        "User-Agent": "Floppy (self-hosted media tracker)",
        "Accept": "application/json",
        "Authorization": f"Basic {token}",
    }


def handle_error(error):
    """Turn a GCD HTTP error into a ProviderAPIError."""
    status_code = error.response.status_code
    if status_code in (requests.codes.unauthorized, requests.codes.forbidden):
        raise services.ProviderAPIError(
            Sources.GCD.value,
            error,
            "GCD rejected the login. Check the username and password under "
            "Settings > Metadata.",
        )
    raise services.ProviderAPIError(Sources.GCD.value, error)


def _get(path, params=None, user=None):
    """GET a GCD API path and return the parsed JSON."""
    try:
        return services.api_request(
            Sources.GCD.value,
            "GET",
            f"{base_url}{path}",
            params={"format": "json", **(params or {})},
            headers=request_headers(user),
        )
    except requests.exceptions.HTTPError as error:
        handle_error(error)
        return None


def _id_from_url(url):
    """Return the numeric id at the end of a GCD API URL, or None."""
    match = _URL_ID_RE.search(url) if isinstance(url, str) else None
    return match.group(1) if match else None


def _leading_number(number):
    """Return the leading integer of an issue number ("12A" -> 12), or None."""
    match = _LEADING_NUMBER_RE.search(str(number or ""))
    return int(match.group()) if match else None


def _issue_sort_key(issue):
    number = _leading_number(issue.get("issue_number"))
    return (0, number) if number is not None else (1, 0)


def _clean_date(value):
    """Return a YYYY-MM-DD date, or None for blank or partial GCD dates."""
    match = _FULL_DATE_RE.match(value or "")
    return match.group() if match else None


def _year(*values):
    """Return the first four-digit year found in the given values."""
    for value in values:
        match = _YEAR_RE.search(value or "")
        if match:
            return match.group()
    return None


def _cover(url):
    """Return a cover URL, or the placeholder when the issue has none."""
    return url or settings.IMG_NONE


def _issue_title(series_name, number, title):
    label = f"{series_name} #{number}".strip()
    return f"{label}: {title}" if title else label


def search(query, page, user=None):
    """Search GCD series by name."""
    cache_key = f"search_{Sources.GCD.value}_{MediaTypes.COMIC.value}_{query}_{page}"
    data = cache.get(cache_key)

    if data is None:
        response = _get(
            f"/series/name/{quote(query, safe='')}/",
            {"page": page},
            user,
        )
        results = [
            {
                "media_id": series_id,
                "source": Sources.GCD.value,
                "media_type": MediaTypes.COMIC.value,
                "title": item.get("name") or "",
                # The list endpoint carries no cover; the detail page does.
                "image": settings.IMG_NONE,
                "year": item.get("year_began"),
            }
            for item in response.get("results", [])
            if (series_id := _id_from_url(item.get("api_url")))
        ]
        data = helpers.format_search_response(
            page,
            GCD_PAGE_SIZE,
            response.get("count", len(results)),
            results,
        )
        cache.set(cache_key, data)

    return data


def search_issues(query, page, user=None):
    """Search GCD issues. GCD needs a series name and an issue number.

    A query like "Batman #12" is split into the two; a query without a
    trailing number has no GCD equivalent and returns no results.
    """
    match = _ISSUE_QUERY_RE.match(query.strip())
    if not match:
        return helpers.format_search_response(page, GCD_PAGE_SIZE, 0, [])

    cache_key = (
        f"search_{Sources.GCD.value}_{MediaTypes.COMIC_ISSUE.value}_{query}_{page}"
    )
    data = cache.get(cache_key)

    if data is None:
        response = _get(
            f"/series/name/{quote(match['series'], safe='')}"
            f"/issue/{quote(match['number'], safe='')}/",
            {"page": page},
            user,
        )
        results = [
            {
                "media_id": issue_id,
                "source": Sources.GCD.value,
                "media_type": MediaTypes.COMIC_ISSUE.value,
                "title": _issue_title(
                    item.get("series_name") or "",
                    item.get("descriptor") or match["number"],
                    "",
                ),
                "image": settings.IMG_NONE,
                "year": _year(item.get("publication_date")),
            }
            for item in response.get("results", [])
            if (issue_id := _id_from_url(item.get("api_url")))
        ]
        data = helpers.format_search_response(
            page,
            GCD_PAGE_SIZE,
            response.get("count", len(results)),
            results,
        )
        cache.set(cache_key, data)

    return data


def _publisher_name(publisher_url, user=None):
    """Return the publisher's name, or None when it cannot be fetched."""
    publisher_id = _id_from_url(publisher_url)
    if not publisher_id:
        return None

    cache_key = f"{Sources.GCD.value}_publisher_{publisher_id}"
    name = cache.get(cache_key)
    if name is None:
        try:
            name = _get(f"/publisher/{publisher_id}/", user=user).get("name") or ""
        except services.ProviderAPIError:
            logger.warning("Failed to fetch GCD publisher %s", publisher_id)
            return None
        cache.set(cache_key, name)
    return name or None


def get_series_issues(series_id, series_name, user=None):
    """Return (issues sorted by number, complete) for a series.

    ``complete`` is False when the series is longer than MAX_OVERVIEW_PAGES.
    """
    cache_key = f"{Sources.GCD.value}_series_{series_id}_issues"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    issues = []
    complete = False
    for page in range(1, MAX_OVERVIEW_PAGES + 1):
        response = _get(f"/series/{series_id}/overview/", {"page": page}, user)
        issues.extend(
            {
                "media_id": str(item["issue_id"]),
                "source": Sources.GCD.value,
                "media_type": MediaTypes.COMIC_ISSUE.value,
                "issue_number": item.get("number") or "",
                "title": f"{series_name} #{item.get('number') or ''}".strip(),
                "image": _cover(item.get("cover_url")),
                "cover_date": _clean_date(item.get("key_date")),
                "store_date": _clean_date(item.get("on_sale_date")),
                "site_detail_url": f"{site_url}/issue/{item['issue_id']}/",
                "history": [],
            }
            for item in response.get("results", [])
            if item.get("issue_id")
        )
        if not response.get("next"):
            complete = True
            break

    result = (sorted(issues, key=_issue_sort_key), complete)
    cache.set(cache_key, result)
    return result


def comic(media_id, user=None):
    """Return the metadata for a GCD series."""
    cache_key = f"{Sources.GCD.value}_{MediaTypes.COMIC.value}_{media_id}"
    data = cache.get(cache_key)

    if data is None:
        response = _get(f"/series/{media_id}/", user=user)
        if not response or not response.get("name"):
            services.raise_not_found_error(Sources.GCD.value, media_id, "comic")

        try:
            issues, complete = get_series_issues(media_id, response["name"], user=user)
        except services.ProviderAPIError:
            logger.warning("Failed to fetch issues for GCD series %s", media_id)
            issues, complete = [], False

        numbered = [i for i in issues if _leading_number(i["issue_number"]) is not None]
        last_issue = numbered[-1] if numbered and complete else None
        image = next(
            (i["image"] for i in issues if i["image"] != settings.IMG_NONE),
            settings.IMG_NONE,
        )

        data = {
            "media_id": media_id,
            "source": Sources.GCD.value,
            "source_url": f"{site_url}/series/{media_id}/",
            "media_type": MediaTypes.COMIC.value,
            "title": response["name"],
            "max_progress": None,
            "max_issue_number": (
                _leading_number(last_issue["issue_number"]) if last_issue else None
            ),
            "image": image,
            "synopsis": (response.get("notes") or "").strip()
            or "No synopsis available",
            "genres": None,
            "score": None,
            "score_count": None,
            "details": {
                "start_date": response.get("year_began"),
                "publisher": _publisher_name(response.get("publisher"), user),
                "issues_count": len(response.get("active_issues") or issues),
                "last_issue_number": last_issue["issue_number"] if last_issue else None,
            },
            "authors_full": [],
            "related": {"recommendations": []},
            # used for events fetching
            "last_issue_id": last_issue["media_id"] if last_issue else None,
            "issues": issues,
        }
        cache.set(cache_key, data)

    return data


def _first_synopsis(stories):
    """Return the synopsis of the first story that has one."""
    for story in stories or []:
        if isinstance(story, dict) and (story.get("synopsis") or "").strip():
            return story["synopsis"].strip()
    return None


def comic_issue(media_id, user=None):
    """Return the metadata for a GCD issue."""
    cache_key = f"{Sources.GCD.value}_{MediaTypes.COMIC_ISSUE.value}_{media_id}"
    data = cache.get(cache_key)

    if data is None:
        response = _get(f"/issue/{media_id}/", user=user)
        if not response or not response.get("series_name"):
            services.raise_not_found_error(Sources.GCD.value, media_id, "comic_issue")

        series_name = response["series_name"]
        number = response.get("number") or ""
        cover_date = _clean_date(response.get("key_date"))
        store_date = _clean_date(response.get("on_sale_date"))

        data = {
            "media_id": media_id,
            "source": Sources.GCD.value,
            "source_url": f"{site_url}/issue/{media_id}/",
            "media_type": MediaTypes.COMIC_ISSUE.value,
            "title": _issue_title(series_name, number, response.get("title") or ""),
            "max_progress": 1,
            "image": _cover(response.get("cover")),
            "synopsis": _first_synopsis(response.get("story_set"))
            or (response.get("notes") or "").strip()
            or "No synopsis available",
            "genres": None,
            "score": None,
            "score_count": None,
            "details": {
                "issue_number": number,
                "volume_name": series_name,
                "volume_id": _id_from_url(response.get("series")) or "",
                "cover_date": cover_date,
                "store_date": store_date,
                "start_date": _year(cover_date, store_date, response.get("key_date")),
            },
            "authors_full": [],
            "related": {"recommendations": []},
        }
        cache.set(cache_key, data)

    return data
