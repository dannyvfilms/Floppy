import logging

import requests
from django.conf import settings
from django.core.cache import cache

from app import helpers
from app.models import MediaTypes, Sources
from app.providers import services

logger = logging.getLogger(__name__)
base_url = "https://api.mangabaka.org/v1"
# MangaBaka rejects the default python-requests User-Agent with 403.
headers = {
    "User-Agent": "Mozilla/5.0",
}


def search(query, page):
    """Search for manga on MangaBaka."""
    cache_key = (
        f"search_{Sources.MANGABAKA.value}_{MediaTypes.MANGA.value}_{query}_{page}"
    )
    data = cache.get(cache_key)

    if data is None:
        url = f"{base_url}/series/search"
        per_page = 30
        params = {
            "q": query,
            "limit": per_page,
            "page": page,
        }

        if not settings.MAL_NSFW:
            params["content_rating"] = "safe"

        try:
            response = services.api_request(
                Sources.MANGABAKA.value,
                "GET",
                url,
                params=params,
                headers=headers,
            )
        except requests.exceptions.HTTPError as error:
            raise services.ProviderAPIError(
                Sources.MANGABAKA.value,
                error,
            ) from error

        results = [
            {
                "media_id": str(item["id"]),
                "source": Sources.MANGABAKA.value,
                "media_type": MediaTypes.MANGA.value,
                "title": item["title"],
                "image": get_image_url(item, thumbnail=True),
                "year": item.get("year"),
            }
            for item in response["data"]
        ]

        total_results = response["pagination"]["count"]
        data = helpers.format_search_response(
            page,
            per_page,
            total_results,
            results,
        )

        cache.set(cache_key, data)

    return data


def manga(media_id):
    """Get metadata for a manga from MangaBaka."""
    cache_key = f"{Sources.MANGABAKA.value}_{MediaTypes.MANGA.value}_{media_id}"
    data = cache.get(cache_key)

    if data is None:
        url = f"{base_url}/series/{media_id}"

        try:
            response = services.api_request(
                Sources.MANGABAKA.value,
                "GET",
                url,
                headers=headers,
            )
        except requests.exceptions.HTTPError as error:
            raise services.ProviderAPIError(
                Sources.MANGABAKA.value,
                error,
            ) from error

        series = response["data"]

        data = {
            "media_id": str(series["id"]),
            "source": Sources.MANGABAKA.value,
            "source_url": series["canonical_url"],
            "media_type": MediaTypes.MANGA.value,
            "title": series["title"],
            "image": get_image_url(series),
            "synopsis": series.get("description"),
            "max_progress": _parse_int(series.get("total_chapters")),
            "genres": get_genres(series.get("genres")),
            "score": get_score(series.get("rating")),
            "score_count": None,
            "details": {
                "format": series.get("type"),
                "authors": get_authors(series),
                "year": series.get("year"),
                "status_in_country_of_origin": series.get("status"),
                "volumes": _parse_int(series.get("final_volume")),
            },
            "authors_full": get_authors_full(series),
            "related": {
                "related_manga": get_related(series.get("relationships_v2")),
                "recommendations": [],
            },
        }

        cache.set(cache_key, data)

    return data


def get_image_url(series, *, thumbnail=False):
    """Get the cover URL: full-res raw for detail, x350 thumb for grids."""
    cover = series.get("cover") or {}
    raw_url = (cover.get("raw") or {}).get("url")
    if not thumbnail and raw_url:
        return raw_url
    url = (
        (cover.get("x350") or {}).get("x1")
        or (cover.get("x250") or {}).get("x1")
        or raw_url
    )
    return url or settings.IMG_NONE


def get_genres(genres):
    """Return display-normalized genres ("slice_of_life" -> "Slice of Life")."""
    if not genres:
        return None
    return [genre.replace("_", " ").title() for genre in genres]


def get_score(rating):
    """Return the score scaled from MangaBaka's 0-100 range to 0-10."""
    if rating:
        return round(rating / 10, 1)
    return None


def get_authors(series):
    """Get the combined author/artist names for a series."""
    names = list(series.get("authors") or []) + list(series.get("artists") or [])
    seen = set()
    unique = []
    for name in names:
        if name not in seen:
            seen.add(name)
            unique.append(name)
    return unique or None


def get_authors_full(series):
    """Normalize MangaBaka author/artist names into authors_full payload rows."""
    # MangaBaka authors are plain strings with no IDs; use the name as person_id.
    entries = [(name, "Author") for name in series.get("authors") or []]
    entries += [(name, "Artist") for name in series.get("artists") or []]

    normalized = []
    seen = set()
    for index, (raw_name, role) in enumerate(entries):
        name = (raw_name or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        normalized.append(
            {
                "person_id": name,
                "name": name,
                "image": settings.IMG_NONE,
                "role": role,
                "sort_order": index,
            },
        )
    return normalized


OFFICIAL_RELATION_TYPES = frozenset(
    {
        "main",
        "side_story",
        "sequel",
        "prequel",
        "source",
        "spin_off",
    },
)


def get_related(relationships):
    """Return official related-manga rows with titles resolved from the API."""
    if not relationships:
        return []
    related = []
    for rel in relationships:
        if rel.get("relation_type") not in OFFICIAL_RELATION_TYPES:
            continue
        to_id = rel.get("to_series_id")
        if to_id is None:
            continue
        try:
            response = services.api_request(
                Sources.MANGABAKA.value,
                "GET",
                f"{base_url}/series/{to_id}",
                headers=headers,
            )
        except requests.exceptions.HTTPError:
            logger.warning("Failed to fetch related MangaBaka series %s", to_id)
            continue
        series = response["data"]
        related.append(
            {
                "source": Sources.MANGABAKA.value,
                "media_id": str(series["id"]),
                "media_type": MediaTypes.MANGA.value,
                "title": series.get("title", ""),
                "image": get_image_url(series, thumbnail=True),
                "year": series.get("year"),
                "relation_type": rel.get("relation_type", ""),
            },
        )
    return related


def _parse_int(value):
    """Parse numeric-string counts like total_chapters/final_volume."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
