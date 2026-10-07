import contextlib
import time

from django.conf import settings
from django.core.cache import cache

import app

CACHE_KEY = "anibridge_v3_mapping_data"
URL = (
    "https://github.com/anibridge/anibridge-mappings/releases/download/v3/"
    "mappings.min.json"
)

# Minimum "provider:id" descriptor components; a third "sNN" component adds a season.
DESCRIPTOR_MIN_PARTS = 2
DESCRIPTOR_SEASON_PART_INDEX = 3

# The mapping table is a multi-MB blob that changes at most once a day (see
# CACHE_TIMEOUT), but this is called on every media-server webhook event.
# Memoize it per-process for a short window to avoid re-transferring and
# re-deserializing it from Redis on every call.
_LOCAL_CACHE_TTL_SECONDS = 300
_local_cache: dict[str, object] = {"data": None, "fetched_at": 0.0}


def fetch_mapping_data():
    """Fetch anime mapping data with an optional local data override."""
    mapping_override = getattr(settings, "ANIBRIDGE_MAPPING_DATA_OVERRIDE", None)
    if mapping_override is not None:
        return mapping_override

    now = time.monotonic()
    if (
        _local_cache["data"] is not None
        and now - _local_cache["fetched_at"] < _LOCAL_CACHE_TTL_SECONDS
    ):
        return _local_cache["data"]

    data = cache.get(CACHE_KEY)
    if data is None:
        data = app.providers.services.api_request(
            "GITHUB",
            "GET",
            URL,
        )
        cache.set(CACHE_KEY, data)

    _local_cache["data"] = data
    _local_cache["fetched_at"] = now
    return data


def get_mal_id_from_anidb(mapping_data, anidb_id, episode_number):
    """Find a MAL ID from AniBridge's AniDB-based anime mappings."""
    descriptors = [f"anidb:{anidb_id}:R"]
    descriptors.extend(
        descriptor
        for descriptor in mapping_data
        if descriptor.startswith(f"anidb:{anidb_id}:") and descriptor not in descriptors
    )

    for descriptor in descriptors:
        mal_id, mal_episode_number = _get_mal_mapping(
            mapping_data,
            descriptor,
            episode_number,
        )
        if mal_id:
            return mal_id, mal_episode_number
    return None, None


def get_mal_id_from_tvdb(
    mapping_data,
    tvdb_id,
    season_number,
    episode_number,
):
    """Find a MAL ID from AniBridge's TVDB-based anime mappings."""
    return _get_mal_mapping(
        mapping_data,
        f"tvdb_show:{tvdb_id}:s{season_number}",
        episode_number,
    )


def get_tmdb_episode_mapping(
    mapping_data,
    tmdb_id,
    season_number,
    episode_number,
    *,
    tvdb_id=None,
):
    """Map an anime episode onto TMDB's season and episode numbering.

    AniBridge entries are directional, and only the TVDB season slice can name
    a TMDB target for the already resolved show, so the source identity is
    fixed to TVDB and the target to that same show.
    """
    if not isinstance(mapping_data, dict) or tmdb_id in (None, ""):
        return None
    if tvdb_id in (None, ""):
        return None

    try:
        source_season = int(season_number)
        source_episode = int(episode_number)
    except (TypeError, ValueError):
        return None
    # Season 0 is deliberately excluded on both sides: the graph's season-0
    # slice is populated but is never a canonical target.
    if source_season <= 0 or source_episode <= 0:
        return None

    targets = mapping_data.get(f"tvdb_show:{tvdb_id}:s{source_season}", {})
    if not isinstance(targets, dict):
        return None

    target_prefix = f"tmdb_show:{tmdb_id}:s"
    candidates: dict[int, int] = {}
    for target_descriptor, ranges in targets.items():
        if not target_descriptor.startswith(target_prefix):
            continue

        try:
            target_season = int(target_descriptor[len(target_prefix) :])
            target_episode = _map_episode_number(ranges, source_episode)
        except (TypeError, ValueError):
            continue

        if target_season > 0 and target_episode and target_episode > 0:
            candidates.setdefault(target_season, target_episode)

    # Identical source ranges can sit under two target seasons, so the only
    # serialisation-independent answer is to refuse the ambiguous mapping and
    # let the caller fall back rather than trust JSON key order.
    if len(candidates) != 1:
        return None

    ((target_season, target_episode),) = candidates.items()
    return target_season, target_episode


def get_mal_id_from_tmdb_movie(mapping_data, tmdb_movie_id):
    """Find MAL ID from TMDB movie mapping."""
    return _get_mal_mapping(
        mapping_data,
        f"tmdb_movie:{tmdb_movie_id}",
    )


def get_mal_id_from_imdb(mapping_data, imdb_id):
    """Find MAL ID from IMDB ID mapping."""
    return _get_mal_mapping(
        mapping_data,
        f"imdb_movie:{imdb_id}",
    )


def get_tmdb_movie_id_from_mal_id(mapping_data, mal_id):
    """Find TMDB movie ID for a MAL anime ID (reverse lookup for anime movies)."""
    mal_id_str = str(mal_id)
    for source_descriptor, targets in mapping_data.items():
        if not source_descriptor.startswith("tmdb_movie:"):
            continue
        for target_descriptor in targets:
            found_id = _parse_mal_descriptor(target_descriptor)
            if found_id is not None and str(found_id) == mal_id_str:
                return source_descriptor.split(":", 1)[1]
    return None


def find_entries_for_mal_id(mapping_data, mal_id):
    """Find TVDB/TMDB provider link dicts for a given MAL ID (reverse lookup)."""
    results = []
    for source_descriptor, targets in mapping_data.items():
        for target_descriptor, ranges in targets.items():
            parsed = _parse_mal_descriptor(target_descriptor)
            if parsed is None or str(parsed) != str(mal_id):
                continue
            link = _parse_source_descriptor_to_link(source_descriptor, ranges)
            if link:
                results.append(link)
    return results


def _parse_source_descriptor_to_link(descriptor, ranges):
    """Parse a source descriptor and ranges into a provider link dict."""
    parts = descriptor.split(":")
    if len(parts) < DESCRIPTOR_MIN_PARTS:
        return None

    provider = parts[0]
    series_id = parts[1]

    episode_offset = 0
    if ranges:
        first_source_str = next(iter(ranges))
        first_target_str = ranges[first_source_str]
        source_start, _ = _parse_episode_range(first_source_str)
        clean_target = first_target_str.split("|")[0].split(",")[0]
        target_start, _ = _parse_episode_range(clean_target)
        episode_offset = source_start - target_start

    season = None
    if len(parts) >= DESCRIPTOR_SEASON_PART_INDEX and parts[2].startswith("s"):
        with contextlib.suppress(ValueError):
            season = int(parts[2][1:])

    if provider == "tvdb_show":
        return {
            "tvdb_id": series_id,
            "season_number": season,
            "episode_offset": episode_offset,
        }
    if provider == "tmdb_show":
        return {
            "tmdb_id": series_id,
            "season_number": season,
            "episode_offset": episode_offset,
        }

    return None


def _get_mal_mapping(mapping_data, source_descriptor, episode_number=None):
    """Return a MAL ID and optional episode number for an AniBridge descriptor."""
    targets = mapping_data.get(source_descriptor, {})
    for target_descriptor, ranges in targets.items():
        mal_id = _parse_mal_descriptor(target_descriptor)
        if mal_id is None:
            continue

        if episode_number is None:
            return mal_id

        mapped_episode_number = _map_episode_number(ranges, episode_number)
        if mapped_episode_number is not None:
            return mal_id, mapped_episode_number

    if episode_number is None:
        return None
    return None, None


def _parse_mal_descriptor(descriptor):
    """Parse MAL ID from an AniBridge target descriptor."""
    if not isinstance(descriptor, str):
        return None

    parts = descriptor.split(":", 2)
    if len(parts) < DESCRIPTOR_MIN_PARTS:
        return None

    provider, media_id = parts[:2]
    if provider != "mal":
        return None
    return _parse_mal_id(media_id)


def _map_episode_number(ranges, episode_number):
    """Map a source episode number through AniBridge episode ranges."""
    if not ranges:
        return episode_number

    for source_range, target_range in ranges.items():
        source_start, source_end = _parse_episode_range(source_range)
        if episode_number < source_start:
            continue
        if source_end is not None and episode_number > source_end:
            continue

        source_offset = episode_number - source_start
        return _map_target_episode_number(target_range, source_offset)

    return None


def _map_target_episode_number(target_range, source_offset):
    """Return the target episode at a zero-based source range offset."""
    target_ranges, _, ratio_text = target_range.partition("|")
    target_start, _ = _parse_episode_range(target_ranges.split(",")[0])

    if ratio_text:
        ratio = int(ratio_text)
        if ratio > 0:
            return target_start + ((source_offset + 1) * ratio) - 1
        return target_start + ((source_offset + 1) // abs(ratio))

    remaining_offset = source_offset
    for target_range_part in target_ranges.split(","):
        target_start, target_end = _parse_episode_range(target_range_part)
        if target_end is None:
            return target_start + remaining_offset

        target_length = target_end - target_start + 1
        if remaining_offset < target_length:
            return target_start + remaining_offset
        remaining_offset -= target_length

    return None


def _parse_episode_range(episode_range):
    """Parse an AniBridge episode range into start and optional end numbers."""
    if "-" not in episode_range:
        episode_number = int(episode_range)
        return episode_number, episode_number

    start, end = episode_range.split("-", 1)
    return int(start), int(end) if end else None


def _parse_mal_id(mal_id):
    """Parse MAL ID from potentially comma-separated string."""
    if isinstance(mal_id, str) and "," in mal_id:
        mal_id = mal_id.split(",")[0].strip()
    if isinstance(mal_id, str) and mal_id.isdigit():
        return int(mal_id)
    return mal_id
