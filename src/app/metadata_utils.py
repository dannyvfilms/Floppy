"""Helpers for persisting normalized provider metadata on Items."""

from __future__ import annotations

from app import helpers
from app.discover.feature_metadata import normalize_certification
from app.models import MediaTypes, Sources

ANIME_SUPPLEMENT_GENRE = "Anime"


def provider_metadata_cache_keys(
    source,
    media_type,
    media_id,
    season_number=None,
    episode_number=None,
    route_media_type=None,
    language=None,
):
    """Return the provider cache keys holding a payload, canonical key first.

    Callers that refresh metadata used to hand-build `source_mediatype_mediaid`.
    That shape stopped matching once the TMDB movie and season keys gained a
    strategy version, so a refresh would read a TTL of None, delete nothing, and
    then be served the very payload it meant to replace (issue #1066). Building
    the keys here - through the providers' own helpers - keeps every refresh
    path honest as versions move.
    """
    keys = []
    if source == Sources.TMDB.value:
        from app.providers import tmdb

        keys.extend(
            tmdb.metadata_cache_keys(
                media_id,
                media_type,
                season_number=season_number,
                episode_number=episode_number,
            ),
        )
    elif source == Sources.TVDB.value:
        from app.providers import tvdb

        # TVDB routes anime separately from TV, and a grouped-anime route
        # persists as `tv`, so the canonical key follows the route the request
        # came in on rather than the tracking type it is stored under.
        routed_media_type = (
            MediaTypes.ANIME.value
            if (route_media_type or media_type) == MediaTypes.ANIME.value
            else MediaTypes.TV.value
        )
        if media_type == MediaTypes.SEASON.value:
            keys.append(
                tvdb._season_cache_key(
                    media_id,
                    season_number,
                    routed_media_type,
                    language,
                ),
            )
        else:
            keys.append(
                tvdb._cache_key(
                    routed_media_type,
                    media_id,
                    tvdb._preferred_language_code(language),
                ),
            )
        keys.extend(
            tvdb.metadata_cache_keys(
                media_id,
                season_number,
                language=language,
            ),
        )

    if source != Sources.TVDB.value:
        # The unversioned shape. Still worth evicting for TMDB, where entries
        # written before the movie key gained a version are sitting in the cache
        # under it; and it is the only key a provider without a helper uses.
        # TVDB's keys have always been versioned and its helper is exhaustive.
        legacy_key = f"{source}_{media_type}_{media_id}"
        if media_type == MediaTypes.SEASON.value and season_number is not None:
            legacy_key += f"_{season_number}"
        keys.append(legacy_key)

    deduped = []
    for key in keys:
        if key and key not in deduped:
            deduped.append(key)
    return deduped

CORE_METADATA_FIELDS = [
    "synopsis",
    "source_url",
    "country",
    "languages",
    "platforms",
    "format",
    "status",
    "studios",
    "themes",
    "authors",
    "number_of_pages",
    "publishers",
    "isbn",
    "source_material",
    "creators",
    "runtime",
]

PROVIDER_METADATA_FIELDS = [
    "provider_popularity",
    "provider_rating",
    "provider_rating_count",
    "provider_keywords",
    "provider_certification",
    "provider_collection_id",
    "provider_collection_name",
    "igdb_user_rating",
    "igdb_user_rating_count",
]


def backfill_sources(sources):
    """Drop providers with no instance credential from a backfill source list.

    Hardcover meters its free tier per account and ships no default token, so
    background jobs must not queue work for it on an unconfigured instance
    (#1025). Resolved per call, not at import, so adding HARDCOVER_API and
    restarting takes effect without a code change.
    """
    from app.providers import hardcover

    if hardcover.enabled():
        return tuple(sources)
    return tuple(source for source in sources if source != Sources.HARDCOVER.value)


def _coerce_list(value, *, allow_scalar: bool = True) -> list:
    if isinstance(value, list):
        return value
    if allow_scalar and value:
        return [value]
    return []


def normalize_genres(value) -> list[str]:
    """Normalize a provider or model genre payload into unique strings."""
    from app.statistics import _coerce_genre_list

    genres = _coerce_genre_list(value)
    return list(dict.fromkeys([str(genre) for genre in genres if genre]))


def genre_list_has_name(genres, name: str) -> bool:
    """Return whether a genre list contains the named genre, case-insensitively."""
    target = str(name or "").strip().lower()
    if not target:
        return False
    return any(
        str(genre).strip().lower() == target for genre in normalize_genres(genres)
    )


def extract_metadata_genres(metadata: dict | None) -> list[str]:
    """Return normalized genres from provider metadata."""
    if not isinstance(metadata, dict):
        return []
    details = metadata.get("details")
    genres_raw = []
    if isinstance(details, dict):
        genres_raw = details.get("genres") or details.get("genre") or []
    if not genres_raw:
        genres_raw = metadata.get("genres") or metadata.get("genre") or []
    return normalize_genres(genres_raw)


def merge_persisted_genres(
    *,
    source: str,
    media_type: str,
    incoming_genres,
    existing_genres=None,
    add_anime: bool = False,
) -> list[str]:
    """Return the stored genre list for an item after source-driven updates."""
    merged = normalize_genres(incoming_genres)
    existing = normalize_genres(existing_genres)

    if (
        (source == Sources.TMDB.value and media_type == MediaTypes.TV.value)
        and (add_anime or genre_list_has_name(existing, ANIME_SUPPLEMENT_GENRE))
    ) and not genre_list_has_name(merged, ANIME_SUPPLEMENT_GENRE):
        merged.append(ANIME_SUPPLEMENT_GENRE)

    return merged


def apply_item_genres(
    item,
    incoming_genres,
    *,
    add_anime: bool = False,
) -> list[str]:
    """Apply merged genres to an item and return changed fields."""
    merged = merge_persisted_genres(
        source=item.source,
        media_type=item.media_type,
        incoming_genres=incoming_genres,
        existing_genres=item.genres,
        add_anime=add_anime,
    )
    current = normalize_genres(item.genres)
    if current != merged:
        item.genres = merged
        return ["genres"]
    return []


def extract_item_metadata_values(metadata: dict | None) -> dict[str, object]:
    """Return normalized metadata values used on the Item model."""
    payload = metadata if isinstance(metadata, dict) else {}
    details = payload.get("details") or {}
    if not isinstance(details, dict):
        details = {}

    authors = details.get("authors") or details.get("author") or []
    if isinstance(authors, str):
        authors = [authors] if authors else []
    elif not isinstance(authors, list):
        authors = []

    publishers = details.get("publishers") or details.get("publisher") or ""
    if isinstance(publishers, list):
        publishers = publishers[0] if publishers else ""

    raw_number_of_pages = payload.get("max_progress") or details.get("number_of_pages")
    try:
        number_of_pages = (
            int(raw_number_of_pages) if raw_number_of_pages is not None else None
        )
    except (TypeError, ValueError):
        number_of_pages = None

    return {
        "synopsis": payload.get("synopsis") or "",
        "source_url": payload.get("source_url") or "",
        "country": details.get("country") or "",
        "languages": _coerce_list(details.get("languages")),
        "platforms": _coerce_list(details.get("platforms"), allow_scalar=False),
        "format": details.get("format") or "",
        "status": details.get("status") or "",
        "studios": _coerce_list(details.get("studios"), allow_scalar=False),
        "themes": _coerce_list(details.get("themes"), allow_scalar=False),
        "authors": authors,
        "number_of_pages": number_of_pages,
        "publishers": publishers,
        "isbn": _coerce_list(details.get("isbn"), allow_scalar=False),
        "source_material": details.get("source") or "",
        "creators": _coerce_list(details.get("people"), allow_scalar=False),
        "runtime": details.get("runtime") or "",
        "provider_popularity": payload.get("provider_popularity"),
        "provider_rating": payload.get("provider_rating", payload.get("score")),
        "provider_rating_count": payload.get(
            "provider_rating_count",
            payload.get("score_count"),
        ),
        "provider_keywords": _coerce_list(
            payload.get("provider_keywords"),
            allow_scalar=False,
        ),
        "provider_certification": normalize_certification(
            payload.get("provider_certification") or details.get("certification") or "",
        ),
        "provider_collection_id": str(
            payload.get("provider_collection_id") or ""
        ).strip(),
        "provider_collection_name": str(
            payload.get("provider_collection_name") or ""
        ).strip(),
        "igdb_user_rating": payload.get("igdb_user_rating"),
        "igdb_user_rating_count": payload.get("igdb_user_rating_count"),
        "release_datetime": helpers.extract_release_datetime(payload),
    }


def apply_item_metadata(
    item,
    metadata: dict | None,
    *,
    include_core: bool = True,
    include_provider: bool = True,
    include_release: bool = True,
) -> list[str]:
    """Apply selected metadata fields to an item and return changed fields."""
    values = extract_item_metadata_values(metadata)
    update_fields: list[str] = []
    for field_name in CORE_METADATA_FIELDS:
        if not include_core:
            break
        # Only book payloads carry a page count, so an absent one means "not
        # provided", not "cleared" — nulling it wipes a stored comic/manga
        # progress denominator on every sync (#1077).
        if field_name == "number_of_pages" and values[field_name] is None:
            continue
        if getattr(item, field_name) != values[field_name]:
            setattr(item, field_name, values[field_name])
            update_fields.append(field_name)

    if include_provider:
        for field_name in PROVIDER_METADATA_FIELDS:
            if getattr(item, field_name) != values[field_name]:
                setattr(item, field_name, values[field_name])
                update_fields.append(field_name)

    if (
        include_release
        and values["release_datetime"]
        and item.release_datetime != values["release_datetime"]
        and item.media_type != MediaTypes.SEASON.value
    ):
        item.release_datetime = values["release_datetime"]
        update_fields.append("release_datetime")

    return update_fields
