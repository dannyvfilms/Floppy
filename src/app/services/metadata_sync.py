"""Shared metadata refresh operations for web and API callers."""

import logging

import requests
from django.core.cache import cache
from django.utils import timezone

from app import credits as credit_helpers
from app import game_artwork, metadata_utils, view_constants
from app.log_safety import exception_summary
from app.models import MediaTypes, Sources
from app.providers import services
from app.services import game_lengths as game_length_services
from app.services import metadata_resolution
from app.services import trakt_popularity as trakt_popularity_service

logger = logging.getLogger(__name__)


def _save_provider_metadata_status(item, status):
    """Persist provider metadata status when it changes."""
    if item is None or item.provider_metadata_status == status:
        return item
    item.provider_metadata_status = status
    item.save(update_fields=["provider_metadata_status"])
    return item


def enrich_synced_item(
    item,
    metadata,
    *,
    source,
    route_media_type,
    tracking_media_type,
    season_number,
    user,
):
    """Apply the full metadata refresh to an already title/image-updated item.

    Shared by the Web UI "Sync metadata with provider" action and the REST
    API sync endpoints so both produce the same result. `route_media_type`
    is the movie/tv/season/episode/game/book "route" type used by
    metadata_resolution and trakt_popularity_service — for a season sync
    this is "season", even where a caller's own media_type parameter is
    fixed to "tv" (e.g. the API's season sync endpoint).

    Returns (warnings, preferred_provider_synced_or_none) — the second value
    is the preferred provider's source value if it was successfully synced,
    else None.
    """
    warnings = []

    # A successful season re-fetch means the provider now has the season,
    # so the local-only flag and its media-server episode count are stale.
    if (
        route_media_type == MediaTypes.SEASON.value
        and item.provider_metadata_status
        and metadata.get("episodes")
    ):
        _save_provider_metadata_status(item, "")
        if item.local_season_episode_count is not None:
            item.local_season_episode_count = None
            item.save(update_fields=["local_season_episode_count"])

    metadata_update_fields = metadata_utils.apply_item_genres(
        item,
        metadata_utils.extract_metadata_genres(metadata),
    )
    metadata_update_fields.extend(metadata_utils.apply_item_metadata(item, metadata))
    if metadata_update_fields:
        metadata_update_fields = list(dict.fromkeys(metadata_update_fields))
        item.metadata_fetched_at = timezone.now()
        metadata_update_fields.append("metadata_fetched_at")
        item.save(update_fields=metadata_update_fields)

    # A sync just did a live fetch: make sure the detail view's stored-metadata
    # shortcut (media_details_views.can_skip_live_fetch) doesn't serve the
    # impoverished Item-only fallback on the page load(s) that follow (#931).
    cache.set(
        view_constants.force_live_metadata_cache_key(item.id),
        True,
        timeout=view_constants.FORCE_LIVE_METADATA_TIMEOUT,
    )

    if source == Sources.IGDB.value and route_media_type == MediaTypes.GAME.value:
        try:
            game_length_services.refresh_game_lengths(
                item,
                igdb_metadata=metadata,
                force=True,
                fetch_hltb=True,
            )
        except Exception as exc:
            logger.warning(
                "game_lengths_manual_refresh_failed item_id=%s media_id=%s error=%s",
                item.id,
                item.media_id,
                exception_summary(exc),
            )
            warnings.append(
                "Game length metadata could not be refreshed. Cached data will be used if available.",
            )

        # The logo and backdrop are looked up when the page next loads, in the
        # visitor's request, because a personal provider key only applies there.
        try:
            game_artwork.expire(item.media_id)
            cache.delete(f"igdb_carousel_v4_{item.media_id}")
        except Exception as exc:
            logger.warning(
                "game_artwork_refresh_failed item_id=%s media_id=%s error=%s",
                item.id,
                item.media_id,
                exception_summary(exc),
            )

    metadata_resolution.upsert_provider_links(
        item,
        metadata,
        provider=source,
        provider_media_type=tracking_media_type,
        season_number=season_number,
    )

    if source == Sources.TMDB.value and tracking_media_type == MediaTypes.TV.value:
        from app.tasks_genre import populate_genres_for_item_sync

        populate_genres_for_item_sync(item, metadata)

    preferred_provider = metadata_resolution.get_preferred_provider(
        user,
        item,
        route_media_type,
    )
    preferred_provider_synced = None
    if preferred_provider not in (source, Sources.MANUAL.value):
        preferred_media_id = metadata_resolution.resolve_provider_media_id(
            item,
            preferred_provider,
            route_media_type=route_media_type,
            season_number=season_number,
        )
        if preferred_media_id:
            language = metadata_resolution.metadata_language_default(user, item)
            preferred_tracking_type = metadata_resolution.get_tracking_media_type(
                route_media_type,
                source=preferred_provider,
            )
            cache.delete_many(
                metadata_utils.provider_metadata_cache_keys(
                    preferred_provider,
                    preferred_tracking_type,
                    preferred_media_id,
                    season_number=season_number,
                    language=language,
                ),
            )
            try:
                preferred_metadata = services.get_media_metadata(
                    metadata_resolution.provider_route_media_type(
                        route_media_type,
                        preferred_provider,
                    ),
                    preferred_media_id,
                    preferred_provider,
                    language=language,
                )
                metadata_resolution.upsert_provider_links(
                    item,
                    preferred_metadata,
                    provider=preferred_provider,
                    provider_media_type=preferred_tracking_type,
                    season_number=season_number,
                )
                preferred_provider_synced = preferred_provider
            except (
                requests.exceptions.RequestException,
                services.ProviderAPIError,
            ) as exc:
                logger.warning(
                    "preferred_provider_sync_failed item_id=%s preferred_provider=%s preferred_media_id=%s error=%s",
                    item.id,
                    preferred_provider,
                    preferred_media_id,
                    exception_summary(exc),
                )

    if trakt_popularity_service.supports_route_media_type(route_media_type):
        try:
            trakt_popularity_service.refresh_trakt_popularity(
                item,
                route_media_type=route_media_type,
                force=True,
            )
        except Exception as exc:
            logger.warning(
                "trakt_popularity_manual_refresh_failed item_id=%s media_id=%s error=%s",
                item.id,
                item.media_id,
                exception_summary(exc),
            )
            warnings.append(
                "Trakt popularity metadata could not be refreshed. Cached data will be used if available.",
            )

    if source == Sources.TMDB.value and tracking_media_type in (
        MediaTypes.MOVIE.value,
        MediaTypes.TV.value,
        MediaTypes.SEASON.value,
    ):
        credit_helpers.sync_item_credits_from_metadata(item, metadata)
    elif source == Sources.IGDB.value and tracking_media_type == MediaTypes.GAME.value:
        # No inline metadata payload for cast here — IMDB cast/crew is a
        # separate best-effort match+download pipeline that's too heavy to
        # run synchronously in a request. Queue it so a manual refresh
        # doesn't have to wait for the nightly job to pick this game up.
        from app.tasks_imdb import refresh_imdb_game_credits_from_datasets

        refresh_imdb_game_credits_from_datasets.apply_async(countdown=2)

    return warnings, preferred_provider_synced


def sync_podcast_show_from_rss(media_id, source):
    """Re-read a podcast show's RSS feed. Returns the show, or None if not one.

    Podcast shows have no upstream metadata provider to sync against -- the
    feed is the provider -- and they have no Item row of their own, since
    Items are per-episode. So this runs the feed reconcile and returns before
    the generic Item create/update path, which would otherwise mint a bogus
    show-level Item.
    """
    from app.fork_services_podcast import refresh_show_from_rss
    from app.models import PodcastShow

    show = PodcastShow.objects.filter(
        podcast_uuid=media_id,
        source=source,
    ).first()
    if show is None:
        return None
    refresh_show_from_rss(show)
    return show
