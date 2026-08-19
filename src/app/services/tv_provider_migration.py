"""In-place migration of TMDB-tracked TV shows to a user's preferred TVDB identity.

Unlike anime's flat-MAL -> grouped-TV migration (`app.services.anime_migration`),
this does not need to recreate any rows: TV/Season/Episode instances FK the
`Item` primary key directly, so re-keying the existing show/season/episode
`Item` rows' `media_id`/`source` in place preserves all watch history with
zero relation rewiring. See issue #387.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from app.models import Item, MediaTypes, Sources
from app.providers import tmdb, tvdb
from app.services import item_merge

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TvMigrationResult:
    """Outcome of a single show's migration attempt."""

    migrated: bool
    reason: str = ""


def _resolve_tvdb_id(item: Item) -> str | None:
    tvdb_id = (item.provider_external_ids or {}).get("tvdb_id")
    if tvdb_id:
        return str(tvdb_id)
    resolved = tmdb.resolve_tvdb_id_for_tmdb_show(item.media_id)
    return str(resolved) if resolved else None


def _local_season_items(item: Item) -> list[Item]:
    return list(
        Item.objects.filter(
            media_id=item.media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
        ),
    )


def _local_episode_items(item: Item, season_numbers: list[int]) -> list[Item]:
    return list(
        Item.objects.filter(
            media_id=item.media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number__in=season_numbers,
        ),
    )


def _structure_is_compatible(
    local_seasons: list[Item],
    local_episodes: list[Item],
    tvdb_payload: dict,
) -> bool:
    """Return whether every locally-tracked season/episode exists on TVDB.

    Deliberately conservative: TVDB is allowed to have *more* seasons or
    episodes than are tracked locally (unaired episodes, specials the user
    never watched); it must not be missing anything the user already has.
    """
    for season in local_seasons:
        season_payload = tvdb_payload.get(f"season/{season.season_number}")
        if season_payload is None:
            return False

    episode_numbers_by_season: dict[int, set[int]] = {}
    for episode in local_episodes:
        episode_numbers_by_season.setdefault(episode.season_number, set()).add(
            episode.episode_number,
        )

    for season_number, episode_numbers in episode_numbers_by_season.items():
        season_payload = tvdb_payload.get(f"season/{season_number}")
        if season_payload is None:
            return False
        tvdb_episode_numbers = {
            episode.get("episode_number")
            for episode in season_payload.get("episodes") or []
        }
        if not episode_numbers.issubset(tvdb_episode_numbers):
            return False

    return True


def _existing_tvdb_item(
    media_id: str,
    media_type: str,
    library_media_type: str,
    *,
    season_number: int | None = None,
    episode_number: int | None = None,
    exclude_pk: int,
) -> Item | None:
    return (
        Item.objects.filter(
            media_id=media_id,
            source=Sources.TVDB.value,
            media_type=media_type,
            library_media_type=library_media_type,
            season_number=season_number,
            episode_number=episode_number,
        )
        .exclude(pk=exclude_pk)
        .first()
    )


def _pin(item: Item, reason: str) -> TvMigrationResult:
    item.metadata_migration_pinned_at = timezone.now()
    item.save(update_fields=["metadata_migration_pinned_at"])
    logger.info(
        "Pinned TV item %s (%s) from TVDB auto-migration: %s",
        item.media_id,
        item.title,
        reason,
    )
    return TvMigrationResult(migrated=False, reason=reason)


def _merge_into_existing_tvdb_show(
    item: Item,
    existing_show: Item,
    local_seasons: list[Item],
    local_episodes: list[Item],
    tvdb_id: str,
    tvdb_payload: dict,
) -> TvMigrationResult:
    """Fold a duplicate TMDB show/season/episode `Item`s onto their TVDB twins.

    Reached when the show already has a separate, independently-tracked
    TVDB `Item` - e.g. created directly, or by a Trakt (TMDB-only) import
    alongside a TVDB-preferring user (#620). The TVDB id resolved by the
    caller is a verified identity match, not a guess, so merging is safe.
    Seasons/episodes without an existing TVDB counterpart are re-keyed in
    place as usual.
    """
    with transaction.atomic():
        item_merge.merge_item(item, existing_show)

        for season in local_seasons:
            existing_season = _existing_tvdb_item(
                tvdb_id,
                MediaTypes.SEASON.value,
                season.library_media_type,
                season_number=season.season_number,
                exclude_pk=season.pk,
            )
            if existing_season is not None:
                item_merge.merge_item(season, existing_season)
                continue
            season_payload = tvdb_payload.get(f"season/{season.season_number}") or {}
            season.media_id = tvdb_id
            season.source = Sources.TVDB.value
            season.image = season_payload.get("image") or season.image
            season.save(update_fields=["media_id", "source", "image"])

        for episode in local_episodes:
            existing_episode = _existing_tvdb_item(
                tvdb_id,
                MediaTypes.EPISODE.value,
                episode.library_media_type,
                season_number=episode.season_number,
                episode_number=episode.episode_number,
                exclude_pk=episode.pk,
            )
            if existing_episode is not None:
                item_merge.merge_item(episode, existing_episode)
                continue
            episode.media_id = tvdb_id
            episode.source = Sources.TVDB.value
            episode.save(update_fields=["media_id", "source"])

    logger.info(
        "Merged duplicate TV item %s into existing TVDB item %s (%s)",
        item.media_id,
        tvdb_id,
        existing_show.title,
    )
    return TvMigrationResult(migrated=True)


def migrate_tv_item_to_tvdb(item: Item) -> TvMigrationResult:
    """Migrate a TMDB-tracked, non-anime TV show `Item` to TVDB identity in place.

    Never raises and never partially migrates: any check that fails aborts
    before mutating data. A structure mismatch pins the item (best-effort,
    still retried for other reasons later) instead of migrating, since a bad
    migration would silently re-identify a user's watch history under the
    wrong show. An identity collision - a separate `Item` already tracks
    this show under TVDB - merges the two instead of pinning, since the
    resolved TVDB id is a verified match rather than a guess.
    """
    if item.source != Sources.TMDB.value or item.media_type != MediaTypes.TV.value:
        return TvMigrationResult(migrated=False, reason="not a TMDB TV item")
    if item.library_media_type == MediaTypes.ANIME.value:
        return TvMigrationResult(migrated=False, reason="grouped anime item, skipped")
    if not tvdb.enabled():
        return TvMigrationResult(migrated=False, reason="TVDB not configured")

    tvdb_id = _resolve_tvdb_id(item)
    if not tvdb_id:
        return TvMigrationResult(migrated=False, reason="no TVDB id resolvable")

    local_seasons = _local_season_items(item)
    season_numbers = [season.season_number for season in local_seasons]
    local_episodes = _local_episode_items(item, season_numbers)

    try:
        tvdb_payload = tvdb.tv_with_seasons(tvdb_id, season_numbers)
    except Exception as exc:  # pragma: no cover - defensive network guard
        logger.warning(
            "TVDB migration lookup failed for show %s (TVDB %s): %s",
            item.media_id,
            tvdb_id,
            exc,
        )
        return TvMigrationResult(migrated=False, reason="TVDB lookup failed")

    if not _structure_is_compatible(local_seasons, local_episodes, tvdb_payload):
        return _pin(item, "season/episode structure does not match TVDB")

    existing_show = _existing_tvdb_item(
        tvdb_id,
        MediaTypes.TV.value,
        item.library_media_type,
        exclude_pk=item.pk,
    )
    if existing_show is not None:
        return _merge_into_existing_tvdb_show(
            item,
            existing_show,
            local_seasons,
            local_episodes,
            tvdb_id,
            tvdb_payload,
        )

    for season in local_seasons:
        if _existing_tvdb_item(
            tvdb_id,
            MediaTypes.SEASON.value,
            season.library_media_type,
            season_number=season.season_number,
            exclude_pk=season.pk,
        ):
            return _pin(item, "a separate season item already exists under TVDB")
    for episode in local_episodes:
        if _existing_tvdb_item(
            tvdb_id,
            MediaTypes.EPISODE.value,
            episode.library_media_type,
            season_number=episode.season_number,
            episode_number=episode.episode_number,
            exclude_pk=episode.pk,
        ):
            return _pin(item, "a separate episode item already exists under TVDB")

    with transaction.atomic():
        item.media_id = tvdb_id
        item.source = Sources.TVDB.value
        item.title = tvdb_payload.get("title") or item.title
        item.image = tvdb_payload.get("image") or item.image
        item.save(update_fields=["media_id", "source", "title", "image"])

        for season in local_seasons:
            season_payload = tvdb_payload.get(f"season/{season.season_number}") or {}
            season.media_id = tvdb_id
            season.source = Sources.TVDB.value
            season.image = season_payload.get("image") or season.image
            season.save(update_fields=["media_id", "source", "image"])

        for episode in local_episodes:
            episode.media_id = tvdb_id
            episode.source = Sources.TVDB.value
            episode.save(update_fields=["media_id", "source"])

    logger.info(
        "Migrated TV item %s to TVDB %s (%s)",
        item.media_id,
        tvdb_id,
        item.title,
    )
    return TvMigrationResult(migrated=True)
