"""Shared helpers for item-based bulk actions."""

from __future__ import annotations

import logging

from django.apps import apps
from django.db import transaction
from django.middleware.csrf import get_token

from app.models import Item, Media, Status, Tag
from app.services import metadata_resolution

logger = logging.getLogger(__name__)


def posted_item_ids(post_data) -> list[int]:
    """Return unique positive Item ids from a bulk-action request."""
    raw_values = [
        *post_data.getlist("item_ids"),
        *post_data.getlist("item_ids[]"),
    ]
    item_ids = []
    seen = set()
    for raw_value in raw_values:
        try:
            item_id = int(raw_value)
        except (TypeError, ValueError):
            continue
        if item_id > 0 and item_id not in seen:
            seen.add(item_id)
            item_ids.append(item_id)
    return item_ids


def build_bulk_action_data(
    user,
    *,
    request,
    status_url: str,
    list_url: str,
    collection_url: str,
    tag_url: str,
) -> dict:
    """Return JSON-serializable configuration for the bulk-action controller."""
    from lists.models import CustomList

    return {
        "statusUrl": status_url,
        "listUrl": list_url,
        "collectionUrl": collection_url,
        "tagUrl": tag_url,
        "csrfToken": get_token(request),
        "statuses": [
            {"value": value, "label": str(label)}
            for value, label in Status.choices
        ],
        "tags": list(Tag.objects.filter(user=user).order_by("name").values_list("name", flat=True)),
        # Names and ids only. get_user_lists prefetches every Item in every
        # list so the list pages can render their contents; this dropdown
        # renders neither, and on a large library that prefetch was 4,683
        # fully hydrated Items and 654 MiB for a menu of labels. Clearing the
        # prefetches and selecting two columns asks for what is actually used.
        "lists": [
            {"id": list_id, "label": name}
            for list_id, name in CustomList.objects.get_editable_lists(user)
            .filter(is_smart=False)
            .prefetch_related(None)
            .order_by("name")
            .values_list("id", "name")
        ],
    }


def _media_model_for_item(item: Item):
    """Return the item-backed tracking model, or None when it is unsupported."""
    media_type = metadata_resolution.get_tracking_media_type(
        item.media_type,
        source=item.source,
        identity_media_type=item.library_media_type or None,
    )
    try:
        model = apps.get_model("app", media_type)
    except LookupError:
        return None
    if not issubclass(model, Media):
        return None
    return model


def apply_bulk_status(user, item_ids: list[int], status: str) -> dict[str, int]:
    """Apply a status to supported item-backed trackers one item at a time."""
    items_by_id = Item.objects.in_bulk(item_ids)
    result = {"updated": 0, "created": 0, "skipped": 0}

    for item_id in item_ids:
        item = items_by_id.get(item_id)
        if item is None:
            result["skipped"] += 1
            continue

        model = _media_model_for_item(item)
        if model is None:
            result["skipped"] += 1
            continue

        try:
            with transaction.atomic():
                instance = model.objects.filter(user=user, item=item).first()
                created = instance is None
                if created:
                    instance = model(item=item, user=user)
                instance.status = status
                instance.save()
        except Exception:
            logger.exception(
                "Bulk status update failed for item_id=%s media_type=%s user_id=%s",
                item.id,
                item.media_type,
                user.id,
            )
            result["skipped"] += 1
            continue

        result["created" if created else "updated"] += 1

    return result
