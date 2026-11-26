"""Celery tasks that look up YouTube game tags and video runtimes."""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="Look up YouTube game tag")
def lookup_youtube_game_tag(item_id):
    """Fetch and store the game tag and runtime for one shared YouTube video.

    Runs on the default queue: no page waits on it.
    """
    from app.services import youtube_game

    return youtube_game.refresh_due_item(item_id)


@shared_task(name="Backfill YouTube game tags")
def backfill_youtube_game_tags():
    """Look up a small batch of videos due for game tag or runtime collection."""
    from app.services import youtube_game

    return {"looked_up": youtube_game.backfill_due_items()}


@shared_task(name="Backfill opened game's YouTube history", ignore_result=True,
             soft_time_limit=120, time_limit=140)
def backfill_youtube_game_detail(user_id, game_id, token):
    """Prioritize a viewer's game in bounded batches on the default worker."""
    from django.core.cache import cache

    from app.models import Item, MediaTypes
    from app.services import youtube_game
    from app.services import youtube_game_watch as watch

    key = watch._game_backfill_key(user_id, game_id)
    if cache.get(key) != token:
        return
    cache.touch(key, watch.GAME_BACKFILL_TTL)
    logger.info("youtube_game_detail_backfill start game=%s", game_id)
    ids = []
    continuing = False
    try:
        game = Item.objects.filter(pk=game_id, media_type=MediaTypes.GAME.value).first()
        if game is None:
            return
        ids = watch.game_backfill_candidates(user_id, game)
        for item_id in ids:
            if youtube_game.refresh_due_item(item_id) == youtube_game.RATE_LIMITED:
                return
        if len(ids) == watch.GAME_BACKFILL_BATCH:
            backfill_youtube_game_detail.apply_async((user_id, game_id, token), countdown=2)
            continuing = True
    finally:
        if not continuing and cache.get(key) == token:
            cache.set(key, "", watch.SUMMARY_TTL)
        logger.info("youtube_game_detail_backfill finish game=%s batch=%s continuing=%s",
                    game_id, len(ids), continuing)
