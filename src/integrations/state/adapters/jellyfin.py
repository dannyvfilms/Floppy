"""Jellyfin's half of watched-state synchronization.

Jellyfin is the reference adapter because its write is a *set* rather than an
increment (``POST``/``DELETE /Users/{uid}/PlayedItems/{id}``), so re-issuing one
cannot manufacture a second play. That is what makes retry-by-read-first safe
here, and it is why Jellyfin is the only provider shipping with an enabled
write direction.
"""

import logging

from app.models import MediaTypes, Sources
from integrations.jellyfin_client import (
    JellyfinAuthError,
    JellyfinClient,
    JellyfinClientError,
)
from integrations.models import (
    CAPABILITY_WATCHED_PUSH_PLAYED,
    CAPABILITY_WATCHED_PUSH_UNPLAYED,
    CAPABILITY_WATCHED_READ,
    CAPABILITY_WATCHED_WRITE_PLAYED,
    CAPABILITY_WATCHED_WRITE_UNPLAYED,
)
from integrations.state.adapters.base import (
    RemoteState,
    TerminalAdapterError,
    TransientAdapterError,
)

logger = logging.getLogger(__name__)

# Floppy source -> Jellyfin provider id key.
_PROVIDER_BY_SOURCE = {
    Sources.TMDB.value: "Tmdb",
    Sources.TVDB.value: "Tvdb",
    Sources.IMDB.value: "Imdb",
}

_SUPPORTED_MEDIA_TYPES = frozenset(
    {MediaTypes.MOVIE.value, MediaTypes.EPISODE.value},
)


class JellyfinStateAdapter:
    """Read and write Jellyfin watched state for one binding."""

    CAPABILITIES = frozenset(
        {
            CAPABILITY_WATCHED_READ,
            CAPABILITY_WATCHED_WRITE_PLAYED,
            CAPABILITY_WATCHED_WRITE_UNPLAYED,
            CAPABILITY_WATCHED_PUSH_PLAYED,
            CAPABILITY_WATCHED_PUSH_UNPLAYED,
        },
    )

    def __init__(self, account):
        """Bind the adapter to one Jellyfin account."""
        self.account = account
        self._client = None

    @property
    def client(self):
        """Return a lazily built Jellyfin client."""
        if self._client is None:
            from integrations.imports.helpers import decrypt_or_raise

            self._client = JellyfinClient(
                base_url=self.account.base_url,
                api_key=decrypt_or_raise(self.account.api_key),
                user_id=self.account.jellyfin_user_id,
            )
        return self._client

    def resolve_external_id(self, item):
        """Return the Jellyfin item id for a Floppy item, or None."""
        if item.media_type not in _SUPPORTED_MEDIA_TYPES:
            return None

        provider = _PROVIDER_BY_SOURCE.get(item.source)
        if not provider:
            return None

        try:
            found = self.client.find_item_by_provider_id(provider, item.media_id)
        except JellyfinAuthError as error:
            raise TerminalAdapterError(str(error)) from error
        except JellyfinClientError as error:
            raise TransientAdapterError(str(error)) from error

        if found is None:
            return None

        # A series-level provider id matches every episode of the show, so an
        # episode must also agree on its numbers before we write to it.
        if item.media_type == MediaTypes.EPISODE.value:
            season = found.get("ParentIndexNumber")
            episode = found.get("IndexNumber")
            if season != item.season_number or episode != item.episode_number:
                return None

        return found.get("Id")

    def read_state(self, external_id):
        """Return Jellyfin's current state for one item, or None if unknown."""
        try:
            user_data = self.client.get_item_user_data(external_id)
        except JellyfinAuthError as error:
            raise TerminalAdapterError(str(error)) from error
        except JellyfinClientError as error:
            raise TransientAdapterError(str(error)) from error

        if not user_data:
            return None

        return RemoteState(
            watched=bool(user_data.get("Played")),
            play_count=int(user_data.get("PlayCount") or 0),
            watched_at=user_data.get("LastPlayedDate"),
        )

    def write_watched(self, external_id, *, watched):
        """Set Jellyfin's played flag for one item."""
        try:
            if watched:
                self.client.mark_played(external_id)
            else:
                self.client.mark_unplayed(external_id)
        except JellyfinAuthError as error:
            raise TerminalAdapterError(str(error)) from error
        except JellyfinClientError as error:
            raise TransientAdapterError(str(error)) from error


def build_adapter(binding):
    """Return the adapter for a Jellyfin binding, or None when unusable."""
    from integrations.models import JellyfinAccount

    account = JellyfinAccount.objects.filter(user=binding.user).first()
    if account is None or not account.base_url or not account.api_key:
        return None
    return JellyfinStateAdapter(account)
