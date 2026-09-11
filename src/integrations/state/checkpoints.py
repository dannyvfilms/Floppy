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

from integrations.models import SyncBinding, SyncCheckpoint, SyncDirection

logger = logging.getLogger(__name__)

WATCHED_STATE_RESOURCE = "watched_state"


def record_applied_position(binding, sequence, *, resource=WATCHED_STATE_RESOURCE):
    """Record that ``binding`` has applied everything up to ``sequence``.

    Never moves a checkpoint backwards: an out-of-order or replayed request
    must not re-expose changes that were already compacted away.
    """
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
