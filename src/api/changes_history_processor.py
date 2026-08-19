from django.apps import apps

from app.models import MediaTypes

EXCLUDED_FIELDS = {"id", "item", "user", "related_tv", "related_season"}


def delete_changes_history_entry(media_type, history_id, user):
    """Delete a history entry for a given media type and user."""
    historical_model = apps.get_model(
        app_label="app",
        model_name=f"historical{media_type.lower()}",
    )

    historical_model.objects.get(
        history_id=history_id,
        history_user=user,
    ).delete()


def get_changes_history_entry(media_type, history_id, user):
    """Retrieve an history entry for a given media type and user."""
    historical_model = apps.get_model(
        app_label="app",
        model_name=f"historical{media_type.lower()}",
    )

    record = historical_model.objects.get(
        history_id=history_id,
        history_user=user,
    )

    media_model = apps.get_model("app", media_type)
    media_instance = media_model.objects.get(id=record.id)

    record.item_obj = media_instance.item
    return record


def get_changes_history_entries(user_medias, media_type):
    """Get all raw historical records for given user medias."""
    entries = []

    for media in user_medias:
        history_records = media.history.all()
        if not history_records:
            continue

        last = history_records.first()
        while last:
            if last.prev_record:
                delta = last.diff_against(last.prev_record)
                has_changes = any(
                    _should_include_field(change.field, media_type)
                    for change in delta.changes
                )
            else:
                has_changes = True

            if has_changes:
                last.item_obj = media.item
                entries.append(last)

            last = last.prev_record

    return entries


def get_changes_from_diff(new_record, old_record, media_type):
    """Extract changes from diff between two records."""
    delta = new_record.diff_against(old_record)
    return [
        {
            "field": change.field,
            "old_value": change.old,
            "new_value": change.new,
        }
        for change in delta.changes
        if _should_include_field(change.field, media_type)
    ]


def get_changes_from_new_record(new_record, media_type):
    """Extract changes from a new record (no previous record)."""
    changes = []
    for field in new_record._meta.fields:
        if _should_include_field(field.name, media_type):
            value = getattr(new_record, field.name, None)
            if value is not None:
                changes.append(
                    {
                        "field": field.name,
                        "old_value": None,
                        "new_value": value,
                    },
                )
    return changes


def _should_include_field(field_name, media_type):
    """Check if a field should be included in the history entry."""
    if field_name.startswith("history_"):
        return False
    if field_name in EXCLUDED_FIELDS:
        return False
    return not (field_name == "progress" and media_type == MediaTypes.MOVIE.value)
