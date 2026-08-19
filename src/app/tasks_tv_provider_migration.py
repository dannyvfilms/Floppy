"""Celery task migrating TMDB-tracked TV shows to TVDB when preferred (#387)."""

from __future__ import annotations

import logging

from celery import shared_task

from app.interactive_requests import interactive_request_active

logger = logging.getLogger(__name__)


def _migration_candidates_queryset():
    from app.models import Item, MediaTypes, Sources

    return (
        Item.objects.filter(
            media_type=MediaTypes.TV.value,
            source=Sources.TMDB.value,
            metadata_migration_pinned_at__isnull=True,
            tv__user__tv_metadata_source_default=Sources.TVDB.value,
        )
        .exclude(library_media_type=MediaTypes.ANIME.value)
        .distinct()
        .order_by("id")
    )


@shared_task(name="Migrate TV shows to preferred metadata provider")
def migrate_tv_shows_to_preferred_provider_task(batch_size: int = 200):
    """Re-key a batch of TMDB-tracked TV shows to TVDB where it's safe to do so.

    Only shows tracked by at least one user who prefers TVDB are considered.
    Each show is migrated in place (see
    app.services.tv_provider_migration.migrate_tv_item_to_tvdb) when its
    season/episode structure matches TVDB exactly; otherwise it's pinned so
    future runs stop retrying it. Best-effort — a failure on one show never
    blocks the rest of the batch.
    """
    from app.providers import tvdb
    from app.services.tv_provider_migration import (
        migrate_tv_item_to_tvdb,
    )

    if not tvdb.enabled():
        return {"skipped": True, "reason": "tvdb_not_configured"}

    if interactive_request_active():
        logger.info("tv_provider_migration_skipped reason=interactive_request_active")
        return {"skipped": True, "reason": "interactive_request_active"}

    migrated = 0
    pinned = 0
    skipped = 0
    errored = 0

    for item in _migration_candidates_queryset()[:batch_size]:
        try:
            result = migrate_tv_item_to_tvdb(item)
        except Exception:
            errored += 1
            logger.warning(
                "TV provider migration crashed for item %s (%s)",
                item.pk,
                item.title,
                exc_info=True,
            )
            continue

        if result.migrated:
            migrated += 1
        elif item.metadata_migration_pinned_at is not None:
            pinned += 1
        else:
            skipped += 1

    return {
        "migrated": migrated,
        "pinned": pinned,
        "skipped": skipped,
        "errored": errored,
        "remaining": _migration_candidates_queryset().count(),
    }
