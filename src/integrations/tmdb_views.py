"""Connect a personal TMDb account and approve rating-only outbound sync."""

import secrets
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET, require_POST

from integrations.imports.helpers import encrypt
from integrations.models import (
    CAPABILITY_RATING_PUSH,
    OutboundDeliveryStatus,
    SyncBinding,
    SyncBindingStatus,
    SyncClientKind,
    SyncDirection,
    TMDbAccount,
)
from integrations.state.adapters.base import AdapterError
from integrations.state.identity import (
    activate_binding,
    deactivate_binding,
    get_or_create_binding,
)
from integrations.tmdb_api import TMDbClient


def rating_sync_status(user):
    """Return bounded connection and delivery results for the settings card."""
    account = TMDbAccount.objects.filter(user=user).first()
    binding = SyncBinding.objects.filter(
        user=user,
        client_kind=SyncClientKind.TMDB.value,
        profile_key=account.account_id if account else "",
    ).first()
    return {
        "account": account,
        "enabled": bool(
            binding
            and binding.allows(SyncDirection.OUTBOUND.value, CAPABILITY_RATING_PUSH)
        ),
        "counts": dict(
            binding.deliveries.values_list("status").annotate(total=Count("pk"))
        )
        if binding
        else {},
        "recent": binding.deliveries.select_related("item").order_by("-created_at")[:10]
        if binding
        else [],
    }


def _stop_bindings(user):
    """Withdraw approval and retire pending writes before changing accounts."""
    bindings = SyncBinding.objects.filter(
        user=user, client_kind=SyncClientKind.TMDB.value
    )
    for binding in bindings:
        deactivate_binding(binding)
        binding.deliveries.filter(status=OutboundDeliveryStatus.PENDING.value).update(
            status=OutboundDeliveryStatus.SKIPPED.value,
        )


@login_required
@require_POST
def tmdb_connect(request):
    """Start TMDb's approved-token flow from the authenticated user's session."""
    try:
        data = TMDbClient(request.user).request("GET", "authentication/token/new")
        token = data.get("request_token")
        raw_expiry = data.get("expires_at")
        try:
            expires = (
                parse_datetime(raw_expiry.replace(" UTC", "+00:00"))
                if isinstance(raw_expiry, str)
                else None
            )
        except ValueError:
            expires = None
        if not isinstance(token, str) or not token or expires is None:
            messages.error(request, "TMDb returned an invalid authorization token.")
            return redirect("integrations")
        if timezone.is_naive(expires):
            expires = timezone.make_aware(
                expires, timezone=timezone.get_fixed_timezone(0)
            )
        if expires <= timezone.now():
            messages.error(
                request, "TMDb returned an expired authorization token. Try again."
            )
            return redirect("integrations")
        request.session["tmdb_auth"] = {
            "request_token": token,
            "expires_at": expires.timestamp(),
            "user_id": request.user.pk,
        }
    except AdapterError as error:
        messages.error(request, str(error))
        return redirect("integrations")
    callback = request.build_absolute_uri(reverse("tmdb_callback"))
    return redirect(
        f"https://www.themoviedb.org/authenticate/{token}?{urlencode({'redirect_to': callback})}"
    )


@login_required
@require_GET
def tmdb_callback(request):
    """Exchange only the token issued for this authenticated browser session."""
    expected = request.session.pop("tmdb_auth", None)
    token = request.GET.get("request_token", "")
    if (
        not expected
        or expected.get("user_id") != request.user.pk
        or expected.get("expires_at", 0) <= timezone.now().timestamp()
        or not secrets.compare_digest(
            token.encode(),
            expected.get("request_token", "").encode(),
        )
        or request.GET.get("approved") != "true"
    ):
        messages.error(
            request,
            "TMDb authorization was denied, expired or did not match this session.",
        )
        return redirect("integrations")
    client = TMDbClient(request.user)
    try:
        result = client.request(
            "POST", "authentication/session/new", json={"request_token": token}
        )
        session_id = result.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            messages.error(request, "TMDb returned an invalid session.")
            return redirect("integrations")
        client.session_id = session_id
        account = client.request("GET", "account")
        if not isinstance(account.get("id"), int) or account["id"] <= 0:
            messages.error(request, "TMDb could not verify the account identity.")
            return redirect("integrations")
    except AdapterError as error:
        messages.error(request, str(error))
        return redirect("integrations")
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=request.user.pk)
        _stop_bindings(request.user)
        TMDbAccount.objects.update_or_create(
            user=request.user,
            defaults={
                "account_id": str(account["id"]),
                "username": account.get("username", ""),
                "session_id": encrypt(session_id),
                "connection_broken": False,
                "last_error_message": "",
                "failure_count": 0,
                "last_failed_at": None,
            },
        )
        binding, _ = get_or_create_binding(
            request.user,
            SyncClientKind.TMDB.value,
            instance_key="themoviedb.org",
            profile_key=str(account["id"]),
            label="TMDb ratings",
        )
        binding.kill_switch = False
        binding.save(update_fields=["kill_switch", "updated_at"])
    messages.success(
        request, "TMDb connected. Enable rating sync to send future rating edits."
    )
    return redirect("integrations")


@login_required
@require_POST
def tmdb_settings(request):
    """Explicitly enable or disable future rating edits, without a backfill."""
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=request.user.pk)
        account = TMDbAccount.objects.filter(user=request.user).first()
        if account is None:
            messages.error(request, "Connect your TMDb account first.")
            return redirect("integrations")
        binding = SyncBinding.objects.select_for_update().get(
            user=request.user,
            client_kind=SyncClientKind.TMDB.value,
            instance_key="themoviedb.org",
            profile_key=account.account_id,
        )
        if request.POST.get("enabled") == "on":
            activate_binding(
                binding,
                capabilities=[CAPABILITY_RATING_PUSH],
                directions=[SyncDirection.OUTBOUND.value],
            )
        else:
            _stop_bindings(request.user)
    messages.success(request, "Updated TMDb rating sync.")
    return redirect("integrations")


@login_required
@require_POST
def tmdb_disconnect(request):
    """Stop locally before attempting remote session revocation."""
    from cryptography.fernet import InvalidToken

    from integrations.imports.helpers import decrypt

    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=request.user.pk)
        _stop_bindings(request.user)
        account = TMDbAccount.objects.filter(user=request.user).first()
        session_id = account.session_id if account else ""
        TMDbAccount.objects.filter(user=request.user).delete()
        request.session.pop("tmdb_auth", None)
    if session_id:
        try:
            TMDbClient(request.user).request(
                "DELETE",
                "authentication/session",
                json={"session_id": decrypt(session_id)},
            )
        except (AdapterError, InvalidToken):
            messages.warning(
                request,
                "Disconnected locally. TMDb session revocation could not be confirmed.",
            )
    messages.success(request, "TMDb disconnected.")
    return redirect("integrations")


@login_required
@require_POST
def tmdb_export_ratings(request):
    """Request an explicit export through the same approved delivery engine."""
    from integrations.tasks import export_tmdb_ratings

    if not SyncBinding.objects.filter(
        user=request.user,
        client_kind=SyncClientKind.TMDB.value,
        status=SyncBindingStatus.ACTIVE.value,
        kill_switch=False,
    ).exists():
        messages.error(request, "Enable TMDb rating sync before exporting.")
        return redirect("integrations")
    export_tmdb_ratings.delay(request.user.pk)
    messages.success(
        request, "Export queued. Delivery results will appear in TMDb ratings."
    )
    return redirect("integrations")
