import logging
from contextlib import contextmanager, suppress
from types import SimpleNamespace

import requests
from celery import shared_task
from django.contrib.auth import get_user_model
from django.utils.module_loading import import_string
from simple_history.models import HistoricalRecords

from app.providers.services import ProviderAPIError

logger = logging.getLogger(__name__)

WEBHOOK_PROCESSORS = {
    "plex": "integrations.webhooks.plex.PlexWebhookProcessor",
    "jellyfin": "integrations.webhooks.jellyfin.JellyfinWebhookProcessor",
    "emby": "integrations.webhooks.emby.EmbyWebhookProcessor",
    "seerr": "integrations.webhooks.seerr.SeerrWebhookProcessor",
    "kodi": "integrations.webhooks.kodi.KodiWebhookProcessor",
    "stremio": "integrations.webhooks.stremio.StremioWebhookProcessor",
}


@contextmanager
def _webhook_history_user(user):
    """Attribute history rows to the webhook user.

    Mirrors simple_history's HistoryRequestMiddleware so Episode history rows
    keep history_user_id when created from a Celery task.
    """
    HistoricalRecords.context.request = SimpleNamespace(user=user)
    try:
        yield
    finally:
        with suppress(AttributeError):
            del HistoricalRecords.context.request


@shared_task(
    name="Process media server webhook",
    # A provider blip used to discard the scrobble outright, since the task
    # re-raised with no retry configured (#521). Only provider/network errors are
    # retried: a malformed payload will fail identically every time, and
    # retrying it would just burn the worker.
    #
    # ProviderAPIError is the one that matters - services.api_request wraps every
    # RequestException in it, so listing only RequestException here would never
    # fire. RequestException stays listed for callers that reach the network
    # without going through api_request.
    autoretry_for=(ProviderAPIError, requests.exceptions.RequestException),
    max_retries=3,
    # Celery's backoff starts at ~1s, so the first (most likely) retry lands
    # inside the five-second end_date window that _handle_tv_episode uses to
    # suppress duplicate episode writes.
    retry_backoff=True,
    retry_jitter=True,
)
def process_webhook(provider, payload, user_id):
    """Process a validated media server webhook payload in the background.

    Keeps webhook HTTP handlers fast: external metadata lookups and DB writes
    run on the worker instead of blocking a web worker.
    """
    user_model = get_user_model()
    try:
        user = user_model.objects.get(pk=user_id)
    except user_model.DoesNotExist:
        logger.warning("Skipping %s webhook for missing user id %s", provider, user_id)
        return

    processor = import_string(WEBHOOK_PROCESSORS[provider])()
    try:
        with _webhook_history_user(user):
            processor.process_payload(payload, user)
    except Exception:
        logger.exception("Error processing %s webhook payload", provider)
        if provider == "plex":
            user.mark_plex_webhook_error(
                "Plex webhook processing failed. Check server logs for details.",
            )
        raise
    if provider == "plex":
        user.mark_plex_webhook_received()

    if provider == "jellyfin":
        account = getattr(user, "jellyfin_account", None)
        if account and account.is_connected and account.instant_push_enabled:
            from integrations.tasks._media_imports import push_jellyfin_watched

            push_jellyfin_watched.delay(user_id=user.id)
