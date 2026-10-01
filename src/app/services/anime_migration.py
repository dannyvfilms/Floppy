"""Explicit migration helpers for flat MAL anime -> grouped TV-style tracking."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from simple_history.utils import bulk_create_with_history, bulk_update_with_history

from app import history_cache, providers, signals
from app.db_retry import run_retryable_db_operation
from app.models import (
    TV,
    Anime,
    Episode,
    Item,
    ItemProviderLink,
    MediaTypes,
    MetadataProviderPreference,
    Season,
    Sources,
    Status,
)
from app.providers import services
from app.services.bulk_episode_tracking import distribute_timestamps
from app.services.tracking_hydration import ensure_item_metadata
from app.signals import suppress_media_change_side_effects
from integrations import anime_mapping


class AnimeMigrationState(StrEnum):
    """Stable forward-migration states used by diagnostics and tests."""

    READY = "ready"
    COMPLETE = "complete"
    PROVABLY_PARTIAL = "provably_partial"
    AMBIGUOUS = "ambiguous"
    STALE = "stale"


class AnimeMigrationError(Exception):
    """Raised when grouped-anime migration cannot be completed safely."""

    def __init__(
        self,
        message: str,
        *,
        state: AnimeMigrationState | None = None,
        code: str | None = None,
    ):
        """Create a safe error with optional stable state and diagnostic code."""
        self.state = state
        self.code = code
        super().__init__(f"{code}: {message}" if code else message)


@dataclass(slots=True)
class AnimeMigrationResult:
    """Result payload for a grouped-anime migration."""

    grouped_tv: TV
    migrated_entries: list[Anime]


@dataclass(frozen=True, slots=True)
class AnimeEntryPayload:
    """Read-only source row and mapping data consumed by persistence."""

    anime_id: int
    item_id: int
    item_media_id: str
    item_title: str
    progress: int
    status: str
    score: Any
    notes: str
    start_date: Any
    end_date: Any
    progressed_at: Any
    created_at: Any
    migrated_to_item_id: int | None
    migrated_at: Any
    season_number: int
    episode_offset: int
    season_metadata: MappingProxyType


@dataclass(frozen=True, slots=True)
class AnimeMigrationPreflight:
    """Immutable, provider-complete input for the database-only phase."""

    state: AnimeMigrationState
    user_id: int
    provider: str
    provider_series_id: str
    entries: tuple[AnimeEntryPayload, ...]
    series_metadata: MappingProxyType
    completed_target_item_id: int | None = None


PARTIAL_CODE = "ANIME-MIGRATION-PARTIAL-001"
AMBIGUOUS_CODE = "ANIME-MIGRATION-AMBIGUOUS-001"
STALE_CODE = "ANIME-MIGRATION-STALE-001"


def _migration_error(
    state: AnimeMigrationState,
    code: str,
    message: str,
) -> AnimeMigrationError:
    return AnimeMigrationError(message, state=state, code=code)


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value):
    if isinstance(value, MappingProxyType):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _provider_series_id(entry: dict, provider: str) -> str | None:
    if provider == Sources.TVDB.value:
        value = entry.get("tvdb_id")
        return str(value) if value not in (None, "") else None
    for key in ("tmdb_show_id", "tmdb_id", "tmdb_tv_id"):
        value = entry.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _provider_season_number(entry: dict, provider: str) -> int | None:
    keys = (
        ["tvdb_season"]
        if provider == Sources.TVDB.value
        else ["tmdb_season", "tvdb_season", "season"]
    )
    for key in keys:
        value = entry.get(key)
        if value in (None, ""):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _provider_episode_offset(entry: dict, provider: str) -> int:
    keys = (
        ["tvdb_epoffset"]
        if provider == Sources.TVDB.value
        else ["tmdb_epoffset", "tvdb_epoffset"]
    )
    for key in keys:
        value = entry.get(key)
        if value in (None, ""):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def _distribution_timestamps(entry: AnimeEntryPayload) -> list:
    return distribute_timestamps(
        entry.start_date,
        entry.end_date,
        entry.progress,
        fallback_dt=entry.progressed_at or entry.created_at or timezone.now(),
    )


def _entry_activity_datetime(entry: AnimeEntryPayload):
    return entry.end_date or entry.progressed_at or entry.created_at or timezone.now()


def _unfinished_status(entries, default=None) -> str:
    """Return the status for a not-fully-completed group of flat entries.

    A dropped or paused status on the most recently active entry is kept;
    otherwise the group is in progress once anything was watched.
    """
    latest = max(entries, key=_entry_activity_datetime)
    if latest.status in {Status.DROPPED.value, Status.PAUSED.value}:
        return latest.status
    if default is not None:
        return default
    return (
        Status.IN_PROGRESS.value
        if any(entry.progress for entry in entries)
        else Status.PLANNING.value
    )


def _mapped_entries(anime_entries: list[Anime], provider: str, series_id: str):
    matches: list[tuple[Anime, dict]] = []
    for anime in anime_entries:
        mapping_entries = anime_mapping.find_entries_for_mal_id(anime.item.media_id)
        provider_entries = [
            entry
            for entry in mapping_entries
            if _provider_series_id(entry, provider) == str(series_id)
        ]
        if len(provider_entries) > 1:
            msg = f'Ambiguous mapping for "{anime.item.title}" on {provider.upper()}.'
            raise AnimeMigrationError(msg)
        if provider_entries:
            matches.append((anime, provider_entries[0]))
    return matches


def _completed_target(
    user_id: int,
    mapped_entries: list[tuple[Anime, dict]],
) -> Item | None:
    marked = [
        anime
        for anime, _mapping in mapped_entries
        if anime.migrated_to_item_id is not None or anime.migrated_at is not None
    ]
    if not marked:
        return None
    for anime in marked:
        if (anime.migrated_to_item_id is None) != (anime.migrated_at is None):
            raise _migration_error(
                AnimeMigrationState.PROVABLY_PARTIAL,
                PARTIAL_CODE,
                "Migration markers do not reference a complete grouped target.",
            )
    if len(marked) != len(mapped_entries):
        raise _migration_error(
            AnimeMigrationState.AMBIGUOUS,
            AMBIGUOUS_CODE,
            "Migrated and unmigrated source rows coexist; no data was changed.",
        )
    target_ids = {anime.migrated_to_item_id for anime in marked}
    if len(target_ids) != 1:
        raise _migration_error(
            AnimeMigrationState.AMBIGUOUS,
            AMBIGUOUS_CODE,
            "Migrated source rows reference different grouped targets.",
        )
    target = Item.objects.filter(pk=target_ids.pop()).first()
    target_is_valid = target is not None and (
        target.media_type == MediaTypes.TV.value
        and target.library_media_type == MediaTypes.ANIME.value
    )
    if not target_is_valid or not TV.objects.filter(
        user_id=user_id,
        item=target,
    ).exists():
        raise _migration_error(
            AnimeMigrationState.PROVABLY_PARTIAL,
            PARTIAL_CODE,
            "Migration markers reference missing grouped tracking.",
        )
    return target


def _existing_grouped_tracking(user_id: int, provider: str, series_id: str) -> bool:
    target_items = Item.objects.filter(
        media_id=series_id,
        source=provider,
        media_type=MediaTypes.TV.value,
        library_media_type=MediaTypes.ANIME.value,
    )
    return TV.objects.filter(user_id=user_id, item__in=target_items).exists() or (
        MetadataProviderPreference.objects.filter(
            user_id=user_id,
            item__in=target_items,
        ).exists()
    )


def _entry_payload(
    anime: Anime,
    *,
    season_number: int,
    episode_offset: int,
    season_metadata: dict,
) -> AnimeEntryPayload:
    return AnimeEntryPayload(
        anime_id=anime.id,
        item_id=anime.item_id,
        item_media_id=anime.item.media_id,
        item_title=anime.item.title,
        progress=int(anime.progress or 0),
        status=anime.status,
        score=anime.score,
        notes=anime.notes,
        start_date=anime.start_date,
        end_date=anime.end_date,
        progressed_at=anime.progressed_at,
        created_at=anime.created_at,
        migrated_to_item_id=anime.migrated_to_item_id,
        migrated_at=anime.migrated_at,
        season_number=season_number,
        episode_offset=episode_offset,
        season_metadata=_freeze(season_metadata),
    )


def preflight_flat_anime_to_grouped(
    user,
    anime_item: Item,
    provider: str,
) -> AnimeMigrationPreflight:
    """Read and validate all provider data without mutating any ORM table."""
    if anime_item.source != Sources.MAL.value or (
        anime_item.media_type != MediaTypes.ANIME.value
    ):
        msg = "Only flat MAL anime can be migrated in this phase."
        raise AnimeMigrationError(msg)

    provider_series_id = anime_mapping.resolve_provider_series_id(
        anime_item.media_id,
        provider,
    )
    if not provider_series_id:
        msg = f"No {provider.upper()} mapping was found for this anime."
        raise AnimeMigrationError(msg)
    provider_series_id = str(provider_series_id)

    anime_entries = list(
        Anime.all_objects.filter(user=user).select_related("item").order_by("id")
    )
    mapped_entries = _mapped_entries(anime_entries, provider, provider_series_id)
    if not mapped_entries:
        msg = "No anime entries matched this grouped series."
        raise AnimeMigrationError(msg)

    completed_target = _completed_target(
        user.id,
        mapped_entries,
    )
    if completed_target is not None:
        entries = tuple(
            _entry_payload(
                anime,
                season_number=0,
                episode_offset=0,
                season_metadata={},
            )
            for anime, _mapping in mapped_entries
        )
        return AnimeMigrationPreflight(
            state=AnimeMigrationState.COMPLETE,
            user_id=user.id,
            provider=provider,
            provider_series_id=provider_series_id,
            entries=entries,
            series_metadata=_freeze({}),
            completed_target_item_id=completed_target.id,
        )

    if _existing_grouped_tracking(user.id, provider, provider_series_id):
        raise _migration_error(
            AnimeMigrationState.AMBIGUOUS,
            AMBIGUOUS_CODE,
            "Grouped tracking already coexists with unmigrated source rows; no data was changed.",
        )

    season_numbers: list[int] = []
    normalized_entries: list[tuple[Anime, int, int]] = []
    for anime, mapping_entry in mapped_entries:
        season_number = _provider_season_number(mapping_entry, provider)
        if season_number is None:
            msg = "One or more mapped entries do not define a season."
            raise AnimeMigrationError(msg)
        season_numbers.append(season_number)
        normalized_entries.append(
            (anime, season_number, _provider_episode_offset(mapping_entry, provider))
        )

    series_metadata = services.get_media_metadata(
        MediaTypes.ANIME.value,
        provider_series_id,
        provider,
    )
    series_metadata = dict(series_metadata or {})
    series_metadata.update(
        {
            "media_id": provider_series_id,
            "source": provider,
            "identity_media_type": MediaTypes.TV.value,
            "library_media_type": MediaTypes.ANIME.value,
        }
    )
    tv_with_seasons = services.get_media_metadata(
        "tv_with_seasons",
        provider_series_id,
        provider,
        sorted(set(season_numbers)),
    )

    payload_entries = []
    for anime, season_number, episode_offset in normalized_entries:
        season_metadata = dict(tv_with_seasons.get(f"season/{season_number}") or {})
        if not season_metadata:
            msg = f"Season {season_number} could not be loaded from {provider.upper()}."
            raise AnimeMigrationError(msg)
        episodes = season_metadata.get("episodes") or []
        if anime.progress > max(len(episodes) - episode_offset, 0):
            msg = (
                f'"{anime.item.title}" has more watched episodes than the '
                "mapped season can hold."
            )
            raise AnimeMigrationError(msg)
        if provider == Sources.TMDB.value:
            season_metadata["_tvdb_episode_image_map"] = (
                providers.tmdb.get_tvdb_episode_image_map(
                    season_metadata.get("tvdb_id"),
                    season_metadata.get("season_number") or season_number,
                    tmdb_media_id=provider_series_id,
                )
            )
        payload_entries.append(
            _entry_payload(
                anime,
                season_number=season_number,
                episode_offset=episode_offset,
                season_metadata=season_metadata,
            )
        )

    return AnimeMigrationPreflight(
        state=AnimeMigrationState.READY,
        user_id=user.id,
        provider=provider,
        provider_series_id=provider_series_id,
        entries=tuple(payload_entries),
        series_metadata=_freeze(series_metadata),
    )


def _source_matches_payload(anime: Anime, entry: AnimeEntryPayload) -> bool:
    return (
        anime.item_id == entry.item_id
        and anime.item.media_id == entry.item_media_id
        and int(anime.progress or 0) == entry.progress
        and anime.status == entry.status
        and anime.score == entry.score
        and anime.notes == entry.notes
        and anime.start_date == entry.start_date
        and anime.end_date == entry.end_date
        and anime.progressed_at == entry.progressed_at
        and anime.created_at == entry.created_at
        and anime.migrated_to_item_id == entry.migrated_to_item_id
        and anime.migrated_at == entry.migrated_at
    )


def _completed_result(
    preflight: AnimeMigrationPreflight,
    anime_rows: list[Anime],
) -> AnimeMigrationResult | None:
    if not anime_rows or any(
        anime.migrated_to_item_id is None or anime.migrated_at is None
        for anime in anime_rows
    ):
        return None
    target_ids = {anime.migrated_to_item_id for anime in anime_rows}
    if len(target_ids) != 1:
        raise _migration_error(
            AnimeMigrationState.AMBIGUOUS,
            AMBIGUOUS_CODE,
            "Migrated source rows reference different grouped targets.",
        )
    grouped_tv = (
        TV.objects.select_related("item")
        .filter(user_id=preflight.user_id, item_id=target_ids.pop())
        .first()
    )
    if grouped_tv is None or not (
        grouped_tv.item.media_type == MediaTypes.TV.value
        and grouped_tv.item.library_media_type == MediaTypes.ANIME.value
    ):
        raise _migration_error(
            AnimeMigrationState.PROVABLY_PARTIAL,
            PARTIAL_CODE,
            "Migration markers reference missing grouped tracking.",
        )
    return AnimeMigrationResult(grouped_tv=grouped_tv, migrated_entries=anime_rows)


def _upsert_provider_link(
    item: Item,
    *,
    provider: str,
    series_id: str,
    season_number: int | None = None,
    episode_offset: int | None = None,
    metadata: dict | None = None,
) -> None:
    defaults = {
        "provider_media_id": series_id,
        "metadata": metadata or {},
    }
    if episode_offset is not None:
        defaults["episode_offset"] = episode_offset
    ItemProviderLink.objects.update_or_create(
        item=item,
        provider=provider,
        provider_media_type=MediaTypes.TV.value,
        season_number=season_number,
        defaults=defaults,
    )

    external_ids = dict(item.provider_external_ids or {})
    external_ids[f"{provider}_id"] = series_id
    if item.provider_external_ids != external_ids:
        item.provider_external_ids = external_ids
        item.save(update_fields=["provider_external_ids"])


def _grouped_item(preflight: AnimeMigrationPreflight) -> Item:
    metadata = _thaw(preflight.series_metadata)
    return ensure_item_metadata(
        get_user_model().objects.get(pk=preflight.user_id),
        MediaTypes.ANIME.value,
        preflight.provider_series_id,
        preflight.provider,
        identity_media_type=MediaTypes.TV.value,
        library_media_type=MediaTypes.ANIME.value,
        fallback_title=preflight.entries[0].item_title,
        prefetched_metadata=metadata,
        provider_link_retry_max_retries=0,
    ).item


def _reconcile_committed_migration(
    user_id: int,
    item_ids: tuple[int, ...],
    history_days: tuple[str, ...],
) -> None:
    """Run skipped cache and smart-list effects once after commit."""
    signals._clear_media_runtime_caches(user_id, MediaTypes.EPISODE.value)
    signals._invalidate_episode_history_changes({user_id: list(history_days)})
    owner = get_user_model().objects.filter(pk=user_id).first()
    items = list(Item.objects.filter(pk__in=item_ids).order_by("id"))
    signals._sync_owner_smart_lists_for_items(owner, items)


def _season_tracker(
    preflight: AnimeMigrationPreflight,
    grouped_tv: TV,
    entry: AnimeEntryPayload,
) -> Season:
    season_metadata = _thaw(entry.season_metadata)
    season_image = season_metadata.get("image") or grouped_tv.item.image
    season_item, _created = Item.objects.get_or_create(
        media_id=preflight.provider_series_id,
        source=preflight.provider,
        media_type=MediaTypes.SEASON.value,
        library_media_type=MediaTypes.ANIME.value,
        season_number=entry.season_number,
        defaults={
            **Item.title_fields_from_metadata(
                season_metadata,
                fallback_title=grouped_tv.item.title,
            ),
            "image": season_image,
        },
    )
    update_fields = []
    if season_item.library_media_type != MediaTypes.ANIME.value:
        season_item.library_media_type = MediaTypes.ANIME.value
        update_fields.append("library_media_type")
    if season_item.image != season_image and season_image:
        season_item.image = season_image
        update_fields.append("image")
    if update_fields:
        season_item.save(update_fields=update_fields)
    return bulk_create_with_history(
        [
            Season(
                item=season_item,
                user_id=preflight.user_id,
                related_tv=grouped_tv,
                status=Status.PLANNING.value,
                score=None,
                notes="",
            )
        ],
        Season,
    )[0]


def _create_migration_episodes(
    season: Season,
    entry: AnimeEntryPayload,
) -> list[Episode]:
    if entry.progress <= 0:
        return []
    season_metadata = _thaw(entry.season_metadata)
    episode_numbers = [
        entry.episode_offset + index for index in range(1, entry.progress + 1)
    ]
    episode_items = [
        season.get_episode_item(episode_number, season_metadata)
        for episode_number in episode_numbers
    ]
    episodes = [
        Episode(related_season=season, item=item, end_date=watched_at)
        for item, watched_at in zip(
            episode_items,
            _distribution_timestamps(entry),
            strict=False,
        )
    ]
    return bulk_create_with_history(episodes, Episode)


def _persist_preflight_once(
    preflight: AnimeMigrationPreflight,
) -> AnimeMigrationResult:
    with transaction.atomic(), suppress_media_change_side_effects():
        locked_rows = list(
            Anime.all_objects.select_for_update()
            .filter(id__in=[entry.anime_id for entry in preflight.entries])
            .select_related("item")
            .order_by("id")
        )
        by_id = {anime.id: anime for anime in locked_rows}
        if len(by_id) != len(preflight.entries):
            raise _migration_error(
                AnimeMigrationState.STALE,
                STALE_CODE,
                "Source rows changed after preflight; retry from a fresh preflight.",
            )

        completed = _completed_result(preflight, locked_rows)
        if completed is not None:
            return completed
        if preflight.state == AnimeMigrationState.COMPLETE:
            raise _migration_error(
                AnimeMigrationState.STALE,
                STALE_CODE,
                "Completed migration state changed after preflight.",
            )

        inconsistent = [
            anime
            for anime in locked_rows
            if (anime.migrated_to_item_id is None) != (anime.migrated_at is None)
        ]
        if inconsistent:
            raise _migration_error(
                AnimeMigrationState.PROVABLY_PARTIAL,
                PARTIAL_CODE,
                "Migration markers do not reference a complete grouped target.",
            )
        marked_count = sum(
            anime.migrated_to_item_id is not None for anime in locked_rows
        )
        if marked_count:
            raise _migration_error(
                AnimeMigrationState.AMBIGUOUS,
                AMBIGUOUS_CODE,
                "Migrated and unmigrated source rows coexist; no data was changed.",
            )
        for entry in preflight.entries:
            if not _source_matches_payload(by_id[entry.anime_id], entry):
                raise _migration_error(
                    AnimeMigrationState.STALE,
                    STALE_CODE,
                    "Source rows changed after preflight; retry from a fresh preflight.",
                )

        if _existing_grouped_tracking(
            preflight.user_id,
            preflight.provider,
            preflight.provider_series_id,
        ):
            raise _migration_error(
                AnimeMigrationState.AMBIGUOUS,
                AMBIGUOUS_CODE,
                "Grouped tracking appeared after preflight; no data was changed.",
            )

        grouped_item = _grouped_item(preflight)
        grouped_tv = bulk_create_with_history(
            [
                TV(
                    item=grouped_item,
                    user_id=preflight.user_id,
                    status=Status.PLANNING.value,
                    score=None,
                    notes="",
                )
            ],
            TV,
        )[0]

        latest_score_entry = None
        latest_notes_entry = None
        created_seasons: dict[int, Season] = {}
        history_days = set()
        smart_list_item_ids = {grouped_item.id, *(anime.item_id for anime in locked_rows)}
        for entry in preflight.entries:
            source_item = by_id[entry.anime_id].item
            _upsert_provider_link(
                source_item,
                provider=preflight.provider,
                series_id=preflight.provider_series_id,
                season_number=entry.season_number,
                episode_offset=entry.episode_offset,
                metadata={
                    "season_number": entry.season_number,
                    "episode_offset": entry.episode_offset,
                },
            )
            season = created_seasons.get(entry.season_number)
            if season is None:
                season = _season_tracker(preflight, grouped_tv, entry)
                created_seasons[entry.season_number] = season
                smart_list_item_ids.add(season.item_id)
            created_episodes = _create_migration_episodes(season, entry)
            history_days.update(
                day_key
                for episode in created_episodes
                if (day_key := history_cache.history_day_key(episode.end_date))
            )

            if entry.score is not None and (
                latest_score_entry is None
                or _entry_activity_datetime(entry)
                > _entry_activity_datetime(latest_score_entry)
            ):
                latest_score_entry = entry
            if entry.notes and (
                latest_notes_entry is None
                or _entry_activity_datetime(entry)
                > _entry_activity_datetime(latest_notes_entry)
            ):
                latest_notes_entry = entry

        for season_number, season in created_seasons.items():
            season_entries = [
                entry
                for entry in preflight.entries
                if entry.season_number == season_number
            ]
            season_metadata = _thaw(season_entries[0].season_metadata)
            desired_status = season.derived_status_from_episode_progress(
                max_progress=len(season_metadata.get("episodes") or []),
            )
            if not all(
                entry.status == Status.COMPLETED.value for entry in season_entries
            ):
                desired_status = _unfinished_status(season_entries)
            if season.status != desired_status:
                season.status = desired_status
                bulk_update_with_history([season], Season, fields=["status"])

        grouped_tv_updates = []
        if latest_score_entry is not None:
            grouped_tv.score = latest_score_entry.score
            grouped_tv_updates.append("score")
        if latest_notes_entry is not None:
            grouped_tv.notes = latest_notes_entry.notes
            grouped_tv_updates.append("notes")
        desired_tv_status = (
            Status.COMPLETED.value
            if created_seasons
            and all(
                season.status == Status.COMPLETED.value
                for season in created_seasons.values()
            )
            else _unfinished_status(preflight.entries, default=Status.IN_PROGRESS.value)
        )
        if grouped_tv.status != desired_tv_status:
            grouped_tv.status = desired_tv_status
            grouped_tv_updates.append("status")
        if grouped_tv_updates:
            bulk_update_with_history(
                [grouped_tv],
                TV,
                fields=list(dict.fromkeys(grouped_tv_updates)),
            )

        now = timezone.now()
        for anime in locked_rows:
            anime.migrated_to_item = grouped_item
            anime.migrated_at = now
        Anime.all_objects.bulk_update(
            locked_rows,
            ["migrated_to_item", "migrated_at"],
        )
        MetadataProviderPreference.objects.update_or_create(
            user_id=preflight.user_id,
            item=grouped_item,
            defaults={"provider": preflight.provider},
        )
        committed_item_ids = tuple(sorted(smart_list_item_ids))
        committed_history_days = tuple(sorted(history_days))
        transaction.on_commit(
            lambda: _reconcile_committed_migration(
                preflight.user_id,
                committed_item_ids,
                committed_history_days,
            ),
        )
        return AnimeMigrationResult(
            grouped_tv=grouped_tv,
            migrated_entries=locked_rows,
        )


def persist_flat_anime_migration(
    preflight: AnimeMigrationPreflight,
) -> AnimeMigrationResult:
    """Persist a preflight in a fresh transaction on every lock retry."""
    return run_retryable_db_operation(
        lambda: _persist_preflight_once(preflight),
        operation_name="flat anime grouped migration",
    ).value


def migrate_flat_anime_to_grouped(
    user,
    anime_item: Item,
    provider: str,
) -> AnimeMigrationResult:
    """Migrate all matching flat anime rows using preflight then one transaction."""
    preflight = preflight_flat_anime_to_grouped(user, anime_item, provider)
    return persist_flat_anime_migration(preflight)
