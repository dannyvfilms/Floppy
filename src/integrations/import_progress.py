"""Cache-backed live progress state for in-progress import tasks.

Mirrors the pattern in ``app.live_playback``: a Celery task writes its
current progress to the cache under a key derived from its task ID, and
the request path reads it back for a polled UI fragment. The active task
ID is threaded through a contextvar (set by ``tracking()``) rather than a
task kwarg, so importer functions can call ``report()`` without any
signature changes.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging

from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

PROGRESS_CACHE_PREFIX = "import_progress"
PROGRESS_CACHE_TIMEOUT_SECONDS = 5 * 60

_current_task_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "import_progress_task_id",
    default=None,
)

_current_import_run_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "import_progress_import_run_id",
    default=None,
)


def _cache_key(task_id: str) -> str:
    return f"{PROGRESS_CACHE_PREFIX}:{task_id}"


@contextlib.contextmanager
def tracking(task_id: str | None, import_run_id: int | None = None):
    """Mark ``task_id``/``import_run_id`` as active for this import.

    Clears the progress cache entry on exit regardless of success/failure,
    so a finished or failed import never leaves a stale progress bar.
    ``import_run_id`` is threaded the same way ``task_id`` is: as ambient
    context rather than a kwarg, so importer functions can tag the media
    they create via ``get_current_import_run_id()`` without any signature
    changes.
    """
    task_token = _current_task_id.set(task_id)
    run_token = _current_import_run_id.set(import_run_id)
    try:
        yield
    finally:
        _current_task_id.reset(task_token)
        _current_import_run_id.reset(run_token)
        if task_id:
            cache.delete(_cache_key(task_id))


def get_current_import_run_id() -> int | None:
    """Return the ``ImportRun`` id for the currently tracked import, if any."""
    return _current_import_run_id.get()


def report(current: int, total: int | None = None, label: str | None = None) -> None:
    """Record progress for the currently tracked import task, if any.

    ``total=None`` means the final count isn't known yet (e.g. still
    gathering items from a paginated API) — the UI renders this as an
    indeterminate state. No-ops outside a ``tracking()`` context, so this
    is safe to call from importer code under test or run standalone.
    """
    task_id = _current_task_id.get()
    if not task_id:
        return

    cache.set(
        _cache_key(task_id),
        {
            "current": current,
            "total": total,
            "label": label,
            "updated_at_ts": int(timezone.now().timestamp()),
        },
        timeout=PROGRESS_CACHE_TIMEOUT_SECONDS,
    )


def get_progress(task_id: str | None) -> dict | None:
    """Return the current progress dict for ``task_id``, if any is recorded."""
    if not task_id:
        return None
    return cache.get(_cache_key(task_id))
