"""Celery task that warms horizontal backdrops into Redis.

Kept out of ``app.tasks`` so the web and interactive processes that enqueue it
import only this module, not the full background task registry.
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="Warm backdrops", ignore_result=True)
def warm_backdrops_task(identities: list[dict]):
    """Fetch missing horizontal backdrops into Redis.

    Scheduled by ``backdrops.schedule_backdrop_warm`` from read paths that
    must not call providers themselves; the next read picks the result up
    from the cache.
    """
    from app import backdrops

    for identity in identities or ():
        # resolve_backdrop is best-effort and caches both hits and misses.
        backdrops.resolve_backdrop(identity, allow_network=True)


GAME_ARTWORK_WARM_CHUNK = 25


@shared_task(name="Warm game artwork", ignore_result=True)
def warm_game_artwork_task(media_ids: list[str]):
    """Resolve each game's detail-page carousel so its first visit is warm.

    Scheduled by ``carousel.schedule_game_artwork_warm`` after imports. Games
    run one after another, which keeps a large library inside the artwork
    providers' rate limits; already-resolved games return from cache.
    """
    from app import carousel
    from app.models import MediaTypes, Sources

    for media_id in media_ids or ():
        try:
            carousel.resolve_carousel_media(
                MediaTypes.GAME.value, Sources.IGDB.value, media_id
            )
        except Exception:
            logger.warning("Game artwork warm failed for %s", media_id, exc_info=True)
