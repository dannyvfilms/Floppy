import itertools
import logging
import re

import requests
from django.conf import settings
from django.core.cache import cache

from app import helpers, request_timing
from app.models import MediaTypes, Sources
from app.providers import services

logger = logging.getLogger(__name__)

base_url = "https://api.mangabaka.org/v1"
# MangaBaka answers the default python-requests User-Agent with a 403.
HEADERS = {"User-Agent": "Mozilla/5.0"}
PER_PAGE = 30
# Bumped when the search filters or result shape change, so pages cached under
# the old rules are not served (same reason as IGDB's).
SEARCH_CACHE_VERSION = "v2"
# Light novels live in the same database; Floppy has no novel media type.
EXCLUDED_TYPES = ("novel",)
# The tiers shown while MANGABAKA_NSFW is off. "erotica" stays in: it is
# MangaBaka's catch-all for any sexual content, so it holds mainstream seinen
# such as Berserk and Vagabond, and excluding it hid Berserk from its own
# search. Only "pornographic" is the explicit tier. The filter is a repeated
# `content_rating` key (a comma-joined value 400s).
DEFAULT_CONTENT_RATINGS = ("safe", "suggestive", "erotica")
# The API has no server-side genre exclusion, so the fan-made and explicit
# works left in the erotica tier are dropped from the rows. "adult" and "ecchi"
# are deliberately absent: MangaBaka puts "adult" on ordinary mysteries too.
EXPLICIT_GENRES = frozenset({"doujinshi", "hentai", "smut"})
# Related series cost one request each, against a 30-a-minute budget.
MAX_RELATED = 8
OFFICIAL_RELATION_TYPES = frozenset(
    {"main", "side_story", "sequel", "prequel", "source", "spin_off", "series"},
)
# `tags_v2` is unusable raw (Berserk carries 306). `weight`, `level`,
# `content_rating` and `is_explicit` are all unreliable (Child Abuse, Sexual
# Abuse and Vore are rated "safe"), so the leading segment of `name_path` is
# the signal: "Sexual Content" is the only namespace with explicit labels, and
# the rest are publication or audience metadata rather than themes. "Sex Slave"
# sits under "Victims", so that is excluded anywhere in the path.
TAG_EXCLUDED_NAMESPACES = frozenset(
    {"Sexual Content", "Work Info", "Derivative Work", "Audience Demographics"},
)
TAG_EXCLUDED_SEGMENTS = frozenset({"Victims"})
# Tags shared by fewer series describe too little to show.
TAG_MIN_SERIES_COUNT = 1000


def handle_error(error):
    """Handle MangaBaka API errors."""
    raise services.ProviderAPIError(Sources.MANGABAKA.value, error)


def search(query, page):
    """Search for manga, manhwa and manhua on MangaBaka."""
    if not query.strip():
        return helpers.format_search_response(page, PER_PAGE, 0, [])

    # The NSFW flag changes the result set server-side, so it belongs in the
    # key: without it, flipping MANGABAKA_NSFW keeps serving the other mode's
    # cached page for the full cache lifetime.
    cache_key = (
        f"search_{SEARCH_CACHE_VERSION}_{Sources.MANGABAKA.value}_"
        f"{MediaTypes.MANGA.value}_nsfw_{settings.MANGABAKA_NSFW}_{query}_{page}"
    )
    data = cache.get(cache_key)

    if data is None:
        params = {"q": query, "page": page, "limit": PER_PAGE}
        if not settings.MANGABAKA_NSFW:
            params["content_rating"] = list(DEFAULT_CONTENT_RATINGS)

        try:
            response = services.api_request(
                Sources.MANGABAKA.value,
                "GET",
                f"{base_url}/series/search",
                params=params,
                headers=HEADERS,
            )
        except requests.exceptions.HTTPError as error:
            handle_error(error)

        results = [
            {
                "media_id": str(series["id"]),
                "source": Sources.MANGABAKA.value,
                "media_type": MediaTypes.MANGA.value,
                "title": series["title"],
                "image": get_image_url(series, thumbnail=True),
                "year": get_start_year(series),
            }
            for series in response["data"]
            if is_listable(series)
        ]

        data = helpers.format_search_response(
            page,
            PER_PAGE,
            response["pagination"]["count"],
            results,
        )

        cache.set(cache_key, data)

    return data


@request_timing.timed_provider_call
def manga(media_id):
    """Get metadata for a manga from MangaBaka."""
    cache_key = f"{Sources.MANGABAKA.value}_{MediaTypes.MANGA.value}_{media_id}"
    data = cache.get(cache_key)

    if data is None:
        try:
            response = services.api_request(
                Sources.MANGABAKA.value,
                "GET",
                f"{base_url}/series/{media_id}",
                headers=HEADERS,
            )
        except requests.exceptions.HTTPError as error:
            handle_error(error)

        series = response["data"]
        published = series.get("published") or {}
        related_manga = get_related(series.get("relationships_v2"))

        data = {
            "media_id": media_id,
            "source": Sources.MANGABAKA.value,
            "source_url": series["canonical_url"],
            "media_type": MediaTypes.MANGA.value,
            "title": series["title"],
            "image": get_image_url(series),
            "synopsis": series.get("description") or "No synopsis available.",
            "max_progress": get_max_progress(series),
            "genres": get_genres(series),
            "score": get_score(series),
            "score_count": None,
            "details": {
                "format": (series.get("type") or "").title() or None,
                "start_date": published.get("start_date"),
                "end_date": published.get("end_date"),
                "status": (series.get("status") or "").title() or None,
                "authors": series.get("authors") or None,
                "artists": series.get("artists") or None,
                "tags": get_tags(series),
                "content_rating": (series.get("content_rating") or "").title() or None,
            },
            "authors_full": get_authors_full(series),
            "related": {
                "related_manga": related_manga,
                # /similar also returns official relations, so drop those.
                "recommendations": get_recommendations(
                    media_id,
                    exclude_ids=[row["media_id"] for row in related_manga],
                ),
            },
        }

        cache.set(cache_key, data)

    return data


def is_explicit(series):
    """Return whether a series is fan-made or explicit by genre."""
    return bool(EXPLICIT_GENRES.intersection(series.get("genres") or []))


def is_listable(series):
    """Return whether a search or similar row passes the shared filters."""
    if series.get("type") in EXCLUDED_TYPES:
        return False
    return settings.MANGABAKA_NSFW or not is_explicit(series)


def is_searchable(metadata):
    """Return whether a series passes the same filters as the search results."""
    details = metadata["details"]
    if (details["format"] or "").lower() in EXCLUDED_TYPES:
        return False
    if settings.MANGABAKA_NSFW:
        return True
    rating = (details["content_rating"] or "").lower()
    genres = {genre.lower() for genre in metadata["genres"] or []}
    return rating != "pornographic" and not EXPLICIT_GENRES & genres


def get_image_url(series, *, thumbnail=False):
    """Get the cover URL: full resolution for a series page, x350 for grids."""
    cover = series.get("cover") or {}
    raw_url = (cover.get("raw") or {}).get("url")
    if not thumbnail and raw_url:
        return raw_url
    url = (cover.get("x350") or {}).get("x1") or raw_url
    return url or settings.IMG_NONE


def get_start_year(series):
    """Get the year publication began."""
    start_date = (series.get("published") or {}).get("start_date")
    if start_date:
        return int(start_date[:4])
    return series.get("year")


def get_max_progress(series):
    """Get the chapter count once the series is complete."""
    total = series.get("total_chapters")
    if series.get("status") == "completed" and total and str(total).isdigit():
        return int(total)
    return None


def get_genres(series):
    """Return the readable genres for the series."""
    genres = [genre.replace("_", " ").title() for genre in series.get("genres") or []]
    return genres or None


def get_tags(series):
    """Return the tags that describe the series, most widely shared first."""

    def is_theme(tag):
        segments = [part.strip() for part in (tag.get("name_path") or "").split(" > ")]
        return (
            bool(segments[0])
            and not tag.get("is_genre")
            and not tag.get("is_spoiler")
            and segments[0] not in TAG_EXCLUDED_NAMESPACES
            and not TAG_EXCLUDED_SEGMENTS.intersection(segments)
            and (tag.get("series_count") or 0) >= TAG_MIN_SERIES_COUNT
        )

    tags = [tag for tag in series.get("tags_v2") or [] if is_theme(tag)]
    tags.sort(key=lambda tag: tag["series_count"], reverse=True)
    return [tag["name"] for tag in tags] or None


def get_score(series):
    """Return the 0-100 MangaBaka rating on Floppy's 0-10 scale."""
    rating = series.get("rating")
    if rating:
        return round(rating / 10, 1)
    return None


def get_authors_full(series):
    """Return the credited people. MangaBaka has no ids, so the name is the id."""
    entries = [(name, "Author") for name in series.get("authors") or []]
    entries += [(name, "Artist") for name in series.get("artists") or []]

    people = []
    seen = set()
    for raw_name, role in entries:
        name = (raw_name or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        people.append(
            {
                "person_id": name,
                "name": name,
                "image": settings.IMG_NONE,
                "role": role,
                "sort_order": len(people),
            },
        )
    return people


def get_related(relationships):
    """Return official related series, with titles resolved from the API."""
    related = []
    for relation in relationships or []:
        if len(related) >= MAX_RELATED:
            break
        related_id = relation.get("to_series_id")
        if relation.get("relation_type") not in OFFICIAL_RELATION_TYPES or not related_id:
            continue
        try:
            response = services.api_request(
                Sources.MANGABAKA.value,
                "GET",
                f"{base_url}/series/{related_id}",
                headers=HEADERS,
            )
        except requests.exceptions.HTTPError:
            logger.warning("Failed to fetch related MangaBaka series %s", related_id)
            continue
        series = response["data"]
        related.append(
            {
                "source": Sources.MANGABAKA.value,
                "media_id": str(series["id"]),
                "media_type": MediaTypes.MANGA.value,
                "title": series.get("title", ""),
                "image": get_image_url(series, thumbnail=True),
                "year": get_start_year(series),
                "relation_type": relation["relation_type"],
            },
        )
    return related


def get_recommendations(media_id, *, exclude_ids=()):
    """Return tag-similar series, most similar first."""
    params = {}
    if not settings.MANGABAKA_NSFW:
        params["content_rating"] = list(DEFAULT_CONTENT_RATINGS)

    try:
        response = services.api_request(
            Sources.MANGABAKA.value,
            "GET",
            f"{base_url}/series/{media_id}/similar",
            params=params or None,
            headers=HEADERS,
        )
    except requests.exceptions.HTTPError:
        logger.warning("Failed to fetch MangaBaka similar series for %s", media_id)
        return []

    excluded = {str(value) for value in exclude_ids}
    # The API's own order is not by score (official relations lead it).
    rows = sorted(
        response.get("data") or [],
        key=lambda row: row.get("score") or 0,
        reverse=True,
    )
    return [
        {
            "source": Sources.MANGABAKA.value,
            "media_id": str(row["series"]["id"]),
            "media_type": MediaTypes.MANGA.value,
            "title": row["series"].get("title", ""),
            "image": get_image_url(row["series"], thumbnail=True),
            "year": get_start_year(row["series"]),
        }
        for row in rows
        if row.get("series")
        and str(row["series"].get("id")) not in excluded
        and is_listable(row["series"])
    ]


# MangaBaka credits one person under several romanizations and splits their
# series between them with no overlap ("MIURA Kentaro" 4 series, "Kentarou
# Miura" 11). There is no /authors endpoint and `staff` is an exact match on
# the credited string, so a bibliography queries each plausible spelling and
# merges the results.
_LONG_VOWEL_PAIRS = (("ou", "o"), ("uu", "u"), ("oo", "o"))
MIN_NAME_TOKENS = 2
# Every request counts against the 30-a-minute budget and the limiter makes the
# page wait for a free slot, so the fan-out is capped.
MAX_NAME_VARIANTS = 6
MAX_BIBLIOGRAPHY_REQUESTS = 8
BIBLIOGRAPHY_PAGE_SIZE = 100
_CONSONANT_VOWEL = r"([bcdfghjklmnpqrstvwxyz])({short})(?![aeiou])"


def _normalized_token(token):
    """Fold a name token to a form shared by every romanization of it."""
    folded = token.lower()
    for long_form, short_form in _LONG_VOWEL_PAIRS:
        folded = folded.replace(long_form, short_form)
    return folded


def _romanization_forms(token):
    """Return a name token under its long and short vowel renderings."""
    forms = {token}
    lowered = token.lower()
    for long_form, short_form in _LONG_VOWEL_PAIRS:
        if long_form in lowered:
            forms.add(re.sub(long_form, short_form, token, flags=re.IGNORECASE))
    # A lone o/u after a consonant is where Japanese long vowels hide:
    # "Koji" -> "Kouji", "Kentaro" -> "Kentarou".
    for short_form, long_form in (("o", "ou"), ("u", "uu")):
        pattern = _CONSONANT_VOWEL.format(short=short_form)
        if re.search(pattern, lowered):
            forms.add(re.sub(pattern, rf"\1{long_form}", token, flags=re.IGNORECASE))
    return forms


def author_name_variants(name):
    """Return the credited name first, then its likely alternate spellings."""
    tokens = (name or "").split()
    if len(tokens) < MIN_NAME_TOKENS:
        return [name] if name else []
    variants = set()
    for ordered in (tokens, tokens[::-1]):
        for combination in itertools.product(*map(_romanization_forms, ordered)):
            variants.add(" ".join(combination))
    variants.discard(name)
    return [name, *sorted(variants)][:MAX_NAME_VARIANTS]


def author_profile(person_id):
    """Return a MangaBaka author profile with a merged bibliography.

    `person_id` is the credited name, since MangaBaka authors have no id.
    """
    cache_key = f"{Sources.MANGABAKA.value}_person_{person_id}"
    data = cache.get(cache_key)
    if data is not None:
        return data

    wanted = {_normalized_token(token) for token in (person_id or "").split()}
    bibliography = []
    seen_ids = set()
    requests_left = MAX_BIBLIOGRAPHY_REQUESTS

    for variant in author_name_variants(person_id):
        page = 1
        while requests_left > 0:
            requests_left -= 1
            params = {"staff": variant, "limit": BIBLIOGRAPHY_PAGE_SIZE, "page": page}
            if not settings.MANGABAKA_NSFW:
                params["content_rating"] = list(DEFAULT_CONTENT_RATINGS)
            try:
                response = services.api_request(
                    Sources.MANGABAKA.value,
                    "GET",
                    f"{base_url}/series/search",
                    params=params,
                    headers=HEADERS,
                )
            except requests.exceptions.HTTPError:
                logger.warning(
                    "Failed to fetch MangaBaka bibliography for %s page %s",
                    variant,
                    page,
                )
                break

            for series in response.get("data") or []:
                if series["id"] in seen_ids or not is_listable(series):
                    continue
                # `staff` matches the credited string, so an anthology listing
                # unrelated names can come back: keep series that credit this
                # person under a spelling with the same tokens.
                credited = (series.get("authors") or []) + (series.get("artists") or [])
                if not any(
                    {_normalized_token(token) for token in name.split()} == wanted
                    for name in credited
                ):
                    continue
                seen_ids.add(series["id"])
                bibliography.append(
                    {
                        "media_id": str(series["id"]),
                        "source": Sources.MANGABAKA.value,
                        "media_type": MediaTypes.MANGA.value,
                        "title": series["title"],
                        "image": get_image_url(series, thumbnail=True),
                        "year": get_start_year(series),
                        "sort_order": len(bibliography),
                    },
                )

            if not (response.get("pagination") or {}).get("next"):
                break
            page += 1

    data = {
        "person_id": str(person_id),
        "source": Sources.MANGABAKA.value,
        "name": person_id or "",
        # MangaBaka does not publish author images.
        "image": settings.IMG_NONE,
        "biography": "",
        "known_for_department": "Author",
        "birth_date": None,
        "death_date": None,
        "place_of_birth": "",
        "bibliography": bibliography,
    }
    cache.set(cache_key, data)
    return data
