"""User-facing management for OAuth connected applications."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from integrations.models import IntegrationToken
from integrations.oauth_models import OAuthClient, OAuthRefreshToken
from integrations.oauth_revocation import revoke_user_client_tokens
from integrations.oauth_scope_info import scope_details

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse


@login_required
@require_GET
def oauth_applications(request: HttpRequest) -> HttpResponse:
    """Render applications that currently hold usable OAuth credentials."""
    now = timezone.now()
    access_tokens = list(
        IntegrationToken.objects.filter(
            user=request.user,
            client_identifier__startswith="flp_oauth_",
            revoked_at__isnull=True,
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .order_by("-created_at")
    )
    refresh_tokens = list(
        OAuthRefreshToken.objects.select_related("client")
        .filter(
            user=request.user,
            revoked_at__isnull=True,
            expires_at__gt=now,
        )
        .order_by("-created_at")
    )

    client_ids = {token.client_identifier for token in access_tokens}
    client_ids.update(token.client.client_id for token in refresh_tokens)
    clients = {
        client.client_id: client
        for client in OAuthClient.objects.filter(client_id__in=client_ids)
    }

    applications = []
    for client_id in sorted(clients, key=lambda value: clients[value].name.lower()):
        client = clients[client_id]
        client_access_tokens = [
            token for token in access_tokens if token.client_identifier == client_id
        ]
        client_refresh_tokens = [
            token for token in refresh_tokens if token.client_id == client.pk
        ]
        scopes = sorted(
            {
                scope
                for token in (*client_access_tokens, *client_refresh_tokens)
                for scope in token.scopes
            }
        )
        created_dates = [
            token.created_at
            for token in (*client_access_tokens, *client_refresh_tokens)
        ]
        last_used_dates = [
            token.last_used_at
            for token in client_access_tokens
            if token.last_used_at is not None
        ]
        applications.append(
            {
                "client": client,
                "scope_details": scope_details(scopes),
                "connected_at": min(created_dates) if created_dates else None,
                "last_used_at": max(last_used_dates) if last_used_dates else None,
            }
        )

    return render(
        request,
        "integrations/oauth_applications.html",
        {"oauth_applications": applications},
    )


@login_required
@require_POST
def oauth_revoke_application(request: HttpRequest, client_id: str) -> HttpResponse:
    """Revoke every OAuth credential issued to one application for this user."""
    client = get_object_or_404(OAuthClient, client_id=client_id)
    revoke_user_client_tokens(user=request.user, client=client)
    messages.success(request, f"Access for '{client.name}' revoked.")
    return redirect("oauth_applications")
