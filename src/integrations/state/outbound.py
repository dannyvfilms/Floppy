"""Deliver watched-state and rating changes through a transactional outbox.

The engine is a transactional outbox. The delivery row is written in the same
transaction as the change that caused it, so there is no window in which state
moved but the intent to tell anyone about it was lost. The Celery kick that
follows is only an optimisation; a sweeper finds anything a dropped kick left
behind, which means correctness never depends on the broker being up.

Two rules do most of the safety work:

- **Claim before you write.** A conditional update moves ``pending`` to
  ``in_flight``, and a partial unique index lets only one row per
  (destination, item, operation) hold that status. Serialization is enforced by the
  database, not by a cache lock a crashed worker could hold forever.
- **Retry by reading first.** A write that timed out may well have applied. Any
  attempt after the first reads provider state before re-issuing, so a network
  failure after a successful write becomes an acknowledgement rather than a
  second play.

A provider that takes many writes in one request (see ``BatchAdapter``) is
different in one way: its deliveries are held until a release time and then
sent together by ``flush_binding``. The release time comes from the schedule the
user picked, and is written onto each delivery as ``next_attempt_at``, so the
sweeper needs no second idea of "due".
"""

import logging
from collections import Counter
from datetime import datetime, timedelta
from uuid import NAMESPACE_OID, uuid4, uuid5

from django.db import IntegrityError, transaction
from django.db.models import F, Max, Q
from django.utils import timezone

from app.cache_safety import ON_ERROR_SKIP, acquire_lock, release_lock
from app.models import TV, MediaTypes, Movie
from app.models.watch_state import WatchStateChange, WatchStateOrigin
from app.services.watch_state import is_importing_watch_state
from integrations.models import (
    CAPABILITY_PLAY_PUSH,
    CAPABILITY_PLAY_REMOVE,
    CAPABILITY_RATING_PUSH,
    CAPABILITY_STATUS_PUSH,
    CAPABILITY_WATCHED_PUSH_PLAYED,
    CAPABILITY_WATCHED_PUSH_UNPLAYED,
    OutboundDeliveryStatus,
    OutboundStateDelivery,
    SyncBinding,
    SyncDeliverySchedule,
    SyncDirection,
)
from integrations.state import registry
from integrations.state.adapters.base import (
    BATCH_DELIVERED,
    BATCH_RETRY,
    BATCH_SKIPPED,
    BatchItem,
    TerminalAdapterError,
    TransientAdapterError,
)

logger = logging.getLogger(__name__)

# Backoff for uncertain writes. Deliberately coarse: every retry re-reads
# provider state first, so retrying often buys nothing and costs rate limit.
RETRY_BACKOFF_SECONDS = (60, 300, 900, 3600)
MAX_ATTEMPTS = len(RETRY_BACKOFF_SECONDS) + 1

# A live batch waits this long, so a burst (a whole season marked watched)
# leaves as one request instead of one per episode.
LIVE_BATCH_WINDOW_SECONDS = 10
FLUSH_LOCK_TIMEOUT = 900
# An attempt still in flight after this long belongs to a worker that died.
STALE_IN_FLIGHT_SECONDS = 1800
MAX_FLUSH_ROUNDS = 20

# Operations where only the latest intent matters. A play is the opposite: each
# one is a dated event of its own and is never replaced by a later one.
COALESCED_OPERATIONS = frozenset({"watched", "rating", "status"})

_OPERATION_CAPABILITIES = {
    "rating": CAPABILITY_RATING_PUSH,
    "play": CAPABILITY_PLAY_PUSH,
    "status": CAPABILITY_STATUS_PUSH,
    "play_remove": CAPABILITY_PLAY_REMOVE,
}


def get_adapter(binding):
    """Return the adapter for a binding, or None when it has none."""
    return registry.build_adapter(binding)


def _capability_for(watched):
    """Return the capability a write of this shape requires."""
    return (
        CAPABILITY_WATCHED_PUSH_PLAYED if watched else CAPABILITY_WATCHED_PUSH_UNPLAYED
    )


def _capability_of(delivery):
    """Return the capability one queued delivery needs."""
    return _OPERATION_CAPABILITIES.get(
        delivery.operation,
    ) or _capability_for(delivery.intent)


def release_time(schedule, now=None):
    """Return when deliveries queued now may first be sent.

    Hourly and daily deliveries leave on the next clock boundary (UTC), so every
    delivery queued in the same period is sent together.
    """
    now = now or timezone.now()
    if schedule == SyncDeliverySchedule.HOURLY.value:
        return now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    if schedule == SyncDeliverySchedule.DAILY.value:
        return now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
            days=1,
        )
    return now + timedelta(seconds=LIVE_BATCH_WINDOW_SECONDS)


def _is_batch(adapter):
    """Return whether this adapter takes its writes in batches."""
    return bool(getattr(adapter, "BATCH_SIZE", None))


def _hold_until(binding, adapter):
    """Return the release time for a new delivery, or None to send it at once."""
    if not _is_batch(adapter):
        return None
    return release_time(binding.delivery_schedule)


def _usable_adapter(binding, capability, *, importing):
    """Return the adapter that may carry this capability for the binding, or None."""
    if not binding.allows(SyncDirection.OUTBOUND.value, capability):
        return None
    adapter = get_adapter(binding)
    if adapter is None or capability not in adapter.CAPABILITIES:
        return None
    # Imports are history, not something the user just did. An adapter opts out
    # when its service would show them as new activity.
    if importing and not getattr(adapter, "ACCEPTS_IMPORTED_CHANGES", True):
        return None
    return adapter


def _previous_play_count(change):
    """Return the play count before this change, or None when there was none."""
    if change.previous_revision is None:
        return None
    return (
        WatchStateChange.objects.filter(
            user=change.user,
            item=change.item,
            revision=change.previous_revision,
        )
        .values_list("play_count", flat=True)
        .first()
    )


def _is_new_play(change):
    """Return whether a change recorded one more play, not just a new date."""
    previous = _previous_play_count(change)
    return previous is None or (change.play_count or 0) > (previous or 0)


def _lost_a_play(change):
    """Return whether a change recorded fewer plays than before."""
    previous = _previous_play_count(change)
    return previous is not None and (change.play_count or 0) < previous


def _queue_play_removals(binding, adapter, change):
    """Queue the removal of each play the destination holds that Floppy no longer has.

    A removal names one exact play: the receipt the destination gave when it
    took it, and the date it was sent with. Nothing is inferred from a count, so
    a rewatch that is still in Floppy is never touched. A play that was never
    delivered is simply not sent, and one still being sent is left alone.
    """
    from app.services.watch_state import derive_state

    current = Counter(derive_state(change.user, change.item).play_dates)
    sent = OutboundStateDelivery.objects.filter(
        binding=binding,
        item=change.item,
        operation="play",
        status__in=[
            OutboundDeliveryStatus.PENDING.value,
            OutboundDeliveryStatus.IN_FLIGHT.value,
            OutboundDeliveryStatus.DELIVERED.value,
        ],
    ).order_by("pk")
    handled = {
        payload.get("play_delivery")
        for payload in OutboundStateDelivery.objects.filter(
            binding=binding,
            item=change.item,
            operation="play_remove",
            status__in=[
                OutboundDeliveryStatus.PENDING.value,
                OutboundDeliveryStatus.IN_FLIGHT.value,
                OutboundDeliveryStatus.DELIVERED.value,
            ],
        ).values_list("payload", flat=True)
    }
    revision = (
        OutboundStateDelivery.objects.filter(
            binding=binding,
            item=change.item,
            operation="play_remove",
        ).aggregate(latest=Max("target_revision"))["latest"]
        or 0
    )
    created = []
    for play in sent:
        if play.pk in handled:
            continue
        try:
            when = datetime.fromisoformat(play.payload.get("watched_at") or "")
        except ValueError:
            continue
        if current[when] > 0:
            current[when] -= 1
            continue
        if play.status == OutboundDeliveryStatus.PENDING.value:
            play.status = OutboundDeliveryStatus.SUPERSEDED.value
            play.save(update_fields=["status", "updated_at"])
        elif play.status == OutboundDeliveryStatus.DELIVERED.value:
            revision += 1
            created.append(
                OutboundStateDelivery.objects.create(
                    binding=binding,
                    user=change.user,
                    item=change.item,
                    change=change,
                    operation="play_remove",
                    target_revision=revision,
                    payload={
                        "watched_at": play.payload["watched_at"],
                        "receipt": play.payload.get("receipt", ""),
                        "play_delivery": play.pk,
                    },
                    client_event_id=str(uuid4()),
                    correlation_id=change.correlation_id,
                    next_attempt_at=_hold_until(binding, adapter),
                ),
            )
    return created


def enqueue_deliveries(change):
    """Record the intent to tell every eligible binding about one change.

    Must be called inside the change's own transaction. Skips the binding the
    change came from — that is the own-origin rule, and it is what stops a
    provider's own event being sent straight back to it.
    """
    if change.watched is None:
        return []

    importing = change.origin_kind == WatchStateOrigin.IMPORT.value
    capability = _capability_for(change.watched)
    new_play = bool(change.watched and change.watched_at and _is_new_play(change))
    lost_a_play = _lost_a_play(change)
    created = []

    for binding in SyncBinding.objects.filter(user=change.user):
        # Own-origin skip: never tell a provider what it just told us.
        if binding.origin_key and binding.origin_key == change.origin_key:
            continue

        adapter = _usable_adapter(binding, capability, importing=importing)
        if adapter is not None:
            # Coalesce: a pending write for this item is about to be wrong. An
            # in-flight one is left alone, because its receipt has to become
            # durable before anything may supersede it.
            OutboundStateDelivery.objects.filter(
                binding=binding,
                item=change.item,
                operation="watched",
                status=OutboundDeliveryStatus.PENDING.value,
            ).update(status=OutboundDeliveryStatus.SUPERSEDED.value)

            delivery, was_created = OutboundStateDelivery.objects.get_or_create(
                binding=binding,
                item=change.item,
                operation="watched",
                target_revision=change.revision,
                defaults={
                    "user": change.user,
                    "change": change,
                    "target_digest": change.state_digest,
                    "intent": change.watched,
                    "status": OutboundDeliveryStatus.PENDING.value,
                    "client_event_id": str(uuid4()),
                    "correlation_id": change.correlation_id,
                    "next_attempt_at": _hold_until(binding, adapter),
                },
            )
            if was_created:
                created.append(delivery)

        adapter = (
            _usable_adapter(binding, CAPABILITY_PLAY_PUSH, importing=importing)
            if new_play
            else None
        )
        if adapter is not None:
            # A dated play, not a flag: every one is kept and none replaces
            # another, so a rewatch is a second play at its own date.
            delivery, was_created = OutboundStateDelivery.objects.get_or_create(
                binding=binding,
                item=change.item,
                operation="play",
                target_revision=change.revision,
                defaults={
                    "user": change.user,
                    "change": change,
                    "target_digest": change.state_digest,
                    "payload": {"watched_at": change.watched_at.isoformat()},
                    "status": OutboundDeliveryStatus.PENDING.value,
                    "client_event_id": str(uuid4()),
                    "correlation_id": change.correlation_id,
                    "next_attempt_at": _hold_until(binding, adapter),
                },
            )
            if was_created:
                created.append(delivery)

        adapter = (
            _usable_adapter(binding, CAPABILITY_PLAY_REMOVE, importing=importing)
            if lost_a_play
            else None
        )
        if adapter is not None:
            created.extend(_queue_play_removals(binding, adapter, change))

    return created


@transaction.atomic
def _enqueue_latest(user, item, operation, *, client_kind, payload=None, rating=None):
    """Queue the newest intent of a coalesced operation for every eligible binding.

    Provider adapters own value normalization and identity resolution. The
    outbox owns approval, ordering, coalescing and delivery for every provider.
    """
    capability = _OPERATION_CAPABILITIES[operation]
    importing = is_importing_watch_state()
    deliveries = []
    bindings = SyncBinding.objects.select_for_update().filter(user=user)
    if client_kind is not None:
        bindings = bindings.filter(client_kind=client_kind)
    for binding in bindings:
        adapter = _usable_adapter(binding, capability, importing=importing)
        if adapter is None:
            continue
        previous = OutboundStateDelivery.objects.filter(
            binding=binding,
            item=item,
            operation=operation,
        )
        revision = (
            previous.aggregate(latest=Max("target_revision"))["latest"] or 0
        ) + 1
        previous.filter(status=OutboundDeliveryStatus.PENDING.value).update(
            status=OutboundDeliveryStatus.SUPERSEDED.value,
        )
        delivery = OutboundStateDelivery.objects.create(
            binding=binding,
            user=user,
            item=item,
            operation=operation,
            target_revision=revision,
            rating=rating,
            payload=payload or {},
            client_event_id=str(uuid4()),
            next_attempt_at=_hold_until(binding, adapter),
        )
        deliveries.append(delivery)
        schedule_delivery(delivery)
    return deliveries


def enqueue_rating_change(user, item, score, *, client_kind=None):
    """Queue a rating set/clear inside the transaction that writes the score."""
    return _enqueue_latest(
        user,
        item,
        "rating",
        client_kind=client_kind,
        rating=score,
    )


def enqueue_status_change(user, item, status, *, client_kind=None):
    """Queue a tracking-status change inside the transaction that writes it."""
    return _enqueue_latest(
        user,
        item,
        "status",
        client_kind=client_kind,
        payload={"status": status},
    )


def set_delivery_schedule(binding, schedule):
    """Change how soon a binding's deliveries are sent, including those waiting."""
    binding.delivery_schedule = schedule
    binding.save(update_fields=["delivery_schedule", "updated_at"])
    # Only rows still on their first attempt are held by the schedule. A later
    # attempt is waiting on a backoff the provider asked for, and a schedule
    # change must not shorten it.
    OutboundStateDelivery.objects.filter(
        binding=binding,
        status=OutboundDeliveryStatus.PENDING.value,
        attempts=0,
        next_attempt_at__gt=timezone.now(),
    ).update(next_attempt_at=release_time(schedule))


def claim(delivery_id):
    """Take exclusive ownership of one delivery, or return None.

    A conditional update rather than a lock: two workers racing here both issue
    the same statement, and only one of them updates a row.
    """
    try:
        with transaction.atomic():
            claimed = (
                OutboundStateDelivery.objects.filter(
                    pk=delivery_id,
                    status=OutboundDeliveryStatus.PENDING.value,
                )
                .filter(
                    Q(next_attempt_at__isnull=True)
                    | Q(next_attempt_at__lte=timezone.now()),
                )
                .update(
                    status=OutboundDeliveryStatus.IN_FLIGHT.value,
                    attempts=F("attempts") + 1,
                    claimed_at=timezone.now(),
                )
            )
    except IntegrityError:
        # Another revision of this operation is still in flight. The sweeper
        # will claim this one once that attempt has finished.
        return None
    if not claimed:
        return None
    return OutboundStateDelivery.objects.select_related("binding", "item").get(
        pk=delivery_id,
    )


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
            "payload",
            "updated_at",
        ],
    )
    return delivery


def _superseded(delivery):
    """Return whether a newer intent has replaced this one."""
    return (
        delivery.operation in COALESCED_OPERATIONS
        and OutboundStateDelivery.objects.filter(
            binding=delivery.binding,
            item=delivery.item,
            operation=delivery.operation,
            target_revision__gt=delivery.target_revision,
        ).exists()
    )


def _reschedule(delivery, error, *, retry_after=None):
    """Put a failed delivery back in the queue, or give up on it.

    ``retry_after`` is a wait the provider asked for; the delivery is never
    retried sooner than that, whatever the backoff says.
    """
    if _superseded(delivery):
        return _finish(delivery, OutboundDeliveryStatus.SUPERSEDED.value)
    if delivery.attempts >= MAX_ATTEMPTS:
        return _finish(
            delivery,
            OutboundDeliveryStatus.FAILED.value,
            error=str(error),
        )

    index = min(delivery.attempts - 1, len(RETRY_BACKOFF_SECONDS) - 1)
    delay = max(RETRY_BACKOFF_SECONDS[max(index, 0)], retry_after or 0)
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

    capability = _capability_of(delivery)
    if not binding.allows(SyncDirection.OUTBOUND.value, capability):
        return _finish(delivery, OutboundDeliveryStatus.SKIPPED.value)

    adapter = get_adapter(binding)
    if adapter is None or capability not in adapter.CAPABILITIES:
        return _finish(
            delivery,
            OutboundDeliveryStatus.SKIPPED.value,
            error="No adapter available for this binding",
        )

    if _is_batch(adapter):
        _send_batch(binding, adapter, [delivery])
        return delivery

    try:
        if delivery.operation == "rating" and _superseded(delivery):
            return _finish(delivery, OutboundDeliveryStatus.SUPERSEDED.value)
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

        if delivery.operation == "rating":
            target = adapter.normalize_rating(delivery.rating)
            if delivery.attempts > 1:
                remote = adapter.read_rating(external_id)
                if remote is not None and remote.score == target:
                    return _finish(delivery, OutboundDeliveryStatus.DELIVERED.value)
            adapter.write_rating(external_id, score=target)
            return _finish(delivery, OutboundDeliveryStatus.DELIVERED.value)

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


def batch_idempotency_key(client_event_ids):
    """Return the key that identifies one set of deliveries sent as a request.

    The same set always gives the same key, so a request that timed out and is
    sent again can be recognised by the provider as the one it already took.
    """
    return str(uuid5(NAMESPACE_OID, ",".join(sorted(client_event_ids))))


def _batch_item(binding, adapter, delivery):
    """Resolve one delivery into a batch item, or finish it and return None."""
    if not binding.allows(SyncDirection.OUTBOUND.value, _capability_of(delivery)):
        _finish(delivery, OutboundDeliveryStatus.SKIPPED.value)
        return None
    if _superseded(delivery):
        _finish(delivery, OutboundDeliveryStatus.SUPERSEDED.value)
        return None
    try:
        external_id = adapter.resolve_external_id(delivery.item)
        if not external_id:
            # Not a failure to retry: the answer will not change until the
            # library does.
            _record_unresolved(binding, delivery.item)
            _finish(
                delivery,
                OutboundDeliveryStatus.SKIPPED.value,
                error="Item could not be resolved unambiguously",
            )
            return None
        rating = (
            adapter.normalize_rating(delivery.rating)
            if delivery.operation == "rating"
            else None
        )
    except TerminalAdapterError as error:
        _finish(delivery, OutboundDeliveryStatus.FAILED.value, error=str(error))
        return None
    except TransientAdapterError as error:
        _reschedule(delivery, error, retry_after=error.retry_after)
        return None

    if delivery.operation == "status" and not _status_still_current(delivery):
        _finish(delivery, OutboundDeliveryStatus.SUPERSEDED.value)
        return None

    payload = dict(delivery.payload)
    if delivery.operation == "watched":
        payload["watched"] = delivery.intent
    return BatchItem(
        delivery_id=delivery.pk,
        operation=delivery.operation,
        item=delivery.item,
        external_id=external_id,
        payload=payload,
        rating=rating,
    )


def _status_still_current(delivery):
    """Return whether the tracked entry still has the status this delivery carries.

    A status is queued just before it is written, so a write that never landed,
    or was replaced, must not be sent.
    """
    model = {MediaTypes.MOVIE.value: Movie, MediaTypes.TV.value: TV}.get(
        delivery.item.media_type,
    )
    if model is None:
        return False
    current = (
        model.objects.filter(user_id=delivery.user_id, item=delivery.item)
        .values_list("status", flat=True)
        .first()
    )
    return current == delivery.payload.get("status")


def _post_batch(adapter, items, deliveries, key=None):
    """Send one request and record what the provider did with each item.

    ``key`` is the key the group was first sent under. A group that has not
    been sent yet gets its key here and keeps it on its rows, so a retry goes
    out under the same key however the group's members have changed since.
    """
    if key is None:
        key = batch_idempotency_key(
            deliveries[i.delivery_id].client_event_id for i in items
        )
        rows = [deliveries[i.delivery_id] for i in items]
        for row in rows:
            row.payload = {**row.payload, "batch_key": key}
        OutboundStateDelivery.objects.bulk_update(rows, ["payload"])
    try:
        results = adapter.write_batch(items, idempotency_key=key)
    except TerminalAdapterError as error:
        for item in items:
            _finish(
                deliveries[item.delivery_id],
                OutboundDeliveryStatus.FAILED.value,
                error=str(error),
            )
        return
    except TransientAdapterError as error:
        for item in items:
            _reschedule(
                deliveries[item.delivery_id],
                error,
                retry_after=error.retry_after,
            )
        return
    except Exception as error:
        # The rows are in flight. Leaving them there would strand them, since
        # only pending rows are ever picked up again.
        logger.exception("Batch write failed unexpectedly")
        for item in items:
            _reschedule(deliveries[item.delivery_id], f"Unexpected error: {error}")
        return

    for position, item in enumerate(items):
        delivery = deliveries[item.delivery_id]
        result = results[position] if position < len(results) else None
        if result is None:
            _reschedule(delivery, "The provider returned no result for this item")
        elif result.outcome == BATCH_DELIVERED:
            if result.receipt:
                delivery.payload = {**delivery.payload, "receipt": result.receipt}
            _finish(delivery, OutboundDeliveryStatus.DELIVERED.value)
        elif result.outcome == BATCH_SKIPPED:
            _finish(delivery, OutboundDeliveryStatus.SKIPPED.value, error=result.error)
        elif result.outcome == BATCH_RETRY:
            _reschedule(delivery, result.error or "The provider asked to retry")
        else:
            _finish(delivery, OutboundDeliveryStatus.FAILED.value, error=result.error)


def _send_batch(binding, adapter, claimed):
    """Resolve claimed deliveries and send them to a batch adapter."""
    items = []
    by_id = {}
    for delivery in claimed:
        item = _batch_item(binding, adapter, delivery)
        if item is not None:
            items.append(item)
            by_id[delivery.pk] = delivery
    # A retry goes out apart from fresh work, grouped as it was first sent and
    # under that request's key, so the provider can recognise a repeat even if
    # other retries are due now or one member has since dropped out.
    sent_before = {}
    fresh = []
    for item in items:
        key = by_id[item.delivery_id].payload.get("batch_key")
        if key:
            sent_before.setdefault(key, []).append(item)
        else:
            fresh.append(item)
    for key, group in sent_before.items():
        _post_batch(adapter, group, by_id, key=key)
    if fresh:
        _post_batch(adapter, fresh, by_id)


def _claim_due(binding, size):
    """Claim up to ``size`` due deliveries, at most one per item and operation.

    The database allows one in-flight row per item and operation, so a second
    play of the same item waits for the next round of the flush.
    """
    now = timezone.now()
    pending = (
        OutboundStateDelivery.objects.filter(
            binding=binding,
            status=OutboundDeliveryStatus.PENDING.value,
        )
        .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
        .order_by("created_at", "pk")[:size]
    )
    claimed = []
    seen = set()
    for delivery in pending:
        key = (delivery.item_id, delivery.operation)
        if key in seen:
            continue
        seen.add(key)
        got = claim(delivery.pk)
        if got is not None:
            claimed.append(got)
    return claimed


def flush_binding(binding_id):
    """Send everything due for one batch binding, in as few requests as it allows.

    Returns the number of deliveries attempted.
    """
    binding = SyncBinding.objects.filter(pk=binding_id).first()
    adapter = get_adapter(binding) if binding is not None else None
    if not _is_batch(adapter):
        return 0

    lock_key = f"outbound_flush:{binding.pk}"
    # Fail closed: the sweeper comes back, and two flushes at once would only
    # spend the provider's rate limit twice.
    if not acquire_lock(lock_key, timeout=FLUSH_LOCK_TIMEOUT, on_error=ON_ERROR_SKIP):
        return 0
    attempted = 0
    try:
        for _ in range(MAX_FLUSH_ROUNDS):
            claimed = _claim_due(binding, adapter.BATCH_SIZE)
            if not claimed:
                break
            attempted += len(claimed)
            _send_batch(binding, adapter, claimed)
    finally:
        release_lock(lock_key)

    if attempted:
        binding.last_flushed_at = timezone.now()
        binding.save(update_fields=["last_flushed_at", "updated_at"])
    return attempted


def due_deliveries(limit=100):
    """Return deliveries ready to be attempted now."""
    now = timezone.now()
    return list(
        OutboundStateDelivery.objects.filter(
            status=OutboundDeliveryStatus.PENDING.value,
        )
        .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
        .select_related("binding")
        .order_by("created_at")[:limit],
    )


def release_stale_deliveries():
    """Put attempts abandoned by a dead worker back in the queue.

    Safe by design: the next attempt of a delivery reads first, or for a batch
    is sent under the same idempotency key, so one that did apply is recognised.
    """
    cutoff = timezone.now() - timedelta(seconds=STALE_IN_FLIGHT_SECONDS)
    # A row that was already in flight when ``claimed_at`` was added has no
    # claim time; its last change is the best the database knows.
    return OutboundStateDelivery.objects.filter(
        Q(claimed_at__lt=cutoff) | Q(claimed_at__isnull=True, updated_at__lt=cutoff),
        status=OutboundDeliveryStatus.IN_FLIGHT.value,
    ).update(status=OutboundDeliveryStatus.PENDING.value, next_attempt_at=None)


def sweep_due_deliveries(limit=100):
    """Attempt everything that is due: singly, or by flushing batch bindings."""
    release_stale_deliveries()
    attempted = 0
    flushed = set()
    for delivery in due_deliveries(limit=limit):
        binding = delivery.binding
        if binding.pk in flushed:
            continue
        if _is_batch(get_adapter(binding)):
            flushed.add(binding.pk)
            attempted += flush_binding(binding.pk)
        else:
            run_delivery(delivery.pk)
            attempted += 1
    return attempted


def kick_flush(binding):
    """Flush a batch binding after the live window, once the transaction commits.

    On an hourly or daily schedule nothing is kicked: the sweeper flushes at the
    release time already written on each delivery.
    """
    from integrations.tasks import flush_outbound_batch

    if binding.delivery_schedule != SyncDeliverySchedule.LIVE.value:
        return
    transaction.on_commit(
        lambda: flush_outbound_batch.apply_async(
            kwargs={"binding_id": binding.pk},
            countdown=LIVE_BATCH_WINDOW_SECONDS,
        ),
        robust=True,
    )


def schedule_delivery(delivery):
    """Kick a delivery once the surrounding transaction commits.

    A batch binding is flushed instead (see ``kick_flush``).
    """
    from integrations.tasks import deliver_watched_state

    binding = delivery.binding
    if _is_batch(get_adapter(binding)):
        kick_flush(binding)
        return
    transaction.on_commit(
        lambda: deliver_watched_state.delay(delivery_id=delivery.pk),
        robust=True,
    )
