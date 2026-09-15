"""Tasks consumed by the dedicated interactive Celery worker."""

from celery import shared_task


@shared_task(name="Resolve live playback image")
def resolve_playback_image(user_id: int):
    """Resolve artwork for a cached live playback state in the background."""
    from app import live_playback

    live_playback.resolve_state_image(user_id)


@shared_task(name="app.tasks.refresh_statistics_cache_task")
def refresh_statistics_cache_task(user_id: int, range_name: str, force: bool = False):
    """Plan a resumable Statistics refresh run and queue its first chunk.

    This used to rebuild the whole range inline, which owned the single-slot
    interactive worker for the entire rebuild. It now only plans the run; the
    days are built by ``continue_statistics_refresh_task``, one bounded chunk
    per message, so latency-sensitive work can land in between.
    """
    from app import statistics_refresh_run

    statistics_refresh_run.start_chunked_run(user_id, range_name, force=force)


@shared_task(
    name="app.tasks.continue_statistics_refresh_task",
    bind=True,
    max_retries=3,
    default_retry_delay=5,
)
def continue_statistics_refresh_task(self, user_id: int, range_name: str, run_id: str):
    """Advance one chunk of a Statistics refresh run, then release the worker.

    A chunk that raises is retried a bounded number of times. The run's cursor
    is only advanced by a chunk that completed, so a retry redoes exactly the
    failed chunk and never re-counts a finished one.
    """
    from app import statistics_refresh_run

    try:
        statistics_refresh_run.advance_chunked_run(user_id, range_name, run_id)
    except Exception as exc:
        raise self.retry(exc=exc) from exc
