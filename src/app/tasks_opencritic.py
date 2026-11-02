"""Celery tasks for OpenCritic game scores."""

from __future__ import annotations

from celery import shared_task
from django.core.cache import cache


@shared_task(name="Refresh item OpenCritic score")
def refresh_item_opencritic_score(item_id, user_id=None):
    """Refresh one game's OpenCritic data, queued when its page is opened.

    ``user_id`` is the viewer, so their personal key is used when they have one.
    """
    from django.contrib.auth import get_user_model

    from app.models import Item
    from app.providers import credentials, opencritic
    from app.services import opencritic_scores

    try:
        item = Item.objects.filter(id=item_id).first()
        if item is None:
            return {"result": "missing_item"}
        user = get_user_model().objects.filter(id=user_id).first() if user_id else None
        with credentials.current_user_scope(user):
            try:
                return {"result": opencritic_scores.refresh_item(item)}
            except opencritic.QuotaExhaustedError:
                return {"result": "quota_exhausted"}
    finally:
        cache.delete(opencritic_scores.QUEUE_LOCK_KEY.format(item_id=item_id))


@shared_task(name="Backfill OpenCritic scores")
def backfill_opencritic_scores():
    """Spend leftover OpenCritic quota in the hour before it resets."""
    from app.services import opencritic_scores

    return {"refreshed": opencritic_scores.backfill()}
