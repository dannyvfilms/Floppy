"""Celery task for syncing video game cast/crew from IMDB public datasets."""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="Refresh IMDB game credits from datasets")
def refresh_imdb_game_credits_from_datasets():
    """Resolve game IMDB ids and sync cast/crew for the ones that matched.

    Best-effort: games are matched to IMDB's "videoGame" titles by exact
    normalized title + release year (see app.services.imdb_game_credits), so
    coverage is intentionally limited to unambiguous matches.
    """
    from app.providers import imdb_datasets
    from app.services import imdb_game_credits

    resolved = imdb_game_credits.resolve_game_imdb_ids()
    synced = 0
    error = None

    tconsts = {item.provider_external_ids["imdb_id"] for item in _resolved_game_items()}
    if tconsts:
        try:
            principals = imdb_datasets.download_principals(tconsts)
            nconsts = {row["nconst"] for rows in principals.values() for row in rows}
            names = imdb_datasets.download_names(nconsts)
            synced = imdb_game_credits.sync_game_credits_from_imdb(principals, names)
        except Exception as exc:
            logger.warning("imdb_game_credits: failed to sync credits: %s", exc)
            error = str(exc)

    # Independent of whether there was new credit syncing to do above — older
    # runs may have left behind missing studios or missing person profile data.
    studios_backfilled = imdb_game_credits.backfill_missing_game_studios()
    profiles_backfilled = imdb_game_credits.backfill_missing_person_profiles()

    result = {
        "resolved": resolved,
        "synced": synced,
        "studios_backfilled": studios_backfilled,
        "profiles_backfilled": profiles_backfilled,
    }
    if error:
        result["error"] = error
    return result


@shared_task(name="Backfill IMDB game person profiles")
def backfill_imdb_game_person_profiles():
    """Backfill TMDB profile data for IMDB-sourced game people."""
    from app.services import imdb_game_credits

    profiles_backfilled = imdb_game_credits.backfill_missing_person_profiles()
    return {"profiles_backfilled": profiles_backfilled}


@shared_task(name="Schedule IMDB game person profile backfill if needed")
def schedule_imdb_game_person_profile_backfill_if_needed():
    """Queue the credits refresh only if profiles are actually missing.

    Runs the DB count check in a Celery worker rather than in
    ``AppConfig.ready()``, which executes in the Gunicorn master process
    before workers fork (see ``preload_app`` in ``config/gunicorn.py``).
    """
    from app.services import imdb_game_credits

    if imdb_game_credits.count_people_missing_profiles() <= 0:
        return

    refresh_imdb_game_credits_from_datasets.apply_async()


def _resolved_game_items():
    from app.models import Item, MediaTypes, Sources
    from app.services.imdb_game_credits import (
        _apply_credit_backfill_filters,
    )

    items_qs = Item.objects.filter(
        source=Sources.IGDB.value,
        media_type=MediaTypes.GAME.value,
        provider_external_ids__has_key="imdb_id",
    )
    return _apply_credit_backfill_filters(items_qs)
