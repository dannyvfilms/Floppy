"""The shared half of every service Floppy sends watch history to.

WeTrakr and SIMKL both work the same way from the user's side: sign in with a
device code, choose what Floppy sends and how often, optionally send the
existing library once, and disconnect. Only a few facts differ, such as the
login endpoints, which changes can be sent, and what the service calls an app
key. Those facts live in one ``PushDestination`` per service; everything else
(approval, pending logins, bindings, the settings card's data) is written once
here, so a third destination is a description plus an adapter, not a copy of
this file.

The ``api`` a destination points at is a module offering:

- ``client_id_for(user)``: the app key to log in with, or empty
- ``start_device_flow(client_id)``: ``{"device_code", "user_code",
  "verification_url", "interval", "expires_in"}``, or raise ``DeviceFlowError``
- ``poll_device_flow(client_id, device_code)``: ``(state, payload)`` where state
  is ``approved`` (payload: the token response), ``pending`` (payload: an
  optional ``{"interval": n}``) or ``failed`` (payload: a message)
- ``token_fields(tokens)``: account columns for a token response, encrypted
- ``logout(client_id, access_token, refresh_token)``: best-effort revoke
"""

import uuid
from dataclasses import dataclass, field
from datetime import timedelta

from cryptography.fernet import InvalidToken
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

from integrations.imports.helpers import decrypt, encrypt
from integrations.models import (
    OutboundDeliveryStatus,
    SyncBinding,
    SyncBindingStatus,
    SyncDeliverySchedule,
    SyncDirection,
)
from integrations.state import outbound
from integrations.state.adapters.base import AdapterError
from integrations.state.identity import (
    activate_binding,
    deactivate_binding,
    get_or_create_binding,
)

MIN_POLL_SECONDS = 3


@dataclass(frozen=True)
class PushDestination:
    """What differs between one service and the next."""

    slug: str
    label: str
    kind: str  # the SyncClientKind value
    instance_key: str
    account_model: type
    api: object  # the module described in the docstring above
    #: ``(form field, capability)`` pairs the settings card can switch on.
    sendable: tuple
    #: Capabilities that, alone, do not count as "sending" (for the export button).
    passive: frozenset = frozenset()
    #: Boolean account columns the settings card also saves, by form field.
    account_flags: tuple = ()
    #: Name of the Celery task that queues the existing library.
    export_task: str = ""
    #: Returns the counts the export button shows, for a bound user.
    preview: object = None
    #: Shown when no app key is configured; defaults to the usual wording.
    missing_key_message: str = ""
    extra: dict = field(default_factory=dict)

    # --- lookups -------------------------------------------------------------

    def account_for(self, user):
        """Return the user's account for this service, or None."""
        return self.account_model.objects.filter(user=user).first()

    def binding_for(self, account):
        """Return the binding a connected account is bound to, or None."""
        if account is None or not account.profile_key:
            return None
        return SyncBinding.objects.filter(
            user=account.user,
            client_kind=self.kind,
            profile_key=account.profile_key,
        ).first()

    def page_url(self, tab):
        """Return this service's provider page, opened on one tab."""
        return f"{reverse('provider_detail', args=[self.slug])}?tab={tab}"

    # --- what the settings card shows ---------------------------------------

    def status(self, user):
        """Return bounded connection and delivery state for the settings card."""
        account = self.account_for(user)
        binding = (
            self.binding_for(account) if account and account.is_connected else None
        )
        allows = lambda capability: bool(  # noqa: E731
            binding and binding.allows(SyncDirection.OUTBOUND.value, capability),
        )
        return {
            "slug": self.slug,
            "label": self.label,
            "account": account,
            "has_key": bool(self.api.client_id_for(user)),
            "binding": binding,
            "enabled": {name: allows(cap) for name, cap in self.sendable},
            "any_enabled": any(
                allows(cap) for name, cap in self.sendable if name not in self.passive
            ),
            "schedules": SyncDeliverySchedule.choices,
            "counts": dict(
                binding.deliveries.values_list("status").annotate(total=Count("pk")),
            )
            if binding
            else {},
            "recent": binding.deliveries.select_related("item").order_by(
                "-created_at",
            )[:10]
            if binding
            else [],
            "preview": self.preview(user) if binding and self.preview else {},
        }

    # --- changing state ------------------------------------------------------

    def stop_bindings(self, user):
        """Withdraw approval and retire waiting writes before changing accounts."""
        for binding in SyncBinding.objects.filter(user=user, client_kind=self.kind):
            deactivate_binding(binding)
            binding.deliveries.filter(
                status=OutboundDeliveryStatus.PENDING.value,
            ).update(status=OutboundDeliveryStatus.SKIPPED.value)

    def _clear_device_flow(self, account):
        """Forget a finished approval; drop the row if nothing was ever connected."""
        if account.refresh_token:
            self.account_model.objects.filter(pk=account.pk).update(
                device_code="",
                user_code="",
                verification_url="",
                device_expires_at=None,
            )
        else:
            account.delete()

    def _finish_connection(self, user, account, tokens):
        """Store the approved login and create the (still switched off) binding."""
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=user.pk)
            self.stop_bindings(user)
            profile_key = uuid.uuid4().hex
            self.account_model.objects.filter(pk=account.pk).update(
                profile_key=profile_key,
                device_code="",
                user_code="",
                verification_url="",
                device_expires_at=None,
                connection_broken=False,
                last_error_message="",
                last_failed_at=None,
                failure_count=0,
                **self.api.token_fields(tokens),
            )
            binding, _ = get_or_create_binding(
                user,
                self.kind,
                instance_key=self.instance_key,
                profile_key=profile_key,
                label=self.label,
            )
            binding.kill_switch = False
            binding.save(update_fields=["kill_switch", "updated_at"])

    # --- the views' work, written once --------------------------------------

    def connect(self, request):
        """Ask the service for a login code the user approves on its own site."""
        back = redirect(self.page_url("connection"))
        client_id = self.api.client_id_for(request.user)
        if not client_id:
            messages.error(
                request,
                self.missing_key_message
                or f"This instance has no {self.label} app key, so "
                f"{self.label} cannot be connected.",
            )
            return back
        existing = self.account_for(request.user)
        if existing is not None and existing.is_connected:
            messages.error(request, f"{self.label} is already connected.")
            return back
        try:
            flow = self.api.start_device_flow(client_id)
        except (self.api.DeviceFlowError, AdapterError) as error:
            messages.error(request, str(error))
            return back
        self.account_model.objects.update_or_create(
            user=request.user,
            defaults={
                "profile_key": existing.profile_key if existing else uuid.uuid4().hex,
                "client_id": client_id,
                "device_code": encrypt(flow["device_code"]),
                "user_code": flow["user_code"],
                "verification_url": flow["verification_url"],
                "device_interval": max(flow["interval"], MIN_POLL_SECONDS),
                "device_expires_at": timezone.now()
                + timedelta(seconds=flow["expires_in"]),
            },
        )
        return back

    def poll(self, request):
        """Check once whether the user has approved; the card calls this repeatedly."""
        account = self.account_for(request.user)
        if account is None or not account.is_pending:
            return JsonResponse({"state": "idle"})
        if account.device_expires_at and account.device_expires_at <= timezone.now():
            self._clear_device_flow(account)
            messages.error(request, "The code expired. Start again.")
            return JsonResponse({"state": "failed"})
        pace = max(account.device_interval, MIN_POLL_SECONDS)
        if not cache.add(f"{self.slug}_poll:{request.user.pk}", 1, timeout=pace - 1):
            return JsonResponse({"state": "pending", "interval": pace})
        try:
            state, payload = self.api.poll_device_flow(
                account.client_id,
                decrypt(account.device_code),
            )
        except AdapterError:
            return JsonResponse({"state": "pending", "interval": pace})
        if state == "approved":
            self._finish_connection(request.user, account, payload)
            messages.success(
                request,
                f"{self.label} connected. Choose what Floppy sends to it.",
            )
            return JsonResponse({"state": "approved"})
        if state == "failed":
            self._clear_device_flow(account)
            messages.error(request, payload)
            return JsonResponse({"state": "failed"})
        if payload and payload.get("interval"):
            pace = max(payload["interval"], pace)
            self.account_model.objects.filter(pk=account.pk).update(
                device_interval=pace,
            )
        return JsonResponse({"state": "pending", "interval": pace})

    def cancel(self, request):
        """Abandon a login code that has not been approved."""
        account = self.account_for(request.user)
        if account is not None and account.is_pending:
            self._clear_device_flow(account)
        return redirect(self.page_url("connection"))

    def save_settings(self, request):
        """Choose what is sent, and how soon. Nothing is sent that is switched off."""
        back = redirect(self.page_url("sync"))
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            account = self.account_for(request.user)
            binding = (
                self.binding_for(account) if account and account.is_connected else None
            )
            if binding is None:
                messages.error(request, f"Connect your {self.label} account first.")
                return back
            capabilities = [
                capability
                for name, capability in self.sendable
                if request.POST.get(name) == "on"
            ]
            if capabilities:
                activate_binding(
                    binding,
                    capabilities=capabilities,
                    directions=[SyncDirection.OUTBOUND.value],
                )
            else:
                self.stop_bindings(request.user)
            if self.account_flags:
                for name in self.account_flags:
                    setattr(account, name, request.POST.get(name) == "on")
                account.save(update_fields=[*self.account_flags, "updated_at"])
            schedule = request.POST.get("schedule", "")
            if schedule in SyncDeliverySchedule.values:
                outbound.set_delivery_schedule(binding, schedule)
        messages.success(request, f"Updated {self.label} sync.")
        return back

    def disconnect(self, request):
        """Stop locally first, then ask the service to end the login."""
        login = None
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            self.stop_bindings(request.user)
            account = self.account_for(request.user)
            if account is not None and account.refresh_token:
                try:
                    login = (
                        account.client_id,
                        decrypt(account.access_token),
                        decrypt(account.refresh_token),
                    )
                except InvalidToken:
                    login = None
            self.account_model.objects.filter(user=request.user).delete()
        if login is not None:
            try:
                self.api.logout(*login)
            except AdapterError:
                messages.warning(
                    request,
                    f"Disconnected locally. {self.label} could not confirm the logout.",
                )
        messages.success(request, f"{self.label} disconnected.")
        return redirect(self.page_url("connection"))

    def export_library(self, request):
        """Queue the user's existing library, only because they asked for it."""
        from integrations import tasks

        back = redirect(self.page_url("sync"))
        if not SyncBinding.objects.filter(
            user=request.user,
            client_kind=self.kind,
            status=SyncBindingStatus.ACTIVE.value,
            kill_switch=False,
        ).exists():
            messages.error(
                request,
                f"Switch on {self.label} sync before sending your library.",
            )
            return back
        getattr(tasks, self.export_task).delay(request.user.pk)
        messages.success(
            request,
            f"Sending queued. Results will appear under {self.label}.",
        )
        return back
