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

from app import history_cache
from app.models import TV, Episode, Item, MediaTypes, Season, Sources
from app.providers import tmdb, tvdb
from app.services import item_merge
from app.tasks_backfill_state import reset_backfill_state_for_identity_change

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
    # `migrate_tv_item_to_tvdb` only reaches here for non-anime items (grouped
    # anime is bailed out on earlier), so exclude the anime bucket the same
    # way `_scoped_season_item_qs()` does in season_details_views.py — a
    # season/episode row's own library_media_type defaults to its media_type,
    # not the show's, so matching `item.library_media_type` verbatim would
    # exclude the show's own seasons/episodes.
    return list(
        Item.objects.filter(
            media_id=item.media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
        ).exclude(library_media_type=MediaTypes.ANIME.value),
    )


def _local_episode_items(item: Item, season_numbers: list[int]) -> list[Item]:
    return list(
        Item.objects.filter(
            media_id=item.media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number__in=season_numbers,
        ).exclude(library_media_type=MediaTypes.ANIME.value),
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


def _tvdb_episode_payloads(tvdb_payload: dict) -> dict[tuple[int, int], dict]:
    """Index normalized TVDB episode payloads by season and episode number."""
    episode_payloads = {}
    for season_key, season_payload in tvdb_payload.items():
        if not season_key.startswith("season/") or not isinstance(season_payload, dict):
            continue
        try:
            season_number = int(season_key.split("/", 1)[1])
        except (IndexError, TypeError, ValueError):
            continue
        for episode_payload in season_payload.get("episodes") or []:
            episode_number = episode_payload.get("episode_number")
            if episode_number is not None:
                episode_payloads[(season_number, episode_number)] = episode_payload
    return episode_payloads


def _apply_episode_title(episode_item: Item, episode_payload: dict) -> list[str]:
    """Apply a usable provider episode title without erasing existing fields."""
    title_fields = Item.title_fields_from_episode_metadata(episode_payload)
    if not title_fields["title"]:
        return []

    changed_fields = [
        field
        for field, value in title_fields.items()
        if getattr(episode_item, field) != value
    ]
    for field, value in title_fields.items():
        setattr(episode_item, field, value)
    return changed_fields


def _user_ids_for_items(items: list[Item]) -> set[int]:
    """Return users whose TV history can reference any of the given Items."""
    item_ids = {item.pk for item in items if item is not None and item.pk}
    if not item_ids:
        return set()

    user_ids = set(
        TV.objects.filter(item_id__in=item_ids).values_list("user_id", flat=True),
    )
    user_ids.update(
        Season.objects.filter(item_id__in=item_ids).values_list(
            "user_id",
            flat=True,
        ),
    )
    user_ids.update(
        Episode.objects.filter(item_id__in=item_ids).values_list(
            "related_season__user_id",
            flat=True,
        ),
    )
    return user_ids


def _invalidate_history_for_users(user_ids: tuple[int, ...]) -> None:
    """Clear and rebuild history caches after provider identity changes."""
    from app import statistics_cache

    for user_id in user_ids:
        history_cache.invalidate_history_cache(user_id, force=True)
        # Titles and runtimes in every day payload may have changed with the
        # provider identity.
        statistics_cache.invalidate_all_statistics_days(
            user_id, reason="tv_provider_migration"
        )


def _schedule_history_invalidation(user_ids: set[int]) -> None:
    """Run history invalidation only after the surrounding migration commits."""
    if user_ids:
        user_ids_tuple = tuple(sorted(user_ids))
        transaction.on_commit(
            lambda: _invalidate_history_for_users(user_ids_tuple),
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
    episode_payloads = _tvdb_episode_payloads(tvdb_payload)
    user_ids = _user_ids_for_items([item, existing_show, *local_seasons, *local_episodes])

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
                user_ids.update(_user_ids_for_items([existing_season]))
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
            episode_payload = episode_payloads.get(
                (episode.season_number, episode.episode_number),
            )
            if existing_episode is not None:
                user_ids.update(_user_ids_for_items([existing_episode]))
                item_merge.merge_item(episode, existing_episode)
                if episode_payload is not None:
                    changed_fields = _apply_episode_title(
                        existing_episode,
                        episode_payload,
                    )
                    if changed_fields:
                        existing_episode.save(update_fields=changed_fields)
                continue
            episode.media_id = tvdb_id
            episode.source = Sources.TVDB.value
            update_fields = ["media_id", "source"]
            if episode_payload is not None:
                update_fields.extend(_apply_episode_title(episode, episode_payload))
            episode.save(update_fields=update_fields)

        # Every backfill verdict recorded against the old TMDB id described
        # that id, not these rows. Clear them so migrated items become
        # candidates again instead of inheriting a "this id does not
        # exist" give-up.
        reset_backfill_state_for_identity_change(
            Item.objects.filter(source=Sources.TVDB.value, media_id=tvdb_id),
        )

        _schedule_history_invalidation(user_ids)

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

    episode_payloads = _tvdb_episode_payloads(tvdb_payload)
    user_ids = _user_ids_for_items([item, *local_seasons, *local_episodes])

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
            update_fields = ["media_id", "source"]
            episode_payload = episode_payloads.get(
                (episode.season_number, episode.episode_number),
            )
            if episode_payload is not None:
                update_fields.extend(_apply_episode_title(episode, episode_payload))
            episode.save(update_fields=update_fields)

        # Every backfill verdict recorded against the old TMDB id described
        # that id, not these rows. Clear them so migrated items become
        # candidates again instead of inheriting a "this id does not
        # exist" give-up.
        reset_backfill_state_for_identity_change(
            Item.objects.filter(source=Sources.TVDB.value, media_id=tvdb_id),
        )

        _schedule_history_invalidation(user_ids)

    logger.info(
        "Migrated TV item %s to TVDB %s (%s)",
        item.media_id,
        tvdb_id,
        item.title,
    )
    return TvMigrationResult(migrated=True)
