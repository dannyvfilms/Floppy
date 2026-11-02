"""Celery tasks for automatic Jellyfin watch-history import.

No manual TSV export/upload required. Two tiers, tried in order for each run:

1. Playback Reporting plugin REST API (``submit_custom_query``) -- full
   per-play history with stable rowids, but only reachable with an admin
   API key and the plugin installed.
2. Core Jellyfin API UserData backfill -- one watch event per played item,
   works with any connected account, used as the fallback when tier 1
   isn't reachable.
"""

import logging

from celery import shared_task
from django.contrib.auth import get_user_model
from django.utils import timezone

import events
from app.mixins import disable_fetch_releases
from integrations.imports.helpers import MediaImportError, decrypt_or_raise
from integrations.imports.jellyfin_playback_reporting import (
    JellyfinPlaybackReportingImporter,
)
from integrations.jellyfin_client import JellyfinClient, JellyfinClientError
from integrations.tasks import _jellyfin_health

logger = logging.getLogger(__name__)

JELLYFIN_PULL_TASK_NAME = "Pull Jellyfin watch history"
JELLYFIN_PULL_INTERVAL_MINUTES = 240
PLAYBACK_ACTIVITY_PAGE_SIZE = 2000
# Safety cap on pages fetched per run; a very large backlog just continues
# on the next scheduled/manual run rather than blocking the worker.
PLAYBACK_ACTIVITY_MAX_PAGES = 25

ACCOUNT_UPDATE_FIELDS = [
    "playback_reporting_available",
    "playback_reporting_last_rowid",
    "library_backfill_completed_at",
    "last_pull_at",
    "last_pull_error_message",
    "connection_broken",
]


def _has_prior_history(account) -> bool:
    """Return True when older, differently-identified imports already exist.

    A manual Playback Reporting TSV upload identifies rows by content hash;
    the library backfill tier identifies rows by Jellyfin item id. Neither
    matches the REST API tier's rowid-based identity, so a first-ever API
    pull that started from rowid 0 would re-import all of that history as
    "new" duplicates. When either has already happened, the first API pull
    instead starts from the current max rowid and only picks up new plays.
    """
    from integrations.models import ImportRun

    if account.library_backfill_completed_at is not None:
        return True
    return ImportRun.objects.filter(
        user_id=account.user_id,
        source="jellyfin_playback_reporting",
        status=ImportRun.Status.COMPLETED,
    ).exists()


def _fetch_new_playback_activity(client, account) -> list[dict]:
    """Page through new Playback Reporting rows since the stored cursor."""
    since_rowid = account.playback_reporting_last_rowid
    if since_rowid is None:
        since_rowid = (
            client.fetch_max_playback_activity_rowid()
            if _has_prior_history(account)
            else 0
        )

    entries: list[dict] = []
    for _ in range(PLAYBACK_ACTIVITY_MAX_PAGES):
        page = client.fetch_playback_activity(since_rowid, PLAYBACK_ACTIVITY_PAGE_SIZE)
        if not page:
            break
        entries.extend(page)
        since_rowid = max(entry["rowid"] for entry in page)
        if len(page) < PLAYBACK_ACTIVITY_PAGE_SIZE:
            break
    return entries


def _run_playback_activity_pull(user, account, client) -> dict | None:
    """Try the Playback Reporting API tier; return None if it's unavailable."""
    # Reprobe whenever it isn't confirmed available, not just on the very
    # first run: a prior "unavailable" result can be a transient outage, a
    # plugin installed after the fact, or a key that later gained admin
    # access. The probe is a single cheap GET, so retrying it every run
    # this tier is skipped is worth the self-healing.
    available = account.playback_reporting_available
    if not available:
        available = client.probe_playback_reporting()
    if not available:
        return None

    try:
        entries = _fetch_new_playback_activity(client, account)
    except JellyfinClientError as exc:
        # The probe endpoint can succeed while the actual query endpoint
        # still fails (e.g. a broken/incompatible Playback Reporting plugin
        # on the user's server) -- treat it the same as "unavailable" and
        # fall back to the library backfill tier instead of failing the run.
        logger.warning(
            "Jellyfin Playback Reporting fetch failed for user %s, "
            "falling back to library backfill: %s",
            user.id,
            exc,
        )
        return None

    importer = JellyfinPlaybackReportingImporter(user, account)
    counts, warnings, max_rowid = importer.import_activity_rows(entries)

    account.playback_reporting_available = True
    if max_rowid is not None:
        account.playback_reporting_last_rowid = max_rowid
    elif account.playback_reporting_last_rowid is None:
        # No rows were returned at all on the very first pull; record 0 so
        # future runs poll for new rows instead of re-running the max-rowid
        # lookup (or a full backfill) every time.
        account.playback_reporting_last_rowid = 0

    return {"tier": "playback_reporting", "counts": counts, "warnings": warnings}


def _run_library_backfill(user, account) -> dict:
    """Fall back to the core-API UserData backfill tier."""
    importer = JellyfinPlaybackReportingImporter(user, account)
    counts, warnings = importer.import_library_backfill()
    account.playback_reporting_available = False
    account.library_backfill_completed_at = timezone.now()
    return {"tier": "library_backfill", "counts": counts, "warnings": warnings}


def _format_pull_message(result: dict) -> str:
    counts = result["counts"]
    imported = sum(counts.values())
    tier_label = (
        "Playback Reporting history"
        if result["tier"] == "playback_reporting"
        else "current watched state"
    )
    message = (
        f"Jellyfin auto-import ({tier_label}): imported {imported} new play(s)."
        if imported
        else f"Jellyfin auto-import ({tier_label}): nothing new to import."
    )
    if result["warnings"]:
        message = f"{message}\n{result['warnings']}"
    return message


@shared_task(bind=True, name=JELLYFIN_PULL_TASK_NAME)
def pull_jellyfin_history(self, user_id):
    """Pull Jellyfin watch history automatically -- no manual export needed."""
    user = get_user_model().objects.get(id=user_id)
    account = getattr(user, "jellyfin_account", None)
    if not _jellyfin_health.has_credentials(account):
        msg = "Connect Jellyfin before importing history."
        raise MediaImportError(msg)

    try:
        api_key = decrypt_or_raise(account.api_key)
        client = JellyfinClient(
            account.base_url,
            api_key,
            account.jellyfin_user_id or None,
        )
        if not _jellyfin_health.reprobe_if_broken(
            account,
            error_field="last_pull_error_message",
            client=client,
        ):
            return "Skipped: Jellyfin rejected the API key. Reconnect Jellyfin."

        # A large initial backfill can complete thousands of movies/episodes
        # in one run; each one would otherwise trigger its own per-item
        # Item.fetch_releases()/reload_calendar task. Suppress those (same
        # as import_media()) and do a single bounded catch-up afterward.
        with disable_fetch_releases():
            result = _run_playback_activity_pull(user, account, client)
            if result is None:
                account.playback_reporting_available = False
                result = _run_library_backfill(user, account)
    except (JellyfinClientError, MediaImportError) as exc:
        logger.warning("Jellyfin history pull failed for user %s: %s", user_id, exc)
        _jellyfin_health.handle_failure(
            self,
            account,
            exc,
            error_field="last_pull_error_message",
        )
        raise

    account.last_pull_at = timezone.now()
    account.last_pull_error_message = ""
    account.connection_broken = False
    account.save(update_fields=ACCOUNT_UPDATE_FIELDS)

    if sum(result["counts"].values()):
        events.tasks.reload_calendar.delay()

    return _format_pull_message(result)
