"""User-facing lifecycle actions for named integration tokens."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from integrations.models import IntegrationToken


@login_required
@require_POST
def delete_integration_token(request, token_id):
    """Permanently remove one revoked, user-created app token.

    Revocation remains the security boundary: an active credential must be
    revoked before it can be deleted. Event receipts are detached first so
    deleting the credential record does not erase idempotency/history data.
    OAuth-issued access tokens use their own Connected Applications lifecycle
    and are deliberately excluded from this endpoint.
    """
    with transaction.atomic():
        token = get_object_or_404(
            IntegrationToken.objects.select_for_update(),
            pk=token_id,
            user=request.user,
            revoked_at__isnull=False,
            client_identifier="",
        )
        token_name = token.name
        token.event_receipts.update(token=None)
        token.delete()

    messages.success(request, f"Deleted revoked token '{token_name}'.")
    return redirect("integrations")
