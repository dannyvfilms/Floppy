"""Helpers the integration view modules share.

Queue a task and tell the user when the broker is unreachable, send the user
back where they came from after connecting a source, consume OAuth state, find
a user's periodic task, and retry connect/disconnect writes on SQLite locks.
A helper used by one subject stays in that subject's views module.
"""

import logging
from http import HTTPStatus

from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

from app import helpers as app_helpers
from app.db_retry import run_retryable_db_operation
from app.redis_diagnosis import queue_failure_message
from integrations import pending_auth

logger = logging.getLogger(__name__)


def _queue_task_or_message(request, task, *args, **kwargs):
    """Queue a task and turn broker failures into a user message instead of a 500."""
    try:
        return task.delay(*args, **kwargs)
    except Exception as error:
        logger.exception("Could not queue background import task")
        messages.error(request, _import_queue_failure_message(error))
        return False


def _import_queue_failure_message(error):
    """Name an unreachable Redis broker instead of blaming the worker (#1263)."""
    return queue_failure_message(
        error,
        "The import could not be queued.",
        "Check the worker and try again.",
        settings.CELERY_BROKER_URL,
    )


def _queue_task_quietly(task, *args, **kwargs):
    """Queue a task, logging (not raising) on broker failure.

    For call sites with no `messages` flow to surface the failure through
    (webhook receivers, JSON polling endpoints).
    """
    try:
        task.delay(*args, **kwargs)
    except Exception:
        logger.exception("Could not queue background task")
        return False
    return True


def _integration_redirect(request, *, connected_slug=None, next_url=None):
    """Redirect back to `next` (e.g. the onboarding wizard) if present.

    Falls back to `import_data`, the normal Settings destination. When
    `connected_slug` is given, records it on the user's onboarding progress
    so the setup wizard's queue drops that source on the next request.
    """
    if connected_slug:
        user = request.user
        if connected_slug not in user.onboarding_connected_sources:
            user.onboarding_connected_sources = [*user.onboarding_connected_sources, connected_slug]
            user.save(update_fields=["onboarding_connected_sources"])
    destination = next_url or request.POST.get("next") or request.GET.get("next")
    if pending_auth.is_native_return(destination):
        # Back into the native app: only its own scheme, never another URL.
        # Django's redirect() refuses custom schemes, so answer directly.
        return HttpResponse(status=HTTPStatus.FOUND, headers={"Location": destination})
    return redirect(
        app_helpers.safe_return_url(request, destination, reverse("import_data"))
    )


def _consume_oauth_state(request, provider):
    """Consume a provider OAuth state value and reject missing or replayed state."""
    state_token = request.GET.get("state")
    if not state_token:
        logger.warning("%s OAuth callback missing state parameter", provider)
        messages.error(
            request,
            f"Invalid or expired {provider} authorization request.",
        )
        return None

    state_data = pending_auth.pop_state(request, state_token)
    if not isinstance(state_data, dict):
        logger.warning("%s OAuth callback state not found in session", provider)
        messages.error(
            request,
            f"Invalid or expired {provider} authorization request.",
        )
        return None

    return state_data


def _plex_watchlist_task_filter(user_id):
    """Match a user's watchlist task regardless of JSON spacing/quotes."""
    return (
        Q(kwargs__contains=f"'user_id': {user_id},")
        | Q(
            kwargs__contains=f"'user_id': {user_id}" + "}",
        )
        | Q(
            kwargs__contains=f'"user_id": {user_id},',
        )
        | Q(
            kwargs__contains=f'"user_id": {user_id}' + "}",
        )
    )


def _periodic_task_filter_for_user(user_id):
    """Match a user's periodic task regardless of JSON spacing/quotes."""
    return _plex_watchlist_task_filter(user_id)


def _run_with_lock_retry(operation_name, fn):
    """Run an integration connect/disconnect DB write with retry on SQLite locks.

    Connect/disconnect views create or delete `django_celery_beat`
    `PeriodicTask` rows, which fire a signal that writes to a shared
    singleton row (`PeriodicTasks.changed()`) — a serialization hotspot on
    SQLite. Wrapping the write in a retried transaction turns a transient
    lock into a short delay instead of a 503 (see issue #1112).

    `max_retries=1` (2 attempts total) rather than the helper's default of
    5: each attempt can block for up to `SQLITE_BUSY_TIMEOUT_SECONDS`
    (30s by default) before raising, and nginx.conf sets no explicit
    `proxy_read_timeout` (nginx's own default is 60s) — more attempts would
    risk the proxy returning a gateway timeout to the user while this view
    keeps retrying underneath it, so the write could still commit after the
    client has already seen a failure.
    """

    def _atomic_fn():
        with transaction.atomic():
            return fn()

    return run_retryable_db_operation(
        _atomic_fn, operation_name=operation_name, max_retries=1
    ).value
