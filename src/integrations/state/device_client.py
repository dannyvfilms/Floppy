"""The authenticated-call machinery every device-login destination shares.

A destination's client says how to make one request and how to read one reply;
this base does the rest, which is the part that is easy to get subtly wrong:

- refresh a little before the access token expires, and once on a 401;
- refresh **once across all workers**. A database row lock does not serialize
  SQLite, so the refresh takes a cache lock and re-reads the account once it
  holds it. If another worker already refreshed, that result is used. Two
  workers refreshing the same login can log it out (WeTrakr rotates the refresh
  token; SIMKL replaces the access token), so neither may race;
- record whether the service still accepts the login, and only a rejection of
  the credentials marks the connection broken.
"""

import time
from datetime import timedelta
from http import HTTPStatus

from cryptography.fernet import InvalidToken
from django.utils import timezone

from app.cache_safety import ON_ERROR_SKIP, acquire_lock, release_lock
from integrations import connection_health
from integrations.imports.helpers import decrypt
from integrations.state.adapters.base import AdapterError, TransientAdapterError


class DeviceLoginClient:
    """Authenticated calls for one account, refreshing its login when needed.

    Subclasses set the attributes below and implement ``_call``, ``_read`` and
    ``_exchange_refresh_token``.
    """

    #: Shown in messages ("WeTrakr", "SIMKL").
    LABEL = ""
    #: Prefix of the cache lock that serializes refreshes.
    LOCK_PREFIX = ""
    #: The raised when the service rejects the credentials; a
    #: ``TerminalAdapterError``.
    auth_error = AdapterError
    #: The account column that changes when a refresh succeeds. WeTrakr rotates
    #: its refresh token; SIMKL keeps it and only replaces the access token.
    CHANGES_ON_REFRESH = "refresh_token"
    REFRESH_MARGIN = timedelta(minutes=5)
    REFRESH_LOCK_TIMEOUT = 30

    #: Seconds to wait for another worker's refresh. A property in subclasses
    #: whose tests adjust it on the module.
    @property
    def refresh_wait_seconds(self):
        """Return how long to wait for another worker's refresh."""
        return 10

    def __init__(self, account):
        """Bind to one connected account."""
        self.account = account

    # --- hooks ---------------------------------------------------------------

    def _call(self, method, path, access_token, **options):
        """Make one request with this access token and return the response."""
        raise NotImplementedError

    def _read(self, response, **options):
        """Raise for an unsuccessful reply, else return its data."""
        raise NotImplementedError

    def _exchange_refresh_token(self):
        """Exchange the refresh token and store the result (compare and set)."""
        raise NotImplementedError

    def _refreshable_rejection(self, response):
        """Return whether a 401 means the access token (not the app key) is bad."""
        return True

    # --- shared --------------------------------------------------------------

    def _tokens(self):
        try:
            return decrypt(self.account.access_token), decrypt(
                self.account.refresh_token,
            )
        except InvalidToken:
            return "", ""

    def _needs_refresh(self):
        expires = self.account.access_expires_at
        return expires is None or expires - timezone.now() <= self.REFRESH_MARGIN

    def request(self, method, path, **options):
        """Call a route, recording whether the service still accepts the login."""
        try:
            data = self._request(method, path, **options)
        except self.auth_error as error:
            # Only a rejection of the credentials marks the connection broken.
            connection_health.record_failure(self.account, str(error), auth=True)
            raise
        except AdapterError as error:
            connection_health.record_failure(self.account, str(error), auth=False)
            raise
        if self.account.connection_broken or self.account.last_error_message:
            connection_health.record_success(self.account)
        return data

    def _request(self, method, path, **options):
        if not self.account.refresh_token:
            message = f"{self.LABEL} is not connected. Connect your account."
            raise self.auth_error(message)
        if self._needs_refresh():
            self.refresh()
        access, _refresh = self._tokens()
        response = self._call(method, path, access, **options)
        if response.status_code == HTTPStatus.UNAUTHORIZED and (
            self._refreshable_rejection(response)
        ):
            self.refresh(force=True)
            access, _refresh = self._tokens()
            response = self._call(method, path, access, **options)
        return self._read(response, **options)

    def refresh(self, *, force=False):
        """Exchange the refresh token for a new login, once across all workers."""
        stale = getattr(self.account, self.CHANGES_ON_REFRESH)
        lock_key = f"{self.LOCK_PREFIX}_refresh:{self.account.pk}"
        if not acquire_lock(
            lock_key,
            timeout=self.REFRESH_LOCK_TIMEOUT,
            on_error=ON_ERROR_SKIP,
        ):
            self._wait_for_other_refresh(stale)
            return
        try:
            self.account.refresh_from_db()
            if getattr(self.account, self.CHANGES_ON_REFRESH) != stale or (
                not force and not self._needs_refresh()
            ):
                return
            self._exchange_refresh_token()
        finally:
            release_lock(lock_key)

    def _wait_for_other_refresh(self, stale):
        deadline = time.monotonic() + self.refresh_wait_seconds
        while time.monotonic() < deadline:
            self.account.refresh_from_db()
            if getattr(self.account, self.CHANGES_ON_REFRESH) != stale:
                return
            time.sleep(0.5)
        message = f"Another {self.LABEL} login refresh is still running."
        raise TransientAdapterError(message)
