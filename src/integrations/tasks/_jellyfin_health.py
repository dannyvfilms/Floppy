"""Connection health shared by the Jellyfin push and pull tasks.

Both tasks follow the contract in ``integrations.connection_health``: only a
rejected API key marks the account broken, a broken account is re-probed on
its next run, and a transient failure is retried with backoff.
"""

import logging

from integrations.connection_health import caused_by, record_failure, record_success
from integrations.imports.helpers import decrypt_or_raise
from integrations.jellyfin_client import (
    JellyfinAuthError,
    JellyfinClient,
    JellyfinClientError,
)

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BASE_SECONDS = 60
INSTANT_PUSH_DEBOUNCE_SECONDS = 60


def instant_push_lock_key(user_id) -> str:
    """Return the cache key that coalesces webhook-triggered pushes."""
    return f"jellyfin_instant_push:{user_id}"


def has_credentials(account) -> bool:
    """Return whether the account can be probed at all."""
    return bool(account and account.base_url and account.api_key)


def reprobe_if_broken(account, *, error_field, client=None) -> bool:
    """Return whether the run may proceed, clearing a stale broken flag.

    A transient probe failure propagates so the caller retries it like any
    other network error.
    """
    if not account.connection_broken:
        return True

    if client is None:
        client = JellyfinClient(account.base_url, decrypt_or_raise(account.api_key))
    try:
        client.healthcheck()
    except JellyfinAuthError as exc:
        logger.warning(
            "Jellyfin still rejects the API key for user %s; skipping run",
            account.user_id,
        )
        record_failure(account, exc, auth=True, error_field=error_field)
        return False

    logger.info("Jellyfin accepted the API key again for user %s", account.user_id)
    record_success(account, error_field=error_field)
    return True


def handle_failure(task, account, exc, *, error_field):
    """Record a failed run, retrying it when the failure is transient."""
    auth = caused_by(exc, JellyfinAuthError)
    record_failure(account, exc, auth=auth, error_field=error_field)
    transient = not auth and caused_by(exc, JellyfinClientError)
    if transient and task.request.retries < MAX_RETRIES:
        countdown = RETRY_BASE_SECONDS * 2**task.request.retries
        raise task.retry(exc=exc, countdown=countdown, max_retries=MAX_RETRIES)
