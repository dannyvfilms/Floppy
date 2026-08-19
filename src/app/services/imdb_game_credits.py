"""Resolve IMDB ids for tracked games and sync their cast/crew.

IGDB (the games provider) doesn't expose an IMDB mapping, so games can't be
linked the way TMDB-sourced movies/TV are. Instead we match a game's title
and release year against IMDB's own "videoGame" titles from the public
title.basics dataset. Matching is deliberately conservative: exact normalized
title plus a release year within one year of each other. Anything ambiguous
or unmatched is left alone rather than guessed.
"""

from __future__ import annotations

import ast
import logging

from django.db.models import Q

from app import credits as credit_helpers
from app.models import (
    CREDITS_BACKFILL_VERSION,
    Item,
    MediaTypes,
    MetadataBackfillField,
    Person,
    PersonGender,
    Sources,
)
from app.providers import services as provider_services
from app.tasks_backfill_state import (
    _apply_backfill_state_filters,
    _record_backfill_failure,
    _record_backfill_success,
)

logger = logging.getLogger(__name__)

_YEAR_TOLERANCE = 1
_IMAGE_BACKFILL_PROGRESS_EVERY = 25

# IMDB principals "category" -> our CreditRoleType/department.
_CAST_CATEGORIES = {"actor", "actress", "self"}
_CREW_CATEGORIES = {
    "director": "Directing",
    "writer": "Writing",
    "producer": "Production",
    "composer": "Sound",
}


def _title_key(title: str) -> str:
    return Item._title_comparison_key(title)


def resolve_game_imdb_ids() -> int:
    """Match untagged IGDB game Items against IMDB's videoGame title index.

    Returns the number of Items updated with a provider_external_ids["imdb_id"].
    """
    from app.providers import imdb_datasets

    candidates = list(
        Item.objects.filter(
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
        ).exclude(
            provider_external_ids__has_key="imdb_id",
        ),
    )
    if not candidates:
        return 0

    try:
        title_index = imdb_datasets.download_videogame_title_index()
    except Exception:
        logger.warning(
            "imdb_game_credits: failed to download title index", exc_info=True
        )
        return 0

    by_title_key: dict[str, list[tuple[str, int | None]]] = {}
    for tconst, (title, year) in title_index.items():
        by_title_key.setdefault(_title_key(title), []).append((tconst, year))

    updated = []
    for item in candidates:
        key = _title_key(item.title)
        if not key:
            continue
        entries = by_title_key.get(key)
        if not entries:
            continue

        item_year = item.release_datetime.year if item.release_datetime else None
        matches = [
            tconst
            for tconst, year in entries
            if item_year is None
            or year is None
            or abs(year - item_year) <= _YEAR_TOLERANCE
        ]
        if len(matches) != 1:
            continue

        item.provider_external_ids = {
            **(item.provider_external_ids or {}),
            "imdb_id": matches[0],
        }
        updated.append(item)

    if updated:
        Item.objects.bulk_update(updated, ["provider_external_ids"])
        logger.info("imdb_game_credits: resolved %d game imdb ids", len(updated))

    return len(updated)


def _parse_characters(raw: str) -> str:
    """title.principals "characters" is a stringified JSON array, e.g. '["Sam"]'."""
    if not raw:
        return ""
    try:
        parsed = ast.literal_eval(raw)
    except (SyntaxError, ValueError):
        return raw
    if isinstance(parsed, (list, tuple)):
        return ", ".join(str(v) for v in parsed if v)
    return str(parsed)


def sync_game_credits_from_imdb(
    principals_by_tconst: dict[str, list[dict]],
    names_by_nconst: dict[str, str],
) -> int:
    """Persist cast/crew for resolved game Items using downloaded IMDB data.

    Returns the number of Items synced.
    """
    items_qs = Item.objects.filter(
        source=Sources.IGDB.value,
        media_type=MediaTypes.GAME.value,
        provider_external_ids__has_key="imdb_id",
    )
    items = list(_apply_credit_backfill_filters(items_qs))
    synced = 0
    for item in items:
        imdb_id = (item.provider_external_ids or {}).get("imdb_id")
        principals = principals_by_tconst.get(imdb_id)
        if not principals:
            _record_backfill_failure(
                item, MetadataBackfillField.CREDITS.value, "no imdb principals"
            )
            continue

        cast_rows = []
        crew_rows = []
        for row in principals:
            name = names_by_nconst.get(row["nconst"])
            if not name:
                continue
            category = row["category"]
            if category in _CAST_CATEGORIES:
                cast_rows.append(
                    {
                        "person_id": row["nconst"],
                        "name": name,
                        "role": _parse_characters(row["characters"]) or row["job"],
                        "sort_order": row["ordering"],
                    },
                )
            elif category in _CREW_CATEGORIES:
                crew_rows.append(
                    {
                        "person_id": row["nconst"],
                        "name": name,
                        "role": row["job"] or category,
                        "department": _CREW_CATEGORIES[category],
                        "sort_order": row["ordering"],
                    },
                )

        if not cast_rows and not crew_rows:
            _record_backfill_failure(
                item, MetadataBackfillField.CREDITS.value, "no usable principals"
            )
            continue

        # Suppress per-row credit signals — a bulk sync across many games would
        # otherwise schedule a Discover rebuild per ItemPersonCredit row.
        from app.signals import suppress_media_change_side_effects

        with suppress_media_change_side_effects():
            credit_helpers.sync_item_credits_from_metadata(
                item,
                {"cast": cast_rows, "crew": crew_rows},
                person_source=Sources.IMDB.value,
            )
        _record_backfill_success(
            item,
            MetadataBackfillField.CREDITS.value,
            strategy_version=CREDITS_BACKFILL_VERSION,
        )
        synced += 1

    if synced:
        logger.info("imdb_game_credits: synced credits for %d games", synced)

    return synced


def backfill_missing_person_profiles() -> int:
    """Best-effort headshot + gender lookup via TMDB for IMDB-sourced people.

    IMDB's public dataset has neither image data nor gender at all, so this is a
    name-only cross reference against TMDB's person search (no id verification)
    — same reliability posture as the rest of this feature. Many game cast (voice
    actors, FMV actors) also have TMDB entries from film/TV work, so one search
    per person recovers both the missing image and the missing gender (needed to
    sort someone into the actor vs actress leaderboard) in a single API call.
    Runs once per Person, not per credit, so it naturally dedupes across however
    many games a person is credited on.
    """
    from app.providers import tmdb

    people = list(
        Person.objects.filter(source=Sources.IMDB.value).filter(
            Q(image="") | Q(gender=PersonGender.UNKNOWN.value),
        ),
    )
    if not people:
        return 0

    logger.info(
        "imdb_game_credits: starting TMDB person profile backfill for %d people",
        len(people),
    )

    updated = []
    failures = 0
    matched = 0
    for index, person in enumerate(people, start=1):
        try:
            profile = tmdb.search_person_profile(person.name)
        except provider_services.ProviderAPIError as exc:
            failures += 1
            logger.warning(
                "imdb_game_credits: TMDB profile lookup failed for %s (%s): %s",
                person.name,
                person.source_person_id,
                exc,
            )
            profile = None

        if profile:
            matched += 1
            changed = False
            if not person.image and profile.get("image"):
                person.image = profile["image"]
                changed = True
            if (
                person.gender == PersonGender.UNKNOWN.value
                and profile.get("gender", "unknown") != "unknown"
            ):
                person.gender = profile["gender"]
                changed = True
            if changed:
                updated.append(person)

        if index == len(people) or index % _IMAGE_BACKFILL_PROGRESS_EVERY == 0:
            logger.info(
                (
                    "imdb_game_credits: TMDB profile backfill progress %d/%d "
                    "(matched=%d updated=%d failed=%d)"
                ),
                index,
                len(people),
                matched,
                len(updated),
                failures,
            )

    if updated:
        Person.objects.bulk_update(updated, ["image", "gender"])
    logger.info(
        (
            "imdb_game_credits: completed TMDB person profile backfill "
            "(matched=%d updated=%d failed=%d total=%d)"
        ),
        matched,
        len(updated),
        failures,
        len(people),
    )

    return len(updated)


def backfill_missing_game_studios() -> int:
    """Best-effort IGDB studio/company backfill for IMDB-resolved games."""
    from app.providers import services
    from app.signals import suppress_media_change_side_effects

    items = list(
        Item.objects.filter(
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            provider_external_ids__has_key="imdb_id",
            studio_credits__isnull=True,
        ).distinct(),
    )
    if not items:
        return 0

    logger.info(
        "imdb_game_credits: starting IGDB studio backfill for %d games",
        len(items),
    )

    updated = 0
    failures = 0
    for index, item in enumerate(items, start=1):
        try:
            metadata = services.get_media_metadata(
                item.media_type,
                item.media_id,
                item.source,
            )
        except provider_services.ProviderAPIError as exc:
            failures += 1
            logger.warning(
                "imdb_game_credits: IGDB studio lookup failed for %s (%s): %s",
                item.title,
                item.media_id,
                exc,
            )
            metadata = None

        studios_full = []
        if isinstance(metadata, dict):
            studios_full = metadata.get("studios_full") or []

        if studios_full:
            with suppress_media_change_side_effects():
                credit_helpers.sync_item_credits_from_metadata(
                    item,
                    {"studios_full": studios_full},
                )
            updated += 1

        if index == len(items) or index % _IMAGE_BACKFILL_PROGRESS_EVERY == 0:
            logger.info(
                (
                    "imdb_game_credits: IGDB studio backfill progress %d/%d "
                    "(updated=%d failed=%d)"
                ),
                index,
                len(items),
                updated,
                failures,
            )

    logger.info(
        "imdb_game_credits: completed IGDB studio backfill (updated=%d failed=%d total=%d)",
        updated,
        failures,
        len(items),
    )
    return updated


def _apply_credit_backfill_filters(queryset):
    filtered = _apply_backfill_state_filters(
        queryset, MetadataBackfillField.CREDITS.value
    )
    current_ids = credit_helpers.current_credits_backfill_item_ids(
        filtered.values_list("id", flat=True),
    )
    if not current_ids:
        return filtered
    return filtered.exclude(id__in=current_ids)


def count_people_missing_profiles() -> int:
    """Return the number of IMDB-sourced people still missing image or gender."""
    return (
        Person.objects.filter(source=Sources.IMDB.value)
        .filter(
            Q(image="") | Q(gender=PersonGender.UNKNOWN.value),
        )
        .count()
    )
