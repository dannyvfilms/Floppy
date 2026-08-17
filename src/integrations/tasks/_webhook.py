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
    """Process one bounded Stremio playback event and start verification."""
    if queue_member:
        from integrations.stremio_queue import release_pending

        release_pending(user_id, queue_member)

    result = _process_webhook("stremio", payload, user_id)

    if not payload.get("_floppy_verified_completion"):
        from django.utils import timezone

        verify_stremio_playback.apply_async(
            args=[payload, user_id, timezone.now().isoformat()],
            countdown=60,
            queue="interactive",
        )

    return result


@shared_task(
    bind=True,
    name="Verify Stremio playback completion",
    max_retries=40,
    soft_time_limit=90,
    time_limit=120,
)
def verify_stremio_playback(
    self,
    payload,
    user_id,
    started_at,
    previous_observation=None,
):
    """Confirm Stremio completion from live playback state."""
    from datetime import timedelta

    from django.contrib.auth import get_user_model
    from django.utils import timezone
    from django.utils.dateparse import parse_datetime

    from integrations.imports import helpers
    from integrations.imports.stremio import get_library_items

    previous_observation = previous_observation or {}

    target_id = str(payload.get("id") or "")
    media_type = str(payload.get("type") or "")
    entry_id = target_id.split(":", 1)[0] if media_type == "series" else target_id

    if not target_id or media_type not in {"movie", "series"}:
        logger.info(
            "stremio_verify status=invalid_payload user_id=%s payload=%s",
            user_id,
            payload,
        )
        return {"status": "invalid_payload"}

    def parse_episode_id(video_id):
        parts = str(video_id or "").split(":")
        if len(parts) != 3:
            return None
        try:
            return parts[0], int(parts[1]), int(parts[2])
        except ValueError:
            return None

    def is_sequential_next(target_video, current_video):
        target = parse_episode_id(target_video)
        current = parse_episode_id(current_video)

        if not target or not current:
            return False

        target_series, target_season, target_episode = target
        current_series, current_season, current_episode = current

        if target_series != current_series:
            return False

        if (
            current_season == target_season
            and current_episode == target_episode + 1
        ):
            return True

        return (
            current_season == target_season + 1
            and current_episode == 1
        )

    def retry_later(reason, observation, countdown=120, **fields):
        logger.info(
            "stremio_verify status=retry reason=%s user_id=%s media_id=%s "
            "attempt=%s details=%s observation=%s",
            reason,
            user_id,
            target_id,
            self.request.retries,
            fields,
            observation,
        )
        raise self.retry(
            args=[payload, user_id, started_at, observation],
            countdown=max(5, int(countdown)),
        )

    try:
        user = get_user_model().objects.get(id=user_id)
        account = user.stremio_account
        auth_key = helpers.decrypt_or_raise(account.auth_key)
        items = get_library_items(auth_key)
    except Exception as exc:
        logger.warning(
            "stremio_verify status=api_error user_id=%s media_id=%s error=%s",
            user_id,
            target_id,
            exc,
        )
        raise self.retry(
            args=[payload, user_id, started_at, previous_observation],
            exc=exc,
            countdown=120,
        ) from exc

    entry = next(
        (
            item
            for item in items
            if str(item.get("_id") or "") == entry_id
        ),
        None,
    )
    if entry is None:
        retry_later("library_item_missing", previous_observation, countdown=60)

    state = entry.get("state") or {}
    current_video = str(state.get("video_id") or "")

    def as_float(value):
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    duration = as_float(state.get("duration"))
    time_watched = as_float(state.get("timeWatched"))
    time_offset = as_float(state.get("timeOffset"))
    flagged = as_float(state.get("flaggedWatched"))
    times_watched = as_float(state.get("timesWatched"))

    watched_percent = (
        time_watched / duration * 100.0
        if duration > 0
        else 0.0
    )
    offset_percent = (
        time_offset / duration * 100.0
        if duration > 0
        else 0.0
    )

    started = parse_datetime(str(started_at))
    last_watched_raw = state.get("lastWatched")
    last_watched = (
        parse_datetime(str(last_watched_raw))
        if last_watched_raw
        else None
    )

    if started is None:
        logger.warning(
            "stremio_verify status=invalid_started_at user_id=%s media_id=%s value=%s",
            user_id,
            target_id,
            started_at,
        )
        return {"status": "invalid_started_at"}

    if timezone.is_naive(started):
        started = timezone.make_aware(started)

    if last_watched is not None and timezone.is_naive(last_watched):
        last_watched = timezone.make_aware(last_watched)

    current_observation = dict(previous_observation)

    # Learn the interval between genuine Stremio playback-state publications.
    # Repeated verifier polls can otherwise read the same lastWatched/timeWatched
    # snapshot several times in a row.
    previous_last_watched = None
    previous_last_watched_raw = current_observation.get("last_watched")

    if previous_last_watched_raw:
        previous_last_watched = parse_datetime(
            str(previous_last_watched_raw)
        )
        if (
            previous_last_watched is not None
            and timezone.is_naive(previous_last_watched)
        ):
            previous_last_watched = timezone.make_aware(
                previous_last_watched
            )

    learned_update_interval = float(
        current_observation.get("update_interval_seconds") or 0
    )
    cadence_samples = int(
        current_observation.get("update_interval_samples") or 0
    )

    if (
        (media_type != "series" or current_video == target_id)
        and last_watched is not None
        and previous_last_watched is not None
        and last_watched > previous_last_watched
    ):
        observed_interval = (
            last_watched - previous_last_watched
        ).total_seconds()
        duration_seconds_for_cadence = (
            duration / 1000.0
            if duration > 0
            else 0.0
        )

        # Ignore stale intervals from pauses/restarts. A genuine publication
        # interval must be positive and no longer than the media runtime.
        if (
            observed_interval > 0
            and (
                duration_seconds_for_cadence <= 0
                or observed_interval <= duration_seconds_for_cadence
            )
        ):
            if learned_update_interval > 0:
                learned_update_interval = (
                    learned_update_interval * 0.70
                    + observed_interval * 0.30
                )
            else:
                learned_update_interval = observed_interval

            cadence_samples += 1
            current_observation["update_interval_seconds"] = round(
                learned_update_interval,
                3,
            )
            current_observation["update_interval_samples"] = cadence_samples

            logger.info(
                "stremio_verify cadence_observed "
                "media_id=%s observed=%.3fs learned=%.3fs samples=%s",
                target_id,
                observed_interval,
                learned_update_interval,
                cadence_samples,
            )

    # Remember only state that belongs to the exact target episode/movie.
    if media_type != "series" or current_video == target_id:
        prior_best = float(
            current_observation.get("best_watched_percent") or 0
        )

        if watched_percent >= prior_best:
            current_observation.update(
                {
                    "best_watched_percent": round(watched_percent, 4),
                    "best_offset_percent": round(offset_percent, 4),
                    "flagged": flagged,
                    "times_watched": times_watched,
                    "last_watched": (
                        last_watched.isoformat()
                        if last_watched is not None
                        else None
                    ),
                    "duration": duration,
                    "time_watched": time_watched,
                    "video_id": current_video,
                }
            )

    remembered_percent = float(
        current_observation.get("best_watched_percent") or 0
    )
    remembered_flagged = float(
        current_observation.get("flagged") or 0
    )
    remembered_times = float(
        current_observation.get("times_watched") or 0
    )

    remembered_last_watched = None
    if current_observation.get("last_watched"):
        remembered_last_watched = parse_datetime(
            current_observation["last_watched"]
        )
        if (
            remembered_last_watched is not None
            and timezone.is_naive(remembered_last_watched)
        ):
            remembered_last_watched = timezone.make_aware(
                remembered_last_watched
            )

    exact_video_match = (
        media_type == "movie"
        or current_video == target_id
    )

    if exact_video_match:
        if duration <= 0:
            retry_later(
                "duration_missing",
                current_observation,
                countdown=30,
            )

        if last_watched is None:
            retry_later(
                "last_watched_missing",
                current_observation,
                countdown=30,
            )

        if last_watched < started - timedelta(minutes=2):
            retry_later(
                "stale_last_watched",
                current_observation,
                countdown=30,
                last_watched=str(last_watched),
                started_at=str(started),
            )

        if (
            watched_percent >= 90.0
            and flagged >= 1
        ):
            verified_last_watched = last_watched

            logger.info(
                "stremio_verify status=verified mode=normal "
                "user_id=%s media_id=%s watched_percent=%.2f "
                "offset_percent=%.2f flagged=%s times=%s last_watched=%s",
                user_id,
                target_id,
                watched_percent,
                offset_percent,
                flagged,
                times_watched,
                verified_last_watched.isoformat(),
            )

            verified_payload = {
                "id": target_id,
                "type": media_type,
                "viewedAt": int(verified_last_watched.timestamp()),
                "_floppy_verified_completion": True,
            }

            _process_webhook("stremio", verified_payload, user_id)

            return {
                "status": "verified",
                "mode": "normal",
                "media_id": target_id,
                "watched_percent": round(watched_percent, 2),
                "offset_percent": round(offset_percent, 2),
                "last_watched": verified_last_watched.isoformat(),
            }

        def playback_retry_countdown(
            duration_ms,
            percent,
            flagged_value,
            last_watched_dt,
            learned_interval,
            cadence_samples,
        ):
            """Calculate a safe, duration-aware playback retry delay."""
            duration_seconds = max(
                1.0,
                float(duration_ms) / 1000.0,
            )

            target_percent = (
                85.0
                if percent < 85.0
                else 90.0
            )
            gap_percent = max(
                0.0,
                target_percent - percent,
            )
            step_percent = max(
                1.0,
                min(
                    10.0,
                    gap_percent / 2.0,
                ),
            )
            raw_threshold_countdown = (
                duration_seconds
                * step_percent
                / 100.0
            )
            max_threshold_countdown = max(
                30.0,
                min(
                    120.0,
                    duration_seconds * 0.05,
                ),
            )
            threshold_countdown = max(
                5.0,
                min(
                    max_threshold_countdown,
                    raw_threshold_countdown,
                ),
            )

            if flagged_value >= 1 or percent >= 85.0:
                return (
                    round(threshold_countdown),
                    "threshold_completion",
                    None,
                    round(threshold_countdown),
                    None,
                )

            if (
                learned_interval <= 0
                or cadence_samples < 2
                or last_watched_dt is None
            ):
                return (
                    round(threshold_countdown),
                    "threshold_untrusted",
                    None,
                    round(threshold_countdown),
                    None,
                )

            state_age = max(
                0.0,
                (
                    timezone.now()
                    - last_watched_dt
                ).total_seconds(),
            )
            until_expected_update = learned_interval - state_age
            publication_buffer = max(
                1.0,
                learned_interval * 0.02,
            )
            predicted_state_countdown = max(
                5.0,
                until_expected_update + publication_buffer,
            )

            # Prediction may only make the poll earlier; it can never extend
            # the duration/threshold safety delay.
            final_countdown = min(
                threshold_countdown,
                predicted_state_countdown,
            )
            schedule_mode = (
                "hybrid_predicted"
                if predicted_state_countdown < threshold_countdown
                else "threshold_guard"
            )

            return (
                round(final_countdown),
                schedule_mode,
                round(state_age, 3),
                round(threshold_countdown),
                round(predicted_state_countdown),
            )

        learned_update_interval = float(
            current_observation.get("update_interval_seconds") or 0
        )
        cadence_samples = int(
            current_observation.get("update_interval_samples") or 0
        )

        (
            countdown,
            schedule_mode,
            state_age,
            threshold_countdown,
            predicted_state_countdown,
        ) = playback_retry_countdown(
            duration,
            watched_percent,
            flagged,
            last_watched,
            learned_update_interval,
            cadence_samples,
        )

        logger.info(
            "stremio_verify retry_schedule "
            "media_id=%s duration=%.0fms watched_percent=%.2f "
            "countdown=%ss mode=%s "
            "threshold_countdown=%ss predicted_countdown=%s "
            "learned_interval=%.3fs cadence_samples=%s "
            "state_age=%s flagged=%s",
            target_id,
            duration,
            watched_percent,
            countdown,
            schedule_mode,
            threshold_countdown,
            predicted_state_countdown,
            learned_update_interval,
            cadence_samples,
            state_age,
            flagged,
        )

        retry_later(
            "not_complete",
            current_observation,
            countdown=countdown,
            watched_percent=round(watched_percent, 2),
            offset_percent=round(offset_percent, 2),
            flagged=flagged,
            times_watched=times_watched,
        )

    if media_type == "series" and is_sequential_next(
        target_id,
        current_video,
    ):
        # Pre-patch jobs that never captured a target observation cannot be
        # trusted for auto-next completion. End them instead of retrying.
        if not current_observation:
            logger.info(
                "stremio_verify status=superseded reason=legacy_no_observation "
                "user_id=%s media_id=%s next_video=%s",
                user_id,
                target_id,
                current_video,
            )
            return {
                "status": "superseded",
                "reason": "legacy_no_observation",
                "media_id": target_id,
                "next_video": current_video,
            }

        auto_next_ready = (
            remembered_percent >= 85.0
            and remembered_flagged >= 1
            and remembered_last_watched is not None
            and remembered_last_watched >= started - timedelta(minutes=2)
        )

        if auto_next_ready:
            logger.info(
                "stremio_verify status=verified mode=auto_next "
                "user_id=%s media_id=%s next_video=%s "
                "remembered_percent=%.2f flagged=%s times=%s "
                "last_watched=%s",
                user_id,
                target_id,
                current_video,
                remembered_percent,
                remembered_flagged,
                remembered_times,
                remembered_last_watched.isoformat(),
            )

            verified_payload = {
                "id": target_id,
                "type": media_type,
                "viewedAt": int(remembered_last_watched.timestamp()),
                "_floppy_verified_completion": True,
            }

            _process_webhook("stremio", verified_payload, user_id)

            return {
                "status": "verified",
                "mode": "auto_next",
                "media_id": target_id,
                "next_video": current_video,
                "watched_percent": round(remembered_percent, 2),
                "last_watched": remembered_last_watched.isoformat(),
            }

        logger.info(
            "stremio_verify status=superseded reason=auto_next_without_threshold "
            "user_id=%s media_id=%s next_video=%s "
            "remembered_percent=%.2f flagged=%s times=%s",
            user_id,
            target_id,
            current_video,
            remembered_percent,
            remembered_flagged,
            remembered_times,
        )
        return {
            "status": "superseded",
            "reason": "auto_next_without_threshold",
            "media_id": target_id,
            "next_video": current_video,
            "watched_percent": round(remembered_percent, 2),
        }

    if media_type == "series" and current_video != target_id:
        logger.info(
            "stremio_verify status=superseded reason=video_mismatch "
            "user_id=%s media_id=%s current_video=%s "
            "remembered_percent=%.2f flagged=%s times=%s",
            user_id,
            target_id,
            current_video,
            remembered_percent,
            remembered_flagged,
            remembered_times,
        )
        return {
            "status": "superseded",
            "reason": "video_mismatch",
            "media_id": target_id,
            "current_video": current_video,
        }

    retry_later(
        "state_not_ready",
        current_observation,
        countdown=30,
    )
