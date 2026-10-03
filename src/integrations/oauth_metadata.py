"""OAuth authorisation-server and scope metadata endpoints."""

from __future__ import annotations

from django.contrib.auth.decorators import login_not_required
from django.http import HttpRequest, JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_GET

from integrations.oauth_models import OAUTH_SUPPORTED_GRANT_TYPES
from integrations.oauth_scope_info import OAUTH_SCOPE_OPTIONS


def _no_store(response: JsonResponse) -> JsonResponse:
    response["Cache-Control"] = "no-store"
    response["Pragma"] = "no-cache"
    return response


@login_not_required
@require_GET
def oauth_authorization_server_metadata(request: HttpRequest) -> JsonResponse:
    """Publish the endpoints and capabilities needed by public OAuth clients."""
    issuer = request.build_absolute_uri("/").rstrip("/")
    return _no_store(
        JsonResponse(
            {
                "issuer": issuer,
                "device_authorization_endpoint": request.build_absolute_uri(
                    reverse("oauth_device_authorization")
                ),
                "token_endpoint": request.build_absolute_uri(reverse("oauth_token")),
                "revocation_endpoint": request.build_absolute_uri(
                    reverse("oauth_revoke")
                ),
                "grant_types_supported": list(OAUTH_SUPPORTED_GRANT_TYPES),
                "token_endpoint_auth_methods_supported": ["none"],
                "scopes_supported": [
                    scope for scope, _label, _description in OAUTH_SCOPE_OPTIONS
                ],
            }
        )
    )


@login_not_required
@require_GET
def oauth_scope_metadata(_request: HttpRequest) -> JsonResponse:
    """Publish human-readable metadata for Floppy's supported OAuth scopes."""
    return _no_store(
        JsonResponse(
            {
                "scopes": [
                    {
                        "scope": scope,
                        "label": label,
                        "description": description,
                    }
                    for scope, label, description in OAUTH_SCOPE_OPTIONS
                ]
            }
        )
    )
