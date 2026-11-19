"""Give every item a library bucket, folding empty-bucket twins into their match.

An item's identity includes its library bucket (``library_media_type``).
``Item.save()`` fills an empty bucket with the media type, but ``bulk_create``
and ``QuerySet.update`` skip ``save()``, and until 0231 the database accepted
the empty string. So one title could be stored twice: once with an empty
bucket and once with its media type. Plain lookups then raise
``MultipleObjectsReturned``, and plays, ratings or list membership end up on
the copy a page is not showing.

For each item with an empty bucket:

- if no other item has the same identity, its bucket becomes its media type,
  which is what ``save()`` would have stored;
- otherwise it is folded into that twin with the rules of
  ``app.services.item_merge.merge_item`` (prompt 66): everything pointing at
  it moves to the twin, and where one person tracked both, the duplicate
  tracking row's score, notes, dates and status are folded into the
  surviving row before it is deleted. Nothing is lowered and nothing is
  overwritten.

The live service cannot run here (migrations use frozen models, and later
model changes must not change what this migration does), so its rules are
restated below against the frozen models, the way 0148 restated its own.

Grouped anime rows (bucket ``anime`` on a ``tv`` item) and every other filled
bucket are left alone. Which filled bucket episodes and seasons belong in is
a separate question (prompt 64).

Frozen models send no signals, so the watch-state projection of a surviving
item is not recomputed here; ``app.tasks_watch_state.REPAIR_VERSION`` was
bumped with this migration so the background repair recomputes it from the
plays (it writes no change records and sends nothing to connected services).

The migration is not atomic: each batch of fills and each merge commits on
its own, so the SQLite writer is never held for the whole run, and an
interrupted run resumes where it stopped. On a database with no empty bucket
it is one query. 0231 then makes the database refuse an empty bucket.
"""

from django.db import migrations, transaction
from django.db.models import F
from django.db.utils import IntegrityError
from django.utils import timezone

BATCH_SIZE = 500

IDENTITY_FIELDS = (
    "media_id",
    "source",
    "media_type",
    "season_number",
    "episode_number",
)

# Rows recording that a user tracks an item; they decide which twin survives.
TRACKING_MODELS = {
    "basicmedia",
    "manga",
    "anime",
    "movie",
    "game",
    "boardgame",
    "book",
    "comic",
    "comicissue",
    "music",
    "podcast",
    "tv",
    "season",
    "episode",
    "video",
}

# Status order for the fold (frozen copy of app.services.tracker_fold).
PLANNING = "Planning"
STATUS_RANK = {None: 0, "": 0, PLANNING: 1, "In progress": 2, "Completed": 3}
USER_HELD_STATUSES = frozenset({"Dropped", "Paused"})
MERGE_CHANGE_REASON = "Merged duplicate entry"
REASON_MAX_LENGTH = 100


def _empty(value):
    return value is None or value == ""


def _folded_status(survivor_status, other_status):
    """Return the status to keep, and whether the other one was set aside."""
    if survivor_status == other_status or _empty(other_status):
        return survivor_status, False
    if survivor_status in USER_HELD_STATUSES:
        return survivor_status, True
    if other_status in USER_HELD_STATUSES:
        if STATUS_RANK.get(survivor_status, 0) <= STATUS_RANK[PLANNING]:
            return other_status, False
        return survivor_status, True
    if STATUS_RANK.get(other_status, 0) > STATUS_RANK.get(survivor_status, 0):
        return other_status, False
    return survivor_status, True


def _fold_fields(other, survivor):
    """Fold ``other``'s user-owned fields into ``survivor`` in memory."""
    names = {field.name for field in survivor._meta.concrete_fields}
    changed = []
    set_aside = []

    def take(name, value):
        setattr(survivor, name, value)
        changed.append(name)

    if "status" in names:
        status, discarded = _folded_status(survivor.status, other.status)
        if status != survivor.status:
            take("status", status)
        elif discarded:
            set_aside.append(f"other status {other.status}")

    if "score" in names and other.score is not None:
        if survivor.score is None:
            take("score", other.score)
            if "scored_at" in names:
                take("scored_at", other.scored_at or timezone.now())
        elif survivor.score != other.score:
            set_aside.append(f"other score {other.score}")

    if "progress" in names and (other.progress or 0) > (survivor.progress or 0):
        take("progress", other.progress)

    if (
        "start_date" in names
        and other.start_date is not None
        and (survivor.start_date is None or other.start_date < survivor.start_date)
    ):
        take("start_date", other.start_date)

    if (
        "end_date" in names
        and other.end_date is not None
        and (survivor.end_date is None or other.end_date > survivor.end_date)
    ):
        take("end_date", other.end_date)

    if "notes" in names:
        other_notes = (other.notes or "").strip()
        survivor_notes = (survivor.notes or "").strip()
        if other_notes and other_notes != survivor_notes:
            take(
                "notes",
                f"{survivor.notes}\n\n{other.notes}" if survivor_notes else other.notes,
            )

    if "entry_source" in names and not survivor.entry_source and other.entry_source:
        take("entry_source", other.entry_source)

    return changed, set_aside


def _history_model(apps, model):
    try:
        return apps.get_model(model._meta.app_label, f"Historical{model.__name__}")
    except LookupError:
        return None


def _fold_tracker_into(apps, other, survivor):
    """Fold ``other`` into ``survivor``, write it, and record why in its history."""
    changed, set_aside = _fold_fields(other, survivor)
    model = type(survivor)
    names = {field.name for field in model._meta.concrete_fields}
    fields = list(dict.fromkeys(changed))
    if "updated_at" in names:
        survivor.updated_at = timezone.now()
        fields.append("updated_at")
    if fields:
        model._base_manager.filter(pk=survivor.pk).update(
            **{name: getattr(survivor, name) for name in fields},
        )

    history = _history_model(apps, model)
    if history is None:
        return
    reason = MERGE_CHANGE_REASON
    if set_aside:
        reason = f"{MERGE_CHANGE_REASON} ({', '.join(set_aside)})"
        if len(reason) > REASON_MAX_LENGTH:
            reason = reason[: REASON_MAX_LENGTH - 1] + ")"
    values = {
        field.attname: getattr(survivor, field.attname)
        for field in model._meta.concrete_fields
    }
    history_names = {field.attname for field in history._meta.concrete_fields}
    row = history(
        **{name: value for name, value in values.items() if name in history_names},
        history_date=timezone.now(),
        history_type="~",
        history_change_reason=reason,
    )
    if "history_user_id" in history_names:
        row.history_user_id = getattr(survivor, "user_id", None)
    row.save()


def _move_children(row, twin):
    """Move rows that cascade from ``row`` (plays, links) onto ``twin``."""
    for relation in type(row)._meta.related_objects:
        if relation.many_to_many or relation.one_to_one:
            continue
        field = relation.field
        manager = relation.related_model._base_manager
        for child in list(manager.filter(**{field.name: row})):
            setattr(child, field.name, twin)
            try:
                with transaction.atomic():
                    child.save(update_fields=[field.attname])
            except IntegrityError:
                child.delete()


def _is_tracking(model):
    names = {field.name for field in model._meta.concrete_fields}
    return model._meta.model_name in TRACKING_MODELS and {"user", "item"} <= names


def _fold_media_twin(apps, related, field_name, keeper):
    """Keep a colliding tracking row's user fields on the keeper's twin."""
    if field_name != "item" or not _is_tracking(type(related)):
        return
    twin = (
        type(related)
        ._base_manager.filter(user_id=related.user_id, item=keeper)
        .exclude(pk=related.pk)
        .order_by("id")
        .first()
    )
    if twin is None:
        return
    _fold_tracker_into(apps, related, twin)
    _move_children(related, twin)


def _keeper_has_equivalent(related, field_name):
    """Return whether a unique constraint already holds this row's twin on the keeper."""
    model = type(related)
    for constraint in model._meta.constraints:
        fields = getattr(constraint, "fields", ())
        if field_name not in fields or getattr(constraint, "condition", None):
            continue
        lookup = {name: getattr(related, name) for name in fields}
        if model._base_manager.filter(**lookup).exclude(pk=related.pk).exists():
            return True
    return False


def _rehome_season(apps, season, surviving_tv, season_model, episode_model):
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
    _fold_tracker_into(apps, season, rival)
    season.delete()


def _absorb_tv_rows(apps, loser, keeper, models):
    """Move the loser's TV rows onto the keeper without dropping history."""
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
            _rehome_season(apps, season, surviving_tv, season_model, episode_model)
        _fold_tracker_into(apps, loser_tv, surviving_tv)
        loser_tv.delete()


def _absorb_season_rows(apps, loser, keeper, models):
    """Move the loser's Season rows onto the keeper without dropping history."""
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
        _fold_tracker_into(apps, loser_season, surviving_season)
        loser_season.delete()


def _repoint(apps, item_model, loser, keeper, models):
    """Move everything referencing ``loser`` onto ``keeper``."""
    for relation in item_model._meta.related_objects:
        field = relation.field
        related_manager = relation.related_model._base_manager
        related_name = relation.related_model._meta.model_name

        if field.name == "item" and related_name == "tv":
            _absorb_tv_rows(apps, loser, keeper, models)
            continue
        if field.name == "item" and related_name == "season":
            _absorb_season_rows(apps, loser, keeper, models)
            continue

        if relation.many_to_many:
            for related in related_manager.filter(**{field.name: loser}):
                getattr(related, field.name).add(keeper)
                getattr(related, field.name).remove(loser)
            continue

        # Materialised: the save changes the column the queryset filters on.
        for related in list(related_manager.filter(**{field.name: loser})):
            setattr(related, field.name, keeper)
            if _keeper_has_equivalent(related, field.name):
                _fold_media_twin(apps, related, field.name, keeper)
                related.delete()
                continue
            try:
                with transaction.atomic():
                    related.save(update_fields=[field.attname])
            except IntegrityError:
                _fold_media_twin(apps, related, field.name, keeper)
                related.delete()


def _tracking_count(item_model, item):
    total = 0
    for relation in item_model._meta.related_objects:
        if relation.many_to_many or relation.field.name != "item":
            continue
        if _is_tracking(relation.related_model):
            total += relation.related_model._base_manager.filter(item=item).count()
    return total


def _pick_keeper(item_model, empty_item, twins):
    """Choose the twin to fold into: most tracking rows, then the media type's own bucket."""
    return max(
        twins,
        key=lambda twin: (
            _tracking_count(item_model, twin),
            twin.library_media_type == empty_item.media_type,
            -twin.pk,
        ),
    )


def _identity(item):
    return tuple(getattr(item, name) for name in IDENTITY_FIELDS)


def fill_empty_item_buckets(apps, schema_editor):
    """Fill or fold every item stored with an empty library bucket."""
    del schema_editor
    item_model = apps.get_model("app", "Item")
    models = (
        apps.get_model("app", "TV"),
        apps.get_model("app", "Season"),
        apps.get_model("app", "Episode"),
    )
    empty = item_model._base_manager.filter(library_media_type="")

    last_id = 0
    while True:
        batch = list(empty.filter(pk__gt=last_id).order_by("pk")[:BATCH_SIZE])
        if not batch:
            return
        last_id = batch[-1].pk

        twins_by_identity = {}
        for twin in (
            item_model._base_manager.filter(
                media_id__in={item.media_id for item in batch},
                media_type__in={item.media_type for item in batch},
            )
            .exclude(library_media_type="")
            .order_by("pk")
        ):
            twins_by_identity.setdefault(_identity(twin), []).append(twin)

        fill_ids = []
        for item in batch:
            twins = twins_by_identity.get(_identity(item))
            if not twins:
                fill_ids.append(item.pk)
                continue
            keeper = _pick_keeper(item_model, item, twins)
            with transaction.atomic():
                _repoint(apps, item_model, item, keeper, models)
                item.delete()

        if fill_ids:
            with transaction.atomic():
                item_model._base_manager.filter(
                    pk__in=fill_ids,
                    library_media_type="",
                ).update(library_media_type=F("media_type"))


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("app", "0229_podcast_show_url_derived_titles"),
    ]

    operations = [
        migrations.RunPython(
            fill_empty_item_buckets,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
