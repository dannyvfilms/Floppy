"""Celery tasks for syncing watch status with MyAnimeList.

These tasks push Floppy's status/progress/score to MyAnimeList. A full sync
first adopts higher MAL progress and missing ratings when the account allows
it; the full MAL import stays in integrations.imports.mal.
"""

import logging
from datetime import timedelta

import requests
from celery import shared_task
from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import models
from django.utils import timezone

from app.providers import services
from integrations import connection_health, mal_sync
from integrations.models import STALE_FULL_SYNC_AGE, MALAccount, MALFullSyncStatus

logger = logging.getLogger(__name__)

MAL_SYNC_TASK_NAME = "Sync status to MyAnimeList"
MAL_FULL_SYNC_TASK_NAME = "Full sync to MyAnimeList"
HEARTBEAT_INTERVAL = timedelta(minutes=1)


@shared_task(name="Preview sync to MyAnimeList", ignore_result=False, bind=True)
def preview_mal_sync(self, user_id):
    """Build a read-only preview outside the web request timeout."""
    try:
        account = MALAccount.objects.select_related("user").get(user_id=user_id)
    except MALAccount.DoesNotExist:
        return {"error": "Connect a MyAnimeList account first."}
    if account.connection_broken or not account.sync_enabled:
        return {"error": "Reconnect or enable your MyAnimeList account first."}
    issues = []
    def report(percent, message):
        if not self.request.id:
            return
        self.update_state(
            state="PROGRESS",
            meta={"percent": percent, "message": message},
        )
    try:
        changes = mal_sync.preview_full_sync(
            account.user,
            account,
            mapping_issues=issues,
            progress_callback=report,
        )
    except mal_sync.MALAuthError as error:
        return {"error": str(error)}
    except services.ProviderAPIError:
        return {"error": "Couldn't load MyAnimeList data or anime mappings. Please try again."}
    except Exception:
        logger.exception("MyAnimeList preview failed for user %s", user_id)
        return {"error": "MyAnimeList preview failed. Check the worker logs for details."}
    return {"changes": changes, "count": len(changes), "mapping_issues": issues}


def _mark_connection_broken(mal_account, message):
    """Disable sync and record why, matching the LastFM/Koito account pattern.

    Missing client credentials only record the message: MAL rejected
    nothing, so the connection works again once they're added back.
    """
    if isinstance(message, mal_sync.MALNotConfiguredError):
        connection_health.record_failure(mal_account, message, auth=False)
        return
    mal_account.sync_enabled = False
    mal_account.last_failed_at = timezone.now()
    mal_account.save(update_fields=["sync_enabled", "last_failed_at", "updated_at"])
    connection_health.record_failure(mal_account, message, auth=True)


def _heartbeat(mal_account):
    """Return a progress callback that keeps a long entry build from looking stale.

    Building grouped anime entries can take minutes before the first push
    saves progress; reconcile_stale_full_sync would otherwise fail a live sync.
    """
    last_beat = timezone.now()

    def beat(*_args):
        nonlocal last_beat
        now = timezone.now()
        if now - last_beat >= HEARTBEAT_INTERVAL:
            MALAccount.objects.filter(pk=mal_account.pk).update(updated_at=now)
            last_beat = now

    return beat


def _claim_full_sync(mal_account, queued):
    """Mark the account's full sync RUNNING for this task, if it may start.

    A task the page queued (queued=True) takes over the QUEUED row the page
    wrote. Any other run, such as the schedule, only starts when no sync is
    queued or running, so it can't replace a user's selective sync. A row
    whose heartbeat went quiet is claimable either way.
    """
    active = [MALFullSyncStatus.QUEUED, MALFullSyncStatus.RUNNING]
    claimable = (
        models.Q(full_sync_status=MALFullSyncStatus.QUEUED)
        if queued
        else ~models.Q(full_sync_status__in=active)
    )
    stale_before = timezone.now() - STALE_FULL_SYNC_AGE
    return MALAccount.objects.filter(pk=mal_account.pk).filter(
        claimable | models.Q(updated_at__lt=stale_before),
    ).update(
        full_sync_status=MALFullSyncStatus.RUNNING,
        full_sync_started_at=timezone.now(),
        full_sync_completed_at=None,
        updated_at=timezone.now(),
    )


@shared_task(
    name=MAL_SYNC_TASK_NAME,
    autoretry_for=(services.ProviderAPIError,),
    retry_backoff=30,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
)
def sync_mal_status(media_type, media_id, clear_score=False):
    """Push a single anime/manga entry's status, progress and score to MyAnimeList.

    Runs after every save() of a MAL-backed Anime/Manga instance (see the
    save() overrides in app.models.media). Silently no-ops if the entry, the
    user's MAL connection, or sync itself is gone by the time this runs -
    it's a best-effort mirror of Floppy's data, not a source of truth. Also
    no-ops if the account has turned off per-item pushes specifically
    (mal_account.per_item_sync_enabled), independent of the overall
    connection and of "Sync All Now"/scheduled full syncs.

    `clear_score` is set when the save removed the entry's rating, so MAL's
    copy is cleared too instead of being pulled back later.
    """
    model = apps.get_model(app_label="app", model_name=media_type)
    # Anime's default manager hides rows auto-migrated to episode tracking on
    # completion; all_objects (Anime only) still finds them for this one-off push.
    manager = model.all_objects if hasattr(model, "all_objects") else model.objects

    try:
        media = manager.select_related("item", "user", "user__mal_account").get(
            pk=media_id,
        )
    except model.DoesNotExist:
        logger.info(
            "%s %s no longer exists, skipping MyAnimeList sync",
            media_type,
            media_id,
        )
        return

    try:
        mal_account = media.user.mal_account
    except MALAccount.DoesNotExist:
        return

    if not mal_account.sync_enabled or mal_account.connection_broken:
        return

    if not mal_account.per_item_sync_enabled:
        return

    if media.status is None and media_type != "tv":
        return

    try:
        if media_type == "anime" and media.migrated_to_item_id:
            media = apps.get_model("app", "TV").objects.filter(
                user=media.user, item_id=media.migrated_to_item_id,
            ).first()
            if media is None:
                return
            media_type = "tv"
        if media_type != "tv":
            # Push the row full sync would push, so saving a rewatch row
            # doesn't replace a completed MAL entry with the rewatch's count.
            media = (
                model.objects.filter(
                    user=media.user, item=media.item, status__isnull=False,
                )
                .select_related("item")
                .order_by("-progress", "pk")
                .first()
            ) or media
        entries = (
            mal_sync.grouped_sync_entries(media.user, tv=media)
            if media_type == "tv" else [media]
        )
    except mal_sync.MALAuthError as error:
        _mark_connection_broken(mal_account, error)
        return

    clear_key = None
    clear_scopes = set()
    if media_type == "tv":
        # queue_grouped_sync flags a removed show or season rating here. The
        # flag stays until the push goes through, so a retry still clears it.
        clear_key = mal_sync.grouped_clear_score_key(media.pk)
        clear_scopes = set(cache.get(clear_key) or ())

    # A grouped show can span several MAL entries (one per cour). Each is
    # pushed on its own, so one that MAL rejects doesn't hold back the rest.
    retryable_error = None
    for entry in entries:
        try:
            # A removed show rating was every unrated cour's fallback; a
            # removed season rating only touches the cours it feeds.
            clears = clear_score or "show" in clear_scopes or bool(
                clear_scopes & set(getattr(entry, "grouped_seasons", ())),
            )
            mal_sync.push_status(entry, mal_account, clear_score=clears)
        except mal_sync.MALAuthError as error:
            _mark_connection_broken(mal_account, error)
            return
        except mal_sync.MALSyncMismatchError as error:
            # Not retryable: MAL echoed a response that doesn't match what was
            # sent, so retrying the same payload won't change the outcome.
            logger.warning(str(error))
        except services.ProviderAPIError as error:
            if error.status_code in {requests.codes.not_found, requests.codes.bad_request}:
                logger.warning(
                    "MyAnimeList rejected the update for %s (MAL ID %s): %s",
                    entry.item.title,
                    entry.item.media_id,
                    error,
                )
                continue
            retryable_error = retryable_error or error
    if retryable_error is not None:
        raise retryable_error
    if clear_scopes:
        # Only the scopes this push read: a rating removed while it ran is
        # left for the push that trigger queued.
        remaining = set(cache.get(clear_key) or ()) - clear_scopes
        if remaining:
            cache.set(
                clear_key, list(remaining), timeout=mal_sync.GROUPED_CLEAR_FLAG_SECONDS,
            )
        else:
            cache.delete(clear_key)


@shared_task(name=MAL_FULL_SYNC_TASK_NAME)
def bulk_sync_mal_status(user_id, selected=None, pull=None, queued=False):
    """Push every MAL-backed anime/manga entry's current status to MyAnimeList.

    Runs on demand (the "Sync All Now" button) rather than per save() - useful
    right after connecting an account with an existing library, or after a
    bulk import/restore, since those bypass save() and never queue a sync.

    `selected` limits the run to those `mal_sync.entry_key` values (None means
    every entry); entries whose key is in `pull` take MyAnimeList's values
    instead of pushing Floppy's. `queued` is set by the page that marked the
    sync QUEUED (see _claim_full_sync).
    """
    selected = None if selected is None else set(selected)
    pull = set(pull or ())
    try:
        user = get_user_model().objects.select_related("mal_account").get(pk=user_id)
    except get_user_model().DoesNotExist:
        return

    try:
        mal_account = user.mal_account
    except MALAccount.DoesNotExist:
        return

    if not mal_account.sync_enabled or mal_account.connection_broken:
        if not queued:
            # A scheduled run keeps the last real report instead of
            # replacing it on every tick while sync is off.
            return
        mal_account.full_sync_status = MALFullSyncStatus.FAILED
        mal_account.full_sync_results = [
            {
                "title": "MyAnimeList connection",
                "media_type": "Account",
                "mal_id": "",
                "outcome": "failed",
                "reason": "Sync was disabled or the account needs to be reconnected.",
            }
        ]
        mal_account.full_sync_total = 0
        mal_account.full_sync_processed = 0
        mal_account.full_sync_succeeded = 0
        mal_account.full_sync_failed = 1
        mal_account.full_sync_completed_at = timezone.now()
        mal_account.save(
            update_fields=[
                "full_sync_status",
                "full_sync_results",
                "full_sync_total",
                "full_sync_processed",
                "full_sync_succeeded",
                "full_sync_failed",
                "full_sync_completed_at",
                "updated_at",
            ]
        )
        return

    if not _claim_full_sync(mal_account, queued=queued):
        return

    remote_statuses = {}
    list_error = None
    pulls_enabled = (
        mal_account.pull_higher_progress_enabled or mal_account.pull_ratings_enabled
    )
    try:
        if pulls_enabled or pull:
            remote_statuses = {
                media_type: mal_sync._fetch_list_statuses(media_type, mal_account)
                for media_type in ("anime", "manga")
            }
        if pulls_enabled:
            # The sync pushes these entries itself; a per-item push per
            # pulled row would double the MAL calls.
            with mal_sync.suppress_per_item_push():
                mal_sync.pull_higher_mal_progress(
                    user, mal_account, remote_statuses, only=selected,
                )
    except mal_sync.MALAuthError as error:
        _mark_connection_broken(mal_account, error)
        mal_account.full_sync_status = MALFullSyncStatus.FAILED
        mal_account.full_sync_completed_at = timezone.now()
        mal_account.save(
            update_fields=["full_sync_status", "full_sync_completed_at", "updated_at"],
        )
        return
    except services.ProviderAPIError as error:
        if not remote_statuses:
            # Selected pulls fail with this error below, not as "not on
            # your list".
            list_error = error
        logger.warning(
            "Could not fetch MyAnimeList lists to check for a higher recorded "
            "progress before pushing",
        )

    if list_error is not None and mal_account.pull_higher_progress_enabled:
        # Pushing now could lower a count MAL has ahead of Floppy, which the
        # user asked to keep, so nothing is pushed until the lists load.
        mal_account.full_sync_status = MALFullSyncStatus.FAILED
        mal_account.full_sync_total = 0
        mal_account.full_sync_processed = 0
        mal_account.full_sync_succeeded = 0
        mal_account.full_sync_failed = 1
        mal_account.full_sync_completed_at = timezone.now()
        mal_account.full_sync_results = [{
            "title": "MyAnimeList lists",
            "media_type": "Anime",
            "mal_id": "",
            "outcome": "failed",
            "reason": (
                "Couldn't load your MyAnimeList lists, so nothing was pushed. "
                "Please try again."
            ),
        }]
        mal_account.save(update_fields=[
            "full_sync_status", "full_sync_total", "full_sync_processed",
            "full_sync_succeeded", "full_sync_failed", "full_sync_completed_at",
            "full_sync_results", "updated_at",
        ])
        return

    mapping_issues = []
    try:
        entries = mal_sync.full_sync_entries(
            user,
            mal_account,
            mapping_issues=mapping_issues,
            progress_callback=_heartbeat(mal_account),
        )
        if selected is not None:
            entries = [
                media for media in entries if mal_sync.entry_key(media) in selected
            ]
    except services.ProviderAPIError:
        mal_account.full_sync_status = MALFullSyncStatus.FAILED
        mal_account.full_sync_total = 0
        mal_account.full_sync_processed = 0
        mal_account.full_sync_succeeded = 0
        mal_account.full_sync_failed = 1
        mal_account.full_sync_completed_at = timezone.now()
        mal_account.full_sync_results = [{
            "title": "Anime mappings",
            "media_type": "Anime",
            "mal_id": "",
            "outcome": "failed",
            "reason": "Could not load anime mappings or metadata. Please try again.",
        }]
        mal_account.save(update_fields=[
            "full_sync_status", "full_sync_total", "full_sync_processed",
            "full_sync_succeeded", "full_sync_failed", "full_sync_completed_at",
            "full_sync_results", "updated_at",
        ])
        return
    mal_account.full_sync_status = MALFullSyncStatus.RUNNING
    mal_account.full_sync_total = len(entries)
    mal_account.full_sync_processed = 0
    mal_account.full_sync_succeeded = 0
    mal_account.full_sync_failed = 0
    mal_account.full_sync_results = mapping_issues
    mal_account.full_sync_started_at = timezone.now()
    mal_account.full_sync_completed_at = None
    mal_account.save(
        update_fields=[
            "full_sync_status",
            "full_sync_total",
            "full_sync_processed",
            "full_sync_succeeded",
            "full_sync_failed",
            "full_sync_results",
            "full_sync_started_at",
            "full_sync_completed_at",
            "updated_at",
        ]
    )

    synced = 0
    failed = 0
    results = list(mapping_issues)
    for media in entries:
        is_pull = mal_sync.entry_key(media) in pull
        result = {
            "title": media.item.title,
            "media_type": media._meta.verbose_name.title(),
            "mal_id": str(media.item.media_id),
        }
        if is_pull:
            # Retry failed repeats the user's choice instead of pushing.
            result["direction"] = "pull"
        try:
            current = remote_statuses.get(media.item.media_type, {}).get(
                str(media.item.media_id),
            )
            if is_pull:
                with mal_sync.suppress_per_item_push():
                    mal_sync.pull_mal_entry(media, current, list_error=list_error)
                result["reason"] = "Pulled from MyAnimeList"
            else:
                if pulls_enabled:
                    with mal_sync.suppress_per_item_push():
                        mal_sync.pull_grouped_rating(media, current, mal_account)
                mal_sync.push_status(media, mal_account)
                result["reason"] = ""
            synced += 1
            result["outcome"] = "succeeded"
        except mal_sync.MALAuthError as error:
            failed += 1
            result["outcome"] = "failed"
            result["reason"] = str(error)[:500]
            results.append(result)
            _mark_connection_broken(mal_account, error)
            mal_account.full_sync_status = MALFullSyncStatus.FAILED
            mal_account.full_sync_processed = synced + failed
            mal_account.full_sync_succeeded = synced
            mal_account.full_sync_failed = failed
            mal_account.full_sync_results = results
            mal_account.full_sync_completed_at = timezone.now()
            mal_account.save(
                update_fields=[
                    "full_sync_status",
                    "full_sync_processed",
                    "full_sync_succeeded",
                    "full_sync_failed",
                    "full_sync_results",
                    "full_sync_completed_at",
                    "updated_at",
                ]
            )
            return
        except mal_sync.MALSyncMismatchError as error:
            failed += 1
            result["outcome"] = "failed"
            result["reason"] = str(error)[:500]
        except services.ProviderAPIError as error:
            logger.warning(
                "Full MyAnimeList sync: failed to push %s (MAL ID %s): %s",
                media.item.title,
                media.item.media_id,
                error,
            )
            failed += 1
            result["outcome"] = "failed"
            result["reason"] = str(error)[:500]
        except Exception:
            logger.exception(
                "Full MyAnimeList sync: unexpected failure pushing %s (MAL ID %s)",
                media.item.title,
                media.item.media_id,
            )
            failed += 1
            result["outcome"] = "failed"
            result["reason"] = "Unexpected error; check the server logs."

        results.append(result)
        mal_account.full_sync_processed = synced + failed
        mal_account.full_sync_succeeded = synced
        mal_account.full_sync_failed = failed
        mal_account.full_sync_results = results
        mal_account.save(
            update_fields=[
                "full_sync_processed",
                "full_sync_succeeded",
                "full_sync_failed",
                "full_sync_results",
                "updated_at",
            ]
        )

    logger.info(
        "Full MyAnimeList sync for %s: %s updated, %s failed (%s total)",
        user,
        synced,
        failed,
        len(entries),
    )
    mal_account.full_sync_status = MALFullSyncStatus.COMPLETED
    mal_account.full_sync_completed_at = timezone.now()
    if failed:
        # A per-item failure (e.g. one deleted MAL entry) isn't a broken
        # connection - leave sync_enabled/connection_broken alone, just
        # surface it the same way an ongoing sync error would show up.
        mal_account.last_error_message = (
            f"Last full sync: {failed} of {len(entries)} entries failed to "
            "update on MyAnimeList - check server logs for details."
        )[:500]
        mal_account.last_failed_at = timezone.now()
    else:
        mal_account.last_error_message = ""
        mal_account.last_failed_at = None
    mal_account.save(
        update_fields=[
            "full_sync_status",
            "full_sync_completed_at",
            "last_error_message",
            "last_failed_at",
            "updated_at",
        ]
    )


@shared_task(name="Retry failed MyAnimeList entries")
def retry_failed_mal_status(user_id, queued=False):
    """Retry only the entries marked "failed" on the last full sync.

    Recomputes eligible entries the same way a full sync does (so a fixed
    mapping or clamp takes effect), but only pushes the MAL ids already
    marked failed, updating those result rows in place. Succeeded and
    skipped rows are left untouched.
    """
    try:
        user = get_user_model().objects.select_related("mal_account").get(pk=user_id)
    except get_user_model().DoesNotExist:
        return

    try:
        mal_account = user.mal_account
    except MALAccount.DoesNotExist:
        return

    def release_claim():
        # A retry that doesn't run must not leave the page's QUEUED row,
        # which refuses every sync until it goes stale.
        if queued:
            MALAccount.objects.filter(
                pk=mal_account.pk, full_sync_status=MALFullSyncStatus.QUEUED,
            ).update(full_sync_status=MALFullSyncStatus.FAILED)

    if not mal_account.sync_enabled or mal_account.connection_broken:
        release_claim()
        return

    failed_keys = {
        (result.get("media_type"), result.get("mal_id"))
        for result in mal_sync.retryable_failures(mal_account)
    }
    if not failed_keys:
        release_claim()
        return

    if not _claim_full_sync(mal_account, queued=queued):
        return
    mal_account.refresh_from_db()

    mapping_issues = []
    try:
        entries = mal_sync.full_sync_entries(
            user,
            mal_account,
            mapping_issues=mapping_issues,
            progress_callback=_heartbeat(mal_account),
        )
    except services.ProviderAPIError:
        mal_account.full_sync_status = MALFullSyncStatus.FAILED
        mal_account.full_sync_completed_at = timezone.now()
        mal_account.save(
            update_fields=[
                "full_sync_status", "full_sync_completed_at", "updated_at",
            ],
        )
        return

    retryable = [
        media
        for media in entries
        if (media._meta.verbose_name.title(), str(media.item.media_id)) in failed_keys
    ]
    results = list(mal_account.full_sync_results)
    results_by_key = {
        (result.get("media_type"), result.get("mal_id")): result for result in results
    }

    def save_progress():
        mal_account.full_sync_succeeded = sum(
            1 for result in results if result.get("outcome") == "succeeded"
        )
        mal_account.full_sync_failed = sum(
            1 for result in results if result.get("outcome") == "failed"
        )
        mal_account.full_sync_results = results
        mal_account.save(
            update_fields=[
                "full_sync_status",
                "full_sync_succeeded",
                "full_sync_failed",
                "full_sync_results",
                "full_sync_completed_at",
                "updated_at",
            ],
        )

    remote_statuses = {}
    for media in retryable:
        key = (media._meta.verbose_name.title(), str(media.item.media_id))
        result = results_by_key.get(key)
        if result is None:
            continue
        try:
            if result.get("direction") == "pull":
                media_type = media.item.media_type
                if media_type not in remote_statuses:
                    remote_statuses[media_type] = mal_sync._fetch_list_statuses(
                        media_type, mal_account,
                    )
                with mal_sync.suppress_per_item_push():
                    mal_sync.pull_mal_entry(
                        media, remote_statuses[media_type].get(str(media.item.media_id)),
                    )
                result["reason"] = "Pulled from MyAnimeList"
            else:
                mal_sync.push_status(media, mal_account)
                result["reason"] = ""
            result["outcome"] = "succeeded"
        except mal_sync.MALAuthError as error:
            result["outcome"] = "failed"
            result["reason"] = str(error)[:500]
            _mark_connection_broken(mal_account, error)
            mal_account.full_sync_status = MALFullSyncStatus.FAILED
            mal_account.full_sync_completed_at = timezone.now()
            save_progress()
            return
        except mal_sync.MALSyncMismatchError as error:
            result["outcome"] = "failed"
            result["reason"] = str(error)[:500]
        except services.ProviderAPIError as error:
            logger.warning(
                "Retry MyAnimeList sync: failed to push %s (MAL ID %s): %s",
                media.item.title,
                media.item.media_id,
                error,
            )
            result["outcome"] = "failed"
            result["reason"] = str(error)[:500]
        except Exception:
            logger.exception(
                "Retry MyAnimeList sync: unexpected failure pushing %s (MAL ID %s)",
                media.item.title,
                media.item.media_id,
            )
            result["outcome"] = "failed"
            result["reason"] = "Unexpected error; check the server logs."

        save_progress()

    mal_account.full_sync_status = MALFullSyncStatus.COMPLETED
    mal_account.full_sync_completed_at = timezone.now()
    remaining_failed = sum(1 for result in results if result.get("outcome") == "failed")
    if remaining_failed:
        mal_account.last_error_message = (
            f"Retry: {remaining_failed} entries still failed - check server "
            "logs for details."
        )[:500]
        mal_account.last_failed_at = timezone.now()
    else:
        mal_account.last_error_message = ""
        mal_account.last_failed_at = None
    mal_account.save(
        update_fields=[
            "full_sync_status",
            "full_sync_completed_at",
            "last_error_message",
            "last_failed_at",
            "updated_at",
        ]
    )
