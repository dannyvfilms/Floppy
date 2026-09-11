"""Assemble what the settings page needs to show about synchronization.

Kept out of the view so the template stays declarative and the "what can this
connection actually do" logic has one home. The distinction that matters here
is between a capability the user has approved and one the adapter can actually
honour: showing only the first would tell someone a direction is on when
nothing will ever travel down it.
"""

from integrations.models import (
    CAPABILITY_WATCHED_PUSH_PLAYED,
    CAPABILITY_WATCHED_PUSH_UNPLAYED,
    CAPABILITY_WATCHED_READ,
    CAPABILITY_WATCHED_WRITE_PLAYED,
    CAPABILITY_WATCHED_WRITE_UNPLAYED,
    OutboundDeliveryStatus,
    StateConflictStatus,
    SyncBinding,
    SyncDirection,
)

# The four choices a connection offers, in the order they are shown.
DIRECTION_OFF = "off"
DIRECTION_INBOUND = "inbound"
DIRECTION_OUTBOUND = "outbound"
DIRECTION_BOTH = "both"

DIRECTION_CHOICES = (
    (DIRECTION_OFF, "Off"),
    (DIRECTION_INBOUND, "Provider to Floppy"),
    (DIRECTION_OUTBOUND, "Floppy to provider"),
    (DIRECTION_BOTH, "Both"),
)
DIRECTION_LABELS = dict(DIRECTION_CHOICES)

INBOUND_CAPABILITIES = (
    CAPABILITY_WATCHED_READ,
    CAPABILITY_WATCHED_WRITE_PLAYED,
    CAPABILITY_WATCHED_WRITE_UNPLAYED,
)
OUTBOUND_CAPABILITIES = (
    CAPABILITY_WATCHED_PUSH_PLAYED,
    CAPABILITY_WATCHED_PUSH_UNPLAYED,
)

CAPABILITY_LABELS = {
    CAPABILITY_WATCHED_READ: "Read watched state",
    CAPABILITY_WATCHED_WRITE_PLAYED: "Accept 'watched' from the provider",
    CAPABILITY_WATCHED_WRITE_UNPLAYED: "Accept 'unwatched' from the provider",
    CAPABILITY_WATCHED_PUSH_PLAYED: "Send 'watched' to the provider",
    CAPABILITY_WATCHED_PUSH_UNPLAYED: "Send 'unwatched' to the provider",
}


def current_direction(binding):
    """Return the direction choice a binding currently represents."""
    directions = set(binding.approved_directions or [])
    inbound = SyncDirection.INBOUND.value in directions
    outbound = SyncDirection.OUTBOUND.value in directions

    if inbound and outbound:
        return DIRECTION_BOTH
    if inbound:
        return DIRECTION_INBOUND
    if outbound:
        return DIRECTION_OUTBOUND
    return DIRECTION_OFF


def capabilities_for_direction(direction, supported):
    """Return the capabilities to grant for a chosen direction.

    Intersected with what the adapter supports, so choosing "Both" on a
    read-only provider grants the reads and silently grants no writes rather
    than recording a permission that cannot be exercised.
    """
    wanted = set()
    if direction in (DIRECTION_INBOUND, DIRECTION_BOTH):
        wanted.update(INBOUND_CAPABILITIES)
    if direction in (DIRECTION_OUTBOUND, DIRECTION_BOTH):
        wanted.update(OUTBOUND_CAPABILITIES)
    return sorted(wanted & set(supported))


def directions_for_choice(direction, capabilities):
    """Return the approved directions for a choice that granted these."""
    directions = []
    if any(capability in INBOUND_CAPABILITIES for capability in capabilities):
        directions.append(SyncDirection.INBOUND.value)
    if any(capability in OUTBOUND_CAPABILITIES for capability in capabilities):
        directions.append(SyncDirection.OUTBOUND.value)
    return directions


def _capability_rows(approved, supported):
    """Return one row per capability, saying plainly whether it is usable."""
    rows = []
    for capability, label in CAPABILITY_LABELS.items():
        is_supported = capability in supported
        rows.append(
            {
                "code": capability,
                "label": label,
                "approved": capability in approved,
                "supported": is_supported,
                # An approved capability the adapter cannot honour is the case
                # worth naming: it is the difference between "off" and
                # "unavailable", and only one of those is the user's choice.
                "unavailable": capability in approved and not is_supported,
            },
        )
    return rows


def binding_rows(user):
    """Return the synchronization view model for one user's connections."""
    from integrations.state.outbound import get_adapter

    rows = []
    for binding in SyncBinding.objects.filter(user=user).order_by("client_kind"):
        adapter = get_adapter(binding)
        supported = set(adapter.CAPABILITIES) if adapter is not None else set()
        approved = set(binding.approved_capabilities or [])

        rows.append(
            {
                "binding": binding,
                "id": binding.pk,
                "client_kind": binding.client_kind,
                "label": binding.label or binding.get_client_kind_display(),
                "status": binding.status,
                "is_operational": binding.is_operational(),
                "kill_switch": binding.kill_switch,
                "direction": current_direction(binding),
                "direction_label": DIRECTION_LABELS[current_direction(binding)],
                "direction_choices": DIRECTION_CHOICES,
                "capability_rows": _capability_rows(approved, supported),
                "has_adapter": adapter is not None,
                "can_write": bool(supported & set(OUTBOUND_CAPABILITIES)),
                "last_reconciled_at": binding.last_reconciled_at,
                "last_error_message": binding.last_error_message,
                "pending_deliveries": binding.deliveries.filter(
                    status=OutboundDeliveryStatus.PENDING.value,
                ).count(),
                "failed_deliveries": binding.deliveries.filter(
                    status=OutboundDeliveryStatus.FAILED.value,
                ).count(),
                "open_conflicts": binding.conflicts.filter(
                    status=StateConflictStatus.OPEN.value,
                ).count(),
            },
        )
    return rows


def open_conflicts(user):
    """Return the disagreements waiting for this user to settle."""
    from integrations.models import StateConflict

    return list(
        StateConflict.objects.filter(
            user=user,
            status=StateConflictStatus.OPEN.value,
        )
        .select_related("item", "binding")
        .order_by("-updated_at"),
    )
