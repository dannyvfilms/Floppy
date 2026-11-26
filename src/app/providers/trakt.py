"""Raw Trakt API helpers used for persisted popularity enrichment."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.cache import cache

from app.models import MediaTypes, Sources
from app.providers import credentials, services

TRAKT_BASE_URL = "https://api.trakt.tv"
TRAKT_API_PROVIDER = "TRAKT"
TRAKT_API_VERSION = "2"
RELATED_RECOMMENDATIONS_CACHE_TIMEOUT = 60 * 60 * 24
RELATED_RECOMMENDATIONS_LIMIT = 25

TRAKT_SEARCH_TYPES = {
    MediaTypes.MOVIE.value: "movie",
    MediaTypes.TV.value: "show",
    MediaTypes.ANIME.value: "show",
    MediaTypes.SEASON.value: "show",
}


def is_configured(*, user=None) -> bool:
    """Return whether Trakt API access is configured."""
    return bool(credentials.get("trakt", "client_id", user=user))


def _headers(user=None) -> dict[str, str]:
    """Return Trakt request headers."""
    return {
        "Content-Type": "application/json",
        "User-Agent": f"Floppy/{settings.VERSION}",
        "trakt-api-version": TRAKT_API_VERSION,
        "trakt-api-key": credentials.get("trakt", "client_id", user=user),
    }


def _normalize_ids(ids: dict[str, Any] | None) -> dict[str, str]:
    """Return a compact normalized Trakt ID payload."""
    normalized: dict[str, str] = {}
    for key, value in (ids or {}).items():
        if value in (None, ""):
            continue
        normalized[str(key)] = str(value)
    return normalized


def _lookup_media_by_external_id(
    external_id_type: str,
    external_id: str | int,
    *,
    media_type: str,
    user=None,
) -> dict[str, Any] | None:
    """Return normalized movie/show metadata from a Trakt external-ID lookup."""
    trakt_media_type = TRAKT_SEARCH_TYPES.get(media_type)
    normalized_id = str(external_id or "").strip()
    if not trakt_media_type or not normalized_id or not is_configured(user=user):
        return None

    response = services.api_request(
        TRAKT_API_PROVIDER,
        "GET",
        f"{TRAKT_BASE_URL}/search/{external_id_type}/{normalized_id}",
        params={
            "type": trakt_media_type,
            "extended": "full",
        },
        headers=_headers(user=user),
    )

    entries = response if isinstance(response, list) else []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        payload = entry.get(trakt_media_type)
        if not isinstance(payload, dict):
            continue
        rating = payload.get("rating")
        votes = payload.get("votes")
        return {
            "rating": float(rating) if rating is not None else None,
            "votes": int(votes) if votes is not None else None,
            "trakt_ids": _normalize_ids(payload.get("ids")),
            "external_ids": _normalize_ids(payload.get("ids")),
            "matched_id_type": external_id_type,
            "title": payload.get("title"),
            "year": payload.get("year"),
        }

    return None


def related_recommendations(media_type: str, tmdb_id: str | int, *, user=None):
    """Return Trakt related movies/shows mapped onto Floppy's TMDb cards."""
    trakt_media_type = TRAKT_SEARCH_TYPES.get(media_type)
    if media_type not in (MediaTypes.MOVIE.value, MediaTypes.TV.value):
        return []

    normalized_id = str(tmdb_id or "").strip()
    if not normalized_id or not is_configured(user=user):
        return []

    credential_key = credentials.cache_suffix("trakt", "client_id", user=user)
    cache_key = f"trakt_related_{trakt_media_type}_{normalized_id}_{credential_key}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    match = _lookup_media_by_external_id(
        "tmdb",
        normalized_id,
        media_type=media_type,
        user=user,
    )
    trakt_ids = (match or {}).get("trakt_ids") or {}
    trakt_id = trakt_ids.get("trakt") or trakt_ids.get("slug")
    if not trakt_id:
        cache.set(cache_key, [], RELATED_RECOMMENDATIONS_CACHE_TIMEOUT)
        return []

    response = services.api_request(
        TRAKT_API_PROVIDER,
        "GET",
        f"{TRAKT_BASE_URL}/{trakt_media_type}s/{trakt_id}/related",
        params={
            "extended": "full",
            "page": 1,
            "limit": RELATED_RECOMMENDATIONS_LIMIT,
        },
        headers=_headers(user=user),
    )
    entries = response if isinstance(response, list) else (
        response.get("results", []) if isinstance(response, dict) else []
    )
    recommendations = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        ids = entry.get("ids") or {}
        destination_id = ids.get("tmdb")
        title = str(entry.get("title") or "").strip()
        if destination_id in (None, "") or not title:
            continue

        images = entry.get("images") or {}
        posters = images.get("poster") or []
        image = posters[0] if isinstance(posters, list) and posters else posters
        if isinstance(image, str) and image.startswith("//"):
            image = f"https:{image}"
        elif isinstance(image, str) and image.startswith(
            ("media.trakt.tv/", "walter-r2.trakt.tv/")
        ):
            image = f"https://{image}"
        elif not isinstance(image, str) or not image.startswith("https://"):
            image = ""

        recommendations.append(
            {
                "source": Sources.TMDB.value,
                "media_type": media_type,
                "media_id": str(destination_id),
                "title": title,
                "image": image,
                "year": entry.get("year"),
                "certification": entry.get("certification"),
                "trakt_id": str(ids.get("trakt") or ""),
            }
        )

    cache.set(cache_key, recommendations, RELATED_RECOMMENDATIONS_CACHE_TIMEOUT)
    return recommendations


def _lookup_season_by_show_id(
    show_lookup: dict[str, Any],
    *,
    season_number: int,
) -> dict[str, Any] | None:
    """Return normalized Trakt summary metadata for one specific season."""
    trakt_ids = show_lookup.get("trakt_ids") or {}
    show_id = trakt_ids.get("trakt") or trakt_ids.get("slug")
    if not show_id:
        return None

    try:
        response = services.api_request(
            TRAKT_API_PROVIDER,
            "GET",
            f"{TRAKT_BASE_URL}/shows/{show_id}/seasons/{season_number}",
            params={"extended": "full"},
            headers=_headers(),
        )
    except services.ProviderAPIError as exc:
        if exc.status_code in {400, 404}:
            return None
        raise

    season_payload = response
    if isinstance(response, list):
        season_payload = next(
            (
                entry
                for entry in response
                if isinstance(entry, dict)
                and str(entry.get("number")) == str(season_number)
            ),
            response[0] if response and isinstance(response[0], dict) else None,
        )

    if not isinstance(season_payload, dict):
        return None

    rating = season_payload.get("rating")
    votes = season_payload.get("votes")
    response_ids = _normalize_ids(season_payload.get("ids"))
    merged_ids = dict(trakt_ids)
    merged_ids.update(response_ids)
    return {
        "rating": float(rating) if rating is not None else None,
        "votes": int(votes) if votes is not None else None,
        "trakt_ids": merged_ids,
        "external_ids": merged_ids,
        "matched_id_type": show_lookup.get("matched_id_type"),
        "title": show_lookup.get("title"),
        "year": show_lookup.get("year"),
        "season_number": season_number,
    }


def fetch_episode_ratings_for_season(
    show_lookup: dict[str, Any],
    season_number: int,
    episode_numbers: list[int],
    *,
    delay_seconds: float = 0.5,
) -> dict[int, dict]:
    """Return aggregate Trakt ratings for multiple episodes in a season.

    Returns {episode_number: {"rating": float | None, "votes": int}}.
    Episodes that 404 or have no data are omitted from the result.
    """
    trakt_ids = show_lookup.get("trakt_ids") or {}
    show_id = trakt_ids.get("trakt") or trakt_ids.get("slug")
    if not show_id:
        return {}

    import time

    results: dict[int, dict] = {}
    for episode_number in episode_numbers:
        try:
            response = services.api_request(
                TRAKT_API_PROVIDER,
                "GET",
                f"{TRAKT_BASE_URL}/shows/{show_id}/seasons/{season_number}/episodes/{episode_number}/ratings",
                headers=_headers(),
            )
        except services.ProviderAPIError as exc:
            if exc.status_code in {400, 404}:
                continue
            raise
        if not isinstance(response, dict):
            continue
        rating = response.get("rating")
        votes = response.get("votes")
        results[episode_number] = {
            "rating": round(float(rating), 1) if rating is not None else None,
            "votes": int(votes) if votes is not None else 0,
        }
        if delay_seconds > 0:
            time.sleep(delay_seconds)
    return results


def lookup_by_external_id(
    external_id_type: str,
    external_id: str | int,
    *,
    media_type: str,
    season_number: int | None = None,
) -> dict[str, Any] | None:
    """Return Trakt summary metadata for a single external-ID lookup."""
    show_lookup = _lookup_media_by_external_id(
        external_id_type,
        external_id,
        media_type=media_type,
    )
    if media_type != MediaTypes.SEASON.value:
        return show_lookup
    if season_number is None or season_number <= 0:
        return None
    if not show_lookup:
        return None
    return _lookup_season_by_show_id(show_lookup, season_number=season_number)
