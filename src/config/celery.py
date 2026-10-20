import gc
import os

from celery import Celery, Task, states
from celery.exceptions import Ignore
from celery.signals import worker_process_init, worker_ready, worker_shutting_down

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")



class FloppyTask(Task):
    """Base task that refuses to run an import the user cancelled while queued.

    ``cancel_pending_import`` marks the tracked row REVOKED, which survives a
    worker restart that loses Celery's in-memory revoke list. Raising Ignore
    here stops the task before it does any work and leaves that row REVOKED
    (no success or failure signal fires), for every tracked task at once.
    """

    def __call__(self, *args, **kwargs):
        """Skip the task when its tracked row was cancelled, else run it."""
        from django_celery_results.models import TaskResult

        from app.signals import TRACKED_TASK_NAMES

        task_id = self.request.id
        if (
            task_id
            and self.name in TRACKED_TASK_NAMES
            and TaskResult.objects.filter(
                task_id=task_id,
                status=states.REVOKED,
            ).exists()
        ):
            raise Ignore
        return super().__call__(*args, **kwargs)


app = Celery("floppy", task_cls=FloppyTask)

app.config_from_object("django.conf:settings", namespace="CELERY")

# The dedicated interactive worker only consumes the task modules listed in
# CELERY_IMPORTS. Avoid autodiscovering every background task and importer into
# that long-lived process. Background and combined workers retain the complete
# task registry.
if os.environ.get("FLOPPY_PROCESS_ROLE") != "interactive":
    app.autodiscover_tasks()


@worker_ready.connect
def _enable_fault_log(**_kwargs):
    """Record the traceback of a fatal signal in a worker (see run_state)."""
    from config import run_state

    run_state.enable_fault_log()


@worker_shutting_down.connect
def _log_shutdown(sig=None, how=None, **_kwargs):
    """Record which tasks were running when the worker was told to stop."""
    import logging

    from config import run_state

    try:
        run_state.log_worker_shutdown(sig, how)
    except Exception:  # diagnostics must never block a shutdown
        logging.getLogger(__name__).debug("shutdown note failed", exc_info=True)


@worker_ready.connect
def _freeze_parent_image(**_kwargs):
    """Move this worker's imported image out of the garbage collector's reach.

    The prefork pool forks its children from this process, so whatever is
    imported here starts shared between them. Collection un-shares it: a pass
    writes to the header of every object it examines, and a written page stops
    being shared.

    Production measured every Python process in the container converging on
    the same ~30 MiB of still-shared memory after three hours, down from
    60-76 MiB. That it is the same floor for the interactive child, the web
    workers and the gunicorn master -- processes with nothing in common but a
    fork and a garbage collector -- is what identifies collection as the
    cause rather than any particular workload.

    Objects created after this point are still collected normally.
    """
    gc.collect()
    gc.freeze()


@worker_process_init.connect
def _freeze_child_image(**_kwargs):
    """Do the same in a pool child, for the pages it inherited.

    Freezing in the parent stops the parent from un-sharing them; this stops
    the child from doing it from its own side. Both are needed, and this also
    covers the children forked before the parent signalled ready.
    """
    gc.collect()
    gc.freeze()
