# FORK: shared podcast domain logic used by the web podcast views and the
# REST API — play recording (extracted from podcast_views.podcast_save) and
# mark-all-played (extracted from podcast_views.podcast_mark_all_played).
import hashlib
import logging

from django.utils import timezone

import events
from app.log_safety import exception_summary
from app.mixins import disable_fetch_releases
from app.models import (
    Podcast,
    PodcastEpisode,
    PodcastPlay,
    PodcastShowTracker,
    Status,
)
from app.services import podcast_plays
from integrations import podcast_rss

logger = logging.getLogger(__name__)


def record_podcast_play(
    user,
    show,
    episode=None,
    episode_uuid=None,
    end_date=None,
    **play_fields,
):
    """Record a podcast play; returns (podcast, duplicate).

    Thin wrapper over ``podcast_plays.create_play`` for callers that only know
    a completion date. Uses the current server time when none is supplied;
    plays within five minutes of an existing one are duplicates.
    """
    play, created = podcast_plays.create_play(
        user,
        show,
        episode=episode,
        episode_uuid=episode_uuid,
        end_date=end_date,
        **play_fields,
    )
    return play.podcast, not created


def set_episode_notes(user, show, episode, notes):
    """Save private episode notes without recording a play.

    A note edit never creates a history record, and a blank note leaves an
    untracked episode untouched. The Podcast row is the per-user tracker, so
    this mirrors set_track_notes for music.
    """
    notes = notes or ""
    item, _ = podcast_plays.ensure_episode_item(show, episode)
    podcast = Podcast.objects.filter(user=user, item=item).first()
    if podcast is None and not notes:
        return None
    if podcast is None:
        podcast = Podcast(
            item=item,
            user=user,
            show=show,
            episode=episode,
            status=Status.PLANNING.value,
            progress=0,
        )
    podcast.notes = notes
    podcast.save_without_historical_record(
        update_fields=["notes"] if podcast.pk else None,
    )
    return podcast


def _episode_fallback_uuid(episode_data):
    """Return the synthetic GUID used for feed items that carry no <guid>."""
    uuid_str = f"{episode_data.get('title', '')}{episode_data.get('published', '')}"
    return hashlib.md5(
        uuid_str.encode(),
        usedforsecurity=False,
    ).hexdigest()[:36]


def _episode_date_key(published):
    """Return the local-date match key for an episode's publication time.

    Mirrors the ``published__date`` lookup the title+date fallback used to run
    as a per-item query: Django resolves ``__date`` in the active timezone, so
    an in-memory comparison has to localize too or a feed re-read would stop
    recognising its own episodes wherever TZ isn't UTC.
    """
    if published is None:
        return None
    return timezone.localtime(published).date()


def _index_existing_episodes(show):
    """Return (by_uuid, by_title_and_date) maps of the show's stored episodes.

    Indexing up front replaces a per-feed-item ``.exists()`` query. The show
    detail page re-reads the whole feed on every view, so that loop was one
    query per episode -- hundreds for a long-running podcast -- on a page load.
    """
    by_uuid = {}
    by_title_and_date = {}
    for episode in PodcastEpisode.objects.filter(show=show):
        by_uuid[episode.episode_uuid] = episode
        date_key = _episode_date_key(episode.published)
        if episode.title and date_key:
            by_title_and_date.setdefault(
                (episode.title.strip().casefold(), date_key),
                episode,
            )
    return by_uuid, by_title_and_date


def _match_existing_episode(episode_data, episode_uuid, by_uuid, by_title_and_date):
    """Return the stored episode a feed item refers to, if the catalog has it.

    The GUID match is what a feed re-read normally hits. The title+date fallback
    is what lets a Pocket Casts- or gPodder-sourced episode -- stored under the
    provider's own id rather than the feed GUID -- still be recognised.
    """
    existing = by_uuid.get(episode_uuid)
    if existing is not None:
        return existing
    title = episode_data.get("title")
    date_key = _episode_date_key(episode_data.get("published"))
    if not title or not date_key:
        return None
    return by_title_and_date.get((title.strip().casefold(), date_key))


def apply_show_metadata_from_rss(show, metadata):
    """Copy a feed's channel metadata onto the show. Returns whether it changed.

    ``website_url`` tracks the feed because the feed is its only source, so a
    show whose <link> changed follows it. The rest are only filled in when
    blank: a provider's own API often has better copy than the feed does, and
    this runs on every catalog refresh, so overwriting would undo that
    repeatedly.
    """
    update_fields = []

    website_url = (metadata.get("website_url") or "").strip()
    if website_url and show.website_url != website_url:
        show.website_url = website_url
        update_fields.append("website_url")

    for field in ("description", "author", "language", "image"):
        value = metadata.get(field)
        if value and not getattr(show, field, ""):
            setattr(show, field, value)
            update_fields.append(field)

    if update_fields:
        show.save(update_fields=update_fields)
    return bool(update_fields)


def refresh_show_episodes_from_rss(show, episodes_data=None):
    """Reconcile the show's episode catalog against its RSS feed.

    Creates episodes the catalog is missing, and backfills ``website_url`` on
    the ones it already has. The backfill matters because every episode stored
    before podcast website links existed -- and every episode from a provider
    import that doesn't carry the field -- would otherwise keep a blank link
    forever, since creation was the only place the value was ever written
    (issue #1014). Only non-empty feed values are written, and only rows whose
    value actually differs, so a feed that has settled costs no writes at all.

    ``episodes_data`` lets a caller that has already read the feed pass the
    parsed episodes in rather than have this fetch the document a second time.
    """
    if episodes_data is None:
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
                exception_summary(e),
            )
            return

    by_uuid, by_title_and_date = _index_existing_episodes(show)
    website_updates = []

    for episode_data in episodes_data:
        episode_uuid = episode_data.get("guid") or _episode_fallback_uuid(episode_data)
        existing = _match_existing_episode(
            episode_data,
            episode_uuid,
            by_uuid,
            by_title_and_date,
        )

        if existing is not None:
            website_url = (episode_data.get("website_url") or "").strip()
            if website_url and existing.website_url != website_url:
                existing.website_url = website_url
                website_updates.append(existing)
            continue

        try:
            episode = PodcastEpisode.objects.create(
                show=show,
                episode_uuid=episode_uuid,
                title=episode_data.get("title", "Unknown Episode"),
                description=episode_data.get("description") or "",
                published=episode_data.get("published"),
                duration=episode_data.get("duration"),
                audio_url=episode_data.get("audio_url", ""),
                website_url=episode_data.get("website_url", ""),
                episode_number=episode_data.get("episode_number"),
                season_number=episode_data.get("season_number"),
            )
        except Exception:
            logger.debug(
                "Skipping duplicate episode UUID %s for show %s",
                episode_uuid,
                show.title,
            )
            continue

        by_uuid[episode_uuid] = episode
        date_key = _episode_date_key(episode.published)
        if episode.title and date_key:
            by_title_and_date.setdefault(
                (episode.title.strip().casefold(), date_key),
                episode,
            )

    if website_updates:
        PodcastEpisode.objects.bulk_update(website_updates, ["website_url"])
        logger.info(
            "Backfilled website_url on %d episodes of %s",
            len(website_updates),
            show.title,
        )


def refresh_show_from_rss(show):
    """Re-read a show's feed for both its channel metadata and its episodes.

    The single entry point for "reconcile this show against its feed", shared
    by the detail page, the manual provider sync and the startup backfill. It
    reads the feed document once: the detail page runs this on every view, so
    fetching separately for the channel and the items would double the
    outbound traffic to the feed host.
    """
    if not show.rss_feed_url:
        return
    try:
        metadata, episodes_data = podcast_rss.fetch_feed_from_rss(
            show.rss_feed_url,
            limit=None,
        )
    except Exception as e:
        logger.warning(
            "Failed to read RSS feed for %s: %s",
            show.title,
            exception_summary(e),
        )
        return

    apply_show_metadata_from_rss(show, metadata)
    refresh_show_episodes_from_rss(show, episodes_data)


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
    plays = []

    with disable_fetch_releases():
        for episode in unplayed_episodes:
            item, item_created = podcast_plays.ensure_episode_item(show, episode)
            if item_created:
                items_created.append(item)

            end_date = episode.published or timezone.now()
            runtime_minutes = episode.duration // 60 if episode.duration else None
            tracker = Podcast.objects.filter(user=user, item=item).first()
            with podcast_plays.service_write():
                if tracker is None:
                    tracker = Podcast.objects.create(
                        item=item,
                        user=user,
                        show=show,
                        episode=episode,
                        status=Status.COMPLETED.value,
                        end_date=end_date,
                        progress=runtime_minutes or 0,
                    )
                else:
                    tracker.status = Status.COMPLETED.value
                    tracker.end_date = end_date
                    tracker.progress = runtime_minutes or 0
                    tracker.save()
            plays.append(
                PodcastPlay(
                    podcast=tracker,
                    status=Status.COMPLETED.value,
                    end_date=end_date,
                    progress=runtime_minutes or 0,
                    is_end_date_inferred=not episode.published,
                ),
            )
            created_count += 1

    PodcastPlay.objects.bulk_create(plays, batch_size=500)

    if items_created:
        events.tasks.reload_calendar.apply_async(
            kwargs={"item_ids": [item.id for item in items_created]},
            countdown=3,
        )

    return created_count
