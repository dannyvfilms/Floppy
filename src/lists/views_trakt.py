"""
Views for the Trakt OAuth import flow.

Covers: storing Trakt client credentials, initiating the OAuth authorization,
and handling the OAuth callback to kick off the async list-import task.
"""

import logging
import secrets
from datetime import timedelta
from http import HTTPStatus

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET, require_POST

from app import helpers as app_helpers
from integrations.imports import helpers as import_helpers
from integrations.imports import trakt as trakt_imports
from integrations.models import TraktAccount
from lists import tasks as list_tasks
from lists.views_helpers import _get_trakt_credentials

logger = logging.getLogger(__name__)
TRAKT_LISTS_DEVICE_SESSION_KEY = "trakt_lists_device_auth"


@login_required
@require_POST
def trakt_lists_credentials(request):
    """Store Trakt client credentials for list imports."""
    client_id = request.POST.get("client_id", "").strip()
    client_secret = request.POST.get("client_secret", "").strip()

    if not client_id:
        messages.error(request, "Trakt client ID is required.")
        return redirect("lists")

    try:
        TraktAccount.objects.update_or_create(
            user=request.user,
            defaults={
                "client_id": import_helpers.encrypt(client_id),
                "client_secret": (
                    import_helpers.encrypt(client_secret) if client_secret else None
                ),
            },
        )
    except Exception:
        logger.exception(
            "Failed to store Trakt credentials for user %s", request.user.username
        )
        messages.error(request, "Failed to save Trakt credentials. Please try again.")
        return redirect("lists")

    messages.success(request, "Trakt credentials saved. You can now authorize Trakt.")
    return redirect("lists")


@login_required
@require_POST
def trakt_lists_oauth(request):
    """Start the Trakt OAuth flow for list imports."""
    redirect_uri = request.build_absolute_uri(reverse("trakt_lists_callback"))
    credentials = _get_trakt_credentials(request.user)
    if not credentials:
        messages.error(
            request, "Add your Trakt client ID before authorizing."
        )
        return redirect("lists")

    client_id, client_secret = credentials

    if not app_helpers.supports_oauth_redirect(redirect_uri):
        # Trakt refuses non-HTTPS callbacks, so fall back to the device code
        # flow, which needs no redirect URI at all (#681).
        return _start_trakt_lists_device_flow(request, client_id)

    state_token = secrets.token_urlsafe(32)
    state = {"source": "trakt_lists"}

    # Build query string manually to match the working trakt_oauth pattern
    # This ensures the redirect_uri is sent exactly as registered
    url = "https://trakt.tv/oauth/authorize"
    logger.debug("Trakt OAuth redirect URI: %s", redirect_uri)
    query = (
        f"client_id={client_id}&redirect_uri={redirect_uri}"
        f"&response_type=code&state={state_token}"
    )
    if not client_secret:
        # An app without a client secret authorizes with PKCE instead.
        state["code_verifier"], code_challenge = trakt_imports.new_pkce_pair()
        query += f"&code_challenge={code_challenge}&code_challenge_method=S256"

    request.session[state_token] = state
    request.session.modified = True
    return redirect(f"{url}?{query}")


def _start_trakt_lists_device_flow(request, client_id):
    """Mint a Trakt device code for the list import and show the code screen."""
    try:
        device = trakt_imports.request_device_code(client_id=client_id)
    except import_helpers.MediaImportError as error:
        messages.error(request, str(error))
        return redirect("lists")

    # The client secret stays out of the session; the poll view re-reads it.
    request.session[TRAKT_LISTS_DEVICE_SESSION_KEY] = {
        "device_code": device["device_code"],
        "user_code": device["user_code"],
        "verification_url": device["verification_url"],
        "interval": device["interval"],
        "expires_at": (
            timezone.now() + timedelta(seconds=int(device["expires_in"]))
        ).isoformat(),
    }
    return redirect("trakt_lists_device_verify")


def _trakt_lists_device_state(request):
    """Return the pending device authorization, or None if gone or expired."""
    state = request.session.get(TRAKT_LISTS_DEVICE_SESSION_KEY)
    if not isinstance(state, dict):
        return None
    expires_at = parse_datetime(state.get("expires_at") or "")
    if expires_at is None or timezone.now() >= expires_at:
        return None
    return state


@login_required
@require_GET
def trakt_lists_device_verify(request):
    """Show the Trakt device code for the list import."""
    state = _trakt_lists_device_state(request)
    if state is None:
        request.session.pop(TRAKT_LISTS_DEVICE_SESSION_KEY, None)
        messages.error(request, "The Trakt authorization code expired. Start again.")
        return redirect("lists")

    return render(
        request,
        "integrations/trakt_device_code.html",
        {
            "user_code": state["user_code"],
            "verification_url": state["verification_url"],
            "interval": state["interval"],
            "poll_url": reverse("trakt_lists_device_poll"),
            "cancel_url": reverse("lists"),
        },
    )


def _lists_htmx_redirect():
    """Tell HTMX to navigate back to the lists page without swapping."""
    return HttpResponse(
        status=HTTPStatus.NO_CONTENT,
        headers={"HX-Redirect": reverse("lists")},
    )


@login_required
@require_GET
def trakt_lists_device_poll(request):
    """Poll Trakt once for the pending list-import device authorization."""
    state = _trakt_lists_device_state(request)
    if state is None:
        request.session.pop(TRAKT_LISTS_DEVICE_SESSION_KEY, None)
        messages.error(request, "The Trakt authorization code expired. Start again.")
        return _lists_htmx_redirect()

    credentials = _get_trakt_credentials(request.user)
    if not credentials:
        request.session.pop(TRAKT_LISTS_DEVICE_SESSION_KEY, None)
        messages.error(
            request, "Trakt credentials are missing. Please add them and try again."
        )
        return _lists_htmx_redirect()

    client_id, client_secret = credentials

    try:
        result = trakt_imports.poll_device_token(
            state["device_code"],
            client_id=client_id,
            client_secret=client_secret,
        )
    except import_helpers.MediaImportError as error:
        request.session.pop(TRAKT_LISTS_DEVICE_SESSION_KEY, None)
        messages.error(request, str(error))
        return _lists_htmx_redirect()

    if result is None:
        return HttpResponse(status=HTTPStatus.NO_CONTENT)

    request.session.pop(TRAKT_LISTS_DEVICE_SESSION_KEY, None)
    list_tasks.import_trakt_lists_task.delay(
        request.user.id,
        result["access_token"],
        client_id=client_id,
    )
    messages.info(
        request,
        "Trakt authorization successful. Your lists are being imported in the background.",
    )
    return _lists_htmx_redirect()


@login_required
@require_GET
def trakt_lists_callback(request):
    """Handle Trakt OAuth callback and import lists."""
    state_token = request.GET.get("state")

    if not state_token:
        logger.error("Trakt OAuth callback missing state parameter")
        messages.error(
            request, "Invalid Trakt authorization request. Missing state parameter."
        )
        return redirect("lists")

    state_data = request.session.pop(state_token, None)

    if not state_data:
        logger.error(
            "Trakt OAuth callback state not found in session",
        )
        messages.error(
            request,
            "Invalid or expired Trakt authorization request. Please try again - make sure to complete the authorization process without closing your browser.",
        )
        return redirect("lists")

    credentials = _get_trakt_credentials(request.user)
    if not credentials:
        messages.error(
            request, "Trakt credentials are missing. Please add them and try again."
        )
        return redirect("lists")

    client_id, client_secret = credentials

    try:
        oauth_callback = trakt_imports.handle_oauth_callback(
            request,
            redirect_uri=request.build_absolute_uri(reverse("trakt_lists_callback")),
            client_id=client_id,
            client_secret=client_secret,
            code_verifier=state_data.get("code_verifier"),
        )
        # Queue the import task asynchronously so we can redirect immediately
        list_tasks.import_trakt_lists_task.delay(
            request.user.id,
            oauth_callback["access_token"],
            client_id=client_id,
        )
        messages.info(
            request,
            "Trakt authorization successful. Your lists are being imported in the background.",
        )
    except import_helpers.MediaImportError as error:
        messages.error(request, f"Trakt list import failed: {error}")
        return redirect("lists")

    return redirect("lists")
