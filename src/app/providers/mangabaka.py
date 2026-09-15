import logging

import requests
from django.conf import settings
from django.core.cache import cache

from app import helpers
from app.models import MediaTypes, Sources
from app.providers import services

logger = logging.getLogger(__name__)
base_url = "https://api.mangabaka.org/v1"
# Bumped whenever the search result shape changes, so entries cached before a
# filter/field change are not served unchanged (same reason as IGDB's).
SEARCH_CACHE_VERSION = "v2"
# Metadata payload shape version. Bump when details keys change so detail pages
# are not served a payload built by the previous normalizer.
METADATA_CACHE_VERSION = "v2"
# MangaBaka's tags_v2 is the richest signal it exposes, but its raw form is
# unusable on a detail page (Overlord carries 107 flat tags, Berserk 306). Three
# candidate filters do not survive contact with real data:
#   * `weight` is not a safety or relevance proxy -- Nudity, Child Abuse and
#     Sexual Abuse are all "defining", Pedophilia and Vore are "recurrent".
#   * `level` is structural depth, not importance -- it drops Nobility (n=5710)
#     and Demons (n=5151) while admitting Heretic (n=6).
#   * `content_rating` and `is_explicit` are both unreliable -- Child Abuse,
#     Sexual Abuse, Pedophilia and Vore are rated "safe", and `is_explicit` is
#     also set on harmless tags like Discrimination.
# The namespace prefix of `name_path` is the dependable signal: the only
# namespace yielding explicit labels is "Sexual Content" (12 of its 27 sampled
# tags are pornographic, against 0 elsewhere), so excluding it removes that
# whole category in one rule. The remaining excluded namespaces are
# publication/audience metadata rather than themes.
TAG_EXCLUDED_NAMESPACES = frozenset(
    {
        "Sexual Content",
        "Work Info",
        "Derivative Work",
        "Audience Demographics",
    },
)
# Excluded anywhere in the path, not just as the leading segment. "Sex Slave"
# sits under "Character Types > Victims", so a namespace-only rule lets it
# through.
TAG_EXCLUDED_SEGMENTS = frozenset({"Victims"})
# Relevance gate on how many series carry the tag. Below ~1000 a tag is shared
# by too few works to describe one, but going higher strips the flavour that
# makes these worth showing at all: at 2000 the Campfire Cooking entry collapses
# to 10 generic tags and loses Travel, Elves and Dragons entirely.
TAG_MIN_SERIES_COUNT = 1000
# MangaBaka rejects the default python-requests User-Agent with 403.
headers = {
    "User-Agent": "Mozilla/5.0",
}


def metadata_cache_key(media_id):
    """Return the versioned metadata cache key for a MangaBaka series."""
    return (
        f"{Sources.MANGABAKA.value}_{MediaTypes.MANGA.value}_"
        f"{METADATA_CACHE_VERSION}_{media_id}"
    )


def metadata_cache_keys(media_id):
    """Return the versioned MangaBaka cache keys for an item.

    Mirrors tmdb/tvdb so cache invalidation reaches versioned entries rather
    than only the legacy unversioned shape.
    """
    return [metadata_cache_key(media_id)]


def search(query, page):
    """Search for manga on MangaBaka."""
    cache_key = (
        f"search_{SEARCH_CACHE_VERSION}_{Sources.MANGABAKA.value}_"
        f"{MediaTypes.MANGA.value}_{query}_{page}"
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

        if not settings.MU_NSFW:
            # MangaBaka's content_rating is an exact-match server filter, and
            # repeated params OR together (a comma-joined value 400s). Adult
            # tiers are erotica/pornographic; "suggestive" is the mild tier that
            # holds most mainstream seinen (Ghost in the Shell, Overlord), so
            # filtering it out hides titles every other provider here shows.
            # MU_NSFW covers both manga providers, so one switch lifts both.
            params["content_rating"] = ["safe", "suggestive"]

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
    cache_key = metadata_cache_key(media_id)
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
                "themes": get_tags(series),
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


def get_tags(series):
    """Curate series tags_v2 into display-ready theme names.

    Keeps tags that carry real signal, drops those that are genre duplicates
    (already shown by get_genres), plot spoilers, sexual content, or
    publication metadata, and orders by how many series share the tag so the
    most descriptive appear first. Returns [] when nothing qualifies.
    """
    tags = series.get("tags_v2") or []

    def is_theme(tag):
        if not isinstance(tag, dict):
            return False
        if tag.get("is_genre") or tag.get("is_spoiler"):
            return False
        segments = [part.strip() for part in (tag.get("name_path") or "").split(" > ")]
        if not segments or not segments[0]:
            return False
        if segments[0] in TAG_EXCLUDED_NAMESPACES:
            return False
        if TAG_EXCLUDED_SEGMENTS.intersection(segments):
            return False
        return (tag.get("series_count") or 0) >= TAG_MIN_SERIES_COUNT

    themes = [tag for tag in tags if is_theme(tag)]
    themes.sort(key=lambda tag: tag.get("series_count") or 0, reverse=True)
    return [
        tag["name"]
        for tag in themes
        if isinstance(tag.get("name"), str) and tag["name"].strip()
    ]


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
        "series",
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
