import itertools
import logging
import re

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
SEARCH_CACHE_VERSION = "v3"
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
# The tiers shown when MU_NSFW is off.
#
# "erotica" is included deliberately, even though the name reads like the
# explicit tier. It is MangaBaka's catch-all for anything tagged as having
# sexual content rather than a measure of how explicit a work is, so it holds
# mainstream seinen alongside genuine erotica: BERSERK (id 1692, nsfw:erotica),
# Vagabond and Homunculus all sit in it. Excluding it hid BERSERK from a search
# for "Berserk" entirely -- the unfiltered result is rank 1 of 60 -- which is
# the same class of bug as the earlier "suggestive" exclusion that hid Overlord
# and Ghost in the Shell.
#
# The genuinely explicit tier is "pornographic", and it is always excluded here.
# The residual erotica-tier doujinshi are removed by TAG/content heuristic
# below, since the API has no server-side genre exclusion (passing an unknown
# filter key 400s rather than being ignored).
DEFAULT_CONTENT_RATINGS = ["safe", "suggestive", "erotica"]
# Genres that mark a work as fan-made or explicit on their own.
#
# "adult" and "ecchi" are deliberately absent: MangaBaka applies "adult" to
# mainstream titles too -- "Berserk: The Flame Dragon Knight" (suggestive) and
# "Tantei Akechi wa Kyouransu" (a mystery) both carry it -- so treating it as a
# porn signal would hide ordinary series.
EXPLICIT_EXCLUDED_GENRES = frozenset({"doujinshi", "hentai", "smut"})


def _is_explicit(row):
    """Return whether a search/similar row is fan-made or explicit by genre."""
    genres = row.get("genres") or []
    return bool(EXPLICIT_EXCLUDED_GENRES.intersection(genres))


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
            # repeated params OR together (a comma-joined value 400s).
            # MU_NSFW covers both manga providers, so one switch lifts both.
            params["content_rating"] = list(DEFAULT_CONTENT_RATINGS)

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

        rows = response["data"]
        if not settings.MU_NSFW:
            rows = [item for item in rows if not _is_explicit(item)]

        results = [
            {
                "media_id": str(item["id"]),
                "source": Sources.MANGABAKA.value,
                "media_type": MediaTypes.MANGA.value,
                "title": item["title"],
                "image": get_image_url(item, thumbnail=True),
                "year": item.get("year"),
            }
            for item in rows
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
        related_manga = get_related(series.get("relationships_v2"))

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
                "related_manga": related_manga,
                # Excludes anything already in related_manga: /similar counts
                # official relations as strong matches and returns them too.
                "recommendations": get_recommendations(
                    media_id,
                    exclude_ids=[row["media_id"] for row in related_manga],
                ),
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


def get_recommendations(media_id, *, exclude_ids=None):
    """Return tag-similar series, ranked by MangaBaka's similarity score.

    `/similar` returns fully populated series objects, so unlike the
    MangaUpdates path this needs no per-item follow-up fetches.
    """
    params = {}
    if not settings.MU_NSFW:
        # Same tiers as search, including erotica for the same reason: the
        # mainstream seinen live there, and the residual explicit doujinshi are
        # dropped by the genre check below instead.
        params["content_rating"] = list(DEFAULT_CONTENT_RATINGS)

    try:
        response = services.api_request(
            Sources.MANGABAKA.value,
            "GET",
            f"{base_url}/series/{media_id}/similar",
            params=params or None,
            headers=headers,
        )
    except requests.exceptions.HTTPError:
        logger.warning("Failed to fetch MangaBaka similar series for %s", media_id)
        return []

    excluded = {str(value) for value in (exclude_ids or ())}
    ranked = []
    for row in response.get("data") or []:
        series = row.get("series") or {}
        series_id = series.get("id")
        if series_id is None:
            continue
        # A series can be both officially related and tag-similar. It already
        # appears in the related grid, so drop it here rather than render the
        # same title twice on one page.
        if str(series_id) in excluded:
            continue
        if not settings.MU_NSFW and _is_explicit(series):
            continue
        ranked.append(
            (
                row.get("score") or 0,
                {
                    "source": Sources.MANGABAKA.value,
                    "media_id": str(series_id),
                    "media_type": MediaTypes.MANGA.value,
                    "title": series.get("title", ""),
                    "image": get_image_url(series, thumbnail=True),
                    "year": series.get("year"),
                },
            ),
        )

    # The API's own ordering is not by score (related series lead instead), so
    # sort explicitly to keep the most similar first.
    ranked.sort(key=lambda entry: entry[0], reverse=True)
    return [item for _, item in ranked]


def _parse_int(value):
    """Parse numeric-string counts like total_chapters/final_volume."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# MangaBaka stores a single person under several romanizations of their name
# and credits whichever spelling each series happened to use. Kentaro Miura is
# credited as both "MIURA Kentaro" (4 series) and "Kentarou Miura" (11 series),
# with no overlap between the two result sets -- so querying the credited
# spelling alone returns a bibliography missing most of the author's work.
# Kouji Mori splits 23 vs 17 the same way.
#
# The API cannot be asked for a canonical person: there is no /authors endpoint
# (it 404s), `staff` is the only author filter, and it is an exact string match
# against the credited name. Searching a bare surname is not an alternative --
# "MORI" alone matches 5123 series -- so the workable approach is to query each
# plausible romanization of the credited name and merge the results.
_LONG_VOWEL_PAIRS = (("ou", "o"), ("uu", "u"), ("oo", "o"))
# A single-token name has no order or pairing to vary.
MIN_NAME_TOKENS = 2
# Long-vowel expansion is applied without a dictionary, so it also yields forms
# no one uses ("MORI" -> "MouRI"). Those simply match nothing, but they cost a
# request each, so the fan-out is capped. Two tokens produce 4-8 useful forms.
MAX_NAME_VARIANTS = 12
# The API accepts up to 100 per page (it 400s on some larger values).
PAGE_SIZE = 100
# A prolific author needs several pages: "Gou Nagai" reports 189 series.
MAX_BIBLIOGRAPHY_PAGES = 6


def _romanization_forms(token):
    """Return a name token under both long and short vowel renderings."""
    forms = {token}
    lowered = token.lower()
    for long_form, short_form in _LONG_VOWEL_PAIRS:
        if long_form in lowered:
            forms.add(re.sub(long_form, short_form, token, flags=re.IGNORECASE))
    # Expansion applies only to a lone o/u sitting after a consonant and not
    # followed by another vowel, which is the Japanese long-vowel position.
    # "Koji" -> "Kouji" and "Kentaro" -> "Kentarou" qualify; the "u" in "MIURA"
    # does not, because it follows a vowel. Testing for a trailing consonant
    # instead of "not a vowel" missed "Koji" entirely.
    for short_form, long_form in (("o", "ou"), ("u", "uu")):
        if re.search(rf"[bcdfghjklmnpqrstvwxyz]{short_form}(?![aeiou])", lowered):
            forms.add(
                re.sub(
                    rf"([bcdfghjklmnpqrstvwxyz]){short_form}(?![aeiou])",
                    rf"\1{long_form}",
                    token,
                    flags=re.IGNORECASE,
                ),
            )
    return forms


def _normalized_token(token):
    """Fold a name token to a romanization-independent form.

    Comparing raw tokens rejected the variants this module deliberately
    queries: "Kentarou Miura" would never match a search for "MIURA Kentaro",
    so the profile silently dropped every series credited under the spelling
    it had just looked up.
    """
    folded = token.lower()
    for long_form, short_form in _LONG_VOWEL_PAIRS:
        folded = folded.replace(long_form, short_form)
    return folded


def author_name_variants(name):
    """Return the plausible spellings MangaBaka may have credited this name under."""
    tokens = (name or "").split()
    if len(tokens) < MIN_NAME_TOKENS:
        return [name] if name else []
    variants = set()
    for ordered in (tokens, list(reversed(tokens))):
        for combination in itertools.product(
            *[_romanization_forms(token) for token in ordered],
        ):
            variants.add(" ".join(combination))
    return sorted(variants)[:MAX_NAME_VARIANTS]


def _collect_bibliography(rows, wanted, seen_ids, bibliography):
    """Append genuinely-credited series from one page of results.

    `staff` matches on the credited string, but the same surname can belong to
    different people: a lookup for "MORI Kouji" returns 23 rows of which only 9
    credit him, the rest being anthologies listing unrelated names. Confirm the
    entry credits a name made of the same tokens before listing it.
    """
    for series in rows:
        series_id = series.get("id")
        if series_id is None or series_id in seen_ids:
            continue

        credited = [
            value
            for value in (series.get("authors") or []) + (series.get("artists") or [])
            if isinstance(value, str)
        ]
        if not any(
            {_normalized_token(token) for token in value.split()} == wanted
            for value in credited
        ):
            continue

        title = series.get("title")
        if not title:
            continue

        seen_ids.add(series_id)
        bibliography.append(
            {
                "media_id": str(series_id),
                "source": Sources.MANGABAKA.value,
                "media_type": MediaTypes.MANGA.value,
                "title": title,
                "image": get_image_url(series, thumbnail=True),
                "year": series.get("year"),
                "sort_order": len(bibliography),
            },
        )


def author_profile(person_id):
    """Return a MangaBaka author profile with a merged bibliography.

    `person_id` is the credited name, since MangaBaka authors are plain strings
    with no numeric identifier to key on.
    """
    cache_key = f"{Sources.MANGABAKA.value}_person_{person_id}"
    data = cache.get(cache_key)
    if data is not None:
        return data

    wanted = {_normalized_token(token) for token in (person_id or "").split()}
    bibliography = []
    seen_ids = set()

    for variant in author_name_variants(person_id):
        url = f"{base_url}/series/search"

        # A prolific author overflows one page: "Gou Nagai" reports 189 series,
        # so fetching page 1 alone silently dropped 86 works that genuinely
        # credit him. Walk the pages until the API stops offering a next one.
        for page in range(1, MAX_BIBLIOGRAPHY_PAGES + 1):
            params = {"staff": variant, "limit": PAGE_SIZE, "page": page}
            if not settings.MU_NSFW:
                params["content_rating"] = list(DEFAULT_CONTENT_RATINGS)

            try:
                response = services.api_request(
                    Sources.MANGABAKA.value,
                    "GET",
                    url,
                    params=params,
                    headers=headers,
                )
            except requests.exceptions.HTTPError:
                logger.warning(
                    "Failed to fetch MangaBaka bibliography for %s page %s",
                    variant,
                    page,
                )
                break

            rows = response.get("data") or []
            if not rows:
                break

            _collect_bibliography(rows, wanted, seen_ids, bibliography)

            if not (response.get("pagination") or {}).get("next"):
                break

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
