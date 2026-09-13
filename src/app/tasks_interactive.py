"""Tasks consumed by the dedicated interactive Celery worker."""

from celery import shared_task


@shared_task(name="Resolve live playback image")
def resolve_playback_image(user_id: int):
    """Resolve artwork for a cached live playback state in the background."""
    from app import live_playback

    live_playback.resolve_state_image(user_id)


@shared_task(name="app.tasks.refresh_statistics_cache_task")
def refresh_statistics_cache_task(user_id: int, range_name: str):
    """Rebuild the cached Statistics page for a user and range."""
    from app import statistics_cache

    statistics_cache.refresh_statistics_cache(user_id, range_name)
