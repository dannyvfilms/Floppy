"""Celery task that looks up the game YouTube tags on a video."""

from __future__ import annotations

from celery import shared_task


@shared_task(name="Look up YouTube game tag")
def lookup_youtube_game_tag(item_id):
    """Fetch and store the game tag for one shared YouTube video item.

    Runs on the default queue: no page waits on it.
    """
    from app.services import youtube_game

    return youtube_game.refresh_game_tag(item_id)


@shared_task(name="Backfill YouTube game tags")
def backfill_youtube_game_tags():
    """Look up a small batch of videos whose game tag is missing or due a recheck."""
    from app.services import youtube_game

    return {"looked_up": youtube_game.backfill_due_items()}
