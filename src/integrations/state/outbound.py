"""Deliver canonical state changes outward, exactly once each.

The engine is a transactional outbox. The delivery row is written in the same
transaction as the change that caused it, so there is no window in which state
moved but the intent to tell anyone about it was lost. The Celery kick that
follows is only an optimisation; a sweeper finds anything a dropped kick left
behind, which means correctness never depends on the broker being up.

Two rules do most of the safety work:

- **Claim before you write.** A conditional update moves ``pending`` to
  ``in_flight``, and a partial unique index lets only one row per
  (destination, item) hold that status. Serialization is enforced by the
  database, not by a cache lock a crashed worker could hold forever.
- **Retry by reading first.** A write that timed out may well have applied. Any
  attempt after the first reads provider state before re-issuing, so a network
  failure after a successful write becomes an acknowledgement rather than a
  second play.
"""

import logging
from uuid import uuid4

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from integrations.models import (
    CAPABILITY_WATCHED_PUSH_PLAYED,
    CAPABILITY_WATCHED_PUSH_UNPLAYED,
    OutboundDeliveryStatus,
    OutboundStateDelivery,
    SyncBinding,
    SyncClientKind,
    SyncDirection,
)
from integrations.state.adapters.base import (
    TerminalAdapterError,
    TransientAdapterError,
)

logger = logging.getLogger(__name__)

# Backoff for uncertain writes. Deliberately coarse: every retry re-reads
# provider state first, so retrying often buys nothing and costs rate limit.
RETRY_BACKOFF_SECONDS = (60, 300, 900, 3600)
MAX_ATTEMPTS = len(RETRY_BACKOFF_SECONDS) + 1

_ADAPTER_BUILDERS = {}


def get_adapter(binding):
    """Return the adapter for a binding, or None when it has none."""
    if not _ADAPTER_BUILDERS:
        from integrations.state.adapters import emby, jellyfin, kodi

        _ADAPTER_BUILDERS.update(
            {
                SyncClientKind.JELLYFIN.value: jellyfin.build_adapter,
                SyncClientKind.EMBY.value: emby.build_adapter,
                SyncClientKind.KODI.value: kodi.build_adapter,
            },
        )

    builder = _ADAPTER_BUILDERS.get(binding.client_kind)
    if builder is None:
        return None
    return builder(binding)


def _capability_for(watched):
    """Return the capability a write of this shape requires."""
    return (
        CAPABILITY_WATCHED_PUSH_PLAYED
        if watched
        else CAPABILITY_WATCHED_PUSH_UNPLAYED
    )


def enqueue_deliveries(change):
    """Record the intent to tell every eligible binding about one change.

    Must be called inside the change's own transaction. Skips the binding the
    change came from — that is the own-origin rule, and it is what stops a
    provider's own event being sent straight back to it.
    """
    if change.watched is None:
        return []

    capability = _capability_for(change.watched)
    created = []

    for binding in SyncBinding.objects.filter(user=change.user):
        # Own-origin skip: never tell a provider what it just told us.
        if binding.origin_key and binding.origin_key == change.origin_key:
            continue
        if not binding.allows(SyncDirection.OUTBOUND.value, capability):
            continue

        adapter = get_adapter(binding)
        if adapter is None or capability not in adapter.CAPABILITIES:
            continue

        # Coalesce: a pending write for this item is about to be wrong. An
        # in-flight one is left alone, because its receipt has to become
        # durable before anything may supersede it.
        OutboundStateDelivery.objects.filter(
            binding=binding,
            item=change.item,
            status=OutboundDeliveryStatus.PENDING.value,
        ).update(status=OutboundDeliveryStatus.SUPERSEDED.value)

        delivery, was_created = OutboundStateDelivery.objects.get_or_create(
            binding=binding,
            item=change.item,
            target_revision=change.revision,
            defaults={
                "user": change.user,
                "change": change,
                "target_digest": change.state_digest,
                "intent": change.watched,
                "status": OutboundDeliveryStatus.PENDING.value,
                "client_event_id": str(uuid4()),
                "correlation_id": change.correlation_id,
            },
        )
        if was_created:
            created.append(delivery)

    return created


def claim(delivery_id):
    """Take exclusive ownership of one delivery, or return None.

    A conditional update rather than a lock: two workers racing here both issue
    the same statement, and only one of them updates a row.
    """
    claimed = OutboundStateDelivery.objects.filter(
        pk=delivery_id,
        status=OutboundDeliveryStatus.PENDING.value,
    ).update(
        status=OutboundDeliveryStatus.IN_FLIGHT.value,
        attempts=F("attempts") + 1,
    )
    if not claimed:
        return None
    return OutboundStateDelivery.objects.get(pk=delivery_id)


def _finish(delivery, status, *, readback_digest="", error=""):
    """Record a terminal outcome for one delivery."""
    delivery.status = status
    delivery.last_error_message = error[:1000]
    if readback_digest:
        delivery.readback_digest = readback_digest
    if status == OutboundDeliveryStatus.DELIVERED.value:
        delivery.delivered_at = timezone.now()
    delivery.save(
        update_fields=[
            "status",
            "last_error_message",
            "readback_digest",
            "delivered_at",
            "updated_at",
        ],
    )
    return delivery


def _reschedule(delivery, error):
    """Put a failed delivery back in the queue, or give up on it."""
    if delivery.attempts >= MAX_ATTEMPTS:
        return _finish(
            delivery,
            OutboundDeliveryStatus.FAILED.value,
            error=str(error),
        )

    index = min(delivery.attempts - 1, len(RETRY_BACKOFF_SECONDS) - 1)
    delay = RETRY_BACKOFF_SECONDS[max(index, 0)]
    delivery.status = OutboundDeliveryStatus.PENDING.value
    delivery.next_attempt_at = timezone.now() + timezone.timedelta(seconds=delay)
    delivery.last_error_message = str(error)[:1000]
    delivery.save(
        update_fields=[
            "status",
            "next_attempt_at",
            "last_error_message",
            "updated_at",
        ],
    )
    return delivery


def _remote_digest(remote):
    """Return the digest for a provider's reported state."""
    from app.models import calculate_state_digest

    if remote is None:
        return ""
    return calculate_state_digest(
        remote.watched,
        remote.play_count,
        None,
    )


def run_delivery(delivery_id):
    """Attempt one delivery, reading first when the outcome is uncertain."""
    delivery = claim(delivery_id)
    if delivery is None:
        return None

    binding = delivery.binding
    if not binding.is_operational():
        return _finish(delivery, OutboundDeliveryStatus.SKIPPED.value)

    capability = _capability_for(delivery.intent)
    if not binding.allows(SyncDirection.OUTBOUND.value, capability):
        return _finish(delivery, OutboundDeliveryStatus.SKIPPED.value)

    adapter = get_adapter(binding)
    if adapter is None:
        return _finish(
            delivery,
            OutboundDeliveryStatus.SKIPPED.value,
            error="No adapter available for this binding",
        )

    try:
        external_id = adapter.resolve_external_id(delivery.item)
        if not external_id:
            # An unresolvable or ambiguous item is not a failure to retry: the
            # answer will not change until the library does.
            _record_unresolved(binding, delivery.item)
            return _finish(
                delivery,
                OutboundDeliveryStatus.SKIPPED.value,
                error="Item could not be resolved unambiguously",
            )

        # Retry by reading first: a previous attempt may have applied before
        # the connection dropped, and re-issuing blindly is how a timeout
        # becomes a phantom second play.
        if delivery.attempts > 1:
            remote = adapter.read_state(external_id)
            if remote is not None and remote.watched == delivery.intent:
                return _finish(
                    delivery,
                    OutboundDeliveryStatus.DELIVERED.value,
                    readback_digest=_remote_digest(remote),
                )

        adapter.write_watched(external_id, watched=delivery.intent)

        # Read back what the write actually did, rather than trusting what we
        # asked for. This digest is what later identifies the provider's echo.
        readback = adapter.read_state(external_id)
    except TerminalAdapterError as error:
        return _finish(
            delivery,
            OutboundDeliveryStatus.FAILED.value,
            error=str(error),
        )
    except TransientAdapterError as error:
        return _reschedule(delivery, error)

    return _finish(
        delivery,
        OutboundDeliveryStatus.DELIVERED.value,
        readback_digest=_remote_digest(readback),
    )


def _record_unresolved(binding, item):
    """Note an item this provider could not be pointed at, deduplicated."""
    from integrations.models import (
        UnresolvedExternalReference,
        UnresolvedReferenceReason,
    )

    reference, created = UnresolvedExternalReference.objects.get_or_create(
        binding=binding,
        namespace=item.source,
        value=item.media_id,
        reason_code=UnresolvedReferenceReason.AMBIGUOUS.value,
        defaults={
            "context": {
                "media_type": item.media_type,
                "season_number": item.season_number,
                "episode_number": item.episode_number,
            },
        },
    )
    if not created:
        reference.occurrence_count += 1
        reference.save(update_fields=["occurrence_count", "last_seen_at"])


def due_deliveries(limit=100):
    """Return deliveries ready to be attempted now."""
    now = timezone.now()
    return list(
        OutboundStateDelivery.objects.filter(
            status=OutboundDeliveryStatus.PENDING.value,
        )
        .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
        .order_by("created_at")[:limit],
    )


def schedule_delivery(delivery):
    """Kick a delivery once the surrounding transaction commits."""
    from integrations.tasks import deliver_watched_state

    transaction.on_commit(
        lambda: deliver_watched_state.delay(delivery_id=delivery.pk),
    )
