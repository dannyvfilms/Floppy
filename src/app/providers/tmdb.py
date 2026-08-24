import contextlib
import logging
from datetime import timedelta
from types import SimpleNamespace

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.utils.html import strip_tags

from app import helpers
from app.log_safety import exception_summary
from app.models import MediaTypes, Sources
from app.providers import services

logger = logging.getLogger(__name__)

YEAR_STRING_LENGTH = 4
TMDB_GENDER_MALE = 2
TMDB_GENDER_NON_BINARY = 3
base_url = "https://api.themoviedb.org/3"
TVDB_OVERRIDE_CACHE_TIMEOUT = 60 * 60 * 24 * 30
# The /changes result for a given day doesn't change once fetched, and the
# calendar reload is the only caller.
TMDB_CHANGES_CACHE_TIMEOUT = 60 * 60 * 6
# Search results are keyed on arbitrary user- and webhook-supplied strings, so
# these keys grow without bound. They're also the cheapest thing to refetch and
# the least valuable to keep, which makes the default 24 hours the wrong trade at
# the point Redis is under pressure (issue #521).
SEARCH_CACHE_TIMEOUT = 60 * 60
# Season blobs are the largest single thing Floppy caches (full episode lists),
# so they expire sooner than the show payload they hang off.
SEASON_CACHE_TIMEOUT = 60 * 60 * 12
# build_filter_data_from_items() requests this catalog on every media-list
# render. A cold cache during a TMDB outage must not repeat both provider
# requests (each carrying the full request timeout) on every single render,
# so a failed fetch is still cached, just for a much shorter window.
WATCH_PROVIDER_CATALOG_FAILURE_CACHE_TIMEOUT = 60 * 5
TMDB_APPEND_TO_RESPONSE_MAX_REMOTE_CALLS = 20
TV_DETAIL_APPEND_RESPONSES = (
    "recommendations,external_ids,aggregate_credits,alternative_titles,watch/providers"
)
TV_DETAIL_SEASON_APPEND_RESPONSES = (
    "season/{season}",
    "season/{season}/credits",
    "season/{season}/watch/providers",
)
TMDB_SEASON_CACHE_VERSION = 4
# Media-details carousel (trailer + photos): fetched lazily, its own cache
# entry, independent of the movie/tv/season append_to_response payloads above.
CAROUSEL_CACHE_TTL_SUCCESS = 60 * 60 * 24 * 7
CAROUSEL_CACHE_TTL_ABSENT = 60 * 60 * 24


def base_params(language=None):
    """Return the base TMDB request params for the given (or default) language."""
    return {
        "api_key": settings.TMDB_API,
        "language": language or settings.TMDB_LANG,
    }


def _language_suffix(language=None):
    """Return a cache-key suffix for non-default languages, empty string otherwise."""
    language = language or settings.TMDB_LANG
    if language == settings.TMDB_LANG:
        return ""
    return f"_lang{language}"


def _tv_detail_max_seasons_per_request():
    """Return the largest season batch that fits within TMDB's append limit."""
    base_append_count = len(TV_DETAIL_APPEND_RESPONSES.split(","))
    return max(
        (TMDB_APPEND_TO_RESPONSE_MAX_REMOTE_CALLS - base_append_count)
        // len(TV_DETAIL_SEASON_APPEND_RESPONSES),
        1,
    )


def _season_cache_key(media_id, season_number, language=None):
    """Return the cache key for a TMDB season payload."""
    return (
        f"{Sources.TMDB.value}_{MediaTypes.SEASON.value}_v{TMDB_SEASON_CACHE_VERSION}_"
        f"{media_id}_{season_number}{_language_suffix(language)}"
    )


def _tv_cache_key(media_id, language=None):
    """Return the cache key for a TMDB TV show payload."""
    return f"{Sources.TMDB.value}_{MediaTypes.TV.value}_{media_id}{_language_suffix(language)}"


def _movie_cache_key(media_id, language=None):
    """Return the cache key for a TMDB movie payload."""
    return (
        f"{Sources.TMDB.value}_{MediaTypes.MOVIE.value}_{media_id}"
        f"{_language_suffix(language)}"
    )


def handle_error(error):
    """Handle TMDB API errors."""
    error_resp = error.response
    status_code = error_resp.status_code

    # Handle authentication errors
    if status_code == requests.codes.unauthorized:
        error_json = None
        try:
            error_json = error_resp.json()
        except requests.exceptions.JSONDecodeError:
            error_json = None

        details = (
            error_json.get("status_message") if isinstance(error_json, dict) else None
        )
        if details:
            # Remove trailing period if present
            details = details.rstrip(".")
            raise services.ProviderAPIError(Sources.TMDB.value, error, details)

    raise services.ProviderAPIError(
        Sources.TMDB.value,
        error,
    )


def get_external_links(external_ids, tmdb_id=None):
    """Build external links dictionary from TMDB external_ids response."""
    links = {}

    if external_ids.get("imdb_id"):
        links["IMDb"] = f"https://www.imdb.com/title/{external_ids['imdb_id']}/"

    if external_ids.get("tvdb_id"):
        links["TVDB"] = (
            f"https://www.thetvdb.com/dereferrer/series/{external_ids['tvdb_id']}"
        )

    if external_ids.get("wikidata_id"):
        links["Wikidata"] = (
            f"https://www.wikidata.org/wiki/{external_ids['wikidata_id']}"
        )

    # Only passed in for movies as Letterboxd seldom supports TV
    if tmdb_id:
        # https://letterboxd.com/about/film-data/
        # Letterboxd will redirect to the correct movie
        # as they source their data from TMDB
        links["Letterboxd"] = f"https://www.letterboxd.com/tmdb/{tmdb_id}"

    return links


def _tvdb_override_cache_key(media_id):
    """Return cache key for a preferred TVDB override on a TMDB show."""
    return f"{Sources.TMDB.value}_tvdb_override_{media_id}"


def get_tvdb_id_override(media_id):
    """Return a preferred TVDB override for a TMDB show, if one exists."""
    override = cache.get(_tvdb_override_cache_key(media_id))
    if override in (None, ""):
        return None
    return str(override)


def _apply_tvdb_id_override_to_tv_data(media_id, tv_data):
    """Overlay any preferred TVDB override onto cached TV metadata."""
    if not isinstance(tv_data, dict):
        return tv_data, False

    override_tvdb_id = get_tvdb_id_override(media_id)
    if not override_tvdb_id:
        return tv_data, False

    changed = False
    current_tvdb_id = str(tv_data.get("tvdb_id") or "")
    if current_tvdb_id != override_tvdb_id:
        tv_data["tvdb_id"] = override_tvdb_id
        changed = True

        related = tv_data.get("related")
        seasons = related.get("seasons") if isinstance(related, dict) else None
        if isinstance(seasons, list):
            filtered_seasons = [
                season for season in seasons if season.get("season_number") != 0
            ]
            if len(filtered_seasons) != len(seasons):
                related["seasons"] = filtered_seasons
                cache.delete(_season_cache_key(media_id, 0))

    external_links = dict(tv_data.get("external_links") or {})
    preferred_tvdb_link = (
        f"https://www.thetvdb.com/dereferrer/series/{override_tvdb_id}"
    )
    if external_links.get("TVDB") != preferred_tvdb_link:
        external_links["TVDB"] = preferred_tvdb_link
        tv_data["external_links"] = external_links
        changed = True

    return tv_data, changed


def set_tvdb_id_override(media_id, tvdb_id):
    """Persist a preferred TVDB override for a TMDB show and invalidate season 0."""
    if not media_id or not tvdb_id:
        return

    media_id = str(media_id)
    tvdb_id = str(tvdb_id)
    cache.set(
        _tvdb_override_cache_key(media_id),
        tvdb_id,
        timeout=TVDB_OVERRIDE_CACHE_TIMEOUT,
    )
    cache.delete(_season_cache_key(media_id, 0))

    tv_cache_key = f"{Sources.TMDB.value}_{MediaTypes.TV.value}_{media_id}"
    cached_tv_data = cache.get(tv_cache_key)
    if cached_tv_data is None:
        return

    cached_tv_data, changed = _apply_tvdb_id_override_to_tv_data(
        media_id,
        cached_tv_data,
    )
    if changed:
        cache.set(tv_cache_key, cached_tv_data)


def _normalize_provider_title_for_match(value):
    """Return a conservative normalized title key for provider cross-matching."""
    text = strip_tags(str(value or "")).strip().lower()
    return "".join(character for character in text if character.isalnum())


def _coerce_provider_year(value):
    """Return a numeric year from a provider payload value when possible."""
    if value in (None, ""):
        return None
    if hasattr(value, "year"):
        try:
            return int(value.year)
        except (TypeError, ValueError):
            return None

    text = str(value).strip()
    if len(text) >= YEAR_STRING_LENGTH and text[:YEAR_STRING_LENGTH].isdigit():
        try:
            return int(text[:YEAR_STRING_LENGTH])
        except ValueError:
            return None
    return None


def _discover_tmdb_tvdb_id_from_search(media_id, tv_data=None):
    """Return a TVDB series id for a TMDB show using a conservative title search."""
    if not media_id:
        return None

    override_tvdb_id = get_tvdb_id_override(media_id)
    if override_tvdb_id:
        return override_tvdb_id

    from app.providers import tvdb

    if not tvdb.enabled():
        return None

    if not isinstance(tv_data, dict):
        tv_cache_key = f"{Sources.TMDB.value}_{MediaTypes.TV.value}_{media_id}"
        tv_data = cache.get(tv_cache_key)

    if not isinstance(tv_data, dict):
        return None

    existing_tvdb_id = str(tv_data.get("tvdb_id") or "").strip()
    if existing_tvdb_id:
        return existing_tvdb_id

    candidate_titles = []
    for key in ("title", "original_title", "localized_title"):
        title = str(tv_data.get(key) or "").strip()
        if title and title not in candidate_titles:
            candidate_titles.append(title)

    if not candidate_titles:
        return None

    target_year = _coerce_provider_year(
        (tv_data.get("details") or {}).get("first_air_date"),
    )

    for candidate_title in candidate_titles:
        normalized_candidate = _normalize_provider_title_for_match(candidate_title)
        if not normalized_candidate:
            continue

        try:
            search_payload = tvdb.search(MediaTypes.TV.value, candidate_title, 1)
        except services.ProviderAPIError as error:
            logger.warning(
                "Skipping TMDB->TVDB title match due to TVDB API error: %s",
                error,
                extra={"media_id": media_id, "title": candidate_title},
            )
            return None

        results = search_payload.get("results") or []
        matching_ids = []

        for result in results:
            if not isinstance(result, dict):
                continue

            result_id = str(result.get("media_id") or "").strip()
            if not result_id:
                continue

            if (
                _normalize_provider_title_for_match(result.get("title"))
                != normalized_candidate
            ):
                continue

            result_year = _coerce_provider_year(result.get("year"))
            if target_year and result_year and result_year != target_year:
                continue

            matching_ids.append(result_id)

        unique_ids = list(dict.fromkeys(matching_ids))
        if len(unique_ids) == 1:
            matched_tvdb_id = unique_ids[0]
            set_tvdb_id_override(media_id, matched_tvdb_id)
            logger.info(
                "Resolved TMDB show %s to TVDB %s via exact title match",
                media_id,
                matched_tvdb_id,
            )
            return matched_tvdb_id

    return None


def resolve_tvdb_id_for_tmdb_show(media_id, tv_data=None):
    """Return a TVDB series id for a TMDB show using cached data or search."""
    return _discover_tmdb_tvdb_id_from_search(media_id, tv_data=tv_data)


def _normalize_season_numbers(season_numbers):
    """Normalize season numbers from route and form inputs before TMDB lookups."""
    normalized_seasons = []

    for season_number in season_numbers:
        if isinstance(season_number, str):
            season_number = season_number.strip()  # noqa: PLW2901  # deliberate in-loop normalisation
            with contextlib.suppress(ValueError):
                season_number = int(season_number)  # noqa: PLW2901  # deliberate in-loop normalisation

        normalized_seasons.append(season_number)

    return normalized_seasons


def search(media_type, query, page, language=None):
    """Search for media on TMDB."""
    cache_key = (
        f"search_{Sources.TMDB.value}_{media_type}_{query}_{page}"
        f"{_language_suffix(language)}"
    )
    data = cache.get(cache_key)

    if data is None:
        url = f"{base_url}/search/{media_type}"

        params = {
            **base_params(language),
            "query": query,
            "page": page,
        }

        if settings.TMDB_NSFW:
            params["include_adult"] = "true"

        try:
            response = services.api_request(
                Sources.TMDB.value,
                "GET",
                url,
                params=params,
            )
        except requests.exceptions.HTTPError as error:
            handle_error(error)

        results = [
            {
                "media_id": media["id"],
                "source": Sources.TMDB.value,
                "media_type": media_type,
                "title": get_title(media),
                "original_title": get_original_title(media),
                "localized_title": get_localized_title(media),
                "image": get_image_url(media["poster_path"]),
                "year": get_year(media),
            }
            for media in response["results"]
        ]

        total_results = response["total_results"]
        per_page = 20  # TMDB always returns 20 results per page
        data = helpers.format_search_response(
            page,
            per_page,
            total_results,
            results,
        )

        cache.set(cache_key, data, SEARCH_CACHE_TIMEOUT)

    return data


def find(external_id, external_source, language=None):
    """Search for media on TMDB."""
    cache_key = (
        f"find_{Sources.TMDB.value}_{external_id}_{external_source}"
        f"{_language_suffix(language)}"
    )
    data = cache.get(cache_key)

    if data is None:
        url = f"{base_url}/find/{external_id}"

        params = {
            **base_params(language),
            "external_source": external_source,
        }

        try:
            response = services.api_request(
                Sources.TMDB.value,
                "GET",
                url,
                params=params,
            )
        except requests.exceptions.HTTPError as error:
            handle_error(error)

        cache.set(cache_key, response)
        return response

    return data


def movie(media_id, language=None):
    """Return the metadata for the selected movie from The Movie Database."""
    cache_key = _movie_cache_key(media_id, language)
    data = cache.get(cache_key)

    if data is None:
        url = f"{base_url}/movie/{media_id}"
        appends = [
            "recommendations",
            "external_ids",
            "credits",
            "watch/providers",
            "alternative_titles",
            "keywords",
            "release_dates",
        ]
        params = {
            **base_params(language),
            "append_to_response": ",".join(appends),
        }

        try:
            response = services.api_request(
                Sources.TMDB.value,
                "GET",
                url,
                params=params,
            )
            if response.get("belongs_to_collection", {}) is not None and (
                collection_id := response.get("belongs_to_collection", {}).get("id")
            ):
                try:
                    collection_response = services.api_request(
                        Sources.TMDB.value,
                        "GET",
                        f"{base_url}/collection/{collection_id}",
                        params={**base_params(language)},
                    )
                except requests.exceptions.HTTPError as error:
                    logger.warning(
                        "Failed to fetch TMDB collection metadata: %s",
                        exception_summary(error),
                    )
                    collection_response = {}
            else:
                collection_response = {}
        except requests.exceptions.HTTPError as error:
            handle_error(error)

        # Filter out collection items from recommendations, to avoid duplicates
        collection_items = get_collection(collection_response)
        collection_ids = [item["media_id"] for item in collection_items]
        recommended_items = response.get("recommendations", {}).get("results", [])
        filtered_recommendations = [
            item for item in recommended_items if item["id"] not in collection_ids
        ]
        collection_info = response.get("belongs_to_collection") or {}
        provider_certification = get_movie_certification(
            response.get("release_dates", {})
        )
        cast = response.get("credits", {}).get("cast", [])
        movie_details = {
            "format": "Movie",
            "release_date": get_start_date(response.get("release_date")),
            "status": response.get("status"),
            "runtime": get_readable_duration(response.get("runtime")),
            "studios": get_companies(response.get("production_companies", [])),
            "country": get_country(response.get("production_countries", [])),
            "languages": get_languages(response.get("spoken_languages", [])),
            "certification": provider_certification,
        }
        if budget := format_currency(response.get("budget")):
            movie_details["budget"] = budget
        if revenue := format_currency(response.get("revenue")):
            movie_details["revenue"] = revenue
        data = {
            "media_id": media_id,
            "source": Sources.TMDB.value,
            "source_url": f"https://www.themoviedb.org/movie/{media_id}",
            "media_type": MediaTypes.MOVIE.value,
            **get_title_fields(response),
            "max_progress": 1,
            "image": get_image_url(response.get("poster_path")),
            "synopsis": get_synopsis(response.get("overview")),
            "genres": get_genres(response.get("genres", [])),
            "score": get_score(response.get("vote_average")),
            "score_count": response.get("vote_count"),
            "provider_popularity": response.get("popularity"),
            "provider_rating": get_score(response.get("vote_average")),
            "provider_rating_count": response.get("vote_count"),
            "details": movie_details,
            "cast": get_cast_credits(response.get("credits", {})),
            "crew": get_crew_credits(response.get("credits", {})),
            "studios_full": get_companies_full(response.get("production_companies")),
            "provider_keywords": get_keyword_names(response.get("keywords", {})),
            "provider_certification": provider_certification,
            "provider_collection_id": str(collection_info.get("id") or ""),
            "provider_collection_name": collection_info.get("name") or "",
            "total_cast_count": len(cast),
            "related": {
                collection_response.get("name", "collection"): collection_items,
                "recommendations": get_related(
                    filtered_recommendations[:15],
                    MediaTypes.MOVIE.value,
                ),
            },
            "external_links": get_external_links(
                response.get("external_ids", {}), media_id
            ),
            "providers": response.get("watch/providers", {}).get("results", {}),
        }

        cache.set(cache_key, data)

    return data


def get_cached_seasons(media_id, season_numbers, language=None):
    """Check cache for seasons and return cached data and list of uncached seasons.

    One get_many rather than a get per season: a 40-season show meant 40 round
    trips, and when Redis is slow it meant 40 socket timeouts back to back rather
    than one (issue #521).
    """
    season_numbers = _normalize_season_numbers(season_numbers)
    keys = {
        _season_cache_key(media_id, season_number, language): season_number
        for season_number in season_numbers
    }
    found = cache.get_many(list(keys)) or {}

    cached_data = {}
    uncached_seasons = []
    for key, season_number in keys.items():
        season_data = found.get(key)
        if season_data:
            cached_data[f"season/{season_number}"] = season_data
        else:
            uncached_seasons.append(season_number)

    return cached_data, uncached_seasons


def enrich_season_with_tv_data(season_data, tv_data, media_id, season_number):
    """Add TV show metadata to season metadata."""
    season_data["media_id"] = media_id
    season_data["source_url"] = season_data.get("source_url") or (
        f"https://www.themoviedb.org/tv/{media_id}/season/{season_number}"
    )
    season_data["title"] = tv_data["title"]
    season_data["original_title"] = tv_data.get("original_title")
    season_data["localized_title"] = tv_data.get("localized_title")
    season_data["tvdb_id"] = tv_data["tvdb_id"]
    season_data["external_links"] = tv_data["external_links"]
    season_data["genres"] = tv_data["genres"]
    if season_data["synopsis"] == "No synopsis available.":
        season_data["synopsis"] = tv_data["synopsis"]
    season_data["image"] = helpers.first_real_image(
        season_data.get("image"),
        tv_data.get("image"),
    )
    if not season_data.get("cast"):
        season_data["cast"] = tv_data.get("cast") or []
    if not season_data.get("crew"):
        season_data["crew"] = tv_data.get("crew") or []
    tv_recommendations = (tv_data.get("related") or {}).get("recommendations") or []
    if tv_recommendations:
        season_related = season_data.setdefault("related", {})
        if not season_related.get("recommendations"):
            season_related["recommendations"] = tv_recommendations
    return season_data


def _build_specials_related_entry(tv_data, season_data):
    """Build a season card entry for fallback TVDB-linked specials."""
    return {
        "source": Sources.TMDB.value,
        "media_type": MediaTypes.SEASON.value,
        "image": helpers.first_real_image(
            season_data.get("image"),
            tv_data.get("image"),
        ),
        "media_id": tv_data["media_id"],
        "title": tv_data["title"],
        "original_title": tv_data.get("original_title"),
        "localized_title": tv_data.get("localized_title"),
        "season_number": 0,
        "season_title": season_data["season_title"],
        "first_air_date": season_data["details"].get("first_air_date"),
        "last_air_date": season_data["details"].get("last_air_date"),
        "max_progress": season_data.get("max_progress"),
    }


def _attach_specials_to_tv_data(tv_data, season_data):
    """Attach a specials season card to TV metadata if one is missing."""
    if not tv_data:
        return

    related = tv_data.setdefault("related", {})
    seasons = related.setdefault("seasons", [])
    if any(season.get("season_number") == 0 for season in seasons):
        return

    seasons.append(_build_specials_related_entry(tv_data, season_data))
    seasons.sort(
        key=lambda season: (
            season.get("season_number") is None,
            season.get("season_number")
            if season.get("season_number") is not None
            else 999999,
        ),
    )


def cache_fallback_season_metadata(media_id, season_number, tv_data, season_data):
    """Persist webhook-derived fallback season metadata under TMDB cache keys."""
    if not tv_data or not season_data:
        return None

    season_number = _normalize_season_numbers([season_number])[0]
    episodes = [
        episode
        for episode in (season_data.get("episodes") or [])
        if isinstance(episode, dict)
    ]
    if not episodes:
        return None

    episode_numbers = [
        int(episode["episode_number"])
        for episode in episodes
        if episode.get("episode_number") is not None
    ]
    max_progress = season_data.get("max_progress") or (
        max(episode_numbers) if episode_numbers else None
    )

    runtimes = [
        runtime
        for runtime in (episode.get("runtime") for episode in episodes)
        if isinstance(runtime, int) and runtime > 0
    ]
    total_runtime = sum(runtimes) if runtimes else None

    air_dates = [
        episode.get("air_date") for episode in episodes if episode.get("air_date")
    ]
    details = dict(season_data.get("details") or {})
    if max_progress is not None:
        details.setdefault("episodes", max_progress)
    if air_dates:
        details.setdefault("first_air_date", get_start_date(min(air_dates)))
        details.setdefault("last_air_date", get_start_date(max(air_dates)))
    if total_runtime:
        details.setdefault(
            "runtime", get_readable_duration(total_runtime / len(runtimes))
        )
        details.setdefault("total_runtime", get_readable_duration(total_runtime))

    cached_season_data = {
        "source": Sources.TMDB.value,
        "media_type": MediaTypes.SEASON.value,
        "season_title": (
            season_data.get("season_title")
            or ("Specials" if season_number == 0 else f"Season {season_number}")
        ),
        "max_progress": max_progress,
        "image": helpers.first_real_image(
            season_data.get("image"),
            tv_data.get("image"),
        ),
        "season_number": season_number,
        "synopsis": season_data.get("synopsis") or get_synopsis(""),
        "score": season_data.get("score"),
        "score_count": season_data.get("score_count"),
        "cast": season_data.get("cast") or [],
        "crew": season_data.get("crew") or [],
        "details": details,
        "episodes": episodes,
        "providers": season_data.get("providers") or {},
        "source_url": (
            season_data.get("source_url")
            or tv_data.get("external_links", {}).get("TVDB")
            or tv_data.get("source_url")
        ),
    }
    cached_season_data = enrich_season_with_tv_data(
        cached_season_data,
        tv_data,
        media_id,
        season_number,
    )

    cache.set(
        _season_cache_key(media_id, season_number),
        cached_season_data,
        SEASON_CACHE_TIMEOUT,
    )

    tv_cache_key = f"{Sources.TMDB.value}_{MediaTypes.TV.value}_{media_id}"
    cached_tv_data = cache.get(tv_cache_key) or tv_data
    cached_tv_data, changed = _apply_tvdb_id_override_to_tv_data(
        media_id,
        cached_tv_data,
    )
    if season_number == 0:
        _attach_specials_to_tv_data(cached_tv_data, cached_season_data)
        changed = True
    if changed or cache.get(tv_cache_key) is None:
        cache.set(tv_cache_key, cached_tv_data)

    return cached_season_data


def _build_specials_season_from_tvdb(media_id, tv_data):
    """Build TMDB-shaped season metadata from TVDB specials data."""
    if not tv_data:
        return None

    if not tv_data.get("tvdb_id"):
        discovered_tvdb_id = _discover_tmdb_tvdb_id_from_search(
            media_id,
            tv_data=tv_data,
        )
        if discovered_tvdb_id:
            tv_data, _ = _apply_tvdb_id_override_to_tv_data(media_id, dict(tv_data))

    if not tv_data.get("tvdb_id"):
        return None

    from app.providers import tvdb

    if not tvdb.enabled():
        return None

    try:
        season_data = tvdb.build_specials_season(
            tv_data["tvdb_id"],
            media_id=media_id,
            source=Sources.TMDB.value,
            tv_data=tv_data,
        )
    except ValueError as error:
        if str(error) != "TVDB is not configured":
            raise
        logger.info(
            "Skipping TMDB specials fallback because TVDB is not configured",
            extra={
                "media_id": media_id,
                "tvdb_id": tv_data.get("tvdb_id"),
            },
        )
        return None
    except services.ProviderAPIError as error:
        logger.warning(
            "Skipping TMDB specials fallback due to TVDB API error: %s",
            error,
            extra={
                "media_id": media_id,
                "tvdb_id": tv_data.get("tvdb_id"),
            },
        )
        return None

    if season_data is None:
        return None
    return enrich_season_with_tv_data(season_data, tv_data, media_id, 0)


def get_tvdb_episode_image_map(tvdb_id, season_number, *, tmdb_media_id=None):
    """Return TVDB episode artwork keyed by episode number for a TMDB show."""
    if not tvdb_id:
        if not tmdb_media_id:
            return {}
        tvdb_id = _discover_tmdb_tvdb_id_from_search(tmdb_media_id)
        if not tvdb_id:
            return {}

    from app.providers import tvdb

    if not tvdb.enabled():
        return {}

    try:
        normalized_season_number = int(season_number)
    except (TypeError, ValueError):
        normalized_season_number = season_number

    error_cache_key = f"tvdb_ep_images_error:{tvdb_id}:{season_number}"
    if cache.get(error_cache_key) is not None:
        return {}

    try:
        season_payloads = tvdb.tv_with_seasons(
            str(tvdb_id),
            [normalized_season_number],
            routed_media_type=MediaTypes.TV.value,
        )
    except ValueError as error:
        if str(error) != "TVDB is not configured":
            raise
        logger.info(
            "Skipping TMDB episode art fallback because TVDB is not configured",
            extra={
                "media_id": tmdb_media_id,
                "tvdb_id": tvdb_id,
                "season_number": season_number,
            },
        )
        return {}
    except services.ProviderAPIError as error:
        # A 404 here just means this TMDB season/episode doesn't exist under
        # TVDB's own numbering (common for grouped-anime shows) - expected
        # and already handled below, not worth a warning. Other failures
        # (auth, 5xx, network) still warrant one.
        log_method = (
            logger.info if error.status_code == requests.codes.not_found else logger.warning
        )
        log_method(
            "Skipping TMDB episode art fallback due to TVDB API error: %s",
            error,
            extra={
                "media_id": tmdb_media_id,
                "tvdb_id": tvdb_id,
                "season_number": season_number,
            },
        )
        # Negative-cache the empty map so repeated artwork resolution
        # doesn't re-hit a failing TVDB endpoint on every attempt.
        cache.set(error_cache_key, {}, EPISODE_ERROR_NOT_FOUND_SECONDS)
        return {}

    season_payload = season_payloads.get(f"season/{normalized_season_number}")
    if not isinstance(season_payload, dict):
        season_payload = season_payloads.get(f"season/{season_number}", {})
    if not isinstance(season_payload, dict):
        return {}

    episode_images = {}
    for episode in season_payload.get("episodes") or []:
        if not isinstance(episode, dict):
            continue
        episode_number = episode.get("episode_number")
        image = helpers.first_real_image(episode.get("image"), default=None)
        if episode_number is None or not image:
            continue
        episode_images[str(episode_number)] = image

    return episode_images


def fetch_and_cache_seasons(media_id, season_numbers, tv_data, language=None):
    """Fetch uncached seasons from API and cache them."""
    url = f"{base_url}/tv/{media_id}"
    max_seasons_per_request = _tv_detail_max_seasons_per_request()
    fetched_tv_data = tv_data
    result_data = {}

    for i in range(0, len(season_numbers), max_seasons_per_request):
        is_first_batch = i == 0
        season_subset = season_numbers[i : i + max_seasons_per_request]
        append_text = ",".join(
            template.format(season=season)
            for season in season_subset
            for template in TV_DETAIL_SEASON_APPEND_RESPONSES
        )

        # The base show fields (recommendations, external_ids,
        # aggregate_credits, alternative_titles, watch/providers) describe
        # the show, not a season, so they can't change between batches of
        # the same fetch. Only the first batch needs to ask TMDB for them;
        # later batches reuse fetched_tv_data from that first response
        # instead of paying for it again (#512).
        if is_first_batch:
            params = {
                **base_params(language),
                "append_to_response": f"{TV_DETAIL_APPEND_RESPONSES},{append_text}",
            }
        else:
            params = {
                **base_params(language),
                "append_to_response": append_text,
            }

        try:
            response = services.api_request(
                Sources.TMDB.value,
                "GET",
                url,
                params=params,
            )
        except requests.exceptions.HTTPError as error:
            handle_error(error)

        if is_first_batch:
            # Always refresh the root TV payload from the same TMDB response
            # so season fetches can pick up updated external_ids (including
            # tvdb_id) even when the show cache already existed before this
            # request.
            refreshed_tv_data = process_tv(response, media_id=media_id)
            if not refreshed_tv_data.get("tvdb_id"):
                discovered_tvdb_id = _discover_tmdb_tvdb_id_from_search(
                    media_id,
                    tv_data=refreshed_tv_data,
                )
                if discovered_tvdb_id:
                    refreshed_tv_data, _ = _apply_tvdb_id_override_to_tv_data(
                        media_id,
                        refreshed_tv_data,
                    )
            tv_cache_key = _tv_cache_key(media_id, language)
            if fetched_tv_data is None or fetched_tv_data != refreshed_tv_data:
                fetched_tv_data = refreshed_tv_data
                cache.set(tv_cache_key, fetched_tv_data)

        # Process and cache each season
        for season_number in season_subset:
            season_key = f"season/{season_number}"
            if season_key not in response:
                logger.warning(
                    "Season %s not found in %s response; skipping cache update",
                    season_number,
                    Sources.TMDB.label,
                )
                continue

            season_credits = response.get(f"{season_key}/credits", {}) or {}
            season_data = process_season(
                response[season_key],
                response.get(f"{season_key}/watch/providers", {}),
                season_credits,
            )
            season_data = enrich_season_with_tv_data(
                season_data,
                fetched_tv_data,
                media_id,
                season_number,
            )
            cache.set(
                _season_cache_key(media_id, season_number, language),
                season_data,
                SEASON_CACHE_TIMEOUT,
            )
            result_data[season_key] = season_data

    if 0 in season_numbers and "season/0" not in result_data and fetched_tv_data:
        specials_season = _build_specials_season_from_tvdb(
            media_id,
            fetched_tv_data,
        )
        if specials_season:
            result_data["season/0"] = specials_season
            _attach_specials_to_tv_data(fetched_tv_data, specials_season)
            cache.set(
                _season_cache_key(media_id, 0, language),
                specials_season,
                SEASON_CACHE_TIMEOUT,
            )
            cache.set(
                _tv_cache_key(media_id, language),
                fetched_tv_data,
            )

    return result_data, fetched_tv_data


def tv_with_seasons(media_id, season_numbers, language=None):
    """Return the metadata for the tv show with seasons appended to the response."""
    if not season_numbers:
        return tv(media_id, language)
    season_numbers = _normalize_season_numbers(season_numbers)

    tv_cache_key = _tv_cache_key(media_id, language)
    tv_data = cache.get(tv_cache_key)
    if tv_data is not None:
        tv_data, changed = _apply_tvdb_id_override_to_tv_data(media_id, tv_data)
        if changed:
            cache.set(tv_cache_key, tv_data)

    cached_seasons, uncached_seasons = get_cached_seasons(
        media_id,
        season_numbers,
        language,
    )

    if tv_data is None and not uncached_seasons:
        tv_data = tv(media_id, language)

    if uncached_seasons:
        fetched_seasons, fetched_tv_data = fetch_and_cache_seasons(
            media_id,
            uncached_seasons,
            tv_data,
            language,
        )

        if fetched_tv_data is not None:
            tv_data = fetched_tv_data

        cached_seasons.update(fetched_seasons)

    return tv_data | cached_seasons


def tv(media_id, language=None):
    """Return the metadata for the selected tv show from The Movie Database."""
    cache_key = _tv_cache_key(media_id, language)
    data = cache.get(cache_key)

    # Invalidate stale cache entries that predate the season score field being added
    # to get_related(). A missing "score" key on the first season signals old format.
    if data is not None:
        first_season = next(
            iter((data.get("related") or {}).get("seasons") or []), None
        )
        if first_season is not None and "score" not in first_season:
            cache.delete(cache_key)
            data = None

    if data is None:
        url = f"{base_url}/tv/{media_id}"
        params = {
            **base_params(language),
            "append_to_response": TV_DETAIL_APPEND_RESPONSES,
        }

        try:
            response = services.api_request(
                Sources.TMDB.value,
                "GET",
                url,
                params=params,
            )
        except requests.exceptions.HTTPError as error:
            handle_error(error)

        data = process_tv(response, media_id=media_id)
        cache.set(cache_key, data)
    else:
        data, changed = _apply_tvdb_id_override_to_tv_data(media_id, data)
        if changed:
            cache.set(cache_key, data)

    return data


def _carousel_cache_key(media_type, media_id, season_number=None):
    """Return the cache key for a media-details carousel payload."""
    key = f"tmdb_carousel_{media_type}_{media_id}"
    if season_number is not None:
        key += f"_s{season_number}"
    return key


def _parse_carousel_video(response):
    """Return the single best YouTube trailer from a TMDB videos append, if any."""
    videos = response.get("videos", {}).get("results", []) or []
    youtube_videos = [v for v in videos if v.get("site") == "YouTube" and v.get("key")]
    trailers = [v for v in youtube_videos if v.get("type") == "Trailer"]
    video = next(iter(trailers), None) or next(iter(youtube_videos), None)
    if not video:
        return None
    return {
        "key": video["key"],
        "name": video.get("name", ""),
        "type": video.get("type", ""),
    }


def _parse_carousel_photos(response):
    """Return normalized backdrop photos from a TMDB images append."""
    backdrops = response.get("images", {}).get("backdrops", []) or []
    return [
        {
            "file_path": photo["file_path"],
            "width": photo.get("width"),
            "height": photo.get("height"),
        }
        for photo in backdrops
        if photo.get("file_path")
    ]


def peek_carousel_media(media_type, media_id, season_number=None):
    """Return the cached carousel payload, or None if nothing is cached yet.

    Never triggers a provider fetch -- callers use this to check whether a
    prior ``carousel_media`` call already confirmed there's no trailer/photos,
    so the page can render the plain layout up front instead of paying for
    the lazy carousel round trip again.
    """
    return cache.get(_carousel_cache_key(media_type, media_id, season_number))


def carousel_media(media_type, media_id, season_number=None, language=None):
    """Return {"video": {...}|None, "photos": [...]} for the details carousel.

    Fetched lazily via its own request/cache entry, never folded into the
    movie/tv/season append_to_response calls (those are already close to
    TMDB_APPEND_TO_RESPONSE_MAX_REMOTE_CALLS).
    """
    cache_key = _carousel_cache_key(media_type, media_id, season_number)
    data = cache.get(cache_key)
    if data is not None:
        return data

    if media_type == MediaTypes.MOVIE.value:
        url = f"{base_url}/movie/{media_id}"
    elif media_type == MediaTypes.SEASON.value:
        url = f"{base_url}/tv/{media_id}/season/{season_number}"
    else:
        url = f"{base_url}/tv/{media_id}"

    params = {
        **base_params(language),
        "append_to_response": "videos,images",
    }

    try:
        response = services.api_request(
            Sources.TMDB.value,
            "GET",
            url,
            params=params,
        )
    except requests.exceptions.HTTPError as error:
        handle_error(error)

    data = {
        "video": _parse_carousel_video(response),
        "photos": _parse_carousel_photos(response),
    }
    ttl = (
        CAROUSEL_CACHE_TTL_SUCCESS
        if data["video"] or data["photos"]
        else CAROUSEL_CACHE_TTL_ABSENT
    )
    cache.set(cache_key, data, ttl)
    return data


def _build_tv_crew(response):
    """Build sorted crew list for a TV show, prepending created_by as Creators."""
    crew = get_crew_credits(response.get("aggregate_credits", {}), is_aggregate=True)
    created_by = response.get("created_by") or []
    if not created_by:
        return crew
    creator_ids = {str(c.get("id")) for c in created_by}
    crew = [c for c in crew if c.get("person_id") not in creator_ids]
    creators = [
        {
            "person_id": str(c.get("id")),
            "name": c.get("name", ""),
            "image": get_profile_image_url(c.get("profile_path")),
            "known_for_department": c.get("known_for_department", "Writing"),
            "gender": get_gender(c.get("gender")),
            "department": "Writing",
            "role": "Creator",
            "order": idx,
        }
        for idx, c in enumerate(created_by)
    ]
    return creators + crew


def process_tv(response, media_id=None):
    """Process the metadata for the selected tv show from The Movie Database."""
    media_id = str(media_id) if media_id is not None else str(response["id"])
    num_episodes = response["number_of_episodes"]
    next_episode = response.get("next_episode_to_air")
    last_episode = response.get("last_episode_to_air")
    external_ids = dict(response.get("external_ids", {}) or {})
    override_tvdb_id = get_tvdb_id_override(media_id)
    if override_tvdb_id:
        external_ids["tvdb_id"] = override_tvdb_id

    return {
        "media_id": response["id"],
        "source": Sources.TMDB.value,
        "source_url": f"https://www.themoviedb.org/tv/{response['id']}",
        "media_type": MediaTypes.TV.value,
        **get_title_fields(response),
        "max_progress": num_episodes,
        "image": get_image_url(response["poster_path"]),
        "synopsis": get_synopsis(response["overview"]),
        "genres": get_genres(response["genres"]),
        "score": get_score(response["vote_average"]),
        "score_count": response["vote_count"],
        "details": {
            "format": "TV",
            "first_air_date": get_start_date(response["first_air_date"]),
            "last_air_date": get_start_date(response["last_air_date"]),
            "status": response["status"],
            "seasons": response["number_of_seasons"],
            "episodes": num_episodes,
            "runtime": get_runtime_tv(response["episode_run_time"]),
            "studios": get_companies(response["production_companies"]),
            "country": get_country(response["production_countries"]),
            "languages": get_languages(response["spoken_languages"]),
        },
        "cast": get_cast_credits(
            response.get("aggregate_credits", {}),
            is_aggregate=True,
        ),
        "crew": _build_tv_crew(response),
        "studios_full": get_companies_full(response.get("production_companies")),
        "related": {
            "seasons": get_related(
                response["seasons"],
                MediaTypes.SEASON.value,
                response,
                tv_media_id=media_id,
            ),
            "recommendations": get_related(
                response.get("recommendations", {}).get("results", [])[:15],
                MediaTypes.TV.value,
            ),
        },
        "tvdb_id": external_ids.get("tvdb_id"),
        "provider_external_ids": external_ids,
        "external_links": get_external_links(external_ids),
        "last_episode_season": last_episode["season_number"] if last_episode else None,
        "next_episode_season": next_episode["season_number"] if next_episode else None,
        "providers": response.get("watch/providers", {}).get("results", {}),
    }


def process_season(response, providers_response, credits_response=None):
    """Process the metadata for the selected season from The Movie Database."""
    episodes = response["episodes"]
    num_episodes = len(episodes)

    runtimes = []
    total_runtime = 0
    score_count = 0

    for episode in episodes:
        if episode["runtime"] is not None:
            runtimes.append(episode["runtime"])
            total_runtime += episode["runtime"]
        score_count += episode["vote_count"]

    avg_runtime = (
        get_readable_duration(sum(runtimes) / len(runtimes)) if runtimes else None
    )
    total_runtime = get_readable_duration(total_runtime) if total_runtime else None
    credits_response = credits_response if isinstance(credits_response, dict) else {}

    return {
        "source": Sources.TMDB.value,
        "media_type": MediaTypes.SEASON.value,
        "season_title": response["name"],
        "max_progress": episodes[-1]["episode_number"] if episodes else 0,
        "image": get_image_url(response["poster_path"]),
        "season_number": response["season_number"],
        "synopsis": get_synopsis(response["overview"]),
        "score": get_score(response["vote_average"]),
        "score_count": score_count,
        "details": {
            "first_air_date": get_start_date(response["air_date"]),
            "last_air_date": get_end_date(response),
            "episodes": num_episodes,
            "runtime": avg_runtime,
            "total_runtime": total_runtime,
        },
        "cast": get_cast_credits(credits_response),
        "crew": get_crew_credits(credits_response),
        "episodes": response["episodes"],
        "providers": providers_response.get("results", {}),
    }


def get_format(media_type):
    """Return media_type capitalized."""
    if media_type == MediaTypes.TV.value:
        return "TV"
    return "Movie"


def get_changed_ids(media_type, max_pages=None):
    """Return changed TMDB ids for the given media type over the last days.

    Capped and cached. The loop was previously unbounded, and TMDB's /changes
    endpoint reports every title changed globally in the window - total_pages can
    run into the hundreds - so one nightly calendar reload could make hundreds of
    sequential API calls through a 3/s rate limiter (issue #521). The first pages
    are the ones that matter: results are ordered by recency, and anything missed
    is picked up by the next night's window.
    """
    end_date = timezone.localdate()
    start_date = end_date - timedelta(days=3)
    cache_key = f"{Sources.TMDB.value}_changes_{media_type}_{end_date.isoformat()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    if max_pages is None:
        max_pages = settings.TMDB_CHANGES_MAX_PAGES

    url = f"{base_url}/{media_type}/changes"
    changed_ids = set()
    page = 1

    while True:
        params = {
            **base_params(),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "page": page,
        }

        try:
            response = services.api_request(
                Sources.TMDB.value,
                "GET",
                url,
                params=params,
            )
        except requests.exceptions.HTTPError as error:
            handle_error(error)

        changed_ids.update(str(result["id"]) for result in response.get("results", []))

        total_pages = response.get("total_pages", 1)
        if page >= total_pages:
            break
        if page >= max_pages:
            logger.info(
                "tmdb_changes_truncated media_type=%s pages=%s of %s",
                media_type,
                page,
                total_pages,
            )
            break
        page += 1

    cache.set(cache_key, changed_ids, timeout=TMDB_CHANGES_CACHE_TIMEOUT)
    return changed_ids


def tv_changes():
    """Return changed TV ids from TMDB for the last days across all pages."""
    return get_changed_ids(MediaTypes.TV.value)


def movie_changes():
    """Return changed movie ids from TMDB for the last days across all pages."""
    return get_changed_ids(MediaTypes.MOVIE.value)


def get_image_url(path):
    """Return the image URL for the media."""
    # when no image, value from response is null
    # e.g movie: 445290
    if path:
        return f"https://image.tmdb.org/t/p/w500{path}"
    return settings.IMG_NONE


def get_title(response):
    """Return the title for the media."""
    # tv shows have name instead of title
    try:
        return response["title"]
    except KeyError:
        return response["name"]


def get_original_title(response):
    """Return the original title/name for the media."""
    original_title = response.get("original_title") or response.get("original_name")
    if original_title:
        return original_title

    alternative_title = get_preferred_alternative_title(
        response,
        get_localized_title(response),
    )
    if alternative_title:
        return alternative_title

    return original_title


def get_localized_title(response):
    """Return the localized title/name for the media."""
    return response.get("title") or response.get("name")


def get_preferred_alternative_title(response, current_title=None):
    """Pick a useful alternate TMDB title when primary/original are missing."""
    preferred_regions = {"JP", "KR", "CN", "TW"}
    candidates = []

    alternative_titles = response.get("alternative_titles") or {}
    entries = (
        alternative_titles.get("results") or alternative_titles.get("titles") or []
    )

    current_norm = str(current_title).strip().casefold() if current_title else None
    for entry in entries:
        alt_title = str(entry.get("title") or "").strip()
        if not alt_title:
            continue
        if current_norm and alt_title.casefold() == current_norm:
            continue
        region = str(entry.get("iso_3166_1") or "").upper()
        # Prioritize regions that frequently contain original/anime-native titles.
        score = 0 if region in preferred_regions else 1
        candidates.append((score, alt_title))

    if not candidates:
        return None

    candidates.sort(key=lambda row: (row[0], row[1]))
    return candidates[0][1]


def get_title_fields(response):
    """Return normalized title fields for TMDB metadata."""
    original_title = get_original_title(response)
    localized_title = get_localized_title(response) or original_title

    return {
        "title": localized_title or original_title or "",
        "original_title": original_title,
        "localized_title": localized_title,
    }


def get_year(media):
    """Extract a release or first air year from a TMDB search result."""
    date_value = media.get("release_date") or media.get("first_air_date")
    if not date_value:
        return None

    try:
        return int(str(date_value).split("-")[0])
    except (TypeError, ValueError):
        return None


def get_start_date(date):
    """Return the start date for the media."""
    # when unknown date, value from response is empty string
    # e.g movie: 445290
    if date == "" or not date:
        return None

    try:
        from datetime import datetime

        from django.utils import timezone

        # TMDB returns dates in YYYY-MM-DD format
        if isinstance(date, str):
            # Parse the date string and convert to timezone-aware datetime
            date_obj = datetime.strptime(date, "%Y-%m-%d")  # noqa: DTZ007  # date-only value; no timezone applies
            return timezone.make_aware(date_obj, timezone.get_current_timezone())

    except (ValueError, TypeError):
        # If parsing fails, return the original value
        return date
    else:
        return date


def get_end_date(response):
    """Return the last air date for the season."""
    if response["episodes"]:
        last_episode_date = response["episodes"][-1]["air_date"]
        if last_episode_date:
            try:
                from datetime import datetime

                from django.utils import timezone

                # TMDB returns dates in YYYY-MM-DD format
                date_obj = datetime.strptime(last_episode_date, "%Y-%m-%d")  # noqa: DTZ007  # date-only value; no timezone applies
                return timezone.make_aware(date_obj, timezone.get_current_timezone())
            except (ValueError, TypeError):
                # If parsing fails, return the original value
                return last_episode_date

        return last_episode_date

    return None


def get_synopsis(text):
    """Return the synopsis for the media."""
    # when unknown synopsis, value from response is empty string
    # e.g movie: 445290
    if text == "":
        return "No synopsis available."
    return text


def format_currency(value):
    """Return a formatted USD string for a TMDB budget/revenue value, or None if zero/missing."""
    if not value:
        return None
    return f"${int(value):,}"


def get_readable_duration(duration):
    """Convert duration in minutes to a readable format."""
    # if unknown movie runtime, value from response is 0
    # e.g movie: 274613
    if duration:
        hours, minutes = divmod(int(duration), 60)
        return f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
    return None


def get_runtime_tv(runtime):
    """Return the runtime for the tv show."""
    # when unknown runtime, value from response is empty list
    # e.g: tv:66672
    if runtime:
        return get_readable_duration(runtime[0])
    return None


def season_scores_count(response):
    """Return the scores count for the season."""
    return sum(episode["vote_count"] for episode in response["episodes"])


def get_genres(genres):
    """Return the genres for the media."""
    # when unknown genres, value from response is empty list
    # e.g tv: 24795
    if genres:
        return [genre["name"] for genre in genres]
    return None


def get_country(countries):
    """Return the production country for the media."""
    # when unknown production country, value from response is empty list
    # e.g tv: 24795
    if countries:
        return countries[0]["name"]
    return None


def get_languages(languages):
    """Return the languages for the media."""
    # when unknown spoken languages, value from response is empty list
    # e.g tv: 24795
    if languages:
        return [language["english_name"] for language in languages]
    return None


def get_companies(companies):
    """Return the production companies for the media."""
    # when unknown production companies, value from response is empty list
    # e.g tv: 24795
    if companies:
        return [company["name"] for company in companies[:3]]
    return None


def get_keyword_names(keyword_payload):
    """Return normalized keyword names from a TMDB keyword payload."""
    keyword_rows = []
    if isinstance(keyword_payload, dict):
        keyword_rows = (
            keyword_payload.get("keywords") or keyword_payload.get("results") or []
        )
    elif isinstance(keyword_payload, list):
        keyword_rows = keyword_payload

    keywords = []
    for row in keyword_rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if name:
            keywords.append(name)
    return keywords


def get_movie_certification(release_dates_payload):
    """Return the preferred movie certification from TMDB release dates."""
    results = []
    if isinstance(release_dates_payload, dict):
        results = release_dates_payload.get("results") or []
    fallback = ""
    for result in results:
        if not isinstance(result, dict):
            continue
        release_rows = result.get("release_dates") or []
        for release in release_rows:
            if not isinstance(release, dict):
                continue
            certification = str(release.get("certification") or "").strip()
            if not certification:
                continue
            if str(result.get("iso_3166_1") or "").upper() == "US":
                return certification
            if not fallback:
                fallback = certification
    return fallback


def get_profile_image_url(path, size="w185"):
    """Return a profile image URL for cast/crew members."""
    if path:
        return f"https://image.tmdb.org/t/p/{size}{path}"
    return settings.IMG_NONE


def get_carousel_image_url(path, size="w1280"):
    """Return a media-details carousel image URL (backdrops/photos)."""
    if path:
        return f"https://image.tmdb.org/t/p/{size}{path}"
    return settings.IMG_NONE


def _upgrade_person_image_url(url):
    """Upgrade legacy person profile URLs to a higher-resolution size."""
    if not url:
        return url
    if "/t/p/w185/" in url:
        return url.replace("/t/p/w185/", "/t/p/h632/")
    return url


def get_gender(value):
    """Normalize TMDB gender integer into a stable string."""
    if value == 1:
        return "female"
    if value == TMDB_GENDER_MALE:
        return "male"
    if value == TMDB_GENDER_NON_BINARY:
        return "non_binary"
    return "unknown"


def get_cast_credits(credits_data, is_aggregate=False):
    """Return normalized cast entries."""
    cast_entries = []
    cast_list = credits_data.get("cast", []) if isinstance(credits_data, dict) else []
    if not isinstance(cast_list, list):
        cast_list = []

    for cast in cast_list:
        if not isinstance(cast, dict):
            continue
        role_value = cast.get("character", "")
        episode_count = None
        if is_aggregate:
            # TMDB aggregate_credits.roles may be a list of role dicts, or a
            # list of single-element lists wrapping those dicts. Normalize to
            # a flat list of dicts so both shapes aggregate correctly. This
            # unwraps exactly one level: a role element that is itself a list
            # is iterated, anything else is treated as a single role. Deeper
            # nesting is not a real TMDB shape and is dropped by the dict
            # filter below. A bare dict (rather than a list) is accepted too.
            raw_roles = cast.get("roles") or []
            if isinstance(raw_roles, dict):
                raw_roles = [raw_roles]
            roles = [
                role
                for inner in raw_roles
                for role in (inner if isinstance(inner, list) else [inner])
                if isinstance(role, dict)
            ]
            if roles:
                # episode_count is not always numeric; comparing a string
                # against an int in max() raises, so rank on the numeric ones
                # and only fall back to the raw list if none qualify.
                valid_roles = [
                    role
                    for role in roles
                    if isinstance(role.get("episode_count"), (int, float))
                ]
                top_role = max(
                    valid_roles or roles,
                    key=lambda role: (
                        role.get("episode_count")
                        if isinstance(role.get("episode_count"), (int, float))
                        else 0
                    ),
                )
                role_char = top_role.get("character")
                # Only a non-empty role replaces the outer `character`: a blank
                # or zero aggregate role must not erase the fallback.
                if role_char and not isinstance(role_char, (dict, list)):
                    role_value = (
                        role_char if isinstance(role_char, str) else str(role_char)
                    )
            # episode_count is the person's total appearances across all their
            # roles in this show, not episodes as the selected top_role only.
            total_eps = sum(
                role.get("episode_count") or 0
                for role in roles
                if isinstance(role.get("episode_count"), (int, float))
            )
            episode_count = total_eps if total_eps > 0 else None

        cast_entries.append(
            {
                "person_id": str(cast.get("id")),
                "name": cast.get("name", "") if isinstance(cast.get("name"), str) else str(cast.get("name") or ""),
                "image": get_profile_image_url(cast.get("profile_path")),
                "known_for_department": cast.get("known_for_department", "") if isinstance(cast.get("known_for_department"), str) else "",
                "gender": get_gender(cast.get("gender")),
                "department": cast.get("known_for_department", "Acting") if isinstance(cast.get("known_for_department"), str) else "Acting",
                "role": str(role_value or ""),
                "order": cast.get("order") if isinstance(cast.get("order"), (int, float)) else None,
                "episode_count": episode_count,
            },
        )

    cast_entries.sort(
        key=lambda row: (
            row.get("order") is None,
            row.get("order") if row.get("order") is not None else 999999,
        ),
    )
    return cast_entries


def get_crew_credits(credits_data, is_aggregate=False):
    """Return normalized crew entries."""
    crew_entries = []
    crew_list = credits_data.get("crew", []) if isinstance(credits_data, dict) else []
    if not isinstance(crew_list, list):
        crew_list = []

    for crew in crew_list:
        if not isinstance(crew, dict):
            continue
        department = crew.get("department", "") if isinstance(crew.get("department"), str) else ""

        if is_aggregate:
            raw_jobs = crew.get("jobs", [])
            if isinstance(raw_jobs, list):
                jobs = [job for job in raw_jobs if isinstance(job, dict)]
            elif isinstance(raw_jobs, dict):
                jobs = [raw_jobs]
            else:
                jobs = []

            if not jobs:
                crew_entries.append(
                    {
                        "person_id": str(crew.get("id")),
                        "name": crew.get("name", "") if isinstance(crew.get("name"), str) else str(crew.get("name") or ""),
                        "image": get_profile_image_url(crew.get("profile_path")),
                        "known_for_department": crew.get("known_for_department", "") if isinstance(crew.get("known_for_department"), str) else "",
                        "gender": get_gender(crew.get("gender")),
                        "department": department,
                        "role": "",
                        "order": crew.get("order") if isinstance(crew.get("order"), (int, float)) else None,
                    },
                )
                continue

            seen_jobs = set()
            for job_data in jobs:
                if not isinstance(job_data, dict):
                    continue
                job_name = (str(job_data.get("job") or "")).strip()
                if not job_name or job_name.lower() in seen_jobs:
                    continue
                seen_jobs.add(job_name.lower())
                job_dept = job_data.get("department", "") if isinstance(job_data.get("department"), str) else ""
                crew_entries.append(
                    {
                        "person_id": str(crew.get("id")),
                        "name": crew.get("name", "") if isinstance(crew.get("name"), str) else str(crew.get("name") or ""),
                        "image": get_profile_image_url(crew.get("profile_path")),
                        "known_for_department": crew.get("known_for_department", "") if isinstance(crew.get("known_for_department"), str) else "",
                        "gender": get_gender(crew.get("gender")),
                        "department": department or job_dept,
                        "role": job_name,
                        "order": crew.get("order") if isinstance(crew.get("order"), (int, float)) else None,
                    },
                )
            continue

        crew_entries.append(
            {
                "person_id": str(crew.get("id")),
                "name": crew.get("name", "") if isinstance(crew.get("name"), str) else str(crew.get("name") or ""),
                "image": get_profile_image_url(crew.get("profile_path")),
                "known_for_department": crew.get("known_for_department", "") if isinstance(crew.get("known_for_department"), str) else "",
                "gender": get_gender(crew.get("gender")),
                "department": department,
                "role": crew.get("job", "") if isinstance(crew.get("job"), str) else str(crew.get("job") or ""),
                "order": crew.get("order") if isinstance(crew.get("order"), (int, float)) else None,
            },
        )

    crew_priority_exact = {
        "creator": 0,
        "created by": 0,
        "showrunner": 0,
        "director": 1,
        "co-director": 1,
        "screenplay": 2,
        "original screenplay": 2,
        "screenwriter": 2,
        "co-screenplay": 2,
        "writer": 3,
        "story": 3,
        "story by": 3,
        "original story": 3,
    }

    def _crew_priority(entry):
        role_lower = (entry.get("role") or "").lower().strip()
        return crew_priority_exact.get(role_lower, 99)

    crew_entries.sort(
        key=lambda row: (
            _crew_priority(row),
            row.get("department", "").lower(),
            row.get("order") is None,
            row.get("order") if row.get("order") is not None else 999999,
        ),
    )
    return crew_entries


def get_companies_full(companies):
    """Return normalized studio/company entries."""
    studios = [
        {
            "studio_id": str(company.get("id")),
            "name": company.get("name", ""),
            "logo": get_profile_image_url(company.get("logo_path")),
            "origin_country": company.get("origin_country", ""),
        }
        for company in companies or []
    ]
    studios.sort(key=lambda row: row.get("name", "").lower())
    return studios


def get_score(score):
    """Return the score for the media with one decimal place."""
    # when unknown score, value from response is 0.0
    if score is None:
        return None

    return round(score, 1)


def get_related(related_medias, media_type, parent_response=None, tv_media_id=None):
    """Return list of related media for the selected media."""
    related = []
    for media in related_medias:
        # For seasons, use TV show poster as fallback if season doesn't have its own poster
        if media_type == MediaTypes.SEASON.value and parent_response:
            season_poster_path = media.get("poster_path")
            # If season doesn't have a poster, use TV show poster as fallback
            if season_poster_path:
                season_image = get_image_url(season_poster_path)
            else:
                season_image = get_image_url(parent_response.get("poster_path"))
        else:
            season_image = get_image_url(media["poster_path"])

        data = {
            "source": Sources.TMDB.value,
            "media_type": media_type,
            "image": season_image,
        }
        if media_type == MediaTypes.SEASON.value:
            episode_count = media.get("episode_count")
            data["media_id"] = (
                tv_media_id if tv_media_id is not None else parent_response["id"]
            )
            data["title"] = get_title(parent_response)
            data["original_title"] = get_original_title(parent_response)
            data["localized_title"] = get_localized_title(parent_response)
            data["season_number"] = media["season_number"]
            data["season_title"] = media["name"]
            # Use the same date processing logic as process_season for consistency
            data["first_air_date"] = get_start_date(media["air_date"])
            # For last_air_date, we need to simulate get_end_date logic since we don't have episode data here
            # This will be updated when the detailed season data is fetched
            data["last_air_date"] = None
            data["max_progress"] = episode_count
            data["episode_count"] = episode_count
            data["score"] = get_score(media.get("vote_average"))
            data["score_count"] = media.get("vote_count")
            data["details"] = {
                "episodes": episode_count,
            }
        else:
            data["media_id"] = media["id"]
            data["title"] = get_title(media)
            data["original_title"] = get_original_title(media)
            data["localized_title"] = get_localized_title(media)
            data["year"] = get_year(media)
        related.append(data)
    return related


def get_collection(collection_response):
    """Format media collection list to match related media."""

    def date_key(media):
        date = media.get("release_date", "")
        if date is None or date == "":
            # If release date is unknown, sort by title after known releases
            title = get_title(media)
            date = f"9999-99-99-{title}"
        return date

    parts = sorted(collection_response.get("parts", []), key=date_key)
    return [
        {
            "source": Sources.TMDB.value,
            "media_type": MediaTypes.MOVIE.value,
            "image": get_image_url(media["poster_path"]),
            "media_id": media["id"],
            "title": get_title(media),
            "original_title": get_original_title(media),
            "localized_title": get_localized_title(media),
            "year": get_year(media),
        }
        for media in parts
    ]


def _person_filmography_entries(combined_credits):
    """Normalize cast and crew filmography entries."""
    entries = []
    cast = (
        combined_credits.get("cast", []) if isinstance(combined_credits, dict) else []
    )
    crew = (
        combined_credits.get("crew", []) if isinstance(combined_credits, dict) else []
    )

    for media in cast:
        media_type = media.get("media_type")
        if media_type not in (MediaTypes.MOVIE.value, MediaTypes.TV.value):
            continue
        entries.append(
            {
                "media_id": str(media.get("id")),
                "source": Sources.TMDB.value,
                "media_type": media_type,
                "title": get_title(media),
                "original_title": get_original_title(media),
                "localized_title": get_localized_title(media),
                "image": get_image_url(media.get("poster_path")),
                "year": get_year(media),
                "release_date": get_start_date(
                    media.get("release_date") or media.get("first_air_date"),
                ),
                "credit_type": "cast",
                "role": media.get("character") or "",
                "department": "Acting",
                "vote_average": media.get("vote_average"),
                "vote_count": media.get("vote_count"),
                "popularity": media.get("popularity"),
            },
        )

    for media in crew:
        media_type = media.get("media_type")
        if media_type not in (MediaTypes.MOVIE.value, MediaTypes.TV.value):
            continue
        entries.append(
            {
                "media_id": str(media.get("id")),
                "source": Sources.TMDB.value,
                "media_type": media_type,
                "title": get_title(media),
                "original_title": get_original_title(media),
                "localized_title": get_localized_title(media),
                "image": get_image_url(media.get("poster_path")),
                "year": get_year(media),
                "release_date": get_start_date(
                    media.get("release_date") or media.get("first_air_date"),
                ),
                "credit_type": "crew",
                "role": media.get("job") or "",
                "department": media.get("department") or "",
                "vote_average": media.get("vote_average"),
                "vote_count": media.get("vote_count"),
                "popularity": media.get("popularity"),
            },
        )

    # Deduplicate by media + credit + role in case TMDB returns duplicates.
    deduped = {}
    for entry in entries:
        key = (
            entry["media_type"],
            entry["media_id"],
            entry["credit_type"],
            entry["role"],
        )
        if key not in deduped:
            deduped[key] = entry

    filmography = list(deduped.values())
    filmography.sort(
        key=lambda entry: (
            entry.get("release_date") is None,
            entry.get("release_date") or 0,
            entry.get("year") or 0,
        ),
        reverse=True,
    )
    return filmography


def search_person_profile(name, language=None):
    """Look up a headshot and gender by name, with no id cross-reference.

    This is a name match only.

    Used to backfill artwork and gender for people synced from a source with no
    (or unusably sparse) profile data of its own — e.g. IMDB-sourced game cast,
    see app.services.imdb_game_credits. Returns {"image": str|None, "gender": str}
    (gender is one of get_gender()'s values, "unknown" if TMDB has no data either),
    or None if no name match was found at all.
    """
    if not name:
        return None

    cache_key = (
        f"{Sources.TMDB.value}_person_search_profile_{name}"
        f"{_language_suffix(language)}"
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached or None

    url = f"{base_url}/search/person"
    params = {**base_params(language), "query": name}
    try:
        response = services.api_request(
            Sources.TMDB.value,
            "GET",
            url,
            params=params,
        )
    except requests.exceptions.HTTPError as error:
        handle_error(error)
        return None

    results = response.get("results") or []
    if not results:
        cache.set(cache_key, "")
        return None

    top_result = results[0]
    image = get_profile_image_url(top_result.get("profile_path"), size="h632")
    if image == settings.IMG_NONE:
        image = None
    profile = {"image": image, "gender": get_gender(top_result.get("gender"))}

    cache.set(cache_key, profile)
    return profile


def person(person_id, language=None):
    """Return metadata for a TMDB person profile."""
    cache_key = f"{Sources.TMDB.value}_person_{person_id}{_language_suffix(language)}"
    data = cache.get(cache_key)

    if data is not None:
        upgraded_image = _upgrade_person_image_url(data.get("image"))
        if upgraded_image != data.get("image"):
            data = {**data, "image": upgraded_image}
            cache.set(cache_key, data)
        return data

    url = f"{base_url}/person/{person_id}"
    params = {
        **base_params(language),
        "append_to_response": "combined_credits,external_ids",
    }
    try:
        response = services.api_request(
            Sources.TMDB.value,
            "GET",
            url,
            params=params,
        )
    except requests.exceptions.HTTPError as error:
        handle_error(error)

    data = {
        "person_id": str(response.get("id")),
        "source": Sources.TMDB.value,
        "name": response.get("name", ""),
        "image": get_profile_image_url(
            response.get("profile_path"),
            size="h632",
        ),
        "biography": response.get("biography") or "",
        "known_for_department": response.get("known_for_department") or "",
        "gender": get_gender(response.get("gender")),
        "birth_date": response.get("birthday"),
        "death_date": response.get("deathday"),
        "place_of_birth": response.get("place_of_birth") or "",
        "filmography": _person_filmography_entries(
            response.get("combined_credits", {}),
        ),
    }

    cache.set(cache_key, data)

    return data


def filter_providers(all_providers, region):
    """Filter watch providers by region."""
    if region == "":
        return None

    if not all_providers:
        return []

    # Create a dict to get rid of duplicates across different provider types
    region_providers = all_providers.get(region, {})
    flatrate_providers = region_providers.get("flatrate", [])
    free_providers = region_providers.get("free", [])
    providers = {}
    for provider in [*flatrate_providers, *free_providers]:
        providers[provider.get("provider_id")] = provider

    # Convert dict back to list and add image URLs
    providers = list(providers.values())
    for provider in providers:
        provider["image"] = get_image_url(provider.get("logo_path"))

    providers.sort(key=lambda e: e.get("display_priority", 999))
    return providers


def item_watch_provider_names(item, region):
    """Return sorted flatrate/free watch-provider names for an item's region.

    Returns None when no region is configured, so callers can distinguish
    "region not set" (hide the filter) from "no providers for this region".
    """
    if not region or region == "UNSET":
        return None

    providers = filter_providers(item.watch_providers, region) or []
    return sorted({p["provider_name"] for p in providers if p.get("provider_name")})


def process_episodes(season_metadata, episodes_in_db, season=None):
    """Process the episodes for the selected season."""
    episodes_metadata = []
    episode_backdrop = None
    tvdb_episode_images = {}

    # Convert the queryset to a dictionary for efficient lookups
    tracked_episodes = {}
    for ep in episodes_in_db:
        episode_number = ep.item.episode_number
        if episode_number not in tracked_episodes:
            tracked_episodes[episode_number] = []
        tracked_episodes[episode_number].append(ep)

    if season_metadata.get("media_id"):
        episode_backdrop = helpers.get_tmdb_backdrop_image(
            MediaTypes.TV.value,
            season_metadata["media_id"],
        )
        tvdb_episode_images = get_tvdb_episode_image_map(
            season_metadata.get("tvdb_id"),
            season_metadata.get("season_number"),
            tmdb_media_id=season_metadata.get("media_id"),
        )
    elif season_metadata.get("tvdb_id"):
        tvdb_episode_images = get_tvdb_episode_image_map(
            season_metadata.get("tvdb_id"),
            season_metadata.get("season_number"),
            tmdb_media_id=season_metadata.get("media_id"),
        )

    # TVDB season payloads are also processed here, so episode rows must keep the
    # season's own source. Hardcoding TMDB sends track/detail routes for a TVDB
    # show to /tmdb/<tvdb_id>, which 404s at TMDB.
    episode_source = season_metadata.get("source") or Sources.TMDB.value

    for episode in season_metadata["episodes"]:
        episode_number = episode["episode_number"]
        pass_plays, all_plays = helpers.split_pass_history(
            tracked_episodes.get(episode_number, []),
            season,
        )

        # Convert air_date to datetime object if it's a string
        air_date = episode.get("air_date")
        if air_date and isinstance(air_date, str):
            try:
                from datetime import datetime

                from django.utils import timezone

                normalized_air_date = air_date.replace("Z", "+00:00")
                if "T" in normalized_air_date:
                    date_obj = datetime.fromisoformat(normalized_air_date)
                else:
                    # TMDB returns dates in YYYY-MM-DD format
                    date_obj = datetime.strptime(normalized_air_date, "%Y-%m-%d")  # noqa: DTZ007  # date-only value; no timezone applies
                air_date = (
                    date_obj
                    if timezone.is_aware(date_obj)
                    else timezone.make_aware(
                        date_obj,
                        timezone.get_current_timezone(),
                    )
                )
            except (ValueError, TypeError):
                # If parsing fails, keep the original value
                pass

        image, image_source = helpers.resolve_image_with_fallback(
            get_image_url(episode["still_path"]) if episode.get("still_path") else None,
            tvdb_episode_images.get(str(episode_number)),
            helpers.first_real_image(episode.get("image"), default=None),
            episode_backdrop,
        )

        episodes_metadata.append(
            {
                "media_id": season_metadata["media_id"],
                "media_type": MediaTypes.EPISODE.value,
                "source": episode_source,
                "season_number": season_metadata["season_number"],
                "episode_number": episode_number,
                "air_date": air_date,  # when unknown, response returns null
                "image": image,
                "image_source": image_source,
                "title": episode.get("name") or episode.get("title") or "",
                "overview": episode.get("overview") or "",
                # Plays in the current rewatch pass — everything watched
                # when no pass is open — so the row renders unwatched again
                # while a rewatch is under way.
                "history": pass_plays,
                "all_history": all_plays,
                "runtime": get_readable_duration(episode.get("runtime")),
            },
        )
    return episodes_metadata


def find_next_episode(episode_number, episodes_metadata):
    """Return the first known episode number after the current one."""
    try:
        current_episode_number = int(episode_number or 0)
    except (TypeError, ValueError):
        current_episode_number = 0

    episode_numbers = sorted(
        {
            int(episode["episode_number"])
            for episode in episodes_metadata or []
            if episode.get("episode_number") is not None
        },
    )
    return next(
        (
            candidate
            for candidate in episode_numbers
            if candidate > current_episode_number
        ),
        None,
    )


EPISODE_ERROR_CACHE_KEY = "__error_status__"
EPISODE_ERROR_NOT_FOUND_SECONDS = 60 * 60
EPISODE_ERROR_TRANSIENT_SECONDS = 60 * 5


def _raise_cached_episode_error(status_code):
    """Re-raise a negative-cached episode lookup without hitting the API."""
    synthetic = SimpleNamespace(
        response=SimpleNamespace(status_code=status_code, headers={}),
    )
    raise services.ProviderAPIError(
        Sources.TMDB.value,
        synthetic,
        "cached episode lookup failure",
    )


def episode(media_id, season_number, episode_number, language=None):
    """Return the metadata for the selected episode from The Movie Database."""
    cache_key = (
        f"{Sources.TMDB.value}_{MediaTypes.EPISODE.value}_{media_id}_{season_number}_"
        f"{episode_number}{_language_suffix(language)}"
    )
    data = cache.get(cache_key)

    if isinstance(data, dict) and EPISODE_ERROR_CACHE_KEY in data:
        _raise_cached_episode_error(data[EPISODE_ERROR_CACHE_KEY])

    if data is None:
        url = (
            f"{base_url}/tv/{media_id}/season/{season_number}/episode/{episode_number}"
        )
        params = {
            **base_params(language),
            "append_to_response": "credits",
        }

        try:
            response = services.api_request(
                Sources.TMDB.value,
                "GET",
                url,
                params=params,
            )
        except requests.exceptions.HTTPError as error:
            # Negative-cache failures so a missing episode (polled every
            # few seconds by the live playback card) doesn't re-block on
            # the network each time.
            status_code = getattr(error.response, "status_code", None)
            if status_code in (requests.codes.not_found, requests.codes.gone):
                cache.set(
                    cache_key,
                    {EPISODE_ERROR_CACHE_KEY: status_code},
                    EPISODE_ERROR_NOT_FOUND_SECONDS,
                )
            elif status_code is not None and status_code >= requests.codes.server_error:
                cache.set(
                    cache_key,
                    {EPISODE_ERROR_CACHE_KEY: status_code},
                    EPISODE_ERROR_TRANSIENT_SECONDS,
                )
            handle_error(error)

        tv_metadata = tv_with_seasons(media_id, [season_number], language)
        season_metadata = tv_metadata.get(f"season/{season_number}", {})

        # TMDB episode payload exposes both regular cast and guest stars.
        # Prefer guest stars for episode-level crediting to avoid attributing
        # season-regular cast to every episode when episode-specific guests exist.
        cast_rows = response.get("guest_stars", []) or []
        if not cast_rows:
            cast_rows = response.get("credits", {}).get("cast", []) or []

        crew_rows = response.get("credits", {}).get("crew", [])
        if not crew_rows:
            crew_rows = response.get("crew", []) or []

        vote_average = response.get("vote_average")
        vote_count = response.get("vote_count")

        data = {
            "title": season_metadata.get("title") or tv_metadata.get("title") or "",
            "original_title": (
                season_metadata.get("original_title")
                or tv_metadata.get("original_title")
            ),
            "localized_title": (
                season_metadata.get("localized_title")
                or tv_metadata.get("localized_title")
            ),
            "season_title": season_metadata.get("season_title")
            or f"Season {season_number}",
            "episode_title": response.get("name") or f"Episode {episode_number}",
            "score": round(vote_average, 1) if vote_average else None,
            "score_count": vote_count or None,
            "cast": get_cast_credits({"cast": cast_rows}),
            "crew": get_crew_credits({"crew": crew_rows}),
        }
        tvdb_episode_images = get_tvdb_episode_image_map(
            tv_metadata.get("tvdb_id"),
            season_number,
            tmdb_media_id=media_id,
        )
        data["image"], data["image_source"] = helpers.resolve_image_with_fallback(
            get_image_url(response.get("still_path")),
            tvdb_episode_images.get(str(episode_number)),
            helpers.get_tmdb_backdrop_image(MediaTypes.TV.value, media_id),
        )

        cache.set(cache_key, data)

    return data


def watch_provider_regions():
    """Return the available watch provider regions from The Movie Database."""
    cache_key = f"{Sources.TMDB.value}_watch_provider_regions"
    data = cache.get(cache_key)

    if data is None:
        url = f"{base_url}/watch/providers/regions"
        params = {**base_params()}

        try:
            response = services.api_request(
                Sources.TMDB.value,
                "GET",
                url,
                params=params,
            )
        except requests.exceptions.HTTPError as error:
            handle_error(error)

        data = [("", "Disabled")]
        regions = response.get("results", [])
        for region in sorted(regions, key=lambda r: r.get("english_name", "")):
            key = region.get("iso_3166_1")
            name = region.get("english_name")
            if key:
                if not name:
                    name = key
                data.append((key, name))

        cache.set(cache_key, data)

    return data


def global_watch_provider_catalog():
    """Return the full TMDB watch-provider catalog (movie + tv), deduped by id.

    Unlike ``filter_providers``, this isn't scoped to a single item or region —
    it's the source list for browsing/pinning providers outside the user's
    home region. This is called on every media-list render (to populate the
    "More" filter panel), so a TMDB outage must degrade to an empty list
    rather than take the page down.
    """
    cache_key = f"{Sources.TMDB.value}_watch_provider_catalog"
    data = cache.get(cache_key)

    if data is None:
        providers = {}
        any_fetch_failed = False
        for media_type in ("movie", "tv"):
            url = f"{base_url}/watch/providers/{media_type}"
            params = {**base_params()}

            try:
                response = services.api_request(
                    Sources.TMDB.value,
                    "GET",
                    url,
                    params=params,
                )
            except (requests.exceptions.RequestException, services.ProviderAPIError):
                logger.warning(
                    "Skipping %s watch-provider catalog fetch due to TMDB API error",
                    media_type,
                )
                any_fetch_failed = True
                continue

            for provider in response.get("results", []):
                provider_id = provider.get("provider_id")
                provider_name = provider.get("provider_name")
                if provider_id is None or not provider_name:
                    continue
                providers[provider_id] = {
                    "provider_id": provider_id,
                    "provider_name": provider_name,
                    "image": get_image_url(provider.get("logo_path")),
                }

        data = sorted(providers.values(), key=lambda p: p["provider_name"].lower())
        if data:
            cache.set(cache_key, data)
        elif any_fetch_failed:
            # Cache the empty result too, just briefly: an outage must not
            # repeat two full-timeout requests on every media-list render.
            cache.set(cache_key, data, WATCH_PROVIDER_CATALOG_FAILURE_CACHE_TIMEOUT)

    return data


def pinned_provider_matches(item, pinned_names):
    """Return providers on ``item`` (any region) whose name is in ``pinned_names``.

    Lets a pinned provider surface on the detail page even when the item is
    only available on it outside the user's home region.
    """
    if not item or not pinned_names or not item.watch_providers:
        return []

    pinned_set = set(pinned_names)
    providers = {}
    for region_data in item.watch_providers.values():
        if not isinstance(region_data, dict):
            continue
        for provider in [
            *region_data.get("flatrate", []),
            *region_data.get("free", []),
        ]:
            if provider.get("provider_name") not in pinned_set:
                continue
            providers[provider.get("provider_id")] = provider

    matches = list(providers.values())
    for provider in matches:
        provider["image"] = get_image_url(provider.get("logo_path"))

    matches.sort(key=lambda e: e.get("display_priority", 999))
    return matches


def metadata_languages():
    """Return the available metadata languages from The Movie Database."""
    cache_key = f"{Sources.TMDB.value}_metadata_languages"
    data = cache.get(cache_key)

    if data is None:
        url = f"{base_url}/configuration/languages"
        params = {**base_params()}

        try:
            response = services.api_request(
                Sources.TMDB.value,
                "GET",
                url,
                params=params,
            )
        except requests.exceptions.HTTPError as error:
            handle_error(error)

        data = [("", f"Server Default ({settings.TMDB_LANG})")]
        for lang in sorted(response, key=lambda entry: entry.get("english_name", "")):
            code = lang.get("iso_639_1")
            name = lang.get("english_name")
            if code:
                data.append((code, name or code))

        cache.set(cache_key, data)

    return data
