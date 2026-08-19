"""Celery tasks for Koito listening-history sync.

Receive-only: these tasks read from Koito and never submit back to it.
"""

import logging
import random
import time

from celery import current_task, shared_task
from django.core.cache import cache
from django.utils import timezone

from app.log_safety import exception_summary
from integrations.imports.helpers import retry_on_lock

logger = logging.getLogger(__name__)

KOITO_POLL_TASK_NAME = "Poll Koito for user"

KOITO_PARTIAL_SYNC_ERROR = (
    "Koito sync ended early during pagination. Imported partial results and will retry "
    "without advancing the cursor."
)

# The export is a single unpaginated response, so a chunk can take a while.
# Sized well above the Last.fm 600s chunk lock for that reason.
KOITO_HISTORY_IMPORT_LOCK_TIMEOUT = 60 * 60


def _refresh_koito_statistics(user_id: int, affected_day_keys) -> None:
    """Refresh statistics caches after a Koito sync."""
    if not affected_day_keys:
        return

    from app import statistics_cache

    statistics_cache.invalidate_statistics_days(
        user_id,
        day_values=list(affected_day_keys),
        reason="koito_batch_import",
    )
    statistics_cache.schedule_all_ranges_refresh(user_id)


def _enqueue_koito_music_enrichment(user_id: int) -> None:
    """Kick off deferred music enrichment after a history backfill."""
    from app.tasks import enrich_albums_task, enrich_music_library_task

    try:
        enrich_music_library_task.delay(user_id)
        enrich_albums_task.delay(user_id)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug(
            "Could not enqueue Koito music enrichment for user %s: %s",
            user_id,
            exception_summary(exc),
        )


def _record_koito_failure(account, message, *, broken=False):
    """Persist a sync failure on the account."""
    account.connection_broken = broken
    account.failure_count += 1
    account.last_error_message = str(message)[:500]
    account.last_failed_at = timezone.now()
    retry_on_lock(
        lambda: account.save(
            update_fields=[
                "connection_broken",
                "failure_count",
                "last_error_message",
                "last_failed_at",
            ],
        ),
    )


def _run_incremental_koito_sync(account) -> dict:
    """Poll new Koito listens for a single account."""
    from integrations import koito_api, koito_sync

    if not getattr(account.user, "music_enabled", False):
        logger.debug(
            "Skipping Koito poll for user %s: music disabled",
            account.user.username,
        )
        return {
            "status": "skipped",
            "processed": 0,
            "skipped": 0,
            "errors": 0,
            "message": "Music tracking is disabled.",
        }

    from_timestamp_uts = None
    if account.last_fetch_timestamp_uts:
        # Rewind guards against boundary races on the cursor.
        from_timestamp_uts = account.last_fetch_timestamp_uts - 60

    try:
        sync_result = koito_sync.sync_koito_account(
            account,
            from_timestamp_uts=from_timestamp_uts,
        )
    except koito_api.KoitoAuthError as exc:
        logger.exception("Koito auth error for user %s", account.user.username)
        _record_koito_failure(account, exc, broken=True)
        return {
            "status": "error",
            "processed": 0,
            "skipped": 0,
            "errors": 1,
            "message": "Koito rejected the API key.",
        }
    except koito_api.KoitoRateLimitError as exc:
        logger.warning(
            "Koito rate limited for user %s, will retry next cycle: %s",
            account.user.username,
            exc,
        )
        _record_koito_failure(account, exc)
        return {
            "status": "error",
            "processed": 0,
            "skipped": 0,
            "errors": 1,
            "message": "Koito rate limit exceeded.",
        }
    except Exception as exc:
        logger.exception("Koito sync failed for user %s", account.user.username)
        _record_koito_failure(account, exc)
        return {
            "status": "error",
            "processed": 0,
            "skipped": 0,
            "errors": 1,
            "message": "Unexpected Koito sync error.",
        }

    _refresh_koito_statistics(account.user.id, sync_result["affected_day_keys"])

    now = timezone.now()
    update_fields = [
        "last_sync_at",
        "connection_broken",
        "failure_count",
        "last_error_message",
        "last_failed_at",
    ]
    account.last_sync_at = now
    account.connection_broken = False

    if sync_result["complete"]:
        latest_timestamp_uts = account.last_fetch_timestamp_uts or 0
        if sync_result["max_seen_uts"] is not None:
            latest_timestamp_uts = max(
                latest_timestamp_uts,
                sync_result["max_seen_uts"],
            )
        account.last_fetch_timestamp_uts = latest_timestamp_uts
        account.failure_count = 0
        account.last_error_message = ""
        account.last_failed_at = None
        update_fields.append("last_fetch_timestamp_uts")
        status = "success"
        message = (
            f"Processed {sync_result['processed']} new Koito listen(s)."
            if sync_result["processed"]
            else "No new Koito listens found."
        )
    else:
        # Leave the cursor alone so the window is retried next cycle.
        account.failure_count += 1
        account.last_error_message = KOITO_PARTIAL_SYNC_ERROR
        account.last_failed_at = now
        status = "partial"
        message = KOITO_PARTIAL_SYNC_ERROR

    retry_on_lock(lambda: account.save(update_fields=update_fields))
    return {
        "status": status,
        "processed": sync_result["processed"],
        "skipped": sync_result["skipped"],
        "errors": sync_result["errors"],
        "message": message,
    }


@shared_task(name=KOITO_POLL_TASK_NAME)
def poll_koito_for_user(user_id):
    """Poll new Koito listens for a single user."""
    from integrations.models import KoitoAccount

    account = (
        KoitoAccount.objects.filter(user_id=user_id).select_related("user").first()
    )
    if not account or not account.is_connected:
        logger.debug("Skipping Koito poll for user %s: no connected account", user_id)
        return {"processed": 0, "errors": 0, "message": "No connected Koito account."}

    result = _run_incremental_koito_sync(account)
    return {
        "processed": 1 if result["status"] in {"success", "partial"} else 0,
        "errors": 1 if result["status"] in {"partial", "error"} else 0,
        "message": result["message"],
    }


@shared_task(name="Poll Koito for all users")
def poll_all_koito_accounts():
    """Global task to poll Koito for all connected users."""
    from integrations.models import KoitoAccount

    accounts = KoitoAccount.objects.filter(
        connection_broken=False,
    ).select_related("user")
    if not accounts.exists():
        logger.debug("No Koito accounts to poll")
        return {"processed": 0, "errors": 0, "message": "No accounts to poll"}

    logger.info("Polling Koito for %d users", accounts.count())

    batch_size = 10
    processed_count = 0
    error_count = 0
    partial_count = 0

    accounts_list = list(accounts)
    random.shuffle(accounts_list)

    for index, account in enumerate(accounts_list):
        if index > 0 and index % batch_size == 0:
            time.sleep(random.uniform(0.5, 2.0))  # noqa: S311  # sampling/jitter only, not cryptographic

        result = _run_incremental_koito_sync(account)
        if result["status"] == "success":
            processed_count += 1
        elif result["status"] == "partial":
            processed_count += 1
            partial_count += 1
            error_count += 1
        elif result["status"] == "error":
            error_count += 1

    logger.info(
        "Koito polling completed: %d users processed, %d partial, %d errors",
        processed_count,
        partial_count,
        error_count,
    )
    return {
        "processed": processed_count,
        "errors": error_count,
        "total_accounts": accounts.count(),
        "message": f"Processed {processed_count} Koito account(s).",
    }


@shared_task(name="Import from Koito History")
def import_koito_history(user_id, reset=False):
    """Import a user's full Koito history from the export endpoint."""
    from integrations import import_progress, koito_api, koito_sync
    from integrations.models import ImportRun, KoitoAccount, LastFMHistoryImportStatus
    from integrations.webhooks.koito import KoitoScrobbleProcessor

    account = (
        KoitoAccount.objects.filter(user_id=user_id).select_related("user").first()
    )
    if not account or not account.is_connected:
        logger.debug(
            "Skipping Koito history import for user %s: no connected account",
            user_id,
        )
        return {"message": "No connected Koito account."}

    if not getattr(account.user, "music_enabled", False):
        return {"message": "Music tracking is disabled."}

    task_id = current_task.request.id if current_task and current_task.request else None
    import_run = ImportRun.objects.create(user_id=user_id, source="koito", task_id=task_id)

    if reset:
        account.reset_history_import()
        retry_on_lock(
            lambda: account.save(
                update_fields=[
                    "history_import_status",
                    "history_import_started_at",
                    "history_import_completed_at",
                    "history_import_last_error_message",
                ],
            ),
        )

    lock_key = koito_sync.get_koito_history_import_lock_key(user_id)
    if not cache.add(
        lock_key,
        {"started_at": timezone.now().isoformat()},
        timeout=KOITO_HISTORY_IMPORT_LOCK_TIMEOUT,
    ):
        logger.debug("Koito history import already running for user %s", user_id)
        return {"message": "Full Koito history import already running."}

    try:
        account.refresh_from_db()
        account.history_import_status = LastFMHistoryImportStatus.RUNNING
        account.history_import_started_at = timezone.now()
        account.history_import_last_error_message = ""
        retry_on_lock(
            lambda: account.save(
                update_fields=[
                    "history_import_status",
                    "history_import_started_at",
                    "history_import_last_error_message",
                ],
            ),
        )

        try:
            base_url, api_key = koito_sync.get_account_credentials(account)
            export_payload = koito_api.get_export(base_url, api_key)

            listens = koito_sync.export_to_listens(export_payload)
            listens.sort(key=lambda listen: koito_api.listen_timestamp_uts(listen) or 0)

            processor = KoitoScrobbleProcessor(base_url, api_key, account_id=account.id)
            with import_progress.tracking(task_id, import_run.id):
                stats = processor.process_listens(listens, account.user)
        except Exception as exc:
            account.refresh_from_db()
            account.history_import_status = LastFMHistoryImportStatus.FAILED
            account.history_import_last_error_message = str(exc)[:500]
            if isinstance(exc, koito_api.KoitoAuthError):
                account.connection_broken = True
            retry_on_lock(
                lambda: account.save(
                    update_fields=[
                        "history_import_status",
                        "history_import_last_error_message",
                        "connection_broken",
                    ],
                ),
            )
            ImportRun.objects.filter(id=import_run.id).update(
                status=ImportRun.Status.FAILED,
                finished_at=timezone.now(),
            )
            raise

        _refresh_koito_statistics(user_id, stats["affected_day_keys"])

        account.refresh_from_db()
        account.history_import_status = LastFMHistoryImportStatus.COMPLETED
        account.history_import_completed_at = timezone.now()
        account.history_import_last_error_message = ""
        retry_on_lock(
            lambda: account.save(
                update_fields=[
                    "history_import_status",
                    "history_import_completed_at",
                    "history_import_last_error_message",
                ],
            ),
        )
        ImportRun.objects.filter(id=import_run.id).update(
            status=ImportRun.Status.COMPLETED,
            created_count=stats["processed"],
            skipped_count=stats["skipped"],
            failed_count=stats["errors"],
            finished_at=timezone.now(),
        )

        _enqueue_koito_music_enrichment(user_id)
        logger.info(
            "Koito history import for user %s: processed=%s skipped=%s errors=%s",
            user_id,
            stats["processed"],
            stats["skipped"],
            stats["errors"],
        )
        return {
            "message": (
                f"Imported {stats['processed']} Koito listen(s). "
                "Music enrichment queued."
            ),
        }
    finally:
        cache.delete(lock_key)
