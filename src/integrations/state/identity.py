"""Binding identity: who we are synchronizing with, and what they may do.

Identity is the part of synchronization that must not be clever. Every write to
someone's media server is authorized by a binding, so the rules here are
deliberately narrow: a binding is created pending, capabilities are granted
explicitly, and a change of profile revokes rather than adapts.
"""

import logging
import secrets

from django.db import transaction
from django.utils import timezone

from app.models import WatchStateSequence
from integrations.models import (
    SyncBinding,
    SyncBindingStatus,
)

logger = logging.getLogger(__name__)


def mint_origin_key(client_kind: str) -> str:
    """Return a stable opaque origin key for a new binding.

    Minted rather than derived from the instance and profile keys, because
    those are allowed to be narrowed later (an empty instance key filled in by
    the first payload that carries one). A derived key would change underneath
    every change and delivery already stamped with it, and the own-origin skip
    that prevents echo loops would stop recognising them.
    """
    return f"{client_kind}_{secrets.token_urlsafe(16)}"


def get_or_create_binding(
    user,
    client_kind,
    *,
    instance_key="",
    profile_key="",
    label="",
):
    """Return the binding for one external profile, creating it pending.

    A new binding can move nothing: it has no capabilities, no directions, and
    pending status. Granting those is a separate, explicit act.
    """
    binding, created = SyncBinding.objects.get_or_create(
        user=user,
        client_kind=client_kind,
        instance_key=instance_key,
        profile_key=profile_key,
        defaults={
            "origin_key": mint_origin_key(client_kind),
            "label": label,
            "status": SyncBindingStatus.PENDING.value,
            "approved_capabilities": [],
            "approved_directions": [],
        },
    )
    return binding, created


def narrow_instance_key(binding, instance_key):
    """Record the instance a binding turned out to point at.

    Filling in an empty instance key is a narrowing: we learned which server we
    were already talking to, and the user's approval still describes it. A
    change from one non-empty instance to another is not — that is a different
    server, so the binding stops until a person approves it again.
    """
    if not instance_key or binding.instance_key == instance_key:
        return binding

    if not binding.instance_key:
        binding.instance_key = instance_key
        binding.save(update_fields=["instance_key", "updated_at"])
        return binding

    logger.warning(
        "Sync binding %s changed instance (%s -> %s); pausing for reapproval",
        binding.pk,
        binding.instance_key,
        instance_key,
    )
    binding.status = SyncBindingStatus.NEEDS_REAPPROVAL.value
    binding.save(update_fields=["status", "updated_at"])
    return binding


def require_reapproval_on_profile_change(binding, profile_key):
    """Stop a binding whose remote profile changed.

    Unlike the instance key this is never narrowed silently, in either
    direction: writing another person's library is the exact failure the check
    exists to prevent.
    """
    if not profile_key or binding.profile_key == profile_key:
        return binding

    logger.warning(
        "Sync binding %s changed profile (%s -> %s); pausing for reapproval",
        binding.pk,
        binding.profile_key,
        profile_key,
    )
    binding.status = SyncBindingStatus.NEEDS_REAPPROVAL.value
    binding.save(update_fields=["status", "updated_at"])
    return binding


@transaction.atomic
def activate_binding(binding, *, capabilities, directions):
    """Approve a binding for exactly these capabilities and directions.

    Replaces rather than merges: re-approving with a smaller set is how a user
    withdraws permission, so a merge would make revocation impossible.

    Activation records approval only. It moves no state, emits no change and
    queues no delivery — establishing the baseline is the caller's next step,
    and a baseline that wrote would mean connecting a provider could rewrite a
    library before anyone saw a diff.
    """
    binding.approved_capabilities = sorted(set(capabilities))
    binding.approved_directions = sorted(set(directions))
    binding.status = SyncBindingStatus.ACTIVE.value
    binding.disabled_at = None
    binding.save(
        update_fields=[
            "approved_capabilities",
            "approved_directions",
            "status",
            "disabled_at",
            "updated_at",
        ],
    )
    _sync_emit_changes_flag(binding.user)
    return binding


@transaction.atomic
def deactivate_binding(binding):
    """Disable a binding without discarding what the user approved."""
    binding.status = SyncBindingStatus.DISABLED.value
    binding.disabled_at = timezone.now()
    binding.save(update_fields=["status", "disabled_at", "updated_at"])
    _sync_emit_changes_flag(binding.user)
    return binding


def _sync_emit_changes_flag(user):
    """Turn the user's local change log on while any binding is operational.

    The log exists to be delivered somewhere. A user with nothing connected
    should not accumulate one, and turning it off again when the last binding
    goes means an abandoned connection stops costing a write per save.
    """
    should_emit = any(
        binding.is_operational()
        for binding in SyncBinding.objects.filter(user=user)
    )
    sequence, _created = WatchStateSequence.objects.get_or_create(user=user)
    if sequence.emit_changes != should_emit:
        sequence.emit_changes = should_emit
        sequence.save(update_fields=["emit_changes"])


def operational_bindings(user, *, direction=None, capability=None):
    """Return the user's bindings that may act, optionally filtered."""
    bindings = [
        binding
        for binding in SyncBinding.objects.filter(user=user)
        if binding.is_operational()
    ]
    if direction is None and capability is None:
        return bindings
    return [
        binding
        for binding in bindings
        if binding.allows(direction, capability)
    ]
