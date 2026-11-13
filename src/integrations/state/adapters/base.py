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

from decimal import Decimal
from typing import Protocol, runtime_checkable


class AdapterError(Exception):
    """A provider call failed in a way the engine should record."""


class TransientAdapterError(AdapterError):
    """The call may succeed later: a timeout, a 5xx, a rate limit.

    ``retry_after`` is the number of seconds the provider asked us to wait, when
    it said. The engine never retries sooner than this.
    """

    def __init__(self, message="", *, retry_after=None):
        """Keep the provider's requested wait alongside the message."""
        super().__init__(message)
        self.retry_after = retry_after


class TerminalAdapterError(AdapterError):
    """The call will not succeed as issued: bad credentials, unknown item."""


class RemoteRating:
    """Known remote rating; a null score means unrated, not unknown."""

    def __init__(self, score: Decimal | None):
        """Store the provider's score."""
        self.score = score


class RatingAdapter(Protocol):
    """Optional rating capability; watched-only adapters need not implement it."""

    CAPABILITIES: frozenset[str]

    def resolve_external_id(self, item) -> str | None:
        """Resolve only a confirmed provider identity."""
        ...

    def normalize_rating(self, score: Decimal | None) -> Decimal | None:
        """Convert a Floppy score into the provider's supported scale."""
        ...

    def read_rating(self, external_id: str) -> RemoteRating | None:
        """Return a known rating, or None when remote state is unknown."""
        ...

    def write_rating(self, external_id: str, *, score: Decimal | None) -> None:
        """Set a score, or remove it when score is None."""
        ...


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


#: Outcomes a batch adapter reports for one item of a batch.
BATCH_DELIVERED = "delivered"
BATCH_SKIPPED = "skipped"  # the provider cannot take this item; do not retry
BATCH_FAILED = "failed"  # the provider rejected this item; do not retry
BATCH_RETRY = "retry"  # the provider could not take it now; try again later


class BatchItem:
    """One queued delivery, resolved and ready to be sent as part of a batch."""

    __slots__ = ("delivery_id", "external_id", "item", "operation", "payload", "rating")

    def __init__(self, *, delivery_id, operation, item, external_id, payload, rating):
        """Store what the adapter needs to write this item."""
        self.delivery_id = delivery_id
        self.operation = operation
        self.item = item
        self.external_id = external_id
        self.payload = payload
        self.rating = rating


class BatchResult:
    """What the provider did with one item of a batch."""

    __slots__ = ("error", "outcome", "receipt")

    def __init__(self, outcome, *, receipt="", error=""):
        """Store the outcome, and the provider's id for what it created."""
        self.outcome = outcome
        self.receipt = receipt
        self.error = error


class BatchAdapter(Protocol):
    """A provider that takes many writes in one request.

    Declaring ``BATCH_SIZE`` is what makes the engine hold deliveries for this
    provider and send them together, on the schedule the user picked. The batch
    path carries every operation the adapter lists in ``CAPABILITIES``.
    """

    BATCH_SIZE: int

    #: Set to False when the provider would show imported history as fresh
    #: activity. The engine then never queues imported changes for it.
    ACCEPTS_IMPORTED_CHANGES: bool

    def write_batch(
        self,
        items: list[BatchItem],
        *,
        idempotency_key: str,
    ) -> list[BatchResult]:
        """Send items in one request and return one result per item, in order.

        Raise ``TransientAdapterError`` when nothing was applied and the whole
        request should be retried, ``TerminalAdapterError`` when it never will
        be. The key is the same whenever the same set is retried.
        """
        ...
