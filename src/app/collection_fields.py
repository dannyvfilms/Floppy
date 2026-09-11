"""Schema serialization, validation, and persistence for custom Collection fields.

CollectionEntry.custom_field_values is a JSONField keyed by str(field.id),
so a save here can never delete-and-recreate rows wholesale: any row the
caller identifies by id must be updated in place so its primary key (and
therefore every already-stored value referencing it) stays valid.
"""

from django.db import transaction
from django.utils import timezone

from app.models import (
    CollectionField,
    CollectionFieldGroup,
    CollectionFieldSource,
    CollectionFieldType,
    MediaTypes,
)

MAX_NAME_LENGTH = 100


class CollectionFieldValidationError(Exception):
    """Raised when a submitted custom-field schema payload is invalid."""


class CollectionFieldNotFoundError(Exception):
    """Raised when a payload references a group/field id the user doesn't own."""


def serialize_collection_field_schema(user):
    """Return the user's custom field schema as plain data, ordered by position."""
    groups = CollectionFieldGroup.objects.filter(user=user).prefetch_related("fields")
    provenance = _field_provenance(user)
    return [
        {
            "id": group.id,
            "name": group.name,
            "fields": [
                {
                    "id": field.id,
                    "label": field.label,
                    "field_type": field.field_type,
                    "options": field.options,
                    "media_types": field.media_types,
                    "provenance": provenance.get(field.id, []),
                }
                for field in group.fields.all()
            ],
        }
        for group in groups
    ]


def _field_provenance(user):
    """Map field id -> the import sources that write to it."""
    provenance = {}
    mappings = CollectionFieldSource.objects.filter(user=user).order_by(
        "source",
        "source_key",
    )
    for mapping in mappings:
        provenance.setdefault(mapping.field_id, []).append(
            {
                "source": mapping.source,
                "source_label": mapping.source_label or mapping.source_key,
                "created_field": mapping.created_field,
                "import_run_id": mapping.created_by_import_run_id,
            },
        )
    return provenance


def _clean_str(value, *, field_name, max_length):
    text = str(value or "").strip()
    if not text:
        msg = f"{field_name} is required"
        raise CollectionFieldValidationError(msg)
    if len(text) > max_length:
        msg = f"{field_name} must be {max_length} characters or fewer"
        raise CollectionFieldValidationError(msg)
    return text


def _clean_id(raw_id):
    if raw_id is None or raw_id == "":
        return None
    try:
        return int(raw_id)
    except (TypeError, ValueError):
        msg = "Invalid id"
        raise CollectionFieldValidationError(msg) from None


def _clean_field_payload(raw_field):
    if not isinstance(raw_field, dict):
        msg = "Invalid field payload"
        raise CollectionFieldValidationError(msg)

    field_id = _clean_id(raw_field.get("id"))
    label = _clean_str(
        raw_field.get("label"), field_name="Field label", max_length=MAX_NAME_LENGTH
    )

    field_type = raw_field.get("field_type")
    if field_type not in CollectionFieldType.values:
        msg = f"Invalid field type '{field_type}'"
        raise CollectionFieldValidationError(msg)

    raw_media_types = raw_field.get("media_types")
    if not isinstance(raw_media_types, list):
        msg = "media_types must be a list"
        raise CollectionFieldValidationError(msg)
    media_types = []
    for media_type in raw_media_types:
        if media_type not in MediaTypes.values:
            msg = f"Invalid media type '{media_type}'"
            raise CollectionFieldValidationError(msg)
        if media_type not in media_types:
            media_types.append(media_type)
    if not media_types:
        msg = f"'{label}' needs at least one media type"
        raise CollectionFieldValidationError(msg)

    options = raw_field.get("options") or []
    if field_type == CollectionFieldType.SELECT:
        if isinstance(options, str):
            options = options.splitlines()
        if not isinstance(options, list):
            msg = "options must be a list"
            raise CollectionFieldValidationError(msg)
        options = [str(option).strip() for option in options if str(option).strip()]
    else:
        options = []

    return {
        "id": field_id,
        "label": label,
        "field_type": field_type,
        "options": options,
        "media_types": media_types,
    }


def _clean_group_payload(raw_group):
    if not isinstance(raw_group, dict):
        msg = "Invalid group payload"
        raise CollectionFieldValidationError(msg)

    group_id = _clean_id(raw_group.get("id"))
    name = _clean_str(
        raw_group.get("name"), field_name="Group name", max_length=MAX_NAME_LENGTH
    )

    raw_fields = raw_group.get("fields")
    if not isinstance(raw_fields, list):
        msg = "fields must be a list"
        raise CollectionFieldValidationError(msg)

    return {
        "id": group_id,
        "name": name,
        "fields": [_clean_field_payload(raw_field) for raw_field in raw_fields],
    }


def _clean_schema_payload(payload):
    if not isinstance(payload, dict):
        msg = "Invalid payload"
        raise CollectionFieldValidationError(msg)

    raw_groups = payload.get("groups")
    if not isinstance(raw_groups, list):
        msg = "groups must be a list"
        raise CollectionFieldValidationError(msg)

    cleaned_groups = [_clean_group_payload(raw_group) for raw_group in raw_groups]

    known_field_ids = payload.get("known_field_ids")
    if known_field_ids is not None:
        if not isinstance(known_field_ids, list):
            msg = "known_field_ids must be a list"
            raise CollectionFieldValidationError(msg)
        known_field_ids = {_clean_id(raw_id) for raw_id in known_field_ids}
        known_field_ids.discard(None)

    seen_group_ids = set()
    seen_field_ids = set()
    for group in cleaned_groups:
        if group["id"] is not None:
            if group["id"] in seen_group_ids:
                msg = "Duplicate group id in payload"
                raise CollectionFieldValidationError(msg)
            seen_group_ids.add(group["id"])
        for field in group["fields"]:
            if field["id"] is not None:
                if field["id"] in seen_field_ids:
                    msg = "Duplicate field id in payload"
                    raise CollectionFieldValidationError(msg)
                seen_field_ids.add(field["id"])

    return cleaned_groups, known_field_ids


@transaction.atomic
def save_collection_field_schema(user, payload):
    """Validate and persist a full custom-field schema, preserving row ids.

    Rows carrying an existing id are updated in place. Rows without an id
    are created. Rows the user already owns but that are absent from the
    payload are deleted. Every id in the payload is resolved only against
    the user's own existing rows, so a payload naming another user's row
    raises CollectionFieldNotFoundError rather than touching it.
    """
    cleaned_groups, known_field_ids = _clean_schema_payload(payload)

    existing_groups = {
        group.id: group for group in CollectionFieldGroup.objects.filter(user=user)
    }
    existing_fields = {
        field.id: field for field in CollectionField.objects.filter(group__user=user)
    }

    for group in cleaned_groups:
        if group["id"] is not None and group["id"] not in existing_groups:
            msg = f"Group {group['id']} not found"
            raise CollectionFieldNotFoundError(msg)
        for field in group["fields"]:
            if field["id"] is not None and field["id"] not in existing_fields:
                msg = f"Field {field['id']} not found"
                raise CollectionFieldNotFoundError(msg)

    now = timezone.now()
    seen_group_ids = set()
    groups_to_update = []
    resolved_groups = []

    for position, group in enumerate(cleaned_groups):
        if group["id"] is not None:
            obj = existing_groups[group["id"]]
            obj.name = group["name"]
            obj.position = position
            obj.updated_at = now
            groups_to_update.append(obj)
        else:
            obj = CollectionFieldGroup.objects.create(
                user=user, name=group["name"], position=position
            )
        seen_group_ids.add(obj.id)
        resolved_groups.append((obj, group["fields"]))

    if groups_to_update:
        CollectionFieldGroup.objects.bulk_update(
            groups_to_update, ["name", "position", "updated_at"]
        )

    seen_field_ids = set()
    fields_to_update = []
    fields_to_create = []

    for group_obj, fields in resolved_groups:
        for position, field in enumerate(fields):
            if field["id"] is not None:
                obj = existing_fields[field["id"]]
                obj.group = group_obj
                obj.label = field["label"]
                obj.field_type = field["field_type"]
                obj.options = field["options"]
                obj.media_types = field["media_types"]
                obj.position = position
                obj.updated_at = now
                fields_to_update.append(obj)
                seen_field_ids.add(obj.id)
            else:
                fields_to_create.append(
                    CollectionField(
                        group=group_obj,
                        label=field["label"],
                        field_type=field["field_type"],
                        options=field["options"],
                        media_types=field["media_types"],
                        position=position,
                    )
                )

    if fields_to_update:
        CollectionField.objects.bulk_update(
            fields_to_update,
            [
                "group",
                "label",
                "field_type",
                "options",
                "media_types",
                "position",
                "updated_at",
            ],
        )
    if fields_to_create:
        created_fields = CollectionField.objects.bulk_create(fields_to_create)
        seen_field_ids.update(field.id for field in created_fields)

    stale_field_ids = set(existing_fields) - seen_field_ids
    if known_field_ids is not None:
        # The client can only intend to delete what it was rendered with.
        # Fields created after the form was built (by an import, or another
        # tab) are left alone instead of being wiped by a stale submission.
        stale_field_ids &= known_field_ids
    if stale_field_ids:
        CollectionField.objects.filter(id__in=stale_field_ids, group__user=user).delete()

    stale_group_ids = set(existing_groups) - seen_group_ids
    if known_field_ids is not None:
        # Keep any group that still holds fields the client never saw.
        surviving = set(
            CollectionField.objects.filter(
                group_id__in=stale_group_ids,
            ).values_list("group_id", flat=True),
        )
        stale_group_ids -= surviving
    if stale_group_ids:
        CollectionFieldGroup.objects.filter(id__in=stale_group_ids, user=user).delete()

    return serialize_collection_field_schema(user)
