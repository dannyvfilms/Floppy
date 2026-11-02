"""Record an integration account's connection health consistently.

``connection_broken`` means one thing: the provider rejected our credentials.
Only an auth failure may set it. A timeout, a refused connection or a 5xx says
nothing about the credentials, so those record the error and leave the flag
alone. Scheduled work gates on "has credentials" rather than ``is_connected``
and re-probes a broken account, so a flag set in error clears itself on the
next good run instead of waiting for a person to reconnect.

See docs/architecture/connection-health.md.
"""

from datetime import timedelta

from django.utils import timezone

from integrations.imports.helpers import retry_on_lock

MAX_ERROR_LENGTH = 500
# How often scheduled work re-probes an account whose credentials were
# rejected. Cheap, but a revoked key should not cost a request every poll.
PROBE_INTERVAL = timedelta(hours=1)


def caused_by(exc, error_types) -> bool:
    """Return whether ``exc`` or anything in its cause chain is one of these."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        if isinstance(exc, error_types):
            return True
        seen.add(id(exc))
        exc = exc.__cause__ or exc.__context__
    return False


def due_for_probe(account, interval=PROBE_INTERVAL) -> bool:
    """Return whether scheduled work should run for this account now.

    Healthy accounts always run. A broken one runs again once ``interval``
    has passed since its last recorded failure, so it can heal on its own.
    """
    if not account.connection_broken:
        return True
    last_failed_at = getattr(account, "last_failed_at", None)
    return last_failed_at is None or timezone.now() - last_failed_at >= interval


def _save(account, fields):
    if hasattr(account, "updated_at"):
        fields.append("updated_at")
    retry_on_lock(lambda: account.save(update_fields=list(dict.fromkeys(fields))))


def record_failure(account, message, *, auth, error_field="last_error_message"):
    """Persist a failed run; only an auth failure marks the account broken."""
    fields = [error_field]
    setattr(account, error_field, str(message)[:MAX_ERROR_LENGTH])
    if auth:
        account.connection_broken = True
        fields.append("connection_broken")
    if hasattr(account, "failure_count"):
        account.failure_count += 1
        account.last_failed_at = timezone.now()
        fields.extend(["failure_count", "last_failed_at"])
    _save(account, fields)


def record_success(account, *, error_field="last_error_message", extra_fields=()):
    """Persist a good run: clear the broken flag, the error, and save extras."""
    account.connection_broken = False
    setattr(account, error_field, "")
    fields = ["connection_broken", error_field, *extra_fields]
    if hasattr(account, "failure_count"):
        account.failure_count = 0
        fields.append("failure_count")
    _save(account, fields)
