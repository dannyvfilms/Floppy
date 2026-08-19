"""Remap Plex/TVDB episode numbering onto TMDB's season structure.

Plex libraries follow TVDB numbering while TMDB may split, merge, or omit
seasons entirely. Both the history importer and the live webhook path need to
recover the real TMDB (season, episode) instead of dropping or mis-filing the
watch, so the strategies live here and each caller supplies its own season
loader (and therefore its own caching).
"""

import logging

import app
from app.log_safety import exception_summary
from app.providers import services

logger = logging.getLogger(__name__)


def episode_in_season(episode_number, season_metadata: dict) -> bool:
    """Return whether the episode number exists in the season payload."""
    return any(
        ep.get("episode_number") == episode_number
        for ep in season_metadata.get("episodes", [])
    )


def remap_via_tmdb_find(external_ids, actual_tmdb_id, load_season, find_cache=None):
    """Resolve TMDB numbering from the episode-level TVDB/IMDB Guid.

    Args:
        external_ids: Dict of episode-level external IDs (tvdb_id, imdb_id).
        actual_tmdb_id: The resolved show's TMDB ID; results for other shows
            are rejected.
        load_season: Callable taking a season number and returning that
            season's metadata payload, or None.
        find_cache: Optional dict reused across calls to memoize TMDB find
            responses (negative results included).

    Returns:
        tuple: (season_number, episode_number, season_metadata), or None.
    """
    external_ids = external_ids or {}
    actual_tmdb_id = str(actual_tmdb_id)

    for ext_type in ("tvdb_id", "imdb_id"):
        ext_id = external_ids.get(ext_type)
        if not ext_id:
            continue

        cache_key = (ext_type, str(ext_id))
        if find_cache is not None and cache_key in find_cache:
            found = find_cache[cache_key]
        else:
            try:
                response = app.providers.tmdb.find(ext_id, ext_type)
            except services.ProviderAPIError as exc:
                logger.debug(
                    "TMDB find failed during Plex episode remap: %s",
                    exception_summary(exc),
                )
                continue
            results = response.get("tv_episode_results") or []
            found = None
            if results:
                found = (
                    str(results[0].get("show_id")),
                    results[0].get("season_number"),
                    results[0].get("episode_number"),
                )
            if find_cache is not None:
                find_cache[cache_key] = found

        if not found:
            continue

        show_id, season_number, episode_number = found
        if show_id != actual_tmdb_id or season_number is None or episode_number is None:
            continue

        season_metadata = load_season(season_number)
        if season_metadata and episode_in_season(episode_number, season_metadata):
            return season_number, episode_number, season_metadata

    return None


def _spill_forward(season_number, episode_number, episode_counts):
    """Walk forward through seasons, spilling the episode offset over.

    Returns (target_season, remaining_episode_number), or (None, None) when the
    offset runs past the last known season.
    """
    if season_number not in episode_counts:
        return None, None

    remaining = episode_number
    target_season = season_number
    while target_season in episode_counts:
        count = episode_counts[target_season]
        if remaining <= count:
            return target_season, remaining
        remaining -= count
        target_season += 1
    return None, None


def remap_via_cumulative_numbering(
    season_number,
    episode_number,
    tv_metadata: dict,
    load_season,
):
    """Carry a TVDB-numbered episode into the right TMDB split season.

    TVDB often keeps one long season where TMDB splits several (e.g.
    Demon Slayer TVDB S2E1-18 = TMDB S2E1-7 + S3E1-11). Walk TMDB seasons
    from the given season and spill the episode offset forward.
    """
    try:
        season_number = int(season_number)
        episode_number = int(episode_number)
    except (TypeError, ValueError):
        return None
    if season_number <= 0 or episode_number <= 0:
        return None

    seasons = (tv_metadata.get("related") or {}).get("seasons") or []
    episode_counts: dict[int, int] = {}
    for season in seasons:
        number = season.get("season_number")
        count = season.get("episode_count")
        if isinstance(number, int) and number > 0 and isinstance(count, int):
            episode_counts[number] = count

    target_season, remaining = _spill_forward(
        season_number,
        episode_number,
        episode_counts,
    )
    # target_season == season_number means no overflow happened, so the episode
    # is genuinely missing on TMDB rather than living in a later split season.
    if target_season is None or target_season == season_number:
        return None

    season_metadata = load_season(target_season)
    if season_metadata and episode_in_season(remaining, season_metadata):
        return target_season, remaining, season_metadata
    return None
