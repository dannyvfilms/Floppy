"""Helpers for normalizing planned activity when an item is completed."""

from collections import defaultdict

from django.apps import apps
from django.db.models import Case, IntegerField, Value, When

from app.models.choices import MediaTypes, Status

_NORMALIZABLE_MEDIA_TYPES = set(MediaTypes.values) - {
    MediaTypes.TV.value,
    MediaTypes.SEASON.value,
}
_PENDING_STATUSES = (
    Status.PLANNING.value,
    Status.IN_PROGRESS.value,
)
PLANNING_PREFETCH_BATCH_SIZE = 500


def _is_normalizable(instance):
    """Return whether an instance is an item-level activity record."""
    return (
        getattr(instance, "_meta", None) is not None
        and instance._meta.model_name in _NORMALIZABLE_MEDIA_TYPES
    )


def _owner_filter(instance):
    """Return the user scope for a media or episode instance."""
    if instance._meta.model_name != MediaTypes.EPISODE.value:
        user_id = getattr(instance, "user_id", None)
        return {"user_id": user_id} if user_id is not None else None

    season_model = apps.get_model("app", "Season")
    user_id = (
        season_model.objects.filter(pk=instance.related_season_id)
        .values_list("related_tv__user_id", flat=True)
        .first()
    )
    return (
        {"related_season__related_tv__user_id": user_id}
        if user_id is not None
        else None
    )


def _planning_entries(instance):
    """Return planning entries for the same user and underlying item."""
    if not _is_normalizable(instance) or not getattr(instance, "item_id", None):
        return []

    owner_filter = _owner_filter(instance)
    if owner_filter is None:
        return []

    filters = {
        **owner_filter,
        "item_id": instance.item_id,
        "status": Status.PLANNING.value,
    }
    queryset = instance.__class__._default_manager.filter(**filters)
    if getattr(instance, "pk", None) is not None:
        queryset = queryset.exclude(pk=instance.pk)
    return list(queryset.order_by("-created_at", "-pk"))


def prepare_completed_entry(instance, *, planning_entries=None):
    """Merge missing metadata and return planning rows to remove after save."""
    if (
        getattr(instance, "status", None) != Status.COMPLETED.value
        or not _is_normalizable(instance)
    ):
        return [], set()

    if planning_entries is None:
        planning_entries = _planning_entries(instance)
    if not planning_entries:
        return [], set()

    merged_fields = set()
    if getattr(instance, "score", None) is None:
        score = next(
            (
                entry.score
                for entry in planning_entries
                if getattr(entry, "score", None) is not None
            ),
            None,
        )
        if score is not None:
            instance.score = score
            merged_fields.add("score")

    if not (getattr(instance, "notes", None) or "").strip():
        notes = next(
            (
                entry.notes
                for entry in planning_entries
                if (getattr(entry, "notes", None) or "").strip()
            ),
            None,
        )
        if notes:
            instance.notes = notes
            merged_fields.add("notes")

    return planning_entries, merged_fields


def finalize_completed_entry(planning_entries):
    """Delete stale planning rows through normal model deletion signals."""
    for planning_entry in planning_entries:
        planning_entry.delete()


def normalize_completed_entry(instance, *, planning_entries=None):
    """Normalize a completed row persisted by a bulk operation."""
    if getattr(instance, "pk", None) is None:
        return

    planning_entries, merged_fields = prepare_completed_entry(
        instance, planning_entries=planning_entries,
    )
    if not planning_entries:
        return

    if merged_fields:
        instance.__class__._default_manager.filter(pk=instance.pk).update(
            **{field: getattr(instance, field) for field in merged_fields},
        )
    finalize_completed_entry(planning_entries)


def normalize_completed_entries(instances):
    """Preload planning state once for one persisted media-type batch.

    Keep persistence order: the first completed watch receives planning metadata
    and deletes those plans through the same model hooks as individual saves.
    Later watches must not inherit metadata from already removed plans.
    """
    completed = [
        row for row in instances
        if row.pk is not None and row.status == Status.COMPLETED.value
        and _is_normalizable(row) and row.item_id is not None
    ]
    if not completed:
        return
    model = completed[0].__class__
    episode = model._meta.model_name == MediaTypes.EPISODE.value
    if episode:
        season_model = apps.get_model("app", "Season")
        season_ids = list({row.related_season_id for row in completed})
        owners = {}
        for start in range(0, len(season_ids), PLANNING_PREFETCH_BATCH_SIZE):
            owners.update(season_model.objects.filter(
                pk__in=season_ids[start : start + PLANNING_PREFETCH_BATCH_SIZE],
            ).values_list("pk", "related_tv__user_id"))
    items_by_owner = defaultdict(set)
    for row in completed:
        owner_id = owners.get(row.related_season_id) if episode else row.user_id
        if owner_id is not None:
            items_by_owner[owner_id].add(row.item_id)
    by_identity = defaultdict(list)
    owner_lookup = "related_season__related_tv__user_id" if episode else "user_id"
    for owner_id, ids in items_by_owner.items():
        item_ids = list(ids)
        for start in range(0, len(item_ids), PLANNING_PREFETCH_BATCH_SIZE):
            plans = model._default_manager.filter(
                **{owner_lookup: owner_id},
                item_id__in=item_ids[start : start + PLANNING_PREFETCH_BATCH_SIZE],
                status=Status.PLANNING.value,
            ).order_by("-created_at", "-pk")
            for plan in plans:
                by_identity[owner_id, plan.item_id].append(plan)
    for row in completed:
        owner_id = owners.get(row.related_season_id) if episode else row.user_id
        normalize_completed_entry(
            row, planning_entries=by_identity.pop((owner_id, row.item_id), []),
        )


def select_preferred_activity_entry(queryset):
    """Select pending activity before older completed activity rows."""
    return (
        queryset.annotate(
            _pending_priority=Case(
                When(status__in=_PENDING_STATUSES, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            ),
        )
        .order_by("_pending_priority", "-created_at", "-pk")
        .first()
    )
