"""Emby's half of watched-state synchronization — reads only, for now.

Emby's API descends from the same codebase as Jellyfin's, so the shapes used
here (``/Users/{uid}/Items`` with ``ProviderIds``, and ``UserData.Played``) are
the ones its documentation describes. Reads are safe to ship on that basis: the
worst a wrong read can do is produce an observation the apply algorithm then
weighs against a baseline.

Writes are not. ``PlaystateService`` documents played/unplayed operations, but
nothing in this repository has exercised them against a real server, and a
write is the one thing that cannot be taken back. So ``CAPABILITIES`` declares
read only, and the engine — which intersects declared capabilities with what
the user approved — will not call the write path. Declaring it before it has
been verified is exactly the "completed two-way sync" claim this program is
supposed to avoid making.
"""

import logging
from http import HTTPStatus

import requests

from app.models import MediaTypes, Sources
from integrations.models import CAPABILITY_WATCHED_READ
from integrations.state.adapters.base import (
    RemoteState,
    TerminalAdapterError,
    TransientAdapterError,
)

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15

_PROVIDER_BY_SOURCE = {
    Sources.TMDB.value: "Tmdb",
    Sources.TVDB.value: "Tvdb",
    Sources.IMDB.value: "Imdb",
}

_SUPPORTED_MEDIA_TYPES = frozenset(
    {MediaTypes.MOVIE.value, MediaTypes.EPISODE.value},
)


class EmbyStateAdapter:
    """Read Emby watched state for one binding."""

    CAPABILITIES = frozenset({CAPABILITY_WATCHED_READ})

    def __init__(self, account):
        """Bind the adapter to one Emby account."""
        self.account = account

    def _request(self, path, params=None):
        """Issue one authenticated Emby request."""
        from integrations.imports.helpers import decrypt_or_raise

        url = f"{self.account.base_url.rstrip('/')}{path}"
        try:
            response = requests.get(
                url,
                headers={"X-Emby-Token": decrypt_or_raise(self.account.api_key)},
                params=params or {},
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as error:
            msg = f"Could not reach Emby: {error}"
            raise TransientAdapterError(msg) from error

        if response.status_code == HTTPStatus.UNAUTHORIZED:
            msg = "Emby API key is invalid or unauthorized"
            raise TerminalAdapterError(msg)
        if response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
            msg = f"Emby returned {response.status_code}"
            raise TransientAdapterError(msg)
        if response.status_code >= HTTPStatus.BAD_REQUEST:
            msg = f"Emby rejected the request: {response.status_code}"
            raise TerminalAdapterError(msg)

        return response.json()

    def resolve_external_id(self, item):
        """Return the Emby item id for a Floppy item, or None."""
        if item.media_type not in _SUPPORTED_MEDIA_TYPES:
            return None

        provider = _PROVIDER_BY_SOURCE.get(item.source)
        if not provider or not self.account.emby_user_id:
            return None

        payload = self._request(
            f"/Users/{self.account.emby_user_id}/Items",
            params={
                "Recursive": "true",
                "IncludeItemTypes": "Movie,Episode",
                "Fields": "ProviderIds",
                "AnyProviderIdEquals": f"{provider.lower()}.{item.media_id}",
                "Limit": 2,
            },
        )

        items = payload.get("Items") or []
        # More than one match is ambiguous, and an ambiguous match must never
        # become a write target.
        if len(items) != 1:
            return None

        found = items[0]
        if item.media_type == MediaTypes.EPISODE.value:
            season = found.get("ParentIndexNumber")
            episode = found.get("IndexNumber")
            if season != item.season_number or episode != item.episode_number:
                return None

        return found.get("Id")

    def read_state(self, external_id):
        """Return Emby's current state for one item, or None if unknown."""
        payload = self._request(
            f"/Users/{self.account.emby_user_id}/Items/{external_id}",
        )
        user_data = payload.get("UserData")
        if not user_data:
            return None

        return RemoteState(
            watched=bool(user_data.get("Played")),
            play_count=int(user_data.get("PlayCount") or 0),
            watched_at=user_data.get("LastPlayedDate"),
        )

    def write_watched(self, external_id, *, watched):
        """Refuse to write until the contract has been verified."""
        msg = (
            "Emby writes are not enabled: the played/unplayed contract has not "
            "been verified against a real server."
        )
        raise TerminalAdapterError(msg)


def build_adapter(binding):
    """Return the adapter for an Emby binding, or None when unusable."""
    from integrations.models import EmbyAccount

    account = EmbyAccount.objects.filter(user=binding.user).first()
    if account is None or not account.is_connected:
        return None
    return EmbyStateAdapter(account)
