"""OAuth 2.0 Device Authorization Grant endpoints and approval UI."""

from __future__ import annotations

import json
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.decorators import login_not_required, login_required
from django.core.cache import cache
from django.http import HttpRequest, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

from integrations.models import DEFAULT_INTEGRATION_SCOPES
from integrations.oauth_models import (
    OAUTH_DEVICE_CODE_GRANT,
    OAUTH_DEVICE_CODE_LIFETIME_SECONDS,
    OAuthClient,
    OAuthDeviceAuthorization,
)
from integrations.oauth_scope_info import normalise_scopes, scope_details

DEVICE_AUTHORIZATION_LIMIT = 10
DEVICE_AUTHORIZATION_WINDOW_SECONDS = 60
CLIENT_NAME_MAX_LENGTH = 60


def _rate_limited(request: HttpRequest, bucket: str) -> bool:
    """Count this caller's requests to one endpoint in the current minute window."""
    # Same trusted header allauth uses; it is only set in production, where
    # nginx overwrites it, so a caller cannot choose their own bucket.
    header = getattr(settings, "ALLAUTH_TRUSTED_CLIENT_IP_HEADER", None)
    forwarded = header and request.META.get("HTTP_" + header.upper().replace("-", "_"))
    caller = forwarded or request.META.get("REMOTE_ADDR", "")
    key = f"{bucket}:{caller}"
    cache.add(key, 0, timeout=DEVICE_AUTHORIZATION_WINDOW_SECONDS)
    try:
        return cache.incr(key) > DEVICE_AUTHORIZATION_LIMIT
    except ValueError:  # the key expired between add and incr
        return False


def _no_store(response: JsonResponse) -> JsonResponse:
    response["Cache-Control"] = "no-store"
    response["Pragma"] = "no-cache"
    return response


def _oauth_error(
    error: str,
    description: str,
    *,
    status: int = 400,
) -> JsonResponse:
    return _no_store(
        JsonResponse(
            {"error": error, "error_description": description},
            status=status,
        )
    )


def _too_many_requests(description: str) -> JsonResponse:
    response = _oauth_error("slow_down", description, status=429)
    response["Retry-After"] = str(DEVICE_AUTHORIZATION_WINDOW_SECONDS)
    return response


def _request_data(request: HttpRequest) -> dict[str, object]:
    if request.content_type == "application/json":
        try:
            payload = json.loads(request.body or b"{}")
        except (TypeError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}
    return request.POST.dict()


@login_not_required
@csrf_exempt
@require_POST
def oauth_register(request: HttpRequest) -> JsonResponse:
    """Let an app introduce itself and receive a client ID (RFC 7591 style).

    Every client made here is unverified: the approval page says so and shows
    the name the app chose, so a user can refuse a name they do not recognise.
    """
    if _rate_limited(request, "oauth_register"):
        return _too_many_requests("Too many registrations. Try again in a minute.")

    data = _request_data(request)
    name = " ".join(str(data.get("client_name") or "").split())
    name = "".join(char for char in name if char.isprintable())
    if not name:
        return _oauth_error("invalid_client_metadata", "client_name is required.")
    if len(name) > CLIENT_NAME_MAX_LENGTH:
        return _oauth_error(
            "invalid_client_metadata",
            f"client_name must be at most {CLIENT_NAME_MAX_LENGTH} characters.",
        )

    OAuthClient.delete_unused()
    client = OAuthClient.register_public_client(name=name)
    return _no_store(
        JsonResponse(
            {
                "client_id": client.client_id,
                "client_name": client.name,
                "grant_types": client.grant_types,
                "token_endpoint_auth_method": "none",
            },
            status=201,
        )
    )


@login_not_required
@csrf_exempt
@require_POST
def oauth_device_authorization(request: HttpRequest) -> JsonResponse:
    """Issue short-lived device and user codes for a registered public client."""
    if _rate_limited(request, "oauth_device_authorization"):
        return _too_many_requests("Too many device code requests. Try again in a minute.")

    data = _request_data(request)
    client_id = str(data.get("client_id") or "").strip()
    if not client_id:
        return _oauth_error("invalid_request", "client_id is required.")

    client = OAuthClient.objects.filter(client_id=client_id).first()
    if client is None or not client.is_active:
        return _oauth_error("invalid_client", "OAuth client is unknown or revoked.")
    if not client.allows_grant_type(OAUTH_DEVICE_CODE_GRANT):
        return _oauth_error(
            "unauthorized_client",
            "This client cannot use the device authorization grant.",
        )

    # A client that names no scope gets the tracking preset, not everything
    # it is allowed: broader scopes such as lists:write must be asked for.
    requested_scopes = normalise_scopes(
        data.get("scope"),
        default=[
            scope
            for scope in DEFAULT_INTEGRATION_SCOPES
            if scope in client.allowed_scopes
        ],
    )
    if not requested_scopes:
        return _oauth_error("invalid_scope", "At least one scope is required.")
    if any(not client.allows_scope(scope) for scope in requested_scopes):
        return _oauth_error(
            "invalid_scope",
            "One or more requested scopes are not allowed for this client.",
        )

    authorization, raw_device_code, user_code = OAuthDeviceAuthorization.issue(
        client=client,
        requested_scopes=requested_scopes,
    )
    verification_uri = request.build_absolute_uri(reverse("oauth_device"))
    verification_uri_complete = (
        f"{verification_uri}?{urlencode({'user_code': user_code})}"
    )

    return _no_store(
        JsonResponse(
            {
                "device_code": raw_device_code,
                "user_code": user_code,
                "verification_uri": verification_uri,
                "verification_uri_complete": verification_uri_complete,
                "expires_in": OAUTH_DEVICE_CODE_LIFETIME_SECONDS,
                "interval": authorization.interval,
            }
        )
    )


@login_required
@require_http_methods(["GET", "POST"])
def oauth_device(request: HttpRequest):
    """Let an authenticated user approve or deny a device authorisation."""
    user_code = (
        request.POST.get("user_code")
        if request.method == "POST"
        else request.GET.get("user_code")
    )
    user_code = (user_code or "").strip()
    authorization = (
        OAuthDeviceAuthorization.for_user_code(user_code) if user_code else None
    )

    context: dict[str, object] = {
        "user_code": user_code,
        "authorization": authorization,
        "scope_details": (
            scope_details(authorization.requested_scopes) if authorization else []
        ),
    }

    if user_code and authorization is None:
        context["error"] = "That device code is not valid."
    elif authorization is not None and authorization.is_expired:
        context["error"] = "That device code has expired."
    elif authorization is not None and not authorization.client.is_active:
        context["error"] = "That application registration has been revoked."
    elif authorization is not None and authorization.consumed_at is not None:
        context["error"] = "That device code has already been used."
    elif request.method == "POST" and authorization is not None:
        action = request.POST.get("action")
        try:
            if action == "approve":
                authorization.approve(request.user)
                context["success"] = "Application authorised."
            elif action == "deny":
                authorization.deny(request.user)
                context["success"] = "Application denied."
            else:
                context["error"] = "Choose whether to approve or deny this application."
        except ValueError as exc:
            context["error"] = str(exc)

    return render(request, "integrations/oauth_device.html", context)
