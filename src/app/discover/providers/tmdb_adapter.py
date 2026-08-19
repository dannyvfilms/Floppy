"""TMDb Discover adapter."""

from __future__ import annotations

import logging
from datetime import date

from django.conf import settings

from app.discover import cache_repo
from app.discover.schemas import CandidateItem
from app.models import MediaTypes, Sources
from app.providers import services

logger = logging.getLogger(__name__)

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_BASE_PARAMS = {
    "api_key": settings.TMDB_API,
    "language": settings.TMDB_LANG,
}

TRENDING_TTL = 60 * 60
CURRENT_CYCLE_TTL = 60 * 60
TOP_RATED_TTL = 60 * 60 * 24
UPCOMING_TTL = 60 * 60 * 24
RELATED_TTL = 60 * 60 * 24
GENRE_DISCOVERY_TTL = 60 * 60 * 24
GENRE_MAP_TTL = 60 * 60 * 24
# TMDB list endpoints return ~20 results per page; multiple pages widen the
# candidate pool so the scoring gauntlet has real competition to rank,
# instead of near-guaranteeing whatever page 1 happens to contain.
RELATED_MAX_PAGES = 2
GENRE_DISCOVERY_MAX_PAGES = 2


class TMDbDiscoverAdapter:
    """TMDb adapter used by the Discover service."""

    provider = Sources.TMDB.value

    def _cache_request(self, endpoint: str, params: dict, *, ttl_seconds: int) -> dict:
        payload, is_stale = cache_repo.get_api_cache(self.provider, endpoint, params)
        if payload and not is_stale:
            return payload

        try:
            response = services.api_request(
                self.provider,
                "GET",
                f"{TMDB_BASE_URL}{endpoint}",
                params={**TMDB_BASE_PARAMS, **params},
            )
            cache_repo.set_api_cache(
                self.provider,
                endpoint,
                params,
                response,
                ttl_seconds=ttl_seconds,
            )
        except Exception as error:
            if payload:
                logger.warning(
                    "discover_tmdb_cache_fallback endpoint=%s error=%s",
                    endpoint,
                    error,
                )
                return payload
            logger.warning(
                "discover_tmdb_request_failed endpoint=%s error=%s",
                endpoint,
                error,
            )
            return {"results": []}
        else:
            return response

    def _paginated_raw_results(
        self,
        endpoint: str,
        params: dict,
        *,
        ttl_seconds: int,
        max_pages: int,
        limit: int,
    ) -> list[dict]:
        """Fetch and merge multiple pages of a TMDB list endpoint, deduped by id."""
        merged: list[dict] = []
        seen_ids: set = set()
        total_pages: int | None = None
        for page in range(1, max_pages + 1):
            if total_pages is not None and page > total_pages:
                break
            payload = self._cache_request(
                endpoint,
                {**params, "page": page},
                ttl_seconds=ttl_seconds,
            )
            results = payload.get("results") or []
            if not results:
                break
            for item in results:
                item_id = item.get("id")
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                merged.append(item)
            total_pages = payload.get("total_pages")
            if len(merged) >= limit:
                break
        return merged[:limit]

    def _poster_url(self, path: str | None) -> str:
        if path:
            return f"https://image.tmdb.org/t/p/w500{path}"
        return settings.IMG_NONE

    def _normalize_results(
        self, media_type: str, results: list[dict], *, row_key: str
    ) -> list[CandidateItem]:
        genre_map = self._genre_id_to_name_map(media_type)
        candidates: list[CandidateItem] = []
        for item in results:
            title = item.get("title") or item.get("name") or ""
            if not title:
                continue

            genre_ids = item.get("genre_ids") or []
            genres = [genre_map.get(genre_id, "") for genre_id in genre_ids]
            genres = [genre for genre in genres if genre]

            release_date = item.get("release_date") or item.get("first_air_date")
            candidates.append(
                CandidateItem(
                    media_type=media_type,
                    source=Sources.TMDB.value,
                    media_id=str(item.get("id", "")),
                    title=title,
                    original_title=item.get("original_title")
                    or item.get("original_name"),
                    localized_title=item.get("title") or item.get("name"),
                    image=self._poster_url(item.get("poster_path")),
                    release_date=release_date,
                    genres=genres,
                    popularity=float(item["popularity"])
                    if item.get("popularity") is not None
                    else None,
                    rating=float(item["vote_average"])
                    if item.get("vote_average") is not None
                    else None,
                    rating_count=int(item["vote_count"])
                    if item.get("vote_count") is not None
                    else None,
                    row_key=row_key,
                ),
            )
        return candidates

    def _genre_id_to_name_map(self, media_type: str) -> dict[int, str]:
        endpoint = f"/genre/{media_type}/list"
        payload = self._cache_request(endpoint, {}, ttl_seconds=GENRE_MAP_TTL)
        mapping: dict[int, str] = {}
        for genre in payload.get("genres", []):
            genre_id = genre.get("id")
            name = genre.get("name")
            if genre_id is None or not name:
                continue
            mapping[int(genre_id)] = str(name)
        return mapping

    def _genre_name_to_id_map(self, media_type: str) -> dict[str, int]:
        return {
            name.lower(): genre_id
            for genre_id, name in self._genre_id_to_name_map(media_type).items()
        }

    def trending(self, media_type: str, *, limit: int = 50) -> list[CandidateItem]:
        """Return the trending."""
        if media_type not in {MediaTypes.MOVIE.value, MediaTypes.TV.value}:
            return []
        payload = self._cache_request(
            f"/trending/{media_type}/day",
            {},
            ttl_seconds=TRENDING_TTL,
        )
        return self._normalize_results(
            media_type,
            payload.get("results", [])[:limit],
            row_key="trending",
        )

    def top_rated(self, media_type: str, *, limit: int = 50) -> list[CandidateItem]:
        """Return the top rated."""
        if media_type not in {MediaTypes.MOVIE.value, MediaTypes.TV.value}:
            return []
        payload = self._cache_request(
            f"/{media_type}/top_rated",
            {},
            ttl_seconds=TOP_RATED_TTL,
        )
        return self._normalize_results(
            media_type,
            payload.get("results", [])[:limit],
            row_key="top_rated",
        )

    def upcoming(self, media_type: str, *, limit: int = 50) -> list[CandidateItem]:
        """Return the upcoming."""
        if media_type == MediaTypes.MOVIE.value:
            payload = self._cache_request(
                "/movie/upcoming",
                {},
                ttl_seconds=UPCOMING_TTL,
            )
            return self._normalize_results(
                media_type,
                payload.get("results", [])[:limit],
                row_key="upcoming",
            )

        if media_type == MediaTypes.TV.value:
            today = date.today().isoformat()  # noqa: DTZ011  # provider filter uses a plain calendar date
            payload = self._cache_request(
                "/discover/tv",
                {
                    "sort_by": "popularity.desc",
                    "first_air_date.gte": today,
                    "include_null_first_air_dates": "false",
                },
                ttl_seconds=UPCOMING_TTL,
            )
            return self._normalize_results(
                media_type,
                payload.get("results", [])[:limit],
                row_key="upcoming",
            )

        return []

    def current_cycle(self, media_type: str, *, limit: int = 50) -> list[CandidateItem]:
        """Return the current cycle."""
        if media_type == MediaTypes.MOVIE.value:
            payload = self._cache_request(
                "/movie/now_playing",
                {},
                ttl_seconds=CURRENT_CYCLE_TTL,
            )
            return self._normalize_results(
                media_type,
                payload.get("results", [])[:limit],
                row_key="current_cycle",
            )

        if media_type == MediaTypes.TV.value:
            payload = self._cache_request(
                "/tv/on_the_air",
                {},
                ttl_seconds=CURRENT_CYCLE_TTL,
            )
            return self._normalize_results(
                media_type,
                payload.get("results", [])[:limit],
                row_key="current_cycle",
            )

        return []

    def related(
        self, media_type: str, media_id: str, *, limit: int = 50
    ) -> list[CandidateItem]:
        """Return the related."""
        if not media_id:
            return []

        if media_type == MediaTypes.MOVIE.value:
            # /similar (content-tag matching) and /recommendations
            # (collaborative filtering) are independent signals; merging both
            # widens the pool with two different kinds of "related" evidence
            # instead of just more of the same one.
            endpoints = [
                f"/movie/{media_id}/similar",
                f"/movie/{media_id}/recommendations",
            ]
        elif media_type == MediaTypes.TV.value:
            endpoints = [f"/tv/{media_id}/recommendations"]
        else:
            return []

        raw_results: list[dict] = []
        seen_ids: set = set()
        for endpoint in endpoints:
            for item in self._paginated_raw_results(
                endpoint,
                {},
                ttl_seconds=RELATED_TTL,
                max_pages=RELATED_MAX_PAGES,
                limit=limit,
            ):
                item_id = item.get("id")
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                raw_results.append(item)

        return self._normalize_results(
            media_type,
            raw_results[:limit],
            row_key="related",
        )

    def genre_discovery(
        self,
        media_type: str,
        genres: list[str],
        *,
        limit: int = 100,
    ) -> list[CandidateItem]:
        """Return the genre discovery."""
        if media_type not in {MediaTypes.MOVIE.value, MediaTypes.TV.value}:
            return []

        name_to_id = self._genre_name_to_id_map(media_type)
        genre_ids = [
            str(name_to_id[genre.lower()])
            for genre in genres
            if genre and genre.lower() in name_to_id
        ]
        params = {
            "sort_by": "vote_average.desc",
            "vote_count.gte": 100,
        }
        if genre_ids:
            params["with_genres"] = ",".join(genre_ids[:3])

        raw_results = self._paginated_raw_results(
            f"/discover/{media_type}",
            params,
            ttl_seconds=GENRE_DISCOVERY_TTL,
            max_pages=GENRE_DISCOVERY_MAX_PAGES,
            limit=limit,
        )
        return self._normalize_results(
            media_type,
            raw_results,
            row_key="genre_discovery",
        )

    def check_capability(self) -> dict[str, bool]:
        """Return endpoint-level availability booleans."""
        checks = {
            "trending_movie": False,
            "trending_tv": False,
            "top_rated_movie": False,
            "top_rated_tv": False,
        }

        try:
            checks["trending_movie"] = bool(
                self.trending(MediaTypes.MOVIE.value, limit=1)
            )
        except Exception:
            checks["trending_movie"] = False

        try:
            checks["trending_tv"] = bool(self.trending(MediaTypes.TV.value, limit=1))
        except Exception:
            checks["trending_tv"] = False

        try:
            checks["top_rated_movie"] = bool(
                self.top_rated(MediaTypes.MOVIE.value, limit=1)
            )
        except Exception:
            checks["top_rated_movie"] = False

        try:
            checks["top_rated_tv"] = bool(self.top_rated(MediaTypes.TV.value, limit=1))
        except Exception:
            checks["top_rated_tv"] = False

        return checks
