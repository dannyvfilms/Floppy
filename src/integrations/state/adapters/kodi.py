"""Kodi's half of watched-state synchronization — reads only, for now.

Kodi is the odd one out: it identifies media by *local library id*, not by any
provider id, so there is no way to address an item without first asking its
library. That is why a connection exists at all — the webhook carries enough to
record a play but not enough to point at anything later.

Identity therefore costs a query: ``VideoLibrary.GetMovies`` /
``GetEpisodes`` filtered on ``uniqueid``. Writes (``SetMovieDetails`` with
``playcount``) are documented but unverified here, and Kodi's write is an
*assignment of a count* rather than a flag, which makes getting it wrong more
consequential than elsewhere. Read only until that is exercised for real.
"""

import logging

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

# Kodi's uniqueid keys for the sources Floppy tracks.
_UNIQUE_ID_BY_SOURCE = {
    Sources.TMDB.value: "tmdb",
    Sources.TVDB.value: "tvdb",
    Sources.IMDB.value: "imdb",
}


class KodiStateAdapter:
    """Read Kodi watched state for one binding."""

    CAPABILITIES = frozenset({CAPABILITY_WATCHED_READ})

    def __init__(self, account):
        """Bind the adapter to one Kodi account."""
        self.account = account

    def _call(self, method, params=None):
        """Issue one Kodi JSON-RPC call and return its result."""
        from integrations.imports.helpers import decrypt

        auth = None
        if self.account.username:
            auth = (self.account.username, decrypt(self.account.password) or "")

        try:
            response = requests.post(
                self.account.base_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": method,
                    "params": params or {},
                },
                auth=auth,
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as error:
            msg = f"Could not reach Kodi: {error}"
            raise TransientAdapterError(msg) from error

        if response.status_code == requests.codes.unauthorized:
            msg = "Kodi credentials were rejected"
            raise TerminalAdapterError(msg)
        if not response.ok:
            msg = f"Kodi returned {response.status_code}"
            raise TransientAdapterError(msg)

        payload = response.json()
        if "error" in payload:
            # A JSON-RPC error is the server understanding us and refusing;
            # retrying the same call will get the same answer.
            msg = f"Kodi rejected {method}: {payload['error']}"
            raise TerminalAdapterError(msg)

        return payload.get("result") or {}

    def _matches_unique_id(self, entry, key, value):
        """Return whether a Kodi entry carries the expected provider id."""
        unique_ids = entry.get("uniqueid") or {}
        return str(unique_ids.get(key, "")) == str(value)

    def resolve_external_id(self, item):
        """Return the Kodi library id for a Floppy item, or None.

        The id is encoded as ``movie:123`` / ``episode:456`` because Kodi's
        library ids are only unique within a media type.
        """
        key = _UNIQUE_ID_BY_SOURCE.get(item.source)
        if not key:
            return None

        if item.media_type == MediaTypes.MOVIE.value:
            result = self._call(
                "VideoLibrary.GetMovies",
                {"properties": ["uniqueid", "playcount"]},
            )
            matches = [
                entry
                for entry in result.get("movies") or []
                if self._matches_unique_id(entry, key, item.media_id)
            ]
            if len(matches) != 1:
                return None
            return f"movie:{matches[0]['movieid']}"

        if item.media_type == MediaTypes.EPISODE.value:
            result = self._call(
                "VideoLibrary.GetEpisodes",
                {"properties": ["uniqueid", "playcount", "season", "episode"]},
            )
            matches = [
                entry
                for entry in result.get("episodes") or []
                if entry.get("season") == item.season_number
                and entry.get("episode") == item.episode_number
            ]
            if len(matches) != 1:
                return None
            return f"episode:{matches[0]['episodeid']}"

        return None

    def read_state(self, external_id):
        """Return Kodi's current state for one item, or None if unknown."""
        kind, _, raw_id = str(external_id).partition(":")
        if not raw_id:
            return None

        if kind == "movie":
            result = self._call(
                "VideoLibrary.GetMovieDetails",
                {"movieid": int(raw_id), "properties": ["playcount", "lastplayed"]},
            )
            details = result.get("moviedetails")
        elif kind == "episode":
            result = self._call(
                "VideoLibrary.GetEpisodeDetails",
                {"episodeid": int(raw_id), "properties": ["playcount", "lastplayed"]},
            )
            details = result.get("episodedetails")
        else:
            return None

        if not details:
            return None

        play_count = int(details.get("playcount") or 0)
        return RemoteState(
            watched=play_count > 0,
            play_count=play_count,
            watched_at=details.get("lastplayed") or None,
        )

    def write_watched(self, external_id, *, watched):
        """Refuse to write until the contract has been verified."""
        msg = (
            "Kodi writes are not enabled: its playcount assignment has not been "
            "verified against a real library."
        )
        raise TerminalAdapterError(msg)


def build_adapter(binding):
    """Return the adapter for a Kodi binding, or None when unusable."""
    from integrations.models import KodiAccount

    account = KodiAccount.objects.filter(user=binding.user).first()
    if account is None or not account.is_connected:
        return None
    return KodiStateAdapter(account)
