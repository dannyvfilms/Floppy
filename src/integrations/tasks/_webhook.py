import logging
from contextlib import contextmanager, suppress
from types import SimpleNamespace

import requests
from celery import shared_task
from django.contrib.auth import get_user_model
from django.utils.module_loading import import_string
from simple_history.models import HistoricalRecords

from app.providers.services import ProviderAPIError
from integrations import anime_mapping

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


def _process_webhook(provider, payload, user_id):
    """Process a validated media server webhook payload in the worker."""
    user_model = get_user_model()
    try:
        user = user_model.objects.get(pk=user_id)
    except user_model.DoesNotExist:
        logger.warning("Skipping %s webhook for missing user id %s", provider, user_id)
        return

    processor = import_string(WEBHOOK_PROCESSORS[provider])()
    if user.anime_enabled:
        try:
            processor._grouped_anime_snapshot = anime_mapping.load_mapping_snapshot()
            processor._grouped_anime_mapping_loaded = True
        except (OSError, TypeError, ValueError, ProviderAPIError) as error:
            # Grouping is deliberately fail-closed when the pinned mapping is
            # unavailable.  The ordinary TV webhook path remains usable.
            processor._grouped_anime_snapshot = None
            processor._grouped_anime_mapping_loaded = True
            logger.warning(
                "grouped_anime_mapping_unavailable provider=%s user_id=%s error=%s",
                provider,
                user.id,
                error,
            )

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


@shared_task(
    name="Process media server webhook",
    # A provider blip used to discard the scrobble outright, since the task
    # re-raised with no retry configured (#521). Only provider/network errors are
    # retried: a malformed payload will fail identically every time, and
    # retrying it would just burn the worker.
    autoretry_for=(ProviderAPIError, requests.exceptions.RequestException),
    max_retries=3,
    retry_backoff=True,
    retry_jitter=True,
)
def process_webhook(provider, payload, user_id):
    """Process a media-server webhook using its provider-specific processor.

    Keeps webhook HTTP handlers fast: external metadata lookups and DB writes
    run on the worker instead of blocking a web worker.
    """
    return _process_webhook(provider, payload, user_id)


@shared_task(
    name="Process Stremio playback webhook",
    autoretry_for=(ProviderAPIError, requests.exceptions.RequestException),
    max_retries=3,
    retry_backoff=True,
    retry_jitter=True,
    soft_time_limit=90,
    time_limit=120,
)
def process_stremio_webhook(payload, user_id, queue_member=None):
    """Process one bounded Stremio playback event.

    ``queue_member`` is released immediately when the worker starts so a
    stuck task cannot permanently consume the per-user admission budget.
    """
    if queue_member:
        from integrations.stremio_queue import release_pending

        release_pending(user_id, queue_member)
    return _process_webhook("stremio", payload, user_id)
