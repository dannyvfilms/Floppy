import logging
from collections import defaultdict

from app import config
from app.models import MediaTypes
from app.statistics_talent import STATISTICS_TOP_N

logger = logging.getLogger(__name__)


def _get_podcast_runtime_minutes(podcast_entry, history_record=None):
    """Get runtime in minutes from a Podcast entry, checking episode and item."""
    # First try the linked PodcastEpisode's duration (in seconds)
    if podcast_entry.episode and podcast_entry.episode.duration:
        return podcast_entry.episode.duration // 60  # seconds to minutes

    # Fall back to item runtime_minutes
    if podcast_entry.item and podcast_entry.item.runtime_minutes:
        return podcast_entry.item.runtime_minutes

    # Fall back to progress (already in minutes, but represents listened time, not total)
    # This is less ideal but better than nothing
    if history_record and history_record.progress and history_record.progress > 0:
        return history_record.progress
    if podcast_entry.progress and podcast_entry.progress > 0:
        return podcast_entry.progress

    return 0


def _get_podcast_history_data(user, start_date, end_date):
    """Return the user's completed podcast plays and a lookup for metadata."""
    if not user:
        return [], {}

    from app.models import Podcast, PodcastPlay

    plays = PodcastPlay.objects.filter(podcast__user=user, end_date__isnull=False)
    if start_date:
        plays = plays.filter(end_date__gte=start_date)
    if end_date:
        plays = plays.filter(end_date__lte=end_date)

    plays = list(plays.order_by("end_date"))
    podcast_ids = {play.podcast_id for play in plays}
    if not podcast_ids:
        return plays, {}

    podcasts_lookup = {
        podcast.id: podcast
        for podcast in Podcast.objects.filter(
            id__in=podcast_ids,
            user=user,
        ).select_related("item", "show", "episode", "episode__show")
    }

    return plays, podcasts_lookup


def _collect_podcast_play_data(plays, podcasts_lookup, start_date, end_date):
    """Collect podcast play datetimes and per-play runtime from plays.

    Returns:
        tuple: (list of datetimes, list of (podcast_entry, datetime, runtime_minutes) tuples)
    """
    from app.statistics import _localize_datetime

    datetimes = []
    play_details = []  # (podcast_entry, datetime, runtime_minutes)

    for play in plays or []:
        play_end_date = play.end_date
        if not play_end_date:
            continue
        if start_date and end_date and not (start_date <= play_end_date <= end_date):
            continue
        podcast = podcasts_lookup.get(play.podcast_id)
        if not podcast:
            continue
        runtime_minutes = _get_podcast_runtime_minutes(podcast, play)
        if runtime_minutes <= 0:
            continue

        localized_date = _localize_datetime(play_end_date)
        datetimes.append(localized_date)
        play_details.append((podcast, localized_date, runtime_minutes))

    logger.debug("Collected %d podcast plays", len(datetimes))
    return datetimes, play_details


def _compute_podcast_top_lists(play_details, limit=STATISTICS_TOP_N):
    """Compute top shows by plays, listening time, and longest episodes.

    Args:
        play_details: List of (podcast_entry, datetime, runtime_minutes) tuples
        limit: Number of items to return per list

    Returns:
        dict with most_played (by show), most_listened (by show), longest_episodes lists
    """
    from app.helpers import minutes_to_hhmm, seconds_to_hm

    # Aggregate by show for most_played and most_listened
    show_stats = defaultdict(
        lambda: {
            "minutes": 0,
            "plays": 0,
            "title": "",
            "show": "",
            "show_id": None,
            "podcast_uuid": None,
            "slug": "",
            "image": "",
        }
    )

    # Aggregate by episode for longest_episodes
    episode_stats = defaultdict(
        lambda: {
            "title": "",
            "show": "",
            "show_id": None,
            "podcast_uuid": None,
            "slug": "",
            "episode_id": None,
            "image": "",
            "duration_seconds": 0,
        }
    )

    for podcast, _dt, runtime in play_details:
        # Aggregate by show for most_played and most_listened
        if podcast.show:
            show_key = podcast.show.id
            show_stats[show_key]["show_id"] = show_key
            show_stats[show_key]["show"] = podcast.show.title
            show_stats[show_key]["title"] = (
                podcast.show.title
            )  # Use show title as display title
            # Always set podcast_uuid if available (it should be the same for all podcasts of the same show)
            if podcast.show.podcast_uuid:
                show_stats[show_key]["podcast_uuid"] = podcast.show.podcast_uuid
            show_stats[show_key]["slug"] = podcast.show.slug or ""
            show_stats[show_key]["image"] = podcast.show.image or ""
        else:
            # Fallback if no show
            show_key = podcast.id
            show_stats[show_key]["show_id"] = None
            show_stats[show_key]["show"] = "Unknown Show"
            show_stats[show_key]["title"] = (
                podcast.item.title if podcast.item else "Unknown Show"
            )
            show_stats[show_key]["image"] = podcast.item.image if podcast.item else ""

        # Aggregate show stats
        show_stats[show_key]["minutes"] += runtime
        show_stats[show_key]["plays"] += 1

        # Aggregate by episode for longest_episodes
        if podcast.episode:
            episode_key = podcast.episode.id
            episode_stats[episode_key]["episode_id"] = episode_key
            episode_stats[episode_key]["title"] = podcast.episode.title
            episode_stats[episode_key]["duration_seconds"] = (
                podcast.episode.duration or 0
            )
        else:
            # Fallback to podcast.id if no episode link
            episode_key = podcast.id
            episode_stats[episode_key]["episode_id"] = episode_key
            episode_stats[episode_key]["title"] = (
                podcast.item.title if podcast.item else "Unknown Episode"
            )
            # Try to get duration from item
            if podcast.item and podcast.item.runtime_minutes:
                episode_stats[episode_key]["duration_seconds"] = (
                    podcast.item.runtime_minutes * 60
                )

        # Get show info for episode stats
        if podcast.show:
            episode_stats[episode_key]["show"] = podcast.show.title
            episode_stats[episode_key]["show_id"] = podcast.show.id
            # Always set podcast_uuid if available (it should be the same for all podcasts of the same show)
            if podcast.show.podcast_uuid:
                episode_stats[episode_key]["podcast_uuid"] = podcast.show.podcast_uuid
            episode_stats[episode_key]["slug"] = podcast.show.slug or ""
            episode_stats[episode_key]["image"] = podcast.show.image or ""
        elif podcast.item:
            episode_stats[episode_key]["image"] = podcast.item.image or ""

    # Ensure podcast_uuid is populated for all shows (look up from show_id if missing)
    from app.models import PodcastShow

    for show_stat in show_stats.values():
        if show_stat["show_id"] and not show_stat["podcast_uuid"]:
            try:
                show = PodcastShow.objects.get(id=show_stat["show_id"])
                if show.podcast_uuid:
                    show_stat["podcast_uuid"] = show.podcast_uuid
                    show_stat["slug"] = show.slug or show_stat["slug"]
            except PodcastShow.DoesNotExist:
                pass

    # Most played shows (by number of plays)
    most_played = sorted(
        show_stats.values(),
        key=lambda x: (x["plays"], x["minutes"]),
        reverse=True,
    )[:limit]

    # Most listened shows (by total minutes)
    most_listened = sorted(
        show_stats.values(),
        key=lambda x: (x["minutes"], x["plays"]),
        reverse=True,
    )[:limit]

    # Ensure podcast_uuid is populated for all episodes (look up from show_id if missing)
    for episode_stat in episode_stats.values():
        if episode_stat["show_id"] and not episode_stat["podcast_uuid"]:
            try:
                show = PodcastShow.objects.get(id=episode_stat["show_id"])
                if show.podcast_uuid:
                    episode_stat["podcast_uuid"] = show.podcast_uuid
                    episode_stat["slug"] = show.slug or episode_stat["slug"]
            except PodcastShow.DoesNotExist:
                pass

    # Longest episodes (by duration_seconds, only episodes with duration)
    longest_episodes = sorted(
        [ep for ep in episode_stats.values() if ep["duration_seconds"] > 0],
        key=lambda x: x["duration_seconds"],
        reverse=True,
    )[:limit]

    # Format durations
    for item in most_played + most_listened:
        item["formatted_duration"] = minutes_to_hhmm(item["minutes"])

    # Format longest episodes duration (from seconds)
    for item in longest_episodes:
        item["formatted_duration"] = seconds_to_hm(item["duration_seconds"])

    return {
        "most_played": most_played,
        "most_listened": most_listened,
        "longest_episodes": longest_episodes,
    }


def get_podcast_consumption_stats(
    user_media, start_date, end_date, minutes_per_type=None, user=None
):
    """Return aggregate metrics and chart data for podcast activity.

    This is similar to music consumption stats but for podcasts.

    Args:
        user_media: Dictionary of media querysets by type
        start_date: Start date for filtering
        end_date: End date for filtering
        minutes_per_type: Pre-calculated minutes per media type (optional)
        user: User object (required to query all podcasts)
    """
    from app.statistics import (
        _build_media_charts,
        _compute_metric_breakdown,
        _infer_user_from_user_media,
        calculate_minutes_per_media_type,
    )

    if user is None:
        user = _infer_user_from_user_media(user_media)

    if not user:
        logger.warning(
            "get_podcast_consumption_stats: No user available, returning empty stats"
        )
        return {
            "minutes": _compute_metric_breakdown(0, [], start_date, end_date),
            "plays": _compute_metric_breakdown(0, [], start_date, end_date),
            "charts": _build_media_charts(
                [], config.get_stats_color(MediaTypes.PODCAST.value), "Podcast Plays"
            ),
            "has_data": False,
            "most_played": [],
            "most_listened": [],
            "longest_episodes": [],
        }

    podcast_history_records, podcasts_lookup = _get_podcast_history_data(
        user,
        start_date,
        end_date,
    )
    podcast_datetimes, play_details = _collect_podcast_play_data(
        podcast_history_records,
        podcasts_lookup,
        start_date,
        end_date,
    )
    logger.debug(
        "get_podcast_consumption_stats: Collected %d datetimes, %d play_details",
        len(podcast_datetimes),
        len(play_details),
    )

    if minutes_per_type is None:
        minutes_per_type = calculate_minutes_per_media_type(
            user_media or {}, start_date, end_date
        )

    total_minutes = minutes_per_type.get(MediaTypes.PODCAST.value, 0)
    total_plays = len(podcast_datetimes)

    # For podcasts, we use minutes breakdown (same as music)
    minutes_breakdown = _compute_metric_breakdown(
        total_minutes,
        podcast_datetimes,
        start_date,
        end_date,
    )
    plays_breakdown = _compute_metric_breakdown(
        total_plays,
        podcast_datetimes,
        start_date,
        end_date,
    )

    color = config.get_stats_color(MediaTypes.PODCAST.value)
    chart_label = "Podcast Plays"
    charts = _build_media_charts(podcast_datetimes, color, chart_label)

    # Compute top lists
    top_lists = _compute_podcast_top_lists(play_details, limit=STATISTICS_TOP_N)

    return {
        "minutes": minutes_breakdown,
        "plays": plays_breakdown,
        "charts": charts,
        "has_data": total_plays > 0,
        "most_played": top_lists["most_played"],
        "most_listened": top_lists["most_listened"],
        "longest_episodes": top_lists["longest_episodes"],
    }
