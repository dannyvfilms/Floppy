"""Merge Item rows that differ only by their library_media_type bucket.

0118 added ``library_media_type`` to all three Item uniqueness constraints, so
the same media identity became storable twice - once in the bucket the tracking
pages use (e.g. 'tv' for a show's episodes) and once in the default bucket
('episode'). Callers keyed on the identity fields alone, notably the Sonarr
importer, then created that second row instead of finding the first. The split
left collection ownership attached to a row the rest of the app never looks at,
and once both rows existed the next import crashed with MultipleObjectsReturned.

0125 cleaned up one flavour of this (stray ('episode','season') rows). This
migration handles the general case: any identity carrying more than one row is
folded onto a single survivor, everything referencing the losers is repointed,
and the losers are deleted. Rebuildable provider metadata (person credits,
backfill state) that would collide on the survivor is dropped rather than
merged, since it regenerates.

The surviving bucket is chosen per title rather than per row. A per-row choice
keeps one episode of a season on 'tv' and the next on 'episode' purely because
of insertion order, which is the same split this migration exists to undo.

Only duplicated identities are touched. Single rows sitting in a non-canonical
bucket are left alone: they resolve fine today, and re-bucketing them would
move rows the app currently finds.
"""

from collections import defaultdict

from django.db import migrations, transaction
from django.db.models import Count
from django.db.utils import IntegrityError

IDENTITY_FIELDS = (
    "media_id",
    "source",
    "media_type",
    "season_number",
    "episode_number",
)

MIN_GROUP_SIZE = 2

# Rows recording that the user tracks this item. These decide which bucket
# survives: they are what the tracking pages, statistics and exports resolve.
TRACKING_MODELS = {
    ("app", "basicmedia"),
    ("app", "manga"),
    ("app", "anime"),
    ("app", "movie"),
    ("app", "game"),
    ("app", "boardgame"),
    ("app", "book"),
    ("app", "comic"),
    ("app", "comicissue"),
    ("app", "music"),
    ("app", "podcast"),
    ("app", "tv"),
    ("app", "season"),
    ("app", "episode"),
}

# Other things a user created or chose, as opposed to provider metadata the app
# can refetch. These break ties and move onto the survivor either way.
OWNED_MODELS = {
    ("app", "collectionentry"),
    ("app", "itemtag"),
    ("app", "playbackprogress"),
    ("app", "discoverfeedback"),
    ("integrations", "collectionsourcestate"),
    ("integrations", "plexwatchlistsyncitem"),
    ("events", "event"),
    ("lists", "customlist"),
    ("lists", "customlistitem"),
}


def _relation_key(relation):
    """Return the (app_label, model_name) of a relation's model."""
    meta = relation.related_model._meta
    return (meta.app_label, meta.model_name)


def _count(item, relations):
    """Count rows on this item across the given reverse relations."""
    total = 0
    for relation in relations:
        total += (
            relation.related_model._base_manager.filter(
                **{relation.field.name: item},
            ).count()
        )
    return total


def _absorb_tv_rows(loser, keeper, models):
    """Move the loser's TV rows onto the keeper without dropping history.

    TV is unique on (user, item), so a plain repoint collides whenever the
    same user tracks both duplicates - and TV cascades through Season into
    Episode, so deleting on that collision destroys watch history. Hand the
    loser's seasons to the surviving TV row first, then delete the row once
    it owns nothing.
    """
    tv_model, season_model, episode_model = models
    for loser_tv in tv_model._base_manager.filter(item=loser):
        surviving_tv = (
            tv_model._base_manager.filter(item=keeper, user_id=loser_tv.user_id)
            .order_by("id")
            .first()
        )
        if surviving_tv is None:
            loser_tv.item = keeper
            loser_tv.save(update_fields=["item_id"])
            continue

        for season in season_model._base_manager.filter(related_tv=loser_tv):
            _rehome_season(season, surviving_tv, season_model, episode_model)
        loser_tv.delete()


def _absorb_season_rows(loser, keeper, models):
    """Move the loser's Season rows onto the keeper without dropping history.

    Season is unique on (related_tv, item) and cascades into Episode, so the
    same reasoning as _absorb_tv_rows applies one level down.
    """
    _tv_model, season_model, episode_model = models
    for loser_season in season_model._base_manager.filter(item=loser):
        surviving_season = (
            season_model._base_manager.filter(
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

        episode_model._base_manager.filter(related_season=loser_season).update(
            related_season=surviving_season,
        )
        loser_season.delete()


def _rehome_season(season, surviving_tv, season_model, episode_model):
    """Attach one season to another TV row, folding it in if one is there."""
    rival = (
        season_model._base_manager.filter(
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

    episode_model._base_manager.filter(related_season=season).update(
        related_season=rival,
    )
    season.delete()


def _repoint(item_model, loser, keeper, models):
    """Move everything referencing loser onto keeper."""
    for relation in item_model._meta.related_objects:
        field = relation.field
        related_manager = relation.related_model._base_manager
        related_name = relation.related_model._meta.model_name

        # TV and Season cascade into Episode, so they cannot fall through to
        # the delete-on-conflict branch below. Episode itself has no unique
        # constraint, so its repoint always succeeds and needs no special case.
        if field.name == "item" and related_name == "tv":
            _absorb_tv_rows(loser, keeper, models)
            continue
        if field.name == "item" and related_name == "season":
            _absorb_season_rows(loser, keeper, models)
            continue

        if relation.many_to_many:
            # 0125 predates the m2m relations on Item and did not handle them.
            for related in related_manager.filter(**{field.name: loser}):
                getattr(related, field.name).add(keeper)
                getattr(related, field.name).remove(loser)
            continue

        # Materialised, not an iterator: the save below changes the column the
        # queryset filters on, which can make a streaming cursor skip rows.
        for related in list(related_manager.filter(**{field.name: loser})):
            setattr(related, field.name, keeper)
            try:
                # A savepoint keeps a collision from poisoning the surrounding
                # transaction, so the rest of the group can still be merged.
                with transaction.atomic():
                    related.save(update_fields=[field.attname])
            except IntegrityError:
                # The keeper already has the equivalent row; the loser's copy
                # is redundant provider metadata.
                related.delete()


def merge_duplicate_item_buckets(apps, schema_editor):
    """Fold every duplicated Item identity onto a single row."""
    del schema_editor
    Item = apps.get_model("app", "Item")
    models = (
        apps.get_model("app", "TV"),
        apps.get_model("app", "Season"),
        apps.get_model("app", "Episode"),
    )

    tracking_relations = [
        relation
        for relation in Item._meta.related_objects
        if _relation_key(relation) in TRACKING_MODELS
    ]
    owned_relations = [
        relation
        for relation in Item._meta.related_objects
        if _relation_key(relation) in OWNED_MODELS
    ]

    duplicate_groups = _duplicate_groups(Item)
    if not duplicate_groups:
        return

    weights = _bucket_weights(duplicate_groups, tracking_relations, owned_relations)

    for items in duplicate_groups:
        scope = (items[0].media_id, items[0].source, items[0].media_type)
        keeper = _pick_keeper(
            items,
            weights.get(scope),
            tracking_relations,
            owned_relations,
        )
        for loser in items:
            if loser.pk == keeper.pk:
                continue
            _repoint(Item, loser, keeper, models)
            loser.delete()


def _duplicate_groups(item_model):
    """Return the Item rows of every identity that has more than one row.

    Two queries rather than a full materialisation of the table: the aggregate
    finds the duplicated identities, then one fetch pulls back only the rows
    belonging to them.
    """
    duplicate_keys = {
        tuple(row[field] for field in IDENTITY_FIELDS)
        for row in item_model.objects.values(*IDENTITY_FIELDS)
        .annotate(row_count=Count("id"))
        .filter(row_count__gte=MIN_GROUP_SIZE)
    }
    if not duplicate_keys:
        return []

    groups = defaultdict(list)
    media_ids = {key[0] for key in duplicate_keys}
    for item in item_model.objects.filter(media_id__in=media_ids).order_by("id"):
        key = tuple(getattr(item, field) for field in IDENTITY_FIELDS)
        if key in duplicate_keys:
            groups[key].append(item)

    return list(groups.values())


def _bucket_weights(duplicate_groups, tracking_relations, owned_relations):
    """Return the winning bucket per title, or None where nothing decides it."""
    tallies = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for items in duplicate_groups:
        for item in items:
            scope = (item.media_id, item.source, item.media_type)
            tally = tallies[scope][item.library_media_type]
            tally[0] += _count(item, tracking_relations)
            tally[1] += _count(item, owned_relations)

    preferred = {}
    for scope, buckets in tallies.items():
        if not any(any(tally) for tally in buckets.values()):
            # Nothing to go on; leave the choice to the per-group fallback.
            continue
        preferred[scope] = max(buckets, key=lambda bucket: buckets[bucket])
    return preferred


def _pick_keeper(items, preferred_bucket, tracking_relations, owned_relations):
    """Return the row the rest of the group should collapse onto."""
    candidates = [
        item for item in items if item.library_media_type == preferred_bucket
    ]
    # Prefer the title's tracked bucket, but never at the cost of losing a row's
    # own tracking history to a bucket that has none in this group.
    if candidates and not any(
        _count(item, tracking_relations)
        for item in items
        if item.pk not in {candidate.pk for candidate in candidates}
    ):
        items = candidates

    return max(
        items,
        key=lambda item: (
            _count(item, tracking_relations),
            _count(item, owned_relations),
            -item.pk,
        ),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0146_backfill_reconcile_state"),
    ]

    operations = [
        migrations.RunPython(
            merge_duplicate_item_buckets,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
