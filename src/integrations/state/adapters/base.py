"""What the delivery engine needs from a provider, and nothing more.

A Protocol rather than a base class, deliberately. ``webhooks/base.py`` grew
into an 84KB template-method mixin that owns TMDB resolution for every
provider, and the result is that changing one provider's behaviour means
reading all of them. The engine here owns ordering, durability and
authorization; each adapter owns its own transport, its own identifiers and its
own idea of what "finished" means.

An adapter that cannot implement a method must not fake it. Returning a
plausible guess from ``read_state`` is worse than declaring the capability
unavailable, because the engine treats a read as evidence.
"""

from typing import Protocol, runtime_checkable


class AdapterError(Exception):
    """A provider call failed in a way the engine should record."""


class TransientAdapterError(AdapterError):
    """The call may succeed later: a timeout, a 5xx, a rate limit."""


class TerminalAdapterError(AdapterError):
    """The call will not succeed as issued: bad credentials, unknown item."""


class RemoteState:
    """What a provider reports about one item."""

    __slots__ = ("play_count", "watched", "watched_at")

    def __init__(self, *, watched, play_count=0, watched_at=None):
        """Store the remote values."""
        self.watched = watched
        self.play_count = play_count
        self.watched_at = watched_at


@runtime_checkable
class StateAdapter(Protocol):
    """One provider's half of watched-state synchronization."""

    #: Capabilities this adapter has actually been shown to hold. The engine
    #: intersects these with what the user approved, so an adapter cannot grant
    #: itself a permission and a user cannot grant one the adapter lacks.
    CAPABILITIES: frozenset[str]

    def resolve_external_id(self, item) -> str | None:
        """Return the provider's id for a Floppy item, or None.

        Must be deterministic. An ambiguous match returns None rather than a
        best guess: a write to the wrong item is unrecoverable, and the engine
        records the ambiguity for a person instead.
        """
        ...

    def read_state(self, external_id: str) -> RemoteState | None:
        """Return the provider's current state, or None when it has no opinion.

        None means "unknown", never "unwatched". A missing item, a partial scan
        and an authorization failure all have to reach the engine as unknown,
        because absence of evidence is the one thing that must never be applied
        as an unwatch.
        """
        ...

    def write_watched(self, external_id: str, *, watched: bool) -> None:
        """Set the provider's watched flag for one item.

        Should be idempotent: the engine retries by reading first, but an
        adapter whose write is a set rather than an increment makes that safe
        even when the read is unavailable.
        """
        ...
