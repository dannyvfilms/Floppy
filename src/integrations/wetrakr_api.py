"""WeTrakr's HTTP API: the device-flow login and authenticated sync calls.

Written against an unofficial transcription of WeTrakr's documentation dated
2026-10-01 (API changelog 1.0.7); nothing here has been checked against a live
account yet, which is why the details that were ambiguous are named below and
each is tested against a mock, not WeTrakr.

- ``DEVICE_TOKEN_FIELDS``: the documentation calls the device code ``code`` on
  the route page and ``device_code`` in the overview. ``code`` goes first, and
  the other is tried once if WeTrakr rejects the request as invalid.
- Error bodies come in two shapes and both are read.
- Rate-limit reset headers are read as seconds, or as an epoch time if large.

The fixed host means no user-supplied URL ever reaches ``requests`` here, so
this does not use the outbound-fetch boundary for user-configured URLs.
"""

import logging
from datetime import timedelta
from http import HTTPStatus

import requests
from cryptography.fernet import InvalidToken
from django.utils import timezone

from app.cache_safety import ON_ERROR_SKIP, acquire_lock, release_lock
from app.providers import credentials
from integrations import connection_health
from integrations.imports.helpers import decrypt, encrypt
from integrations.models import WeTrakrAccount
from integrations.state.adapters.base import (
    AdapterError,
    TerminalAdapterError,
    TransientAdapterError,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://api.wetrakr.com"
API_VERSION = "1"
TIMEOUT = 30
DEVICE_TOKEN_FIELDS = ("code", "device_code")

# Refresh a little before the access token actually expires.
REFRESH_MARGIN = timedelta(minutes=5)
DEFAULT_ACCESS_LIFETIME = timedelta(days=7)
REFRESH_LOCK_TIMEOUT = 30
REFRESH_WAIT_SECONDS = 10

# Epoch seconds are far larger than any plausible wait in seconds.
EPOCH_THRESHOLD = 10**9
DEFAULT_RETRY_AFTER = 60
SECONDS_PER_DAY = 86400


class WeTrakrAuthError(TerminalAdapterError):
    """WeTrakr rejected the credentials; the user has to reconnect."""


class WeTrakrKeyError(WeTrakrAuthError):
    """WeTrakr rejected the application key itself."""


def client_id_for(user):
    """Return the application key this user (or the instance) has configured."""
    with credentials.current_user_scope(user):
        return credentials.get("wetrakr", "client_id")


def read_error(response):
    """Return ``(code, message)`` from either of WeTrakr's error shapes."""
    try:
        body = response.json()
    except ValueError:
        return "", ""
    if not isinstance(body, dict):
        return "", ""
    error = body.get("error")
    if isinstance(error, dict):
        return str(error.get("code") or ""), str(error.get("message") or "")
    return str(error or ""), str(body.get("message") or "")


def retry_after(response, now=None):
    """Return how many seconds to wait after a 429.

    A spent daily quota waits for the next UTC midnight; the per-minute limit
    waits for the reset the response names.
    """
    now = now or timezone.now()
    if response.headers.get("X-Quota-Remaining") == "0":
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return int((midnight + timedelta(days=1) - now).total_seconds())
    reset = response.headers.get("RateLimit-Reset") or response.headers.get(
        "Retry-After",
    )
    try:
        seconds = int(float(reset))
    except (TypeError, ValueError):
        return DEFAULT_RETRY_AFTER
    if seconds >= EPOCH_THRESHOLD:
        seconds = int(seconds - now.timestamp())
    return max(seconds, 1)


def _headers(client_id, access_token=""):
    headers = {
        "wetrakr-api-version": API_VERSION,
        "wetrakr-api-key": client_id,
        "Content-Type": "application/json",
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    return headers


def _send(method, path, *, client_id, access_token="", json=None, extra_headers=None):
    """Make one request and return the response, or raise a transient error."""
    headers = _headers(client_id, access_token)
    headers.update(extra_headers or {})
    try:
        return requests.request(
            method,
            f"{BASE_URL}{path}",
            headers=headers,
            json=json,
            timeout=TIMEOUT,
            allow_redirects=False,
        )
    except requests.RequestException as error:
        message = "WeTrakr could not be reached."
        raise TransientAdapterError(message) from error


def raise_for_status(response):
    """Turn an unsuccessful response into the error the engine understands."""
    status = response.status_code
    if HTTPStatus.OK <= status < HTTPStatus.MULTIPLE_CHOICES:
        return
    code, message = read_error(response)
    detail = message or code or f"HTTP {status}"
    if status == HTTPStatus.TOO_MANY_REQUESTS:
        wait = retry_after(response)
        text = f"WeTrakr rate limit reached. {detail}"
        raise TransientAdapterError(text, retry_after=wait)
    if status >= HTTPStatus.INTERNAL_SERVER_ERROR:
        text = f"WeTrakr is temporarily unavailable (HTTP {status})."
        raise TransientAdapterError(text)
    if status == HTTPStatus.UNAUTHORIZED:
        if code == "MISSING_API_KEY":
            text = "WeTrakr rejected the app key. Check it in Settings."
            raise WeTrakrKeyError(text)
        text = "WeTrakr rejected the login. Reconnect your account."
        raise WeTrakrAuthError(text)
    if status in {420, 426}:
        # Plan limit and VIP-only route: retrying cannot help.
        text = f"WeTrakr plan limit: {detail}"
        raise TerminalAdapterError(text)
    text = f"WeTrakr request failed: {detail}"
    raise TerminalAdapterError(text)


def _json(response):
    try:
        data = response.json()
    except ValueError as error:
        message = "WeTrakr returned an invalid response."
        raise TransientAdapterError(message) from error
    if not isinstance(data, dict):
        message = "WeTrakr returned an invalid response."
        raise TransientAdapterError(message)
    return data


# --- device-flow login -------------------------------------------------------


class DeviceFlowError(AdapterError):
    """The approval cannot continue; the message says why, in plain words."""


def start_device_flow(client_id):
    """Ask WeTrakr for a code the user approves on wetrakr.com."""
    response = _send(
        "POST",
        "/oauth/device/code",
        client_id=client_id,
        json={"client_id": client_id},
    )
    status = response.status_code
    if status == HTTPStatus.LOCKED:
        message = "WeTrakr has suspended this app key."
        raise DeviceFlowError(message)
    if status in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN, HTTPStatus.NOT_FOUND}:
        message = "WeTrakr did not accept this app key."
        raise DeviceFlowError(message)
    if status == HTTPStatus.TOO_MANY_REQUESTS:
        message = "WeTrakr allows only a few login codes at a time. Try again later."
        raise DeviceFlowError(message)
    raise_for_status(response)
    data = _json(response)
    device_code = data.get("device_code")
    user_code = data.get("user_code")
    url = data.get("verification_url") or data.get("verification_uri")
    if not (device_code and user_code and url):
        message = "WeTrakr returned an incomplete login code."
        raise DeviceFlowError(message)
    return {
        "device_code": str(device_code),
        "user_code": str(user_code),
        "verification_url": str(url),
        "interval": int(data.get("interval") or 5),
        "expires_in": int(data.get("expires_in") or 600),
    }


def poll_device_flow(client_id, device_code):
    """Check once whether the user has approved; returns ``(state, payload)``.

    ``state`` is ``approved`` (payload is the token response), ``pending`` (an
    optional payload of ``{"interval": n}`` asks for slower polling) or
    ``failed`` (payload is a message for the user).
    """
    first_error = None
    for field in DEVICE_TOKEN_FIELDS:
        response = _send(
            "POST",
            "/oauth/device/token",
            client_id=client_id,
            json={"client_id": client_id, field: device_code},
        )
        status = response.status_code
        if status == HTTPStatus.OK:
            tokens = _json(response)
            if not tokens.get("access_token") or not tokens.get("refresh_token"):
                return "failed", "WeTrakr returned no login tokens."
            return "approved", tokens
        code, _message = read_error(response)
        if status == HTTPStatus.BAD_REQUEST and code == "authorization_pending":
            return "pending", None
        if status == HTTPStatus.TOO_MANY_REQUESTS:
            return "pending", {"interval": retry_after(response)}
        terminal = {
            HTTPStatus.GONE: "The code expired. Start again.",
            418: "The login was denied on WeTrakr.",
            HTTPStatus.CONFLICT: "That code was already used. Start again.",
            HTTPStatus.NOT_FOUND: "WeTrakr did not recognise the code. Start again.",
            HTTPStatus.UNAUTHORIZED: "WeTrakr did not accept this app key.",
            HTTPStatus.LOCKED: "WeTrakr has suspended this app key.",
        }
        if status in terminal:
            return "failed", terminal[status]
        if status == HTTPStatus.BAD_REQUEST:
            # Possibly the wrong name for the code field; try the other once.
            first_error = first_error or code or "invalid request"
            continue
        if status >= HTTPStatus.INTERNAL_SERVER_ERROR:
            return "pending", None
        return "failed", f"WeTrakr could not complete the login (HTTP {status})."
    return "failed", f"WeTrakr rejected the login request ({first_error})."


def token_fields(tokens, now=None):
    """Return the account columns for a token response, encrypted."""
    now = now or timezone.now()
    try:
        lifetime = timedelta(seconds=int(tokens.get("expires_in")))
    except (TypeError, ValueError):
        lifetime = DEFAULT_ACCESS_LIFETIME
    return {
        "access_token": encrypt(tokens["access_token"]),
        "refresh_token": encrypt(tokens["refresh_token"]),
        "access_expires_at": now + lifetime,
    }


def logout(client_id, access_token, refresh_token):
    """Ask WeTrakr to end a login. Best effort: the caller has already let go."""
    response = _send(
        "POST",
        "/oauth/logout",
        client_id=client_id,
        access_token=access_token,
        json={"refresh_token": refresh_token},
    )
    if response.status_code not in {HTTPStatus.UNAUTHORIZED, HTTPStatus.NOT_FOUND}:
        raise_for_status(response)


# --- authenticated calls -----------------------------------------------------


class WeTrakrClient:
    """Authenticated calls for one account, refreshing its login when needed."""

    def __init__(self, account):
        """Bind to one connected account."""
        self.account = account

    def _tokens(self):
        try:
            return decrypt(self.account.access_token), decrypt(
                self.account.refresh_token,
            )
        except InvalidToken:
            return "", ""

    def _needs_refresh(self):
        expires = self.account.access_expires_at
        return expires is None or expires - timezone.now() <= REFRESH_MARGIN

    def request(
        self,
        method,
        path,
        *,
        json=None,
        idempotency_key=None,
        missing_ok=False,
    ):
        """Call a sync route, recording whether WeTrakr still accepts the login.

        ``missing_ok`` answers a 404 with ``{"missing": True}`` instead of an
        error, for a delete where "already gone" is the result wanted.
        """
        try:
            data = self._request(
                method,
                path,
                json=json,
                idempotency_key=idempotency_key,
                missing_ok=missing_ok,
            )
        except WeTrakrAuthError as error:
            # Only a rejection of the credentials marks the connection broken.
            connection_health.record_failure(self.account, str(error), auth=True)
            raise
        except AdapterError as error:
            connection_health.record_failure(self.account, str(error), auth=False)
            raise
        if self.account.connection_broken or self.account.last_error_message:
            connection_health.record_success(self.account)
        return data

    def _request(
        self,
        method,
        path,
        *,
        json=None,
        idempotency_key=None,
        missing_ok=False,
    ):
        if not self.account.refresh_token:
            message = "WeTrakr is not connected. Connect your account."
            raise WeTrakrAuthError(message)
        if self._needs_refresh():
            self.refresh()
        extra = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        access, _refresh = self._tokens()
        response = _send(
            method,
            path,
            client_id=self.account.client_id,
            access_token=access,
            json=json,
            extra_headers=extra,
        )
        if response.status_code == HTTPStatus.UNAUTHORIZED:
            code, _message = read_error(response)
            if code != "MISSING_API_KEY":
                self.refresh(force=True)
                access, _refresh = self._tokens()
                response = _send(
                    method,
                    path,
                    client_id=self.account.client_id,
                    access_token=access,
                    json=json,
                    extra_headers=extra,
                )
        if missing_ok and response.status_code == HTTPStatus.NOT_FOUND:
            return {"missing": True}
        raise_for_status(response)
        if not response.content:
            return {}
        return _json(response)

    def refresh(self, *, force=False):
        """Exchange the refresh token for new tokens, once across all workers.

        WeTrakr rotates the refresh token on every use and rejects the old one
        after a short grace period, so two workers refreshing at once would log
        the account out. A database row lock does not serialize SQLite, so this
        takes a cache lock and re-reads the account once it holds it: if
        another worker already rotated the token, that is used instead.
        """
        stale = self.account.refresh_token
        lock_key = f"wetrakr_refresh:{self.account.pk}"
        if not acquire_lock(
            lock_key,
            timeout=REFRESH_LOCK_TIMEOUT,
            on_error=ON_ERROR_SKIP,
        ):
            self._wait_for_other_refresh(stale)
            return
        try:
            self.account.refresh_from_db()
            if self.account.refresh_token != stale or (
                not force and not self._needs_refresh()
            ):
                return
            self._exchange_refresh_token()
        finally:
            release_lock(lock_key)

    def _wait_for_other_refresh(self, stale):
        import time

        deadline = time.monotonic() + REFRESH_WAIT_SECONDS
        while time.monotonic() < deadline:
            self.account.refresh_from_db()
            if self.account.refresh_token != stale:
                return
            time.sleep(0.5)
        message = "Another WeTrakr login refresh is still running."
        raise TransientAdapterError(message)

    def _exchange_refresh_token(self):
        _access, refresh = self._tokens()
        if not refresh:
            message = "WeTrakr login cannot be read. Reconnect your account."
            raise WeTrakrAuthError(message)
        response = _send(
            "POST",
            "/oauth/token/refresh",
            client_id=self.account.client_id,
            json={"refresh_token": refresh},
        )
        if response.status_code in {
            HTTPStatus.BAD_REQUEST,
            HTTPStatus.UNAUTHORIZED,
            HTTPStatus.FORBIDDEN,
        }:
            message = "WeTrakr no longer accepts this login. Reconnect your account."
            raise WeTrakrAuthError(message)
        raise_for_status(response)
        tokens = _json(response)
        if not tokens.get("access_token") or not tokens.get("refresh_token"):
            message = "WeTrakr returned no login tokens."
            raise TransientAdapterError(message)
        fields = token_fields(tokens)
        # Compare-and-set on the old ciphertext, so a refresh that lost a race
        # never overwrites the winner's newer token.
        WeTrakrAccount.objects.filter(
            pk=self.account.pk,
            refresh_token=self.account.refresh_token,
        ).update(**fields)
        self.account.refresh_from_db()
