"""Start and finish progress lines for every Celery task.

A task that hangs or times out raises nothing, so the log shows it only as a
``task_started`` line with no ``task_finished`` after it. Both lines go through
``app.progress_log`` so the diagnostic report shows them to every signed-in
user. They carry the task name, a short id, the end state and the duration:
never the task's arguments, which can hold usernames or titles.
"""

import time

from app.progress_log import progress

_started: dict[str, float] = {}


def _task_started(task_id=None, task=None, **_kwargs):
    _started[task_id] = time.monotonic()
    progress(
        "task_started name=%s id=%s",
        getattr(task, "name", "<unknown>"),
        str(task_id)[:8],
    )


def _task_finished(task_id=None, task=None, state=None, **_kwargs):
    began = _started.pop(task_id, None)
    duration_ms = int((time.monotonic() - began) * 1000) if began else -1
    progress(
        "task_finished name=%s id=%s state=%s duration_ms=%d",
        getattr(task, "name", "<unknown>"),
        str(task_id)[:8],
        state or "unknown",
        duration_ms,
    )


def connect_celery_signals() -> None:
    """Bind the start and finish lines around every task, once per process."""
    from celery.signals import task_postrun, task_prerun

    task_prerun.connect(
        _task_started,
        weak=False,
        dispatch_uid="task_progress_prerun",
    )
    task_postrun.connect(
        _task_finished,
        weak=False,
        dispatch_uid="task_progress_postrun",
    )
