"""Decide what one provider observation means for canonical state.

The classification below is ordered, and the order is the design. Each rule
exists because a specific real failure has to be impossible:

1. **Replay** — the same provider event delivered twice. A retry is not a
   rewatch.
2. **Convergent** — the provider already agrees. Agreement is not an event.
   This is the fail-safe: if every other rule below were wrong, identical
   states would still produce no write.
3. **Echo** — the provider is telling us what we just told it. Correlated
   against a durable delivery receipt and a fresh read-back, never a cache
   timeout, because a slow echo and a genuine second play look identical to a
   clock.
4. **Stale remote** — the provider has not moved since we last agreed, so
   the only side that changed is us. We owe them a delivery, not a rollback,
   and it is not a disagreement.
5. **Fast-forward** — the last state we demonstrably agreed on is still our
   current state, so nothing local has moved and the remote change applies.
6. **Diverged** — both sides moved off the same ancestor. Resolved by the
   non-destructive rules in ``_resolve_divergence``, never by last-write-wins.

The merge base is ``ProviderStateObservation``: without the local revision and
digest captured when the provider last spoke, "they moved" and "we moved" are
indistinguishable and every disagreement collapses into whoever wrote last.
"""

import logging
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from app.models import WatchStateOrigin, calculate_state_digest
from app.services.watch_state import (
    effective_state,
    record_state_change,
)
from integrations.models import (
    CAPABILITY_WATCHED_WRITE_UNPLAYED,
    ProviderStateObservation,
    StateConflict,
    StateConflictReason,
    StateConflictStatus,
    SyncDirection,
)

logger = logging.getLogger(__name__)


class Outcome:
    """Named results, so callers branch on meaning rather than on booleans."""

    REPLAY = "replay"
    CONVERGENT = "convergent"
    ECHO = "echo"
    APPLIED = "applied"
    STALE_REMOTE = "stale_remote"
    CONFLICT = "conflict"
    SKIPPED = "skipped"


class ApplyResult:
    """What ``apply_observation`` decided and what it changed."""

    __slots__ = ("change", "conflict", "outcome", "state")

    def __init__(self, outcome, *, state=None, change=None, conflict=None):
        """Store the decision."""
        self.outcome = outcome
        self.state = state
        self.change = change
        self.conflict = conflict

    def __repr__(self):
        """Readable representation."""
        return f"ApplyResult({self.outcome})"


class ObservedState:
    """What a provider says about one item."""

    __slots__ = ("external_id", "play_count", "watched", "watched_at")

    def __init__(self, *, watched, play_count=0, watched_at=None, external_id=""):
        """Store the observation."""
        self.watched = watched
        self.play_count = play_count
        self.watched_at = watched_at
        self.external_id = external_id

    @property
    def digest(self):
        """Return the digest identifying this exact remote state."""
        return calculate_state_digest(self.watched, self.play_count, self.watched_at)


def _open_conflict(binding, item, reason, *, local, remote, base):
    """Record a disagreement, or count another occurrence of a known one."""
    conflict, created = StateConflict.objects.get_or_create(
        user=binding.user,
        item=item,
        binding=binding,
        reason=reason,
        status=StateConflictStatus.OPEN.value,
        defaults={
            "local_snapshot": local,
            "remote_snapshot": remote,
            "base_snapshot": base,
        },
    )
    if not created:
        conflict.occurrence_count += 1
        conflict.local_snapshot = local
        conflict.remote_snapshot = remote
        conflict.save(
            update_fields=[
                "occurrence_count",
                "local_snapshot",
                "remote_snapshot",
                "updated_at",
            ],
        )
    return conflict


def _snapshot(watched, play_count, watched_at):
    """Return a serializable description of one side's state."""
    return {
        "watched": bool(watched),
        "play_count": int(play_count or 0),
        "watched_at": watched_at.isoformat() if watched_at else None,
    }


def _record_observation(binding, item, observed, state, source):
    """Store the new merge base for this binding and item."""
    ProviderStateObservation.objects.update_or_create(
        binding=binding,
        item=item,
        defaults={
            "user": binding.user,
            "external_id": observed.external_id,
            "watched": observed.watched,
            "play_count": observed.play_count,
            "watched_at": observed.watched_at,
            "provider_digest": observed.digest,
            "local_revision_at_observation": state.revision if state else 0,
            "local_digest_at_observation": state.state_digest if state else "",
            "source": source,
            "observed_at": timezone.now(),
        },
    )


def _is_echo(binding, item, observed, state):
    """Return whether this observation is our own write coming back.

    Correlated against a durable delivery whose read-back digest matches, and
    against the revision that delivery targeted. Kept separate from the
    convergent rule so a play count we caused is never mistaken for remote
    evidence of a new play.
    """
    try:
        from integrations.models import OutboundStateDelivery
    except ImportError:  # pragma: no cover - delivery lands in a later patch
        return False

    return OutboundStateDelivery.objects.filter(
        binding=binding,
        item=item,
        status="delivered",
        readback_digest=observed.digest,
        target_revision=state.revision if state else 0,
    ).exists()


def _resolve_divergence(binding, item, observed, state, base):
    """Apply the non-destructive divergence rules.

    Returns the values to write, or None when the disagreement has to be held
    for a person. Deliberately biased toward keeping information: a wrong
    "watched" costs a checkmark, a wrong "unwatched" costs history.
    """
    # Rule 1: a watch on either side wins. Union, not last-write.
    if observed.watched and not state.watched:
        watched_at = observed.watched_at or state.last_watched_at
        return True, max(state.play_count, observed.play_count or 1), watched_at

    # Rule 3: a remote unwatch while diverged is never applied automatically.
    if state.watched and not observed.watched:
        return None

    # Rule 2: play counts never decrease. A remote decrement is reported by the
    # caller's observation record, never written.
    if observed.play_count > state.play_count:
        watched_at = observed.watched_at or state.last_watched_at
        # Rule 1 again for timestamps: prefer the earlier genuine time, and
        # never replace a full timestamp with a coarser or absent one.
        return state.watched or observed.watched, observed.play_count, watched_at

    return None


@transaction.atomic
def apply_observation(
    binding,
    item,
    observed,
    *,
    origin_event_id=None,
    correlation_id=None,
    source="",
    observed_at=None,
):
    """Apply one provider observation to canonical state.

    Never writes when the binding is not operational, and never writes an
    unwatch the binding was not granted. A missing item, an incomplete scan or
    an authorization failure must reach this function as *no observation at
    all* rather than as ``watched=False``: absence is not evidence.
    """
    if not binding.is_operational():
        return ApplyResult(Outcome.SKIPPED)

    state = effective_state(binding.user, item)
    base = ProviderStateObservation.objects.filter(
        binding=binding,
        item=item,
    ).first()

    # 1. Replay: this exact provider event was already applied.
    if origin_event_id:
        from app.models import WatchStateChange

        replayed = WatchStateChange.objects.filter(
            user=binding.user,
            origin_key=binding.origin_key,
            origin_event_id=origin_event_id,
        ).first()
        if replayed is not None:
            return ApplyResult(Outcome.REPLAY, state=state, change=replayed)

    # A first observation for an item we have never held state for establishes
    # a baseline. It is not an instruction, and in particular an unwatched
    # first observation is not an instruction to unwatch.
    if state is None:
        if not observed.watched:
            _record_observation(binding, item, observed, None, source)
            return ApplyResult(Outcome.CONVERGENT)
        result = record_state_change(
            binding.user,
            item,
            watched=True,
            play_count=observed.play_count or 1,
            watched_at=observed.watched_at,
            origin_kind=WatchStateOrigin.PROVIDER_PULL.value,
            origin_key=binding.origin_key,
            origin_event_id=origin_event_id,
            origin_observed_at=observed_at,
            correlation_id=correlation_id or uuid4(),
        )
        _record_observation(binding, item, observed, result.state, source)
        return ApplyResult(
            Outcome.APPLIED,
            state=result.state,
            change=result.change,
        )

    # 2. Convergent: they already agree with us.
    if observed.digest == state.state_digest:
        _record_observation(binding, item, observed, state, source)
        return ApplyResult(Outcome.CONVERGENT, state=state)

    # 3. Echo: this is our own write coming back.
    if _is_echo(binding, item, observed, state):
        _record_observation(binding, item, observed, state, source)
        return ApplyResult(Outcome.ECHO, state=state)

    # An item held for a person is frozen for this binding until they settle it.
    if state.conflicted:
        _record_observation(binding, item, observed, state, source)
        return ApplyResult(Outcome.SKIPPED, state=state)

    # 5. Stale remote: the provider has not moved since we last agreed, so the
    # only thing that changed is us. Checked before divergence because a remote
    # that stood still cannot be half of a disagreement — we owe them a
    # delivery, not a rollback and not a conflict.
    if base is not None and observed.digest == base.provider_digest:
        _record_observation(binding, item, observed, state, source)
        return ApplyResult(Outcome.STALE_REMOTE, state=state)

    fast_forward = (
        base is not None and base.local_digest_at_observation == state.state_digest
    ) or (base is None and state.revision == 0)

    if fast_forward:
        # 4. Fast-forward: nothing local moved, so the remote change applies.
        if not observed.watched and not binding.allows(
            SyncDirection.INBOUND.value,
            CAPABILITY_WATCHED_WRITE_UNPLAYED,
        ):
            _record_observation(binding, item, observed, state, source)
            return ApplyResult(Outcome.SKIPPED, state=state)

        result = record_state_change(
            binding.user,
            item,
            watched=observed.watched,
            play_count=observed.play_count,
            watched_at=observed.watched_at,
            origin_kind=WatchStateOrigin.PROVIDER_PULL.value,
            origin_key=binding.origin_key,
            origin_event_id=origin_event_id,
            origin_observed_at=observed_at,
            correlation_id=correlation_id or uuid4(),
        )
        _record_observation(binding, item, observed, result.state, source)
        return ApplyResult(
            Outcome.APPLIED if result.applied else Outcome.CONVERGENT,
            state=result.state,
            change=result.change,
        )

    # 6. Diverged: both sides moved off the same ancestor.
    resolution = _resolve_divergence(binding, item, observed, state, base)
    local_snapshot = _snapshot(state.watched, state.play_count, state.last_watched_at)
    remote_snapshot = _snapshot(
        observed.watched,
        observed.play_count,
        observed.watched_at,
    )
    base_snapshot = (
        _snapshot(base.watched, base.play_count, base.watched_at) if base else {}
    )

    if resolution is None:
        reason = (
            StateConflictReason.DIVERGENT_WATCHED.value
            if state.watched != observed.watched
            else StateConflictReason.DIGEST_MISMATCH.value
        )
        conflict = _open_conflict(
            binding,
            item,
            reason,
            local=local_snapshot,
            remote=remote_snapshot,
            base=base_snapshot,
        )
        state.conflicted = True
        state.save(update_fields=["conflicted", "updated_at"])
        _record_observation(binding, item, observed, state, source)
        return ApplyResult(Outcome.CONFLICT, state=state, conflict=conflict)

    watched, play_count, watched_at = resolution
    result = record_state_change(
        binding.user,
        item,
        watched=watched,
        play_count=play_count,
        watched_at=watched_at,
        origin_kind=WatchStateOrigin.RECONCILE.value,
        origin_key=binding.origin_key,
        origin_event_id=origin_event_id,
        origin_observed_at=observed_at,
        correlation_id=correlation_id or uuid4(),
    )
    _record_observation(binding, item, observed, result.state, source)
    return ApplyResult(
        Outcome.APPLIED if result.applied else Outcome.CONVERGENT,
        state=result.state,
        change=result.change,
    )


@transaction.atomic
def resolve_conflict(conflict, *, watched, play_count=None, watched_at=None):
    """Settle a held disagreement with the state a person chose.

    Creates a new revision rather than reinstating either side's old one, so
    the resolution is itself a decision that propagates through whatever
    directions are enabled.
    """
    result = record_state_change(
        conflict.user,
        conflict.item,
        watched=watched,
        play_count=play_count,
        watched_at=watched_at,
        origin_kind=WatchStateOrigin.LOCAL_UI.value,
        origin_key="conflict-resolution",
    )

    conflict.status = StateConflictStatus.RESOLVED.value
    conflict.resolved_at = timezone.now()
    conflict.save(update_fields=["status", "resolved_at", "updated_at"])

    state = result.state
    still_open = StateConflict.objects.filter(
        user=conflict.user,
        item=conflict.item,
        status=StateConflictStatus.OPEN.value,
    ).exists()
    if state is not None and not still_open and state.conflicted:
        state.conflicted = False
        state.save(update_fields=["conflicted", "updated_at"])

    return result
