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


def instant_push_lock_key(user_id, account_id=None) -> str:
    """Return the cache key that coalesces webhook-triggered pushes.

    One key per connection, so a burst of events from one server never absorbs
    the push another server is waiting for.
    """
    if account_id is None:
        return f"jellyfin_instant_push:{user_id}"
    return f"jellyfin_instant_push:{user_id}:{account_id}"


def get_account(user, account_id):
    """Return one of the user's connections, or None when it is not theirs."""
    from integrations.models import JellyfinAccount

    return JellyfinAccount.objects.filter(user=user, id=account_id).first()


def pick_account(task, user, account_id):
    """Return ``(account, queued_message)`` for a task call.

    A call names its connection. One without (a message queued before multiple
    connections, or an old schedule) is unambiguous for a user with a single
    connection and runs as before. With several it is expanded into one call
    per connection rather than guessing which server was meant.
    """
    from integrations.models import JellyfinAccount

    if account_id is not None:
        return get_account(user, account_id), None
    accounts = list(JellyfinAccount.objects.filter(user=user))
    if len(accounts) <= 1:
        return (accounts[0] if accounts else None), None
    for account in accounts:
        task.apply_async(kwargs={"user_id": user.id, "account_id": account.id})
    return None, f"Queued {len(accounts)} Jellyfin connections."


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
            "Jellyfin still rejects the API key for user %s account %s; skipping run",
            account.user_id,
            account.id,
        )
        record_failure(account, exc, auth=True, error_field=error_field)
        return False

    logger.info("Jellyfin accepted the API key again for user %s account %s",
        account.user_id,
        account.id,
    )
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
