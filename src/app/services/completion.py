"""Helpers for normalizing planned activity when an item is completed."""

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


def prepare_completed_entry(instance):
    """Merge missing metadata and return planning rows to remove after save."""
    if (
        getattr(instance, "status", None) != Status.COMPLETED.value
        or not _is_normalizable(instance)
    ):
        return [], set()

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


def normalize_completed_entry(instance):
    """Normalize a completed row persisted by a bulk operation."""
    if getattr(instance, "pk", None) is None:
        return

    planning_entries, merged_fields = prepare_completed_entry(instance)
    if not planning_entries:
        return

    if merged_fields:
        instance.__class__._default_manager.filter(pk=instance.pk).update(
            **{field: getattr(instance, field) for field in merged_fields},
        )
    finalize_completed_entry(planning_entries)


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
