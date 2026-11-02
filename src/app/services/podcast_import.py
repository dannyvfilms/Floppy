"""Resolve an iTunes podcast search result into a tracked PodcastShow.

Shared by the web media-detail view and the podcast API so both surfaces
create/import shows the same way instead of duplicating the logic.
"""

from __future__ import annotations

import logging

from app.log_safety import exception_summary
from app.models import Item, MediaTypes, PodcastEpisode, PodcastShow, Sources

logger = logging.getLogger(__name__)


class PodcastImportError(Exception):
    """Raised when an iTunes id cannot be resolved into a podcast show."""


def resolve_show_metadata(itunes_data: dict, rss_feed_url: str) -> dict:
    """Return the iTunes lookup data with RSS-feed fallbacks applied.

    iTunes' own lookup frequently omits the description, and when it does it
    often omits the author and language too; the show's feed carries all
    three. Returns a new dict instead of mutating `itunes_data`, and creates
    nothing, so `PodcastLookupView`'s read-only preview can share it with the
    import below and get the same metadata an import would store.
    """
    from integrations import podcast_rss

    resolved = dict(itunes_data)
    if resolved.get("description") and resolved.get("website_url"):
        return resolved
    try:
        rss_metadata = podcast_rss.fetch_show_metadata_from_rss(rss_feed_url)
    except Exception as e:
        logger.debug(
            "Failed to fetch show metadata from RSS: %s",
            exception_summary(e),
        )
        return resolved

    for field in ("description", "author", "language", "website_url"):
        if not resolved.get(field) and rss_metadata.get(field):
            resolved[field] = rss_metadata[field]
    return resolved


def find_existing_show(itunes_id: str, rss_feed_url: str) -> PodcastShow | None:
    """Return the already-imported show for an iTunes result, if there is one.

    Matches on the feed first and then on the iTunes-derived uuid — the same
    two lookups `import_show_from_itunes_id` uses to avoid importing a show
    twice, so a preview reports exactly what an import would reuse.
    """
    if rss_feed_url:
        existing = PodcastShow.objects.filter(rss_feed_url=rss_feed_url).first()
        if existing:
            return existing
    return PodcastShow.objects.filter(podcast_uuid=f"itunes:{itunes_id}").first()


def resolve_show_for_media_id(
    media_id: str,
    source: str = Sources.POCKETCASTS.value,
) -> PodcastShow | None:
    """Return the show a podcast route's media_id names, importing it if needed.

    Podcast search results carry the provider's identifier: an iTunes
    collection id for Pocket Casts, or the RSS feed URL for GPodder. Imported
    shows are stored under their own ``podcast_uuid``, so both forms have to
    resolve to the same show before the track and list modals can act on it.
    """
    media_id = str(media_id)
    show = PodcastShow.objects.filter(podcast_uuid=media_id).first()
    if show is not None:
        return show
    if PodcastEpisode.objects.filter(
        episode_uuid=media_id,
        show__source=source,
    ).exists():
        return None
    if source == Sources.POCKETCASTS.value and media_id.isdigit():
        return import_show_from_itunes_id(media_id)
    if source == Sources.GPODDER.value:
        return import_show_from_feed_url(media_id)
    return None


def _stored_show_for_search_id(media_id: str) -> PodcastShow | None:
    """Return the stored show a raw search id names, without any network call."""
    from integrations.gpodder_api import normalize_external_url
    from integrations.imports.gpodder import show_key_for_feed

    if media_id.isdigit():
        return PodcastShow.objects.filter(podcast_uuid=f"itunes:{media_id}").first()
    normalized = normalize_external_url(media_id) or media_id
    return (
        PodcastShow.objects.filter(rss_feed_url__in={media_id, normalized}).first()
        or PodcastShow.objects.filter(
            podcast_uuid=show_key_for_feed(normalized),
        ).first()
    )


def merge_stray_podcast_items(items=None) -> int:
    """Fold show Items filed under a raw search id into the show's own Item.

    Quick-add once stored a searched podcast under the provider id (an iTunes
    id or feed URL) instead of the show's ``podcast_uuid``, leaving a second
    Item that carried the list entry but none of the show's tracking. Only
    strays whose show is already stored are repaired, so this never touches
    the network; returns how many were merged or re-keyed.
    """
    from app.services import item_merge

    strays = items
    if strays is None:
        strays = Item.objects.filter(
            media_type=MediaTypes.PODCAST.value,
            episode_number__isnull=True,
            season_number__isnull=True,
        )
    repaired = 0
    for stray in list(strays):
        media_id = str(stray.media_id)
        if not (media_id.isdigit() or media_id.startswith(("http://", "https://"))):
            continue
        if PodcastShow.objects.filter(podcast_uuid=media_id).exists():
            continue
        show = _stored_show_for_search_id(media_id)
        if show is None:
            continue
        keeper = (
            Item.objects.filter(
                media_id=show.podcast_uuid,
                media_type=MediaTypes.PODCAST.value,
                source=stray.source,
                episode_number__isnull=True,
                season_number__isnull=True,
            )
            .exclude(pk=stray.pk)
            .first()
        )
        if keeper is not None:
            item_merge.merge_item(stray, keeper)
        else:
            stray.media_id = show.podcast_uuid
            stray.save(update_fields=["media_id"])
        repaired += 1
    return repaired


def import_show_from_feed_url(feed_url: str) -> PodcastShow:
    """Return the GPodder show for a feed URL, importing it if needed.

    Public GPodder search results identify a podcast by its RSS feed rather
    than an id Floppy already stores, so the feed is the only thing available
    to look up or create the show with.
    """
    from django.utils.text import slugify

    from app.fork_services_podcast import refresh_show_episodes_from_rss
    from integrations import podcast_rss
    from integrations.gpodder_api import normalize_external_url
    from integrations.imports.gpodder import show_key_for_feed

    feed_url = (feed_url or "").strip()
    if not feed_url:
        no_feed_error = "Could not find an RSS feed for this podcast."
        raise PodcastImportError(no_feed_error)

    normalized_feed = normalize_external_url(feed_url) or feed_url
    show = PodcastShow.objects.filter(rss_feed_url=feed_url).first()
    if show is None and normalized_feed != feed_url:
        show = PodcastShow.objects.filter(rss_feed_url=normalized_feed).first()
    if show is None:
        show = PodcastShow.objects.filter(
            podcast_uuid=show_key_for_feed(normalized_feed),
        ).first()
    if show is not None:
        return show

    metadata, episodes_data = podcast_rss.fetch_feed_from_rss(feed_url)
    if not metadata and not episodes_data:
        read_error = f"Could not read the RSS feed for {feed_url}."
        raise PodcastImportError(read_error)

    title = metadata.get("title") or "Unknown Podcast"
    show = PodcastShow.objects.create(
        podcast_uuid=show_key_for_feed(normalized_feed),
        source=Sources.GPODDER.value,
        title=title[:255],
        slug=slugify(title)[:255],
        author=(metadata.get("author") or "")[:255],
        image=metadata.get("image") or "",
        description=metadata.get("description") or "",
        language=(metadata.get("language") or "")[:10],
        rss_feed_url=feed_url,
        website_url=metadata.get("website_url") or "",
    )

    try:
        refresh_show_episodes_from_rss(show, episodes_data)
    except Exception as e:
        logger.warning(
            "Failed to import episodes from RSS feed for %s: %s",
            show.title,
            exception_summary(e),
        )

    return show


def import_show_from_itunes_id(itunes_id: str) -> PodcastShow:
    """Return the PodcastShow for an iTunes collection id, importing it if needed.

    Looks up the iTunes id via Pocket Casts, reuses an existing show with the
    same RSS feed if one is already tracked locally, or creates a new
    PodcastShow and imports its episode catalog from the RSS feed.

    Raises:
        PodcastImportError: if the iTunes id has no RSS feed, or the lookup
            fails.
    """
    from app.providers import pocketcasts

    try:
        itunes_data = pocketcasts.lookup_by_itunes_id(itunes_id)
    except Exception as e:
        logger.warning(
            "iTunes lookup failed for id=%s: %s",
            itunes_id,
            exception_summary(e),
        )
        lookup_error = f"Failed to look up iTunes id {itunes_id}."
        raise PodcastImportError(lookup_error) from e

    rss_feed_url = itunes_data.get("feed_url", "")
    if not rss_feed_url:
        no_feed_error = f"Could not find an RSS feed for iTunes id {itunes_id}."
        raise PodcastImportError(no_feed_error)

    existing_show = find_existing_show(itunes_id, rss_feed_url)
    if existing_show:
        return existing_show

    metadata = resolve_show_metadata(itunes_data, rss_feed_url)

    show = PodcastShow.objects.create(
        podcast_uuid=f"itunes:{itunes_id}",
        title=metadata.get("title", "Unknown Podcast"),
        author=metadata.get("author", ""),
        image=metadata.get("artwork_url", ""),
        description=metadata.get("description", ""),
        genres=metadata.get("genres", []),
        language=metadata.get("language", ""),
        rss_feed_url=rss_feed_url,
        website_url=metadata.get("website_url", ""),
    )

    try:
        _import_episodes_from_rss(show, rss_feed_url)
    except Exception as e:
        logger.warning(
            "Failed to fetch episodes from RSS feed for %s: %s",
            show.title,
            exception_summary(e),
        )

    return show


def _import_episodes_from_rss(show: PodcastShow, rss_feed_url: str) -> None:
    """Import every episode from an RSS feed into a newly created show."""
    from app.fork_services_podcast import refresh_show_episodes_from_rss

    # The show was just created from this feed, so rss_feed_url is already the
    # one to read; the shared reconciler builds the whole catalog when the show
    # has no episodes yet, and is the only place episode rows are written from
    # a feed.
    show.rss_feed_url = rss_feed_url
    refresh_show_episodes_from_rss(show)
