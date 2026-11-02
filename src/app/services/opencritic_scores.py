"""Match games to OpenCritic and keep their stored scores fresh.

Quota is spent in two places only: when someone opens a game's page, and in
the hour before the daily quota resets, when whatever is left would otherwise
be wasted. A search is the scarce call, so a matched ID is saved as soon as it
is found and never searched for again.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import timedelta

from django.core.cache import cache
from django.db.models import F, Q
from django.utils import timezone

from app.models import Item, MediaTypes
from app.providers import opencritic

logger = logging.getLogger(__name__)

MATCHED_REFRESH_AGE = timedelta(days=7)
UNMATCHED_RETRY_AGE = timedelta(days=30)
BACKFILL_WINDOW_SECONDS = 60 * 60
QUEUE_LOCK_KEY = "opencritic_refresh:{item_id}"
QUEUE_LOCK_SECONDS = 60 * 15

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _normalize(title):
    text = unicodedata.normalize("NFKD", title or "")
    text = text.encode("ascii", "ignore").decode().lower()
    return _NON_ALNUM_RE.sub(" ", text).strip()


def needs_refresh(item, now=None):
    """Return whether a game's stored OpenCritic data is missing or stale."""
    if item is None or item.media_type != MediaTypes.GAME.value:
        return False
    if item.opencritic_checked_at is None:
        return True
    now = now or timezone.now()
    max_age = MATCHED_REFRESH_AGE if item.opencritic_id else UNMATCHED_RETRY_AGE
    return now - item.opencritic_checked_at >= max_age


def pick_match(title, results):
    """Return the one result whose name matches the title exactly, else None.

    Two exact matches (a remake sharing its original's name) are ambiguous, and
    a wrong score is worse than none, so neither is picked.
    """
    wanted = _normalize(title)
    matches = [
        result
        for result in results
        if isinstance(result, dict)
        and result.get("id")
        and _normalize(result.get("name")) == wanted
    ]
    if len(matches) != 1:
        return None
    return int(matches[0]["id"])


def refresh_item(item):
    """Fetch and store OpenCritic data for one game.

    Returns "updated", "unmatched" or "skipped". Raises
    ``opencritic.QuotaExhaustedError`` when the day's quota runs out, after
    saving anything already paid for.
    """
    if not opencritic.is_configured() or not needs_refresh(item):
        return "skipped"

    if not item.opencritic_id:
        match_id = pick_match(item.title, opencritic.search(item.title))
        if match_id is None:
            item.opencritic_checked_at = timezone.now()
            item.save(update_fields=["opencritic_checked_at"])
            return "unmatched"
        # Saved before the next call so the search is never paid for twice.
        item.opencritic_id = match_id
        item.save(update_fields=["opencritic_id"])

    fields = opencritic.game(item.opencritic_id)
    for name, value in fields.items():
        setattr(item, name, value)
    item.opencritic_checked_at = timezone.now()
    item.save(update_fields=[*fields, "opencritic_checked_at"])
    return "updated"


def queue_refresh(item, user=None):
    """Queue a background refresh for a game page, at most once per window.

    The viewer's personal key, when they have one, is the key spent.
    """
    if not needs_refresh(item) or not opencritic.is_configured():
        return False
    quotas = (
        (opencritic.QUOTA_REQUESTS,)
        if item.opencritic_id
        else (opencritic.QUOTA_SEARCHES, opencritic.QUOTA_REQUESTS)
    )
    if not opencritic.has_quota(*quotas):
        return False
    lock_key = QUEUE_LOCK_KEY.format(item_id=item.id)
    if not cache.add(lock_key, True, timeout=QUEUE_LOCK_SECONDS):
        return False
    try:
        from app.tasks_opencritic import refresh_item_opencritic_score

        refresh_item_opencritic_score.delay(
            item.id,
            user_id=getattr(user, "id", None),
        )
    except Exception:
        cache.delete(lock_key)
        logger.warning(
            "opencritic_refresh_schedule_failed item_id=%s",
            item.id,
            exc_info=True,
        )
        return False
    return True


def backfill_candidates(now=None):
    """Return tracked games that need data, never-checked first."""
    now = now or timezone.now()
    return (
        Item.objects.filter(media_type=MediaTypes.GAME.value, game__isnull=False)
        .filter(
            Q(opencritic_checked_at__isnull=True)
            | Q(
                opencritic_id__isnull=False,
                opencritic_checked_at__lte=now - MATCHED_REFRESH_AGE,
            )
            | Q(
                opencritic_id__isnull=True,
                opencritic_checked_at__lte=now - UNMATCHED_RETRY_AGE,
            ),
        )
        .distinct()
        .order_by(F("opencritic_checked_at").asc(nulls_first=True), "-id")
    )


def backfill():
    """Spend the quota left before today's reset. Returns games refreshed."""
    if not opencritic.is_configured():
        return 0
    if opencritic.seconds_until_reset() > BACKFILL_WINDOW_SECONDS:
        return 0

    refreshed = 0
    for item in backfill_candidates().iterator():
        if not opencritic.has_quota(opencritic.QUOTA_REQUESTS):
            break
        if not item.opencritic_id and not opencritic.has_quota(
            opencritic.QUOTA_SEARCHES,
        ):
            # Out of searches, but matched games can still be refreshed.
            continue
        try:
            result = refresh_item(item)
        except opencritic.QuotaExhaustedError:
            break
        except Exception:
            logger.warning(
                "opencritic_backfill_item_failed item_id=%s",
                item.id,
                exc_info=True,
            )
            continue
        if result != "skipped":
            refreshed += 1
    return refreshed
