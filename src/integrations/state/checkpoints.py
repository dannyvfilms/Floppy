"""Client checkpoints over the watched-state change feed.

A checkpoint is the position a binding has proved it applied. Nothing wrote one
before this: ``SyncCheckpoint`` existed as a model with no writer, so the change
log had no safe watermark and could never be compacted.

The proof is the client's next request. A client that asks for changes after
sequence N is telling us it applied everything up to N; the server cannot know
that any earlier. Advancing on delivery instead would skip silently whenever a
client fetched a page and then died before applying it.
"""

import logging

from django.db.models import Min
from django.utils import timezone

from integrations.models import (
    CAPABILITY_WATCHED_PULL,
    SyncBinding,
    SyncCheckpoint,
    SyncDirection,
)

logger = logging.getLogger(__name__)

WATCHED_STATE_RESOURCE = "watched_state"


def record_applied_position(
    binding, sequence, *, resource=WATCHED_STATE_RESOURCE, create=True,
):
    """Record that ``binding`` has applied everything up to ``sequence``.

    Never moves a checkpoint backwards: an out-of-order or replayed request
    must not re-expose changes that were already compacted away. With
    ``create=False`` only an existing checkpoint advances, for a pull client
    whose checkpoint a snapshot alone may create.
    """
    if not create:
        SyncCheckpoint.objects.filter(
            binding=binding,
            resource=resource,
            direction=SyncDirection.OUTBOUND.value,
            last_sequence__lt=sequence,
        ).update(last_sequence=sequence, cursor=str(sequence), updated_at=timezone.now())
        return None
    checkpoint, created = SyncCheckpoint.objects.get_or_create(
        binding=binding,
        resource=resource,
        # The feed carries Floppy state outward to the client.
        direction=SyncDirection.OUTBOUND.value,
        defaults={"last_sequence": sequence, "cursor": str(sequence)},
    )
    if not created and sequence > checkpoint.last_sequence:
        checkpoint.last_sequence = sequence
        checkpoint.cursor = str(sequence)
        checkpoint.save(update_fields=["last_sequence", "cursor", "updated_at"])
    return checkpoint


def pin_snapshot_position(binding, sequence, *, resource=WATCHED_STATE_RESOURCE):
    """Pin ``binding`` at the sequence a snapshot began, and mark it as seen now.

    A snapshot is a client's proof that it holds everything up to ``sequence``,
    so the log must not compact past it before the client's first feed pull.
    Unlike :func:`record_applied_position` this always refreshes the row, even
    when the sequence has not moved: a resnapshot at the same position has to
    be visible as a fresh check-in, not look like the stale pin it replaces.
    """
    checkpoint, created = SyncCheckpoint.objects.get_or_create(
        binding=binding,
        resource=resource,
        direction=SyncDirection.OUTBOUND.value,
        defaults={"last_sequence": sequence, "cursor": str(sequence)},
    )
    if not created:
        checkpoint.last_sequence = max(sequence, checkpoint.last_sequence)
        checkpoint.cursor = str(checkpoint.last_sequence)
        checkpoint.save(update_fields=["last_sequence", "cursor", "updated_at"])
    return checkpoint


def reset_pull_positions(user=None, *, binding=None, resource=WATCHED_STATE_RESOURCE):
    """Forget where pull clients got to, so each must take a fresh snapshot.

    Called whenever the log stopped being a complete record: it was not being
    written, or state moved without being logged. A checkpoint is the only
    thing that lets a named pull client resume from a cursor, so removing it is
    what makes the client's next feed pull ask for a resnapshot.
    """
    # Filtered in Python: JSONField containment is not available on SQLite.
    bindings = [binding] if binding is not None else list(
        SyncBinding.objects.filter(user=user),
    )
    pull_ids = [
        candidate.pk
        for candidate in bindings
        if candidate.has_capability(CAPABILITY_WATCHED_PULL)
    ]
    deleted, _ = SyncCheckpoint.objects.filter(
        binding_id__in=pull_ids,
        resource=resource,
    ).delete()
    return deleted


def compaction_watermark(user, *, resource=WATCHED_STATE_RESOURCE, stale_before=None):
    """Return the highest sequence safe to compact below, or None.

    None means compact nothing. That is the answer whenever a live binding has
    no checkpoint yet, because it has applied nothing and every change is still
    owed to it.

    A binding that has not checked in since ``stale_before`` is excluded: it has
    to take a fresh snapshot when it returns, so holding the whole log for it
    would let one dead device pin the table forever.
    """
    bindings = SyncBinding.objects.filter(user=user, kill_switch=False).exclude(
        disabled_at__isnull=False,
    )
    checkpoints = SyncCheckpoint.objects.filter(
        binding__in=bindings,
        resource=resource,
    )
    if stale_before is not None:
        checkpoints = checkpoints.filter(updated_at__gte=stale_before)
        bindings = bindings.filter(
            checkpoints__resource=resource,
            checkpoints__updated_at__gte=stale_before,
        )

    live_count = bindings.distinct().count()
    if live_count == 0:
        # Nobody is listening. Retention alone decides.
        return None

    positions = checkpoints.values("binding_id").distinct().count()
    if positions < live_count:
        # At least one live binding has applied nothing yet.
        return None

    return checkpoints.aggregate(safe=Min("last_sequence"))["safe"]
