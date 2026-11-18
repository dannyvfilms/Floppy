"""Webhook receivers for media servers and request managers.

Jellyfin, Plex, Emby, Kodi and Jellyseerr find their user by the token in the
URL; the instance-wide Seerr hook matches users from the payload. Each queues
the payload and answers at once. What a webhook may write is decided by the
processors in integrations/webhooks/ (docs/architecture/webhook-write-rules.md).
"""

import hmac
import json
import logging
import secrets

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

import users
from integrations import tasks
from integrations.models import PlexWebhookShare
from integrations.view_helpers import _queue_task_quietly
from integrations.webhooks.plex import extract_plex_webhook_usernames

logger = logging.getLogger(__name__)


def _webhook_request_fields(payload, provider, user_id):
    """Return correlation fields shared by receipt and worker logs.

    The id ties the HTTP receipt, the queued task and its outcome together;
    ``received_at`` is the arrival time, so the worker can report queue wait
    and ignore an older event that overtakes a newer one. See
    docs/architecture/webhook-delivery.md.
    """
    event = metadata = None
    if isinstance(payload, dict):
        event = payload.get("event") or payload.get("Event")
        metadata = payload.get("Metadata") or payload.get("Item") or {}
    rating_key = None
    if isinstance(metadata, dict):
        rating_key = (
            metadata.get("ratingKey")
            or metadata.get("ratingkey")
            or metadata.get("Id")
            or metadata.get("id")
        )
    event_id = secrets.token_hex(8)
    received_at = timezone.now().isoformat()
    logger.info(
        "webhook_received event_id=%s provider=%s event=%s user_id=%s rating_key=%s",
        event_id,
        provider,
        event,
        user_id,
        rating_key,
    )
    return {"received_at": received_at, "event_id": event_id}


@login_not_required
@csrf_exempt
@require_POST
def jellyfin_webhook(request, token):
    """Handle Jellyfin webhook notifications for media playback."""
    try:
        user = users.models.User.objects.get(token=token, is_active=True)
    except ObjectDoesNotExist:
        logger.warning(
            "Could not process Jellyfin webhook: Invalid token",
        )
        return HttpResponse(status=401)

    data = request.body
    if not data:
        logger.warning("Missing payload in Jellyfin webhook request")
        return HttpResponse("Missing payload", status=400)

    try:
        payload = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return HttpResponse("Invalid JSON", status=400)
    if not isinstance(payload, dict):
        return HttpResponse("Invalid payload", status=400)
    if not _queue_task_quietly(
        tasks.process_webhook,
        "jellyfin",
        payload,
        user.id,
        **_webhook_request_fields(payload, "jellyfin", user.id),
    ):
        return HttpResponse(status=503)
    return HttpResponse(status=200)


@login_not_required
@csrf_exempt
@require_POST
def plex_webhook(request, token):
    """Handle Plex webhook notifications for media playback."""
    try:
        user = users.models.User.objects.get(token=token, is_active=True)
    except ObjectDoesNotExist:
        logger.warning(
            "Could not process Plex webhook: Invalid token",
        )
        return HttpResponse(status=401)

    # https://support.plex.tv/hc/en-us/articles/115002267687-Webhooks
    # As stated above, the payload is sent in JSON format inside a multipart
    # HTTP POST request. For the media.play and media.rate events, a second part of
    # the POST request contains a JPEG thumbnail for the media.

    data = request.POST.get("payload")
    if not data:
        logger.warning("Missing payload in Plex webhook request")
        user.mark_plex_webhook_error("Missing payload in Plex webhook request")
        return HttpResponse("Missing payload", status=400)

    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON payload in Plex webhook request")
        user.mark_plex_webhook_error("Invalid JSON payload in Plex webhook request")
        return HttpResponse("Invalid payload", status=400)

    request_fields = _webhook_request_fields(payload, "plex", user.id)
    queued = _queue_task_quietly(
        tasks.process_webhook,
        "plex",
        payload,
        user.id,
        **request_fields,
    )
    payload_usernames = extract_plex_webhook_usernames(payload)
    for share in PlexWebhookShare.objects.filter(
        owner=user,
        recipient_enabled=True,
        recipient__is_active=True,
    ).only("id", "recipient_id", "plex_username"):
        if share.plex_username.strip().casefold() in payload_usernames:
            queued &= _queue_task_quietly(
                tasks.process_webhook,
                "plex",
                payload,
                share.recipient_id,
                share_id=share.id,
                **request_fields,
            )
    if not queued:
        return HttpResponse(status=503)
    return HttpResponse(status=200)


@login_not_required
@csrf_exempt
@require_POST
def emby_webhook(request, token):
    """Handle Emby webhook notifications for media playback."""
    try:
        user = users.models.User.objects.get(token=token, is_active=True)
    except ObjectDoesNotExist:
        logger.warning(
            "Could not process Emby webhook: Invalid token",
        )
        return HttpResponse(status=401)

    # The payload is sent in JSON format inside a multipart
    # HTTP POST request.

    data = request.POST.get("data")
    if not data:
        logger.warning("Missing payload in Emby webhook request")
        return HttpResponse("Missing payload", status=400)

    try:
        payload = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return HttpResponse("Invalid JSON", status=400)
    if not isinstance(payload, dict):
        return HttpResponse("Invalid payload", status=400)
    if not _queue_task_quietly(
        tasks.process_webhook,
        "emby",
        payload,
        user.id,
        **_webhook_request_fields(payload, "emby", user.id),
    ):
        return HttpResponse(status=503)
    return HttpResponse(status=200)


# kept: URL name — renaming breaks already-configured Seerr/Jellyseerr webhook URLs
@login_not_required
@csrf_exempt
@require_POST
def jellyseerr_webhook(request, token):
    """Handle Seerr webhook notifications for requested/approved media."""
    try:
        user = users.models.User.objects.get(token=token, is_active=True)
    except ObjectDoesNotExist:
        logger.warning(
            "Could not process Seerr webhook: Invalid token",
        )
        return HttpResponse(status=401)

    data = request.body
    if not data:
        logger.warning("Missing payload in Seerr webhook request")
        return HttpResponse("Missing payload", status=400)

    try:
        payload = json.loads(data)
    except Exception:
        logger.warning("Invalid JSON payload in Seerr webhook request")
        return HttpResponse("Invalid JSON", status=400)

    if not _queue_task_quietly(tasks.process_webhook, "seerr", payload, user.id):
        return HttpResponse(status=503)
    return HttpResponse(status=200)


@login_not_required
@csrf_exempt
@require_POST
def seerr_global_webhook(request):
    """Handle a single shared Seerr webhook for multiple Floppy users.

    Unlike the per-user Seerr webhook, this endpoint has no per-user
    token in the URL, so it demultiplexes users by matching the payload's
    requester username against each opted-in user's allowed usernames.
    """
    if not settings.SEERR_GLOBAL_WEBHOOK_SECRET:
        return HttpResponse(status=404)

    data = request.body
    if not data:
        logger.warning("Missing payload in Seerr global webhook request")
        return HttpResponse("Missing payload", status=400)

    try:
        payload = json.loads(data)
    except Exception:
        logger.warning("Invalid JSON payload in Seerr global webhook request")
        return HttpResponse("Invalid JSON", status=400)

    if not hmac.compare_digest(
        str(payload.get("secret", "")),
        settings.SEERR_GLOBAL_WEBHOOK_SECRET,
    ):
        logger.warning("Seerr global webhook: invalid or missing secret")
        return HttpResponse(status=401)

    requester = (payload.get("requestedBy_username") or "").strip() or (
        payload.get("notifyuser_username") or ""
    ).strip()
    if not requester:
        logger.warning("Missing requester in Seerr global webhook request")
        return HttpResponse("Missing requester", status=400)

    matched = False
    queued = True
    for user in users.models.User.objects.filter(
        jellyseerr_enabled=True,
        is_active=True,
    ).exclude(jellyseerr_allowed_usernames=""):
        allowed = {
            username.strip().lower()
            for username in user.jellyseerr_allowed_usernames.split(",")
            if username.strip()
        }
        if requester.lower() in allowed:
            matched = True
            queued &= _queue_task_quietly(tasks.process_webhook, "seerr", payload, user.id)

    if not matched:
        logger.info(
            "Seerr global webhook: no user matched requester=%r",
            requester,
        )

    if not queued:
        return HttpResponse(status=503)
    return HttpResponse(status=200)


@login_not_required
@csrf_exempt
@require_POST
def kodi_webhook(request, token):
    """Handle Kodi webhook notifications for media playback."""
    try:
        user = users.models.User.objects.get(token=token, is_active=True)
    except ObjectDoesNotExist:
        logger.warning(
            "Could not process Kodi webhook: Invalid token",
        )
        return HttpResponse(status=401)

    data = request.body
    if not data:
        logger.warning("Missing payload in Kodi webhook request")
        return HttpResponse("Missing payload", status=400)

    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON payload in Kodi webhook request")
        return HttpResponse("Invalid JSON", status=400)

    if not _queue_task_quietly(
        tasks.process_webhook,
        "kodi",
        payload,
        user.id,
        **_webhook_request_fields(payload, "kodi", user.id),
    ):
        return HttpResponse(status=503)
    return HttpResponse(status=200)
