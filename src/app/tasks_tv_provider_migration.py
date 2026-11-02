"""Explicit TV provider moves.

Changing the default provider never moves existing shows. The user asks for a
move from Settings, or from one show's Match & Ordering tab. The batch task
below is kept as a manual maintenance entry point and is deliberately not on
the Celery beat schedule: an automatic nightly move made a preference change
silently rewrite the library.
"""

from __future__ import annotations

import logging

from celery import shared_task

from app.interactive_requests import interactive_request_active

logger = logging.getLogger(__name__)

# The beat runs this daily and the shared backoff caps at one day, so without a
# longer floor an unresolvable backlog is due again on every nightly run - it
# keeps filling the id-ordered batch and keeps starving newly tracked shows,
# which is the whole thing the backoff is here to stop.
_MIGRATION_RETRY_SECONDS = 7 * 24 * 60 * 60


def _migration_candidates_queryset():
    from app.models import Item, MediaTypes, MetadataBackfillField, Sources
    from app.tasks_backfill_state import _apply_backfill_state_filters

    queryset = (
        Item.objects.filter(
            media_type=MediaTypes.TV.value,
            source=Sources.TMDB.value,
            metadata_migration_pinned_at__isnull=True,
            tv__user__tv_metadata_source_default=Sources.TVDB.value,
            tv__user__tv_auto_move_to_default_provider=True,
        )
        .exclude(library_media_type=MediaTypes.ANIME.value)
        .distinct()
        .order_by("id")
    )
    # A show TVDB has no resolvable id for is not pinned - TMDB may publish
    # the external id later - but it also must not be retried every single
    # day. Worse, the batch is taken in id order, so once enough unresolvable
    # shows accumulated at the front they filled the batch and newly tracked
    # shows never got a turn at all.
    return _apply_backfill_state_filters(
        queryset,
        MetadataBackfillField.TVDB_MIGRATION.value,
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
    from app.models import MetadataBackfillField
    from app.providers import tvdb
    from app.services.tv_provider_migration import (
        migrate_tv_item_to_tvdb,
    )
    from app.tasks_backfill_state import (
        _record_backfill_failure,
        _record_backfill_pending,
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
            _record_backfill_failure(
                item,
                MetadataBackfillField.TVDB_MIGRATION.value,
                "migration crashed",
            )
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
            # Not migratable today and not pinned - back off instead of
            # re-asking the providers about it again tomorrow.
            skipped += 1
            _record_backfill_pending(
                item,
                MetadataBackfillField.TVDB_MIGRATION.value,
                result.reason,
                min_delay_seconds=_MIGRATION_RETRY_SECONDS,
            )

    return {
        "migrated": migrated,
        "pinned": pinned,
        "skipped": skipped,
        "errored": errored,
        "remaining": _migration_candidates_queryset().count(),
    }


@shared_task(name="Move TV library to preferred provider")
def move_user_tv_library_task(user_id: int):
    """Move one user's tracked shows to their default TV provider, on request.

    Only runs when the user explicitly asks for it. A show that cannot move
    safely (no match, or a tracked episode missing on the other provider) is
    left untouched and named in the result.
    """
    from django.contrib.auth import get_user_model

    from app.models import MediaTypes
    from app.providers.services import ProviderAPIError
    from app.services import library_migration, metadata_resolution
    from app.services.library_migration import LibraryMigrationError

    user = get_user_model().objects.filter(pk=user_id).first()
    if user is None:
        return {"moved": 0, "skipped": 0, "unresolved": []}

    target_source = metadata_resolution.metadata_default_source(
        user,
        MediaTypes.TV.value,
    )
    moved = 0
    unresolved = []
    for item in list(library_migration.tv_items_to_move(user, target_source)):
        try:
            library_migration.switch_tv_provider(user, item)
        except (LibraryMigrationError, ProviderAPIError) as error:
            unresolved.append(item.title)
            logger.warning("Left %r on its current provider: %s", item.title, error)
        except Exception:
            unresolved.append(item.title)
            logger.warning("Provider move crashed for %r", item.title, exc_info=True)
        else:
            moved += 1

    return {"moved": moved, "skipped": len(unresolved), "unresolved": unresolved}
