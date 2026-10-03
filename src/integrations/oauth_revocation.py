"""OAuth token and connected-application revocation helpers."""

from __future__ import annotations

import json

from django.contrib.auth.decorators import login_not_required
from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from integrations.models import IntegrationToken
from integrations.oauth_models import OAuthClient, OAuthRefreshToken, oauth_token_digest


def _no_store(response: JsonResponse) -> JsonResponse:
    response["Cache-Control"] = "no-store"
    response["Pragma"] = "no-cache"
    return response


def _request_data(request: HttpRequest) -> dict[str, object]:
    if request.content_type == "application/json":
        try:
            payload = json.loads(request.body or b"{}")
        except (TypeError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}
    return request.POST.dict()


def revoke_refresh_token_family(
    refresh_token: OAuthRefreshToken,
    *,
    revoked_at=None,
) -> None:
    """Revoke every refresh and access token in one rotation lineage."""
    now = revoked_at or timezone.now()
    pending = {refresh_token.pk}
    refresh_token_ids = set()
    access_token_ids = set()

    with transaction.atomic():
        while pending:
            token_id = pending.pop()
            if token_id in refresh_token_ids:
                continue

            current = (
                OAuthRefreshToken.objects.select_for_update()
                .filter(pk=token_id)
                .values("id", "access_token_id", "replaced_by_id")
                .first()
            )
            if current is None:
                continue

            refresh_token_ids.add(current["id"])
            if current["access_token_id"] is not None:
                access_token_ids.add(current["access_token_id"])
            if current["replaced_by_id"] is not None:
                pending.add(current["replaced_by_id"])

            pending.update(
                OAuthRefreshToken.objects.select_for_update()
                .filter(replaced_by_id=current["id"])
                .values_list("id", flat=True)
            )

        OAuthRefreshToken.objects.filter(
            pk__in=refresh_token_ids,
            revoked_at__isnull=True,
        ).update(revoked_at=now)
        IntegrationToken.objects.filter(
            pk__in=access_token_ids,
            revoked_at__isnull=True,
        ).update(revoked_at=now)


def revoke_user_client_tokens(*, user, client: OAuthClient) -> None:
    """Revoke every live OAuth credential for one user/client pairing."""
    now = timezone.now()
    refresh_tokens = OAuthRefreshToken.objects.filter(
        user=user,
        client=client,
        revoked_at__isnull=True,
    )
    access_token_ids = list(
        refresh_tokens.exclude(access_token_id=None).values_list(
            "access_token_id",
            flat=True,
        )
    )
    refresh_tokens.update(revoked_at=now)

    IntegrationToken.objects.filter(
        Q(pk__in=access_token_ids)
        | Q(user=user, client_identifier=client.client_id),
        revoked_at__isnull=True,
    ).update(revoked_at=now)


@login_not_required
@csrf_exempt
@require_POST
def oauth_revoke(request: HttpRequest) -> JsonResponse:
    """Revoke an OAuth access or refresh token without revealing token state."""
    data = _request_data(request)
    client_id = str(data.get("client_id") or "").strip()
    raw_token = str(data.get("token") or "")

    if not client_id or not raw_token:
        return _no_store(
            JsonResponse(
                {
                    "error": "invalid_request",
                    "error_description": "client_id and token are required.",
                },
                status=400,
            )
        )

    client = OAuthClient.objects.filter(client_id=client_id).first()
    if client is None:
        return _no_store(
            JsonResponse(
                {
                    "error": "invalid_client",
                    "error_description": "OAuth client is unknown.",
                },
                status=400,
            )
        )

    digest = oauth_token_digest(raw_token)
    now = timezone.now()

    with transaction.atomic():
        refresh_token = (
            OAuthRefreshToken.objects.select_for_update()
            .filter(client=client, token_digest=digest)
            .first()
        )
        if refresh_token is not None:
            revoke_refresh_token_family(refresh_token)
        else:
            IntegrationToken.objects.filter(
                client_identifier=client.client_id,
                token_digest=digest,
                revoked_at__isnull=True,
            ).update(revoked_at=now)

    return _no_store(JsonResponse({}))
