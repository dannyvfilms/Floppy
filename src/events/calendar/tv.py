import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone
from simple_history.utils import bulk_create_with_history, bulk_update_with_history

from app import cache_utils, metadata_utils
from app.models import TV, Item, MediaTypes, Season, Sources, Status
from app.providers import services, tmdb, tvdb
from events.models import Event
from integrations.imports.helpers import find_item_across_buckets

from .helpers import date_parser

logger = logging.getLogger(__name__)

TVMAZE_MAP_CACHE_VERSION = 4

# Episode air dates before this year are treated as placeholder/unknown values
# rather than real release dates.
MIN_VALID_RELEASE_YEAR = 1900


def _clear_tv_time_left_cache(media_id, source, user_ids=None):
    """Invalidate cached time-left values for users tracking a TV show."""
    if not media_id or not source:
        return

    if user_ids is None:
        tv_user_ids = TV.objects.filter(
            item__media_id=media_id,
            item__source=source,
            item__media_type=MediaTypes.TV.value,
        ).values_list("user_id", flat=True)
        season_user_ids = Season.objects.filter(
            item__media_id=media_id,
            item__source=source,
            item__media_type=MediaTypes.SEASON.value,
        ).values_list("user_id", flat=True)
        user_ids = sorted(set(tv_user_ids).union(season_user_ids))
    else:
        user_ids = sorted(set(user_ids))

    for user_id in user_ids:
        cache_utils.clear_time_left_cache_for_user(user_id)


def _evict_cached_metadata(tv_item, season_numbers=(), *, show=True):
    """Drop cached provider payloads so this check reads current air dates.

    Provider metadata is cached for 12 to 24 hours, and a check that reads it
    can miss a season the provider added, or dated, since (#1531). Only shows
    selected for a check come through here, and each is about to be fetched.
    """
    show_keys = metadata_utils.provider_metadata_cache_keys(
        tv_item.source,
        MediaTypes.TV.value,
        tv_item.media_id,
    )
    keys = list(show_keys) if show else []
    for season_number in season_numbers:
        # TVDB's season keys include the series payload; keep the one just fetched.
        keys.extend(
            key
            for key in metadata_utils.provider_metadata_cache_keys(
                tv_item.source,
                MediaTypes.SEASON.value,
                tv_item.media_id,
                season_number=season_number,
            )
            if show or key not in show_keys
        )
    try:
        cache.delete_many(keys)
    except Exception:
        logger.warning("Could not clear cached metadata for %s", tv_item, exc_info=True)


def process_tv(tv_item, events_bulk, tv_metadata=None, force_seasons=None):
    """Process TV item and create events for all seasons and episodes.

    Returns True when the show was successfully checked (including when no season
    needed processing), False when the provider call failed or processing errored.
    """
    logger.info("Processing TV show: %s", tv_item)

    try:
        if tv_metadata is None:
            _evict_cached_metadata(tv_item)

        seasons_to_process = get_seasons_to_process(
            tv_item,
            tv_metadata=tv_metadata,
            force_seasons=force_seasons,
        )

        if not seasons_to_process:
            logger.info("%s - No seasons need processing", tv_item)
            return True

        if tv_metadata is None:
            _evict_cached_metadata(tv_item, seasons_to_process, show=False)

        process_tv_seasons(
            tv_item,
            seasons_to_process,
            events_bulk,
        )

    except services.ProviderAPIError:
        logger.warning(
            "Failed to fetch metadata for %s",
            tv_item,
        )
        return False
    except Exception:
        logger.exception("Error processing %s", tv_item)
        return False

    return True


def _tv_provider(source):
    """Return the metadata provider module for a TV item's source."""
    return tvdb if source == Sources.TVDB.value else tmdb


def get_seasons_to_process(tv_item, tv_metadata=None, force_seasons=None):
    """Identify which seasons of a TV show need to be processed."""
    if tv_metadata is None:
        tv_metadata = _tv_provider(tv_item.source).tv(tv_item.media_id)

    if not tv_metadata.get("related", {}).get("seasons"):
        logger.warning("No seasons found for TV show: %s", tv_item)
        return []

    season_numbers = [
        season["season_number"]
        for season in tv_metadata["related"]["seasons"]
        if season["season_number"] > 0
    ]

    if not season_numbers:
        logger.warning("No valid seasons found for TV show: %s", tv_item)
        return []

    next_episode_season = tv_metadata.get("next_episode_season")

    existing_season_events = Event.objects.filter(
        item__media_id=tv_item.media_id,
        item__source=tv_item.source,
        item__media_type=MediaTypes.SEASON.value,
    ).select_related("item")

    seasons_with_events = {event.item.season_number for event in existing_season_events}
    # Seasons whose events can still change: future air dates (including the
    # year-9999 unknown-date sentinel) or the datetime.min unknown-date
    # fallback. TMDB refreshes these via next_episode_season, but sources
    # without that field (TVDB) rely on this to keep ongoing seasons current.
    now = timezone.now()
    seasons_with_refreshable_events = {
        event.item.season_number
        for event in existing_season_events
        if event.datetime >= now or event.datetime.year == 1
    }
    if force_seasons is not None:
        forced_seasons = {int(season_number) for season_number in force_seasons}
        seasons_to_process = [
            season_num for season_num in season_numbers if season_num in forced_seasons
        ]
    else:
        seasons_to_process = [
            season_num
            for season_num in season_numbers
            if season_num not in seasons_with_events
            or (next_episode_season and season_num >= next_episode_season)
            or season_num in seasons_with_refreshable_events
        ]

    # One line per checked show: it separates "the provider has no new season"
    # from "the show was never checked" when a season is missing (#1531).
    logger.info(
        "%s - Provider seasons %s, seasons with events %s, processing %s "
        "(Next episode season: %s)",
        tv_item,
        sorted(season_numbers),
        sorted(seasons_with_events),
        sorted(seasons_to_process),
        next_episode_season,
    )

    if not seasons_to_process:
        return []

    return seasons_to_process


def process_tv_seasons(tv_item, seasons_to_process, events_bulk):
    """Process specific seasons of a TV show."""
    process_seasons_data = _tv_provider(tv_item.source).tv_with_seasons(
        tv_item.media_id,
        seasons_to_process,
    )
    processed_season_items = []
    item_changes = False

    for season_number in seasons_to_process:
        season_key = f"season/{season_number}"
        if season_key not in process_seasons_data:
            logger.warning(
                "Season %s data not found for %s",
                season_number,
                tv_item,
            )
            continue

        season_metadata = process_seasons_data[season_key]

        season_image = season_metadata.get("image") or tv_item.image
        season_bucket = (
            MediaTypes.ANIME.value
            if tv_item.library_media_type == MediaTypes.ANIME.value
            else MediaTypes.SEASON.value
        )

        season_item = find_item_across_buckets(
            preferred_bucket=season_bucket,
            media_id=tv_item.media_id,
            source=tv_item.source,
            media_type=MediaTypes.SEASON.value,
            season_number=season_number,
        )
        season_created = False
        if season_item is None:
            season_item, season_created = Item.objects.get_or_create(
                media_id=tv_item.media_id,
                source=tv_item.source,
                media_type=MediaTypes.SEASON.value,
                library_media_type=season_bucket,
                season_number=season_number,
                defaults={
                    **Item.title_fields_from_metadata(
                        season_metadata,
                        fallback_title=tv_item.title,
                    ),
                    "image": season_image,
                },
            )

        if season_created:
            item_changes = True
        processed_season_items.append(season_item)
        if process_season_episodes(
            season_item,
            season_metadata,
            events_bulk,
            tv_metadata=process_seasons_data,
        ):
            item_changes = True

    if item_changes:
        _clear_tv_time_left_cache(tv_item.media_id, tv_item.source)

    reopen_completed_tv_with_new_seasons(tv_item, processed_season_items, events_bulk)

    return processed_season_items


def reopen_completed_tv_with_new_seasons(tv_item, season_items, events_bulk):
    """Reopen completed TV entries and create planning seasons when needed."""
    eligible_season_items = [
        season_item
        for season_item in season_items
        if season_item.season_number and season_item.season_number > 0
    ]
    season_item_map = {
        season_item.season_number: season_item for season_item in eligible_season_items
    }
    if not season_item_map:
        logger.info(
            "%s - No processed seasons eligible for completed-TV reopening",
            tv_item,
        )
        return

    now = timezone.now()
    future_season_numbers = {
        event.item.season_number
        for event in events_bulk
        if event.item in eligible_season_items and event.datetime >= now
    }
    if not future_season_numbers:
        logger.info(
            "%s - Processed seasons have no future events; "
            "skipping completed-TV reopening",
            tv_item,
        )
        return

    sorted_season_numbers = sorted(future_season_numbers)
    completed_tvs = list(
        TV.objects.filter(
            item__media_id=tv_item.media_id,
            item__source=tv_item.source,
            item__media_type=MediaTypes.TV.value,
            status=Status.COMPLETED.value,
        )
        .select_related("user")
        .prefetch_related(
            Prefetch(
                "seasons",
                queryset=Season.objects.select_related("item"),
            ),
        ),
    )
    if not completed_tvs:
        logger.info("%s - No completed TV entries to reopen", tv_item)
        return

    logger.info(
        "%s - Checking %d completed TV entries against discovered seasons %s",
        tv_item,
        len(completed_tvs),
        sorted_season_numbers,
    )

    seasons_by_tv_id = {}
    tvs_to_update = []

    for tv in completed_tvs:
        existing_seasons = list(tv.seasons.all())
        existing_season_numbers = {
            season.item.season_number
            for season in existing_seasons
            if season.item.season_number and season.item.season_number > 0
        }
        existing_new_seasons = [
            season
            for season in existing_seasons
            if season.item.season_number in season_item_map
        ]
        missing_season_numbers = [
            season_number
            for season_number in sorted_season_numbers
            if season_number not in existing_season_numbers
        ]
        has_incomplete_discovered_season = any(
            season.status != Status.COMPLETED.value for season in existing_new_seasons
        )

        if not missing_season_numbers and not has_incomplete_discovered_season:
            logger.info(
                "%s - User %s already tracks all discovered seasons",
                tv_item,
                tv.user,
            )
            continue

        if missing_season_numbers:
            logger.info(
                "%s - Reopening completed TV for user %s; new seasons: %s",
                tv_item,
                tv.user,
                missing_season_numbers,
            )
        else:
            logger.info(
                "%s - Reopening completed TV for user %s; discovered seasons already tracked in a non-completed state",
                tv_item,
                tv.user,
            )

        seasons_by_tv_id[tv.id] = [
            Season(
                item=season_item_map[season_number],
                related_tv=tv,
                user=tv.user,
                status=Status.PLANNING.value,
            )
            for season_number in missing_season_numbers
        ]
        tv.status = Status.IN_PROGRESS.value
        tvs_to_update.append(tv)

    if not seasons_by_tv_id:
        logger.info("%s - No completed TV entries required reopening", tv_item)
        return

    with transaction.atomic():
        for tv in tvs_to_update:
            if seasons_by_tv_id[tv.id]:
                bulk_create_with_history(
                    seasons_by_tv_id[tv.id],
                    Season,
                    default_user=tv.user,
                    default_change_reason="New season announced",
                )
            bulk_update_with_history(
                [tv],
                TV,
                ["status"],
                default_user=tv.user,
                default_change_reason="New season announced",
            )
            logger.info(
                "%s - Reopened TV for user %s and created %d planning seasons",
                tv_item,
                tv.user,
                len(seasons_by_tv_id[tv.id]),
            )


def process_season_episodes(item, metadata, events_bulk, tv_metadata=None):
    """Process episodes for a season and add them to events_bulk."""
    tvmaze_map = {}
    if metadata.get("tvdb_id"):
        logger.info(
            "%s - TVDB ID found, fetching TVMaze episode data",
            item,
        )
        tvmaze_map = get_tvmaze_episode_map(metadata["tvdb_id"])
    else:
        logger.warning(
            "%s - No TVDB ID found, skipping TVMaze episode data",
            item,
        )

    if not metadata.get("episodes"):
        logger.warning("%s - No episodes found in metadata", item)
        return False

    episode_numbers = [episode["episode_number"] for episode in metadata["episodes"]]
    existing_episode_items = {
        episode_item.episode_number: episode_item
        for episode_item in Item.objects.filter(
            media_id=item.media_id,
            source=item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=item.season_number,
            episode_number__in=episode_numbers,
        )
    }
    items_to_update = []
    new_items = []
    earliest_release = None
    undated_count = 0

    for episode in metadata["episodes"]:
        episode_number = episode["episode_number"]
        season_number = metadata["season_number"]

        episode_datetime = get_episode_datetime(
            episode,
            season_number,
            episode_number,
            tvmaze_map,
            tvmaze_entry=_get_tvmaze_episode_entry(
                item,
                metadata,
                episode_number,
                tvmaze_map,
                tv_metadata,
            ),
        )

        events_bulk.append(
            Event(
                item=item,
                content_number=episode_number,
                datetime=episode_datetime,
            ),
        )

        episode_item = existing_episode_items.get(episode_number)
        image = settings.IMG_NONE
        if episode.get("still_path"):
            image = f"https://image.tmdb.org/t/p/original{episode['still_path']}"
        elif episode.get("image"):
            image = episode["image"]

        if episode_item is None:
            episode_item = Item(
                media_id=item.media_id,
                source=item.source,
                media_type=MediaTypes.EPISODE.value,
                title=item.title,
                image=image,
                library_media_type=(
                    item.library_media_type
                    if item.library_media_type
                    and item.library_media_type != MediaTypes.SEASON.value
                    else MediaTypes.EPISODE.value
                ),
                season_number=season_number,
                episode_number=episode_number,
            )
            existing_episode_items[episode_number] = episode_item
            new_items.append(episode_item)

        release_datetime = (
            episode_datetime if episode_datetime.year > MIN_VALID_RELEASE_YEAR else None
        )
        if release_datetime is None:
            undated_count += 1

        if release_datetime is not None and (
            earliest_release is None or release_datetime < earliest_release
        ):
            earliest_release = release_datetime

        runtime_minutes = None
        if episode.get("runtime") is not None:
            runtime_minutes = (
                int(episode["runtime"]) if episode["runtime"] > 0 else None
            )
        elif release_datetime:
            runtime_minutes = 999998

        updated = False
        if episode_item.image == settings.IMG_NONE and image != settings.IMG_NONE:
            episode_item.image = image
            updated = True
        if episode_item.release_datetime != release_datetime:
            episode_item.release_datetime = release_datetime
            updated = True
        if episode_item.runtime_minutes != runtime_minutes:
            episode_item.runtime_minutes = runtime_minutes
            updated = True
        if updated and episode_item not in new_items:
            items_to_update.append(episode_item)

    logger.info(
        "%s - %d episodes from the provider, %d without an air date",
        item,
        len(metadata["episodes"]),
        undated_count,
    )

    if new_items:
        Item.objects.bulk_create(new_items, batch_size=100)

    if items_to_update:
        Item.objects.bulk_update(
            items_to_update,
            ["image", "release_datetime", "runtime_minutes"],
            batch_size=100,
        )

    season_release_updated = False
    if earliest_release is not None and item.release_datetime != earliest_release:
        item.release_datetime = earliest_release
        item.save(update_fields=["release_datetime"])
        season_release_updated = True

    return bool(new_items or items_to_update or season_release_updated)


_TVMAZE_ENTRY_UNSET = object()


def _get_tmdb_episode_position(
    tv_metadata,
    season_metadata,
    season_number,
    episode_number,
):
    """Return a TMDB episode's one-based position across regular seasons."""
    if not tv_metadata:
        return None

    try:
        season_number = int(season_number)
        episode_number = int(episode_number)
    except (TypeError, ValueError):
        return None

    if season_number <= 0 or episode_number <= 0:
        return None

    related_seasons = (tv_metadata.get("related") or {}).get("seasons") or []
    ordered_seasons = []
    for season in related_seasons:
        try:
            related_season_number = int(season.get("season_number"))
        except (TypeError, ValueError):
            continue
        if related_season_number > 0:
            ordered_seasons.append((related_season_number, season))

    offset = 0
    for related_season_number, season in sorted(ordered_seasons):
        episode_count = season.get("episode_count")
        if episode_count is None and related_season_number == season_number:
            episode_count = len(season_metadata.get("episodes") or [])
        try:
            episode_count = int(episode_count)
        except (TypeError, ValueError):
            return None
        if episode_count < 0:
            return None

        if related_season_number == season_number:
            if episode_number > episode_count:
                return None
            return offset + episode_number
        offset += episode_count

    return None


def _ordered_tvmaze_episode_entries(tvmaze_map):
    """Return TVMaze entries in regular-season broadcast order."""
    ordered_entries = []
    for key, entry in tvmaze_map.items():
        try:
            season_number, episode_number = map(int, key.split("_", 1))
        except (AttributeError, TypeError, ValueError):
            continue
        if season_number <= 0 or episode_number <= 0:
            continue
        ordered_entries.append((season_number, episode_number, entry))

    ordered_entries.sort(key=lambda row: (row[0], row[1]))
    return [entry for _, _, entry in ordered_entries]


def _get_tvmaze_episode_entry(
    item,
    season_metadata,
    episode_number,
    tvmaze_map,
    tv_metadata,
):
    """Resolve the TVMaze entry corresponding to a provider episode."""
    season_number = season_metadata.get("season_number")
    direct_key = f"{season_number}_{episode_number}"

    if item.source == Sources.TVDB.value or tv_metadata is None:
        return tvmaze_map.get(direct_key)

    position = _get_tmdb_episode_position(
        tv_metadata,
        season_metadata,
        season_number,
        episode_number,
    )
    if position is None:
        logger.info(
            "%s - No reliable TMDB episode position for S%sE%s; using TMDB date",
            item,
            season_number,
            episode_number,
        )
        return None

    ordered_entries = _ordered_tvmaze_episode_entries(tvmaze_map)
    if position > len(ordered_entries):
        logger.info(
            "%s - No TVMaze episode at position %s for S%sE%s; using TMDB date",
            item,
            position,
            season_number,
            episode_number,
        )
        return None

    return ordered_entries[position - 1]


def get_episode_datetime(
    episode,
    season_number,
    episode_number,
    tvmaze_map,
    tvmaze_entry=_TVMAZE_ENTRY_UNSET,
):
    """Determine the most accurate air datetime for an episode."""
    if tvmaze_entry is _TVMAZE_ENTRY_UNSET:
        tvmaze_key = f"{season_number}_{episode_number}"
        tvmaze_entry = tvmaze_map.get(tvmaze_key)
    if isinstance(tvmaze_entry, dict):
        tvmaze_airdate = tvmaze_entry.get("airdate")
        tvmaze_airstamp = tvmaze_entry.get("airstamp")
    else:
        # Keep test fixtures and callers using the pre-v3 cache shape working.
        tvmaze_airdate = None
        tvmaze_airstamp = tvmaze_entry

    tmdb_datetime = None
    if episode.get("air_date"):
        try:
            tmdb_datetime = date_parser(episode["air_date"])
        except ValueError:
            logger.warning(
                "Invalid air date for S%sE%s from TMDB: %s",
                season_number,
                episode_number,
                episode["air_date"],
            )

    tvmaze_date_datetime = None
    if tvmaze_airdate:
        try:
            tvmaze_date_datetime = date_parser(tvmaze_airdate)
        except ValueError:
            logger.warning(
                "Invalid air date for S%sE%s from TVMaze: %s",
                season_number,
                episode_number,
                tvmaze_airdate,
            )

    if tvmaze_airstamp:
        tvmaze_datetime = datetime.fromisoformat(tvmaze_airstamp)
        if tmdb_datetime is None or abs(tvmaze_datetime - tmdb_datetime) <= timedelta(
            days=2,
        ):
            return tvmaze_datetime
        return tmdb_datetime

    if tvmaze_date_datetime is not None:
        if tmdb_datetime is None or abs(tvmaze_date_datetime - tmdb_datetime) <= timedelta(
            days=2,
        ):
            return tvmaze_date_datetime
        return tmdb_datetime

    if tmdb_datetime is not None:
        return tmdb_datetime

    return datetime.min.replace(tzinfo=ZoneInfo("UTC"))


def get_tvmaze_episode_map(tvdb_id):
    """Fetch and process episode data from TVMaze using TVDB ID with caching."""
    cache_key = f"tvmaze_map_v{TVMAZE_MAP_CACHE_VERSION}_{tvdb_id}"
    cached_map = cache.get(cache_key)

    if cached_map:
        logger.info("%s - Using cached TVMaze episode map", tvdb_id)
        return cached_map

    show_response = get_tvmaze_response(tvdb_id)
    tvmaze_map = {}

    if show_response:
        episodes = show_response["_embedded"]["episodes"]

        for episode in episodes:
            season_num = episode.get("season")
            episode_num = episode.get("number")
            airdate = episode.get("airdate")
            airstamp = episode.get("airstamp")
            if season_num is None or episode_num is None:
                continue
            entry = {}
            if airdate or (airstamp and episode.get("airtime")):
                entry["airdate"] = airdate or airstamp[:10]
            if airstamp and episode.get("airtime"):
                entry["airstamp"] = airstamp

            key = f"{season_num}_{episode_num}"
            tvmaze_map[key] = entry

    cache.set(cache_key, tvmaze_map)
    logger.info(
        "%s - Cached TVMaze episode map with %d entries",
        tvdb_id,
        len(tvmaze_map),
    )

    return tvmaze_map


def get_tvmaze_response(tvdb_id):
    """Fetch episode data from TVMaze using TVDB ID."""
    lookup_url = f"https://api.tvmaze.com/lookup/shows?thetvdb={tvdb_id}"
    try:
        lookup_response = services.api_request("TVMaze", "GET", lookup_url)
    except requests.exceptions.HTTPError as err:
        if err.response.status_code == requests.codes.not_found:
            logger.warning(
                "TVMaze lookup failed for TVDB ID %s - %s",
                tvdb_id,
                err.response.text,
            )
        else:
            logger.warning(
                "%s - TVMaze lookup error: %s",
                tvdb_id,
                err.response.text,
            )
        lookup_response = {}

    if not lookup_response:
        logger.warning("%s - No TVMaze lookup response for TVDB ID", tvdb_id)
        return {}

    tvmaze_id = lookup_response.get("id")

    if not tvmaze_id:
        logger.warning("%s - TVMaze ID not found for TVDB ID", tvdb_id)
        return {}

    show_url = f"https://api.tvmaze.com/shows/{tvmaze_id}?embed=episodes"

    try:
        return services.api_request("TVMaze", "GET", show_url)
    except requests.exceptions.HTTPError:
        return {}
