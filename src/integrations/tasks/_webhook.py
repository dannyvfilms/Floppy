import json
import logging
from contextlib import contextmanager, suppress
from types import SimpleNamespace

import requests
from celery import shared_task
from django.contrib.auth import get_user_model
from django.utils.module_loading import import_string
from simple_history.models import HistoricalRecords

from app.log_safety import redact_secrets
from app.providers.services import ProviderAPIError
from integrations import anime_mapping
from integrations.models import PlexWebhookShare

logger = logging.getLogger(__name__)

WEBHOOK_PROCESSORS = {
    "plex": "integrations.webhooks.plex.PlexWebhookProcessor",
    "jellyfin": "integrations.webhooks.jellyfin.JellyfinWebhookProcessor",
    "emby": "integrations.webhooks.emby.EmbyWebhookProcessor",
    "seerr": "integrations.webhooks.seerr.SeerrWebhookProcessor",
    "kodi": "integrations.webhooks.kodi.KodiWebhookProcessor",
    "stremio": "integrations.webhooks.stremio.StremioWebhookProcessor",
}

# Bounds one event's logged payload so a pathological payload can't crowd out
# other log history in the rotating file the sanitized log export reads from.
_WEBHOOK_PAYLOAD_LOG_CAP = 4000


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


def _process_webhook(provider, payload, user_id, share_id=None):
    """Process a validated media server webhook payload in the worker."""
    user_model = get_user_model()
    share = None
    source_account = None
    source_username = None
    source_libraries = None

    if share_id is not None:
        try:
            share = (
                PlexWebhookShare.objects.select_related(
                    "owner__plex_account",
                    "recipient",
                )
                .get(
                    pk=share_id,
                    recipient_id=user_id,
                    recipient_enabled=True,
                )
            )
        except PlexWebhookShare.DoesNotExist:
            logger.info("Skipping disabled or missing Plex webhook share id %s", share_id)
            return

        if not share.owner.is_active:
            logger.info("Skipping Plex webhook share from inactive owner id %s", share.owner_id)
            return

        user = share.recipient
        source_account = getattr(share.owner, "plex_account", None)
        if not source_account or not source_account.plex_token:
            logger.info("Skipping Plex webhook share %s without an owner Plex account", share.id)
            return
        source_username = share.plex_username
        source_libraries = share.allowed_libraries
    else:
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

    dumped_payload = redact_secrets(json.dumps(payload, default=str))
    if len(dumped_payload) > _WEBHOOK_PAYLOAD_LOG_CAP:
        dumped_payload = dumped_payload[:_WEBHOOK_PAYLOAD_LOG_CAP] + "...[truncated]"
    logger.info("Webhook payload for %s: %s", provider, dumped_payload)

    try:
        with _webhook_history_user(user):
            if share is None:
                processor.process_payload(payload, user)
            else:
                processor.process_payload(
                    payload,
                    user,
                    source_account=source_account,
                    source_username=source_username,
                    source_libraries=source_libraries,
                )
    except Exception:
        logger.exception(
            "Error processing %s webhook payload%s",
            provider,
            f" for Plex webhook share {share.id}" if share else "",
        )
        if provider == "plex" and share is None:
            user.mark_plex_webhook_error(
                "Plex webhook processing failed. Check server logs for details.",
            )
        raise
    if provider == "plex" and share is None:
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
def process_webhook(provider, payload, user_id, share_id=None):
    """Process a media-server webhook using its provider-specific processor.

    Keeps webhook HTTP handlers fast: external metadata lookups and DB writes
    run on the worker instead of blocking a web worker.
    """
    return _process_webhook(provider, payload, user_id, share_id=share_id)


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
    """Process one Stremio start and create its guarded verifier session."""
    if queue_member:
        from integrations.stremio_queue import release_pending

        release_pending(user_id, queue_member)

    result = _process_webhook("stremio", payload, user_id)
    if payload.get("_floppy_verified_completion"):
        return result

    from integrations.stremio_playback import start_session

    decision = start_session(payload, user_id)
    if decision.status == "schedule":
        verify_stremio_playback.apply_async(
            args=[decision.session_id],
            countdown=decision.countdown,
            queue="interactive",
        )
    else:
        logger.info(
            "stremio_verify_start status=%s reason=%s user_id=%s media_id=%s",
            decision.status,
            decision.reason,
            user_id,
            payload.get("id"),
        )
    return result


@shared_task(
    name="Verify Stremio playback completion",
    soft_time_limit=90,
    time_limit=120,
)
def verify_stremio_playback(session_id):
    """Run one bounded observation and schedule only the requested successor."""
    from integrations.stremio_playback import observe_session

    decision = observe_session(session_id)
    if decision.status == "schedule":
        verify_stremio_playback.apply_async(
            args=[session_id],
            countdown=decision.countdown,
            queue="interactive",
        )
    elif decision.status == "complete":
        _process_webhook("stremio", decision.payload, decision.user_id)
    logger.info(
        "stremio_verify status=%s reason=%s session_id=%s",
        decision.status,
        decision.reason,
        session_id,
    )
    return {
        "status": decision.status,
        "reason": decision.reason,
        "session_id": session_id,
    }
