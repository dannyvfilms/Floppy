"""OAuth token exchange for Floppy's public device-flow clients."""

from __future__ import annotations

import json
from datetime import timedelta

from django.contrib.auth.decorators import login_not_required
from django.db import transaction
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from integrations.models import IntegrationToken
from integrations.oauth_models import (
    OAUTH_ACCESS_TOKEN_LIFETIME_SECONDS,
    OAUTH_DEVICE_CODE_GRANT,
    OAUTH_SUPPORTED_GRANT_TYPES,
    OAuthClient,
    OAuthDeviceAuthorization,
    OAuthRefreshToken,
    oauth_token_digest,
)
from integrations.oauth_revocation import revoke_refresh_token_family
from integrations.oauth_scope_info import normalise_scopes, serialise_scopes


def _no_store(response: JsonResponse) -> JsonResponse:
    response["Cache-Control"] = "no-store"
    response["Pragma"] = "no-cache"
    return response


def _oauth_error(error: str, description: str) -> JsonResponse:
    return _no_store(
        JsonResponse(
            {"error": error, "error_description": description},
            status=400,
        )
    )


def _request_data(request: HttpRequest) -> dict[str, object]:
    if request.content_type == "application/json":
        try:
            payload = json.loads(request.body or b"{}")
        except (TypeError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}
    return request.POST.dict()


def _token_response(
    *,
    raw_access_token: str,
    raw_refresh_token: str,
    scopes: list[str],
) -> JsonResponse:
    return _no_store(
        JsonResponse(
            {
                "access_token": raw_access_token,
                "token_type": "Bearer",
                "expires_in": OAUTH_ACCESS_TOKEN_LIFETIME_SECONDS,
                "refresh_token": raw_refresh_token,
                "scope": serialise_scopes(scopes),
            }
        )
    )


def _issue_token_pair(
    *,
    user,
    client: OAuthClient,
    scopes: list[str],
    rotated_from: OAuthRefreshToken | None = None,
) -> tuple[str, str]:
    access_token, raw_access_token = IntegrationToken.generate(
        user=user,
        name=f"{client.name} OAuth",
        client_identifier=client.client_id,
        scopes=scopes,
        expires_at=timezone.now()
        + timedelta(seconds=OAUTH_ACCESS_TOKEN_LIFETIME_SECONDS),
    )
    _refresh_token, raw_refresh_token = OAuthRefreshToken.generate(
        user=user,
        client=client,
        access_token=access_token,
        scopes=scopes,
        rotated_from=rotated_from,
    )
    return raw_access_token, raw_refresh_token


@login_not_required
@csrf_exempt
@require_POST
def oauth_token(request: HttpRequest) -> JsonResponse:
    """Exchange a device code or refresh token for scoped bearer credentials."""
    data = _request_data(request)
    client_id = str(data.get("client_id") or "").strip()
    grant_type = str(data.get("grant_type") or "").strip()

    if not client_id or not grant_type:
        return _oauth_error(
            "invalid_request",
            "client_id and grant_type are required.",
        )
    if grant_type not in OAUTH_SUPPORTED_GRANT_TYPES:
        return _oauth_error("unsupported_grant_type", "Grant type is not supported.")

    client = OAuthClient.objects.filter(client_id=client_id).first()
    if client is None or not client.is_active:
        return _oauth_error("invalid_client", "OAuth client is unknown or revoked.")
    if not client.allows_grant_type(grant_type):
        return _oauth_error(
            "unauthorized_client",
            "This client cannot use the requested grant type.",
        )

    if grant_type == OAUTH_DEVICE_CODE_GRANT:
        return _exchange_device_code(client, data)
    return _exchange_refresh_token(client, data)


def _exchange_device_code(
    client: OAuthClient,
    data: dict[str, object],
) -> JsonResponse:
    raw_device_code = str(data.get("device_code") or "")
    if not raw_device_code:
        return _oauth_error("invalid_request", "device_code is required.")

    now = timezone.now()
    with transaction.atomic():
        authorization = (
            OAuthDeviceAuthorization.objects.select_for_update()
            .select_related("user")
            .filter(
                client=client,
                device_code_digest=oauth_token_digest(raw_device_code),
            )
            .first()
        )
        if authorization is None:
            return _oauth_error("invalid_grant", "Device code is not valid.")
        if authorization.consumed_at is not None:
            return _oauth_error("invalid_grant", "Device code has already been used.")
        if now >= authorization.expires_at:
            return _oauth_error("expired_token", "Device code has expired.")
        if authorization.denied_at is not None:
            return _oauth_error("access_denied", "The user denied this request.")

        if authorization.last_polled_at is not None:
            elapsed = (now - authorization.last_polled_at).total_seconds()
            if elapsed < authorization.interval:
                authorization.interval += 5
                authorization.last_polled_at = now
                authorization.save(update_fields=["interval", "last_polled_at"])
                return _oauth_error(
                    "slow_down",
                    "The client is polling faster than the permitted interval.",
                )

        authorization.last_polled_at = now
        authorization.save(update_fields=["last_polled_at"])

        if authorization.approved_at is None or authorization.user is None:
            return _oauth_error(
                "authorization_pending",
                "The user has not yet completed authorisation.",
            )

        scopes = list(authorization.requested_scopes)
        raw_access_token, raw_refresh_token = _issue_token_pair(
            user=authorization.user,
            client=client,
            scopes=scopes,
        )
        authorization.consumed_at = now
        authorization.save(update_fields=["consumed_at"])

    return _token_response(
        raw_access_token=raw_access_token,
        raw_refresh_token=raw_refresh_token,
        scopes=scopes,
    )


def _exchange_refresh_token(
    client: OAuthClient,
    data: dict[str, object],
) -> JsonResponse:
    raw_refresh_token = str(data.get("refresh_token") or "")
    if not raw_refresh_token:
        return _oauth_error("invalid_request", "refresh_token is required.")

    with transaction.atomic():
        refresh_token = (
            OAuthRefreshToken.objects.select_for_update()
            .select_related("user")
            .filter(
                client=client,
                token_digest=oauth_token_digest(raw_refresh_token),
            )
            .first()
        )
        if refresh_token is None:
            return _oauth_error("invalid_grant", "Refresh token is not valid.")
        if refresh_token.revoked_at is not None:
            if refresh_token.replaced_by_id is not None:
                revoke_refresh_token_family(refresh_token)
            return _oauth_error("invalid_grant", "Refresh token is not valid.")
        if not refresh_token.is_valid:
            return _oauth_error("invalid_grant", "Refresh token is not valid.")

        if "scope" in data:
            scopes = normalise_scopes(data.get("scope"))
            if not scopes:
                return _oauth_error(
                    "invalid_scope",
                    "A supplied scope parameter cannot be empty.",
                )
        else:
            scopes = list(refresh_token.scopes)

        if any(scope not in refresh_token.scopes for scope in scopes) or any(
            not client.allows_scope(scope) for scope in scopes
        ):
            return _oauth_error(
                "invalid_scope",
                "A refresh exchange cannot broaden the original permissions.",
            )

        refresh_token.revoked_at = timezone.now()
        refresh_token.save(update_fields=["revoked_at"])
        raw_access_token, new_raw_refresh_token = _issue_token_pair(
            user=refresh_token.user,
            client=client,
            scopes=scopes,
            rotated_from=refresh_token,
        )

    return _token_response(
        raw_access_token=raw_access_token,
        raw_refresh_token=new_raw_refresh_token,
        scopes=scopes,
    )
