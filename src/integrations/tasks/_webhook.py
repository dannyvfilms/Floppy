import logging
import time
from contextlib import contextmanager, suppress
from types import SimpleNamespace

import requests
from celery import shared_task
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.module_loading import import_string
from simple_history.models import HistoricalRecords

from app import cache_safety
from app.log_safety import mapping_keys
from app.providers import credentials
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

# Queue wait is logged as a millisecond value plus one fixed bucket label, so
# the distribution is visible without a metrics backend. Anything past the
# warning threshold deserves an incident note (see
# docs/architecture/webhook-delivery.md).
QUEUE_DELAY_BUCKETS_MS = (100, 500, 1_000, 5_000, 10_000, 30_000)
QUEUE_DELAY_WARNING_MS = 10_000


def _queue_delay_bucket(delay_ms):
    """Return the histogram bucket label for a queue delay."""
    if delay_ms is None:
        return "unknown"
    for upper in QUEUE_DELAY_BUCKETS_MS:
        if delay_ms <= upper:
            return f"le_{upper}ms"
    return f"gt_{QUEUE_DELAY_BUCKETS_MS[-1]}ms"


def _event_identity(payload):
    """Return the provider event and item key for correlation, never values."""
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
    rating_key = str(rating_key).strip() if rating_key is not None else None
    return event, rating_key or None


def _log_webhook_finished(
    *,
    event_id,
    provider,
    user_id,
    event,
    rating_key,
    outcome,
    started,
):
    """Log the terminal state of one webhook task attempt."""
    logger.info(
        "webhook_finished event_id=%s provider=%s user_id=%s event=%s "
        "rating_key=%s outcome=%s elapsed_ms=%s",
        event_id,
        provider,
        user_id,
        event,
        rating_key,
        outcome,
        int((time.monotonic() - started) * 1000),
    )


def _received_at_details(received_at):
    """Return (queue delay in ms, event epoch seconds) for a receipt timestamp."""
    if not received_at:
        return None, None
    try:
        received = parse_datetime(received_at)
    except (TypeError, ValueError):
        return None, None
    if received is None:
        return None, None
    if timezone.is_naive(received):
        received = timezone.make_aware(received)
    delay_ms = max(0, int((timezone.now() - received).total_seconds() * 1000))
    return delay_ms, int(received.timestamp())


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


def _process_webhook(
    provider,
    payload,
    user_id,
    share_id=None,
    received_at=None,
    event_id=None,
):
    """Process a validated media server webhook payload in the worker."""
    started = time.monotonic()
    event, rating_key = _event_identity(payload)
    queue_delay_ms, event_ts = _received_at_details(received_at)
    logger.info(
        "webhook_started event_id=%s provider=%s user_id=%s event=%s "
        "rating_key=%s queue_delay_ms=%s queue_delay_bucket=%s",
        event_id,
        provider,
        user_id,
        event,
        rating_key,
        queue_delay_ms,
        _queue_delay_bucket(queue_delay_ms),
    )
    if queue_delay_ms is not None and queue_delay_ms > QUEUE_DELAY_WARNING_MS:
        logger.warning(
            "webhook_slow_queue event_id=%s provider=%s user_id=%s event=%s "
            "rating_key=%s queue_delay_ms=%s",
            event_id,
            provider,
            user_id,
            event,
            rating_key,
            queue_delay_ms,
        )

    def finish(outcome):
        _log_webhook_finished(
            event_id=event_id,
            provider=provider,
            user_id=user_id,
            event=event,
            rating_key=rating_key,
            outcome=outcome,
            started=started,
        )

    user_model = get_user_model()
    share = None
    source_account = None
    source_username = None
    source_libraries = None
    result = None

    if share_id is not None:
        try:
            share = PlexWebhookShare.objects.select_related(
                "owner__plex_account",
                "recipient",
            ).get(
                pk=share_id,
                recipient_id=user_id,
                recipient_enabled=True,
            )
        except PlexWebhookShare.DoesNotExist:
            logger.info(
                "Skipping disabled or missing Plex webhook share id %s", share_id
            )
            finish("ignored")
            return

        if not share.owner.is_active:
            logger.info(
                "Skipping Plex webhook share from inactive owner id %s", share.owner_id
            )
            finish("ignored")
            return

        user = share.recipient
        source_account = getattr(share.owner, "plex_account", None)
        if not source_account or not source_account.plex_token:
            logger.info(
                "Skipping Plex webhook share %s without an owner Plex account", share.id
            )
            finish("ignored")
            return
        source_username = share.plex_username
        source_libraries = share.allowed_libraries
    else:
        try:
            user = user_model.objects.get(pk=user_id)
        except user_model.DoesNotExist:
            logger.warning(
                "Skipping %s webhook for missing user id %s", provider, user_id
            )
            finish("ignored")
            return

    if not user.is_active:
        logger.info("Skipping %s webhook for inactive user id %s", provider, user.id)
        finish("ignored")
        return

    processor = import_string(WEBHOOK_PROCESSORS[provider])()
    processor._event_ts = event_ts
    processor._event_id = event_id
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

    logger.info("Webhook received provider=%s keys=%s", provider, mapping_keys(payload))

    try:
        with _webhook_history_user(user), credentials.current_user_scope(user):
            if share is None:
                result = processor.process_payload(payload, user)
            else:
                result = processor.process_payload(
                    payload,
                    user,
                    source_account=source_account,
                    source_username=source_username,
                    source_libraries=source_libraries,
                )
    except Exception:
        logger.exception(
            "Error processing %s webhook payload%s event_id=%s event=%s "
            "rating_key=%s outcome=error elapsed_ms=%s",
            provider,
            f" for Plex webhook share {share.id}" if share else "",
            event_id,
            event,
            rating_key,
            int((time.monotonic() - started) * 1000),
        )
        if provider == "plex" and share is None:
            user.mark_plex_webhook_error(
                "Plex webhook processing failed. Check server logs for details.",
            )
        raise
    if provider == "plex" and share is None:
        user.mark_plex_webhook_received()

    outcome = getattr(processor, "outcome", None) or "skipped"
    if outcome == "skipped" and result is not None:
        outcome = "persisted"
    finish(outcome)

    if provider == "jellyfin":
        _queue_jellyfin_instant_push(user, payload)


# Only events that can change watched state warrant a push. Play, Pause and
# progress events arrive every few seconds during playback, and each push is a
# full library walk.
_JELLYFIN_INSTANT_PUSH_EVENTS = frozenset({"Stop", "MarkPlayed", "MarkUnplayed"})


def _queue_jellyfin_instant_push(user, payload):
    """Queue one delayed push per user, however many events arrive meanwhile."""
    account = getattr(user, "jellyfin_account", None)
    if not (account and account.is_connected and account.instant_push_enabled):
        return
    if payload.get("Event") not in _JELLYFIN_INSTANT_PUSH_EVENTS:
        return

    from integrations.tasks._jellyfin_health import (
        INSTANT_PUSH_DEBOUNCE_SECONDS,
        instant_push_lock_key,
    )
    from integrations.tasks._media_imports import push_jellyfin_watched

    # The push releases this key when it starts, so a pending push absorbs
    # every event until then. The timeout only covers a push that never runs.
    if not cache_safety.acquire_lock(
        instant_push_lock_key(user.id),
        timeout=INSTANT_PUSH_DEBOUNCE_SECONDS * 5,
        on_error=cache_safety.ON_ERROR_PROCEED,
    ):
        return
    push_jellyfin_watched.apply_async(
        kwargs={"user_id": user.id},
        countdown=INSTANT_PUSH_DEBOUNCE_SECONDS,
    )


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
    # A wedged metadata lookup used to hold this interactive worker slot
    # indefinitely; the delay surfaced as minutes of webhook lag (#1708).
    soft_time_limit=120,
    time_limit=150,
)
def process_webhook(
    provider,
    payload,
    user_id,
    share_id=None,
    received_at=None,
    event_id=None,
):
    """Process a media-server webhook using its provider-specific processor.

    Keeps webhook HTTP handlers fast: external metadata lookups and DB writes
    run on the worker instead of blocking a web worker.

    ``received_at`` is the request arrival time, used for queue-delay
    telemetry and to keep a late event from overwriting newer state.
    ``event_id`` ties receipt, worker start and the saved result together.
    """
    return _process_webhook(
        provider,
        payload,
        user_id,
        share_id=share_id,
        received_at=received_at,
        event_id=event_id,
    )


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
    name="Process Stremio tracker event",
    autoretry_for=(ProviderAPIError, requests.exceptions.RequestException),
    max_retries=3,
    retry_backoff=True,
    retry_jitter=True,
    soft_time_limit=90,
    time_limit=120,
)
def process_stremio_tracker_event(
    kind,
    user_id,
    media_type,
    media_id,
    extra,
    received_at,
):
    """Record one Stremio player or library event on the worker.

    `received_at` is when the request arrived, so a queued event keeps its place
    in the session even if the worker picks it up late.
    """
    from django.utils.dateparse import parse_datetime

    from integrations import stremio_tracker

    user = get_user_model().objects.filter(pk=user_id).first()
    if user is None:
        return "unknown_user"
    handler = (
        stremio_tracker.record_player_event
        if kind == "player"
        else stremio_tracker.record_library_event
    )
    return handler(
        user,
        media_type,
        media_id,
        extra,
        now=parse_datetime(received_at),
    )


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
