"""SIMKL's HTTP API for sending plays: the device login and authenticated calls.

This is the writing side. The import (``integrations.imports.simkl``) reads with
its own token and is left alone; a device login here asks for
``media:read media:write`` and is stored separately, so connecting one never
changes the other.

Facts from SIMKL's AUTH V2 documentation that the code relies on:

- the device flow needs no client secret and works for any V2 app (a V1 app
  gets ``401 invalid_client``);
- there is no "denied" signal while polling: a user who declines just keeps
  producing ``authorization_pending``, so the code's own expiry ends the wait;
- an unrecognised scope is quietly downgraded to read-only, so the granted
  scope is checked before the login is kept;
- access tokens last 7 days; the refresh token does not rotate, but refreshing
  replaces the access token at once, so two refreshes must not run together;
- the daily quota resets at midnight America/New_York, and a write made while
  another is running answers ``400`` with ``error: "rate_limit"``.

The host is fixed, so no user-supplied URL ever reaches ``requests`` here.
"""

import logging
from datetime import timedelta
from http import HTTPStatus
from zoneinfo import ZoneInfo

import requests
from django.conf import settings
from django.utils import timezone

from app.providers import credentials
from integrations.imports.helpers import encrypt
from integrations.models import SimklAccount
from integrations.state.adapters.base import (
    AdapterError,
    TerminalAdapterError,
    TransientAdapterError,
)
from integrations.state.device_client import DeviceLoginClient

logger = logging.getLogger(__name__)

BASE_URL = "https://api.simkl.com"
TIMEOUT = 30
SCOPE = "media:read media:write"
WRITE_SCOPE = "media:write"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
DEFAULT_ACCESS_LIFETIME = timedelta(days=7)
REFRESH_MARGIN = timedelta(hours=1)
REFRESH_LOCK_TIMEOUT = 30
REFRESH_WAIT_SECONDS = 10
# SIMKL serializes a user's writes behind a 20 second lock.
WRITE_LOCK_SECONDS = 20
SLOW_DOWN_SECONDS = 5
DEFAULT_RETRY_AFTER = 60
QUOTA_ZONE = ZoneInfo("America/New_York")


class SimklAuthError(TerminalAdapterError):
    """SIMKL rejected the login; the user has to reconnect."""


class DeviceFlowError(AdapterError):
    """The approval cannot continue; the message says why, in plain words."""


def client_id_for(user):
    """Return the SIMKL app Client ID this user (or the instance) has configured."""
    with credentials.current_user_scope(user):
        return credentials.get("simkl", "client_id")


def _client_secret():
    return credentials.get("simkl", "client_secret")


def _headers(client_id, access_token=""):
    headers = {
        "simkl-api-key": client_id,
        "User-Agent": f"Floppy/{settings.VERSION}",
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    return headers


def _send(method, path, *, client_id, access_token="", json=None, data=None):
    """Make one request and return the response, or raise a transient error."""
    params = {
        "client_id": client_id,
        "app-name": "floppy",
        "app-version": settings.VERSION,
    }
    if path == "/sync/history":
        # An individual play must never fill in earlier episodes by itself.
        params["skip_auto_watching"] = "yes"
    try:
        return requests.request(
            method,
            f"{BASE_URL}{path}",
            headers=_headers(client_id, access_token),
            params=params if access_token else None,
            json=json,
            data=data,
            timeout=TIMEOUT,
            allow_redirects=False,
        )
    except requests.RequestException as error:
        message = "SIMKL could not be reached."
        raise TransientAdapterError(message) from error


def read_error(response):
    """Return ``(code, message)`` from SIMKL's error body."""
    try:
        body = response.json()
    except ValueError:
        return "", ""
    if not isinstance(body, dict):
        return "", ""
    return str(body.get("error") or ""), str(
        body.get("message") or body.get("error_description") or "",
    )


def retry_after(response, now=None):
    """Return how many seconds to wait after a 429.

    SIMKL names the wait in ``Retry-After``. Without it, a spent daily quota
    waits for midnight in New York, when the quota resets.
    """
    try:
        return max(int(float(response.headers.get("Retry-After"))), 1)
    except (TypeError, ValueError):
        pass
    now = (now or timezone.now()).astimezone(QUOTA_ZONE)
    if response.headers.get("X-RateLimit-Remaining") == "0":
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return int((midnight + timedelta(days=1) - now).total_seconds())
    return DEFAULT_RETRY_AFTER


def raise_for_status(response):
    """Turn an unsuccessful response into the error the engine understands."""
    status = response.status_code
    if HTTPStatus.OK <= status < HTTPStatus.MULTIPLE_CHOICES:
        return
    code, message = read_error(response)
    detail = message or code or f"HTTP {status}"
    if status == HTTPStatus.TOO_MANY_REQUESTS:
        text = f"SIMKL rate limit reached. {detail}"
        raise TransientAdapterError(text, retry_after=retry_after(response))
    if status == HTTPStatus.BAD_REQUEST and code == "rate_limit":
        # Another write for this user is still running: not the daily quota.
        text = "SIMKL is still busy with another sync."
        raise TransientAdapterError(text, retry_after=WRITE_LOCK_SECONDS)
    if status >= HTTPStatus.INTERNAL_SERVER_ERROR:
        text = f"SIMKL is temporarily unavailable (HTTP {status})."
        raise TransientAdapterError(text)
    if status == HTTPStatus.UNAUTHORIZED:
        text = "SIMKL rejected the login. Reconnect your account."
        raise SimklAuthError(text)
    text = f"SIMKL request failed: {detail}"
    raise TerminalAdapterError(text)


def _json(response):
    try:
        data = response.json()
    except ValueError as error:
        message = "SIMKL returned an invalid response."
        raise TransientAdapterError(message) from error
    if not isinstance(data, (dict, list)):
        message = "SIMKL returned an invalid response."
        raise TransientAdapterError(message)
    return data


# --- device-flow login -------------------------------------------------------


def start_device_flow(client_id):
    """Ask SIMKL for a code the user approves on simkl.com/pin."""
    response = _send(
        "POST",
        "/oauth2/device",
        client_id=client_id,
        data={"client_id": client_id, "scope": SCOPE},
    )
    if response.status_code == HTTPStatus.UNAUTHORIZED:
        message = (
            "SIMKL did not accept this Client ID. Device login needs an app made "
            "with AUTH V2 (apps made before 2026-09-18 use the older login)."
        )
        raise DeviceFlowError(message)
    if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
        message = "SIMKL allows only a few login codes at a time. Try again later."
        raise DeviceFlowError(message)
    raise_for_status(response)
    data = _json(response)
    device_code = data.get("device_code")
    user_code = data.get("user_code")
    url = data.get("verification_uri_complete") or data.get("verification_uri")
    if not (device_code and user_code and url):
        message = "SIMKL returned an incomplete login code."
        raise DeviceFlowError(message)
    return {
        "device_code": str(device_code),
        "user_code": str(user_code),
        "verification_url": str(url),
        "interval": int(data.get("interval") or 5),
        "expires_in": int(data.get("expires_in") or 900),
    }


def poll_device_flow(client_id, device_code):
    """Check once whether the user has approved; returns ``(state, payload)``."""
    response = _send(
        "POST",
        "/oauth2/token",
        client_id=client_id,
        data={
            "grant_type": DEVICE_GRANT,
            "client_id": client_id,
            "device_code": device_code,
        },
    )
    status = response.status_code
    code, _message = read_error(response)
    if status == HTTPStatus.OK:
        tokens = _json(response)
        if not isinstance(tokens, dict) or not tokens.get("access_token"):
            return "failed", "SIMKL returned no login tokens."
        granted = str(tokens.get("scope") or "")
        if granted and WRITE_SCOPE not in granted.split():
            return "failed", "SIMKL only allowed reading, so Floppy cannot send plays."
        return "approved", tokens
    if status == HTTPStatus.BAD_REQUEST:
        if code == "authorization_pending":
            return "pending", None
        if code == "slow_down":
            return "pending", {"interval": SLOW_DOWN_SECONDS}
        if code == "expired_token":
            return "failed", "The code expired. Start again."
        return "failed", "SIMKL rejected the login request."
    if status == HTTPStatus.UNAUTHORIZED:
        return "failed", "SIMKL did not accept this Client ID."
    if status == HTTPStatus.TOO_MANY_REQUESTS:
        return "pending", {"interval": retry_after(response)}
    if status >= HTTPStatus.INTERNAL_SERVER_ERROR:
        return "pending", None
    return "failed", f"SIMKL could not complete the login (HTTP {status})."


def token_fields(tokens, now=None):
    """Return the account columns for a token response, encrypted."""
    now = now or timezone.now()
    try:
        lifetime = timedelta(seconds=int(tokens.get("expires_in")))
    except (TypeError, ValueError):
        lifetime = DEFAULT_ACCESS_LIFETIME
    fields = {
        "access_token": encrypt(tokens["access_token"]),
        "access_expires_at": now + lifetime,
        "scope": str(tokens.get("scope") or SCOPE),
    }
    if tokens.get("refresh_token"):
        fields["refresh_token"] = encrypt(tokens["refresh_token"])
    return fields


def logout(client_id, access_token, refresh_token):
    """Ask SIMKL to revoke the login. Either token revokes the whole grant."""
    response = _send(
        "POST",
        "/oauth2/revoke",
        client_id=client_id,
        data={"client_id": client_id, "token": refresh_token or access_token},
    )
    raise_for_status(response)


# --- authenticated calls -----------------------------------------------------


class SimklClient(DeviceLoginClient):
    """Authenticated calls for one account, refreshing its login when needed."""

    LABEL = "SIMKL"
    LOCK_PREFIX = "simkl"
    auth_error = SimklAuthError
    # The refresh token does not rotate; the access token is what changes.
    CHANGES_ON_REFRESH = "access_token"
    REFRESH_MARGIN = REFRESH_MARGIN
    REFRESH_LOCK_TIMEOUT = REFRESH_LOCK_TIMEOUT

    @property
    def refresh_wait_seconds(self):
        """Read the module value so tests can shorten it."""
        return REFRESH_WAIT_SECONDS

    def _call(self, method, path, access_token, *, json=None, **_):
        return _send(
            method,
            path,
            client_id=self.account.client_id,
            access_token=access_token,
            json=json,
        )

    def _read(self, response, **_):
        raise_for_status(response)
        if not response.content:
            return {}
        return _json(response)

    def _exchange_refresh_token(self):
        _access, refresh = self._tokens()
        if not refresh:
            message = "SIMKL login cannot be read. Reconnect your account."
            raise SimklAuthError(message)
        form = {
            "grant_type": "refresh_token",
            "client_id": self.account.client_id,
            "refresh_token": refresh,
        }
        secret = _client_secret()
        if secret:
            # Apps registered as "Server apps & services" must also send this.
            form["client_secret"] = secret
        response = _send(
            "POST",
            "/oauth2/token",
            client_id=self.account.client_id,
            data=form,
        )
        if response.status_code in {
            HTTPStatus.BAD_REQUEST,
            HTTPStatus.UNAUTHORIZED,
            HTTPStatus.FORBIDDEN,
        }:
            message = "SIMKL no longer accepts this login. Reconnect your account."
            raise SimklAuthError(message)
        raise_for_status(response)
        tokens = _json(response)
        if not isinstance(tokens, dict) or not tokens.get("access_token"):
            message = "SIMKL returned no login tokens."
            raise TransientAdapterError(message)
        fields = token_fields(tokens)
        # Keep the granted scope as it was: a refresh never widens it.
        fields.pop("scope", None)
        # Compare-and-set on the old ciphertext, so a refresh that lost a race
        # never overwrites the winner's newer token.
        SimklAccount.objects.filter(
            pk=self.account.pk,
            access_token=self.account.access_token,
        ).update(**fields)
        self.account.refresh_from_db()
