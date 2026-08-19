"""Bulk aggregation helpers for episode runtimes.

Media.total_runtime_minutes for TV/anime needs per-season episode runtimes.
Computing it per media object used to issue one query per season; these
helpers fetch all episode runtimes for a set of shows in a single query so
list pages and home rows can aggregate purely in Python.

The same rule applies to the cached season metadata that answers "how long is
an average episode of this show". Read it for all shows at once, before the
loop that needs it, not once per show inside that loop.
"""

import logging
from collections import defaultdict

from django.core.cache import cache

from app.models.choices import MediaTypes
from app.models.item import Item

logger = logging.getLogger(__name__)

# Sentinel values meaning "runtime unknown"; mirrored from the per-season
# queries this module replaces.
EXCLUDED_RUNTIME_SENTINELS = (999998, 999999)

# Season numbers that carry usable metadata often enough to be worth reading.
# Season 1 is tried first, then these, and the first hit wins.
SEASON_RUNTIME_FALLBACK_NUMBERS = (1, 2, 3, 4, 5)

# Cache reads are grouped into batches of this size. One request must not turn
# into a single huge multi-key read for a very large library.
SEASON_RUNTIME_CACHE_CHUNK = 200

# Runtime in minutes to assume when no metadata answers the question.
DEFAULT_RUNTIME_MINUTES_BY_SOURCE = {"tmdb": 30, "mal": 23}
DEFAULT_RUNTIME_MINUTES = 30


def season_runtime_cache_key(media_id, season_number):
    """Return the cache key that holds metadata for one season of one show."""
    return f"tmdb_season_{media_id}_{season_number}"


def build_season_runtime_index(media_ids, season_numbers=None):
    """Read cached season metadata for the given shows in grouped requests.

    Returns {media_id: runtime_minutes} and contains only the shows that had
    usable metadata. An earlier season wins over a later one, which keeps the
    result identical to reading the seasons one at a time in order.

    An unavailable cache is treated as "no metadata", never as an error. The
    cache is optional here: the caller has a usable default, and an
    interactive page must not fail or wait because optional metadata is slow.
    """
    from app.stats_utils import parse_runtime_to_minutes

    seasons = tuple(season_numbers or SEASON_RUNTIME_FALLBACK_NUMBERS)
    media_ids = [media_id for media_id in dict.fromkeys(media_ids) if media_id]
    if not media_ids or not seasons:
        return {}

    resolved = {}
    for start in range(0, len(media_ids), SEASON_RUNTIME_CACHE_CHUNK):
        chunk = media_ids[start : start + SEASON_RUNTIME_CACHE_CHUNK]
        keys = [
            season_runtime_cache_key(media_id, season_number)
            for media_id in chunk
            for season_number in seasons
        ]
        try:
            payloads = cache.get_many(keys) or {}
        except Exception as error:
            logger.debug("Cache unavailable reading season runtimes: %s", error)
            continue

        for media_id in chunk:
            for season_number in seasons:
                payload = payloads.get(
                    season_runtime_cache_key(media_id, season_number),
                )
                if not payload:
                    continue
                runtime_text = (payload.get("details") or {}).get("runtime")
                if not runtime_text:
                    continue
                runtime_minutes = parse_runtime_to_minutes(runtime_text)
                if runtime_minutes and runtime_minutes > 0:
                    resolved[media_id] = runtime_minutes
                    break

    return resolved


def default_runtime_minutes(source):
    """Return the assumed episode runtime for a show from the given source."""
    return DEFAULT_RUNTIME_MINUTES_BY_SOURCE.get(source, DEFAULT_RUNTIME_MINUTES)


def build_episode_runtime_index(show_keys):
    """Fetch episode runtimes for the given (media_id, source) shows in one query.

    Returns {(media_id, source): {season_number: [(episode_number, runtime), ...]}}.
    Like _annotate_tv_released_episodes, the query tolerates a superset cross
    product of ids and sources; extra rows are filtered out by the dict keying.
    """
    if not show_keys:
        return {}

    media_ids = {media_id for media_id, _ in show_keys}
    sources = {source for _, source in show_keys}
    rows = (
        Item.objects.filter(
            media_type=MediaTypes.EPISODE.value,
            media_id__in=media_ids,
            source__in=sources,
            runtime_minutes__isnull=False,
        )
        .exclude(runtime_minutes__in=EXCLUDED_RUNTIME_SENTINELS)
        .values_list(
            "media_id",
            "source",
            "season_number",
            "episode_number",
            "runtime_minutes",
        )
    )

    index = {}
    for media_id, source, season_number, episode_number, runtime in rows:
        key = (media_id, source)
        if key not in show_keys:
            continue
        index.setdefault(key, defaultdict(list))[season_number].append(
            (episode_number, runtime),
        )
    return index


def prefill_episode_runtime_index(media_list):
    """Prefill episode runtimes for TV/anime entries with a single query.

    Sets media._episode_runtime_index on every TV/anime entry (an empty dict
    counts as prefilled) so total_runtime_minutes never queries per season.
    Entries that already carry an index are left untouched.

    List-entry wrappers (e.g. MediaListEntry) are unwrapped via their .media
    attribute: runtime properties evaluate on the wrapped model, so the index
    must live there, not on the wrapper.
    """
    targets = []
    show_keys = set()
    for entry in media_list:
        media = getattr(entry, "media", None) or entry
        item = getattr(media, "item", None)
        if item is None or getattr(media, "_episode_runtime_index", None) is not None:
            continue
        if item.media_type not in (MediaTypes.TV.value, MediaTypes.ANIME.value):
            continue
        targets.append(media)
        show_keys.add((item.media_id, item.source))

    if not targets:
        return

    index = build_episode_runtime_index(show_keys)
    for media in targets:
        key = (media.item.media_id, media.item.source)
        media._episode_runtime_index = index.get(key, {})
