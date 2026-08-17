# FORK: shared podcast domain logic used by the web podcast views and the
# REST API — play recording (extracted from podcast_views.podcast_save) and
# mark-all-played (extracted from podcast_views.podcast_mark_all_played).
import hashlib
import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

import events
from app.mixins import disable_fetch_releases
from app.models import (
    Item,
    MediaTypes,
    Podcast,
    PodcastEpisode,
    PodcastShowTracker,
    Status,
)
from integrations import podcast_rss

logger = logging.getLogger(__name__)

_DUPLICATE_PLAY_WINDOW_SECONDS = 300


def _episode_item_defaults(show, episode, runtime_minutes):
    defaults = {
        "title": episode.title if episode else "Unknown Episode",
        "image": show.image or settings.IMG_NONE,
    }
    if runtime_minutes:
        defaults["runtime_minutes"] = runtime_minutes
    if episode and episode.published:
        defaults["release_datetime"] = episode.published
    return defaults


def record_podcast_play(user, show, episode=None, episode_uuid=None, end_date=None):
    """Record a completed podcast play; returns (podcast, duplicate).

    Uses the current server time when the caller does not supply a completion
    date. One Podcast row is kept per (user, item); a new play updates its
    end_date, and plays within five minutes of the latest history entry are
    treated as duplicates.
    """
    completed_at = end_date if end_date is not None else timezone.now()
    runtime_minutes = None
    if episode and episode.duration:
        runtime_minutes = episode.duration // 60

    item, created = Item.objects.get_or_create(
        media_id=episode_uuid,
        source=show.source,
        media_type=MediaTypes.PODCAST.value,
        defaults=_episode_item_defaults(show, episode, runtime_minutes),
    )
    if not created:
        update_fields = []
        if runtime_minutes and item.runtime_minutes != runtime_minutes:
            item.runtime_minutes = runtime_minutes
            update_fields.append("runtime_minutes")
        if episode and episode.published and item.release_datetime != episode.published:
            item.release_datetime = episode.published
            update_fields.append("release_datetime")
        if update_fields:
            item.save(update_fields=update_fields)

    existing_podcast = Podcast.objects.filter(user=user, item=item).first()
    if existing_podcast:
        # Compare against the plays near this timestamp, not against the newest
        # one. An import that re-delivers a 2020 play has to be measured against
        # the stored 2020 play; measuring it against the newest play means one
        # "played just now" in between makes every replayed import look new.
        window = timedelta(seconds=_DUPLICATE_PLAY_WINDOW_SECONDS)
        if existing_podcast.history.filter(
            end_date__gt=completed_at - window,
            end_date__lt=completed_at + window,
        ).exists():
            logger.debug(
                "Skipping duplicate podcast history entry near %s",
                completed_at,
            )
            return existing_podcast, True

        existing_podcast.end_date = completed_at
        if runtime_minutes and existing_podcast.progress != runtime_minutes:
            existing_podcast.progress = runtime_minutes
        existing_podcast.save()
        return existing_podcast, False

    podcast = Podcast.objects.create(
        item=item,
        user=user,
        show=show,
        episode=episode,
        status=Status.COMPLETED.value,
        end_date=completed_at,
        progress=runtime_minutes or 0,
    )
    return podcast, False


def refresh_show_episodes_from_rss(show):
    """Pull the full episode list from the show's RSS feed into the catalog."""
    if not show.rss_feed_url:
        return
    try:
        episodes_data = podcast_rss.fetch_episodes_from_rss(
            show.rss_feed_url,
            limit=None,
        )
    except Exception as e:
        logger.warning(
            "Failed to fetch full episode list from RSS feed for %s: %s",
            show.title,
            e,
        )
        return

    seen_uuids = set(
        PodcastEpisode.objects.filter(show=show).values_list(
            "episode_uuid",
            flat=True,
        ),
    )
    for episode_data in episodes_data:
        episode_uuid = episode_data.get("guid")
        if not episode_uuid:
            uuid_str = (
                f"{episode_data.get('title', '')}{episode_data.get('published', '')}"
            )
            episode_uuid = hashlib.md5(uuid_str.encode()).hexdigest()[:36]  # noqa: S324

        if episode_uuid in seen_uuids:
            continue

        exists = False
        if episode_data.get("title") and episode_data.get("published"):
            exists = PodcastEpisode.objects.filter(
                show=show,
                title__iexact=episode_data["title"].strip(),
                published__date=episode_data["published"].date(),
            ).exists()

        if not exists:
            try:
                PodcastEpisode.objects.create(
                    show=show,
                    episode_uuid=episode_uuid,
                    title=episode_data.get("title", "Unknown Episode"),
                    published=episode_data.get("published"),
                    duration=episode_data.get("duration"),
                    audio_url=episode_data.get("audio_url", ""),
                    episode_number=episode_data.get("episode_number"),
                    season_number=episode_data.get("season_number"),
                )
                seen_uuids.add(episode_uuid)
            except Exception:
                logger.debug(
                    "Skipping duplicate episode UUID %s for show %s",
                    episode_uuid,
                    show.title,
                )


def mark_all_episodes_played(user, show):
    """Mark every unplayed catalog episode of the show as completed.

    Refreshes the catalog from RSS first (like the web view), then creates
    Completed Podcast rows dated on each episode's release date. Returns the
    number of episodes marked played.
    """
    PodcastShowTracker.objects.get_or_create(
        user=user,
        show=show,
        defaults={"status": Status.IN_PROGRESS.value},
    )

    refresh_show_episodes_from_rss(show)

    all_episodes = PodcastEpisode.objects.filter(show=show)
    completed_episodes = set(
        Podcast.objects.filter(
            user=user,
            show=show,
            episode__isnull=False,
            end_date__isnull=False,
        ).values_list("episode_id", flat=True),
    )
    unplayed_episodes = all_episodes.exclude(id__in=completed_episodes)

    if not unplayed_episodes.exists():
        return 0

    created_count = 0
    items_created = []

    with disable_fetch_releases():
        for episode in unplayed_episodes:
            runtime_minutes = episode.duration // 60 if episode.duration else None
            item, item_created = Item.objects.get_or_create(
                media_id=episode.episode_uuid,
                source=show.source,
                media_type=MediaTypes.PODCAST.value,
                defaults=_episode_item_defaults(show, episode, runtime_minutes),
            )

            if not item_created:
                update_fields = []
                if runtime_minutes and item.runtime_minutes != runtime_minutes:
                    item.runtime_minutes = runtime_minutes
                    update_fields.append("runtime_minutes")
                if episode.published and item.release_datetime != episode.published:
                    item.release_datetime = episode.published
                    update_fields.append("release_datetime")
                if update_fields:
                    item.save(update_fields=update_fields)

            if item_created:
                items_created.append(item)

            end_date = episode.published or timezone.now()

            Podcast.objects.create(
                item=item,
                user=user,
                show=show,
                episode=episode,
                status=Status.COMPLETED.value,
                end_date=end_date,
                progress=runtime_minutes or 0,
            )
            created_count += 1

    if items_created:
        events.tasks.reload_calendar.apply_async(
            kwargs={"item_ids": [item.id for item in items_created]},
            countdown=3,
        )

    return created_count
