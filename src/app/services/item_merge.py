"""Merge two `Item` rows that represent the same logical media.

They arise under different provider identities (e.g. a TMDB-sourced show
and its TVDB counterpart). This reuses the repoint strategy from
`app.migrations.0148_merge_duplicate_item_buckets`, which merges `Item`
rows that differ only by `library_media_type`. That migration operates on
frozen historical models inside a data migration; this module is the live
equivalent, callable from request/task code, for merging across `source`
instead of across bucket.

Every relation that FKs `Item` falls into one of two buckets:

- Owned data (playback progress, tags, collection membership, custom list
  membership, feedback, provider-display preference, calendar events,
  cross-provider links) represents a user's choices or a verified mapping.
  It always survives the merge; if the keeper already has an equivalent row,
  the loser's copy is redundant and is dropped rather than merged field by
  field.
- Rebuildable provider metadata (credits, backfill state) regenerates from
  the provider, so a collision on the keeper's side just drops the loser's
  copy.

`TV` and `Season` are unique on `(user, item)` / `(related_tv, item)` and
cascade into `Episode`, so a naive repoint can collide and, on delete,
destroy watch history. They get the same "fold the loser's children onto
the matching survivor row" treatment `0148` uses.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.db.utils import IntegrityError

from app.models import TV, Episode, Item, MediaTypes, Season, Sources
from app.providers import tmdb

logger = logging.getLogger(__name__)


def _relation_key(relation):
    """Return the (app_label, model_name) of a relation's model."""
    meta = relation.related_model._meta
    return (meta.app_label, meta.model_name)


def _absorb_tv_rows(loser: Item, keeper: Item) -> None:
    """Move the loser's TV rows onto the keeper without dropping history."""
    for loser_tv in TV._base_manager.filter(item=loser):
        surviving_tv = (
            TV._base_manager.filter(item=keeper, user_id=loser_tv.user_id)
            .order_by("id")
            .first()
        )
        if surviving_tv is None:
            loser_tv.item = keeper
            loser_tv.save(update_fields=["item_id"])
            continue

        for season in Season._base_manager.filter(related_tv=loser_tv):
            _rehome_season(season, surviving_tv)
        loser_tv.delete()


def _absorb_season_rows(loser: Item, keeper: Item) -> None:
    """Move the loser's Season rows onto the keeper without dropping history."""
    for loser_season in Season._base_manager.filter(item=loser):
        surviving_season = (
            Season._base_manager.filter(
                item=keeper,
                related_tv_id=loser_season.related_tv_id,
            )
            .order_by("id")
            .first()
        )
        if surviving_season is None:
            loser_season.item = keeper
            loser_season.save(update_fields=["item_id"])
            continue

        Episode._base_manager.filter(related_season=loser_season).update(
            related_season=surviving_season,
        )
        loser_season.delete()


def _rehome_season(season: Season, surviving_tv: TV) -> None:
    """Attach one season to another TV row, folding it in if one is there."""
    rival = (
        Season._base_manager.filter(
            related_tv=surviving_tv,
            item_id=season.item_id,
        )
        .order_by("id")
        .first()
    )
    if rival is None:
        season.related_tv = surviving_tv
        season.save(update_fields=["related_tv_id"])
        return

    Episode._base_manager.filter(related_season=season).update(related_season=rival)
    season.delete()


def _repoint(loser: Item, keeper: Item) -> None:
    """Move everything referencing loser onto keeper."""
    for relation in Item._meta.related_objects:
        field = relation.field
        related_manager = relation.related_model._base_manager
        related_name = relation.related_model._meta.model_name

        if field.name == "item" and related_name == "tv":
            _absorb_tv_rows(loser, keeper)
            continue
        if field.name == "item" and related_name == "season":
            _absorb_season_rows(loser, keeper)
            continue

        if relation.many_to_many:
            for related in related_manager.filter(**{field.name: loser}):
                getattr(related, field.name).add(keeper)
                getattr(related, field.name).remove(loser)
            continue

        # Materialised, not an iterator: the save below changes the column
        # the queryset filters on, which can make a streaming cursor skip
        # rows.
        for related in list(related_manager.filter(**{field.name: loser})):
            setattr(related, field.name, keeper)
            try:
                # A savepoint keeps a collision from poisoning the
                # surrounding transaction, so the rest of the merge can
                # still complete.
                with transaction.atomic():
                    related.save(update_fields=[field.attname])
            except IntegrityError:
                # The keeper already has the equivalent row; the loser's
                # copy is redundant.
                related.delete()


def merge_item(loser: Item, keeper: Item) -> None:
    """Fold `loser` into `keeper`: repoint every reference, then delete `loser`.

    `loser` and `keeper` must be different rows. Runs in one transaction: a
    failure partway through leaves both items untouched.
    """
    if loser.pk == keeper.pk:
        msg = "cannot merge an item into itself"
        raise ValueError(msg)

    with transaction.atomic():
        _repoint(loser, keeper)
        loser.delete()

    logger.info(
        "Merged item %s (%s/%s) into %s (%s/%s)",
        loser.pk,
        loser.source,
        loser.media_id,
        keeper.pk,
        keeper.source,
        keeper.media_id,
    )


def resolve_tvdb_id(item: Item) -> str | None:
    """Return the verified TVDB id for a TMDB TV/season item, if resolvable."""
    tvdb_id = (item.provider_external_ids or {}).get("tvdb_id")
    if tvdb_id:
        return str(tvdb_id)
    if item.media_type == MediaTypes.SEASON.value:
        return None
    resolved = tmdb.resolve_tvdb_id_for_tmdb_show(item.media_id)
    return str(resolved) if resolved else None


def find_tvdb_counterpart(
    tmdb_show_id: str,
    media_type: str,
    *,
    season_number: int | None = None,
    library_media_type: str,
) -> Item | None:
    """Return an existing TVDB `Item` for the same logical show/season, if any.

    Resolves the show's TVDB id via TMDB's external-ids lookup - a verified
    provider mapping, never a title guess - then looks for an `Item` already
    tracked under that identity. Scoped to TV/season, since that's the shape
    of the cross-provider duplicate this guards against (#620): an importer
    that only ever supplies TMDB ids creating a second `Item` tree alongside
    one a user already tracks under TVDB.
    """
    if media_type not in (MediaTypes.TV.value, MediaTypes.SEASON.value):
        return None

    resolved = tmdb.resolve_tvdb_id_for_tmdb_show(tmdb_show_id)
    if not resolved:
        return None

    return Item.objects.filter(
        media_id=str(resolved),
        source=Sources.TVDB.value,
        media_type=media_type,
        season_number=season_number,
        library_media_type=library_media_type,
    ).first()


def find_cross_provider_duplicate(item: Item) -> Item | None:
    """Return the verified TVDB counterpart of a TMDB TV/season item, if any.

    Only ever matches on a resolved provider identity (TVDB id), never on
    title - reused titles, localized titles and remakes make title matching
    unsafe. Returns None when the item isn't TMDB TV/season, or no verified
    TVDB counterpart exists.
    """
    if item.source != Sources.TMDB.value:
        return None
    if item.media_type not in (MediaTypes.TV.value, MediaTypes.SEASON.value):
        return None

    if item.media_type == MediaTypes.TV.value:
        tvdb_id = resolve_tvdb_id(item)
    else:
        show_item = Item.objects.filter(
            media_id=item.media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
        ).first()
        tvdb_id = resolve_tvdb_id(show_item) if show_item else None

    if not tvdb_id:
        return None

    return Item.objects.filter(
        media_id=tvdb_id,
        source=Sources.TVDB.value,
        media_type=item.media_type,
        season_number=item.season_number,
        library_media_type=item.library_media_type,
    ).first()


def dedupe_cross_provider_items(items: list[Item], preferred_source: str) -> list[Item]:
    """Collapse TV/season `Item`s that are a verified alias of another in the list.

    Multi-provider imports can leave a TMDB and a TVDB `Item` both tracking
    the same show/season until `app.services.tv_provider_migration` next
    reconciles them (#620), and a user may legitimately track a show under
    both identities on purpose - in which case both trees stay, and only the
    non-preferred one should be hidden from render-time listings (#639).
    This hides the item the user doesn't prefer using only the already-cached
    `provider_external_ids["tvdb_id"]` mapping - never a title match, and
    never a network call, so it can't misfire on unrelated shows and can't
    slow down rendering.
    """
    tvdb_by_key = {
        (
            item.media_id,
            item.media_type,
            item.season_number,
            item.library_media_type,
        ): item
        for item in items
        if item.source == Sources.TVDB.value
        and item.media_type in (MediaTypes.TV.value, MediaTypes.SEASON.value)
    }
    if not tvdb_by_key:
        return items

    hidden_ids = set()
    for item in items:
        if item.source != Sources.TMDB.value or item.media_type not in (
            MediaTypes.TV.value,
            MediaTypes.SEASON.value,
        ):
            continue
        tvdb_id = (item.provider_external_ids or {}).get("tvdb_id")
        if not tvdb_id:
            continue
        counterpart = tvdb_by_key.get(
            (
                str(tvdb_id),
                item.media_type,
                item.season_number,
                item.library_media_type,
            ),
        )
        if counterpart is None:
            continue
        loser = item if preferred_source == Sources.TVDB.value else counterpart
        hidden_ids.add(loser.id)

    if not hidden_ids:
        return items
    return [item for item in items if item.id not in hidden_ids]
