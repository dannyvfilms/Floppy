"""Uncached personal TMDb calls; metadata responses never contain account data."""

from http import HTTPStatus

import requests

from app.providers import credentials
from integrations.state.adapters.base import TerminalAdapterError, TransientAdapterError

BASE_URL = "https://api.themoviedb.org/3"
TIMEOUT = 20


class TMDbAuthError(TerminalAdapterError):
    """TMDb explicitly rejected the supplied credentials."""


class TMDbClient:
    """Use the user's resolved application key and private account session."""

    def __init__(self, user, session_id=""):
        """Bind a client to one user's credential resolution scope."""
        self.user = user
        self.session_id = session_id

    def request(self, method, path, **kwargs):
        """Call a fixed TMDb endpoint without exposing credentials in errors."""
        with credentials.current_user_scope(self.user):
            api_key = credentials.get("tmdb", "api_key")
        if not api_key:
            message = "Configure a TMDb API key in Metadata settings."
            raise TerminalAdapterError(message)
        params = {"api_key": api_key}
        if self.session_id:
            params["session_id"] = self.session_id
        try:
            response = requests.request(
                method,
                f"{BASE_URL}/{path}",
                params=params,
                timeout=TIMEOUT,
                allow_redirects=False,
                **kwargs,
            )
        except requests.RequestException as error:
            message = "TMDb could not be reached."
            raise TransientAdapterError(message) from error
        if response.status_code in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
            message = "TMDb rejected the credentials. Reconnect your account."
            raise TMDbAuthError(message)
        if (
            response.status_code == HTTPStatus.TOO_MANY_REQUESTS
            or response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR
        ):
            message = f"TMDb temporarily unavailable (HTTP {response.status_code})."
            raise TransientAdapterError(message)
        if not HTTPStatus.OK <= response.status_code < HTTPStatus.MULTIPLE_CHOICES:
            message = f"TMDb request failed (HTTP {response.status_code})."
            raise TerminalAdapterError(message)
        try:
            data = response.json()
        except ValueError as error:
            message = "TMDb returned an invalid response."
            raise TransientAdapterError(message) from error
        if not isinstance(data, dict):
            message = "TMDb returned an invalid response."
            raise TransientAdapterError(message)
        if data.get("success") is False:
            message = "TMDb did not accept the request."
            raise TerminalAdapterError(message)
        return data
