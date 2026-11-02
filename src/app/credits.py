"""Helpers for synchronizing person/studio metadata."""

from __future__ import annotations

from datetime import date

from django.db import transaction

from app.models import (
    CREDITS_BACKFILL_VERSION,
    CreditRoleType,
    Item,
    ItemPersonCredit,
    ItemStudioCredit,
    MediaTypes,
    MetadataBackfillField,
    MetadataBackfillState,
    Person,
    PersonGender,
    Sources,
    Studio,
)

TMDB_SHOW_REGULAR_CAST_SORT_ORDER_CUTOFF = 100


def _coerce_iso_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _coerce_gender(value):
    normalized = str(value or "").strip().lower()
    if normalized in {
        PersonGender.FEMALE.value,
        PersonGender.MALE.value,
        PersonGender.NON_BINARY.value,
    }:
        return normalized
    if normalized in {"1", "female", "f"}:
        return PersonGender.FEMALE.value
    if normalized in {"2", "male", "m"}:
        return PersonGender.MALE.value
    if normalized in {"3", "non-binary", "non_binary", "nb"}:
        return PersonGender.NON_BINARY.value
    return PersonGender.UNKNOWN.value


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_text(value):
    """Normalize provider text fields that may arrive as non-string values."""
    return str(value or "").strip()


def is_regular_show_cast_credit(source, sort_order):
    """Return whether a show-level cast credit should count as series-regular fallback."""
    if source != Sources.TMDB.value:
        return True
    return (
        sort_order is not None and sort_order < TMDB_SHOW_REGULAR_CAST_SORT_ORDER_CUTOFF
    )


def is_usable_tv_show_credit(source, role_type, sort_order):
    """Return whether a show-level TV credit is usable as attribution fallback."""
    if role_type != CreditRoleType.CAST.value:
        return True
    return is_regular_show_cast_credit(source, sort_order)


def current_credits_backfill_item_ids(item_ids):
    """Return item IDs whose credits are backed by the current TMDB strategy."""
    normalized_ids = []
    for item_id in item_ids or []:
        try:
            parsed = int(item_id)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            normalized_ids.append(parsed)
    if not normalized_ids:
        return set()
    return set(
        MetadataBackfillState.objects.filter(
            field=MetadataBackfillField.CREDITS,
            item_id__in=normalized_ids,
            give_up=False,
            fail_count=0,
            last_success_at__isnull=False,
            strategy_version__gte=CREDITS_BACKFILL_VERSION,
        ).values_list("item_id", flat=True),
    )


def usable_credits_backfill_item_ids(item_ids):
    """Return item IDs whose stored TMDB credits remain usable for reads."""
    normalized_ids = []
    for item_id in item_ids or []:
        try:
            parsed = int(item_id)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            normalized_ids.append(parsed)
    if not normalized_ids:
        return set()
    return set(
        MetadataBackfillState.objects.filter(
            field=MetadataBackfillField.CREDITS,
            item_id__in=normalized_ids,
            last_success_at__isnull=False,
            strategy_version__gte=CREDITS_BACKFILL_VERSION,
        ).values_list("item_id", flat=True),
    )


def missing_credits_backfill_item_ids(item_ids):
    """Return item IDs that still need credits backfill."""
    normalized_ids = []
    for item_id in item_ids or []:
        try:
            parsed = int(item_id)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            normalized_ids.append(parsed)
    normalized_ids = sorted(set(normalized_ids))
    if not normalized_ids:
        return []

    candidate_items = list(
        Item.objects.filter(
            id__in=normalized_ids,
            source__in=(Sources.TMDB.value, Sources.TVDB.value),
            media_type__in=[
                MediaTypes.MOVIE.value,
                MediaTypes.TV.value,
                MediaTypes.SEASON.value,
                MediaTypes.EPISODE.value,
            ],
        )
        # TVDB seasons/episodes never carry a credits payload (see
        # providers.tvdb._normalize_season_metadata / episode()), so they
        # would otherwise always look "missing" and be requeued forever.
        .exclude(
            source=Sources.TVDB.value,
            media_type__in=[MediaTypes.SEASON.value, MediaTypes.EPISODE.value],
        )
        .values("id", "media_type", "source"),
    )
    if not candidate_items:
        return []

    candidate_ids = {row["id"] for row in candidate_items}
    media_type_by_id = {row["id"]: row["media_type"] for row in candidate_items}
    source_by_id = {row["id"]: row["source"] for row in candidate_items}
    current_credit_ids = current_credits_backfill_item_ids(candidate_ids)

    person_credit_ids = set(
        ItemPersonCredit.objects.filter(item_id__in=candidate_ids)
        .order_by()
        .values_list("item_id", flat=True)
        .distinct(),
    )
    cast_credit_ids = set(
        ItemPersonCredit.objects.filter(
            item_id__in=candidate_ids,
            role_type=CreditRoleType.CAST.value,
        )
        .order_by()
        .values_list("item_id", flat=True)
        .distinct(),
    )
    studio_credit_ids = set(
        ItemStudioCredit.objects.filter(item_id__in=candidate_ids)
        .order_by()
        .values_list("item_id", flat=True)
        .distinct(),
    )

    missing_ids = []
    for item_id in sorted(candidate_ids):
        media_type = media_type_by_id.get(item_id)
        has_people = item_id in person_credit_ids
        has_cast = item_id in cast_credit_ids
        has_studios = item_id in studio_credit_ids
        # TVDB never returns studio data (see providers.tvdb._build_series_metadata),
        # so only TMDB items are held to the "has studios" bar.
        studios_required = source_by_id.get(item_id) == Sources.TMDB.value
        if media_type == MediaTypes.SEASON.value:
            if not has_cast or item_id not in current_credit_ids:
                missing_ids.append(item_id)
            continue
        if media_type == MediaTypes.TV.value:
            if (
                not has_cast
                or (studios_required and not has_studios)
                or item_id not in current_credit_ids
            ):
                missing_ids.append(item_id)
            continue
        if media_type == MediaTypes.EPISODE.value:
            if not has_people or item_id not in current_credit_ids:
                missing_ids.append(item_id)
            continue
        if not has_people or not has_studios:
            missing_ids.append(item_id)
    return missing_ids


def should_count_tv_show_credit_for_episode(
    source,
    role_type,
    sort_order,
    season_has_usable_credits,
    show_has_current_credits,
):
    """Return whether a show-level TV credit should count for a played episode."""
    if season_has_usable_credits:
        return False
    if not show_has_current_credits:
        return False
    if sort_order is None:
        return True
    return is_usable_tv_show_credit(source, role_type, sort_order)


def _normalize_credit_rows(rows):
    normalized = []
    for row in rows or []:
        person_id = row.get("person_id") or row.get("id")
        if person_id is None:
            continue
        normalized.append(
            {
                "person_id": str(person_id),
                "name": _as_text(row.get("name")),
                "image": _as_text(row.get("image")),
                "known_for_department": _as_text(row.get("known_for_department")),
                "gender": _coerce_gender(row.get("gender")),
                "role": _as_text(
                    row.get("role") or row.get("character") or row.get("job") or ""
                ),
                "department": _as_text(row.get("department")),
                "sort_order": _as_int(
                    row["order"]
                    if "order" in row and row["order"] is not None
                    else row.get("sort_order")
                ),
            },
        )
    return normalized


def _normalize_studio_rows(rows):
    normalized = []
    for row in rows or []:
        studio_id = row.get("studio_id") or row.get("id")
        if studio_id is None:
            continue
        normalized.append(
            {
                "studio_id": str(studio_id),
                "name": _as_text(row.get("name")),
                "logo": _as_text(row.get("logo")),
                "sort_order": _as_int(
                    row["order"]
                    if "order" in row and row["order"] is not None
                    else row.get("sort_order")
                ),
            },
        )
    return normalized


# SQLite caps bound parameters per statement, so IN lists are read in chunks.
_UPSERT_CHUNK_SIZE = 500


def _bulk_upsert(model, id_field, source, fields_by_id):
    """Create or update one ``model`` row per external id; return ``{id: row}``.

    Reads the existing rows once and writes only what changed, instead of an
    ``update_or_create`` (a lock, a read, a savepoint and a write) per row: a
    film with a thousand credits was issuing about 6,000 queries per sync.
    Fields not named in ``fields_by_id`` (a biography, say) are left alone.
    """
    ids = list(fields_by_id)
    rows = {}
    for start in range(0, len(ids), _UPSERT_CHUNK_SIZE):
        chunk = ids[start : start + _UPSERT_CHUNK_SIZE]
        rows.update(
            {
                getattr(row, id_field): row
                for row in model.objects.filter(
                    source=source,
                    **{f"{id_field}__in": chunk},
                )
            },
        )

    to_create = []
    to_update = []
    field_names = []
    for external_id, fields in fields_by_id.items():
        field_names = list(fields)
        row = rows.get(external_id)
        if row is None:
            to_create.append(model(source=source, **{id_field: external_id}, **fields))
        elif any(getattr(row, name) != value for name, value in fields.items()):
            for name, value in fields.items():
                setattr(row, name, value)
            to_update.append(row)

    if to_update:
        model.objects.bulk_update(to_update, field_names, batch_size=_UPSERT_CHUNK_SIZE)
    if to_create:
        # ignore_conflicts does not set primary keys, so read the rows back.
        # It also keeps a concurrent sync that created the same row first from
        # failing this one.
        model.objects.bulk_create(
            to_create,
            ignore_conflicts=True,
            batch_size=_UPSERT_CHUNK_SIZE,
        )
        created_ids = [getattr(row, id_field) for row in to_create]
        for start in range(0, len(created_ids), _UPSERT_CHUNK_SIZE):
            chunk = created_ids[start : start + _UPSERT_CHUNK_SIZE]
            rows.update(
                {
                    getattr(row, id_field): row
                    for row in model.objects.filter(
                        source=source,
                        **{f"{id_field}__in": chunk},
                    )
                },
            )
    return rows


def _replace_person_credits(item, role_types):
    """Delete an item's credits of ``role_types`` before they are re-created.

    Each deleted row would fire its own Discover invalidation (two reads apiece:
    a thousand credits cost two thousand queries), so they are deleted with the
    per-row side effect off and invalidated once. A caller that already
    suppresses the side effects, such as a bulk backfill, does its own.
    """
    from app.signals import (
        invalidate_discover_for_credit_item,
        media_change_side_effects_suppressed,
        suppress_media_change_side_effects,
    )

    already_suppressed = media_change_side_effects_suppressed()
    with suppress_media_change_side_effects():
        deleted, _ = ItemPersonCredit.objects.filter(
            item=item,
            role_type__in=role_types,
        ).delete()
    if deleted and not already_suppressed:
        invalidate_discover_for_credit_item(item)


def _upsert_people(source, credit_rows):
    """Upsert the people named by normalized credit rows; return ``{id: Person}``."""
    return _bulk_upsert(
        Person,
        "source_person_id",
        source,
        {
            row["person_id"]: {
                "name": row["name"] or "Unknown Person",
                "image": row["image"],
                "known_for_department": row["known_for_department"],
                "gender": row["gender"],
            }
            for row in credit_rows
        },
    )


@transaction.atomic
def sync_item_credits_from_metadata(item, metadata, person_source=None):
    """Persist cast/crew and studios for an item from normalized metadata.

    person_source defaults to item.source. Pass it explicitly when the credit
    data comes from a different provider than the item itself (e.g. IMDB cast
    attached to an IGDB-sourced game) so Person/Studio rows aren't tagged with
    the wrong source namespace.
    """
    if not item or not isinstance(metadata, dict):
        return

    person_source = person_source or item.source

    has_people_payload = "cast" in metadata or "crew" in metadata
    has_studio_payload = "studios_full" in metadata

    cast_rows = _normalize_credit_rows(metadata.get("cast", []))
    crew_rows = _normalize_credit_rows(metadata.get("crew", []))
    studio_rows = _normalize_studio_rows(metadata.get("studios_full", []))

    if has_people_payload:
        people_by_source_id = _upsert_people(person_source, cast_rows + crew_rows)

        _replace_person_credits(
            item,
            (CreditRoleType.CAST.value, CreditRoleType.CREW.value),
        )
        credits_to_create = []

        for row in cast_rows:
            person = people_by_source_id.get(row["person_id"])
            if not person:
                continue
            credits_to_create.append(
                ItemPersonCredit(
                    item=item,
                    person=person,
                    role_type=CreditRoleType.CAST.value,
                    role=row["role"],
                    department=row["department"],
                    sort_order=row["sort_order"],
                ),
            )

        for row in crew_rows:
            person = people_by_source_id.get(row["person_id"])
            if not person:
                continue
            credits_to_create.append(
                ItemPersonCredit(
                    item=item,
                    person=person,
                    role_type=CreditRoleType.CREW.value,
                    role=row["role"],
                    department=row["department"],
                    sort_order=row["sort_order"],
                ),
            )

        if credits_to_create:
            ItemPersonCredit.objects.bulk_create(
                credits_to_create, ignore_conflicts=True
            )

    if has_studio_payload:
        studios_by_source_id = _bulk_upsert(
            Studio,
            "source_studio_id",
            person_source,
            {
                row["studio_id"]: {
                    "name": row["name"] or "Unknown Studio",
                    "logo": row["logo"],
                }
                for row in studio_rows
            },
        )

        ItemStudioCredit.objects.filter(item=item).delete()
        studio_links = []
        for row in studio_rows:
            studio = studios_by_source_id.get(row["studio_id"])
            if not studio:
                continue
            studio_links.append(
                ItemStudioCredit(
                    item=item,
                    studio=studio,
                    sort_order=row["sort_order"],
                ),
            )
        if studio_links:
            ItemStudioCredit.objects.bulk_create(studio_links, ignore_conflicts=True)


def _normalize_author_rows(rows):
    normalized = []
    for row in rows or []:
        person_id = row.get("person_id") or row.get("id")
        if person_id is None:
            continue
        normalized.append(
            {
                "person_id": str(person_id),
                "name": _as_text(row.get("name")),
                "image": _as_text(row.get("image")),
                "known_for_department": _as_text(
                    row.get("known_for_department") or row.get("department") or "Author"
                ),
                "gender": _coerce_gender(row.get("gender")),
                "role": _as_text(row.get("role")),
                "department": _as_text(row.get("department")),
                "sort_order": _as_int(
                    row["order"]
                    if "order" in row and row["order"] is not None
                    else row.get("sort_order")
                ),
            },
        )
    return normalized


@transaction.atomic
def sync_item_author_credits(item, authors_full):
    """Persist author credits for an item from normalized metadata."""
    if not item:
        return

    author_rows = _normalize_author_rows(authors_full)
    _replace_person_credits(item, (CreditRoleType.AUTHOR.value,))

    if not author_rows:
        return

    people_by_source_id = _upsert_people(item.source, author_rows)

    credits_to_create = []
    for row in author_rows:
        person = people_by_source_id.get(row["person_id"])
        if not person:
            continue
        credits_to_create.append(
            ItemPersonCredit(
                item=item,
                person=person,
                role_type=CreditRoleType.AUTHOR.value,
                role=row["role"],
                department=row["department"],
                sort_order=row["sort_order"],
            ),
        )

    if credits_to_create:
        ItemPersonCredit.objects.bulk_create(credits_to_create, ignore_conflicts=True)


@transaction.atomic
def upsert_person_profile(source, source_person_id, metadata):
    """Create or update a local person profile from provider metadata."""
    if (
        source not in Sources.values
        or not source_person_id
        or not isinstance(metadata, dict)
    ):
        return None

    person, _ = Person.objects.update_or_create(
        source=source,
        source_person_id=str(source_person_id),
        defaults={
            "name": _as_text(metadata.get("name")) or "Unknown Person",
            "image": _as_text(metadata.get("image")),
            "known_for_department": _as_text(metadata.get("known_for_department")),
            "biography": _as_text(metadata.get("biography")),
            "gender": _coerce_gender(metadata.get("gender")),
            "birth_date": _coerce_iso_date(metadata.get("birth_date")),
            "death_date": _coerce_iso_date(metadata.get("death_date")),
            "place_of_birth": _as_text(metadata.get("place_of_birth")),
        },
    )
    return person
